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


def portfolio_weights(stocks: list[dict], cash_pct: float, cfg: dict) -> dict:
    """코어&새틀라이트 + 가치 가중.
    - 코어: 시총 기준 이상 · 퀄리티 통과 🟢/🟡 상위 core_size 종목 → 주식 몫 × core_ratio
    - 새틀라이트: 나머지 🟢/🟡 상위 satellite_size 종목 → 주식 몫 × (1−core_ratio)
    - 각 바구니 안에서 비중 ∝ 등급배수 × 총점 × (1+안전마진) ÷ 변동성, 한 종목 상한 max_weight_pct
    stocks 는 순위순. 각 종목에 weight_pct, bucket 을 채운다."""
    sc = cfg["strategy"]
    cs = sc["core_satellite"]
    mult = sc["grade_multiplier"]
    cap = sc["max_weight_pct"]
    elig = [s for s in stocks if s["score"]["grade"] in ("green", "yellow") and s["score"]["total"]]
    core = [s for s in elig if (s.get("mcap_eok") or 0) >= cs["core_min_mcap_eok"] and not s["score"]["quality_fails"]][: cs["core_size"]]
    core_codes = {s["code"] for s in core}
    sat = [s for s in elig if s["code"] not in core_codes][: cs["satellite_size"]]
    investable = 100 - cash_pct
    budgets = {"코어": investable * cs["core_ratio"], "새틀라이트": investable * (1 - cs["core_ratio"])}
    if not core:
        budgets = {"코어": 0, "새틀라이트": investable}
    if not sat:
        budgets["코어"] += budgets["새틀라이트"]
        budgets["새틀라이트"] = 0
    for s in stocks:
        s["weight_pct"], s["bucket"] = 0.0, None

    def raw(s):
        vol = s.get("vol_annual") or 40.0
        mos = s.get("mos_pct")
        vw = (1 + clamp(mos or 0, -50, 100) / 100) if sc.get("value_weighting") else 1
        return mult.get(s["score"]["grade"], 0) * s["score"]["total"] * vw / clamp(vol, 15, 120)

    for name, bucket in (("코어", core), ("새틀라이트", sat)):
        w = _alloc({s["code"]: raw(s) for s in bucket}, budgets[name], cap)
        for s in bucket:
            s["weight_pct"], s["bucket"] = round(w.get(s["code"], 0.0), 1), name
    return {"core": [s["code"] for s in core], "satellite": [s["code"] for s in sat], "budgets": budgets}


def _alloc(raw: dict, budget: float, cap: float) -> dict:
    weights = {k: 0.0 for k in raw}
    remaining = {k: v for k, v in raw.items() if v > 0}
    for _ in range(30):
        tot = sum(remaining.values())
        if not remaining or tot <= 0 or budget <= 1e-9:
            break
        over = [k for k, v in remaining.items() if weights[k] + budget * v / tot > cap]
        if not over:
            for k, v in remaining.items():
                weights[k] += budget * v / tot
            break
        for k in over:
            budget -= cap - weights[k]
            weights[k] = cap
            del remaining[k]
    return weights


def cash_policy(index: dict | None, n_green: int, cfg: dict, macro_adj: tuple[int, list[str]] | None = None) -> dict:
    """정률투자(기본 현금) + 코스피 추세 + 절대모멘텀 + 🟢 개수 + 매크로 불안요소."""
    c = cfg["cash"]
    steps = [("정률 기본", c["base_pct"])]
    state, desc = "unknown", "코스피 추세 데이터 없음"
    if index and index.get("ma_short") is not None and index.get("ma_long") is not None:
        a, b = index["last"] > index["ma_short"], index["last"] > index["ma_long"]
        state = "above_both" if a and b else "below_both" if not a and not b else "mixed"
        desc = {"above_both": f"코스피 {c['ma_short']}·{c['ma_long']}일선 위(상승 추세)",
                "mixed": f"코스피 {c['ma_short']}·{c['ma_long']}일선 혼조",
                "below_both": f"코스피 {c['ma_short']}·{c['ma_long']}일선 아래(하락 추세)"}[state]
        steps.append((desc, c["trend_adj"][state]))
    r12 = (index or {}).get("ret_12m")
    if r12 is not None and r12 < 0:
        steps.append((f"절대모멘텀: 코스피 12개월 {r12:+.1f}% < 0", c["abs_momentum_adj"]))
    for rule in c["green_adjust"]:
        if n_green >= rule["min_green"]:
            steps.append((f"🟢 {n_green}종목", rule["adj"]))
            break
    if macro_adj:
        adj, why = macro_adj
        for w in why:
            steps.append((w.split(" (+")[0], int(w.split("(+")[1].split("%")[0]) if "(+" in w else 0))
    total = sum(v for _, v in steps)
    pct = clamp(total, c["min_pct"], c["max_pct"])
    return {"cash_pct": pct, "trend_state": state, "trend_desc": desc, "n_green": n_green,
            "steps": [{"label": l, "adj": v} for l, v in steps], "rebalance_band_pct": c.get("rebalance_band_pct")}
