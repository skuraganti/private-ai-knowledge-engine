"""Frozen held-out page retrieval evaluation. No network/model calls, no question training."""

import datetime as dt
import hashlib
import json
import platform
import statistics
import sys
import tempfile
from pathlib import Path

from app.store import Store

ROOT = Path(__file__).resolve().parent


def main():
    cases_path = ROOT / "evals/heldout.json"
    freeze = json.loads((ROOT / "evals/FREEZE.json").read_text())
    assert hashlib.sha256(cases_path.read_bytes()).hexdigest() == freeze["heldout_sha256"]
    cases = json.loads(cases_path.read_text())["cases"]
    results = []
    metrics = []
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        store = Store(base / "eval.sqlite", ROOT / "data/prepared", base / "queue")
        store.initialize()
        counts = store.state()["counts"]
        for mode in ("lexical", "latent", "hybrid"):
            mode_rows = []
            for case in cases:
                found = store.search(case["query"], mode, 5)
                relevant = [
                    (rank, hit["page"])
                    for rank, hit in enumerate(found["hits"], 1)
                    if hit["document_id"] == case["document_id"] and hit["page"] in case["pages"]
                ]
                matched = sorted({page for rank, page in relevant})
                record = {
                    "case_id": case["id"],
                    "query": case["query"],
                    "mode": mode,
                    "first_relevant_rank": relevant[0][0] if relevant else None,
                    "matched_pages": matched,
                    "designated_pages": case["pages"],
                    "document_id": case["document_id"],
                    "designated_page_recall": len(matched) / len(case["pages"]),
                    "took_ms": found["took_ms"],
                    "hits": [
                        {
                            "document_id": h["document_id"],
                            "page": h["page"],
                            "chunk_id": h["chunk_id"],
                            "score": h["score"],
                        }
                        for h in found["hits"]
                    ],
                }
                mode_rows.append(record)
                results.append(record)
            metrics.append(
                {
                    "mode": mode,
                    "n": len(mode_rows),
                    "hit_at_5": sum(r["first_relevant_rank"] is not None for r in mode_rows)
                    / len(mode_rows),
                    "mrr": sum(
                        1 / r["first_relevant_rank"] if r["first_relevant_rank"] else 0
                        for r in mode_rows
                    )
                    / len(mode_rows),
                    "designated_page_recall_at_5": statistics.mean(
                        r["designated_page_recall"] for r in mode_rows
                    ),
                    "mean_ms": statistics.mean(r["took_ms"] for r in mode_rows),
                    "median_ms": statistics.median(r["took_ms"] for r in mode_rows),
                }
            )
    report = {
        "available": True,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "methodology": (
            "12 root-authored held-out questions frozen before retrieval evaluation; "
            "single original corpus snapshot, top5 indexed chunks, designated physical PDF "
            "page anchors. BM25, local TF-IDF/SVD and equal-weight reciprocal-rank fusion(k60). "
            "No question labels used in model fitting and no held-out tuning."
        ),
        "limitations": (
            "Page-anchor relevance is incomplete and overlapping chunks can repeat pages. "
            "Hit@5 and MRR are against designated pages, not exhaustive relevance judgments. "
            "One small English institutional corpus; no general superiority claim. "
            "First latent query includes index fitting; sequential timings are observations, "
            "not a controlled benchmark."
        ),
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "host_ram_gib": 8,
            "math_threads": "set OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 for this recorded run",
        },
        "freeze": freeze,
        "counts": counts,
        "retrieval": {"metrics": metrics, "results": results},
        "live": None,
    }
    destination = ROOT / "data/prepared/evaluation.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (ROOT / "data/verification/retrieval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps({"counts": counts, "metrics": metrics, "report": str(destination)}))


if __name__ == "__main__":
    main()
