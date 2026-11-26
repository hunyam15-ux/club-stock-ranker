"""시세·밸류에이션: 네이버 금융(기본) → pykrx(보조) → 시트 값(최후 보조).

각 값에는 출처(source)를 함께 기록한다. 가져오지 못한 값은 None(화면에서 N/A).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from .util import get, log, parse_korean_amount, to_num

NAVER_BASIC = "https://m.stock.naver.com/api/stock/{code}/basic"
NAVER_INTEGRATION = "https://m.stock.naver.com/api/stock/{code}/integration"
NAVER_FCHART = "https://fchart.stock.naver.com/sise.nhn"


# ---------------------------------------------------------------- 일봉
def fetch_daily(sess, symbol: str, count: int = 300) -> list[list]:
    """[[YYYY-MM-DD, open, high, low, close, volume], ...] 오래된 순. symbol: '005930' 또는 'KOSPI'."""
    r = get(sess, NAVER_FCHART, params={"symbol": symbol, "timeframe": "day",
                                        "count": count, "requestType": 0})
    text = r.content.decode("euc-kr", errors="replace")
    # 선언부가 EUC-KR 이라 expat 이 못 읽으므로 디코딩 후 선언부를 제거하고 파싱
    root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))
    out = []
    for item in root.iter("item"):
        d = item.get("data", "").split("|")
        if len(d) < 6:
            continue
        try:
            o, h, l, c, v = (float(x) for x in d[1:6])
        except ValueError:
            continue
        if c <= 0:
            continue
        out.append([f"{d[0][:4]}-{d[0][4:6]}-{d[0][6:8]}", o, h, l, c, v])
    if not out:
        raise RuntimeError(f"{symbol}: 일봉 데이터 없음")
    return out


def fetch_daily_pykrx(code: str, days: int = 400) -> list[list]:
    from pykrx import stock  # 선택 의존성

    end = datetime.now()
    start = end - timedelta(days=days)
    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    out = []
    for idx, row in df.iterrows():
        c = float(row["종가"])
        if c <= 0:
            continue
        out.append([idx.strftime("%Y-%m-%d"), float(row["시가"]), float(row["고가"]),
                    float(row["저가"]), c, float(row["거래량"])])
    if not out:
        raise RuntimeError(f"{code}: pykrx 일봉 없음")
    return out


# ---------------------------------------------------------------- 네이버 요약 지표
def _total_infos(js: dict) -> dict[str, str]:
    out = {}
    for it in js.get("totalInfos") or []:
        key = (it.get("key") or it.get("code") or "").strip()
        if key:
            out[key] = it.get("value")
    return out


def _pick(infos: dict[str, str], *names):
    for n in names:
        for k, v in infos.items():
            if k.replace(" ", "") == n.replace(" ", ""):
                return v
    return None


def fetch_naver_summary(sess, code: str, with_basic: bool = True) -> dict:
    """현재가·시총·PER·PBR·배당수익률·52주 고저·컨센서스 목표가 등.
    with_basic=False 면 현재가 조회(basic)를 생략한다(전체 목록에서 이미 받은 경우)."""
    out: dict = {}
    if with_basic:
        out.update(_fetch_basic(sess, code))
    out.update(_fetch_integration(sess, code))
    return out


def _fetch_basic(sess, code: str) -> dict:
    out: dict = {}
    try:
        b = get(sess, NAVER_BASIC.format(code=code)).json()
        out["price"] = to_num(b.get("closePrice"))
        out["change_pct"] = to_num(b.get("fluctuationsRatio"))
        out["name"] = b.get("stockName")
        out["market"] = (b.get("stockExchangeType") or {}).get("nameKor") or b.get("stockExchangeName")
        out["price_time"] = b.get("localTradedAt")
        out["stock_type"] = b.get("stockEndType")  # 'stock' / 'etf' 등
    except Exception as e:  # noqa: BLE001
        log.warning("%s 네이버 basic 실패: %s", code, e)
    return out


def _fetch_integration(sess, code: str) -> dict:
    out: dict = {}
    try:
        js = get(sess, NAVER_INTEGRATION.format(code=code)).json()
        infos = _total_infos(js)
        out["mcap_eok"] = parse_korean_amount(_pick(infos, "시총", "시가총액"))
        out["per"] = to_num(_pick(infos, "PER"))
        out["eps"] = to_num(_pick(infos, "EPS"))
        out["fwd_per_naver"] = to_num(_pick(infos, "추정PER"))
        out["fwd_eps_naver"] = to_num(_pick(infos, "추정EPS"))
        out["pbr"] = to_num(_pick(infos, "PBR"))
        out["bps"] = to_num(_pick(infos, "BPS"))
        out["div_yield"] = to_num(_pick(infos, "배당수익률"))
        out["high52"] = to_num(_pick(infos, "52주 최고", "52주최고"))
        out["low52"] = to_num(_pick(infos, "52주 최저", "52주최저"))
        cons = js.get("consensusInfo") or {}
        out["cons_target"] = to_num(cons.get("priceTargetMean"))
        out["cons_opinion"] = to_num(cons.get("recommMean"))
        out["cons_date"] = cons.get("createDate")
        # 동일업종 비교 목록이 있으면 업종 PER 산출에 사용
        peers = js.get("industryCompareInfo") or []
        out["peer_codes"] = [p.get("itemCode") for p in peers if p.get("itemCode")]
    except Exception as e:  # noqa: BLE001
        log.warning("%s 네이버 integration 실패: %s", code, e)
    return out


def fetch_per(sess, code: str) -> float | None:
    """동종업종 비교용: 종목 PER 하나만."""
    js = get(sess, NAVER_INTEGRATION.format(code=code)).json()
    return to_num(_pick(_total_infos(js), "PER"))


def fetch_pykrx_fundamental(code: str) -> dict:
    from pykrx import stock

    d = datetime.now()
    for _ in range(7):
        ds = d.strftime("%Y%m%d")
        try:
            f = stock.get_market_fundamental(ds, ds, code)
            if len(f):
                row = f.iloc[-1]
                return {"per": to_num(row.get("PER")) or None, "pbr": to_num(row.get("PBR")) or None,
                        "div_yield": to_num(row.get("DIV")), "eps": to_num(row.get("EPS")),
                        "bps": to_num(row.get("BPS"))}
        except Exception:  # noqa: BLE001
            pass
        d -= timedelta(days=1)
    return {}


# ---------------------------------------------------------------- 파생 지표
def derive_from_daily(daily: list[list]) -> dict:
    closes = [r[4] for r in daily]
    last = daily[-1]
    year = daily[-250:]
    out = {
        "last_date": last[0],
        "last_close": last[4],
        "high52_calc": max(r[2] for r in year),
        "low52_calc": min(r[3] for r in year),
    }

    def ret(n):
        if len(closes) > n:
            return (closes[-1] / closes[-1 - n] - 1) * 100
        return None

    out["ret_1w"], out["ret_1m"], out["ret_3m"], out["ret_6m"], out["ret_12m"] = (
        ret(5), ret(21), ret(63), ret(126), ret(245))
    for n in (60, 120):
        seg = daily[-n:]
        out[f"low_{n}d"] = min(r[3] for r in seg)
        out[f"high_{n}d"] = max(r[2] for r in seg)
    if len(closes) >= 200:
        out["ma200"] = sum(closes[-200:]) / 200
        out["below_ma200"] = closes[-1] < out["ma200"]
    else:
        out["ma200"], out["below_ma200"] = None, None
    # 60일 일간 수익률 표준편차(연율화)
    import math
    seg = closes[-61:]
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) >= 20:
        mu = sum(rets) / len(rets)
        var = sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)
        out["vol_annual"] = math.sqrt(var) * math.sqrt(252) * 100
    else:
        out["vol_annual"] = None
    return out


def price_on_or_after(daily: list[list], date: str | None) -> float | None:
    if not date:
        return None
    for r in daily:
        if r[0] >= date:
            return r[4]
    return None


def index_trend(daily: list[list], ma_short: int, ma_long: int) -> dict:
    closes = [r[4] for r in daily]
    out = {"last": closes[-1], "date": daily[-1][0], "ma_short": None, "ma_long": None}
    if len(closes) >= ma_short:
        out["ma_short"] = sum(closes[-ma_short:]) / ma_short
    if len(closes) >= ma_long:
        out["ma_long"] = sum(closes[-ma_long:]) / ma_long
    if len(closes) > 21:
        out["ret_1m"] = (closes[-1] / closes[-22] - 1) * 100
    out["ret_12m"] = (closes[-1] / closes[-246] - 1) * 100 if len(closes) > 245 else None
    return out
