"""공통 유틸: HTTP 세션, 숫자 파싱, 호가 단위 반올림, 로깅."""
from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests

KST = timezone(timedelta(hours=9))
log = logging.getLogger("collector")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def now_kst() -> datetime:
    return datetime.now(KST)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    return s


def get(sess: requests.Session, url: str, *, params=None, retries: int = 2,
        timeout: int = 20, sleep: float = 0.3, **kw) -> requests.Response:
    """재시도 포함 GET. 실패하면 마지막 예외를 그대로 올린다."""
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            r = sess.get(url, params=params, timeout=timeout, **kw)
            r.raise_for_status()
            time.sleep(sleep)  # 상대 서버 배려
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 + i)
    assert last is not None
    raise last


_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def to_num(v: Any) -> float | None:
    """'3,805' · '13.45배' · '-1.2%' · 1234 → float. 'N/A', '', '-' → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return float(v)
    s = str(v).strip()
    if not s or s.upper() in {"N/A", "NA", "#N/A", "-", "—", "NAN", "#VALUE!", "#REF!", "LOADING..."}:
        return None
    m = _NUM_RE.search(s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_korean_amount(s: Any) -> float | None:
    """'1,018조 4,523억' / '5,127억' / '840' → 억원 단위 float."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    txt = str(s).replace(",", "").replace(" ", "")
    if not txt:
        return None
    jo = re.search(r"([\d.]+)조", txt)
    eok = re.search(r"([\d.]+)억", txt)
    if jo or eok:
        total = 0.0
        if jo:
            total += float(jo.group(1)) * 10000
        if eok:
            total += float(eok.group(1))
        return total
    return to_num(txt)


def first(*vals):
    """None 이 아닌 첫 값."""
    for v in vals:
        if v is not None:
            return v
    return None


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def lin_score(x: float | None, worst: float, best: float) -> float | None:
    """x 가 worst 이면 0점, best 이면 100점, 그 사이 선형 (worst>best 도 지원)."""
    if x is None:
        return None
    if best == worst:
        return 50.0
    return clamp((x - worst) / (best - worst) * 100.0, 0.0, 100.0)


def tick_size(price: float) -> int:
    """KRX 주식 호가가격단위 (2023-01-25 시행, 코스피·코스닥 통일)."""
    if price < 2000:
        return 1
    if price < 5000:
        return 5
    if price < 20000:
        return 10
    if price < 50000:
        return 50
    if price < 200000:
        return 100
    if price < 500000:
        return 500
    return 1000


def round_tick(price: float | None, mode: str = "nearest") -> int | None:
    if price is None or price <= 0:
        return None
    t = tick_size(price)
    q = price / t
    if mode == "down":
        n = math.floor(q + 1e-9)
    elif mode == "up":
        n = math.ceil(q - 1e-9)
    else:
        n = round(q)
    return int(n * t)


def median(xs: Iterable[float | None]) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def mean(xs: Iterable[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def pct(a: float | None, b: float | None) -> float | None:
    """(a/b - 1) * 100"""
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0
