import pytest
from app.chunking import chunk_blocks
from app.parser import ParsedBlock


def test_chunking_preserves_page_and_overlap():
    block = ParsedBlock(" ".join(f"word{i}" for i in range(12)), page=3)
    chunks = chunk_blocks([block], size=5, overlap=2)
    assert len(chunks) == 4
    assert chunks[0].page_start == 3
    assert chunks[0].content.split()[-2:] == chunks[1].content.split()[:2]


def test_chunking_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_blocks([ParsedBlock("content")], size=10, overlap=10)
