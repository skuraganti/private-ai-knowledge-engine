"""Offline, frozen retrieval evaluation (v2). No network, model, bridge or answer calls.

Every pinned input is verified before any Store exists: cases, prepared corpus, source hashes and
the retrieval/store code. The Store then indexes a private copy of exactly the verified corpus
bytes. Gold labels are used only for scoring; every search runs over all prepared documents.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODES = ("lexical", "latent", "hybrid")
TOP_K = 5
CATEGORIES = {"direct", "procedural", "nearby"}
ALGORITHMS = ("app/retrieval.py", "app/store.py")
LEGACY = ("data/prepared/evaluation.json", "data/verification/retrieval.json")
FREEZE_KEYS = set(
    "cases_sha256 prepared_manifest_sha256 preparation_sha256 sources algorithm_sha256 "
    "frozen_at parameters policy".split()
)
SHA = re.compile(r"[0-9a-f]{64}")


class EvaluationError(ValueError):
    """An input failed validation; nothing was evaluated or written."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path, label: str) -> tuple[bytes, object]:
    if not path.is_file() or path.is_symlink():
        raise EvaluationError(f"{label} missing or not a regular file: {path}")
    data = path.read_bytes()
    try:
        return data, json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"{label} is not valid JSON") from exc


def _pin(actual: str, expected: object, label: str) -> None:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise EvaluationError(f"freeze {label} is not a SHA-256 hex digest")
    if actual != expected:
        raise EvaluationError(f"{label} does not match the freeze")


def _validate_freeze(freeze: object) -> dict:
    if not isinstance(freeze, dict) or set(freeze) != FREEZE_KEYS:
        raise EvaluationError("freeze must have exactly: " + ", ".join(sorted(FREEZE_KEYS)))
    algorithms = freeze["algorithm_sha256"]
    if not isinstance(algorithms, dict) or set(algorithms) != set(ALGORITHMS):
        raise EvaluationError("freeze algorithm_sha256 must pin " + ", ".join(ALGORITHMS))
    sources = freeze["sources"]
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(s, dict) and set(s) == {"id", "sha256"} for s in sources)
    ):
        raise EvaluationError("freeze sources must be a non-empty list of {id, sha256}")
    parameters = freeze["parameters"]
    if not isinstance(parameters, dict):
        raise EvaluationError("freeze parameters must be an object")
    for key, value in (("top_k", TOP_K), ("modes", list(MODES)), ("limit", TOP_K)):
        if key in parameters and parameters[key] != value:
            raise EvaluationError(f"freeze parameter {key} differs from this harness ({value})")
    if not isinstance(freeze["frozen_at"], str) or not freeze["frozen_at"]:
        raise EvaluationError("freeze frozen_at must be a non-empty string")
    return freeze


def _validate_cases(cases: object, documents: dict[str, int]) -> list[dict]:
    if (
        not isinstance(cases, dict)
        or set(cases) != {"cases"}
        or not isinstance(cases["cases"], list)
    ):
        raise EvaluationError("cases file must be {cases: [...]}")
    keys, seen = {"id", "query", "document_id", "pages", "support", "category"}, set()
    for case in cases["cases"]:
        if not isinstance(case, dict) or set(case) != keys:
            raise EvaluationError("each case needs exactly: " + ", ".join(sorted(keys)))
        cid, pages = case["id"], case["pages"]
        if not isinstance(cid, str) or not cid or cid in seen:
            raise EvaluationError(f"case id missing or duplicated: {cid!r}")
        seen.add(cid)
        if not isinstance(case["query"], str) or not 1 <= len(case["query"].strip()) <= 500:
            raise EvaluationError(f"{cid}: query must be 1..500 characters")
        if case["document_id"] not in documents:
            raise EvaluationError(f"{cid}: document_id is not a prepared document")
        if case["category"] not in CATEGORIES:
            raise EvaluationError(f"{cid}: category must be one of {sorted(CATEGORIES)}")
        if (
            not isinstance(pages, list)
            or not pages
            or not all(type(p) is int and 1 <= p <= documents[case["document_id"]] for p in pages)
        ):
            raise EvaluationError(f"{cid}: pages must be valid 1-based pages of its document")
        if len(set(pages)) != len(pages):
            raise EvaluationError(f"{cid}: duplicate designated pages")
        support = case["support"]
        if (
            not isinstance(support, list)
            or not support
            or not all(
                isinstance(s, dict)
                and set(s) == {"page", "excerpt"}
                and type(s["page"]) is int
                and s["page"] in pages
                and isinstance(s["excerpt"], str)
                and s["excerpt"].strip()
                for s in support
            )
        ):
            raise EvaluationError(f"{cid}: support must be {{page, excerpt}} on designated pages")
    if not seen:
        raise EvaluationError("cases file has no cases")
    return cases["cases"]


def _score(case: dict, found: dict) -> dict:
    designated = case["pages"]
    relevant = [
        (rank, hit["page"])
        for rank, hit in enumerate(found["hits"], 1)
        if hit["document_id"] == case["document_id"] and hit["page"] in designated
    ]
    matched = sorted({page for _, page in relevant})
    return {
        "first_relevant_rank": relevant[0][0] if relevant else None,
        "matched_pages": matched,
        "designated_pages": designated,
        "designated_page_recall": len(matched) / len(designated),
        "took_ms": found["took_ms"],
        "hits": [
            {"rank": rank}
            | {k: hit[k] for k in ("chunk_id", "document_id", "version", "page", "sha256", "score")}
            | {k: hit[k] for k in ("lexical_rank", "latent_rank") if k in hit}
            for rank, hit in enumerate(found["hits"], 1)
        ],
    }


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    ranks = [row["first_relevant_rank"] for row in rows]
    return {
        "n": n,
        "hits_at_5": sum(rank is not None for rank in ranks),
        "hit_at_5": sum(rank is not None for rank in ranks) / n,
        "mrr_at_5": sum(1 / rank for rank in ranks if rank) / n,
        "designated_page_recall_at_5": sum(row["designated_page_recall"] for row in rows) / n,
        "misses": [row["case_id"] for row in rows if row["first_relevant_rank"] is None],
    }


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def run(cases_path: Path, freeze_path: Path, output: Path, *, root: Path = ROOT) -> dict:
    output = output if output.is_absolute() else root / output
    verification = (root / "data" / "verification").resolve()
    target = output.resolve()
    if target in {(root / legacy).resolve() for legacy in LEGACY}:
        raise EvaluationError("refusing to write a legacy v1 output")
    if verification not in target.parents:
        raise EvaluationError("output must be inside data/verification/")
    if output.exists():
        raise EvaluationError(f"output already exists; choose a new run path: {output}")

    freeze_bytes, freeze = _load(freeze_path, "freeze")
    _validate_freeze(freeze)
    policy_hashes = {}
    policy = freeze["policy"]
    if isinstance(policy, dict):
        for name, key in (
            ("PROTOCOL.md", "protocol_sha256"),
            ("SOURCE_CHECK.json", "source_check_sha256"),
        ):
            if key in policy:
                path = freeze_path.parent / name
                if not path.is_file() or path.is_symlink():
                    raise EvaluationError(f"missing policy artifact: {name}")
                policy_hashes[name] = _sha(path.read_bytes())
                _pin(policy_hashes[name], policy[key], name)
    cases_bytes, cases = _load(cases_path, "cases")
    _pin(_sha(cases_bytes), freeze["cases_sha256"], "cases_sha256")
    prepared = root / "data" / "prepared"
    manifest_bytes, manifest = _load(prepared / "manifest.json", "prepared manifest")
    preparation_bytes, _ = _load(prepared / "preparation.json", "preparation record")
    _pin(_sha(manifest_bytes), freeze["prepared_manifest_sha256"], "prepared_manifest_sha256")
    _pin(_sha(preparation_bytes), freeze["preparation_sha256"], "preparation_sha256")
    if not isinstance(manifest, list) or not all(isinstance(d, dict) for d in manifest):
        raise EvaluationError("prepared manifest must be a list of documents")
    pinned_sources = sorted((s["id"], s["sha256"]) for s in freeze["sources"])
    if sorted((d.get("id"), d.get("sha256")) for d in manifest) != pinned_sources:
        raise EvaluationError("prepared documents differ from the frozen source list")
    algorithm_bytes = {}
    for name in ALGORITHMS:
        algorithm_bytes[name] = (ROOT / name).read_bytes()
        _pin(_sha(algorithm_bytes[name]), freeze["algorithm_sha256"][name], name)
    documents = {
        d["id"]: max((p.get("page", 0) for p in d.get("pages", [])), default=0) for d in manifest
    }
    validated = _validate_cases(cases, documents)
    page_text = {(d["id"], p["page"]): p["text"] for d in manifest for p in d["pages"]}
    for case in validated:
        for support in case["support"]:
            if support["excerpt"] not in page_text.get((case["document_id"], support["page"]), ""):
                raise EvaluationError(f"{case['id']}: support excerpt is not literal page text")

    parameters = freeze["parameters"]
    expected_design = {"cases": len(validated), "documents": sorted(documents)}
    for key, actual in expected_design.items():
        declared = parameters.get(key, actual)
        if (
            sorted(declared) if key == "documents" and isinstance(declared, list) else declared
        ) != actual:
            raise EvaluationError(f"freeze parameter {key} differs from the case design")
    counts_by_doc = Counter(c["document_id"] for c in validated)
    if "cases_per_document" in parameters and any(
        count != parameters["cases_per_document"] for count in counts_by_doc.values()
    ):
        raise EvaluationError("freeze cases_per_document differs from the case design")
    if "category_mix_per_document" in parameters and any(
        dict(Counter(c["category"] for c in validated if c["document_id"] == doc))
        != parameters["category_mix_per_document"]
        for doc in documents
    ):
        raise EvaluationError("freeze category mix differs from the case design")
    if parameters.get("requests_per_case_per_mode", 1) != 1 or parameters.get(
        "planned_retrieval_requests", len(validated) * len(MODES)
    ) != len(validated) * len(MODES):
        raise EvaluationError("freeze request count differs from the case design")
    if parameters.get("query_scope", "all_documents") not in {
        "all_documents",
        "all_three_original_active_documents; gold document IDs are grading-only",
    }:
        raise EvaluationError("freeze query_scope must search all documents")
    if parameters.get("model_calls_allowed", 0) != 0:
        raise EvaluationError("this evaluator permits zero model calls")

    sys.path.insert(0, str(ROOT))
    from app.store import Store  # imported only after the code hashes are verified

    rows = {mode: [] for mode in MODES}
    cold = None
    failures = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="folio-eval-v2-") as directory:
        base = Path(directory)
        (base / "prepared").mkdir()
        (base / "prepared" / "manifest.json").write_bytes(manifest_bytes)  # verified bytes only
        store = Store(base / "eval.sqlite", base / "prepared", base / "queue")
        store.initialize()
        state = store.state()
        budget_before = state["model_budget"]
        indexed = sorted(d["id"] for d in state["documents"])
        if indexed != sorted(documents):
            raise EvaluationError("Store did not index every prepared document")
        for mode in MODES:
            for case in validated:
                query_started = time.perf_counter()
                error_type = None
                try:
                    found = store.search(case["query"], mode, TOP_K)  # no gold filters
                except Exception as error:
                    error_type = type(error).__name__
                    failures.append({"case_id": case["id"], "mode": mode, "error_type": error_type})
                    found = {"hits": [], "took_ms": (time.perf_counter() - query_started) * 1000}
                row = {"case_id": case["id"], "category": case["category"]}
                row |= {"document_id": case["document_id"], "mode": mode} | _score(case, found)
                row["error_type"] = error_type
                if mode == "latent" and cold is None:  # this query also fits TF-IDF/SVD
                    cold = {"mode": mode, "case_id": case["id"], "took_ms": found["took_ms"]}
                rows[mode].append(row)
        counts = state["counts"]
        budget_after = store.state()["model_budget"]
        if any(
            b[key] != 0 for b in (budget_before, budget_after) for key in ("attempted", "pending")
        ):
            raise EvaluationError("temporary evaluation store has nonzero model reservations")
    report = {
        "evaluation": "retrieval-v2",
        "complete": not failures,
        "request_failures": failures,
        "model_budget": {"before": budget_before, "after": budget_after},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observational_note": (
            "One sequential pass on one machine. Timings are observations, not a controlled "
            "latency benchmark; the first latent query fits TF-IDF/SVD (cold start). Designated "
            "pages are incomplete relevance labels, so scores are not broad accuracy claims."
        ),
        "cold_start": cold,
        "parameters": {"top_k": TOP_K, "modes": list(MODES), "candidates": indexed},
        "corpus": {"documents": len(indexed), "chunks": counts["chunks"]},
        "summary": {mode: _summary(rows[mode]) for mode in MODES},
        "by_document": {
            mode: {
                doc: _summary([r for r in rows[mode] if r["document_id"] == doc])
                for doc in indexed
                if any(r["document_id"] == doc for r in rows[mode])
            }
            for mode in MODES
        },
        "by_category": {
            mode: {
                category: _summary([r for r in rows[mode] if r["category"] == category])
                for category in sorted({r["category"] for r in rows[mode]})
            }
            for mode in MODES
        },
        "results": [row for mode in MODES for row in rows[mode]],
        "hashes": {
            "policy_artifacts": policy_hashes,
            "uv_lock": _sha((ROOT / "uv.lock").read_bytes()),
            "runner": _sha(Path(__file__).read_bytes()),
            "algorithms": {name: _sha(data) for name, data in algorithm_bytes.items()},
            "cases": _sha(cases_bytes),
            "freeze": _sha(freeze_bytes),
            "prepared_manifest": _sha(manifest_bytes),
            "preparation": _sha(preparation_bytes),
        },
        "freeze": {k: freeze[k] for k in ("frozen_at", "parameters", "policy")},
        "runtime": {
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "packages": {p: _version(p) for p in ("numpy", "scipy", "scikit-learn")},
            "threads": {
                k: os.environ.get(k)
                for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
            },
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target_file:  # exclusive: never overwrite a run
        json.dump(report, target_file, ensure_ascii=False, indent=2)
        target_file.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = run(arguments.cases, arguments.freeze, arguments.output)
    except EvaluationError as error:
        raise SystemExit(f"evaluation refused: {error}") from None
    print(json.dumps({"complete": result["complete"], "summary": result["summary"]}, indent=2))
    raise SystemExit(0 if result["complete"] else 1)
