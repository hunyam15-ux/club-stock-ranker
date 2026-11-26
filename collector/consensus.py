"""실적·컨센서스: 네이버 증권 모바일 API (연간 재무 + 컨센서스 추정치).

  https://m.stock.naver.com/api/stock/{code}/finance/annual
  → 최근 3개 연도 확정치 + 컨센서스(isConsensus=Y) 연도. 단위: 매출·이익 억원, EPS 원, 비율 %.

※ 2026-11 확인: FnGuide 종목 페이지는 GitHub Actions 서버에서 '페이지 없음'을 돌려주고,
   네이버 종목 메인(finance.naver.com/item/main) 은 개편되어 표가 사라져 이 API 로 대체했다.
   네이버는 보통 컨센서스 1개 연도(올해 E)만 제공하므로 내년 E 는 없으면 N/A 로 둔다.
"""
from __future__ import annotations

import re

from .util import get, to_num

NAVER_ANNUAL = "https://m.stock.naver.com/api/stock/{code}/finance/annual"

# 표준 키 → 행 제목 후보 (정확 일치 우선)
ROW_KEYS = {
    "revenue": ["매출액", "영업수익", "순영업수익", "보험영업수익", "이자수익"],
    "op_income": ["영업이익"],
    "net_income": ["지배주주순이익", "당기순이익"],
    "eps": ["EPS"],
    "debt_ratio": ["부채비율"],
    "roe": ["ROE"],
    "per": ["PER"],
    "pbr": ["PBR"],
    "dps": ["주당배당금"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+|\(.*?\)", "", str(s or ""))


def parse_naver_annual(js: dict) -> dict:
    """→ {'2025': {'estimate': False, 'revenue':..., 'eps':...}, '2026': {'estimate': True, ...}}"""
    info = js.get("financeInfo") or {}
    cols = info.get("trTitleList") or []
    rows = info.get("rowList") or []
    out: dict[str, dict] = {}
    for c in cols:
        key = str(c.get("key") or "")
        m = re.match(r"(20\d\d)", key) or re.search(r"(20\d\d)", str(c.get("title") or ""))
        if not m:
            continue
        year = m.group(1)
        rec = {"estimate": str(c.get("isConsensus")).upper() == "Y"}
        for std, cands in ROW_KEYS.items():
            for cand in cands:  # 후보 순서대로(지배주주순이익 → 당기순이익)
                row = next((r for r in rows if _norm(r.get("title")) == cand), None)
                if row is None:
                    continue
                cell = (row.get("columns") or {}).get(key) or {}
                v = to_num(cell.get("value"))
                if v is not None:
                    rec[std] = v
                    break
        out[year] = rec
    return out


def fetch_naver_annual(sess, code: str) -> dict:
    js = get(sess, NAVER_ANNUAL.format(code=code)).json()
    return parse_naver_annual(js)


def estimates_for(annual: dict, year: int) -> dict:
    """전년·올해·내년 값과 성장률."""
    def g(y):
        return annual.get(str(y)) or {}

    prev, cur, nxt = g(year - 1), g(year), g(year + 1)
    res = {"prev": prev, "cur": cur, "next": nxt, "year": year}

    def growth(a, b):
        if a is None or b is None or a == 0 or a < 0:
            return None  # 적자 기준 성장률은 의미 없음 → 별도 표기
        return (b / a - 1) * 100

    for k in ("revenue", "op_income", "eps"):
        res[f"{k}_g_cur"] = growth(prev.get(k), cur.get(k))
        res[f"{k}_g_next"] = growth(cur.get(k), nxt.get(k))
    res["turnaround_next"] = (cur.get("eps") is not None and cur["eps"] <= 0
                              and nxt.get("eps") is not None and nxt["eps"] > 0)
    res["turnaround_cur"] = (prev.get("eps") is not None and prev["eps"] <= 0
                             and cur.get("eps") is not None and cur["eps"] > 0)
    return res
