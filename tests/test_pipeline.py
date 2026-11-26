import json

from collector import main as M

from . import fake_sources


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    fake_sources.install(monkeypatch)
    monkeypatch.setitem(M.__dict__, "ROOT", M.ROOT)
    import yaml
    real = M.load_yaml

    def cfg(p):
        d = real(p)
        if p.name == "settings.yaml":
            d["universe"]["min_listing"] = 10
        return d
    monkeypatch.setattr(M, "load_yaml", cfg)
    assert M.main(["--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    st = data["stocks"]
    codes = {s["code"] for s in st}
    assert {"073010", "005930", "0088M0"} <= codes          # 모임 종목은 항상 포함
    assert "069500" not in codes                             # ETF 제외
    assert data["meta"]["universe"]["excluded"].get("거래대금 미달", 0) > 0
    assert [s["rank"] for s in st] == list(range(1, len(st) + 1))
    for s in st:
        assert s["score"]["grade"] in ("green", "yellow", "white", "red")
        assert isinstance(s["thesis"]["ideas"], list) and s["thesis"]["checks"]
        assert (tmp_path / "stock" / f"{s['code']}.json").exists()
    club = [s for s in st if s["club"]]
    assert len(club) == 3
    det = json.loads((tmp_path / "stock" / "005930.json").read_text(encoding="utf-8"))
    assert det["pitches"] and det["chart"] and det["summary"]
    assert sum(s["weight_pct"] for s in st) <= 100
    assert any((tmp_path / "history").glob("*.json"))
    _ = yaml


def test_sheet_failure_stops(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("403")
    monkeypatch.setattr("collector.main.fetch_csv", boom)
    assert M.main(["--out", str(tmp_path)]) == 2
    assert not (tmp_path / "latest.json").exists()
