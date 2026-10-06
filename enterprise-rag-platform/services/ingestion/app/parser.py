import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup


@dataclass
class ParsedBlock:
    text: str
    page: int | None = None
    section_path: list[str] = field(default_factory=list)


def parse_document(path: Path, content_type: str | None = None) -> list[ParsedBlock]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        import fitz

        with fitz.open(path) as document:
            return [ParsedBlock(page.get_text("text"), page.number + 1) for page in document]
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        return [ParsedBlock("\n".join(p.text for p in document.paragraphs if p.text.strip()))]
    if suffix in {".html", ".htm"}:
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        return [ParsedBlock(soup.get_text("\n", strip=True))]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        return [ParsedBlock(json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in rows]
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return [ParsedBlock(json.dumps(row, sort_keys=True)) for row in csv.DictReader(handle)]
    if suffix in {".txt", ".md"} or content_type == "text/plain":
        return [ParsedBlock(path.read_text(encoding="utf-8"))]
    raise ValueError(f"unsupported document type: {suffix or content_type}")
