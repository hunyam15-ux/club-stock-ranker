"""코스피·코스닥 전체 종목 유니버스 + 네이버 업종 분류.

  목록: https://m.stock.naver.com/api/stocks/marketValue/{KOSPI|KOSDAQ}?page=N&pageSize=100
        (시가총액 순, marketValue 단위 억원, accumulatedTradingValue 단위 백만원)
  업종: https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100   → 업종 번호·이름
        https://m.stock.naver.com/api/stocks/industry/{no}?page=N&pageSize=100 → 업종 소속 종목
"""
from __future__ import annotations

import re

from .util import get, log, to_num

LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}"
IND_LIST_URL = "https://m.stock.naver.com/api/stocks/industry"
IND_URL = "https://m.stock.naver.com/api/stocks/industry/{no}"

PREFERRED_RE = re.compile(r"(\d?우[A-C]?|우선주)$")


def _pages(sess, url: str, key: str = "stocks", page_size: int = 100, max_pages: int = 60):
    for page in range(1, max_pages + 1):
        js = get(sess, url, params={"page": page, "pageSize": page_size}, sleep=0.1).json()
        items = js.get(key) or []
        if not items:
            break
        yield from items
        total = js.get("totalCount")
        if total and page * page_size >= total:
            break


def fetch_listing(sess) -> list[dict]:
    out = []
    for mk in ("KOSPI", "KOSDAQ"):
        n = 0
        for it in _pages(sess, LIST_URL.format(market=mk)):
            n += 1
            out.append({
                "code": it.get("itemCode"),
                "name": it.get("stockName"),
                "market": "코스피" if mk == "KOSPI" else "코스닥",
                "end_type": (it.get("stockEndType") or "").lower(),
                "price": to_num(it.get("closePriceRaw") or it.get("closePrice")),
                "change_pct": to_num(it.get("fluctuationsRatio")),
                "mcap_eok": to_num(it.get("marketValue")),
                "trade_value_mil": to_num(it.get("accumulatedTradingValue")),
                "price_time": it.get("localTradedAt"),
                "trading": ((it.get("tradeStopType") or {}).get("name") or "TRADING") == "TRADING",
            })
        log.info("목록 %s: %d건", mk, n)
    return out


def fetch_industries(sess) -> dict[str, str]:
    """종목코드 → 네이버 업종명."""
    groups = list(_pages(sess, IND_LIST_URL, key="groups"))
    m: dict[str, str] = {}
    for g in groups:
        name, no = g.get("name"), g.get("no")
        try:
            for it in _pages(sess, IND_URL.format(no=no)):
                c = it.get("itemCode")
                if c and c not in m:
                    m[c] = name
        except Exception as e:  # noqa: BLE001
            log.warning("업종 %s(%s) 실패: %s", name, no, e)
    log.info("업종 분류: %d개 업종, %d종목", len(groups), len(m))
    return m


def is_excluded(it: dict, cfg: dict) -> str | None:
    """제외 사유(없으면 None)."""
    name = it.get("name") or ""
    code = it.get("code") or ""
    if it.get("end_type") not in ("stock", ""):
        return "ETF/ETN 등"
    if not re.fullmatch(r"[0-9][0-9A-Z]{5}", code):
        return "코드 형식"
    if cfg.get("exclude_preferred", True) and (PREFERRED_RE.search(name) or code[-1] in "5789K"):
        return "우선주"
    if cfg.get("exclude_spac", True) and "스팩" in name:
        return "스팩"
    if cfg.get("exclude_reits", False) and "리츠" in name:
        return "리츠"
    if not it.get("trading", True):
        return "거래정지"
    if (it.get("mcap_eok") or 0) < cfg.get("min_mcap_eok", 0):
        return "시총 미달"
    if (it.get("trade_value_mil") or 0) < cfg.get("min_trade_value_mil", 0):
        return "거래대금 미달"
    return None
