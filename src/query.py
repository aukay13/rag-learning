import argparse
import os
import time

import psycopg2
import requests
from dotenv import load_dotenv

from embed_test import embed_query

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
OLLAMA_URL = "http://localhost:11434"
GEN_MODEL = "llama3.2:3b"
TOP_K = 4


def retrieve(question: str, conn, k: int) -> tuple[list[tuple[str, dict, float]], float]:
    start = time.time()
    embedding = embed_query(question)
    vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    cur = conn.cursor()
    cur.execute(
        """
        SELECT content, metadata, embedding <=> %s::vector AS distance
        FROM chunks
        ORDER BY distance
        LIMIT %s
        """,
        (vector_literal, k),
    )
    rows = cur.fetchall()
    cur.close()

    return rows, time.time() - start


def build_prompt(question: str, rows: list[tuple[str, dict, float]]) -> str:
    context = "\n\n".join(f"[{i}] {content}" for i, (content, _, _) in enumerate(rows, start=1))
    return (
        "Use only the following context to answer the question.\n"
        "If the context does not contain the answer, say you don't know.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def generate(prompt: str) -> tuple[str, float]:
    start = time.time()
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": GEN_MODEL, "prompt": prompt, "stream": False},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["response"], time.time() - start


def answer_question(question: str, conn, k: int, no_context: bool, retrieve_only: bool) -> None:
    if no_context:
        prompt = question
    else:
        rows, retrieval_elapsed = retrieve(question, conn, k)
        print(f"\nRetrieved {len(rows)} chunks in {retrieval_elapsed:.2f}s:")
        for content, metadata, distance in rows:
            header = (metadata or {}).get("header")
            print(f"  distance={distance:.4f}  header={header}")
            print(f"    {content[:200]!r}")
        if retrieve_only:
            return
        prompt = build_prompt(question, rows)

    answer, gen_elapsed = generate(prompt)
    print(f"\nGenerated in {gen_elapsed:.2f}s")
    print(f"\nAnswer:\n{answer}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--no-context", action="store_true")
    parser.add_argument("--retrieve-only", action="store_true")
    parser.add_argument("--k", type=int, default=TOP_K)
    args = parser.parse_args()

    conn = None if args.no_context else psycopg2.connect(DATABASE_URL)

    try:
        if args.question:
            answer_question(args.question, conn, args.k, args.no_context, args.retrieve_only)
        else:
            while True:
                question = input("> ").strip()
                if question == "quit":
                    break
                if not question:
                    continue
                answer_question(question, conn, args.k, args.no_context, args.retrieve_only)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
