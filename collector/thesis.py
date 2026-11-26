"""모임 시트의 분석 틀(투자아이디어 · Risk · 목표가 근거 · 비고: 희석·경영진 Check)과
모임 자료(실적 vs 컨센서스, 수주잔고, EPS 감익×PER 밸류에이션 점검, 불안요소)를 모든 종목에 적용한다.
숫자는 수집된 값만 쓰고, 없으면 해당 문장을 만들지 않는다.
"""
from __future__ import annotations

from .scoring import target_label


def _p(x, d=0):
    return f"{x:+.{d}f}%"


def _w(x):
    return f"{x:,.0f}원"


# ------------------------------------------------------------------ 목표가
def intrinsic_value(r: dict, cfg: dict) -> tuple[float | None, str | None]:
    """내재가치 = 예상 EPS × (1 − 감익 가정) × 업종 중앙 PER(상한)."""
    tc = cfg["target"]
    eps = r.get("fwd_eps")
    bper = (r.get("bench") or {}).get("per")
    if not eps or eps <= 0 or not bper:
        return None, None
    mult = min(bper, tc["intrinsic_per_cap"])
    cut = tc["intrinsic_eps_haircut"]
    val = eps * (1 - cut) * mult
    basis = f"{r.get('fwd_basis_short') or '예상'} EPS {eps:,.0f}원 × (1−{cut * 100:.0f}% 감익 가정) × 업종 중앙 PER {mult:.1f}배"
    return val, basis


def conservative_target(r: dict, cfg: dict) -> tuple[float | None, str | None]:
    tc = cfg["target"]
    cons = r.get("target_cons")
    iv = r.get("intrinsic")
    price = r.get("price")
    if tc.get("mode") == "consensus_first":
        for k in tc["source_order"]:
            v = {"consensus": cons, "model": iv, "club": r.get("target_club")}.get(k)
            if v:
                return v, {"consensus": "컨센서스", "model": "내재가치", "club": "모임"}[k]
        return None, None
    cons_h = cons * tc["consensus_haircut"] if cons else None
    if cons_h and iv:
        return (cons_h, "보수적 목표가") if cons_h <= iv else (iv, "내재가치")
    if cons_h:
        return cons_h, "보수적 목표가"
    if iv:
        cap = tc.get("model_max_upside_pct")
        if price and cap is not None and iv > price * (1 + cap / 100):
            return price * (1 + cap / 100), "내재가치(상한)"
        return iv, "내재가치"
    return None, None


def sensitivity(r: dict, cfg: dict) -> dict | None:
    """모임 자료의 '목표가 민감도(EPS 감익 × PER)' 표."""
    eps, bper, price = r.get("fwd_eps"), (r.get("bench") or {}).get("per"), r.get("price")
    if not eps or eps <= 0 or not bper or not price:
        return None
    tc = cfg["target"]
    pers = [round(bper * m, 1) for m in tc["sensitivity_per_mults"]]
    rows = []
    for cut in tc["sensitivity_eps_cuts"]:
        vals = [eps * (1 + cut / 100) * p for p in pers]
        rows.append({"eps_cut": cut, "values": vals, "upside": [(v / price - 1) * 100 for v in vals]})
    return {"eps": eps, "pers": pers, "rows": rows, "price": price, "basis": r.get("fwd_basis_short")}


# ------------------------------------------------------------------ 선정 프로세스
def process(r: dict, cfg: dict) -> list[dict]:
    sc = r["score"]
    q = cfg["quality"]
    steps = [{"name": "① 유니버스", "ok": True,
              "note": "모임 발표 종목(기준 예외)" if r.get("club_only") else "보통주 · 시총·거래대금 기준 통과"}]
    fails = sc.get("quality_fails") or []
    steps.append({"name": "② 퀄리티", "ok": not fails,
                  "note": "흑자 · ROE ≥ {0}% · 부채 ≤ {1}% · 희석 < {2}%".format(q["min_roe"], q["max_debt_ratio"], q["max_dilution_pct"])
                  if not fails else " / ".join(fails)})
    up = sc.get("upside_pct")
    steps.append({"name": "③ 밸류(안전마진)", "ok": (r.get("mos_pct") if r.get("mos_pct") is not None else -1) >= 0 and (up or -1) > 0,
                  "note": f"안전마진 {_p(r['mos_pct'])}" if r.get("mos_pct") is not None else "내재가치 산출 불가"})
    a = sc["components"]["alpha"]
    bits = []
    if a.get("surprise") is not None:
        bits.append(f"서프라이즈 {_p(a['surprise'], 1)}")
    elif r.get("q_op_yoy") is not None:
        bits.append(f"분기 OP YoY {_p(r['q_op_yoy'])}")
    if (r.get("orders") or {}).get("count"):
        bits.append(f"수주 공시 {r['orders']['count']}건")
    if a.get("revision") is not None:
        bits.append(f"컨센서스 {_p(a['revision'], 1)}")
    steps.append({"name": "④ 알파(실적·수주)", "ok": (a.get("score") or 0) >= 55, "note": " · ".join(bits) or "신호 없음"})
    steps.append({"name": "⑤ 추세·위험", "ok": not sc.get("falling_knife"),
                  "note": "하락 추세(−3점)" if sc.get("falling_knife") else
                  (f"변동성 연 {r['vol_annual']:.0f}%" if r.get("vol_annual") is not None else "")})
    return steps


# ------------------------------------------------------------------ 박스 문장
def build(r: dict, macro_notes: list[str] | None = None) -> dict:
    sc = r["score"]
    bench = r.get("bench") or {}
    ideas: list[tuple[float, str]] = []
    risks: list[tuple[float, str]] = []
    a = sc["components"]["alpha"]

    # ---------- 투자아이디어 (왜 사야 하나)
    up = sc.get("upside_pct")
    if up is not None and up >= 15:
        ideas.append((min(up, 80), f"{target_label(r.get('target_source'))} {_w(r['target'])}까지 {_p(up)} 상승 여력"))
    mos = r.get("mos_pct")
    if mos is not None and mos >= 20:
        ideas.append((mos, f"보수적 내재가치({_w(r['intrinsic'])}) 대비 안전마진 {_p(mos)}"))
    if a.get("surprise") is not None and a["surprise"] >= 5:
        ideas.append((a["surprise"] * 4, f"{r.get('surprise_q')} 영업이익이 컨센서스를 {_p(a['surprise'], 1)} 상회(어닝 서프라이즈)"))
    elif r.get("q_op_yoy") is not None and r["q_op_yoy"] >= 30:
        ideas.append((min(r["q_op_yoy"], 150) * 0.4, f"최근 분기({r.get('last_q')}) 영업이익 YoY {_p(r['q_op_yoy'])}"))
    elif r.get("q_turnaround"):
        ideas.append((35, f"최근 분기({r.get('last_q')}) 영업이익 흑자전환"))
    od = r.get("orders") or {}
    if od.get("count"):
        ideas.append((min(od.get("sum_pct_of_sales") or 5, 60), f"최근 {od.get('months')}개월 수주 공시 {od['count']}건"
                      + (f"(매출 대비 합계 {od['sum_pct_of_sales']:.0f}%)" if od.get("sum_pct_of_sales") else "")))
    rev = r.get("revision_pct")
    if rev is not None and rev >= 3:
        ideas.append((rev * 4, f"최근 컨센서스 EPS 상향 {_p(rev, 1)}"))
    per, bper = r.get("per"), bench.get("per")
    if per and per > 0 and bper:
        d = (1 - per / bper) * 100
        if d >= 15:
            ideas.append((d, f"PER {per:.1f}배로 업종({r.get('sector')}) 중앙값 {bper:.1f}배보다 {d:.0f}% 저평가"))
    pbr = r.get("pbr")
    if pbr and 0 < pbr < 1 and (r.get("roe") or 0) >= 8:
        ideas.append((25, f"PBR {pbr:.2f}배(1배 미만)인데 ROE {r['roe']:.1f}%"))
    g = sc["components"]["growth"].get("eps_growth")
    if r.get("turnaround"):
        ideas.append((40, "적자에서 흑자로 전환 예상(컨센서스)"))
    elif g is not None and g >= 15:
        ideas.append((min(g, 100) * 0.6, f"{r.get('eps_growth_label') or '예상 EPS'} 성장률 {_p(g)}"))
    roe = r.get("roe")
    if roe is not None and roe >= 15:
        ideas.append((roe, f"ROE {roe:.1f}% — 높은 자본 효율"))
    dy = r.get("div_yield")
    if dy is not None and dy >= 3:
        ideas.append((dy * 6, f"배당수익률 {dy:.1f}%"))
    vol = r.get("vol_annual")
    if vol is not None and vol <= 30:
        ideas.append((15, f"저변동성(연 {vol:.0f}%) — 하락장 방어력"))
    dr = r.get("debt_ratio")
    if dr is not None and dr < 50 and not r.get("is_financial"):
        ideas.append((8, f"부채비율 {dr:.0f}%로 재무구조 안정"))

    # ---------- Risk
    for f in sc.get("quality_fails") or []:
        risks.append((60, f"퀄리티 미달(감점): {f}"))
    if sc.get("falling_knife"):
        risks.append((50, f"하락 추세 — 3개월 {_p(r.get('ret_3m') or 0)}, 200일선 아래 (−3점, 분할매수로 접근)"))
    if up is not None and up <= 0:
        risks.append((55, f"현재가가 {target_label(r.get('target_source'))}({_w(r['target'])}) 이상"))
    if r.get("target_cons") and r.get("price") and r["target_cons"] / r["price"] >= 2:
        risks.append((30, f"컨센서스 목표가가 현재가의 {r['target_cons'] / r['price']:.1f}배 — 최근 급락을 아직 반영 못 했을 수 있음"))
    if a.get("surprise") is not None and a["surprise"] <= -5:
        risks.append((abs(a["surprise"]) * 3, f"{r.get('surprise_q')} 영업이익이 컨센서스 대비 {_p(a['surprise'], 1)} (어닝 쇼크)"))
    elif r.get("q_op_yoy") is not None and r["q_op_yoy"] <= -20:
        risks.append((min(-r["q_op_yoy"], 80) * 0.5, f"최근 분기 영업이익 YoY {_p(r['q_op_yoy'])}"))
    if rev is not None and rev <= -3:
        risks.append((-rev * 4, f"최근 컨센서스 EPS 하향 {_p(rev, 1)}"))
    if per and per > 0 and bper and per / bper >= 1.5:
        risks.append((25, f"PER {per:.1f}배로 업종 중앙값 {bper:.1f}배 대비 {(per / bper - 1) * 100:.0f}% 고평가"))
    if g is not None and g <= -10:
        risks.append((min(-g, 60), f"{r.get('eps_growth_label') or '예상 EPS'} {_p(g)} 감소 예상"))
    rp = r.get("range_pos")
    if rp is not None and rp >= 0.85:
        risks.append((25, f"52주 고점권({rp * 100:.0f}%) — 추격매수 주의"))
    dil = r.get("dilution_pct")
    if dil is not None and dil >= 3:
        risks.append((min(dil * 3, 50), f"CB·BW·유상증자 잠재 희석 {dil:.1f}% (DART)"))
    if dr is not None and not r.get("is_financial") and dr >= 150:
        risks.append((min(dr / 10, 40), f"부채비율 {dr:.0f}%"))
    if vol is not None and vol >= 60:
        risks.append((vol / 4, f"변동성 높음(연 {vol:.0f}%)"))
    if r.get("intrinsic_outlier"):
        risks.append((35, "예상 EPS가 현재 주가 대비 비정상적으로 큼(이익 급변·일회성 가능) — 내재가치 미반영"))
    if (r.get("target_source") or "").startswith("내재가치") and not r.get("target_cons"):
        risks.append((15, "증권사 컨센서스 없음 — 목표가는 보수적 내재가치 추정"))
    elif r.get("target") is None:
        risks.append((20, "목표가 산출 불가(컨센서스·이익 추정치 없음)"))
    if (r.get("mcap_eok") or 0) < 3000:
        risks.append((10, f"소형주(시총 {r.get('mcap_eok', 0):,.0f}억) — 유동성·정보 비대칭"))
    for kw in sc.get("memo_hits") or []:
        risks.append((12, f"모임 메모 리스크: {kw}"))

    ideas.sort(key=lambda x: -x[0])
    risks.sort(key=lambda x: -x[0])

    # ---------- 목표가 근거
    tbasis = []
    if r.get("target_source") == "보수적 목표가":
        tbasis.append(f"보수적 목표가 = 컨센서스 {_w(r['target_cons'])} × 0.9 (낙관 편향 할인)")
    if r.get("intrinsic"):
        tbasis.append(f"내재가치 {_w(r['intrinsic'])} = {r.get('intrinsic_basis')}")
    if r.get("target_cons"):
        tbasis.append(f"증권사 컨센서스 평균 {_w(r['target_cons'])}" + (f" ({r['cons_date']})" if r.get("cons_date") else ""))
    if r.get("target_club"):
        tbasis.append(f"모임 발표 목표가 {_w(r['target_club'])}")
    if r.get("fwd_per"):
        tbasis.append(f"현재 Forward PER {r['fwd_per']:.1f}배 ({r.get('fwd_basis') or ''})")

    # ---------- 체크포인트 (시트 '비고: 주가희석요소 및 경영진 Check 필수' + 모임 자료의 불안요소)
    checks = []
    if r.get("dilution_pct") is not None:
        checks.append(f"희석: 최근 CB·BW·유증 결정 합계 {r['dilution_pct']:.1f}% (DART)")
    else:
        checks.append("희석: DART 미조회 — 메자닌·유상증자 공시 직접 확인")
    h = (r.get("dart") or {}).get("holder") or {}
    if h.get("pct") is not None:
        checks.append(f"최대주주 {h.get('name') or ''} 외 특수관계인 {h['pct']:.1f}% ({h.get('basis', '')})")
    else:
        checks.append("경영진·최대주주: 지분 변동·오버행 직접 확인")
    checks.append("자회사 상장(IPO)·블록딜 등 오버행 일정 확인")
    if r.get("next_q"):
        checks.append(f"다음 실적({r['next_q']}) 컨센서스 영업이익 {r['next_op_est']:,.0f}억 — 발표 후 서프라이즈 여부 확인"
                      if r.get("next_op_est") is not None else f"다음 실적({r['next_q']}) 발표 확인")
    for m in macro_notes or []:
        checks.append(f"매크로: {m}")
    return {"ideas": [t for _, t in ideas[:5]], "risks": [t for _, t in risks[:5]],
            "target_basis": tbasis, "checks": checks}
