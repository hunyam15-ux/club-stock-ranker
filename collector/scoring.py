"""매수 점수·등급·한 줄 근거 (보수적 버전).

종목 선정 프로세스
  ① 유니버스 필터(universe.py)
  ② 퀄리티 게이트: 적자·낮은 ROE·과도한 부채·대규모 희석·데이터 부족 → 최고 ⚪ (가치 함정 회피)
  ③ 알파 점수: 업사이드(보수적 목표가) · 가치(업종 대비·안전마진) · 성장 · 알파(서프라이즈·수주·컨센서스 상향) · 가격/위험(위치·저변동성)
  ④ 리스크 감점(희석·부채·메모) · 떨어지는 칼날 → 최고 🟡
  ⑤ 등급 정원(🟢·🟡)

입력 s(dict)의 주요 키 (없으면 None) — main.score_input 참고.
"""
from __future__ import annotations

from .util import clamp, lin_score

GRADES = {
    "green": {"emoji": "🟢", "label": "개꿀(적극 매수)"},
    "yellow": {"emoji": "🟡", "label": "분할매수"},
    "white": {"emoji": "⚪", "label": "관망"},
    "red": {"emoji": "🔴", "label": "비싸다(매수 금지)"},
}
ORDER = ["red", "white", "yellow", "green"]


def target_label(src: str | None) -> str:
    return {"컨센서스": "컨센서스 목표가", "보수적 목표가": "보수적 목표가", "내재가치": "내재가치",
            "내재가치(상한)": "내재가치(상한 적용)",
            "모델 적정가": "모델 적정가", "모임": "모임 목표가"}.get(src or "", "목표가")


def _wavg(parts: dict[str, tuple[float | None, float]]) -> float | None:
    num = den = 0.0
    for score, w in parts.values():
        if score is not None and w > 0:
            num += score * w
            den += w
    return num / den if den else None


def _cap(grade: str, max_grade: str) -> str:
    return grade if ORDER.index(grade) <= ORDER.index(max_grade) else max_grade


def quality_gate(s: dict, cfg: dict) -> list[str]:
    """통과 못 한 사유 목록(빈 목록이면 통과)."""
    q = cfg["quality"]
    fails = []
    if s.get("per") is not None and s["per"] <= 0:
        fails.append("최근 4분기 적자")
    elif s.get("op_income_last") is not None and s["op_income_last"] < 0:
        fails.append("최근 연간 영업적자")
    if s.get("roe") is not None and s["roe"] < q["min_roe"]:
        fails.append(f"ROE {s['roe']:.1f}% < {q['min_roe']}%")
    if s.get("debt_ratio") is not None and s["debt_ratio"] > q["max_debt_ratio"]:
        fails.append(f"부채비율 {s['debt_ratio']:.0f}% > {q['max_debt_ratio']}%")
    if s.get("dilution_pct") is not None and s["dilution_pct"] >= q["max_dilution_pct"]:
        fails.append(f"잠재 희석 {s['dilution_pct']:.1f}% ≥ {q['max_dilution_pct']}%")
    return fails


def score_stock(s: dict, cfg: dict) -> dict:
    W = cfg["weights"]
    miss = cfg.get("missing_component_score", 30)
    comps: dict[str, dict] = {}

    # 1) 업사이드 — 보수적 목표가 기준 ------------------------------------
    up = None
    if s.get("price") and s.get("target"):
        up = (s["target"] / s["price"] - 1) * 100
    u = cfg["upside"]
    up_s = up
    if up is not None and not s.get("has_consensus"):
        up_s = up * cfg["target"].get("model_upside_weight", 1.0)  # 컨센서스 없는 추정 목표가는 할인 반영
    comps["upside"] = {"score": lin_score(up_s, u["worst_pct"], u["best_pct"]), "value": up}

    # 2) 가치 — 업종 대비 PER·PBR, Forward PER, 안전마진 -------------------
    v = cfg["valuation"]
    loss = v["loss_making_score"]

    def ratio_score(x, bench):
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
    mos = s.get("mos_pct")
    mos_s = lin_score(mos, v["mos_worst_pct"], v["mos_best_pct"])
    sw = v["sub_weights"]
    comps["value"] = {"score": _wavg({"per": (per_s, sw["per_vs_sector"]), "pbr": (pbr_s, sw["pbr_vs_sector"]),
                                      "fwd": (fwd_s, sw["forward_per"]), "mos": (mos_s, sw["margin_of_safety"])}),
                      "per_ratio": per_r, "pbr_ratio": pbr_r, "fwd_ratio": fwd_r, "mos": mos,
                      "sub": {"per": per_s, "pbr": pbr_s, "fwd": fwd_s, "mos": mos_s}}

    # 3) 성장 — EPS·영업이익 성장 -----------------------------------------
    gcfg = cfg["growth"]
    g = s.get("eps_growth")
    g_s = float(gcfg["turnaround_score"]) if s.get("turnaround") else lin_score(g, gcfg["worst_pct"], gcfg["best_pct"])
    og = s.get("op_growth")
    og_s = lin_score(og, gcfg["worst_pct"], gcfg["best_pct"])
    gsw = gcfg["sub_weights"]
    comps["growth"] = {"score": _wavg({"eps": (g_s, gsw["eps_growth"]), "op": (og_s, gsw["op_growth"])}),
                       "eps_growth": g, "op_growth": og, "sub": {"eps_growth": g_s, "op_growth": og_s}}

    # 4) 알파 — 실적 서프라이즈 · 수주 · 컨센서스 상향 --------------------
    a = cfg["alpha"]
    sur = s.get("surprise_pct")
    if sur is not None:
        sur_s, sur_kind = lin_score(sur, a["surprise_worst_pct"], a["surprise_best_pct"]), "서프라이즈"
    elif s.get("q_op_yoy") is not None:
        sur_s, sur_kind = lin_score(s["q_op_yoy"], a["q_yoy_worst_pct"], a["q_yoy_best_pct"]), "분기 영업이익 YoY(대리)"
    elif s.get("q_turnaround"):
        sur_s, sur_kind = 80.0, "분기 흑자전환"
    else:
        sur_s, sur_kind = None, None
    od = s.get("orders_pct")
    od_s = lin_score(od, a["orders_worst_pct"], a["orders_best_pct"]) if (s.get("orders_count") or 0) > 0 else None
    rev = s.get("revision_pct")
    rev_s = lin_score(rev, a["revision_worst_pct"], a["revision_best_pct"])
    asw = a["sub_weights"]
    comps["alpha"] = {"score": _wavg({"s": (sur_s, asw["surprise"]), "o": (od_s, asw["orders"]), "r": (rev_s, asw["revision"])}),
                      "surprise": sur, "surprise_kind": sur_kind, "orders_pct": od, "revision": rev,
                      "sub": {"surprise": sur_s, "orders": od_s, "revision": rev_s}}

    # 5) 가격·위험 — 52주 위치, 3개월 수익률, 저변동성 ---------------------
    p = cfg["price_risk"]
    pos = s.get("range_pos")
    pos_s = None if pos is None else clamp((1 - pos) * 100, 0, 100)
    r3 = lin_score(s.get("ret_3m"), p["return_3m_worst_pct"], p["return_3m_best_pct"])
    vol_s = lin_score(s.get("vol_annual"), p["vol_worst_pct"], p["vol_best_pct"])
    psw = p["sub_weights"]
    comps["price_risk"] = {"score": _wavg({"pos": (pos_s, psw["range_position"]), "r3": (r3, psw["return_3m"]),
                                           "vol": (vol_s, psw["low_volatility"])}),
                           "range_pos": pos, "sub": {"range_position": pos_s, "return_3m": r3, "low_volatility": vol_s}}

    for k in comps:
        comps[k]["weight"] = float(W.get(k, 0))
        comps[k]["missing"] = comps[k]["score"] is None

    # 리스크 감점 ---------------------------------------------------------
    rk = cfg["risk"]
    pen = {}
    dil = s.get("dilution_pct")
    pen["dilution"] = None if dil is None else clamp(dil / rk["dilution_full_pct"], 0, 1) * rk["dilution_points"]
    dr = s.get("debt_ratio")
    pen["debt"] = None if dr is None else clamp((dr - rk["debt_ratio_start_pct"]) /
                                                (rk["debt_ratio_full_pct"] - rk["debt_ratio_start_pct"]), 0, 1) * rk["debt_points"]
    memo = s.get("memo_text") or ""
    hits = [kw for kw in rk["memo_keywords"] if kw.lower() in memo.lower()]
    pen["memo"] = min(len(hits) * rk["memo_points_per_keyword"], rk["memo_points_max"])
    penalty = min(sum(x for x in pen.values() if x), rk["max_total"])

    # 총점: 결측 항목은 제외하지 않고 보수적 점수(missing_component_score)로 계산 --------
    total_w = sum(c["weight"] for c in comps.values())
    have_w = sum(c["weight"] for c in comps.values() if c["score"] is not None)
    coverage = have_w / total_w if total_w else 0
    base = _wavg({k: (c["score"] if c["score"] is not None else miss, c["weight"]) for k, c in comps.items()})
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
    # 🔴(매수 금지)는 '비싸다'는 근거가 있을 때만: 데이터가 부족해 점수가 낮은 것은 ⚪(관망)
    if grade == "red" and coverage < gc["min_coverage"] and not (up is not None and up <= 0):
        grade = "white"
        flags.append("데이터 부족으로 관망")

    # 퀄리티 게이트 → 최고 ⚪
    fails = quality_gate(s, cfg)
    if coverage < gc["min_coverage"]:
        fails.append(f"데이터 부족(충족률 {coverage * 100:.0f}%)")
    if fails:
        new = _cap(grade, "white")
        if new != grade:
            flags.append("퀄리티 미달")
        grade = new
    # 떨어지는 칼날 → 최고 🟡
    fk = cfg["falling_knife"]
    knife = (s.get("ret_3m") is not None and s["ret_3m"] <= fk["ret_3m_pct"]
             and bool(s.get("below_ma200")) and not (rev is not None and rev > 0))
    if knife:
        new = _cap(grade, "yellow")
        if new != grade:
            flags.append("하락 추세(떨어지는 칼날)")
        grade = new
    if gc.get("red_if_negative_upside") and up is not None and up <= 0:
        grade = "red"
        flags.append("현재가 ≥ 보수적 목표가")

    result = {
        "total": total, "base": None if base is None else round(base, 1), "penalty": round(penalty, 1),
        "penalty_detail": {k: (None if v is None else round(v, 1)) for k, v in pen.items()},
        "memo_hits": hits, "coverage": round(coverage, 2), "components": comps,
        "grade": grade, "grade_emoji": GRADES[grade]["emoji"], "grade_label": GRADES[grade]["label"],
        "flags": flags, "upside_pct": up, "quality_fails": fails, "falling_knife": bool(knife),
    }
    result["reason"] = reason_line(s, result)
    return result


def _f(x, d=0):
    return f"{x:+.{d}f}%"


def reason_line(s: dict, r: dict) -> str:
    """판단 근거 한 줄: 등급 방향의 핵심 요인 2~3개."""
    c = r["components"]
    pos, neg = [], []
    up = r["upside_pct"]
    if up is not None:
        txt = f"{target_label(s.get('target_source'))} 대비 {_f(up)}"
        (pos if up >= 20 else neg).append((abs(up - 20) + 10, txt))
    mos = c["value"].get("mos")
    if mos is not None and mos >= 15:
        pos.append((mos, f"안전마진 {_f(mos)}"))
    pr = c["value"].get("per_ratio")
    if pr is not None:
        d = (1 - pr) * 100
        txt = f"PER 업종 대비 {abs(d):.0f}% {'할인' if d >= 0 else '할증'}"
        if d >= 15:
            pos.append((d, txt))
        elif d <= -30:
            neg.append((-d / 2, txt))
    elif s.get("per") is not None and s["per"] <= 0:
        neg.append((30, "적자(PER 산출 불가)"))
    a = c["alpha"]
    if a.get("surprise") is not None and abs(a["surprise"]) >= 5:
        (pos if a["surprise"] > 0 else neg).append((abs(a["surprise"]) * 3, f"실적 서프라이즈 {_f(a['surprise'])}"))
    elif s.get("q_op_yoy") is not None and abs(s["q_op_yoy"]) >= 30:
        (pos if s["q_op_yoy"] > 0 else neg).append((min(abs(s["q_op_yoy"]), 100) * 0.4, f"최근 분기 영업이익 YoY {_f(s['q_op_yoy'])}"))
    if (s.get("orders_count") or 0) > 0 and (s.get("orders_pct") or 0) >= 10:
        pos.append((s["orders_pct"], f"최근 수주 공시 매출 대비 {s['orders_pct']:.0f}%"))
    g = c["growth"].get("eps_growth")
    if s.get("turnaround"):
        pos.append((40, "흑자전환 예상"))
    elif g is not None and (g >= 15 or g < 0):
        (pos if g >= 15 else neg).append((min(abs(g), 100) * 0.5, f"{s.get('eps_growth_label') or '예상 EPS'} {_f(g)}"))
    rev = a.get("revision")
    if rev is not None and abs(rev) >= 3:
        (pos if rev > 0 else neg).append((abs(rev) * 3, f"컨센서스 {'상향' if rev > 0 else '하향'} {_f(rev, 1)}"))
    rp = c["price_risk"].get("range_pos")
    if rp is not None and rp >= 0.85:
        neg.append((30 * rp, f"52주 고점권({rp * 100:.0f}%)"))
    if r["falling_knife"]:
        neg.append((40, "하락 추세 지속"))
    for f in r["quality_fails"][:2]:
        neg.append((45, f))
    pd_ = r["penalty_detail"]
    if (pd_.get("dilution") or 0) >= 3:
        neg.append((25, f"잠재 희석 {s.get('dilution_pct', 0):.1f}%"))

    pos.sort(reverse=True)
    neg.sort(reverse=True)
    if r["grade"] in ("green", "yellow"):
        parts = [t for _, t in pos[:2]] + [t for _, t in neg[:1]]
    elif r["grade"] == "red":
        parts = [t for _, t in neg[:2]] + [t for _, t in pos[:1]]
    else:
        parts = [t for _, t in neg[:2]] + [t for _, t in pos[:1]]
    return ", ".join(parts[:3]) if parts else "판단 근거 데이터 부족"
