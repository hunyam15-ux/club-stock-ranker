"""매크로 불안요소(모임 자료의 '불안요소': 금리 · 하이일드 스프레드).

FRED 공개 CSV(키 불필요)  https://fred.stlouisfed.org/graph/fredgraph.csv?id=...
  BAMLH0A0HYM2       미국 하이일드 스프레드(OAS, %)  — 일간
  DGS10              미국 10년물 국채금리(%)          — 일간
  IRLTLT01KRM156N    한국 10년물 국채금리(%)          — 월간
가져오지 못하면 해당 항목은 N/A, 현금 비중 가감에서 빠진다.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from .util import get, log, to_num

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {
    "hy_spread": ("BAMLH0A0HYM2", "미국 하이일드 스프레드"),
    "us10y": ("DGS10", "미국 10년물 금리"),
    "kr10y": ("IRLTLT01KRM156N", "한국 10년물 금리(월간)"),
}


def fetch_series(sess, sid: str, days: int = 400) -> list[tuple[str, float]]:
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    r = get(sess, FRED, params={"id": sid, "cosd": start}, timeout=30)
    rows = []
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 2 or not row[0][:4].isdigit():
            continue
        v = to_num(row[1])
        if v is not None:
            rows.append((row[0], v))
    if not rows:
        raise RuntimeError(f"{sid}: 데이터 없음")
    return rows


def _change(rows, days):
    if not rows:
        return None
    last_d = datetime.strptime(rows[-1][0], "%Y-%m-%d")
    target = last_d - timedelta(days=days)
    past = [v for d, v in rows if datetime.strptime(d, "%Y-%m-%d") <= target]
    return rows[-1][1] - past[-1] if past else None


def fetch_macro(sess) -> dict:
    out = {}
    for key, (sid, label) in SERIES.items():
        try:
            rows = fetch_series(sess, sid)
            vals = [v for _, v in rows[-260:]]
            out[key] = {"label": label, "value": rows[-1][1], "date": rows[-1][0],
                        "chg_1m": _change(rows, 30), "chg_3m": _change(rows, 91),
                        "high_1y": max(vals), "low_1y": min(vals)}
        except Exception as e:  # noqa: BLE001
            log.warning("매크로 %s 실패: %s", sid, e)
            out[key] = {"label": label, "value": None}
    return out


def macro_adjust(m: dict, cfg: dict) -> tuple[int, list[str]]:
    """현금 비중 가감(%p)과 사유."""
    adj, why = 0, []
    hy = (m or {}).get("hy_spread") or {}
    if hy.get("value") is not None:
        if hy["value"] >= cfg["hy_spread_high"]:
            adj += cfg["hy_spread_high_adj"]
            why.append(f"하이일드 스프레드 {hy['value']:.2f}% ≥ {cfg['hy_spread_high']}% (+{cfg['hy_spread_high_adj']}%p)")
        if (hy.get("chg_1m") or 0) >= cfg["hy_spread_jump"]:
            adj += cfg["hy_spread_jump_adj"]
            why.append(f"하이일드 스프레드 1개월 +{hy['chg_1m']:.2f}%p 확대 (+{cfg['hy_spread_jump_adj']}%p)")
    us = (m or {}).get("us10y") or {}
    if us.get("value") is not None and us["value"] >= cfg["us10y_high"]:
        adj += cfg["us10y_high_adj"]
        why.append(f"미국 10년물 {us['value']:.2f}% ≥ {cfg['us10y_high']}% (+{cfg['us10y_high_adj']}%p)")
    return adj, why
