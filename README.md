# Folio — private AI knowledge engine

**[Open the GitHub Pages browser demo](https://skuraganti.github.io/private-ai-knowledge-engine/)** · [Architecture](ARCHITECTURE.md) · [Data sources](DATA_SOURCES.md) · [Verification](VERIFICATION.md) · [Public roadmap](https://github.com/users/skuraganti/projects/4)

Folio is a local, single-user workbench for researching engineering-risk questions in a pinned document corpus. Public-document results link to an exact passage, a physical PDF page and hash provenance. Imported notes use local text-page indices; a search-hit hash identifies chunk text, while the document inspector exposes the original PDF hash. The corpus is three original NIST publications: AI RMF 1.0 (NIST AI 100-1), the Generative AI Profile (NIST AI 600-1) and SSDF 1.1 (NIST SP 800-218). Folio is a retrieval and evidence tool, not compliance or legal advice.

![Folio GitHub Pages demo: a lexical search over original NIST passages, with an extractive answer quoting matched excerpts, each showing its document, physical PDF page and official PDF link.](assets/folio-demo.png)

## A research workflow

1. Select SSDF and ask *What does PW.9 say about secure software configuration defaults?*
2. Compare the lexical, latent and hybrid rankings. Open the cited passage on SSDF physical PDF page 25, and check the document's SHA-256 against [DATA_SOURCES.md](DATA_SOURCES.md).
3. Import a short private note, search one of its unique terms, edit it and watch the version change and the old term disappear. Delete it, and it leaves search results and invalidates earlier answers.
4. Open the evaluation view, including where hybrid retrieval did *worse*.

Public PDF pages are 1-based physical pages, not printed page numbers. An exact quote proves where text came from, not that a claim is true.

## How it works

- **Hybrid retrieval.** SQLite FTS5 BM25 and a local TF-IDF + truncated SVD model each rank chunks. Equal-weight reciprocal rank fusion (k = 60, deterministic ties) combines them. The latent model is refitted in memory over active chunks only (at most 1,000 chunks and 10,000 features). It is not a neural embedding, and no pretrained weights are downloaded.
- **Incremental updates and deletion.** A document's identity covers its original bytes and prepared page content. Only changed documents replace their chunks. Any corpus change invalidates the latent cache, rebuilt on the next latent/hybrid query, and cancels or invalidates dependent local answers.
- **Local private-document search.** Imported document snippets are excluded from inference. If any retrieved passage is private, generation is refused and search stays local. The optional bridge also re-checks each excerpt against the pinned public originals. Optional generation sends the entered question and approved public snippets through that bridge; keep private content out of the question.
- **Evidence provenance.** Chunk IDs are derived from document, version, page and position. Each accepted generated claim needs one to three exact quotes from the current indexed version. A stale or invalid citation fails visibly instead of being repaired.

Queue and crash handling are covered in [ARCHITECTURE.md](ARCHITECTURE.md) and [API_CONTRACT.md](API_CONTRACT.md); review findings and corrections are in [DECISIONS.md](DECISIONS.md).

## Pages demo vs. full application

| | Pages demo | Full local app |
|---|---|---|
| Corpus | 402 captured NIST page passages ([fixture and checksum](PUBLIC_DEMO_DATA.md)) | Locally acquired PDFs plus your private notes |
| Retrieval | Lexical, in the browser | BM25, TF-IDF/SVD and hybrid |
| Answers | Extractive: quotes up to three passages, or abstains | Optional cited generation through the existing authorized remote-model bridge, for public sources only |
| Changes | Hiding a document affects only the current page | Import, edit, delete and restore, persisted in SQLite |

Pages has no backend, credentials or model calls. It displays the recorded metrics but does not compute them. The walkthroughs are in [docs/DEMO.md](docs/DEMO.md) (Pages) and [DEMO.md](DEMO.md) (local).

## Recorded retrieval evaluation

The evaluation uses 12 project-authored held-out questions, frozen by hash ([evals/FREEZE.json](evals/FREEZE.json)) with no held-out tuning. Each is scored against designated page anchors over 318 chunks.

| Mode | Hit@5 | MRR@5 |
|---|---:|---:|
| Lexical (BM25) | 11/12 | 0.861 |
| Latent (TF-IDF/SVD) | 10/12 | 0.649 |
| Hybrid (RRF) | 11/12 | 0.808 |

Hybrid tied lexical on Hit@5 but had a lower MRR@5, and a development definition question missed its source page. These are recorded results ([examples/recorded-retrieval-evaluation.json](examples/recorded-retrieval-evaluation.json)) from one small corpus with incomplete relevance labels, not a general benchmark. Some live model evaluations abstained or failed. A safe abstention can still leave the question unanswered, so it is not counted as automatic success.

## Run locally

Requirements: a POSIX host (macOS or Linux), Python 3.13+, [uv](https://docs.astral.sh/uv/), and Docker with Compose. No GPU is needed. Bootstrap copies the recorded evaluation and runs `scripts/acquire.py`, which downloads the three NIST PDFs, extracts their pages with pypdf and writes checksum manifests to the Git-excluded `data/` directory.

```sh
uv sync --frozen
uv run python scripts/bootstrap.py
sh stack.sh up
```

Check `sh stack.sh status` and wait for healthy, then open **http://127.0.0.1:8283**. `sh stack.sh stop` stops the app and any bridge, and keeps local data and the named volume. You can also run `sh stack.sh status` or `sh stack.sh logs`. The defaults work without copying `.env.example`, which documents `FOLIO_PORT`, `FOLIO_UID`, `FOLIO_DB`, `FOLIO_PREPARED` and `FOLIO_BRIDGE`. The stack binds only to 127.0.0.1.

**Optional bridge.** Search works without a model. On a host already configured for the existing authorized `claude-omni` / `cookllm` route (with `zsh`), `sh stack.sh bridge` starts a fixed, tool-free operation for cited generation over public snippets. Inference may run remotely. The repository includes no credentials, no model service and no fallback provider. At most three generation requests can be pending. The persistent app state allows ten queued attempts, including failures and cancellations; the host bridge keeps a separate ten-call ledger with no automatic retry. Pages never contacts the bridge.

## Verify and evaluate

```sh
uv run pytest
uv run ruff check .
uv run python evaluate.py
python3 -m http.server 8008 --bind 127.0.0.1 --directory docs
```

Run bootstrap first. Native tests use fixtures and simulated model responses, with no live inference. `evaluate.py` reruns the frozen retrieval evaluation without network or model calls, writes `data/verification/retrieval.json` and replaces `data/prepared/evaluation.json` with a retrieval-only report (`live: null`). The tracked recorded example stays intact; a later bootstrap refuses to overwrite the changed local report, so use a separate checkout to reproduce the original bootstrap state. The last command previews Pages at http://127.0.0.1:8008; leave it running. In a second terminal, with agent-browser 0.38.1 installed, `sh scripts/check-pages.sh http://127.0.0.1:8008` runs `tests/pages-smoke.js`. The recorded release suite passed 36 native tests; those tests were not rerun for this documentation edit. Release checks and their limits are in [VERIFICATION.md](VERIFICATION.md).

## Scope and limitations

Folio is a single-user localhost app with no authentication, and it is not a distributed vector service. The corpus is a static snapshot of three overlapping US reports. Extraction keeps hyphenation splits and an imperfect table order, so check the linked originals when layout matters. Deletion removes indexed, answer and queue copies, but acquired originals stay in the local cache, and an explicit *Restore* can bring back a deleted public document. Deletion invalidates local answer and queue copies; it cannot retract an already dispatched inference request. Bridge models are not pinned, so live outputs can vary.

## Sources, attribution and license

The documents are republished courtesy of the National Institute of Standards and Technology. No NIST endorsement is implied, and third-party material inside them can carry separate rights. Citations, DOIs and reuse terms are in [DATA_SOURCES.md](DATA_SOURCES.md), and source versions are in [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json). The original implementation was developed with Claude Code, with architecture, integration, review, correction and independent verification by ChatGPT. Upstream components are credited in [UPSTREAM.md](UPSTREAM.md), and third-party licenses remain in force. No additional license grant for the original implementation has been selected.
