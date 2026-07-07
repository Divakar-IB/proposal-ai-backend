"""
DocxExtractor
─────────────
Converts a .docx file to structured JSON.

Handles:
  - Title and date detection
  - H1 / H2 headings (detected via bold + font size, not styles)
  - Body text paragraphs
  - Bullet points  (●) with optional bold keyword prefix
  - Sub-bullet points (○)
  - Tables → list of row dicts
  - TOC and footer lines are skipped automatically

Output shape:
{
  "title": str,
  "date": str | None,
  "sections": [
    {
      "index": "1",
      "title": "Introduction and Overview",
      "content": [...],          # body content directly under H1
      "subsections": [
        {
          "index": "1.1",
          "title": "About Inmar",
          "content": [
            {"type": "text",       "text": "..."},
            {"type": "bullet",     "keyword": "Content Ingestion", "text": "..."},
            {"type": "sub_bullet", "keyword": null, "text": "..."},
            {"type": "table",      "headers": [...], "rows": [{...}]}
          ]
        }
      ]
    }
  ]
}
"""

import re
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml.ns import qn


# ── Font size constants (EMUs — 1pt = 12700) ──────────────────────────
_SIZE_FOOTER    = 100000   # <= this → footer / page number → skip
_SIZE_H1_MIN    = 165000   # >= this + bold → H1
_SIZE_TITLE_MIN = 200000   # >= this + bold → document title


# ── Data models ───────────────────────────────────────────────────────

@dataclass
class ContentItem:
    type: str                        # text | bullet | sub_bullet | table
    text: Optional[str]   = None
    keyword: Optional[str] = None    # bold label at bullet start e.g. "Content Ingestion"
    headers: Optional[list] = None   # table only
    rows: Optional[list]    = None   # table only


@dataclass
class Subsection:
    index: str
    title: str
    content: list = field(default_factory=list)


@dataclass
class Section:
    index: str
    title: str
    content: list = field(default_factory=list)       # content directly under H1
    subsections: list = field(default_factory=list)


@dataclass
class DocxDocument:
    title: str
    date: Optional[str]
    sections: list = field(default_factory=list)


# ── Extractor ─────────────────────────────────────────────────────────

class DocxExtractor:
    """
    Usage:
        extractor = DocxExtractor()
        result    = extractor.extract("path/to/file.docx")
        json_str  = extractor.to_json(result, indent=2)
    """

    def extract(self, file_path: str) -> DocxDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if path.suffix.lower() != ".docx":
            raise ValueError(f"Expected .docx file, got: {path.suffix}")

        doc = Document(str(path))

        # Build a flat list of classified paragraphs first,
        # then wire them into the nested section/subsection tree.
        flat = self._classify_paragraphs(doc)
        tables = self._extract_tables(doc)

        return self._build_tree(flat, tables)

    # ── Step 1: classify every paragraph ─────────────────────────────

    def _classify_paragraphs(self, doc: Document) -> list[dict]:
        """
        Returns a list of dicts, one per non-empty paragraph:
          {type, text, size, bold, keyword}
        """
        classified = []
        toc_section_passed = False    # flip True after we pass the TOC block

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # ── Collect run metadata ──────────────────────────────────
            runs = para.runs
            sizes = [r.font.size for r in runs if r.font.size]
            dominant_size = max(sizes) if sizes else 0
            all_bold  = bool(runs) and all(r.bold for r in runs if r.text.strip())
            has_bold  = any(r.bold for r in runs if r.text.strip())

            # ── Skip footer / confidentiality lines ──────────────────
            if dominant_size and dominant_size <= _SIZE_FOOTER:
                continue

            # ── Detect TOC entries and skip them ──────────────────────
            # TOC lines: not bold, large font, end with a page number
            if not all_bold and dominant_size >= _SIZE_H1_MIN:
                if re.search(r'\s+\d{1,3}\s*$', text):
                    continue   # TOC line — skip
                else:
                    # H1 heading — mark TOC as passed
                    toc_section_passed = True

            # ── Title ─────────────────────────────────────────────────
            if all_bold and dominant_size >= _SIZE_TITLE_MIN:
                classified.append({
                    "type": "title",
                    "text": text,
                    "size": dominant_size,
                    "bold": True,
                    "keyword": None,
                })
                continue

            # ── Date line (bold, medium size, matches date pattern) ───
            if all_bold and re.search(
                r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{4})',
                text, re.IGNORECASE
            ) and len(text) < 40:
                classified.append({
                    "type": "date",
                    "text": text,
                    "size": dominant_size,
                    "bold": True,
                    "keyword": None,
                })
                continue

            # ── H1 heading ────────────────────────────────────────────
            if all_bold and dominant_size >= _SIZE_H1_MIN:
                classified.append({
                    "type": "h1",
                    "text": text,
                    "size": dominant_size,
                    "bold": True,
                    "keyword": None,
                })
                continue

            # ── H2 heading ────────────────────────────────────────────
            # Bold, smaller size, numbered pattern like "1.1 Something"
            if all_bold and dominant_size < _SIZE_H1_MIN and re.match(
                r'^\d+\.\d+', text
            ):
                classified.append({
                    "type": "h2",
                    "text": text,
                    "size": dominant_size,
                    "bold": True,
                    "keyword": None,
                })
                continue

            # ── Bullet  ● ─────────────────────────────────────────────
            if text.startswith("●"):
                content_text = text[1:].strip()
                keyword = self._extract_bullet_keyword(para)
                classified.append({
                    "type": "bullet",
                    "text": content_text,
                    "size": dominant_size,
                    "bold": has_bold,
                    "keyword": keyword,
                })
                continue

            # ── Sub-bullet  ○ ─────────────────────────────────────────
            if text.startswith("○"):
                content_text = text[1:].strip()
                keyword = self._extract_bullet_keyword(para)
                classified.append({
                    "type": "sub_bullet",
                    "text": content_text,
                    "size": dominant_size,
                    "bold": has_bold,
                    "keyword": keyword,
                })
                continue

            # ── Regular body text ─────────────────────────────────────
            classified.append({
                "type": "text",
                "text": text,
                "size": dominant_size,
                "bold": all_bold,
                "keyword": None,
            })

        return classified

    def _extract_bullet_keyword(self, para) -> Optional[str]:
        """
        Extracts the bold keyword prefix from a bullet paragraph.
        e.g. '● Content Ingestion: The tool must...'
             → 'Content Ingestion'
        """
        for run in para.runs:
            if run.bold and run.text.strip():
                # Strip leading bullet char and trailing colon/space
                kw = run.text.strip().lstrip("●○•").strip().rstrip(":").strip()
                if kw:
                    return kw
        return None

    # ── Step 2: extract tables ────────────────────────────────────────

    def _extract_tables(self, doc: Document) -> list[dict]:
        """
        Extracts all tables from the document.
        First row → headers, remaining rows → list of dicts.
        """
        tables = []
        for table in doc.tables:
            rows = []
            for row in table.rows:
                rows.append([cell.text.strip() for cell in row.cells])

            if not rows:
                continue

            # Deduplicate merged cells (python-docx repeats merged cell text)
            rows = [self._dedup_row(r) for r in rows]

            headers = rows[0]
            data_rows = []
            for row in rows[1:]:
                if any(cell for cell in row):   # skip fully empty rows
                    # Map to dict if headers available, else keep as list
                    if headers and len(headers) == len(row):
                        data_rows.append(dict(zip(headers, row)))
                    else:
                        data_rows.append(row)

            tables.append({
                "type": "table",
                "headers": headers,
                "rows": data_rows,
            })

        return tables

    def _dedup_row(self, row: list[str]) -> list[str]:
        """Remove consecutive duplicate values caused by merged cells."""
        if not row:
            return row
        result = [row[0]]
        for cell in row[1:]:
            if cell != result[-1]:
                result.append(cell)
        return result

    # ── Step 3: build the nested tree ────────────────────────────────

    def _build_tree(
        self,
        flat: list[dict],
        tables: list[dict]
    ) -> DocxDocument:
        """
        Wires flat classified paragraphs into:
        DocxDocument → Section(H1) → Subsection(H2) → ContentItem
        Tables are appended at the end of the last subsection (or section).
        """
        title_text = ""
        date_text  = None
        sections: list[Section] = []

        current_section: Optional[Section]    = None
        current_subsection: Optional[Subsection] = None

        def current_content() -> list:
            """Returns the content list we should append to right now."""
            if current_subsection:
                return current_subsection.content
            if current_section:
                return current_section.content
            return []   # before any heading — discard

        for item in flat:
            t = item["type"]

            if t == "title":
                title_text = item["text"]

            elif t == "date":
                date_text = item["text"]

            elif t == "h1":
                # Parse index from "1. Introduction and Overview"
                m = re.match(r'^(\d+)[\.\s]+(.+)', item["text"])
                if m:
                    idx, heading = m.group(1), m.group(2).strip()
                else:
                    idx, heading = str(len(sections) + 1), item["text"]

                current_subsection = None
                current_section = Section(index=idx, title=heading)
                sections.append(current_section)

            elif t == "h2":
                # Parse index from "1.1 About Inmar"
                m = re.match(r'^(\d+\.\d+)[\.\s]+(.+)', item["text"])
                if m:
                    idx, heading = m.group(1), m.group(2).strip()
                else:
                    idx, heading = "", item["text"]

                current_subsection = Subsection(index=idx, title=heading)
                if current_section:
                    current_section.subsections.append(current_subsection)

            elif t in ("text", "bullet", "sub_bullet"):
                target = current_content()
                if target is not None:
                    target.append(ContentItem(
                        type=t,
                        text=item["text"],
                        keyword=item.get("keyword"),
                    ))

        # Append tables to the last subsection or section
        for table in tables:
            target = current_content()
            if target is not None:
                target.append(ContentItem(
                    type="table",
                    headers=table["headers"],
                    rows=table["rows"],
                ))

        return DocxDocument(
            title=title_text,
            date=date_text,
            sections=sections,
        )

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self, document: DocxDocument) -> dict:
        """Convert DocxDocument to a plain dict (JSON-serialisable)."""
        return {
            "title": document.title,
            "date": document.date,
            "sections": [
                {
                    "index": s.index,
                    "title": s.title,
                    "content": [self._item_to_dict(c) for c in s.content],
                    "subsections": [
                        {
                            "index": sub.index,
                            "title": sub.title,
                            "content": [self._item_to_dict(c) for c in sub.content],
                        }
                        for sub in s.subsections
                    ],
                }
                for s in document.sections
            ],
        }
    def _item_to_dict(self, item: ContentItem) -> dict:
        d: dict = {"type": item.type}
        if item.type in ("text", "bullet", "sub_bullet"):
            if item.keyword:
                d["keyword"] = item.keyword
            d["text"] = item.text
        elif item.type == "table":
            d["headers"] = item.headers
            d["rows"]    = item.rows
        return d

    def to_json(self, document: DocxDocument, indent: int = 2) -> str:
        """Serialize DocxDocument to a JSON string."""
        sections_list = []
        for s in document.sections:
            sections_list.append({
                "index": s.index,
                "title": s.title,
                "content": [self._item_to_dict(c) for c in s.content],
                "subsections": [
                    {
                        "index": sub.index,
                        "title": sub.title,
                        "content": [self._item_to_dict(c) for c in sub.content],
                    }
                    for sub in s.subsections
                ],
            })

        return json.dumps(
            {
                "title": document.title,
                "date": document.date,
                "sections": sections_list,
            },
            indent=indent,
            ensure_ascii=False,
        )


# ── CLI entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python docx_extractor.py <file.docx> [output.json]")
        sys.exit(1)

    input_path  = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    extractor = DocxExtractor()
    result    = extractor.extract(input_path)
    json_str  = extractor.to_json(result, indent=2)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")
        print(f"Saved to {output_path}")
    else:
        print(json_str)