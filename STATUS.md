# Release status

**Local release gates: verified on 2026-10-16.** Source, native tests, Docker workflow/persistence, Pages browser/mobile/error states and publication privacy review passed. Actual publication is recorded by GitHub commit/deployment metadata after this prepared initial commit. See [VERIFICATION.md](VERIFICATION.md) for exact checks and limits.

Local: `sh stack.sh up` → http://127.0.0.1:8283. [Pages demo](https://skuraganti.github.io/private-ai-knowledge-engine/) · [Source](https://github.com/skuraganti/private-ai-knowledge-engine). Pages uses static browser interactions; full Python services run locally. Runtime databases, caches, model-control files and credentials stay excluded. The Pages demo runs lexical search and extractive quotations, not a remote model. On12held-out retrieval questions, hybrid Hit@5=11/12 tied lexical; this is a small corpus, not evidence of general superiority. Some live model evaluations abstained or failed.

Next maintenance action: use the documented setup, verify original-source checksums before updating fixtures, rerun affected tests and retain failed/uncertain evaluation outcomes. No hosted inference or unattended service is supplied by Pages.
