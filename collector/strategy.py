"""종목별 매매 전략(분할매수·손절·익절)과 포트폴리오 비중·현금 비중."""
from __future__ import annotations

from .util import clamp, round_tick


def entry_plan(price: float, deriv: dict, cfg: dict) -> dict:
    sc = cfg["strategy"]
    supports = sorted({round(deriv[f"low_{n}d"]) for n in sc["support_lookbacks"]
                       if deriv.get(f"low_{n}d") and deriv[f"low_{n}d"] < price}, reverse=True)
    steps = []
    used = set()
    for i, (pct, frac) in enumerate(zip(sc["entry_steps_pct"], sc["entry_split"])):
        target = price * (1 + pct / 100)
        basis = "현재가" if pct == 0 else f"현재가 {pct:+.0f}%"
        if i > 0:
            for sp in supports:
                if sp in used:
                    continue
                if abs(sp / target - 1) * 100 <= sc["support_snap_pct"]:
                    target = sp * 1.005  # 지지선 바로 위
                    lb = next(n for n in sc["support_lookbacks"] if round(deriv[f"low_{n}d"]) == sp)
                    basis = f"{lb}일 저점(지지선) 부근"
                    used.add(sp)
                    break
        steps.append({"step": i + 1, "price": round_tick(target, "down" if i else "nearest"),
                      "fraction": frac, "basis": basis})
    tot = sum(s["fraction"] for s in steps)
    avg = sum(s["price"] * s["fraction"] for s in steps) / tot

    # 손절: 평균진입가 -8% 와 (3차 매수가 아래) 주요 지지선 -2% 중 높은 가격 = 먼저 닿는 쪽
    stop_pct_price = avg * (1 + sc["stop_loss_pct"] / 100)
    last_entry = steps[-1]["price"]
    below = [sp for sp in supports if sp < last_entry]
    stop_sup_price = below[0] * (1 + sc["stop_below_support_pct"] / 100) if below else None
    if stop_sup_price and stop_sup_price > stop_pct_price and stop_sup_price < last_entry:
        stop, stop_basis = stop_sup_price, f"지지선({below[0]:,.0f}원) {sc['stop_below_support_pct']}% 이탈"
    else:
        stop, stop_basis = stop_pct_price, f"평균 진입가 {sc['stop_loss_pct']}%"
    stop = min(stop, last_entry * 0.98)
    return {"entries": steps, "avg_entry": round_tick(avg), "stop": round_tick(stop, "down"),
            "stop_basis": stop_basis, "supports": supports}


def exit_plan(price: float, target: float | None, cfg: dict) -> dict:
    sc = cfg["strategy"]
    if not target or target <= price:
        return {"tp1": None, "tp2": None, "trailing_pct": sc["trailing_stop_pct"],
                "note": "목표가가 없거나 현재가 이하 → 신규 매수 대상 아님, 보유 시 추적 손절만 적용"}
    tp1 = price + (target - price) * sc["take_profit_1_progress"]
    return {"tp1": round_tick(tp1), "tp1_fraction": sc["take_profit_1_fraction"], "tp2": round_tick(target),
            "trailing_pct": sc["trailing_stop_pct"], "note": None}


def portfolio_weights(stocks: list[dict], cash_pct: float, cfg: dict) -> None:
    """총점·변동성 반영 권장 비중. stocks 각 항목에 'weight_pct' 를 채운다."""
    sc = cfg["strategy"]
    mult = sc["grade_multiplier"]
    cap = sc["max_weight_pct"]
    raw = {}
    for s in stocks:
        m = mult.get(s["score"]["grade"], 0)
        tot = s["score"]["total"]
        vol = s.get("vol_annual") or 40.0  # 변동성 결측 시 보수적으로 40% 가정
        if m > 0 and tot:
            raw[s["code"]] = m * tot / clamp(vol, 15, 120)
    investable = 100 - cash_pct
    weights = {k: 0.0 for k in raw}
    remaining = dict(raw)
    budget = investable
    # 상한 초과분을 나머지 종목에 재분배(반복)
    for _ in range(20):
        tot_raw = sum(remaining.values())
        if not remaining or tot_raw <= 0 or budget <= 1e-9:
            break
        capped = False
        for k, v in list(remaining.items()):
            w = budget * v / tot_raw
            if weights[k] + w > cap:
                capped = True
        if not capped:
            for k, v in remaining.items():
                weights[k] += budget * v / tot_raw
            budget = 0
            break
        for k, v in list(remaining.items()):
            w = budget * v / tot_raw
            if weights[k] + w > cap:
                budget -= cap - weights[k]
                weights[k] = cap
                del remaining[k]
    for s in stocks:
        s["weight_pct"] = round(weights.get(s["code"], 0.0), 1)
    return None


def cash_policy(index: dict | None, n_green: int, cfg: dict) -> dict:
    c = cfg["cash"]
    if not index or index.get("ma_short") is None or index.get("ma_long") is None:
        state, base = "unknown", c["base_pct"]["mixed"]
        desc = "코스피 추세 데이터 없음 → 중립 가정"
    else:
        a, b = index["last"] > index["ma_short"], index["last"] > index["ma_long"]
        state = "above_both" if a and b else "below_both" if not a and not b else "mixed"
        base = c["base_pct"][state]
        desc = {"above_both": f"코스피 {c['ma_short']}·{c['ma_long']}일선 위(상승 추세)",
                "mixed": f"코스피 {c['ma_short']}·{c['ma_long']}일선 혼조",
                "below_both": f"코스피 {c['ma_short']}·{c['ma_long']}일선 아래(하락 추세)"}[state]
    adj = 0
    for rule in c["green_adjust"]:
        if n_green >= rule["min_green"]:
            adj = rule["adj"]
            break
    pct = clamp(base + adj, c["min_pct"], c["max_pct"])
    return {"cash_pct": pct, "trend_state": state, "trend_desc": desc, "base": base, "green_adj": adj,
            "n_green": n_green}
