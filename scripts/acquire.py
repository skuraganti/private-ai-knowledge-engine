"""Acquire fixed original NIST PDFs; never execute content or arbitrary archive scripts."""

import argparse
import asyncio
import datetime as dt
import hashlib
import io
import json
import os
import re
from pathlib import Path

import httpx
from pypdf import PdfReader

SOURCES = [
    {
        "id": "ai-rmf",
        "title": "AI Risk Management Framework (AI RMF 1.0)",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        "publication": "January 2023",
        "doi": "10.6028/NIST.AI.100-1",
    },
    {
        "id": "genai-profile",
        "title": "Generative Artificial Intelligence Profile",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
        "publication": "July 2024",
        "doi": "10.6028/NIST.AI.600-1",
    },
    {
        "id": "ssdf",
        "title": "Secure Software Development Framework (SSDF) 1.1",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf",
        "publication": "February 2022",
        "doi": "10.6028/NIST.SP.800-218",
    },
]


async def fetch(client, url):
    async with asyncio.timeout(25):
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            if (
                response.status_code != 200
                or response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise ValueError("Expected identity-encoded HTTP200")
            body = bytearray()
            async for chunk in response.aiter_raw():
                body.extend(chunk)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError("PDF exceeds4MiB acquisition bound")
            if not body.startswith(b"%PDF-"):
                raise ValueError("Original did not return a PDF")
            return bytes(body), {
                k: response.headers.get(k) for k in ("etag", "last-modified", "content-type")
            }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    target = Path(args.output_dir)
    raw = target / "raw"
    prepared = target / "prepared"
    if (raw / "manifest.json").exists() and not args.replace:
        raise SystemExit(
            "Preserve existing snapshot; choose a new output-dir or explicitly --replace"
        )
    captures = []
    documents = []
    bodies = []
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=10,
        headers={"User-Agent": "FolioLocalResearch/1.0", "Accept-Encoding": "identity"},
    ) as client:
        for source in SOURCES:
            body, headers = await fetch(client, source["url"])
            reader = PdfReader(io.BytesIO(body), strict=True)
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError("Encrypted/oversize PDF not allowed")
            pages = []
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                # Preserve prose/page structure; normalize soft hyphens and spacing only.
                text = text.replace("\u00ad", "").replace("\u0000", "")
                text = re.sub(r"[ \t]+", " ", text).strip()
                if len(text) > 50000:
                    raise ValueError("Page text exceeds bound")
                pages.append({"page": number, "text": text})
            if sum(len(p["text"]) for p in pages) < 20000:
                raise ValueError("Unexpectedly sparse PDF; inspect source")
            record = {
                **source,
                "name": source["id"] + ".pdf",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "headers": headers,
                "pages": len(pages),
                "text_characters": sum(len(p["text"]) for p in pages),
                "license": (
                    "NIST Technical Series public-use policy; third-party components retain rights"
                ),
            }
            captures.append(record)
            bodies.append((record["name"], body))
            documents.append(
                {
                    **source,
                    "pdf_name": record["name"],
                    "sha256": record["sha256"],
                    "remote_allowed": True,
                    "pages": pages,
                }
            )
            print(
                json.dumps(
                    {k: record[k] for k in ("id", "bytes", "sha256", "pages", "text_characters")}
                )
            )
    raw.mkdir(parents=True, exist_ok=True)
    prepared.mkdir(parents=True, exist_ok=True)
    for name, body in bodies:
        path = raw / name
        temporary = path.with_suffix(".part")
        temporary.write_bytes(body)
        os.replace(temporary, path)
    (raw / "manifest.json").write_text(json.dumps(captures, indent=2))
    (prepared / "manifest.json").write_text(json.dumps(documents, ensure_ascii=False, indent=2))
    (prepared / "preparation.json").write_text(
        json.dumps(
            {
                "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "extractor": "pypdf",
                "version": __import__("pypdf").__version__,
                "transforms": ["soft-hyphen/NUL removal", "horizontal whitespace normalization"],
                "page_numbers": "1-based physical PDF pages, not printed pages",
                "documents": [
                    {k: r[k] for k in ("id", "sha256", "pages", "text_characters")}
                    for r in captures
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
