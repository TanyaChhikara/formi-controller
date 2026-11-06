"""Tests for the parts where a bug would be silent: statistics, config composition, idempotent ingestion.
Run: python -m pytest -q tests"""
import json

import pytest

from controller.governance import changed_dims, max_shift
from controller.ingest import Ingestor
from controller.policies import Brain
from controller.stats import holm, n_per_arm, poisson_sf, two_prop_z
from controller.store import Store


def test_two_prop_z_sign_and_symmetry():
    assert two_prop_z(60, 100, 50, 100) > 0
    assert two_prop_z(60, 100, 50, 100) == pytest.approx(-two_prop_z(50, 100, 60, 100))
    assert two_prop_z(0, 0, 5, 10) == 0.0


def test_holm_controls_family():
    # one strong, one marginal: Holm keeps only what survives the step-down
    assert holm({"a": 0.001, "b": 0.04}, 0.05) == {"a", "b"}
    assert holm({"a": 0.001, "b": 0.04, "c": 0.04}, 0.05) == {"a"}
    assert holm({"a": 0.2}, 0.05) == set()


def test_sample_size_matches_textbook():
    # 55% base, +10% relative (→60.5%), α=.05 two-sided, power .8 → ~1,250 per arm
    assert 1200 <= n_per_arm(0.55, 0.10) <= 1320


def test_poisson_tail():
    assert poisson_sf(0, 3) == 1.0
    assert poisson_sf(12, 3.0) < 1e-4
    assert poisson_sf(3, 3.0) > 0.5


def test_compose_appends_cohorts_and_sets_alloc():
    old = {"cohorts": [{"id": "a", "where": {"lang": ["ta"]}}],
           "allocations": {"default": {"welcome_message": {"W1": 1}, "voice": {"V1": 1}, "caller_id": {"D1": 1}}},
           "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}
    i = {"alloc": {"b": {"voice": {"V3": 0.85, "V1": 0.15}}}, "new_cohorts": [{"id": "b", "where": {"age_band": ["60+"]}}]}
    new = Brain._compose(old, [i])
    assert [c["id"] for c in new["cohorts"]] == ["a", "b"]          # existing cohort keeps precedence
    assert new["allocations"]["b"]["voice"] == {"V3": 0.85, "V1": 0.15}
    assert old["cohorts"] == [{"id": "a", "where": {"lang": ["ta"]}}]  # no mutation of the live config
    assert set(changed_dims(old, new)) == {"cohorts", "voice"}
    assert max_shift(old, new) == pytest.approx(0.85)


class FakeSim:
    def __init__(self, chunks):
        self.chunks = chunks

    def get(self, path, **params):
        kind, after = params["kind"], params["after"]
        return [{"chunk": n, "kind": k} for n, (k, _) in enumerate(self.chunks) if k == kind and n > after]

    def chunk_lines(self, n):
        return [json.dumps(e).encode() for e in self.chunks[n][1]]


def _call(i, wf="w", conn=True):
    return {"type": "call", "ts": "2027-01-04T10:15:00+05:30", "workflow_id": wf, "lead_id": f"l{i}",
            "config_version": 1, "cohort_id": "default", "connected": conn, "engaged": conn,
            "variant": {"welcome_message": "W1", "voice": "V1", "caller_id": "D1", "prompt_version": "P1"},
            "qa": {"hallucination_flag": False}}


def test_ingest_is_idempotent_and_crash_safe(tmp_path, monkeypatch):
    lead = {"type": "lead", "lead_id": "l0", "features": {"lang": "hi", "city_tier": "1", "age_band": "60+",
                                                       "value_band": "mid"}}
    sim = FakeSim([("history", [lead, _call(0)]), ("events", [_call(1), _call(2, conn=False)])])
    st = Store(str(tmp_path / "c.db"))
    ing = Ingestor(st, sim)
    # crash in the middle of the second chunk's transaction: nothing from it may persist
    real = st.tx
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt("kill -9 stand-in")
        return real()
    monkeypatch.setattr(st, "tx", flaky)
    with pytest.raises(KeyboardInterrupt):
        ing.ingest_pending()
    assert st.q1("SELECT SUM(dials) FROM agg WHERE key='all'")[0] == 1
    monkeypatch.setattr(st, "tx", real)
    ing2 = Ingestor(st, sim)               # "restart": fresh process state, same store
    ing2.ingest_pending()
    ing2.ingest_pending()                  # and a second pass is a no-op
    assert st.q1("SELECT SUM(dials), SUM(conn) FROM agg WHERE key='all'") == (3, 2)
    assert st.q1("SELECT SUM(dials) FROM agg WHERE key='voice=V1|age_band=60+'")[0] == 1
