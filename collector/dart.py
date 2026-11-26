"""DART OpenAPI: 확정 실적, 희석 요소(CB/BW/유상증자), 최대주주 지분.

API 키는 환경변수 DART_API_KEY 로만 받는다(코드·저장소에 넣지 않음).
키가 없으면 DART 항목은 전부 N/A 로 남고 나머지 수집은 계속 진행한다.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from .util import get, log, to_num

BASE = "https://opendart.fss.or.kr/api"
REPRT = {"11011": "사업보고서", "11014": "3분기보고서", "11012": "반기보고서", "11013": "1분기보고서"}


class Dart:
    def __init__(self, sess, cache_dir: Path):
        self.key = os.environ.get("DART_API_KEY", "").strip()
        self.sess = sess
        self.cache_dir = cache_dir
        self._corp: dict[str, str] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _call(self, name: str, **params) -> dict:
        params["crtfc_key"] = self.key
        r = get(self.sess, f"{BASE}/{name}.json", params=params, sleep=0.15)
        js = r.json()
        st = js.get("status")
        if st == "013":  # 조회된 데이터 없음
            return {"list": []}
        if st != "000":
            raise RuntimeError(f"DART {name}: {st} {js.get('message')}")
        return js

    # ------------------------------------------------------------ 고유번호
    def corp_code(self, stock_code: str) -> str | None:
        if self._corp is None:
            self._corp = self._load_corp_codes()
        return self._corp.get(stock_code)

    def _load_corp_codes(self) -> dict[str, str]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache = self.cache_dir / "dart_corp_codes.json"
        if cache.exists() and (datetime.now().timestamp() - cache.stat().st_mtime) < 7 * 86400:
            return json.loads(cache.read_text(encoding="utf-8"))
        r = get(self.sess, f"{BASE}/corpCode.xml", params={"crtfc_key": self.key}, timeout=60)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0])
        root = ET.fromstring(xml)
        m = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc:
                m[sc] = el.findtext("corp_code").strip()
        cache.write_text(json.dumps(m), encoding="utf-8")
        return m

    # ------------------------------------------------------------ 확정 실적
    def financials(self, corp: str, today: datetime) -> dict:
        """가장 최근 사업보고서(연간) 주요 계정 + 최근 분기 부채비율."""
        out: dict = {}
        for y in (today.year - 1, today.year - 2):
            rows = self._call("fnlttSinglAcnt", corp_code=corp, bsns_year=str(y), reprt_code="11011").get("list", [])
            if rows:
                out["annual"] = {"year": y, **_accounts(rows)}
                break
        # 최근 분기 기준 부채비율
        for y, rc in _recent_reports(today):
            rows = self._call("fnlttSinglAcnt", corp_code=corp, bsns_year=str(y), reprt_code=rc).get("list", [])
            if rows:
                acc = _accounts(rows)
                if acc.get("liabilities") is not None and acc.get("equity"):
                    out["debt_ratio"] = acc["liabilities"] / acc["equity"] * 100
                    out["debt_ratio_basis"] = f"{y} {REPRT[rc]}"
                break
        return out

    # ------------------------------------------------------------ 희석 요소
    def dilution(self, corp: str, today: datetime, cb_years: int, rights_years: int) -> dict:
        end = today.strftime("%Y%m%d")
        events = []
        potential_pct = 0.0
        for api, kind, cnt_key, pct_key, amt_key, price_key in (
            ("cvbdIsDecsn", "CB(전환사채)", "cvisstk_cnt", "cvisstk_tisstk_vs", "bd_fta", "cv_prc"),
            ("bdwtIsDecsn", "BW(신주인수권부사채)", "nstk_isstk_cnt", "nstk_isstk_tisstk_vs", "bd_fta", "ex_prc"),
        ):
            bgn = (today - timedelta(days=365 * cb_years)).strftime("%Y%m%d")
            for it in self._call(api, corp_code=corp, bgn_de=bgn, end_de=end).get("list", []):
                p = to_num(it.get(pct_key))
                if p:
                    potential_pct += p
                events.append({"type": kind, "date": it.get("rcept_no", "")[:8],
                               "amount_won": to_num(it.get(amt_key)), "shares": to_num(it.get(cnt_key)),
                               "pct_of_shares": p, "conv_price": to_num(it.get(price_key)),
                               "rcept_no": it.get("rcept_no")})
        bgn = (today - timedelta(days=365 * rights_years)).strftime("%Y%m%d")
        for it in self._call("piicDecsn", corp_code=corp, bgn_de=bgn, end_de=end).get("list", []):
            new = (to_num(it.get("nstk_ostk_cnt")) or 0) + (to_num(it.get("nstk_estk_cnt")) or 0)
            before = (to_num(it.get("bfic_tisstk_ostk")) or 0) + (to_num(it.get("bfic_tisstk_estk")) or 0)
            p = new / before * 100 if before else None
            if p:
                potential_pct += p
            events.append({"type": "유상증자", "date": it.get("rcept_no", "")[:8], "shares": new or None,
                           "pct_of_shares": p, "method": it.get("ic_mthn"), "rcept_no": it.get("rcept_no")})
        events.sort(key=lambda e: e["date"], reverse=True)
        return {"potential_pct": round(potential_pct, 2), "events": events,
                "basis": f"최근 CB·BW {cb_years}년 / 유상증자 {rights_years}년 발행결정 합계(전환·상환분 미차감, 보수적 추정)"}

    # ------------------------------------------------------------ 최대주주
    def major_holder(self, corp: str, today: datetime) -> dict:
        for y, rc in _recent_reports(today):
            rows = self._call("hyslrSttus", corp_code=corp, bsns_year=str(y), reprt_code=rc).get("list", [])
            if not rows:
                continue
            common = [r for r in rows if "보통" in (r.get("stock_knd") or "보통")]
            total_row = next((r for r in common if (r.get("nm") or "").strip() in ("계", "합계")), None)
            if total_row:
                pct = to_num(total_row.get("trmend_posesn_stock_qota_rt"))
            else:
                pct = sum(to_num(r.get("trmend_posesn_stock_qota_rt")) or 0 for r in common) or None
            top = next((r.get("nm") for r in common if (r.get("relate") or "").strip() in ("본인", "최대주주")), None)
            return {"pct": pct, "name": top, "basis": f"{y} {REPRT[rc]}"}
        return {}


def _recent_reports(today: datetime):
    """최근 → 과거 순 (연도, 보고서코드). 공시 시차를 감안해 넉넉히 시도."""
    y = today.year
    return [(y, "11014"), (y, "11012"), (y, "11013"), (y - 1, "11011"), (y - 1, "11014")]


def _accounts(rows: list[dict]) -> dict:
    """연결(CFS) 우선, 없으면 별도(OFS)."""
    by_fs: dict[str, dict] = {}
    for r in rows:
        fs = r.get("fs_div") or "OFS"
        nm = (r.get("account_nm") or "").replace(" ", "")
        val = to_num(r.get("thstrm_amount"))
        d = by_fs.setdefault(fs, {})
        if nm in ("매출액", "수익(매출액)", "영업수익") and "revenue" not in d:
            d["revenue"] = val
        elif nm == "영업이익" and "op_income" not in d:
            d["op_income"] = val
        elif nm in ("당기순이익", "당기순이익(손실)") and "net_income" not in d:
            d["net_income"] = val
        elif nm == "부채총계":
            d["liabilities"] = val
        elif nm == "자본총계":
            d["equity"] = val
    d = by_fs.get("CFS") or by_fs.get("OFS") or {}
    # 원 → 억원
    out = {k: (v / 1e8 if v is not None and k in ("revenue", "op_income", "net_income") else v) for k, v in d.items()}
    out["fs"] = "연결" if "CFS" in by_fs else "별도"
    return out
