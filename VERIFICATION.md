# Release verification — 2026-10-16

Actual development and release preparation 2026-10-16. This report records checks on the sanitized public source copy before its initial commit. Deployment is checked separately after pushing, without backdated commits. Passing these bounded checks does not guarantee every future feed, model response or workload.

| Check | Observed result |
|---|---|
| Clean source environment | `uv sync --frozen`, project-specific `scripts/bootstrap.py`: passed |
| Native suite | **36 passed** with Python 3.14.8; FastAPI/Starlette emitted a TestClient deprecation warning |
| Lint | `uv run ruff check .`: passed; pinned upstream corpus files excluded from project style rules |
| Docker | Digest-pinned Python 3.13 image built; startup, HTTP health and application page passed |
| Workflow | Three real NIST documents seeded; hybrid query returned source citations |
| Persistence | Restarted app container; workflow state retained |
| Browser | Isolated Chromium via agent-browser 0.38.1; 7 domain assertions passed; native input/click controls passed |
| Error state | Fixture temporarily unavailable: visible recoverable error; restored fixture loads after reload |
| Responsive layout | 1440×1000 and 390×844 inspected; 390px document width with no page overflow |
| Accessibility | axe-core 4.12.1, WCAG 2 A/AA and 2.1 AA tags: **0 detected violations** |
| Privacy | Candidate-file Gitleaks scan passed; no private home paths, unrelated service IDs, credentials or mutable data included |
| Release inference | **0 model calls**; recorded original model studies remain distinct from release checks |

Browser scenarios: source-backed extractive quote; document removal clears stale answer; edited query recomputed with abstention; no-match empty state; physical-page source citation; query edit invalidates answer; NIST attribution.

Some axe color checks on clipped scroll contents require manual review. Visible desktop/mobile views and the authored foreground/background palette were inspected; the minimum checked ink/muted/link ratio against the declared page/panel backgrounds was 5.68:1. This is a bounded audit, not a universal accessibility certification. Scroll regions are keyboard focusable and tables accompany charts/graphs.

## Corrections and retesting

Query, filter and document-removal changes invalidate old extracts; creating an answer recomputes the current visible corpus. Publisher attribution and third-party rights caveats were added. Long hashes and document names now wrap on mobile.

## Recorded findings and limitations

The Pages demo runs lexical search and extractive quotations, not a remote model. On12held-out retrieval questions, hybrid Hit@5=11/12 tied lexical; this is a small corpus, not evidence of general superiority. Some live model evaluations abstained or failed.

Native tests use explicit fixtures, original-source boundary checks and simulated model responses; they do not perform live inference. See [PUBLIC_DEMO_DATA.md](PUBLIC_DEMO_DATA.md) for the curated Pages fixture and checksum, [DATA_SOURCES.md](DATA_SOURCES.md) for publisher/version/rights and [UPSTREAM.md](UPSTREAM.md) for attribution. Original model studies have small samples and cannot establish general performance or costs.

## Reproduce

```sh
uv sync --frozen
uv run python scripts/bootstrap.py
uv run pytest
uv run ruff check .
sh stack.sh up
```

Local URL: http://127.0.0.1:8283. The container limit is 512 MiB for the app, plus Docker and host process overhead. Tested one portfolio stack at a time on an ARM Mac with 8 GiB host RAM and a 2 GiB Docker VM. No GPU. Defaults use independent named volumes and localhost bindings. Stack stop retains state; no unrelated services are managed.

For Pages: `python3 -m http.server 8008 --bind 127.0.0.1 --directory docs`. With optional agent-browser 0.38.1 installed, run `sh scripts/check-pages.sh`; assertions are in `tests/pages-smoke.js`. No browser automation package is shipped to Pages.

## Retrieval and answer-diagnostic maintenance

**57 native tests passed**, including 21 new harness regressions; Ruff passed on Python 3.14.8. The existing FastAPI/Starlette TestClient deprecation warning remains. Synthetic cases independently exercise rank/recall arithmetic, pre-index pin/schema rejection, literal support validation, failure denominators/incomplete status, unfiltered scope, zero model reservations, protected legacy outputs and exclusive new results.

The new 24 source-grounded cases (8 per report) and all 27 literal excerpts passed independent source review before the first run. Cases, corpus, algorithms and authoring protocol are frozen; the richer accepted proposal remains in the private audit and is linked by fingerprint in the public runtime freeze. The unchanged algorithms searched all three documents for all 72 requests: lexical Hit@5 20/24, latent 17/24, hybrid 19/24; MRR@5 0.711806 / 0.560417 / 0.666667. Every hit rank and denominator was independently recomputed. All misses remain; no post-result tuning or new generation occurred. See the [recorded v2 report](examples/recorded-retrieval-v2.json) for actual UTC, runtime/package/thread settings and code/input hashes. Native math threads were explicitly set to one on the ARM Mac with 8 GiB RAM. The runner verifies prepared text and PDF-hash declarations, not newly downloaded PDF bytes.

Docker build/health, 3-document/318-chunk source search and the browser's source links/legacy evaluation notebook passed. Restarting only the isolated app retained its exact state, revision and model budget (attempted 0, pending 0). The v2 CLI output is separate from the app's original n12 notebook. No model bridge was started.

The sanitized archived answer diagnostic matches the saved four-call study exactly: one supported answer and three safe abstentions, including a development information-task miss. All four transported/schema-validated successfully; the separate browser repeat is excluded from that study. Actual model billing and underlying alias version remain unknown. No new application-model calls were made. Cloud tests lacked the NIST cache (45 passed / 4 pre-existing missing-corpus errors); complete local acceptance used the verified cache.
