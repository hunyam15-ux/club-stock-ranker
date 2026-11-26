"""실적·컨센서스: FnGuide(기본) → 네이버 '기업실적분석'(보조).

FnGuide 종목 메인의 Financial Highlight(연결/연간) 표에서 연도별
매출액·영업이익·지배주주순이익·EPS·부채비율·ROE 와 (E) 추정치를 읽는다.
"""
from __future__ import annotations

import re
from io import StringIO

from .util import get, log, to_num

FNGUIDE_MAIN = "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp"

# 표준 키 → 표에서 찾을 라벨 후보(앞부분 일치, 공백 무시)
ROW_KEYS = {
    "revenue": ["매출액", "영업수익", "순영업수익", "보험료수익", "이자수익"],
    "op_income": ["영업이익"],
    "net_income": ["지배주주순이익", "당기순이익"],
    "eps": ["EPS(원)", "EPS"],
    "debt_ratio": ["부채비율"],
    "roe": ["ROE"],
    "per": ["PER"],
    "pbr": ["PBR"],
    "div_yield": ["배당수익률", "시가배당률"],
}


def _clean(s) -> str:
    s = s[0] if isinstance(s, tuple) else s
    return re.sub(r"\s+", "", str(s))


def _match(label: str, cands: list[str]) -> bool:
    lab = re.sub(r"\(발표기준\)|\(지배\)", "", label)
    return any(lab == c or lab.startswith(c) for c in cands)


def normalize_years(raw: dict[str, dict[str, float | None]]) -> dict[str, dict]:
    """{'2025': {'매출액': ..}} → {'2025': {'revenue': .., 'estimate': False}}"""
    out = {}
    for ykey, rows in raw.items():
        year = ykey[:4]
        est = ykey.endswith("E")
        rec = {"estimate": est}
        for std, cands in ROW_KEYS.items():
            for label, val in rows.items():
                if _match(_clean(label), cands):
                    if val is not None:
                        rec[std] = val
                        break
        out[year] = rec
    return out


def parse_fnguide_highlight(html: str) -> dict | None:
    import pandas as pd

    # 연결 연간(highlight_D_Y) 우선, 없으면 별도 연간(highlight_B_Y)
    for div_id in ("highlight_D_Y", "highlight_B_Y"):
        i = html.find(f'id="{div_id}"')
        if i < 0:
            continue
        j = html.find("</table>", i)
        seg = html[i: j + 8]
        k = seg.find("<table")
        if k < 0:
            continue
        try:
            df = pd.read_html(StringIO(seg[k:]))[0]
        except Exception:  # noqa: BLE001
            continue
        raw: dict[str, dict] = {}
        cols = list(df.columns)
        label_col = cols[0]
        for c in cols[1:]:
            txt = " ".join(str(p) for p in (c if isinstance(c, tuple) else (c,)))
            m = re.search(r"(20\d\d)/\d\d", txt)
            if not m:
                continue
            key = m.group(1) + ("E" if "(E)" in txt else "")
            raw[key] = {_clean(row[label_col]): to_num(row[c]) for _, row in df.iterrows()}
        if raw:
            return raw
    return None


def parse_fnguide_target(html: str) -> float | None:
    """투자의견 컨센서스 표의 목표주가."""
    i = html.find("목표주가")
    if i < 0:
        return None
    seg = html[i: i + 3000]
    # 헤더(투자의견, 목표주가, EPS, PER, 추정기관수) 다음 첫 데이터 행의 두 번째 셀
    m = re.search(r"<tbody>.*?<tr>(.*?)</tr>", seg, re.S)
    if not m:
        return None
    tds = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)
    if len(tds) >= 2:
        return to_num(re.sub(r"<[^>]+>", "", tds[1]))
    return None


def fetch_fnguide(sess, code: str) -> dict:
    r = get(sess, FNGUIDE_MAIN, params={"pGB": 1, "gicode": f"A{code}", "cID": "", "MenuYn": "Y",
                                        "ReportGB": "", "NewMenuID": 101, "stkGb": 701})
    html = r.content.decode("utf-8", errors="replace")
    out = {}
    raw = parse_fnguide_highlight(html)
    if raw:
        out["annual"] = normalize_years(raw)
    t = parse_fnguide_target(html)
    if t:
        out["target"] = t
    return out


def merge_annual(primary: dict | None, secondary: dict | None) -> dict:
    """연도별로 primary 값을 우선, 빈 값은 secondary 로 채운다. 출처도 기록."""
    out: dict[str, dict] = {}
    for src_name, src in (("FnGuide", primary), ("네이버", secondary)):
        for y, rec in (src or {}).items():
            cur = out.setdefault(y, {"estimate": rec.get("estimate", False), "_src": {}})
            for k, v in rec.items():
                if k == "estimate":
                    continue
                if v is not None and cur.get(k) is None:
                    cur[k] = v
                    cur["_src"][k] = src_name
    return out


def estimates_for(annual: dict, year: int) -> dict:
    """올해·내년 추정/확정치를 꺼낸다."""
    def g(y):
        return annual.get(str(y)) or {}

    prev, cur, nxt = g(year - 1), g(year), g(year + 1)
    res = {"prev": prev, "cur": cur, "next": nxt, "year": year}

    def growth(a, b):
        if a is None or b is None or a == 0:
            return None
        if a < 0:
            return None  # 적자 기준 성장률은 의미 없음 → 별도 표기
        return (b / a - 1) * 100

    for k in ("revenue", "op_income", "eps"):
        res[f"{k}_g_cur"] = growth(prev.get(k), cur.get(k))
        res[f"{k}_g_next"] = growth(cur.get(k), nxt.get(k))
    res["turnaround_next"] = (cur.get("eps") is not None and cur["eps"] <= 0
                              and nxt.get("eps") is not None and nxt["eps"] > 0)
    return res


def log_fail(code, src, e):
    log.warning("%s %s 실패: %s", code, src, e)
