# Public demonstration data

Curated input for the browser demonstration.

402 exact page passages from three original NIST PDFs, with document/source hashes, physical pages and PDF links. Page text normalization follows the preparation script; excerpts remain attributable to the publisher. Browser search is lexical and answers are extractive quotes. Full-app recorded hybrid metrics are separate from browser functionality. Republished courtesy of the National Institute of Standards and Technology. Third-party content can retain separate rights; no NIST endorsement is implied.

Fixture: `docs/demo-data.json` · SHA-256 `cc02751070c4edb330ef14371da6980a6b9a46d452abc45d6d5dc71f5c790469` · 572,219 bytes.

Declared mode: Original NIST text; browser lexical retrieval and extractive quotations, no new model inference

Top-level schema fields: `title`, `data_kind`, `documents`, `passages`, `retrieval_metrics`, `question_examples`, `limit`, `repository`

Original publisher URLs, revisions, retrieval methods, rights and caveats are in [DATA_SOURCES.md](DATA_SOURCES.md). Browser behavior is described in [docs/DEMO.md](docs/DEMO.md). Data and application dependencies are credited separately in [UPSTREAM.md](UPSTREAM.md).
