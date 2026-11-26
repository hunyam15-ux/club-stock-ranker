"""오프라인 테스트용 가짜 데이터 소스(네트워크 없이 파이프라인 전체를 돌려 보기 위함).

※ 여기서 만드는 숫자는 전부 난수로 만든 가짜 값입니다. 실제 사이트 데이터에는 쓰이지 않습니다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def fake_summary(sess, code):
    r = _rng(code)
    last = fake_daily(None, code)[-1][4]
    return {"price": round(last), "change_pct": r.uniform(-3, 3), "price_time": "2026-11-26T15:30:00+09:00",
            "mcap_eok": r.choice([800, 3000, 9000, 40000, 300000]), "per": r.choice([-5, 6, 9, 14, 22, 35]),
            "pbr": r.choice([0.5, 0.9, 1.4, 2.5, 4.0]), "div_yield": r.choice([None, 0.5, 2.1, 4.0]),
            "high52": None, "low52": None, "cons_target": round(last * r.uniform(0.85, 1.6), -2),
            "market": "코스닥" if r.random() > 0.5 else "코스피"}


def fake_main(sess, code):
    r = _rng(code)
    return {"industry_per": r.choice([None, 10.5, 15.2, 20.1])}


def fake_fnguide(sess, code):
    r = _rng(code)
    e = r.uniform(200, 5000)
    ann = {}
    for y in (2023, 2024, 2025, 2026, 2027):
        e *= 1 + r.uniform(-0.2, 0.45)
        ann[str(y)] = {"estimate": y >= 2026, "revenue": e * 300, "op_income": e * 30, "eps": e,
                       "roe": r.uniform(3, 20), "debt_ratio": r.choice([40, 90, 180, 320])}
    return {"annual": ann}


def install(monkeypatch):
    from collector import consensus, market, sheet

    csv_text = (ROOT / "tests" / "fixtures" / "sample_sheet.csv").read_text(encoding="utf-8")
    monkeypatch.setattr("collector.main.fetch_csv", lambda *a, **k: csv_text)
    monkeypatch.setattr(market, "fetch_daily", fake_daily)
    monkeypatch.setattr(market, "fetch_naver_summary", fake_summary)
    monkeypatch.setattr(market, "fetch_naver_main", fake_main)
    monkeypatch.setattr(consensus, "fetch_fnguide", fake_fnguide)
    _ = sheet
