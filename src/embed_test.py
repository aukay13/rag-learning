import math
import sys
import time
import requests

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
TIMEOUT = 60


def check_server():
    """Fail fast with a clear message if Ollama isn't reachable."""
    try:
        requests.get(OLLAMA_URL, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: cannot reach Ollama at {OLLAMA_URL}")
        print(f"  {type(e).__name__}: {e}")
        print("  Is the Ollama desktop app running?")
        sys.exit(1)


def get_embedding(text):
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text, "keep_alive": "10m"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def get_embeddings_batch(texts):
    """Batch endpoint — one round trip for many texts. Used by index.py."""
    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts, "keep_alive": "10m"},
        timeout=TIMEOUT * 4,
    )
    response.raise_for_status()
    return response.json()["embeddings"]


def cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return 1 - (dot / (norm_a * norm_b))


DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def embed_document(text):
    return get_embedding(DOC_PREFIX + text)


def embed_query(text):
    return get_embedding(QUERY_PREFIX + text)


def embed_documents_batch(texts):
    return get_embeddings_batch([DOC_PREFIX + t for t in texts])

if __name__ == "__main__":
    check_server()
    print(f"Ollama reachable at {OLLAMA_URL}\n")

    sentences = [
        "The MCP server writes JSON-RPC messages to stdout",
        "print() corrupts the protocol stream",
        "OAuth tokens are stored in token.json",
        "The service is up",
        "The service is down",
        "My favourite food is dosa",
    ]

    vectors = []
    for i, s in enumerate(sentences):
        start = time.time()
        vectors.append(get_embedding(s))
        print(f"  [{i+1}/{len(sentences)}] {time.time() - start:5.2f}s  {s[:50]}")

    print(f"\nDimensions: {len(vectors[0])}\n")

    pairs = []
    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            pairs.append((cosine_distance(vectors[i], vectors[j]),
                          sentences[i], sentences[j]))

    pairs.sort()
    for dist, a, b in pairs:
        print(f"{dist:.4f}  |  {a[:45]:<45} <-> {b[:45]}")


    # --- prefix test ---
    print("\n--- Prefix test ---")

    base      = "The MCP server writes JSON-RPC messages to stdout"
    related   = "print() corrupts the protocol stream"
    unrelated = "OAuth tokens are stored in token.json"

    a = get_embedding(f"search_query: {base}")
    b = get_embedding(f"search_document: {related}")
    c = get_embedding(f"search_document: {unrelated}")

    print(f"related:   {cosine_distance(a, b):.4f}   (baseline 0.4928)")
    print(f"unrelated: {cosine_distance(a, c):.4f}   (baseline 0.4981)")