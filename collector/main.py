"""데이터 갱신 진입점:  python -m collector.main

1) 모임 시트 읽기(실패 시 중단)  2) 코스피·코스닥 전체 목록 + 업종 분류
3) 필터 통과 종목 + 모임 발표 종목 상세 수집(병렬)  4) 업종 벤치마크·목표가·점수
5) 상위 N종목 DART(희석·부채·대주주) 반영 후 재채점  6) 투자아이디어·Risk·목표가 근거 자동 작성
7) site/data/latest.json, site/data/stock/{code}.json, history 스냅샷 저장
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import consensus, macro, market, scoring, strategy, thesis, universe
from .dart import Dart
from .sheet import club_target, fetch_csv, parse_sheet
from .util import first, log, median, now_kst, pct, session

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
CACHE = ROOT / ".cache"
FINANCIAL_SECTORS = {"은행", "증권", "생명보험", "손해보험", "카드", "기타금융", "창업투자"}

_tls = threading.local()


def tsess():
    if not hasattr(_tls, "s"):
        _tls.s = session()
    return _tls.s


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def clean(o):
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return round(o, 4)
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items() if not str(k).startswith("_") or k == "_src"}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


# ------------------------------------------------------------------ 히스토리(컨센서스 변화 추적)
def load_history(hist_dir: Path) -> list[dict]:
    out = []
    for p in sorted(hist_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return out


def find_snapshot(history: list[dict], today: datetime, lookback: int) -> dict | None:
    best, best_gap = None, None
    for h in history:
        try:
            d = datetime.strptime(h["date"], "%Y-%m-%d")
        except Exception:  # noqa: BLE001
            continue
        age = (today.replace(tzinfo=None) - d).days
        if age < lookback / 2:
            continue
        gap = abs(age - lookback)
        if best_gap is None or gap < best_gap:
            best, best_gap = {**h, "_age": age}, gap
    return best


def revision(code: str, annual: dict, year: int, snap: dict | None) -> tuple[float | None, str | None]:
    if not snap:
        return None, None
    old = (snap.get("items") or {}).get(code, {}).get("eps") or {}
    for y in (year + 1, year):
        now_v = (annual.get(str(y)) or {}).get("eps")
        old_v = old.get(str(y))
        if now_v is not None and old_v not in (None, 0) and old_v > 0:
            return (now_v / old_v - 1) * 100, f"{y}년 EPS 추정치, {snap['_age']}일 전 대비"
    return None, None


def surprise(code: str, quarters: dict, history: list[dict]) -> tuple[float | None, str | None]:
    """최근 확정 분기 영업이익 ÷ (발표 전 마지막으로 저장된 그 분기 컨센서스) − 1."""
    act = sorted(k for k, v in quarters.items() if not v.get("estimate"))
    if not act:
        return None, None
    k = act[-1]
    actual = quarters[k].get("op_income")
    est = None
    for h in sorted(history, key=lambda x: x.get("date", "")):
        v = ((h.get("items") or {}).get(code) or {}).get("q", {}).get(k)
        if v is not None:
            est = v  # 가장 최근(=발표 직전) 스냅샷 값이 남는다
    if actual is None or not est or est <= 0:
        return None, None
    return (actual / est - 1) * 100, k


# ------------------------------------------------------------------ 종목 1개 수집
def collect_one(base: dict, st, today: datetime, cfg_set: dict) -> dict:
    """base: 전체 목록의 한 줄(현재가·시총 포함). st: 모임 시트 종목(없으면 None)."""
    code = base["code"]
    sess = tsess()
    errors: list[str] = []
    rec: dict = {"code": code, "name": base.get("name") or (st.name if st else code), "market": base.get("market"),
                 "sources": {}, "club": st is not None}

    nv = {}
    try:
        nv = market.fetch_naver_summary(sess, code, with_basic=base.get("price") is None)
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 지표: {e}")

    daily = None
    try:
        daily = market.fetch_daily(sess, code, cfg_set["collect"]["daily_count"])
        rec["sources"]["chart"] = "네이버 일봉"
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 일봉: {e}")
    deriv = market.derive_from_daily(daily) if daily else {}

    annual, summary = {}, []
    try:
        annual, summary = consensus.fetch_finance(sess, code)
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 재무·컨센서스: {e}")
    quarters = {}
    try:
        quarters = consensus.fetch_quarter(sess, code)
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 분기 실적: {e}")

    price = first(base.get("price"), nv.get("price"), deriv.get("last_close"), st.sheet_price if st else None)
    if base.get("price") or nv.get("price"):
        rec["sources"]["price"] = "네이버"
    elif deriv.get("last_close"):
        rec["sources"]["price"] = "일봉 종가"
    elif price:
        rec["sources"]["price"] = "시트"
    rec.update(price=price, change_pct=first(base.get("change_pct"), nv.get("change_pct")),
               price_time=first(base.get("price_time"), nv.get("price_time"), deriv.get("last_date")))
    rec["is_etf"] = base.get("end_type") == "etf" or (nv.get("stock_type") or "").lower() == "etf"
    rec["summary"] = summary

    est = consensus.estimates_for(annual, today.year)
    rec["annual"] = {y: annual[y] for y in sorted(annual)[-5:]}
    rec["est"] = est
    rec["quarters"] = quarters
    qs = consensus.quarter_signals(quarters)
    rec.update(last_q=qs.get("last_q"), next_q=qs.get("next_q"), next_op_est=qs.get("next_op_est"),
               q_op_yoy=qs.get("op_yoy"), q_op_qoq=qs.get("op_qoq"), q_turnaround=qs.get("op_turnaround"))
    actual_years = sorted(y for y, v in annual.items() if not v.get("estimate"))
    rec["op_income_last"] = annual[actual_years[-1]].get("op_income") if actual_years else None
    rec["op_growth"] = first(est.get("op_income_g_next"), est.get("op_income_g_cur"))

    eps_cur, eps_next = est["cur"].get("eps"), est["next"].get("eps")
    fwd_eps, fwd_basis, short = None, None, None
    if eps_cur is not None and eps_next is not None:
        w = (12 - today.month) / 12
        fwd_eps, fwd_basis, short = w * eps_cur + (1 - w) * eps_next, "12개월 선행", "12M 선행"
    elif eps_next is not None:
        fwd_eps, fwd_basis, short = eps_next, f"{today.year + 1}E", f"{today.year + 1}E"
    elif eps_cur is not None and est["cur"].get("estimate"):
        fwd_eps, fwd_basis, short = eps_cur, f"{today.year}E", f"{today.year}E"
    fwd_per = price / fwd_eps if (price and fwd_eps) else None
    if fwd_per is None and nv.get("fwd_per_naver") is not None:
        fwd_per, fwd_basis = nv["fwd_per_naver"], "네이버 추정PER"
    rec.update(per=first(nv.get("per"), st.sheet_per if st else None), pbr=nv.get("pbr"),
               fwd_eps=fwd_eps, fwd_per=fwd_per, fwd_basis=fwd_basis, fwd_basis_short=short,
               roe=first(est["prev"].get("roe"), est["cur"].get("roe")),
               div_yield=nv.get("div_yield"),
               mcap_eok=first(base.get("mcap_eok"), nv.get("mcap_eok"), st.sheet_mcap if st else None),
               debt_ratio=first(est["prev"].get("debt_ratio"), est["cur"].get("debt_ratio")))
    rec["debt_basis"] = "네이버 연간 재무" if rec["debt_ratio"] is not None else None

    hi = first(nv.get("high52"), deriv.get("high52_calc"))
    lo = first(nv.get("low52"), deriv.get("low52_calc"))
    rec.update(high52=hi, low52=lo)
    rec["range_pos"] = ((price - lo) / (hi - lo)) if (price and hi and lo and hi > lo) else None
    for k in ("ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol_annual", "low_60d", "low_120d", "ma200", "below_ma200"):
        rec[k] = deriv.get(k)

    rec["target_cons"] = nv.get("cons_target")
    rec["cons_date"] = nv.get("cons_date")
    rec["cons_opinion"] = nv.get("cons_opinion")

    if st:  # 모임 발표 종목
        ct, _ = club_target(st)
        rec["target_club"] = ct
        rec["club_sector"] = st.sector
        pitches = []
        for p in st.pitches:
            base_px = p.price_at_pitch or (market.price_on_or_after(daily, p.date) if daily else None)
            pitches.append({"presenter": p.presenter, "date": p.date, "price_at_pitch": base_px,
                            "target": p.target, "target_raw": p.target_raw, "return_since": pct(price, base_px)})
        rec["pitches"] = pitches
        rec["sheet"] = {"idea": st.idea, "risk": st.risk, "basis": st.basis, "note": st.note, "qna": st.qna, "etc": st.etc}
    else:
        rec["target_club"] = None
    rec["errors"] = errors
    rec["_daily"] = daily
    rec["_deriv"] = deriv
    return rec


# ------------------------------------------------------------------ 업종 벤치마크
def sector_stats(recs: list[dict]) -> dict:
    groups: dict[str, list] = {}
    for r in recs:
        groups.setdefault(r["sector"], []).append(r)
    out = {}
    for sec, rs in groups.items():
        pers = [r["per"] for r in rs if r.get("per") and 0 < r["per"] < 200]
        pbrs = [r["pbr"] for r in rs if r.get("pbr") and 0 < r["pbr"] < 30]
        out[sec] = {"n": len(rs), "per_median": median(pers), "n_per": len(pers),
                    "pbr_median": median(pbrs), "n_pbr": len(pbrs),
                    "per_mean": (sum(pers) / len(pers)) if pers else None,
                    "pbr_mean": (sum(pbrs) / len(pbrs)) if pbrs else None,
                    "codes": [r["code"] for r in rs]}
    return out


def score_input(r: dict) -> dict:
    est = r["est"]
    return {
        "price": r["price"], "target": r["target"], "target_source": r["target_source"],
        "per": r["per"], "pbr": r["pbr"], "fwd_per": r["fwd_per"],
        "bench_per": r["bench"]["per"], "bench_pbr": r["bench"]["pbr"],
        "eps_growth": first(est.get("eps_g_next"), est.get("eps_g_cur")),
        "eps_growth_label": r["eps_growth_label"],
        "op_growth": r.get("op_growth"), "turnaround": r["turnaround"],
        "mos_pct": r.get("mos_pct"), "roe": r.get("roe"), "has_consensus": bool(r.get("target_cons")), "op_income_last": r.get("op_income_last"),
        "surprise_pct": r.get("surprise_pct"), "q_op_yoy": r.get("q_op_yoy"), "q_turnaround": r.get("q_turnaround"),
        "orders_pct": (r.get("orders") or {}).get("sum_pct_of_sales"), "orders_count": (r.get("orders") or {}).get("count"),
        "revision_pct": r.get("revision_pct"), "range_pos": r["range_pos"],
        "ret_1m": r["ret_1m"], "ret_3m": r["ret_3m"], "vol_annual": r.get("vol_annual"),
        "below_ma200": r.get("below_ma200"),
        "dilution_pct": r.get("dilution_pct"),
        "debt_ratio": None if r["is_financial"] else r["debt_ratio"],
        "memo_text": ((r.get("sheet") or {}).get("risk") or "") + "\n" + ((r.get("sheet") or {}).get("note") or ""),
    }


def apply_grade_caps(recs: list[dict], gcfg: dict) -> None:
    """🟢·🟡 정원: 점수순으로 상위만 유지하고 넘치는 종목은 한 단계 내린다."""
    caps = {"green": gcfg.get("max_green"), "yellow": gcfg.get("max_yellow")}
    lower = {"green": "yellow", "yellow": "white"}
    for g in ("green", "yellow"):
        cap = caps[g]
        if not cap:
            continue
        L = sorted([r for r in recs if r["score"]["grade"] == g], key=lambda r: -(r["score"]["total"] or 0))
        for r in L[cap:]:
            sc = r["score"]
            sc["grade"] = lower[g]
            sc["grade_emoji"] = scoring.GRADES[lower[g]]["emoji"]
            sc["grade_label"] = scoring.GRADES[lower[g]]["label"]
            sc["flags"] = list(sc.get("flags") or []) + [f"{scoring.GRADES[g]['emoji']} 정원({cap}) 초과"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="테스트용: 유니버스 앞 N종목만(+모임 종목)")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg_set = load_yaml(ROOT / "config" / "settings.yaml")
    cfg_sc = load_yaml(ROOT / "config" / "scoring.yaml")
    ucfg = cfg_set["universe"]
    out_dir = Path(args.out)
    sess = session()
    today = now_kst()

    # 1) 시트 --------------------------------------------------------------
    try:
        text = fetch_csv(sess, cfg_set["sheet"]["id"], cfg_set["sheet"]["gid"])
        club_stocks, sheet_stats = parse_sheet(text)
    except Exception as e:  # noqa: BLE001
        log.error("시트 읽기 실패 → 갱신 중단(기존 데이터 유지): %s", e)
        return 2
    club = {s.code: s for s in club_stocks}

    # 2) 전체 목록 + 업종 ---------------------------------------------------
    try:
        listing = universe.fetch_listing(sess)
    except Exception as e:  # noqa: BLE001
        log.error("전체 종목 목록 수집 실패 → 중단: %s", e)
        return 3
    if len(listing) < ucfg.get("min_listing", 1000):
        log.error("전체 목록이 %d건뿐 → 비정상으로 보고 중단", len(listing))
        return 3
    try:
        industry = universe.fetch_industries(sess)
    except Exception as e:  # noqa: BLE001
        log.warning("업종 분류 실패: %s", e)
        industry = {}

    by_code = {it["code"]: it for it in listing}
    excluded: dict[str, int] = {}
    cands = []
    for it in listing:
        why = universe.is_excluded(it, ucfg)
        if why and it["code"] not in club:
            excluded[why] = excluded.get(why, 0) + 1
            continue
        cands.append(it)
    for code, st in club.items():  # 목록에 없는 모임 종목(코드 변경 등)
        if code not in by_code:
            cands.append({"code": code, "name": st.name, "market": st.market_hint, "price": None})
    if args.limit:
        cands = cands[: args.limit] + [c for c in cands[args.limit:] if c["code"] in club]
    log.info("유니버스: 전체 %d → 분석 대상 %d (제외 %s)", len(listing), len(cands), excluded)

    # 3) 상세 수집(병렬) ----------------------------------------------------
    recs = []
    with ThreadPoolExecutor(max_workers=ucfg.get("workers", 8)) as ex:
        futs = [ex.submit(collect_one, c, club.get(c["code"]), today, cfg_set) for c in cands]
        for i, f in enumerate(futs, 1):
            try:
                recs.append(f.result())
            except Exception as e:  # noqa: BLE001
                log.warning("수집 실패 %s: %s", cands[i - 1]["code"], e)
            if i % 200 == 0:
                log.info("상세 수집 %d/%d", i, len(cands))
    have = sum(1 for r in recs if r["price"] and r.get("_daily"))
    if not recs or have / len(recs) < cfg_set["collect"]["min_price_coverage"]:
        log.error("시세 수집률 %.0f%% → 비정상으로 보고 중단", (have / max(1, len(recs))) * 100)
        return 3

    for r in recs:
        r["sector"] = industry.get(r["code"]) or (club[r["code"]].sector if r["code"] in club else None) or "미분류"
        r["is_financial"] = r["sector"] in FINANCIAL_SECTORS

    # 4) 벤치마크·목표가·점수 ----------------------------------------------
    min_n = cfg_sc["valuation"]["sector_min_members"]
    secstats = sector_stats(recs)
    all_per = median([r["per"] for r in recs if r.get("per") and 0 < r["per"] < 200])
    all_pbr = median([r["pbr"] for r in recs if r.get("pbr") and 0 < r["pbr"] < 30])
    hist_dir = out_dir / "history"
    history = load_history(hist_dir)
    snap = find_snapshot(history, today, cfg_sc["alpha"]["revision_lookback_days"])

    def score_all(rs):
        for r in rs:
            r["score"] = scoring.score_stock(score_input(r), cfg_sc)

    for r in recs:
        ss = secstats[r["sector"]]
        if ss["n_per"] >= min_n:
            bper, bper_src = ss["per_median"], f"{r['sector']} 업종 중앙값({ss['n_per']}종목)"
        else:
            bper, bper_src = all_per, "전체 종목 중앙값"
        if ss["n_pbr"] >= min_n:
            bpbr, bpbr_src = ss["pbr_median"], f"{r['sector']} 업종 중앙값({ss['n_pbr']}종목)"
        else:
            bpbr, bpbr_src = all_pbr, "전체 종목 중앙값"
        r["bench"] = {"per": bper, "per_src": bper_src, "pbr": bpbr, "pbr_src": bpbr_src}
        r["intrinsic"], r["intrinsic_basis"] = thesis.intrinsic_value(r, cfg_sc)
        r["mos_pct"] = (r["intrinsic"] / r["price"] - 1) * 100 if (r["intrinsic"] and r["price"]) else None
        r["intrinsic_outlier"] = False
        if r["mos_pct"] is not None and r["mos_pct"] > cfg_sc["target"].get("intrinsic_outlier_pct", 300):
            # 내재가치가 현재가의 4배 초과 → 이익 급변·일회성 가능성: 보수적으로 내재가치를 쓰지 않는다
            r["intrinsic_outlier"], r["intrinsic"], r["mos_pct"] = True, None, None
        r["target"], r["target_source"] = thesis.conservative_target(r, cfg_sc)
        r["surprise_pct"], r["surprise_q"] = surprise(r["code"], r["quarters"], history)
        r["orders"] = None
        est = r["est"]
        r["eps_growth_label"] = f"{today.year + 1}E EPS" if est.get("eps_g_next") is not None else f"{today.year}E EPS"
        r["turnaround"] = bool(est.get("turnaround_next") or (est.get("eps_g_next") is None and est.get("turnaround_cur")))
        r["revision_pct"], r["revision_basis"] = revision(r["code"], r["annual"], today.year, snap)
        r["dilution_pct"] = None
    score_all(recs)

    # 5) DART: 상위 N + 모임 종목 -------------------------------------------
    dart = Dart(sess, CACHE)
    for r in recs:
        r["dart"] = {"enabled": dart.enabled}
    if dart.enabled:
        top_n = cfg_sc["risk"].get("dart_top_n", 60)
        ranked = sorted(recs, key=lambda r: -(r["score"]["total"] or 0))
        targets = {r["code"] for r in ranked[:top_n]} | set(club)
        try:
            dart.corp_code("005930")  # 고유번호 파일을 한 번만 받아 둔다
        except Exception as e:  # noqa: BLE001
            log.warning("DART 고유번호 파일 실패: %s", e)
            targets = set()

        def do_dart(r):
            try:
                corp = dart.corp_code(r["code"])
                if not corp:
                    raise RuntimeError("DART 고유번호 없음(ETF·리츠 등)")
                d = Dart(tsess(), CACHE)
                d._corp = dart._corp
                fin = d.financials(corp, today)
                dil = d.dilution(corp, today, cfg_sc["risk"]["cb_lookback_years"], cfg_sc["risk"]["rights_lookback_years"])
                hold = d.major_holder(corp, today)
                try:
                    r["orders"] = d.orders(corp, today, cfg_sc["alpha"]["orders_months"])
                except Exception as e:  # noqa: BLE001
                    r["errors"].append(f"DART 수주 공시: {e}")
                r["dart"].update(corp_code=corp, financials=fin, dilution=dil, holder=hold)
                r["dilution_pct"] = dil.get("potential_pct")
                if fin.get("debt_ratio") is not None:
                    r["debt_ratio"], r["debt_basis"] = fin["debt_ratio"], "DART " + fin.get("debt_ratio_basis", "")
            except Exception as e:  # noqa: BLE001
                r["errors"].append(f"DART: {e}")

        sel = [r for r in recs if r["code"] in targets]
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(do_dart, sel))
        score_all(sel)
        log.info("DART 반영: %d종목", len(sel))

    # 6) 순위·현금·비중·전략·투자논리 ----------------------------------------
    apply_grade_caps(recs, cfg_sc["grades"])
    recs.sort(key=lambda r: -(r["score"]["total"] if r["score"]["total"] is not None else -1))  # 순수 점수순
    for i, r in enumerate(recs, 1):
        r["rank"] = i

    idx = None
    index_series = {}
    for sym in ("KOSPI", "KOSDAQ"):
        try:
            dd = market.fetch_daily(sess, sym, 300)
            closes = [r[4] for r in dd]
            ma = lambda n, i: (sum(closes[i - n + 1:i + 1]) / n) if i >= n - 1 else None  # noqa: E731
            index_series[sym] = {"rows": [[r[0], r[4], ma(60, i), ma(120, i)] for i, r in enumerate(dd)][-250:],
                                 "change_pct": (closes[-1] / closes[-2] - 1) * 100 if len(closes) > 1 else None}
            if sym == cfg_sc["cash"]["index_symbol"]:
                idx = market.index_trend(dd, cfg_sc["cash"]["ma_short"], cfg_sc["cash"]["ma_long"])
        except Exception as e:  # noqa: BLE001
            log.warning("%s 지수 수집 실패: %s", sym, e)
    mac = macro.fetch_macro(sess)
    mac_adj = macro.macro_adjust(mac, cfg_sc["cash"]["macro"])
    n_green = sum(1 for r in recs if r["score"]["grade"] == "green")
    cash = strategy.cash_policy(idx, n_green, cfg_sc, mac_adj)
    port = strategy.portfolio_weights(recs, cash["cash_pct"], cfg_sc)
    cash["effective_cash_pct"] = round(100 - sum(r["weight_pct"] for r in recs), 1)
    cash["portfolio_size"] = len(port["core"]) + len(port["satellite"])
    port["allocation"] = strategy.asset_allocation(recs, port, cash["cash_pct"], mac, cfg_sc)

    for r in recs:
        if r["price"] and r.get("_daily"):
            r["plan"] = strategy.entry_plan(r["price"], r["_deriv"], cfg_sc)
            r["plan"].update(strategy.exit_plan(r["price"], r["target"], cfg_sc))
        else:
            r["plan"] = None
        r["thesis"] = thesis.build(r, mac_adj[1])
        r["process"] = thesis.process(r, cfg_sc)
        r["sensitivity"] = thesis.sensitivity(r, cfg_sc)

    # 7) 저장 -------------------------------------------------------------
    sdir = out_dir / "stock"
    sdir.mkdir(parents=True, exist_ok=True)
    hist_dir.mkdir(parents=True, exist_ok=True)
    chart_days = cfg_set["collect"]["chart_days"]
    live = set()
    for r in recs:
        daily = r.pop("_daily", None)
        r.pop("_deriv", None)
        r["has_chart"] = bool(daily)
        r["_spark"] = [round(x[4]) for x in daily[-120::3]] if daily else None
        detail = {**r, "chart": daily[-chart_days:] if daily else None}
        (sdir / f"{r['code']}.json").write_text(json.dumps(clean(detail), ensure_ascii=False, allow_nan=False),
                                                encoding="utf-8")
        live.add(r["code"])
    for p in sdir.glob("*.json"):
        if p.stem not in live:
            p.unlink()

    def brief(r):
        sc = r["score"]
        pl = r.get("plan") or {}
        ent = pl.get("entries") or []
        return {
            "code": r["code"], "name": r["name"], "market": r["market"], "sector": r["sector"], "club": r["club"],
            "club_sector": r.get("club_sector"), "rank": r["rank"], "price": r["price"], "change_pct": r["change_pct"],
            "mcap_eok": r["mcap_eok"], "per": r["per"], "pbr": r["pbr"], "fwd_per": r["fwd_per"], "roe": r["roe"],
            "div_yield": r["div_yield"], "target": r["target"], "target_source": r["target_source"],
            "weight_pct": r["weight_pct"], "bucket": r.get("bucket"), "summary": (r.get("summary") or [])[:2],
            "thesis": r["thesis"], "mos_pct": r.get("mos_pct"), "intrinsic": r.get("intrinsic"),
            "alpha": {"surprise": r.get("surprise_pct"), "surprise_q": r.get("surprise_q"), "q_op_yoy": r.get("q_op_yoy"),
                      "last_q": r.get("last_q"), "orders": (r.get("orders") or {}).get("count"),
                      "orders_pct": (r.get("orders") or {}).get("sum_pct_of_sales"), "revision": r.get("revision_pct"),
                      "quality_ok": not sc.get("quality_fails"), "knife": sc.get("falling_knife"),
                      "low_vol": (r.get("vol_annual") or 99) <= 30},
            "ret_1w": r.get("ret_1w"), "ret_1m": r.get("ret_1m"), "ret_3m": r["ret_3m"], "ret_6m": r.get("ret_6m"),
            "ret_12m": r.get("ret_12m"), "range_pos": r["range_pos"], "vol_annual": r.get("vol_annual"),
            "spark": r.get("_spark"),
            "comps": {k: (None if v["score"] is None else round(v["score"])) for k, v in sc["components"].items()},
            "plan": ({"entry1": ent[0]["price"] if ent else None, "entry3": ent[-1]["price"] if ent else None,
                      "stop": pl.get("stop"), "tp1": pl.get("tp1"), "tp2": pl.get("tp2")} if pl else None),
            "score": {k: sc[k] for k in ("total", "grade", "grade_emoji", "grade_label", "reason", "upside_pct",
                                         "coverage", "flags")},
        }

    price_dates = sorted({str(r["price_time"])[:10] for r in recs if r.get("price_time")})
    meta = {
        "generated_at": today.strftime("%Y-%m-%d %H:%M KST"),
        "price_as_of": price_dates[-1] if price_dates else None,
        "universe": {"listed": len(listing), "analyzed": len(recs), "excluded": excluded, "filters": ucfg},
        "sheet": {"rows": sheet_stats["rows"], "club_stocks": len(club), "excluded": sheet_stats["foreign_or_no_ticker"]},
        "dart_enabled": dart.enabled, "market": idx, "cash": cash, "macro": mac, "index_series": index_series,
        "portfolio": port,
        "grade_counts": {g: sum(1 for r in recs if r["score"]["grade"] == g) for g in scoring.GRADES},
        "revision_snapshot_age_days": snap["_age"] if snap else None,
        "config": cfg_sc,
    }
    sec_out = {k: {kk: vv for kk, vv in v.items() if kk != "codes"} for k, v in secstats.items()}
    payload = {"meta": meta, "sectors": sec_out, "stocks": [brief(r) for r in recs]}
    (out_dir / "latest.json").write_text(json.dumps(clean(payload), ensure_ascii=False, allow_nan=False),
                                         encoding="utf-8")
    old_prices = out_dir / "prices"  # 이전 버전 차트 폴더 정리
    if old_prices.exists():
        for p in old_prices.glob("*.json"):
            p.unlink()
        old_prices.rmdir()

    snap_today = {"date": today.strftime("%Y-%m-%d"),
                  "items": {r["code"]: {"eps": {y: v.get("eps") for y, v in r["annual"].items() if v.get("estimate")},
                                        "q": {k: v.get("op_income") for k, v in (r.get("quarters") or {}).items()
                                              if v.get("estimate") and v.get("op_income") is not None},
                                        "target_cons": r["target_cons"]} for r in recs}}
    (hist_dir / f"{snap_today['date']}.json").write_text(
        json.dumps(clean(snap_today), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    keep = today.replace(tzinfo=None) - timedelta(days=cfg_set["collect"]["history_keep_days"])
    for p in hist_dir.glob("*.json"):
        try:
            if datetime.strptime(p.stem, "%Y-%m-%d") < keep:
                p.unlink()
        except ValueError:
            pass

    log.info("완료: 분석 %d종목, 🟢%d 🟡%d ⚪%d 🔴%d, 권장 현금 %.0f%%", len(recs), *meta["grade_counts"].values(),
             cash["cash_pct"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
