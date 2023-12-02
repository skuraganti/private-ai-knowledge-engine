"""Retrieval-v2 harness on tiny synthetic fixtures; never reads real cases or corpus."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.store import Store

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "evaluate_retrieval", REPO / "scripts/evaluate_retrieval.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

DOCS = {
    "doc-a": ["Zephyr quokka calibration register.", "Lantern inventory checklist."],
    "doc-b": ["Harbor tides overview.", "Granite survey steps.", "Granite survey review steps."],
    "doc-c": ["Orchard irrigation schedule.", "Velvet compass bearings."],
}


def _case(cid, query, doc, pages, category):
    support = [{"page": pages[0], "excerpt": DOCS[doc][pages[0] - 1]}]
    keys = ("id", "query", "document_id", "pages", "support", "category")
    return dict(zip(keys, (cid, query, doc, pages, support, category)))


CASES = [  # c3 is a deliberate miss: its designated page lacks the query terms
    _case("c1", "zephyr quokka", "doc-a", [1], "direct"),
    _case("c2", "granite survey steps", "doc-b", [2, 3], "procedural"),
    _case("c3", "velvet compass", "doc-a", [2], "nearby"),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_root(tmp_path, cases=None, **freeze_changes):
    root = tmp_path / "root"
    prepared = root / "data" / "prepared"
    prepared.mkdir(parents=True)
    fixed = {"publication": "2026", "remote_allowed": True}
    manifest = [
        fixed
        | dict(id=doc, title=doc, url=f"https://example.org/{doc}.pdf", pdf_name=f"{doc}.pdf")
        | {
            "sha256": _sha(doc.encode()),
            "pages": [{"page": n, "text": t} for n, t in enumerate(p, 1)],
        }
        for doc, p in DOCS.items()
    ]
    (prepared / "manifest.json").write_text(json.dumps(manifest))
    (prepared / "preparation.json").write_text('{"synthetic": true}')
    cases_path = root / "cases.json"
    cases_path.write_text(json.dumps({"cases": cases if cases is not None else CASES}))
    freeze = {
        "cases_sha256": _sha(cases_path.read_bytes()),
        "prepared_manifest_sha256": _sha((prepared / "manifest.json").read_bytes()),
        "preparation_sha256": _sha((prepared / "preparation.json").read_bytes()),
        "sources": [{"id": d["id"], "sha256": d["sha256"]} for d in manifest],
        "algorithm_sha256": {n: _sha((REPO / n).read_bytes()) for n in harness.ALGORITHMS},
        "frozen_at": "synthetic",
        "parameters": {"top_k": 5},
        "policy": "synthetic test",
    } | freeze_changes
    freeze_path = root / "FREEZE.json"
    freeze_path.write_text(json.dumps(freeze))
    for legacy in harness.LEGACY:  # sentinel legacy v1 outputs that must never change
        (root / legacy).parent.mkdir(parents=True, exist_ok=True)
        (root / legacy).write_text("legacy v1")
    return root, cases_path, freeze_path, root / "data/verification/retrieval-v2/run-001.json"


def test_metric_oracle_by_hand():
    case = {"document_id": "t", "pages": [3, 7]}
    hits = [("x", 3), ("t", 9), ("t", 7), ("t", 7), ("t", 3)]  # other doc, wrong page, dup page
    found = {
        "took_ms": 1.0,
        "hits": [
            {
                "chunk_id": f"k{i}",
                "document_id": d,
                "version": 1,
                "page": p,
                "sha256": "s",
                "score": 0.1,
            }
            for i, (d, p) in enumerate(hits)
        ],
    }
    scored = harness._score(case, found)
    assert (scored["first_relevant_rank"], scored["matched_pages"]) == (3, [3, 7])
    assert scored["designated_page_recall"] == 1.0 and len(scored["hits"]) == 5
    miss = {"first_relevant_rank": None, "designated_page_recall": 0.0, "case_id": "m"}
    summary = harness._summary([scored | {"case_id": "h"}, miss])
    assert summary == {
        "n": 2,
        "hits_at_5": 1,
        "hit_at_5": 0.5,
        "mrr_at_5": (1 / 3) / 2,
        "designated_page_recall_at_5": 0.5,
        "misses": ["m"],
    }


def test_unfiltered_searches_over_all_documents_and_misses_retained(tmp_path, monkeypatch):
    root, cases, freeze, output = make_root(tmp_path)
    calls, original = [], Store.search

    def spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Store, "search", spy)
    report = harness.run(cases, freeze, output, root=root)
    assert len(calls) == 9 and all(kw == {} and len(a) == 3 for a, kw in calls)  # no doc filter
    assert report["parameters"]["candidates"] == sorted(DOCS)
    assert {m: report["summary"][m]["n"] for m in harness.MODES} == dict.fromkeys(harness.MODES, 3)
    lexical = {r["case_id"]: r for r in report["results"] if r["mode"] == "lexical"}
    assert lexical["c1"]["first_relevant_rank"] == 1
    assert lexical["c2"]["designated_page_recall"] == 1.0
    for mode in harness.MODES:  # c3's answer page lacks its terms: a miss in every mode
        assert "c3" in report["summary"][mode]["misses"]
    assert report["cold_start"]["mode"] == "latent" and report["cold_start"]["case_id"] == "c1"
    assert json.loads(output.read_text())["summary"] == report["summary"]
    assert all((root / legacy).read_text() == "legacy v1" for legacy in harness.LEGACY)


def _broken(case_change=None, **freeze_changes):
    cases = copy.deepcopy(CASES)
    if case_change:
        case_change(cases[0])
    return cases, freeze_changes


@pytest.mark.parametrize(
    "cases,freeze_changes,message",
    [
        (*_broken(cases_sha256="0" * 64), "cases_sha256"),
        (*_broken(preparation_sha256="0" * 64), "preparation_sha256"),
        (
            *_broken(algorithm_sha256=dict.fromkeys(harness.ALGORITHMS, "0" * 64)),
            "app/retrieval.py",
        ),
        (*_broken(sources=[{"id": "doc-a", "sha256": "0" * 64}]), "frozen source list"),
        (*_broken(parameters={"top_k": 10}), "top_k"),
        (*_broken(parameters={"limit": 10}), "limit"),
        (*_broken(parameters={"cases": 24}), "case design"),
        (*_broken(parameters={"query_scope": "gold-only"}), "query_scope"),
        (*_broken(parameters={"cases_per_document": 8}), "cases_per_document"),
        (*_broken(extra="x"), "exactly"),
        (*_broken(lambda c: c.update(pages=[1, 1])), "duplicate designated pages"),
        (*_broken(lambda c: c.update(document_id="doc-z")), "not a prepared document"),
        (*_broken(lambda c: c.update(support=[{"page": 2, "excerpt": "x"}])), "support"),
        (*_broken(lambda c: c.update(category="other")), "category"),
        (*_broken(lambda c: c.update(support=[{"page": 1, "excerpt": "invented"}])), "literal"),
    ],
)
def test_invalid_inputs_refused_before_any_store(
    tmp_path, monkeypatch, cases, freeze_changes, message
):
    root, cases_path, freeze, output = make_root(tmp_path, cases, **freeze_changes)
    monkeypatch.setattr(Store, "__init__", lambda *a, **k: pytest.fail("Store built"))
    with pytest.raises(harness.EvaluationError, match=message):
        harness.run(cases_path, freeze, output, root=root)
    assert not output.exists()


def test_missing_freeze_and_output_rules(tmp_path, monkeypatch):
    root, cases, freeze, output = make_root(tmp_path)
    monkeypatch.setattr(Store, "__init__", lambda *a, **k: pytest.fail("Store built"))
    with pytest.raises(harness.EvaluationError, match="freeze missing"):
        harness.run(cases, root / "absent.json", output, root=root)
    for bad, message in [(root / harness.LEGACY[1], "legacy"), (root / "out.json", "inside")]:
        with pytest.raises(harness.EvaluationError, match=message):
            harness.run(cases, freeze, bad, root=root)
    output.parent.mkdir(parents=True)
    output.write_text("earlier run")
    with pytest.raises(harness.EvaluationError, match="already exists"):
        harness.run(cases, freeze, output, root=root)
    assert output.read_text() == "earlier run"
    assert all((root / legacy).read_text() == "legacy v1" for legacy in harness.LEGACY)


def test_failed_request_is_zero_and_run_remains_explicitly_incomplete(tmp_path, monkeypatch):
    root, cases, freeze, output = make_root(tmp_path)
    original = Store.search

    def fail_one(self, query, mode, limit):
        if query == "zephyr quokka" and mode == "lexical":
            raise RuntimeError("synthetic query failure")
        return original(self, query, mode, limit)

    monkeypatch.setattr(Store, "search", fail_one)
    report = harness.run(cases, freeze, output, root=root)
    assert report["complete"] is False
    assert report["request_failures"] == [
        {"case_id": "c1", "mode": "lexical", "error_type": "RuntimeError"}
    ]
    assert len(report["results"]) == 9
    assert report["summary"]["lexical"]["n"] == 3
    row = next(r for r in report["results"] if r["case_id"] == "c1" and r["mode"] == "lexical")
    assert row["first_relevant_rank"] is None and row["designated_page_recall"] == 0
    assert report["by_document"]["lexical"]["doc-a"]["n"] == 2
    assert all(b["attempted"] == b["pending"] == 0 for b in report["model_budget"].values())


@pytest.mark.parametrize(
    "name,key", [("PROTOCOL.md", "protocol_sha256"), ("SOURCE_CHECK.json", "source_check_sha256")]
)
def test_policy_artifact_drift_is_refused_before_store(tmp_path, monkeypatch, name, key):
    root, cases, freeze, output = make_root(tmp_path)
    (freeze.parent / name).write_text("changed artifact")
    record = json.loads(freeze.read_text())
    record["policy"] = {key: _sha(b"original artifact")}
    freeze.write_text(json.dumps(record))
    monkeypatch.setattr(Store, "__init__", lambda *a, **k: pytest.fail("Store built"))
    with pytest.raises(harness.EvaluationError, match=name):
        harness.run(cases, freeze, output, root=root)
    assert not output.exists()
