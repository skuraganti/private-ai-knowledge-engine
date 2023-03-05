"""Transactional local corpus, retrieval snapshots and a bounded disk answer queue."""

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.retrieval import LatentIndex, fuse, query_terms

DOCUMENT_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
MAX_CHUNKS = 1000


class UnknownDocument(Exception):
    pass


class InvalidInput(Exception):
    pass


class PrivateContext(Exception):
    pass


class QueueFull(Exception):
    pass


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _unique_pairs(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_json_file(path: Path, limit: int) -> object:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("file too large")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
        )
    finally:
        os.close(fd)


def _schema(value: object, required: set[str], optional: set[str] = frozenset()) -> dict:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - optional
    ):
        raise ValueError("invalid response fields")
    return value


def _text(value: object, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high or not value.strip():
        raise ValueError("invalid text")
    return value


def _chunks(pages: list[dict]) -> list[tuple[int, str]]:
    result = []
    for page in pages:
        text = page["text"].strip()
        start = 0
        while start < len(text):
            end = min(start + 1600, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + 1200, end)
                if boundary > start:
                    end = boundary + 1
            part = text[start:end].strip()
            if part:
                result.append((page["page"], part))
            if end == len(text):
                break
            start = max(start + 1, end - 200)
    return result


class Store:
    def __init__(self, db_path: Path, prepared_dir: Path, bridge_dir: Path):
        self.db_path = Path(db_path)
        self.prepared_dir = Path(prepared_dir)
        self.bridge_dir = Path(bridge_dir)
        self.lock = threading.RLock()
        self._index_revision = -1
        self._index = None

    @contextmanager
    def _connection(self, write: bool = False):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
                for row in connection.execute("SELECT id FROM answers WHERE state!='queued'"):
                    self._remove_artifacts(row["id"])
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.bridge_dir.mkdir(parents=True, exist_ok=True)
            if self.bridge_dir.is_symlink():
                raise ValueError("bridge directory cannot be a symlink")
            with self._connection() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                    INSERT OR IGNORE INTO meta VALUES ('revision', 0);
                    INSERT OR IGNORE INTO meta VALUES ('attempts', 0);
                    INSERT OR IGNORE INTO meta VALUES ('initialized', 0);
                    CREATE TABLE IF NOT EXISTS versions (
                        id TEXT PRIMARY KEY, version INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS identities (
                        id TEXT PRIMARY KEY, identity TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS documents (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL, sha256 TEXT NOT NULL,
                        version INTEGER NOT NULL, pages INTEGER NOT NULL, source_url TEXT NOT NULL,
                        publication TEXT NOT NULL, remote_allowed INTEGER NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS chunks (
                        id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                        version INTEGER NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
                        sha256 TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                    USING fts5(chunk_id UNINDEXED, text);
                    CREATE TABLE IF NOT EXISTS answers (
                        id TEXT PRIMARY KEY, state TEXT NOT NULL, question TEXT NOT NULL,
                        revision INTEGER NOT NULL, created_at REAL NOT NULL,
                        completed_at REAL, claims TEXT NOT NULL, reason TEXT,
                        citations TEXT NOT NULL, model TEXT, usage TEXT, latency_ms REAL,
                        contexts TEXT NOT NULL
                    );
                """)
            # Seed is a one-time initialization decision, even if the manifest is absent.
            with self._connection(write=True) as db:
                first = not self._meta(db, "initialized")
                for queued in db.execute("SELECT id FROM answers WHERE state='queued'").fetchall():
                    request = self.bridge_dir / f"{queued['id']}.request.json"
                    response = self.bridge_dir / f"{queued['id']}.response.json"
                    if not request.exists() and not response.exists():
                        db.execute(
                            "UPDATE answers SET state='failed',reason=?,completed_at=?,"
                            "contexts='[]' "
                            "WHERE id=? AND state='queued'",
                            (
                                "Interrupted request publication; no automatic retry",
                                time.time(),
                                queued["id"],
                            ),
                        )
                if first:
                    if (self.prepared_dir / "manifest.json").exists():
                        self._seed_into(db, self._manifest())
                    self._set_meta(db, "initialized", 1)

    @staticmethod
    def _meta(db, key):
        return db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]

    @staticmethod
    def _set_meta(db, key, value):
        db.execute("UPDATE meta SET value=? WHERE key=?", (value, key))

    def _manifest(self):
        data = _read_json_file(self.prepared_dir / "manifest.json", 12 * 1024 * 1024)
        if not isinstance(data, list) or len(data) > 20:
            raise InvalidInput("invalid prepared manifest")
        seen = set()
        for doc in data:
            if not isinstance(doc, dict) or set(doc) not in (
                {
                    "id",
                    "title",
                    "url",
                    "pdf_name",
                    "sha256",
                    "publication",
                    "remote_allowed",
                    "pages",
                },
                {
                    "id",
                    "title",
                    "url",
                    "pdf_name",
                    "sha256",
                    "publication",
                    "remote_allowed",
                    "pages",
                    "doi",
                },
            ):
                raise InvalidInput("invalid prepared document")
            if (
                not isinstance(doc["id"], str)
                or not DOCUMENT_ID.fullmatch(doc["id"])
                or doc["id"] in seen
            ):
                raise InvalidInput("invalid or duplicate prepared id")
            seen.add(doc["id"])
            if not isinstance(doc["title"], str) or not 1 <= len(doc["title"].strip()) <= 120:
                raise InvalidInput("invalid prepared title")
            if not isinstance(doc["url"], str) or not re.fullmatch(
                r"https://[^\s<>'\"]{1,500}", doc["url"]
            ):
                raise InvalidInput("invalid prepared source URL")
            if (
                not isinstance(doc["pdf_name"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.pdf", doc["pdf_name"])
                or ".." in doc["pdf_name"]
            ):
                raise InvalidInput("invalid prepared PDF name")
            if not isinstance(doc["sha256"], str) or not SHA256.fullmatch(doc["sha256"]):
                raise InvalidInput("invalid prepared hash")
            if not isinstance(doc["publication"], str) or len(doc["publication"]) > 120:
                raise InvalidInput("invalid prepared publication")
            if doc["remote_allowed"] is not True:
                raise InvalidInput("prepared source must explicitly allow remote snippets")
            pages = doc["pages"]
            if not isinstance(pages, list) or len(pages) > 500:
                raise InvalidInput("invalid prepared pages")
            page_numbers = set()
            for page in pages:
                if (
                    not isinstance(page, dict)
                    or set(page) != {"page", "text"}
                    or type(page["page"]) is not int
                    or not 1 <= page["page"] <= 5000
                    or page["page"] in page_numbers
                    or not isinstance(page["text"], str)
                    or len(page["text"]) > 200000
                ):
                    raise InvalidInput("invalid prepared page")
                page_numbers.add(page["page"])
        return data

    def _invalidate(self, db):
        self._set_meta(db, "revision", self._meta(db, "revision") + 1)
        db.execute(
            """UPDATE answers SET state='cancelled', question='', claims='[]',
                   citations='[]', contexts='[]', reason='Corpus changed; answer invalidated',
                   model=NULL, usage=NULL, latency_ms=NULL, completed_at=?""",
            (time.time(),),
        )
        self._index_revision = -1
        self._index = None

    def _put(
        self,
        db,
        document_id: str,
        title: str,
        pages: list[dict],
        digest: str,
        url: str = "",
        publication: str = "",
        remote_allowed: bool = False,
    ):
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        # Page text is part of the identity: a corrected extraction changes the indexed version
        # even when the original PDF bytes/hash remain identical.
        content_hash = _hash(_json(pages))
        identity = _hash(_json([title, digest, content_hash, url, publication, remote_allowed]))
        old_identity = db.execute(
            "SELECT identity FROM identities WHERE id=?", (document_id,)
        ).fetchone()
        if row and old_identity and old_identity[0] == identity:
            return "unchanged"
        parts = _chunks(pages)
        remaining = db.execute(
            "SELECT count(*) FROM chunks WHERE document_id!=?", (document_id,)
        ).fetchone()[0]
        if remaining + len(parts) > MAX_CHUNKS:
            raise InvalidInput("corpus exceeds 1000 chunks")
        version_row = db.execute(
            "SELECT version FROM versions WHERE id=?", (document_id,)
        ).fetchone()
        version = version_row[0] + 1 if version_row else 1
        self._invalidate(db)
        old_ids = [
            r[0] for r in db.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,))
        ]
        for chunk_id in old_ids:
            db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (chunk_id,))
        db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        db.execute(
            """INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title, sha256=excluded.sha256,
                    version=excluded.version, pages=excluded.pages, source_url=excluded.source_url,
                    publication=excluded.publication, remote_allowed=excluded.remote_allowed,
                    updated_at=excluded.updated_at""",
            (
                document_id,
                title,
                digest,
                version,
                len(pages),
                url,
                publication,
                int(remote_allowed),
                time.time(),
            ),
        )
        db.execute(
            "INSERT INTO versions VALUES (?,?) "
            "ON CONFLICT(id) DO UPDATE SET version=excluded.version",
            (document_id, version),
        )
        db.execute(
            "INSERT INTO identities VALUES (?,?) "
            "ON CONFLICT(id) DO UPDATE SET identity=excluded.identity",
            (document_id, identity),
        )
        for position, (page, text) in enumerate(parts):
            chunk_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"folio:{document_id}:{version}:{page}:{position}")
            )
            db.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                (chunk_id, document_id, version, page, text, _hash(text)),
            )
            db.execute("INSERT INTO chunks_fts VALUES (?,?)", (chunk_id, text))
        return "updated" if row else "added"

    def _seed_into(self, db, manifest):
        result = {"added": 0, "updated": 0, "unchanged": 0}
        for doc in manifest:
            state = self._put(
                db,
                doc["id"],
                doc["title"].strip(),
                doc["pages"],
                doc["sha256"],
                doc["url"],
                doc["publication"],
                True,
            )
            result[state] += 1
        result["revision"] = self._meta(db, "revision")
        return result

    def seed(self):
        with self.lock:
            manifest = self._manifest()
            with self._connection(write=True) as db:
                result = self._seed_into(db, manifest)
                self._set_meta(db, "initialized", 1)
                return result

    @staticmethod
    def _document(row, chunks):
        return {
            "id": row["id"],
            "title": row["title"],
            "sha256": row["sha256"],
            "version": row["version"],
            "pages": row["pages"],
            "chunks": chunks,
            "source_url": row["source_url"],
            "publication": row["publication"],
            "remote_allowed": bool(row["remote_allowed"]),
            "updated_at": row["updated_at"],
        }

    def _get_document(self, db, document_id):
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise UnknownDocument(document_id)
        count = db.execute(
            "SELECT count(*) FROM chunks WHERE document_id=?", (document_id,)
        ).fetchone()[0]
        return self._document(row, count)

    def import_text(self, title: str, text: str, document_id: str | None = None):
        if not title.strip() or not text.strip():
            raise InvalidInput("title and text cannot be blank")
        if document_id is not None and not DOCUMENT_ID.fullmatch(document_id):
            raise InvalidInput("invalid document id")
        with self.lock, self._connection(write=True) as db:
            if document_id is not None:
                self._get_document(db, document_id)
            else:
                document_id = str(uuid.uuid4())
            self._put(db, document_id, title.strip(), [{"page": 1, "text": text}], _hash(text))
            return self._get_document(db, document_id)

    def delete(self, document_id):
        with self.lock, self._connection(write=True) as db:
            self._get_document(db, document_id)
            self._invalidate(db)
            ids = [
                r[0]
                for r in db.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,))
            ]
            for chunk_id in ids:
                db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (chunk_id,))
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.execute("DELETE FROM identities WHERE id=?", (document_id,))
            return {"deleted": document_id, "revision": self._meta(db, "revision")}

    def document_chunks(self, document_id):
        with self.lock, self._connection() as db:
            doc = self._get_document(db, document_id)
            chunks = [
                dict(row)
                for row in db.execute(
                    """SELECT id,document_id,version,page,text,sha256
                         FROM chunks WHERE document_id=? ORDER BY page,id""",
                    (document_id,),
                )
            ]
            return {"document": doc, "chunks": chunks}

    def _search(self, db, query, mode, limit, document_ids):
        revision = self._meta(db, "revision")
        terms = query_terms(query)
        if not terms:
            return revision, []
        rows = db.execute("""SELECT c.*,d.title,d.source_url,d.remote_allowed FROM chunks c
                             JOIN documents d ON d.id=c.document_id ORDER BY c.id""").fetchall()
        if not rows:
            return revision, []
        chunks = {row["id"]: row for row in rows}
        allowed = set(document_ids) if document_ids is not None else None
        lexical = []
        if mode != "latent":
            # Quoting each tokenizer-derived term prevents MATCH operators and syntax injection.
            match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            conditions = ""
            parameters = [match]
            if allowed is not None:
                if not allowed:
                    return revision, []
                conditions = " AND c.document_id IN (" + ",".join("?" for _ in allowed) + ")"
                parameters.extend(sorted(allowed))
            lexical = [
                (row["chunk_id"], float(row["rank"]))
                for row in db.execute(
                    "SELECT chunk_id, bm25(chunks_fts) AS rank FROM chunks_fts "
                    "JOIN chunks c ON c.id=chunks_fts.chunk_id WHERE chunks_fts MATCH ?"
                    + conditions
                    + " ORDER BY rank,chunk_id LIMIT 100",
                    parameters,
                )
                if row["chunk_id"] in chunks
                and (allowed is None or chunks[row["chunk_id"]]["document_id"] in allowed)
            ]
        latent = []
        if mode != "lexical":
            if self._index_revision != revision:
                self._index = LatentIndex([dict(row) for row in rows])
                self._index_revision = revision
            latent = self._index.ranks(
                query, allowed, {id_: row["document_id"] for id_, row in chunks.items()}
            )
        if mode == "hybrid":
            ranked = fuse(lexical, latent)
        else:
            source = lexical if mode == "lexical" else latent
            rank_key = "lexical_rank" if mode == "lexical" else "latent_rank"
            ranked = [
                {"chunk_id": id_, "score": score, rank_key: rank}
                for rank, (id_, score) in enumerate(source, 1)
            ]
        hits = []
        for hit in ranked[:limit]:
            row = chunks[hit["chunk_id"]]
            hits.append(
                {
                    "chunk_id": row["id"],
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "version": row["version"],
                    "page": row["page"],
                    "text": row["text"],
                    "source_url": row["source_url"],
                    "sha256": row["sha256"],
                    "score": hit["score"],
                    "remote_allowed": bool(row["remote_allowed"]),
                    **{key: hit[key] for key in ("lexical_rank", "latent_rank") if key in hit},
                }
            )
        return revision, hits

    def search(self, query, mode="hybrid", limit=5, document_ids=None):
        start = time.perf_counter()
        with self.lock, self._connection() as db:
            revision, hits = self._search(db, query, mode, limit, document_ids)
        return {
            "query": query,
            "mode": mode,
            "revision": revision,
            "took_ms": round((time.perf_counter() - start) * 1000, 3),
            "hits": hits,
        }

    def _remove_artifacts(self, answer_id):
        for suffix in ("request", "response"):
            (self.bridge_dir / f"{answer_id}.{suffix}.json").unlink(missing_ok=True)

    @staticmethod
    def _answer(row):
        result = {
            "id": row["id"],
            "state": row["state"],
            "question": row["question"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "claims": json.loads(row["claims"]),
            "citations": json.loads(row["citations"]),
        }
        for key in ("completed_at", "reason", "model", "latency_ms"):
            if row[key] is not None:
                result[key] = row[key]
        if row["usage"] is not None:
            result["usage"] = json.loads(row["usage"])
        return result

    def _answer_by_id(self, db, answer_id):
        row = db.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
        if row is None:
            raise UnknownDocument("unknown answer")
        return self._answer(row)

    def _write_request(self, answer_id, request):
        target = self.bridge_dir / f"{answer_id}.request.json"
        temporary = self.bridge_dir / f"{answer_id}.tmp"
        data = _json(request).encode("utf-8")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def queue_answer(self, question, document_ids=None):
        with self.lock, self._connection(write=True) as db:
            revision, hits = self._search(db, question, "hybrid", 5, document_ids)
            if any(not hit["remote_allowed"] for hit in hits):
                raise PrivateContext("Retrieved private text cannot be sent to remote inference")
            if hits and self._meta(db, "attempts") >= 10:
                raise QueueFull("Ten lifetime model attempts exhausted")
            pending = db.execute("SELECT count(*) FROM answers WHERE state='queued'").fetchone()[0]
            if hits and pending >= 3:
                raise QueueFull("Three model requests already pending")
            answer_id = str(uuid.uuid4())
            created = time.time()
            contexts = [
                {
                    key: hit[key]
                    for key in (
                        "chunk_id",
                        "document_id",
                        "version",
                        "page",
                        "title",
                        "source_url",
                        "sha256",
                    )
                }
                | {"text": hit["text"][:1200]}
                for hit in hits
            ]
            state = "queued" if contexts else "abstained"
            reason = None if contexts else "No relevant indexed source found"
            db.execute(
                """INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    answer_id,
                    state,
                    question,
                    revision,
                    created,
                    None if contexts else created,
                    "[]",
                    reason,
                    "[]",
                    None,
                    None,
                    None,
                    _json(contexts),
                ),
            )
            if contexts:
                self._set_meta(db, "attempts", self._meta(db, "attempts") + 1)
            result = self._answer_by_id(db, answer_id)
        if contexts:
            # The attempt is committed before publication. If disk publication fails, fail it
            # visibly, without silently refunding or automatically retrying the model request.
            try:
                with self.lock:
                    with self._connection(write=True) as db:
                        if self._meta(db, "revision") != revision:
                            return self._answer_by_id(db, answer_id)
                        self._write_request(
                            answer_id,
                            {
                                "id": answer_id,
                                "revision": revision,
                                "question": question,
                                "contexts": contexts,
                            },
                        )
            except OSError:
                with self.lock, self._connection(write=True) as db:
                    db.execute(
                        """UPDATE answers SET state='failed', reason='Request publication failed',
                                  completed_at=?,contexts='[]' WHERE id=? AND state='queued'""",
                        (time.time(), answer_id),
                    )
                    result = self._answer_by_id(db, answer_id)
        return result

    def _validated_result(self, db, row, data):
        _schema(
            data, {"id", "revision", "state", "model", "latency_ms"}, {"output", "usage", "error"}
        )
        if (
            data["id"] != row["id"]
            or type(data["revision"]) is not int
            or data["revision"] != row["revision"]
            or data["model"] != "cookllm"
            or data["state"] not in ("succeeded", "failed")
        ):
            raise ValueError("response identity, revision, model or state invalid")
        latency = data["latency_ms"]
        if (
            type(latency) not in (float, int)
            or not 0 <= latency <= 1e9
            or not math.isfinite(latency)
        ):
            raise ValueError("invalid latency")
        usage = data.get("usage")
        if usage is not None:
            if (
                not isinstance(usage, dict)
                or len(usage) > 16
                or any(
                    not isinstance(k, str)
                    or len(k) > 64
                    or type(v) not in (int, float)
                    or not 0 <= v <= 1e9
                    or not math.isfinite(v)
                    for k, v in usage.items()
                )
            ):
                raise ValueError("invalid usage")
        if data["state"] == "failed":
            if "output" in data:
                raise ValueError("failed response must not contain output")
            return "failed", [], [], _text(data.get("error"), 1, 500), usage, float(latency)
        if "error" in data:
            raise ValueError("successful response must not contain error")
        output = _schema(data.get("output"), {"abstain", "reason", "claims"})
        if (
            type(output["abstain"]) is not bool
            or not isinstance(output["reason"], str)
            or len(output["reason"]) > 500
        ):
            raise ValueError("invalid abstention")
        claims = output["claims"]
        if not isinstance(claims, list) or len(claims) > 5:
            raise ValueError("invalid claims")
        if output["abstain"]:
            if claims:
                raise ValueError("abstention cannot contain claims")
            return "abstained", [], [], _text(output["reason"], 1, 500), usage, float(latency)
        if not claims:
            raise ValueError("empty non-abstaining answer")
        contexts = {item["chunk_id"]: item for item in json.loads(row["contexts"])}
        citations = []
        for claim in claims:
            _schema(claim, {"text", "supports"})
            _text(claim["text"], 1, 600)
            supports = claim["supports"]
            if not isinstance(supports, list) or not 1 <= len(supports) <= 3:
                raise ValueError("claim missing bounded supports")
            for support in supports:
                _schema(support, {"chunk_id", "quote"})
                if not isinstance(support["chunk_id"], str) or support["chunk_id"] not in contexts:
                    raise ValueError("unknown citation")
                quote = _text(support["quote"], 20, 400)
                source = contexts[support["chunk_id"]]
                live = db.execute(
                    "SELECT version,text,sha256 FROM chunks WHERE id=? AND document_id=?",
                    (source["chunk_id"], source["document_id"]),
                ).fetchone()
                if (
                    live is None
                    or live["version"] != source["version"]
                    or live["sha256"] != source["sha256"]
                    or quote not in source["text"]
                    or quote not in live["text"]
                ):
                    raise ValueError("unsupported quote or changed citation")
                citation = {
                    key: source[key]
                    for key in (
                        "chunk_id",
                        "document_id",
                        "version",
                        "page",
                        "title",
                        "source_url",
                        "sha256",
                    )
                }
                citation["quote"] = quote
                if citation not in citations:
                    citations.append(citation)
        return "succeeded", claims, citations, None, usage, float(latency)

    def consume_results(self):
        with self.lock, self._connection(write=True) as db:
            rows = db.execute("SELECT * FROM answers WHERE state='queued'").fetchall()
            for row in rows:
                answer_id = row["id"]
                path = self.bridge_dir / f"{answer_id}.response.json"
                if time.time() - row["created_at"] > 360:
                    db.execute(
                        "UPDATE answers SET state='failed',reason=?,completed_at=?,"
                        "contexts='[]' WHERE id=?",
                        (
                            "Model request expired after 360 seconds; no automatic retry",
                            time.time(),
                            answer_id,
                        ),
                    )
                    continue
                if not path.exists() and not path.is_symlink():
                    continue
                try:
                    data = _read_json_file(path, 64 * 1024)
                    if self._meta(db, "revision") != row["revision"]:
                        raise ValueError("stale corpus revision")
                    state, claims, citations, reason, usage, latency = self._validated_result(
                        db, row, data
                    )
                except (OSError, ValueError, TypeError, UnicodeError):
                    state, claims, citations, reason, usage, latency = (
                        "failed",
                        [],
                        [],
                        "Invalid or stale model response",
                        None,
                        None,
                    )
                db.execute(
                    """UPDATE answers SET state=?,claims=?,citations=?,reason=?,
                              model=?,usage=?,latency_ms=?,completed_at=?,contexts='[]'
                              WHERE id=? AND state='queued'""",
                    (
                        state,
                        _json(claims),
                        _json(citations),
                        reason,
                        "cookllm" if latency is not None else None,
                        _json(usage) if usage is not None else None,
                        latency,
                        time.time(),
                        answer_id,
                    ),
                )

    def answer(self, answer_id):
        with self.lock:
            self.consume_results()
            with self._connection() as db:
                return self._answer_by_id(db, answer_id)

    def state(self):
        with self.lock:
            self.consume_results()
            with self._connection() as db:
                docs = [
                    self._document(
                        row,
                        db.execute(
                            "SELECT count(*) FROM chunks WHERE document_id=?", (row["id"],)
                        ).fetchone()[0],
                    )
                    for row in db.execute("SELECT * FROM documents ORDER BY id")
                ]
                answers = [
                    self._answer(row)
                    for row in db.execute(
                        "SELECT * FROM answers ORDER BY created_at DESC,id DESC LIMIT 20"
                    )
                ]
                return {
                    "revision": self._meta(db, "revision"),
                    "documents": docs,
                    "counts": {
                        "documents": len(docs),
                        "chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0],
                    },
                    "bridge": self.heartbeat(),
                    "model_budget": {
                        "attempted": self._meta(db, "attempts"),
                        "limit": 10,
                        "pending": db.execute(
                            "SELECT count(*) FROM answers WHERE state='queued'"
                        ).fetchone()[0],
                    },
                    "answers": answers,
                }

    def heartbeat(self):
        try:
            beat = _schema(
                _read_json_file(self.bridge_dir / "heartbeat.json", 4096),
                {"at", "model", "status", "calls"},
            )
            timestamp = beat["at"]
            if (
                type(timestamp) not in (int, float)
                or not 0 <= timestamp <= time.time() + 5
                or not math.isfinite(timestamp)
                or beat["model"] != "cookllm"
                or beat["status"] not in ("ready", "busy", "stopped")
                or type(beat["calls"]) is not int
                or beat["calls"] < 0
            ):
                raise ValueError("invalid heartbeat")
            return {
                "heartbeat_at": float(timestamp),
                "online": beat["status"] in ("ready", "busy") and time.time() - timestamp < 30,
            }
        except (OSError, ValueError, UnicodeError):
            return {"heartbeat_at": None, "online": False}
