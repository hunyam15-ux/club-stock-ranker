"""오프라인 테스트용 가짜 데이터 소스(네트워크 없이 파이프라인 전체를 돌려 보기 위함).

※ 여기서 만드는 숫자는 전부 난수로 만든 가짜 값입니다. 실제 사이트 데이터에는 쓰이지 않습니다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTORS = ["반도체와반도체장비", "조선", "화장품", "자동차부품", "증권", "화학", "소프트웨어", "제약"]


def _rng(code):
    return random.Random(sum(ord(c) * (i + 1) for i, c in enumerate(code)))


def fake_daily(sess, symbol, count=300):
    r = _rng(symbol)
    p = 1000 * r.choice([3, 8, 20, 60, 150]) if symbol != "KOSPI" else 2500.0
    d = date(2026, 11, 26) - timedelta(days=int(count * 1.45))
    rows = []
    drift = r.uniform(-0.001, 0.002)
    while len(rows) < count:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        ch = r.gauss(drift, 0.022)
        o = p
        c = max(100, p * (1 + ch))
        h, l = max(o, c) * (1 + abs(r.gauss(0, 0.008))), min(o, c) * (1 - abs(r.gauss(0, 0.008)))
        rows.append([d.isoformat(), o, h, l, c, r.randint(10_000, 2_000_000)])
        p = c
    return rows


def demo_codes(n=40):
    return [f"{900000 + i * 10:06d}" for i in range(1, n + 1)]


def fake_listing(sess, extra=("073010", "005930", "0088M0"), n=40):
    out = []
    for i, code in enumerate(list(extra) + demo_codes(n)):
        r = _rng(code)
        last = fake_daily(None, code)[-1][4]
        out.append({"code": code, "name": f"데모종목{i:02d}", "market": r.choice(["코스피", "코스닥"]), "end_type": "stock",
                    "price": round(last), "change_pct": r.uniform(-3, 3),
                    "mcap_eok": r.choice([1500, 3000, 9000, 40000, 300000]),
                    "trade_value_mil": r.choice([200, 1000, 50000]), "price_time": "2026-11-26T15:30:00+09:00",
                    "trading": True})
    out.append({"code": "069500", "name": "데모ETF", "end_type": "etf", "mcap_eok": 50000, "trade_value_mil": 9e5,
                "price": 30000, "trading": True})
    return out


def fake_industries(sess):
    return {c: SECTORS[i % len(SECTORS)] for i, c in enumerate(["073010", "005930", "0088M0"] + demo_codes())}


def fake_summary(sess, code, with_basic=True):
    r = _rng(code)
    last = fake_daily(None, code)[-1][4]
    return {"price": round(last), "mcap_eok": 5000, "per": r.choice([-5, 6, 9, 14, 22, 35]),
            "pbr": r.choice([0.5, 0.9, 1.4, 2.5, 4.0]), "div_yield": r.choice([None, 0.5, 2.1, 4.0]),
            "high52": None, "low52": None,
            "cons_target": r.choice([None, round(last * r.uniform(0.85, 1.6), -2)]), "cons_date": "2026-11-25"}


def fake_finance(sess, code):
    r = _rng(code)
    e = r.uniform(200, 5000)
    ann = {}
    for y in (2023, 2024, 2025, 2026):
        e *= 1 + r.uniform(-0.2, 0.45)
        ann[str(y)] = {"estimate": y >= 2026, "revenue": e * 300, "op_income": e * 30, "eps": e,
                       "roe": r.uniform(3, 20), "debt_ratio": r.choice([40, 90, 180, 320])}
    return ann, ["(데모) 회사 개요 문장 1입니다.", "(데모) 주요 사업 설명 문장입니다."]


def fake_quarter(sess, code):
    r = _rng(code + "q")
    out = {}
    for i, q in enumerate(["2025.09", "2025.12", "2026.03", "2026.06", "2026.09", "2026.12"]):
        out[q] = {"estimate": q == "2026.12", "op_income": r.uniform(-50, 500), "revenue": r.uniform(1000, 5000)}
    return out


def fake_macro(sess):
    return {"hy_spread": {"label": "미국 하이일드 스프레드", "value": 3.2, "chg_1m": 0.1, "date": "2026-11-25"},
            "us10y": {"label": "미국 10년물 금리", "value": 4.4, "chg_1m": -0.1, "date": "2026-11-25"},
            "kr10y": {"label": "한국 10년물 금리(월간)", "value": None}}


def patch(setter):
    """setter(module, name, value) 로 가짜 함수를 끼운다 (pytest monkeypatch.setattr 또는 setattr)."""
    from collector import consensus, macro, market, universe
    setter(consensus, "fetch_quarter", fake_quarter)
    setter(macro, "fetch_macro", fake_macro)
    setter(market, "fetch_daily", fake_daily)
    setter(market, "fetch_naver_summary", fake_summary)
    setter(consensus, "fetch_finance", fake_finance)
    setter(universe, "fetch_listing", fake_listing)
    setter(universe, "fetch_industries", fake_industries)


def install(monkeypatch):
    csv_text = (ROOT / "tests" / "fixtures" / "sample_sheet.csv").read_text(encoding="utf-8")
    monkeypatch.setattr("collector.main.fetch_csv", lambda *a, **k: csv_text)
    patch(monkeypatch.setattr)
