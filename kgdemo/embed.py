"""Chunking, embeddings (fastembed, BAAI/bge-small-en-v1.5, 384-d) and the Neo4j vector index.

    python -m kgdemo.embed      # re-chunk and re-embed every Document in Neo4j

Documents are split into paragraph-aware chunks; each chunk becomes a Chunk node with its embedding,
linked to its Document by PART_OF. Retrieval uses the vector index `chunkEmbedding` (cosine).
"""
from __future__ import annotations

import re
import time
from functools import lru_cache

from neo4j.exceptions import Neo4jError

from . import config
from . import neo4j_client as db

VECTOR_INDEX = "chunkEmbedding"
INDEX_TIMEOUT_S = 300
DELETE_BATCH_SIZE = 5000

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# A gap between sentences (after . ! ? and an optional closing quote/bracket) or a line break.
_SENTENCE_GAP = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))[ \t]+|[ \t]*\n\s*")
_ABBREVIATIONS = {"dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "jr.", "sr.", "inc.", "co.", "corp.", "ltd.",
                  "no.", "vs.", "e.g.", "i.e.", "approx.", "u.s.", "u.k.", "jan.", "feb.", "mar.", "apr.",
                  "jun.", "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec."}


# =============================================================================
# chunking
# =============================================================================
def chunk_text(text: str, max_chars: int = 900, overlap_paragraphs: int = 1) -> list[str]:
    """Splits text into chunks of at most `max_chars` characters, never empty.

    Paragraphs (separated by blank lines) are packed greedily; each new chunk starts with the last
    `overlap_paragraphs` paragraphs of the previous chunk when they fit. A paragraph longer than
    `max_chars` is split at sentence and line boundaries (a single over-long sentence at word
    boundaries, an over-long word by characters).
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_paragraphs < 0:
        raise ValueError("overlap_paragraphs must not be negative")
    units: list[str] = []
    for paragraph in _paragraphs(text):
        units.extend([paragraph] if len(paragraph) <= max_chars else _split_paragraph(paragraph, max_chars))
    return _pack(units, max_chars, overlap_paragraphs)


def _paragraphs(text: str) -> list[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for block in _PARAGRAPH_BREAK.split(text):
        paragraph = "\n".join(line.rstrip() for line in block.strip().split("\n"))
        if paragraph:
            out.append(paragraph)
    return out


def _is_abbreviation(text: str, end: int) -> bool:
    """True when the token ending at `end` (just after its period) is an abbreviation or an initial."""
    token = text[:end].rsplit(None, 1)[-1].lstrip("(\"'[").lower()
    return token in _ABBREVIATIONS or bool(re.fullmatch(r"[a-z]\.", token))


def _sentence_spans(paragraph: str) -> list[tuple[int, int]]:
    """[start, end) spans of the sentences and lines of a paragraph."""
    spans, start = [], 0
    for gap in _SENTENCE_GAP.finditer(paragraph):
        if "\n" not in gap.group() and _is_abbreviation(paragraph, gap.start()):
            continue
        if gap.start() > start:
            spans.append((start, gap.start()))
        start = gap.end()
    if start < len(paragraph):
        spans.append((start, len(paragraph)))
    return spans


def _split_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Greedily packs whole sentences/lines (keeping the original separators) into pieces <= max_chars."""
    pieces: list[str] = []
    start = end = None
    for s, e in _sentence_spans(paragraph):
        if start is not None and e - start <= max_chars:
            end = e
            continue
        if start is not None:
            pieces.append(paragraph[start:end])
            start = end = None
        if e - s <= max_chars:
            start, end = s, e
        else:
            pieces.extend(_split_words(paragraph[s:e], max_chars))
    if start is not None:
        pieces.append(paragraph[start:end])
    return [p.strip() for p in pieces if p.strip()]


def _split_words(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_chars:
            if current:
                out.append(current)
                current = ""
            out.append(word[:max_chars])
            word = word[max_chars:]
        if not word:
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out


def _joined_len(units: list[str]) -> int:
    return sum(len(u) for u in units) + 2 * (len(units) - 1)


def _pack(units: list[str], max_chars: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and _joined_len(current + [unit]) > max_chars:
            chunks.append("\n\n".join(current))
            carry = current[-overlap:] if overlap else []
            while carry and _joined_len(carry + [unit]) > max_chars:
                carry = carry[1:]
            current = carry + [unit]
        else:
            current.append(unit)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


# =============================================================================
# embeddings
# =============================================================================
@lru_cache(maxsize=1)
def get_model():
    """The fastembed model, loaded once from the local cache (.cache/fastembed)."""
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=str(config.EMBED_CACHE_DIR))


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embeds passages (documents, chunks, sentences); one normalized 384-d vector per text."""
    texts = list(texts)
    if not texts:
        return []
    return [vector.tolist() for vector in get_model().passage_embed(texts)]


def embed_query(text: str) -> list[float]:
    """Embeds a search query (fastembed's query_embed)."""
    return next(iter(get_model().query_embed(text))).tolist()


def _embedding_input(title: str | None, chunk: str) -> str:
    """What gets embedded for a chunk: the passage, prefixed with its document title for context."""
    title = (title or "").strip()
    return chunk if not title or chunk.startswith(title) else f"{title}\n\n{chunk}"


# =============================================================================
# Neo4j: chunks + vector index + search
# =============================================================================
def build_chunks(batch_size: int = 64) -> int:
    """Replaces all Chunk nodes: chunks every Document, embeds the chunks, creates the vector index if needed.

    Everything is embedded before the old chunks are deleted, so an embedding failure leaves them intact.
    Chunk ids are '<DOC-ID>#<seq>' with seq counted from 00. Returns the number of chunks.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    docs = db.run("MATCH (d:Document) RETURN d.id AS id, d.title AS title, d.text AS text ORDER BY d.id")
    rows = [{"id": f"{d['id']}#{seq:02d}", "doc_id": d["id"], "seq": seq, "text": chunk, "title": d["title"]}
            for d in docs for seq, chunk in enumerate(chunk_text(d["text"] or ""))]
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        vectors = embed_passages([_embedding_input(r.pop("title"), r["text"]) for r in batch])
        if any(len(v) != config.EMBED_DIM for v in vectors):
            raise ValueError(f"{config.EMBED_MODEL} returned vectors that are not {config.EMBED_DIM}-dimensional")
        for row, vector in zip(batch, vectors):
            row["embedding"] = vector
    _delete_chunks()
    query = ("UNWIND $rows AS row\n"
             "MATCH (d:Document {id: row.doc_id})\n"
             "CREATE (c:Chunk {id: row.id, doc_id: row.doc_id, seq: row.seq, text: row.text, "
             "embedding: row.embedding})\n"
             "CREATE (c)-[:PART_OF {origin: 'structured'}]->(d)\n"
             "RETURN count(*) AS n")
    for i in range(0, len(rows), batch_size):
        written = db.write(query, {"rows": rows[i:i + batch_size]})[0]["n"]
        if written != len(rows[i:i + batch_size]):
            raise RuntimeError("a Document was deleted while its chunks were being written; run build_chunks again")
    ensure_vector_index()
    return len(rows)


def _delete_chunks() -> None:
    while db.write("MATCH (c:Chunk) WITH c LIMIT $limit DETACH DELETE c RETURN count(*) AS n",
                   {"limit": DELETE_BATCH_SIZE})[0]["n"]:
        pass


def ensure_vector_index() -> None:
    """Creates the vector index on Chunk.embedding (384 dimensions, cosine) if needed and waits until it is online."""
    db.write(f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
             f"OPTIONS {{indexConfig: {{`vector.dimensions`: {int(config.EMBED_DIM)}, "
             "`vector.similarity_function`: 'cosine'}}")
    db.write("CALL db.awaitIndex($name, $timeout)", {"name": VECTOR_INDEX, "timeout": INDEX_TIMEOUT_S})


def vector_search(question: str, k: int = 6) -> list[dict]:
    """Top-k chunks for a question: chunk_id, text, score, doc_id, title, doc_type, date (ISO), source_system."""
    if k < 1:
        raise ValueError("k must be positive")
    query = ("CALL db.index.vector.queryNodes($index, $k, $vector) YIELD node, score\n"
             "OPTIONAL MATCH (node)-[:PART_OF]->(d:Document)\n"
             "RETURN node.id AS chunk_id, node.text AS text, score, coalesce(d.id, node.doc_id) AS doc_id,\n"
             "       d.title AS title, d.doc_type AS doc_type, d.date AS date, d.source_system AS source_system\n"
             "ORDER BY score DESC")
    try:
        return db.run(query, {"index": VECTOR_INDEX, "k": k, "vector": embed_query(question)})
    except Neo4jError as exc:
        if not db.run("SHOW VECTOR INDEXES YIELD name WHERE name = $name RETURN name", {"name": VECTOR_INDEX}):
            raise RuntimeError(f"the vector index '{VECTOR_INDEX}' does not exist; build it with "
                               "python -m kgdemo.embed (or python -m kgdemo.build without --skip-embed)") from exc
        raise


if __name__ == "__main__":
    t0 = time.perf_counter()
    count = build_chunks()
    print(f"{count} chunks embedded with {config.EMBED_MODEL} and indexed as '{VECTOR_INDEX}' "
          f"in {time.perf_counter() - t0:.1f}s")
