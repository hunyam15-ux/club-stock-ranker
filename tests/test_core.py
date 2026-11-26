from pathlib import Path

import yaml

from collector import consensus, market, scoring, strategy
from collector.sheet import club_target, parse_sheet, parse_target, parse_ticker
from collector.util import parse_korean_amount, round_tick, to_num

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------- 시트
def test_parse_ticker():
    assert parse_ticker("KOSDAQ:073010") == ("073010", "KOSDAQ")
    assert parse_ticker("KRX:005930") == ("005930", "KOSPI")
    assert parse_ticker("042700") == ("042700", None)
    assert parse_ticker("0088M0") == ("0088M0", None)
    for f in ("NE", "IONQ", "IBIDF", "", None, "TLT"):
        assert parse_ticker(f) == (None, None)


def test_parse_target():
    assert parse_target("7,600") == 7600
    assert parse_target("N/A") is None
    assert parse_target("200,000~240,000") == 220000


def test_parse_sheet_fixture():
    text = (ROOT / "tests" / "fixtures" / "sample_sheet.csv").read_text(encoding="utf-8")
    stocks, stats = parse_sheet(text)
    codes = [s.code for s in stocks]
    assert codes == ["073010", "005930", "0088M0"]          # 해외·티커없음·두 번째 표 제외
    assert "042700" not in codes
    s1 = stocks[0]
    assert s1.pitches[0].presenter == "갑" and s1.pitches[0].price_at_pitch == 3805
    assert "줄3" in s1.idea and "CB" in s1.risk
    sam = stocks[1]
    assert len(sam.pitches) == 2 and sam.pitches[0].date == "2025-11-17"   # 최신순
    assert sam.name == "테스트반도체(재발표)"
    t, p = club_target(sam)
    assert t == 220000 and p.presenter == "을"
    assert sam.sheet_mcap == 11103938
    assert any("해외기업" in x for x in stats["foreign_or_no_ticker"])


# ------------------------------------------------------------- 유틸
def test_numbers():
    assert to_num("13.45배") == 13.45
    assert to_num("-1.2%") == -1.2
    assert to_num("N/A") is None
    assert parse_korean_amount("1,018조 4,523억") == 10184523
    assert parse_korean_amount("5,127억") == 5127


def test_ticks():
    assert round_tick(171_349) == 171_300
    assert round_tick(4_997, "down") == 4_995
    assert round_tick(512_345, "down") == 512_000


# ------------------------------------------------------------- 실적 파서
NAVER_ANNUAL = {"financeInfo": {
    "trTitleList": [{"isConsensus": "N", "title": "2024.12.", "key": "202412"},
                    {"isConsensus": "N", "title": "2025.12.", "key": "202512"},
                    {"isConsensus": "Y", "title": "2026.12.", "key": "202612"}],
    "rowList": [
        {"title": "매출액", "columns": {"202412": {"value": "1,000"}, "202512": {"value": "1,200"}, "202612": {"value": "1,500"}}},
        {"title": "당기순이익", "columns": {"202412": {"value": "90"}, "202512": {"value": "95"}, "202612": {"value": "130"}}},
        {"title": "지배주주순이익", "columns": {"202412": {"value": "80"}, "202512": {"value": "90"}, "202612": {"value": "-"}}},
        {"title": "ROE", "columns": {"202412": {"value": "9.0"}, "202512": {"value": "10.85"}, "202612": {"value": "12"}}},
        {"title": "부채비율", "columns": {"202412": {"value": "80.1"}, "202512": {"value": "29.94"}, "202612": {"value": "-"}}},
        {"title": "EPS", "columns": {"202412": {"value": "-50"}, "202512": {"value": "100"}, "202612": {"value": "150"}}},
    ]}}


def test_naver_annual():
    a = consensus.parse_naver_annual(NAVER_ANNUAL)
    assert set(a) == {"2024", "2025", "2026"} and a["2026"]["estimate"] and not a["2025"]["estimate"]
    assert a["2025"]["net_income"] == 90 and a["2026"]["net_income"] == 130   # 지배주주 없으면 당기순이익
    assert a["2025"]["debt_ratio"] == 29.94 and "debt_ratio" not in a["2026"]
    est = consensus.estimates_for(a, 2026)
    assert est["eps_g_cur"] == 50.0 and est["eps_g_next"] is None and est["next"] == {}
    est25 = consensus.estimates_for(a, 2025)
    assert est25["eps_g_cur"] is None and est25["turnaround_cur"]          # 적자→흑자


# ------------------------------------------------------------- 점수
BASE = dict(price=10000, target=14000, target_source="모임", per=8, pbr=0.8, fwd_per=6, bench_per=12,
            bench_pbr=1.2, eps_growth_next=25, turnaround=False, revision_pct=None, range_pos=0.25,
            ret_1m=-5, ret_3m=-10, dilution_pct=0, debt_ratio=60, memo_text="")


def test_score_good_stock_is_green():
    r = scoring.score_stock(BASE, CFG)
    assert r["grade"] == "green", r
    assert "모임 목표가 대비 +40%" in r["reason"]
    assert r["coverage"] == 1.0


def test_negative_upside_is_red():
    r = scoring.score_stock({**BASE, "target": 9000}, CFG)
    assert r["grade"] == "red" and "목표가 대비 -10%" in r["reason"] and "현재가 ≥ 목표가" in r["flags"]


def test_missing_data_reweights_and_caps_grade():
    s = {k: None for k in BASE}
    s.update(price=10000, range_pos=0.1, ret_1m=-8, ret_3m=-15)
    r = scoring.score_stock(s, CFG)
    assert r["coverage"] < 0.6 and r["grade"] in ("white", "red")


def test_risk_penalty():
    r0 = scoring.score_stock(BASE, CFG)
    r1 = scoring.score_stock({**BASE, "dilution_pct": 12, "debt_ratio": 350, "memo_text": "CB 오버행, 유상증자"}, CFG)
    assert r1["penalty"] == min(12 + 8 + 4.5, CFG["risk"]["max_total"])
    assert r1["total"] < r0["total"]


# ------------------------------------------------------------- 전략
def test_entry_and_exit_plan():
    deriv = {"low_60d": 9480, "low_120d": 8000}
    p = strategy.entry_plan(10000, deriv, CFG)
    prices = [e["price"] for e in p["entries"]]
    assert prices[0] == 10000 and prices[1] < 10000 and prices[2] < prices[1]
    assert "지지선" in p["entries"][1]["basis"]          # 9,500 근처 60일 저점에 맞춤
    assert p["stop"] < prices[2]
    x = strategy.exit_plan(10000, 14000, CFG)
    assert x["tp1"] == 12000 and x["tp2"] == 14000


def test_weights_cap_and_cash():
    stocks = [{"code": str(i), "score": {"grade": "green", "total": 80}, "vol_annual": 20} for i in range(3)]
    stocks.append({"code": "x", "score": {"grade": "red", "total": 20}, "vol_annual": 20})
    strategy.portfolio_weights(stocks, 20, CFG)
    assert all(s["weight_pct"] <= 15 for s in stocks) and stocks[-1]["weight_pct"] == 0
    assert abs(sum(s["weight_pct"] for s in stocks) - 45) < 0.5   # 3종목 × 상한 15%
    c = strategy.cash_policy({"last": 100, "ma_short": 90, "ma_long": 95}, 0, CFG)
    assert c["cash_pct"] == 35 and c["trend_state"] == "above_both"


def test_grade_caps():
    from collector.main import apply_grade_caps
    recs = [{"score": {"grade": "green", "total": 90 - i, "flags": []}} for i in range(5)]
    apply_grade_caps(recs, {"max_green": 2, "max_yellow": 2})
    assert [r["score"]["grade"] for r in recs] == ["green", "green", "yellow", "yellow", "white"]
