"""데이터 갱신 진입점:  python -m collector.main

1) 시트 읽기(실패 시 중단) → 2) 시세·실적·공시 수집 → 3) 점수·전략 → 4) site/data/*.json 저장
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import consensus, market, scoring, strategy
from .dart import Dart
from .sheet import club_target, fetch_csv, parse_sheet
from .util import first, log, mean, median, now_kst, pct, session

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
CACHE = ROOT / ".cache"


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def clean(o):
    """JSON 저장용: NaN/inf → None, float 반올림."""
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
def collect_one(sess, st, dart: Dart, today: datetime, cfg_set: dict, cfg_sc: dict) -> dict:
    code = st.code
    errors = []
    rec: dict = {"code": code, "name": st.name, "sector": st.sector or "미분류", "sources": {}}

    nv = {}
    try:
        nv = market.fetch_naver_summary(sess, code)
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 요약: {e}")

    daily = None
    try:
        daily = market.fetch_daily(sess, code, cfg_set["collect"]["daily_count"])
        rec["sources"]["chart"] = "네이버 일봉"
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 일봉: {e}")
        if cfg_set["collect"].get("use_pykrx_fallback"):
            try:
                daily = market.fetch_daily_pykrx(code)
                rec["sources"]["chart"] = "pykrx"
            except Exception as e2:  # noqa: BLE001
                errors.append(f"pykrx 일봉: {e2}")
    deriv = market.derive_from_daily(daily) if daily else {}

    nmain = {}
    try:
        nmain = market.fetch_naver_main(sess, code)
    except Exception as e:  # noqa: BLE001
        errors.append(f"네이버 종목메인: {e}")

    fg = {}
    try:
        fg = consensus.fetch_fnguide(sess, code)
    except Exception as e:  # noqa: BLE001
        errors.append(f"FnGuide: {e}")

    pk = {}
    if (nv.get("per") is None or nv.get("pbr") is None) and cfg_set["collect"].get("use_pykrx_fallback"):
        try:
            pk = market.fetch_pykrx_fundamental(code)
        except Exception as e:  # noqa: BLE001
            errors.append(f"pykrx 지표: {e}")

    # ---- 현재가
    price, psrc = None, None
    if nv.get("price"):
        price, psrc = nv["price"], "네이버"
    elif deriv.get("last_close"):
        price, psrc = deriv["last_close"], f"{rec['sources'].get('chart')} 종가"
    elif st.sheet_price:
        price, psrc = st.sheet_price, "시트(구글파이낸스)"
    rec.update(price=price, change_pct=nv.get("change_pct"),
               price_time=nv.get("price_time") or deriv.get("last_date"))
    rec["sources"]["price"] = psrc
    rec["market"] = nv.get("market") or st.market_hint
    rec["is_etf"] = (nv.get("stock_type") or "").lower() == "etf" or "ETF" in (st.name or "").upper()

    # ---- 실적(연간) 병합: FnGuide 우선, 네이버 보조
    naver_annual = consensus.normalize_years(nmain["annual"]) if nmain.get("annual") else None
    annual = consensus.merge_annual(fg.get("annual"), naver_annual)
    est = consensus.estimates_for(annual, today.year)
    rec["annual"] = {y: annual[y] for y in sorted(annual)[-6:]}
    rec["est"] = est

    # ---- 밸류에이션
    per = first(nv.get("per"), pk.get("per"), st.sheet_per)
    rec["sources"]["per"] = "네이버" if nv.get("per") is not None else "pykrx" if pk.get("per") is not None else ("시트" if st.sheet_per is not None else None)
    pbr = first(nv.get("pbr"), pk.get("pbr"))
    eps_cur, eps_next = est["cur"].get("eps"), est["next"].get("eps")
    fwd_eps, fwd_basis = None, None
    if eps_cur is not None and eps_next is not None:
        w = (12 - today.month) / 12  # 올해 남은 비중
        fwd_eps, fwd_basis = w * eps_cur + (1 - w) * eps_next, f"12개월 선행({today.year}E·{today.year + 1}E 가중)"
    elif eps_next is not None:
        fwd_eps, fwd_basis = eps_next, f"{today.year + 1}E"
    elif eps_cur is not None:
        fwd_eps, fwd_basis = eps_cur, f"{today.year}E"
    fwd_per = price / fwd_eps if (price and fwd_eps) else None
    if fwd_per is None and nv.get("fwd_per_naver") is not None:
        fwd_per, fwd_basis = nv["fwd_per_naver"], "네이버 추정PER"
    roe = first(est["prev"].get("roe"), est["cur"].get("roe"))
    rec.update(per=per, pbr=pbr, fwd_per=fwd_per, fwd_basis=fwd_basis, roe=roe,
               div_yield=first(nv.get("div_yield"), pk.get("div_yield")),
               mcap_eok=first(nv.get("mcap_eok"), st.sheet_mcap),
               industry_per=nmain.get("industry_per"))
    rec["sources"]["mcap"] = "네이버" if nv.get("mcap_eok") else ("시트" if st.sheet_mcap else None)

    # ---- 52주
    hi = first(nv.get("high52"), deriv.get("high52_calc"), st.sheet_high52)
    lo = first(nv.get("low52"), deriv.get("low52_calc"), st.sheet_low52)
    rec.update(high52=hi, low52=lo)
    rec["range_pos"] = ((price - lo) / (hi - lo)) if (price and hi and lo and hi > lo) else None
    for k in ("ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol_annual", "low_60d", "low_120d"):
        rec[k] = deriv.get(k)

    # ---- 목표가
    ct, cpitch = club_target(st)
    cons_t = first(nv.get("cons_target"), fg.get("target"))
    rec["target_club"], rec["target_cons"] = ct, cons_t
    rec["sources"]["target_cons"] = "네이버(FnGuide 컨센서스)" if nv.get("cons_target") else ("FnGuide" if fg.get("target") else None)
    rec["cons_date"] = nv.get("cons_date")
    tgt, tsrc = scoring.pick_target(ct, cons_t, cfg_sc["upside"]["target_source"])
    rec["target"], rec["target_source"] = tgt, tsrc

    # ---- 모임 발표 이력 & 발표일 이후 수익률
    pitches = []
    for p in st.pitches:
        base = p.price_at_pitch or (market.price_on_or_after(daily, p.date) if daily else None)
        pitches.append({"presenter": p.presenter, "date": p.date, "price_at_pitch": base,
                        "target": p.target, "target_raw": p.target_raw, "row_no": p.row_no,
                        "return_since": pct(price, base)})
    rec["pitches"] = pitches
    rec["sheet"] = {"idea": st.idea, "risk": st.risk, "basis": st.basis, "note": st.note,
                    "qna": st.qna, "etc": st.etc}

    # ---- DART
    rec["dart"] = {"enabled": dart.enabled}
    debt = first(est["prev"].get("debt_ratio"), est["cur"].get("debt_ratio"))
    debt_basis = "FnGuide/네이버 연간" if debt is not None else None
    if dart.enabled:
        try:
            corp = dart.corp_code(code)
            if not corp:
                raise RuntimeError("DART 고유번호 없음(ETF·리츠 등)")
            fin = dart.financials(corp, today)
            dil = dart.dilution(corp, today, cfg_sc["risk"]["cb_lookback_years"], cfg_sc["risk"]["rights_lookback_years"])
            hold = dart.major_holder(corp, today)
            rec["dart"].update(corp_code=corp, financials=fin, dilution=dil, holder=hold)
            if fin.get("debt_ratio") is not None:
                debt, debt_basis = fin["debt_ratio"], "DART " + fin.get("debt_ratio_basis", "")
        except Exception as e:  # noqa: BLE001
            errors.append(f"DART: {e}")
    rec["debt_ratio"], rec["debt_basis"] = debt, debt_basis
    rec["errors"] = errors
    rec["_daily"] = daily
    return rec


# ------------------------------------------------------------------ 섹터 벤치마크
def sector_stats(recs: list[dict]) -> dict:
    out = {}
    for r in recs:
        out.setdefault(r["sector"], []).append(r)
    stats = {}
    for sec, rs in out.items():
        pers = [r["per"] for r in rs if r.get("per") and r["per"] > 0]
        pbrs = [r["pbr"] for r in rs if r.get("pbr") and r["pbr"] > 0]
        stats[sec] = {"n": len(rs), "per_mean": mean(pers), "per_median": median(pers), "n_per": len(pers),
                      "pbr_mean": mean(pbrs), "pbr_median": median(pbrs), "n_pbr": len(pbrs),
                      "codes": [r["code"] for r in rs]}
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="테스트용: 앞에서 N개 종목만")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg_set = load_yaml(ROOT / "config" / "settings.yaml")
    cfg_sc = load_yaml(ROOT / "config" / "scoring.yaml")
    out_dir = Path(args.out)
    sess = session()
    today = now_kst()

    # 1) 시트 -------------------------------------------------------------
    try:
        text = fetch_csv(sess, cfg_set["sheet"]["id"], cfg_set["sheet"]["gid"])
        stocks, sheet_stats = parse_sheet(text)
    except Exception as e:  # noqa: BLE001
        log.error("시트 읽기 실패 → 갱신 중단(기존 데이터 유지): %s", e)
        return 2
    if not stocks:
        log.error("시트에서 국내 종목을 하나도 찾지 못했습니다 → 중단")
        return 2
    if args.limit:
        stocks = stocks[: args.limit]

    # 2) 수집 -------------------------------------------------------------
    dart = Dart(sess, CACHE)
    if not dart.enabled:
        log.warning("DART_API_KEY 미설정 → DART 항목은 N/A")
    recs = []
    for i, st in enumerate(stocks, 1):
        log.info("[%d/%d] %s %s", i, len(stocks), st.code, st.name)
        recs.append(collect_one(sess, st, dart, today, cfg_set, cfg_sc))

    have_price = sum(1 for r in recs if r["price"] and r["sources"]["price"] != "시트(구글파이낸스)")
    if have_price / len(recs) < cfg_set["collect"]["min_price_coverage"]:
        log.error("실시간 현재가 수집률 %.0f%% → 비정상으로 보고 갱신 중단(기존 데이터 유지)", have_price / len(recs) * 100)
        return 3

    # 3) 점수 -------------------------------------------------------------
    secstats = sector_stats(recs)
    all_pers = [r["per"] for r in recs if r.get("per") and r["per"] > 0]
    all_pbrs = [r["pbr"] for r in recs if r.get("pbr") and r["pbr"] > 0]
    vcfg = cfg_sc["valuation"]
    hist_dir = out_dir / "history"
    history = load_history(hist_dir)
    snap = find_snapshot(history, today, cfg_sc["momentum"]["revision_lookback_days"])

    for r in recs:
        ss = secstats[r["sector"]]
        if vcfg["sector_benchmark"] == "naver_industry_first" and r.get("industry_per"):
            bper, bper_src = r["industry_per"], "네이버 동일업종 PER"
        elif ss["n_per"] >= vcfg["sector_min_members"]:
            bper, bper_src = ss["per_median"], f"모임 '{r['sector']}' 섹터 중앙값({ss['n_per']}종목)"
        else:
            bper, bper_src = median(all_pers), "모임 전체 종목 중앙값"
        if ss["n_pbr"] >= vcfg["sector_min_members"]:
            bpbr, bpbr_src = ss["pbr_median"], f"모임 '{r['sector']}' 섹터 중앙값({ss['n_pbr']}종목)"
        else:
            bpbr, bpbr_src = median(all_pbrs), "모임 전체 종목 중앙값"
        rev, rev_basis = revision(r["code"], r["annual"], today.year, snap)
        est = r["est"]
        s = {
            "price": r["price"], "target": r["target"], "target_source": r["target_source"],
            "per": r["per"], "pbr": r["pbr"], "fwd_per": r["fwd_per"], "bench_per": bper, "bench_pbr": bpbr,
            "eps_growth_next": est.get("eps_g_next"), "turnaround": est.get("turnaround_next"),
            "revision_pct": rev, "range_pos": r["range_pos"], "ret_1m": r["ret_1m"], "ret_3m": r["ret_3m"],
            "dilution_pct": ((r["dart"].get("dilution") or {}).get("potential_pct") if r["dart"].get("dilution") else None),
            "debt_ratio": r["debt_ratio"],
            "memo_text": (r["sheet"]["risk"] or "") + "\n" + (r["sheet"]["note"] or ""),
        }
        r["bench"] = {"per": bper, "per_src": bper_src, "pbr": bpbr, "pbr_src": bpbr_src}
        r["revision_pct"], r["revision_basis"] = rev, rev_basis
        r["dilution_pct"] = s["dilution_pct"]
        r["score"] = scoring.score_stock(s, cfg_sc)
        if r["price"] and r.get("_daily"):
            deriv = market.derive_from_daily(r["_daily"])
            r["plan"] = strategy.entry_plan(r["price"], deriv, cfg_sc)
            r["plan"].update(strategy.exit_plan(r["price"], r["target"], cfg_sc))
        else:
            r["plan"] = None

    # 4) 시장·현금·비중 ----------------------------------------------------
    idx = None
    try:
        idx_daily = market.fetch_daily(sess, cfg_sc["cash"]["index_symbol"], 200)
        idx = market.index_trend(idx_daily, cfg_sc["cash"]["ma_short"], cfg_sc["cash"]["ma_long"])
    except Exception as e:  # noqa: BLE001
        log.warning("코스피 지수 수집 실패: %s", e)
    n_green = sum(1 for r in recs if r["score"]["grade"] == "green")
    cash = strategy.cash_policy(idx, n_green, cfg_sc)
    strategy.portfolio_weights(recs, cash["cash_pct"], cfg_sc)
    cash["effective_cash_pct"] = round(100 - sum(r["weight_pct"] for r in recs), 1)

    g_order = {"green": 0, "yellow": 1, "white": 2, "red": 3}

    def sort_key(r):  # 등급 우선, 같은 등급 안에서는 총점 순
        t = r["score"]["total"]
        return (g_order[r["score"]["grade"]], -(t if t is not None else -1))
    recs.sort(key=sort_key)
    for i, r in enumerate(recs, 1):
        r["rank"] = i

    # 5) 저장 -------------------------------------------------------------
    (out_dir / "prices").mkdir(parents=True, exist_ok=True)
    hist_dir.mkdir(parents=True, exist_ok=True)
    chart_days = cfg_set["collect"]["chart_days"]
    for r in recs:
        daily = r.pop("_daily", None)
        if daily:
            (out_dir / "prices" / f"{r['code']}.json").write_text(
                json.dumps({"code": r["code"], "rows": daily[-chart_days:]}, ensure_ascii=False), encoding="utf-8")
        r["has_chart"] = bool(daily)

    price_dates = sorted({str(r["price_time"])[:10] for r in recs if r.get("price_time")})
    meta = {
        "generated_at": today.strftime("%Y-%m-%d %H:%M KST"),
        "price_as_of": price_dates[-1] if price_dates else None,
        "sheet": {"rows": sheet_stats["rows"], "domestic_rows": sheet_stats["domestic_rows"],
                  "stocks": len(recs), "excluded": sheet_stats["foreign_or_no_ticker"]},
        "dart_enabled": dart.enabled,
        "market": idx, "cash": cash,
        "grade_counts": {g: sum(1 for r in recs if r["score"]["grade"] == g) for g in scoring.GRADES},
        "revision_snapshot_age_days": snap["_age"] if snap else None,
        "config": cfg_sc,
    }
    payload = {"meta": meta, "sectors": secstats, "stocks": recs}
    (out_dir / "latest.json").write_text(json.dumps(clean(payload), ensure_ascii=False, allow_nan=False),
                                         encoding="utf-8")

    # 컨센서스 스냅샷 저장 + 오래된 것 정리
    snap_today = {"date": today.strftime("%Y-%m-%d"),
                  "items": {r["code"]: {"eps": {y: v.get("eps") for y, v in r["annual"].items() if v.get("estimate")},
                                        "target_cons": r["target_cons"]} for r in recs}}
    (hist_dir / f"{snap_today['date']}.json").write_text(json.dumps(clean(snap_today), ensure_ascii=False), encoding="utf-8")
    keep = today.replace(tzinfo=None) - timedelta(days=cfg_set["collect"]["history_keep_days"])
    for p in hist_dir.glob("*.json"):
        try:
            if datetime.strptime(p.stem, "%Y-%m-%d") < keep:
                p.unlink()
        except ValueError:
            pass
    # 오래된 종목 차트 정리
    live = {r["code"] for r in recs}
    for p in (out_dir / "prices").glob("*.json"):
        if p.stem not in live:
            p.unlink()

    log.info("완료: %d종목, 🟢%d 🟡%d ⚪%d 🔴%d, 권장 현금 %.0f%%", len(recs), *meta["grade_counts"].values(), cash["cash_pct"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
