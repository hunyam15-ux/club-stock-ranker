import json

from collector import main as M

from . import fake_sources


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    fake_sources.install(monkeypatch)
    assert M.main(["--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    st = data["stocks"]
    assert [s["rank"] for s in st] == list(range(1, len(st) + 1))
    assert {s["code"] for s in st} == {"073010", "005930", "0088M0"}
    for s in st:
        assert s["score"]["grade"] in ("green", "yellow", "white", "red")
        assert s["score"]["reason"]
        assert (tmp_path / "prices" / f"{s['code']}.json").exists()
        assert s["dart"]["enabled"] is False
    assert data["meta"]["cash"]["cash_pct"] >= 10
    assert (tmp_path / "history").glob("*.json")


def test_sheet_failure_stops(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("403")
    monkeypatch.setattr("collector.main.fetch_csv", boom)
    assert M.main(["--out", str(tmp_path)]) == 2
    assert not (tmp_path / "latest.json").exists()
