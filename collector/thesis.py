"""모임 시트의 분석 틀(투자아이디어 · Risk · 목표가 근거 · 비고: 희석·경영진 Check)을
모든 종목에 데이터로 자동 작성한다. 숫자는 수집된 값만 쓰고, 없으면 해당 문장을 만들지 않는다.
"""
from __future__ import annotations

from .scoring import target_label


def _p(x, d=0):
    return f"{x:+.{d}f}%"


def _w(x):
    return f"{x:,.0f}원"


def model_target(r: dict, cfg: dict) -> tuple[float | None, str | None]:
    """컨센서스가 없을 때의 적정가: 업종 중앙 PER × 예상 EPS (보수적 할인 적용)."""
    tc = cfg["target"]
    eps = r.get("fwd_eps")
    bper = (r.get("bench") or {}).get("per")
    if not eps or eps <= 0 or not bper:
        return None, None
    mult = min(bper, tc.get("model_per_cap", 30))
    fair = mult * eps * tc.get("model_haircut", 0.85)
    price = r.get("price")
    cap = tc.get("model_max_upside_pct")
    capped = False
    if price and cap is not None and fair > price * (1 + cap / 100):
        fair, capped = price * (1 + cap / 100), True
    basis = (f"업종 중앙 PER {mult:.1f}배 × {r.get('fwd_basis_short') or '예상'} EPS {eps:,.0f}원"
             f" × 보수적 할인 {tc.get('model_haircut', 0.85):.2f}"
             + (f" (상한: 현재가 +{cap:.0f}%)" if capped else ""))
    return fair, basis


def build(r: dict) -> dict:
    """r: 수집·점수 계산이 끝난 종목 레코드 → 박스별 문장 목록."""
    sc = r["score"]
    est = r.get("est") or {}
    bench = r.get("bench") or {}
    ideas: list[tuple[float, str]] = []
    risks: list[tuple[float, str]] = []

    # ---------- 투자아이디어 (왜 사야 하나)
    up = sc.get("upside_pct")
    if up is not None and up >= 15:
        ideas.append((min(up, 80), f"{target_label(r.get('target_source'))} {_w(r['target'])}까지 {_p(up)} 상승 여력"))
    per, bper = r.get("per"), bench.get("per")
    if per and per > 0 and bper:
        d = (1 - per / bper) * 100
        if d >= 15:
            ideas.append((d, f"PER {per:.1f}배로 업종({r.get('sector')}) 중앙값 {bper:.1f}배보다 {d:.0f}% 저평가"))
        elif d <= -40:
            risks.append((min(-d, 80) / 2, f"PER {per:.1f}배로 업종 중앙값 {bper:.1f}배 대비 {-d:.0f}% 고평가"))
    pbr, bpbr = r.get("pbr"), bench.get("pbr")
    if pbr and pbr > 0 and bpbr:
        d = (1 - pbr / bpbr) * 100
        if d >= 30:
            ideas.append((d * 0.6, f"PBR {pbr:.2f}배, 업종 중앙값 {bpbr:.2f}배 대비 {d:.0f}% 할인"))
    if pbr and 0 < pbr < 1 and (r.get("roe") or 0) >= 8:
        ideas.append((25, f"PBR 1배 미만({pbr:.2f}배)인데 ROE {r['roe']:.1f}% — 자산가치 대비 저평가"))
    g = sc["components"]["momentum"].get("eps_growth")
    lab = r.get("eps_growth_label") or "예상 EPS"
    if r.get("turnaround"):
        ideas.append((45, "적자에서 흑자로 전환 예상(컨센서스)"))
    elif g is not None:
        if g >= 15:
            ideas.append((min(g, 100) * 0.7, f"{lab} 성장률 {_p(g)} (실적 개선)"))
        elif g <= -10:
            risks.append((min(-g, 60), f"{lab} {_p(g)} 감소 예상 (실적 둔화)"))
    op_g = est.get("op_income_g_cur")
    if op_g is not None and op_g >= 30:
        ideas.append((min(op_g, 100) * 0.4, f"{est.get('year')}년 영업이익 {_p(op_g)} 증가 예상"))
    rev = r.get("revision_pct")
    if rev is not None:
        if rev >= 3:
            ideas.append((rev * 4, f"최근 컨센서스 EPS 상향 {_p(rev, 1)}"))
        elif rev <= -3:
            risks.append((-rev * 4, f"최근 컨센서스 EPS 하향 {_p(rev, 1)}"))
    roe = r.get("roe")
    if roe is not None and roe >= 15:
        ideas.append((roe, f"ROE {roe:.1f}% — 높은 자본 효율"))
    dy = r.get("div_yield")
    if dy is not None and dy >= 3:
        ideas.append((dy * 6, f"배당수익률 {dy:.1f}%"))
    rp = r.get("range_pos")
    if rp is not None and rp <= 0.25 and (r.get("ret_3m") or 0) < 0:
        ideas.append((20, f"52주 범위 하단({rp * 100:.0f}%)까지 조정 — 분할매수 구간"))
    dr = r.get("debt_ratio")
    if dr is not None and dr < 50 and not r.get("is_financial"):
        ideas.append((8, f"부채비율 {dr:.0f}%로 재무구조 안정"))

    # ---------- Risk
    if per is not None and per <= 0:
        risks.append((35, "최근 4분기 적자(PER 산출 불가)"))
    if up is not None and up >= 100 and r.get("target_source") == "컨센서스":
        risks.append((30, f"컨센서스 목표가가 현재가의 {1 + up / 100:.1f}배 — 최근 급락을 목표가가 아직 반영 못 했을 수 있음"))
    if up is not None and up < 0:
        risks.append((60, f"현재가가 목표가({_w(r['target'])})를 {(-up):.0f}% 웃돎"))
    if r.get("target_source") == "모델 적정가":
        risks.append((15, "증권사 커버리지 없음 — 목표가는 업종 PER 기반 추정치"))
    elif r.get("target") is None:
        risks.append((20, "목표가 산출 불가(컨센서스·이익 추정치 없음)"))
    if rp is not None and rp >= 0.85:
        risks.append((25, f"52주 고점권({rp * 100:.0f}%) — 추격매수 주의"))
    r3 = r.get("ret_3m")
    if r3 is not None and r3 >= 40:
        risks.append((r3 / 2, f"3개월 {_p(r3)} 급등"))
    if dr is not None and not r.get("is_financial") and dr >= 150:
        risks.append((min(dr / 10, 40), f"부채비율 {dr:.0f}%"))
    dil = r.get("dilution_pct")
    if dil is not None and dil >= 3:
        risks.append((min(dil * 3, 50), f"CB·BW·유상증자 잠재 희석 {dil:.1f}% (DART)"))
    vol = r.get("vol_annual")
    if vol is not None and vol >= 60:
        risks.append((vol / 4, f"변동성 높음(연 {vol:.0f}%)"))
    if (r.get("mcap_eok") or 0) < 3000:
        risks.append((10, f"소형주(시총 {r.get('mcap_eok', 0):,.0f}억) — 유동성·정보 비대칭"))
    for kw in sc.get("memo_hits") or []:
        risks.append((12, f"모임 메모 리스크: {kw}"))

    ideas.sort(key=lambda x: -x[0])
    risks.sort(key=lambda x: -x[0])

    # ---------- 목표가 근거
    tbasis = []
    if r.get("target_cons"):
        tbasis.append(f"증권사 컨센서스 평균 {_w(r['target_cons'])}" + (f" ({r['cons_date']})" if r.get("cons_date") else ""))
    if r.get("model_target"):
        tbasis.append(f"모델 적정가 {_w(r['model_target'])} = {r.get('model_basis')}")
    if r.get("target_club"):
        tbasis.append(f"모임 발표 목표가 {_w(r['target_club'])}")
    if r.get("fwd_per"):
        tbasis.append(f"현재 Forward PER {r['fwd_per']:.1f}배 ({r.get('fwd_basis') or ''})")

    # ---------- 체크포인트 (시트 '비고: 주가희석요소 및 경영진 Check 필수')
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
    return {
        "ideas": [t for _, t in ideas[:5]],
        "risks": [t for _, t in risks[:5]],
        "target_basis": tbasis,
        "checks": checks,
    }
