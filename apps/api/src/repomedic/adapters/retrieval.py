"""Content-hash embedding cache and embedded Chroma retrieval."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Protocol, cast

import chromadb
import numpy as np
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, HttpUrl

from repomedic.domain.models import EvidenceItem, IssueSubmission, SourceKind


class CorpusChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_kind: SourceKind
    url: HttpUrl
    repository_sha: str
    text: str
    path: str | None = None
    issue_number: int | None = None


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS embeddings "
            "(content_hash TEXT PRIMARY KEY, model TEXT NOT NULL, vector_json TEXT NOT NULL)"
        )

    def get(self, content_hash: str, model: str) -> list[float] | None:
        row = self._connection.execute(
            "SELECT vector_json FROM embeddings WHERE content_hash = ? AND model = ?",
            (content_hash, model),
        ).fetchone()
        return None if row is None else cast(list[float], json.loads(row[0]))

    def put(self, content_hash: str, model: str, vector: list[float]) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO embeddings(content_hash, model, vector_json) VALUES (?, ?, ?)",
            (content_hash, model, json.dumps(vector)),
        )
        self._connection.commit()


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str, model: str, cache: EmbeddingCache) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._cache = cache

    async def embed(self, text: str) -> list[float]:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        cached = self._cache.get(content_hash, self._model)
        if cached is not None:
            return cached
        response = await self._client.embeddings.create(model=self._model, input=text)
        vector = response.data[0].embedding
        self._cache.put(content_hash, self._model, vector)
        return vector


class EmbeddingClient(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class ChromaRetriever:
    def __init__(self, path: Path, embeddings: EmbeddingClient) -> None:
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            "repomedic", metadata={"hnsw:space": "cosine"}
        )
        self._embeddings = embeddings

    async def index(self, chunks: tuple[CorpusChunk, ...]) -> int:
        expected_ids = {chunk.source_id for chunk in chunks}
        for chunk in chunks:
            vector = await self._embeddings.embed(chunk.text)
            metadata = {
                "source_kind": chunk.source_kind.value,
                "url": str(chunk.url),
                "repository_sha": chunk.repository_sha,
                "path": chunk.path or "",
                "issue_number": chunk.issue_number or 0,
            }
            self._collection.upsert(
                ids=[chunk.source_id],
                embeddings=np.asarray([vector], dtype=np.float32),
                documents=[chunk.text],
                metadatas=[metadata],
            )
        stale_ids = set(self.source_ids()) - expected_ids
        if stale_ids:
            self._collection.delete(ids=sorted(stale_ids))
        return len(chunks)

    def source_ids(self) -> tuple[str, ...]:
        return tuple(str(source_id) for source_id in self._collection.get(include=[])["ids"])

    async def retrieve(self, submission: IssueSubmission) -> tuple[EvidenceItem, ...]:
        return await self.retrieve_text(f"{submission.title}\n\n{submission.body}")

    async def retrieve_text(self, query: str, limit: int = 5) -> tuple[EvidenceItem, ...]:
        vector = await self._embeddings.embed(query)
        result = self._collection.query(
            query_embeddings=np.asarray([vector], dtype=np.float32),
            n_results=limit,
            include=["metadatas", "documents", "distances"],
        )
        ids = result["ids"][0]
        documents = result["documents"][0] if result["documents"] else []
        metadatas = result["metadatas"][0] if result["metadatas"] else []
        distances = result["distances"][0] if result["distances"] else []
        evidence: list[EvidenceItem] = []
        for source_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            raw_issue_number = metadata.get("issue_number")
            issue_number = (
                int(raw_issue_number)
                if isinstance(raw_issue_number, (str, int, float)) and raw_issue_number
                else None
            )
            evidence.append(
                EvidenceItem(
                    source_id=source_id,
                    source_kind=SourceKind(str(metadata["source_kind"])),
                    url=HttpUrl(str(metadata["url"])),
                    repository_sha=str(metadata["repository_sha"]),
                    path=str(metadata["path"]) or None,
                    issue_number=issue_number,
                    excerpt=document,
                    score=max(0.0, min(1.0, 1.0 - float(distance))),
                )
            )
        return tuple(evidence)


def read_chunks(path: Path) -> tuple[CorpusChunk, ...]:
    return tuple(
        CorpusChunk.model_validate_json(line) for line in path.read_text().splitlines() if line
    )


def write_chunks(path: Path, chunks: tuple[CorpusChunk, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(chunk.model_dump_json() for chunk in chunks) + "\n")
