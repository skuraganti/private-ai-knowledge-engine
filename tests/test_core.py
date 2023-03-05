"""Synthetic-only contract tests; these are not live inference checks."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

QUOTE = "A precise and sufficiently long source sentence supports this exact citation."


@pytest.fixture
def fixture(tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    bridge = tmp_path / "bridge"
    source = {
        "id": "public-one",
        "title": "Original",
        "url": "https://example.org/original.pdf",
        "pdf_name": "original.pdf",
        "sha256": "a" * 64,
        "publication": "2026",
        "remote_allowed": True,
        "pages": [
            {"page": 3, "text": f"Confabulation risk and retrieval. {QUOTE}"},
            {"page": 7, "text": "Encrypted archival storage protects a local record."},
        ],
    }
    (prepared / "manifest.json").write_text(json.dumps([source]))
    app = create_app(tmp_path / "folio.sqlite", prepared, bridge)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, source, prepared, bridge, tmp_path


def search(client, query, mode="hybrid", **kw):
    response = client.post("/api/search", json={"query": query, "mode": mode, **kw})
    assert response.status_code == 200, response.text
    return response.json()


def queued(client):
    response = client.post("/api/answers", json={"question": "confabulation risk"})
    assert response.status_code == 200, response.text
    return response.json()


def response_file(bridge, answer, output, **extra):
    (bridge / f"{answer['id']}.response.json").write_text(
        json.dumps(
            {
                "id": answer["id"],
                "revision": answer["revision"],
                "state": "succeeded",
                "model": "cookllm",
                "latency_ms": 23.5,
                "output": output,
                **extra,
            }
        )
    )


def test_initial_seed_is_once_and_restore_is_explicit(fixture):
    client, _, prepared, _, tmp = fixture
    initial = client.get("/api/state").json()
    assert initial["counts"] == {"documents": 1, "chunks": 2}
    client.delete("/api/documents/public-one")
    with TestClient(
        create_app(tmp / "folio.sqlite", prepared, tmp / "bridge"), base_url="http://localhost"
    ) as again:
        assert again.get("/api/state").json()["counts"]["documents"] == 0
        assert again.post("/api/seed", json={}).json()["added"] == 1


@pytest.mark.parametrize("mode", ["lexical", "latent", "hybrid"])
def test_search_modes_and_exact_page_links(fixture, mode):
    client, *_ = fixture
    hits = search(client, "confabulation", mode)["hits"]
    assert hits and hits[0]["page"] == 3
    assert hits[0]["source_url"] == "https://example.org/original.pdf"
    assert hits[0]["remote_allowed"] is True
    assert isinstance(hits[0]["score"], float)  # LSA score is not a probability.


def test_query_syntax_and_stopwords_do_not_raise(fixture):
    client, *_ = fixture
    assert search(client, '" OR * () confabulation')["hits"]
    assert search(client, "the and of")["hits"] == []
    assert search(client, "unrepresented-universe-word")["hits"] == []


def test_private_import_searchable_but_inference_rejected(fixture):
    client, *_ = fixture
    imported = client.post(
        "/api/documents", json={"title": "Private", "text": "secret confabulation note"}
    ).json()
    assert imported["remote_allowed"] is False
    assert search(client, "secret", document_ids=[imported["id"]])["hits"]
    response = client.post("/api/answers", json={"question": "secret confabulation"})
    assert response.status_code == 422


def test_identical_import_noop_and_change_versions(fixture):
    client, *_ = fixture
    first = client.post("/api/documents", json={"title": "Note", "text": "private original"}).json()
    before = client.get("/api/state").json()["revision"]
    payload = {"document_id": first["id"], "title": "Note", "text": "private original"}
    same = client.post("/api/documents", json=payload).json()
    assert same["version"] == first["version"]
    assert client.get("/api/state").json()["revision"] == before
    payload["text"] = "private revised"
    changed = client.post("/api/documents", json=payload).json()
    assert changed["version"] == first["version"] + 1
    assert changed["sha256"] == hashlib.sha256(b"private revised").hexdigest()
    assert not search(client, "original", document_ids=[first["id"]])["hits"]


def test_public_edit_becomes_private(fixture):
    client, *_ = fixture
    changed = client.post(
        "/api/documents",
        json={
            "document_id": "public-one",
            "title": "Edited",
            "text": "confabulation local revision",
        },
    ).json()
    assert changed["remote_allowed"] is False
    assert client.post("/api/answers", json={"question": "confabulation"}).status_code == 422


def test_delete_cancels_answer_removes_files_and_prevents_resurrection(fixture):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    assert (bridge / f"{answer['id']}.request.json").exists()
    result = client.delete("/api/documents/public-one")
    assert result.status_code == 200
    assert not (bridge / f"{answer['id']}.request.json").exists()
    response_file(bridge, answer, {"abstain": False, "reason": "", "claims": []})
    assert client.get(f"/api/answers/{answer['id']}").json()["state"] == "cancelled"
    assert not (bridge / f"{answer['id']}.response.json").exists()
    assert search(client, "confabulation")["hits"] == []


def test_valid_citation_quote_and_usage(fixture):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    context = json.loads((bridge / f"{answer['id']}.request.json").read_text())["contexts"][0]
    response_file(
        bridge,
        answer,
        {
            "abstain": False,
            "reason": "",
            "claims": [
                {
                    "text": "A source describes risk",
                    "supports": [{"chunk_id": context["chunk_id"], "quote": QUOTE}],
                }
            ],
        },
        usage={"input_tokens": 15},
    )
    done = client.get(f"/api/answers/{answer['id']}").json()
    assert done["state"] == "succeeded"
    assert done["citations"][0]["page"] == 3
    assert done["usage"] == {"input_tokens": 15}


@pytest.mark.parametrize(
    "support",
    [
        {"chunk_id": "unknown", "quote": QUOTE},
        {"chunk_id": "REPLACE", "quote": "An entirely invented passage without source support."},
    ],
)
def test_invalid_citation_or_quote_fails(fixture, support):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    context = json.loads((bridge / f"{answer['id']}.request.json").read_text())["contexts"][0]
    support["chunk_id"] = context["chunk_id"] if support["chunk_id"] == "REPLACE" else "unknown"
    response_file(
        bridge,
        answer,
        {
            "abstain": False,
            "reason": "",
            "claims": [{"text": "unsupported claim", "supports": [support]}],
        },
    )
    assert client.get(f"/api/answers/{answer['id']}").json()["state"] == "failed"


def test_unknown_response_fields_and_nonfinite_fail(fixture):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    response_file(
        bridge, answer, {"abstain": True, "reason": "unknown", "claims": []}, extra="not permitted"
    )
    assert client.get(f"/api/answers/{answer['id']}").json()["state"] == "failed"


def test_queued_cap_persists_after_restart(fixture):
    client, _, prepared, bridge, tmp = fixture
    assert all(queued(client)["state"] == "queued" for _ in range(3))
    assert client.post("/api/answers", json={"question": "confabulation"}).status_code == 429
    with TestClient(
        create_app(tmp / "folio.sqlite", prepared, bridge), base_url="http://localhost"
    ) as again:
        assert again.post("/api/answers", json={"question": "confabulation"}).status_code == 429


def test_total_ten_attempts_persist(fixture):
    client, _, _, bridge, _ = fixture
    for _ in range(10):
        answer = queued(client)
        response_file(
            bridge, answer, {"abstain": True, "reason": "No supported answer", "claims": []}
        )
        assert client.get(f"/api/answers/{answer['id']}").json()["state"] == "abstained"
    assert client.post("/api/answers", json={"question": "confabulation"}).status_code == 429


def test_no_hits_abstains_locally(fixture):
    client, *_ = fixture
    answer = client.post("/api/answers", json={"question": "xylophonically bizarre"}).json()
    assert answer["state"] == "abstained" and "model" not in answer


def test_malicious_import_fields_and_unknown_id_rejected(fixture):
    client, *_ = fixture
    assert (
        client.post(
            "/api/documents", json={"title": "a", "text": "b", "source_url": "https://evil"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/documents", json={"title": "a", "text": "b", "document_id": "../other"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/documents", json={"title": "a", "text": "b", "document_id": "missing"}
        ).status_code
        == 404
    )


def test_symlink_response_is_not_consumed(fixture, tmp_path):
    client, _, _, bridge, _ = fixture
    answer = queued(client)
    external = tmp_path / "external.json"
    external.write_text("{}")
    (bridge / f"{answer['id']}.response.json").symlink_to(external)
    assert client.get(f"/api/answers/{answer['id']}").json()["state"] == "failed"
    assert external.exists()


def test_concurrent_answer_requests_obey_pending_limit(fixture):
    client, *_ = fixture
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(
            pool.map(
                lambda _: (
                    client.post("/api/answers", json={"question": "confabulation"}).status_code
                ),
                range(8),
            )
        )
    assert codes.count(200) == 3 and codes.count(429) == 5


def test_heartbeat_does_not_invent_online_state(fixture):
    client, _, _, bridge, _ = fixture
    assert client.get("/api/state").json()["bridge"] == {"heartbeat_at": None, "online": False}
    (bridge / "heartbeat.json").write_text(
        json.dumps({"at": time.time() - 60, "model": "cookllm", "status": "ready", "calls": 0})
    )
    assert client.get("/api/state").json()["bridge"]["online"] is False
