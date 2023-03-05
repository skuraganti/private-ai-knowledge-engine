"""Local HTTP contract; the application never invokes or retries inference itself."""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.store import (
    InvalidInput,
    PrivateContext,
    QueueFull,
    Store,
    UnknownDocument,
    _read_json_file,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedRequest(StrictModel):
    pass


class ImportRequest(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=200000)
    document_id: str | None = Field(default=None, min_length=1, max_length=64)


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["lexical", "latent", "hybrid"] = "hybrid"
    limit: int = Field(default=5, ge=1, le=10, strict=True)
    document_ids: list[str] | None = Field(default=None, max_length=20)


class AnswerRequest(StrictModel):
    question: str = Field(min_length=1, max_length=500)
    document_ids: list[str] | None = Field(default=None, max_length=20)


def create_app(db_path=None, prepared_dir=None, bridge_dir=None) -> FastAPI:
    db = Path(db_path if db_path is not None else os.getenv("FOLIO_DB", "data/folio.sqlite"))
    prepared = Path(
        prepared_dir if prepared_dir is not None else os.getenv("FOLIO_PREPARED", "data/prepared")
    )
    bridge = Path(
        bridge_dir if bridge_dir is not None else os.getenv("FOLIO_BRIDGE", "data/bridge")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db, prepared, bridge)
        store.initialize()
        app.state.store = store
        yield

    app = FastAPI(title="Folio source workbench", lifespan=lifespan)
    from app.security import protect

    protect(app)

    def store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/health")
    def health(request: Request):
        try:
            with store(request)._connection() as connection:
                connection.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
        except Exception as exc:
            raise HTTPException(503, "Local index is unavailable") from exc
        return {"status": "ok"}

    @app.get("/api/state")
    def state(request: Request):
        return store(request).state()

    @app.post("/api/seed")
    def seed(request: Request, _: SeedRequest):
        try:
            return store(request).seed()
        except (ValueError, OSError) as exc:
            raise HTTPException(422, "Prepared corpus is unavailable or invalid") from exc

    @app.post("/api/documents")
    def import_document(request: Request, body: ImportRequest):
        try:
            return store(request).import_text(body.title, body.text, body.document_id)
        except UnknownDocument as exc:
            raise HTTPException(404, "Document not found") from exc
        except InvalidInput as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/documents/{document_id}")
    def delete_document(request: Request, document_id: str):
        try:
            return store(request).delete(document_id)
        except UnknownDocument as exc:
            raise HTTPException(404, "Document not found") from exc

    @app.get("/api/documents/{document_id}/chunks")
    def chunks(request: Request, document_id: str):
        try:
            return store(request).document_chunks(document_id)
        except UnknownDocument as exc:
            raise HTTPException(404, "Document not found") from exc

    @app.post("/api/search")
    def search(request: Request, body: SearchRequest):
        return store(request).search(body.query, body.mode, body.limit, body.document_ids)

    @app.post("/api/answers")
    def answer(request: Request, body: AnswerRequest):
        try:
            return store(request).queue_answer(body.question, body.document_ids)
        except PrivateContext as exc:
            raise HTTPException(422, str(exc)) from exc
        except QueueFull as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/answers/{answer_id}")
    def get_answer(request: Request, answer_id: uuid.UUID):
        try:
            return store(request).answer(str(answer_id))
        except UnknownDocument as exc:
            raise HTTPException(404, "Answer not found") from exc

    @app.get("/api/evaluation")
    def evaluation():
        try:
            data = _read_json_file(prepared / "evaluation.json", 256 * 1024)
            if not isinstance(data, dict):
                raise ValueError("invalid evaluation")
            return data
        except (OSError, ValueError, UnicodeError):
            return {"available": False}

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")

    @app.get("/")
    def root():
        index = static / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"status": "loading", "message": "Folio interface is not installed"}

    return app


app = create_app()
