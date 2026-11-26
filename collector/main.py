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

from . import consensus, market, scoring, strategy, thesis, universe
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
    for k in ("ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol_annual", "low_60d", "low_120d"):
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
        "eps_growth_next": first(est.get("eps_g_next"), est.get("eps_g_cur")),
        "eps_growth_label": r["eps_growth_label"],
        "turnaround": r["turnaround"],
        "revision_pct": r.get("revision_pct"), "range_pos": r["range_pos"],
        "ret_1m": r["ret_1m"], "ret_3m": r["ret_3m"],
        "dilution_pct": r.get("dilution_pct"),
        "debt_ratio": None if r["is_financial"] else r["debt_ratio"],
        "memo_text": ((r.get("sheet") or {}).get("risk") or "") + "\n" + ((r.get("sheet") or {}).get("note") or ""),
    }


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
    snap = find_snapshot(load_history(hist_dir), today, cfg_sc["momentum"]["revision_lookback_days"])
    order = cfg_sc["target"]["source_order"]

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
        mt, mb = thesis.model_target(r, cfg_sc)
        r["model_target"], r["model_basis"] = mt, mb
        options = {"consensus": (r["target_cons"], "컨센서스"), "model": (mt, "모델 적정가"),
                   "club": (r.get("target_club"), "모임")}
        r["target"], r["target_source"] = None, None
        for k in order:
            v, lab = options.get(k, (None, None))
            if v:
                r["target"], r["target_source"] = v, lab
                break
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
    g_order = {"green": 0, "yellow": 1, "white": 2, "red": 3}
    recs.sort(key=lambda r: (g_order[r["score"]["grade"]], -(r["score"]["total"] if r["score"]["total"] is not None else -1)))
    for i, r in enumerate(recs, 1):
        r["rank"] = i

    idx = None
    try:
        idx_daily = market.fetch_daily(sess, cfg_sc["cash"]["index_symbol"], 200)
        idx = market.index_trend(idx_daily, cfg_sc["cash"]["ma_short"], cfg_sc["cash"]["ma_long"])
    except Exception as e:  # noqa: BLE001
        log.warning("코스피 지수 수집 실패: %s", e)
    n_green = sum(1 for r in recs if r["score"]["grade"] == "green")
    cash = strategy.cash_policy(idx, n_green, cfg_sc)
    psize = cfg_sc["strategy"].get("portfolio_size", 15)
    port = [r for r in recs if r["score"]["grade"] in ("green", "yellow")][:psize]
    strategy.portfolio_weights(port, cash["cash_pct"], cfg_sc)
    for r in recs:
        r.setdefault("weight_pct", 0.0)
    cash["effective_cash_pct"] = round(100 - sum(r["weight_pct"] for r in recs), 1)
    cash["portfolio_size"] = psize

    for r in recs:
        if r["price"] and r.get("_daily"):
            r["plan"] = strategy.entry_plan(r["price"], r["_deriv"], cfg_sc)
            r["plan"].update(strategy.exit_plan(r["price"], r["target"], cfg_sc))
        else:
            r["plan"] = None
        r["thesis"] = thesis.build(r)

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
            "weight_pct": r["weight_pct"], "summary": (r.get("summary") or [])[:2], "thesis": r["thesis"],
            "ret_3m": r["ret_3m"], "range_pos": r["range_pos"],
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
        "dart_enabled": dart.enabled, "market": idx, "cash": cash,
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
