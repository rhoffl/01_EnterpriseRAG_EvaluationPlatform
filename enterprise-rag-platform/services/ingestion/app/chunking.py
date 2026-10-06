from dataclasses import dataclass

from .parser import ParsedBlock


@dataclass(frozen=True)
class Chunk:
    content: str
    page_start: int | None
    page_end: int | None
    section_path: list[str]
    token_count: int


def chunk_blocks(blocks: list[ParsedBlock], size: int = 500, overlap: int = 75) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk size")
    chunks: list[Chunk] = []
    for block in blocks:
        words = block.text.split()
        start = 0
        while start < len(words):
            window = words[start : start + size]
            if window:
                chunks.append(
                    Chunk(" ".join(window), block.page, block.page, block.section_path, len(window))
                )
            if start + size >= len(words):
                break
            start += size - overlap
    return chunks
