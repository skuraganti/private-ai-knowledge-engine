"""Independent crash, rollback and hostile metadata regressions; synthetic fixtures only."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import InvalidInput
from tests.test_core import QUOTE, queued, response_file
from tests.test_core import fixture as fixture


def test_rollback_does_not_unpublish_existing_request(fixture):
    client, source, prepared, bridge, _ = fixture
    answer = queued(client)
    store = client.app.state.store
    changed = copy.deepcopy(source)
    changed["title"] = "Changed but rolled back"
    huge = copy.deepcopy(source)
    huge["id"] = "too-large"
    huge["pages"] = [{"page": n, "text": "large record evidence " * 9000} for n in range(1, 10)]
    (prepared / "manifest.json").write_text(json.dumps([changed, huge]))
    with pytest.raises(InvalidInput):
        store.seed()
    assert (bridge / f"{answer['id']}.request.json").exists()
    state = client.get("/api/state").json()
    assert state["documents"][0]["title"] == "Original"
    assert state["answers"][0]["state"] == "queued"


def test_orphaned_committed_request_fails_once_without_replay(fixture, monkeypatch):
    client, _, prepared, bridge, base = fixture
    store = client.app.state.store

    def interrupted(*args):
        raise KeyboardInterrupt("synthetic crash before request publication")

    monkeypatch.setattr(store, "_write_request", interrupted)
    with pytest.raises(KeyboardInterrupt):
        store.queue_answer("confabulation risk")
    with TestClient(
        create_app(base / "folio.sqlite", prepared, bridge), base_url="http://localhost"
    ) as reopened:
        state = reopened.get("/api/state").json()
        assert state["answers"][0]["state"] == "failed"
        assert "no automatic retry" in state["answers"][0]["reason"]
        with reopened.app.state.store._connection() as db:
            assert db.execute("SELECT value FROM meta WHERE key='attempts'").fetchone()[0] == 1
    assert not list(bridge.glob("*.request.json"))


def test_result_artifacts_removed_only_after_committed_terminal_state(fixture, monkeypatch):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    request = json.loads((bridge / f"{answer['id']}.request.json").read_text())
    response_file(
        bridge,
        answer,
        {
            "abstain": False,
            "reason": "",
            "claims": [
                {
                    "text": "Exact supported fixture claim.",
                    "supports": [{"chunk_id": request["contexts"][0]["chunk_id"], "quote": QUOTE}],
                }
            ],
        },
    )
    store = client.app.state.store
    original = store._remove_artifacts
    observed = []

    def checked(identifier):
        with store._connection() as db:
            row = db.execute("SELECT state FROM answers WHERE id=?", (identifier,)).fetchone()
        assert row["state"] != "queued"
        observed.append(row["state"])
        original(identifier)

    monkeypatch.setattr(store, "_remove_artifacts", checked)
    assert client.get("/api/answers/" + answer["id"]).json()["state"] == "succeeded"
    assert observed == ["succeeded"]


@pytest.mark.parametrize("field", ["latency", "usage"])
def test_huge_json_integer_fails_response_without_breaking_reads(fixture, field):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    extra = {"latency_ms": 10**400} if field == "latency" else {"usage": {"output_tokens": 10**400}}
    response_file(
        bridge, answer, {"abstain": True, "reason": "No evidence.", "claims": []}, **extra
    )
    result = client.get("/api/state")
    assert result.status_code == 200
    assert result.json()["answers"][0]["state"] == "failed"


def test_huge_heartbeat_is_offline_not_an_exception(fixture):
    client, _, _, bridge, _ = fixture
    (bridge / "heartbeat.json").write_text(
        json.dumps({"at": 10**400, "model": "cookllm", "status": "ready", "calls": 0})
    )
    assert client.get("/api/state").json()["bridge"]["online"] is False


def test_selected_source_filters_before_global_candidate_limit(fixture):
    client, _, _, _, _ = fixture
    imported = client.post(
        "/api/documents",
        json={"title": "Synthetic repeated-term noise", "text": "confabulation risk " * 10000},
    )
    assert imported.status_code == 200
    result = client.post(
        "/api/search",
        json={"query": "confabulation", "mode": "lexical", "document_ids": ["public-one"]},
    ).json()
    assert result["hits"] and all(h["document_id"] == "public-one" for h in result["hits"])


def test_health_detects_corrupt_index(fixture):
    client, _, _, _, base = fixture
    (base / "folio.sqlite").write_bytes(b"Synthetic corrupt database")
    assert client.get("/health").status_code == 503


def test_expiry_frees_slot_without_model_replay(fixture):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    with client.app.state.store._connection(write=True) as db:
        db.execute("UPDATE answers SET created_at=created_at-361 WHERE id=?", (answer["id"],))
    result = client.get("/api/answers/" + answer["id"]).json()
    assert result["state"] == "failed" and "expired" in result["reason"]
    assert not (bridge / f"{answer['id']}.request.json").exists()


def test_http_boundaries_and_preparser_limit(fixture):
    client, *_ = fixture
    assert client.get("/static/app.js", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post("/api/seed", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.post("/api/documents", content=b"{" + b"x" * 530000).status_code == 413
    assert client.post("/api/search", json={"query": "risk", "limit": True}).status_code == 422
    assert "object-src 'none'" in client.get("/").headers["Content-Security-Policy"]
