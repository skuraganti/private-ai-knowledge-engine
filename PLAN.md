# Folio development and publication plan

Actual development/publication preparation2026-10-16. The full application is independent, useful and locally runnable. Original-document ingestion, hybrid FTS5/TF-IDF-SVD retrieval, source-linked RAG, incremental updates, deletion propagation and held-out evaluation.

Completed original milestones: define user/workflow/non-goals; compare real-data candidates; pin sources/licenses; scoped implementation; integration and corrections; native/Docker/browser/persistence checks; record actual results and limitations. Public release adds a separate static browser demo, reviewed examples, reproducible bootstrap, portable configuration and publication checks before an initial commit.

Publication gates: clean-source/native tests after bootstrap, Docker health and real-data smoke workflow, Pages relative-path functionality/mobile/accessibility, credential/privacy/license review, truthful metadata, one initial commit, then sequential push/Pages deployment and public URL verification. A failure stops that repository's publication until corrected. No fabricated history or model-evaluation outcome is allowed.

The Pages demo runs lexical search and extractive quotations, not a remote model. On12held-out retrieval questions, hybrid Hit@5=11/12 tied lexical; this is a small corpus, not evidence of general superiority. Some live model evaluations abstained or failed.
