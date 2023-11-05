# Corpus and provenance

Selected2026-10-16 after comparing3candidates. Actual source/download/version metadata and SHA-256 are in data/raw/manifest.json; acquisition scripts/acquire.py and local pypdf preparation are reproducible, bounded and separate from runtime. No credential/login/paid source. Prepared source data and PDFs are excluded from future Git tracking.

| Candidate | Value | Decision |
|---|---|---|
| Original NIST Technical Series: AI RMF1.0,GenAI Profile,SSDF1.1 | Related real guidance with distinct terminology, citations, overlapping concepts and physical-page evidence;148pages/~3.86MB PDFs | Chosen for a focused source-backed engineering-risk workbench, not compliance/legal advice |
| [NASA Systems Engineering Handbook Rev2](https://www.nasa.gov/wp-content/uploads/2018/09/nasa_systems_engineering_handbook_0.pdf) | Authentic SP-2016-6105,297physical pages, strong engineering content; diagram/layout-heavy; [NASA reuse terms](https://www.nasa.gov/nasa-brand-center/images-and-media/) require media/third-party care | Valuable alternative; greater layout complexity and broader subject than current bounded workflow. Not acquired |
| [Python3.13 documentation](https://docs.python.org/3.13/) | Native structured technical docs, precise anchors and practical questions; PSFv2 docs with0BSD examples per [license](https://docs.python.org/3.13/license.html) | Good alternative, but overlaps next project's code domain. Not acquired; an actual future acquisition would pin exact3.13.16 revision rather than floating path |

Original publisher: National Institute of Standards and Technology, US Department of Commerce. Recommended citations, accessed2026-10-16:

- Tabassi E. (2023), Artificial Intelligence Risk Management Framework (AI RMF1.0), NIST AI100-1, [DOI10.6028/NIST.AI.100-1](https://doi.org/10.6028/NIST.AI.100-1). Republished courtesy of the National Institute of Standards and Technology.
- NIST (2024), Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile, NIST AI600-1, [DOI10.6028/NIST.AI.600-1](https://doi.org/10.6028/NIST.AI.600-1). Republished courtesy of the National Institute of Standards and Technology.
- Souppaya M.,Scarfone K.,Dodson D. (2022), Secure Software Development Framework (SSDF) Version1.1: Recommendations for Mitigating the Risk of Software Vulnerabilities, NIST SP800-218, [DOI10.6028/NIST.SP.800-218](https://doi.org/10.6028/NIST.SP.800-218). Republished courtesy of the National Institute of Standards and Technology.

The [NIST Technical Series reuse policy](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications) says NIST-employee-authored works lack US copyright protection and grants broad reprint/derivative rights where NIST asserts foreign rights; it also preserves possible third-party copyright. Do not label all figures public domain. For example, AI RMF Figure2 credits adapted OECD material. This local demo indexes extracted prose; no figure/brand reproduction or endorsement is implied. No restricted archive/code is executed.

| Original | Bytes | SHA-256 | Physical pages | Text characters |
|---|---:|---|---:|---:|
| ai-rmf.pdf |1,946,127|7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1|48|106,444|
| genai-profile.pdf |1,174,643|6e73620ab6b64e90ef2c04bf0e0d6246185a2f4b1b13cab0df494496cff89b6a|64|160,114|
| ssdf.pdf |739,891|617746e553a9e2da49bfbd4eef0dfc3094758a39b869314e4173ac36605cde22|36|107,398|

Publication editions remain January2023/July2024/February2022; first2 files have2025maintenance timestamps. Preserve HTTPETag/Last-Modified/retrieval times in raw manifest; a maintenance date is not a new publication edition. This is a static snapshot, not live policy.

Preparation schema: immutable manifest records {id,title,url,pdf_name,sha256,publication,remote_allowed,pages:[{page,text}]}. `page` is1-based physical PDF, not printed page. pypdf6.20.1 plain extraction removes soft-hyphen/NUL characters and normalizes horizontal whitespace; original PDFs remain unchanged. No OCR, external document service, figure parsing or dataset script. All148pages have text; an independent re-extraction exactly reproduced373,956characters. There are239/40/21 hyphen-newline splits respectively, presentation ligatures and complex table reading order. Citation quotes match the supplied extracted evidence literally; this protects attribution but does not make extraction perfect. Check linked originals when layout matters.

No sampling of documents/pages; bounded full3-document corpus. Retrieval fits only active source chunks, without question/answer labels. evals/development.json is separate from12frozen heldout queries in evals/heldout.json/FREEZE.json; no heldout-specific prompt/ranking adjustments. Cases are project-specific, not a published benchmark. Page relevance anchors are useful but not exhaustive. Synthetic private notes, invalid outputs and deletion/race fixtures supplement originals and are labeled in tests/reports. Live-model measurements remain separate from mocked tests. No pretrained weight download, new model provider or model-upload occurs: local LSA plus the existing approved cookllm route.

Coverage/bias: English, three overlapping US institutional technical reports; limited prose/table extraction, static editions, guidance rather than implementation proof. Results cannot establish general RAG quality, model superiority, regulatory compliance or current worldwide requirements. Document deletion removes indexed/answer/queue copies; acquisition originals remain local excluded files until intentionally removed by the user. Restore originals is explicit and may revive a deliberately deleted public document. Imported text is private/local and cannot enter the bridge.
