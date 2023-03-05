# Upstream use and original work

2026-10-16: reviewed [Haystack DocumentJoiner](https://docs.haystack.deepset.ai/docs/documentjoiner), an [Apache2.0 project](https://github.com/deepset-ai/haystack/blob/main/LICENSE), for the useful hybrid-retrieval/reciprocal-rank-fusion pattern. Its full pipeline and external vector services are unnecessary for this bounded local corpus. No Haystack source was copied and no Haystack runtime dependency is installed. This is conceptual inspiration, not compatibility or reproduced performance.

Original work here: scoped document/version lifecycle, citation snapshots, deletion invalidation, pinned-public-only bridge, evidence review interface, frozen local evaluation cases and independent acceptance harness. ClaudeCode is the primary backend implementation worker, supervised/corrected/verified by ChatGPT; no concealed provenance or employer attribution.

Dependencies include FastAPI/Starlette/uvicorn (framework licenses), NumPy/SciPy/scikit-learn (BSD), pypdf (BSD3) and httpx(BSD3); exact versions and package hashes are locked. Local [TruncatedSVD](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.TruncatedSVD.html) fits latent semantics over the active corpus; it is not a neural embedding model. No pretrained weights, external vectorDB or additional inference provider.

The supervisor reused its own earlier project HTTP boundaries, stack-management ideas and browser-verification harness as separate source copies. No cross-project runtime imports/dependency sharing or mutable state. NIST publications follow their own attribution/third-party policy in DATA_SOURCES.md. If axe-core is used for QA, keep its MPL-2.0 notice/version source in the excluded verification cache; it is not runtime code.
