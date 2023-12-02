# Retrieval evaluation

Folio has two separate retrieval evaluations. Neither tunes retrieval, uses labels during search, or calls a model, the bridge or the answer queue.

| | Legacy v1 | Retrieval v2 |
|---|---|---|
| Cases | 12 held-out (`evals/heldout.json`) plus 4 development | 24 purposive cases: 8 per NIST document (3 direct, 3 procedural, 2 nearby-wording) |
| Freeze | `evals/FREEZE.json` | `evals/retrieval-v2/FREEZE.json`, authored and frozen by the maintainer |
| Runner | `evaluate.py` | `scripts/evaluate_retrieval.py` |
| Output | `data/verification/retrieval.json` and `data/prepared/evaluation.json` | a new file under `data/verification/retrieval-v2/` |
| Recorded result | Hit@5 lexical 11/12, latent 10/12, hybrid 11/12; MRR 0.861 / 0.649 / 0.808 ([recorded](../examples/recorded-retrieval-evaluation.json)) | Hit@5 lexical 20/24, latent 17/24, hybrid 19/24 ([recorded](../examples/recorded-retrieval-v2.json)) |

The v1 cases, freeze and reports are left unchanged. The v2 cases are a purposive cohort, not a random sample, so neither result generalizes beyond these three English NIST reports.

## Running v2

Complete the [local setup](../README.md#run-locally) first (`uv sync --frozen` and `uv run python scripts/bootstrap.py`). Preparation acquires the pinned public PDFs; the evaluator itself makes no network requests.

```sh
uv run python scripts/evaluate_retrieval.py \
  --cases evals/retrieval-v2/cases.json \
  --freeze evals/retrieval-v2/FREEZE.json \
  --output data/verification/retrieval-v2/run-001.json
```

**Before anything is indexed**, the runner checks every pin in the freeze:
- the cases file;
- `data/prepared/manifest.json` and `preparation.json`;
- each source document ID and PDF SHA-256 declaration in the pinned prepared manifest (PDF bytes are not rehashed by this runner);
- the exact bytes of `app/retrieval.py` and `app/store.py`.

It also validates the case schema `{id, query, document_id, pages, support:[{page, excerpt}], category}`. It rejects:
- unknown documents;
- out-of-range or duplicate designated pages;
- support excerpts on pages that aren't designated;
- unknown categories.

Input validation failure stops the run with nothing written. A failed retrieval request remains a zero in its mode denominator, is recorded separately, and marks the report incomplete; the CLI exits unsuccessfully. The report observes model attempts and pending reservations before and after the temporary run and requires both to stay zero.

**The run itself:**
- **Storage:** a fresh temporary Store and queue index a private copy of the verified manifest bytes.
- **Algorithm:** the existing BM25, TF-IDF/SVD and reciprocal-rank-fusion code, unchanged.
- **Search:** each query runs once per mode (`lexical`, `latent`, `hybrid`) for the top 5, always over all three documents. Gold labels are used only afterwards, for scoring.
- **Output:** written exclusively; an existing output file is refused, as are the legacy v1 paths. No network access is used.

**The report contains:**
- **Per case and mode:** the rank of the first designated page, matched and designated pages, distinct designated-page recall, every hit (chunk, document, page, hash, scores) and timing.
- **Per mode, document and category:** n, Hit@5, MRR@5, recall and the list of misses. Misses are never dropped.
- **Provenance:** runner, code, corpus, case and freeze hashes, plus Python, platform, package versions and BLAS thread settings.

## Reading the numbers

- **Incomplete labels:** designated pages are incomplete relevance labels. Another page can also answer a question, and overlapping chunks can return the same page twice. Recall counts distinct pages.
- **Timing:** one sequential pass is an observation, not a controlled latency benchmark. The first latent retrieval also fits TF-IDF/SVD, and the report marks that fit. Hybrid reuses it. This is not whole-application startup timing; reported elapsed time excludes input validation/imports and output serialization.
- **Scope:** these are retrieval measurements only. They are not answer accuracy or broad search-quality claims.

## Recorded answer diagnostics (v1, separate from retrieval)

- The original four live application calls produced one supported answer and three safe abstentions. All four passed transport and response-schema validation.
- The three held-out live checks covered a supported answer, an unknown-measurement request and a synthetic override that had to be refused. Meeting their criteria 3/3 is therefore **not** 100% answer accuracy.
- The development question "What is confabulation in generative AI?" safely abstained but failed the information-task criterion. The archived adjudication attributed the missing definition to retrieval. The original contexts were not retained, so that cause has not been independently re-proven.
- A later browser repeat was not an independent sample.
- This archive holds no saved transport or JSON failure.

The sanitized existing observations are in [`examples/recorded-answer-diagnostics-v1.json`](../examples/recorded-answer-diagnostics-v1.json).

Source documents, their provenance and the licensing position, including the absence of any additional license grant, are described in [DATA_SOURCES.md](../DATA_SOURCES.md) and [LICENSING.md](../LICENSING.md).

## First frozen v2 result

All 72 requests completed over 3 documents / 318 chunks, with no request failures. Observed temporary model attempts and pending reservations stayed zero before and after.

| Mode | Page Hit@5 | MRR@5 |
|---|---:|---:|
| Lexical | 20/24 | 0.711806 |
| Latent | 17/24 | 0.560417 |
| Hybrid | 19/24 | 0.666667 |

Every designated-page miss is retained in the [full recorded report](../examples/recorded-retrieval-v2.json), including per-document and per-category denominators, all returned hit identities and actual runtime/hash records. Hybrid did not improve on lexical for this purposive set. No questions, anchors, ranking settings or original results were changed after seeing the scores. The original 12-case results remain separate; this is not a population estimate or a generation study.
