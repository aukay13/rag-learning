"""Markdown-header-aware chunker. Standard library only."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "gcal-mcp-notes.md"
SOURCE = "docs/gcal-mcp-notes.md"

MAX_CHUNK_CHARS = 800
CHUNK_OVERLAP = 150
SEPARATORS = ["\n\n", "\n", ". ", " "]

HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^```")
HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split text into (header, content) pairs on markdown headers, ignoring headers inside code fences."""
    sections: list[tuple[str, list[str]]] = []
    current_header = "(no header)"
    current_lines: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        if not in_fence:
            match = HEADER_RE.match(line)
            if match:
                sections.append((current_header, current_lines))
                current_header = match.group(2).strip()
                current_lines = []
                continue
            if HR_RE.match(line):
                continue
        current_lines.append(line)
    sections.append((current_header, current_lines))

    return [
        (header, joined)
        for header, lines in sections
        for joined in ["\n".join(lines).strip()]
        if joined
    ]


def _merge_splits(splits: list[str], separator: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Greedily merge small splits into chunks up to chunk_size, sliding a chunk_overlap window between them."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    sep_len = len(separator)

    for piece in splits:
        added_len = len(piece) + (sep_len if current else 0)
        if current and current_len + added_len > chunk_size:
            chunks.append(separator.join(current))
            while current and (current_len > chunk_overlap or current_len + added_len > chunk_size):
                removed = current.pop(0)
                current_len -= len(removed) + (sep_len if current else 0)
            added_len = len(piece) + (sep_len if current else 0)
        current.append(piece)
        current_len += added_len

    if current:
        chunks.append(separator.join(current))
    return chunks


def _recursive_split(text: str, separators: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text using the first separator that appears in it, recursing into oversized pieces with the rest."""
    if len(text) <= chunk_size:
        return [text] if text else []

    separator = separators[-1]
    next_separators: list[str] = []
    for i, sep in enumerate(separators):
        if sep in text:
            separator = sep
            next_separators = separators[i + 1 :]
            break

    pieces = text.split(separator)

    small_pieces: list[str] = []
    chunks: list[str] = []
    for piece in pieces:
        if len(piece) < chunk_size:
            small_pieces.append(piece)
        else:
            if small_pieces:
                chunks.extend(_merge_splits(small_pieces, separator, chunk_size, chunk_overlap))
                small_pieces = []
            if next_separators:
                chunks.extend(_recursive_split(piece, next_separators, chunk_size, chunk_overlap))
            else:
                chunks.append(piece)

    if small_pieces:
        chunks.extend(_merge_splits(small_pieces, separator, chunk_size, chunk_overlap))

    return chunks


def chunk_document(text: str, source: str) -> list[dict[str, Any]]:
    """Chunk markdown text section-by-section, prepending each section's header to every chunk it produces."""
    chunks: list[dict[str, Any]] = []

    for header, content in _split_sections(text):
        if len(content) <= MAX_CHUNK_CHARS:
            pieces = [content]
        else:
            pieces = _recursive_split(content, SEPARATORS, MAX_CHUNK_CHARS, CHUNK_OVERLAP)

        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            chunk_text = piece if header == "(no header)" else f"{header}\n\n{piece}"
            chunks.append({"content": chunk_text, "metadata": {"header": header, "source": source}})

    return chunks


def _run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = chunk_document(text, SOURCE)

    for i, chunk in enumerate(chunks):
        content = chunk["content"]
        print("=" * 80)
        print(f"Chunk {i} | {len(content)} chars | header: {chunk['metadata']['header']}")
        print("-" * 80)
        print(content)
    print("=" * 80)

    total = len(chunks)
    avg = sum(len(c["content"]) for c in chunks) / total if total else 0
    print(f"\nTotal chunks: {total} | Average size: {avg:.1f} chars")

    smallest = sorted(
        enumerate(chunks), key=lambda pair: len(pair[1]["content"])
    )[:5]
    print("\n5 smallest chunks:")
    for i, chunk in smallest:
        print(f"  Chunk {i} | {len(chunk['content'])} chars | header: {chunk['metadata']['header']}")


if __name__ == "__main__":
    _run()
