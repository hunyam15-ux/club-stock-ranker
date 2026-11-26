"""매수 점수·등급·한 줄 근거.

입력 s(dict)의 주요 키 (없으면 None):
  price, target, target_source, per, pbr, fwd_per, bench_per, bench_pbr,
  eps_growth_next, turnaround, revision_pct, range_pos, ret_1m, ret_3m,
  dilution_pct, debt_ratio, memo_text
"""
from __future__ import annotations

from .util import clamp, lin_score

GRADES = {
    "green": {"emoji": "🟢", "label": "개꿀(적극 매수)"},
    "yellow": {"emoji": "🟡", "label": "분할매수"},
    "white": {"emoji": "⚪", "label": "관망"},
    "red": {"emoji": "🔴", "label": "비싸다(매수 금지)"},
}


def _wavg(parts: dict[str, tuple[float | None, float]]) -> float | None:
    num = den = 0.0
    for score, w in parts.values():
        if score is not None and w > 0:
            num += score * w
            den += w
    return num / den if den else None


def pick_target(club: float | None, cons: float | None, mode: str) -> tuple[float | None, str | None]:
    if mode == "consensus_first":
        return (cons, "컨센서스") if cons else ((club, "모임") if club else (None, None))
    if mode == "average" and club and cons:
        return (club + cons) / 2, "모임·컨센서스 평균"
    return (club, "모임") if club else ((cons, "컨센서스") if cons else (None, None))


def score_stock(s: dict, cfg: dict) -> dict:
    W = cfg["weights"]
    comps: dict[str, dict] = {}

    # 1) 업사이드 --------------------------------------------------------
    up = None
    if s.get("price") and s.get("target"):
        up = (s["target"] / s["price"] - 1) * 100
    u = cfg["upside"]
    up_s = up
    if up is not None and s.get("target_source") == "모델 적정가":
        up_s = up * cfg.get("target", {}).get("model_upside_weight", 1.0)  # 추정 목표가는 할인 반영
    comps["upside"] = {"score": lin_score(up_s, u["worst_pct"], u["best_pct"]), "value": up}

    # 2) 밸류에이션 ------------------------------------------------------
    v = cfg["valuation"]
    loss = v["loss_making_score"]

    def ratio_score(x, bench):
        if x is None and bench is None:
            return None, None
        if x is None or bench is None or bench <= 0:
            return None, None
        if x <= 0:
            return loss, None
        r = x / bench
        return lin_score(r, v["ratio_worst"], v["ratio_best"]), r

    per_s, per_r = ratio_score(s.get("per"), s.get("bench_per"))
    pbr_s, pbr_r = ratio_score(s.get("pbr"), s.get("bench_pbr"))
    fwd_s = fwd_r = None
    if s.get("fwd_per") is not None:
        if s["fwd_per"] <= 0:
            fwd_s = loss
        elif s.get("per") and s["per"] > 0:
            fwd_r = s["fwd_per"] / s["per"]
            fwd_s = lin_score(fwd_r, v["fwd_ratio_worst"], v["fwd_ratio_best"])
        elif s.get("per") is not None and s["per"] <= 0:
            fwd_s = 80.0  # 현재 적자 → 예상 흑자(Forward PER 양수)
    sw = v["sub_weights"]
    comps["valuation"] = {
        "score": _wavg({"per": (per_s, sw["per_vs_sector"]), "pbr": (pbr_s, sw["pbr_vs_sector"]),
                        "fwd": (fwd_s, sw["forward_per"])}),
        "per_ratio": per_r, "pbr_ratio": pbr_r, "fwd_ratio": fwd_r,
        "sub": {"per": per_s, "pbr": pbr_s, "fwd": fwd_s},
    }

    # 3) 실적 모멘텀 -----------------------------------------------------
    m = cfg["momentum"]
    g = s.get("eps_growth_next")
    if s.get("turnaround"):
        g_s = float(m["turnaround_score"])
    else:
        g_s = lin_score(g, m["eps_growth_worst_pct"], m["eps_growth_best_pct"])
    rev = s.get("revision_pct")
    rev_s = lin_score(rev, m["revision_worst_pct"], m["revision_best_pct"])
    msw = m["sub_weights"]
    comps["momentum"] = {"score": _wavg({"g": (g_s, msw["eps_growth"]), "r": (rev_s, msw["revision"])}),
                         "eps_growth": g, "revision": rev, "sub": {"eps_growth": g_s, "revision": rev_s}}

    # 4) 가격 위치 -------------------------------------------------------
    p = cfg["price_position"]
    pos = s.get("range_pos")
    pos_s = None if pos is None else clamp((1 - pos) * 100, 0, 100)
    r3 = lin_score(s.get("ret_3m"), p["return_3m_worst_pct"], p["return_3m_best_pct"])
    r1 = lin_score(s.get("ret_1m"), p["return_1m_worst_pct"], p["return_1m_best_pct"])
    psw = p["sub_weights"]
    comps["price_position"] = {"score": _wavg({"pos": (pos_s, psw["range_position"]), "r3": (r3, psw["return_3m"]),
                                                "r1": (r1, psw["return_1m"])}),
                               "range_pos": pos, "sub": {"range_position": pos_s, "return_3m": r3, "return_1m": r1}}

    for k in comps:
        comps[k]["weight"] = float(W.get(k, 0))

    # 5) 리스크 감점 -----------------------------------------------------
    rk = cfg["risk"]
    pen = {}
    dil = s.get("dilution_pct")
    pen["dilution"] = None if dil is None else clamp(dil / rk["dilution_full_pct"], 0, 1) * rk["dilution_points"]
    dr = s.get("debt_ratio")
    pen["debt"] = None if dr is None else clamp((dr - rk["debt_ratio_start_pct"]) /
                                                (rk["debt_ratio_full_pct"] - rk["debt_ratio_start_pct"]), 0, 1) * rk["debt_points"]
    memo = (s.get("memo_text") or "")
    hits = [kw for kw in rk["memo_keywords"] if kw.lower() in memo.lower()]
    pen["memo"] = min(len(hits) * rk["memo_points_per_keyword"], rk["memo_points_max"])
    penalty = min(sum(x for x in pen.values() if x), rk["max_total"])

    # 총점 ---------------------------------------------------------------
    total_w = sum(c["weight"] for c in comps.values())
    have_w = sum(c["weight"] for c in comps.values() if c["score"] is not None)
    coverage = have_w / total_w if total_w else 0
    base = _wavg({k: (c["score"], c["weight"]) for k, c in comps.items()})
    total = None if base is None else round(clamp(base - penalty, 0, 100), 1)

    gc = cfg["grades"]
    if total is None:
        grade = "white"
    elif total >= gc["green"]:
        grade = "green"
    elif total >= gc["yellow"]:
        grade = "yellow"
    elif total >= gc["white"]:
        grade = "white"
    else:
        grade = "red"
    flags = []
    if coverage < gc["min_coverage"] and grade in ("green", "yellow"):
        grade = "white"
        flags.append("데이터 부족")
    if gc.get("red_if_negative_upside") and up is not None and up <= 0:
        grade = "red"
        flags.append("현재가 ≥ 목표가")

    result = {
        "total": total, "base": None if base is None else round(base, 1), "penalty": round(penalty, 1),
        "penalty_detail": {k: (None if v is None else round(v, 1)) for k, v in pen.items()},
        "memo_hits": hits, "coverage": round(coverage, 2), "components": comps,
        "grade": grade, "grade_emoji": GRADES[grade]["emoji"], "grade_label": GRADES[grade]["label"],
        "flags": flags, "upside_pct": up,
    }
    result["reason"] = reason_line(s, result)
    return result


def target_label(src: str | None) -> str:
    return {"컨센서스": "컨센서스 목표가", "모델 적정가": "모델 적정가", "모임": "모임 목표가"}.get(src or "", "목표가")


def _f(x, d=0):
    return f"{x:+.{d}f}%"


def reason_line(s: dict, r: dict) -> str:
    """판단 근거 한 줄: 등급에 맞는 방향의 핵심 요인 2~3개."""
    c = r["components"]
    pos, neg = [], []  # (강도, 문구)
    up = r["upside_pct"]
    if up is not None:
        txt = f"{target_label(s.get('target_source'))} 대비 {_f(up)}"
        (pos if up >= 15 else neg).append((abs(up - 15) + 10, txt))
    pr = c["valuation"].get("per_ratio")
    if pr is not None:
        d = (1 - pr) * 100
        txt = f"PER 업종 대비 {abs(d):.0f}% {'할인' if d >= 0 else '할증'}"
        (pos if d >= 10 else neg if d <= -10 else []).append((abs(d), txt))
    elif s.get("per") is not None and s["per"] <= 0:
        neg.append((20, "적자(PER 산출 불가)"))
    br = c["valuation"].get("pbr_ratio")
    if br is not None:
        d = (1 - br) * 100
        if abs(d) >= 25:
            (pos if d > 0 else neg).append((abs(d) * 0.6, f"PBR 업종 대비 {abs(d):.0f}% {'할인' if d > 0 else '할증'}"))
    g = c["momentum"].get("eps_growth")
    if s.get("turnaround"):
        pos.append((40, "흑자전환 예상"))
    elif g is not None:
        (pos if g >= 10 else neg if g < 0 else []).append((abs(g), f"{s.get('eps_growth_label') or '예상 EPS'} {_f(g)}"))
    rev = c["momentum"].get("revision")
    if rev is not None and abs(rev) >= 3:
        (pos if rev > 0 else neg).append((abs(rev) * 3, f"컨센서스 {'상향' if rev > 0 else '하향'} {_f(rev, 1)}"))
    rp = c["price_position"].get("range_pos")
    if rp is not None:
        if rp <= 0.3:
            pos.append((30 * (1 - rp), f"52주 범위 하단({rp * 100:.0f}%)"))
        elif rp >= 0.85:
            neg.append((30 * rp, f"52주 고점권({rp * 100:.0f}%)"))
    if s.get("ret_3m") is not None and s["ret_3m"] >= 40:
        neg.append((s["ret_3m"] / 2, f"3개월 {_f(s['ret_3m'])} 급등"))
    pd_ = r["penalty_detail"]
    if (pd_.get("dilution") or 0) >= 3:
        neg.append((25, f"잠재 희석 {s.get('dilution_pct', 0):.1f}%"))
    if (pd_.get("debt") or 0) >= 3:
        neg.append((20, f"부채비율 {s.get('debt_ratio', 0):.0f}%"))
    if r["memo_hits"]:
        neg.append((10, "메모 리스크: " + "·".join(r["memo_hits"][:2])))

    pos.sort(reverse=True)
    neg.sort(reverse=True)
    if r["grade"] in ("green", "yellow"):
        parts = [t for _, t in pos[:2]] + [t for _, t in neg[:1]]
    elif r["grade"] == "red":
        parts = [t for _, t in neg[:2]] + [t for _, t in pos[:1]]
    else:
        parts = [t for _, t in pos[:1]] + [t for _, t in neg[:2]]
    if "데이터 부족" in r["flags"]:
        parts.insert(0, f"데이터 부족(충족률 {r['coverage'] * 100:.0f}%)")
    return ", ".join(parts[:3]) if parts else "판단 근거 데이터 부족"
