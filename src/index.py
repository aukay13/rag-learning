import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

from chunk import chunk_file
from embed_test import embed_documents_batch

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "gcal-mcp-notes.md"
BATCH_SIZE = 10
EMBED_DIM = 768


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _run() -> None:
    chunks = chunk_file(DOC_PATH)
    print(f"Chunked {len(chunks)} pieces from {DOC_PATH.name}")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            metadata JSONB,
            embedding VECTOR({EMBED_DIM})
        )
        """
    )
    cur.execute("TRUNCATE TABLE chunks")

    total = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        embeddings = embed_documents_batch([c["content"] for c in batch])

        for chunk, embedding in zip(batch, embeddings):
            cur.execute(
                "INSERT INTO chunks (content, metadata, embedding) VALUES (%s, %s, %s::vector)",
                (chunk["content"], json.dumps(chunk["metadata"]), _vector_literal(embedding)),
            )

        total += len(batch)
        print(f"  Batch {i // BATCH_SIZE + 1}: inserted {len(batch)} chunks ({total}/{len(chunks)} total)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. Inserted {total} chunks into 'chunks' table.")


if __name__ == "__main__":
    _run()
