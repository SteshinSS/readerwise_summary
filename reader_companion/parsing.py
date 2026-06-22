"""F1 — export ingestion: parse the library HTML and highlights CSV, then join them."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config
from . import textutils as T
from .models import Document, Highlight, Source

# Subfolders Reader uses inside the export.
_BUCKETS = ("Library", "Feed")


# --------------------------------------------------------------------------------------
# Documents (the universe)
# --------------------------------------------------------------------------------------
def load_documents(exports_dir: str) -> list[Document]:
    root = Path(exports_dir)
    if not root.exists():
        raise FileNotFoundError(f"Exports folder not found: {exports_dir}")

    # Accept either an export root containing Library/ & Feed/, or those folders directly.
    bucket_dirs: list[tuple[str, Path]] = []
    for b in _BUCKETS:
        d = root / b
        if d.is_dir():
            bucket_dirs.append((b, d))
    if not bucket_dirs:
        # Fall back: treat every .html under root as a single (Library) bucket.
        bucket_dirs = [("Library", root)]

    docs: list[Document] = []
    for bucket, d in bucket_dirs:
        for path in sorted(d.rglob("*.html")):
            docs.append(_load_one(path, bucket))
    return docs


def _load_one(path: Path, bucket: str) -> Document:
    title, doc_id = T.parse_filename(path.stem)
    try:
        html = path.read_text("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - unexpected IO
        html = ""
        print(f"  ! could not read {path.name}: {e}", file=sys.stderr)
    text = T.html_to_text(html)
    wc = T.word_count(text)
    stub = T.is_error_stub(text)
    doc = Document(
        doc_id=doc_id,
        title=title,
        bucket=bucket,
        path=str(path),
        text=text,
        word_count=wc,
        is_stub=stub,
        reader_url=config.READER_URL.format(doc_id=doc_id) if doc_id else None,
    )
    doc.reading_minutes = T.reading_minutes(wc)
    doc.effort = T.effort_label(doc.reading_minutes)
    return doc


# --------------------------------------------------------------------------------------
# Highlights (engagement)
# --------------------------------------------------------------------------------------
def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    # Readwise tag fields are comma-separated; tolerate stray whitespace/empties.
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def load_highlights(csv_path: str) -> list[Source]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Highlights CSV not found: {csv_path}")

    grouped: dict[str, Source] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("Book Title") or "").strip()
            if not title:
                continue
            hl = Highlight(
                text=(row.get("Highlight") or "").strip(),
                note=(row.get("Note") or "").strip() or None,
                color=(row.get("Color") or "").strip() or None,
                tags=_split_tags(row.get("Tags")),
                location_type=(row.get("Location Type") or "").strip() or None,
                location=(row.get("Location") or "").strip() or None,
                highlighted_at=_parse_dt(row.get("Highlighted at")),
            )
            if title not in grouped:
                grouped[title] = Source(
                    title=title,
                    author=(row.get("Book Author") or "").strip() or None,
                    document_tags=_split_tags(row.get("Document tags")),
                    highlights=[],
                )
            src = grouped[title]
            # Merge any document-level tags seen on later rows.
            for dt in _split_tags(row.get("Document tags")):
                if dt not in src.document_tags:
                    src.document_tags.append(dt)
            if hl.text or hl.note:
                src.highlights.append(hl)
    return list(grouped.values())


# --------------------------------------------------------------------------------------
# Join
# --------------------------------------------------------------------------------------
@dataclass
class JoinResult:
    documents: list[Document]          # all parsed docs (source attached where matched)
    sources: list[Source]              # all parsed sources (matched flag set)
    matched: list[Document]            # docs with highlights
    library_only: list[Document]       # docs without highlights
    highlights_only: list[Source]      # sources with no matching doc
    stubs: list[Document]              # failed/empty exports (excluded from LLM stages)


def join(documents: list[Document], sources: list[Source],
         threshold: float = config.MATCH_THRESHOLD) -> JoinResult:
    """Fuzzy-join sources to documents on normalised title (no shared id exists)."""
    # Greedy best-match: for each source, pick the best unused document above threshold.
    used: set[str] = set()
    for src in sources:
        best_doc: Document | None = None
        best_score = 0.0
        for doc in documents:
            if doc.key in used or doc.is_stub:
                continue
            score = T.title_match_score(src.title, doc.title)
            if score > best_score:
                best_score, best_doc = score, doc
        if best_doc is not None and best_score >= threshold:
            best_doc.source = src
            src.matched_doc_key = best_doc.key
            used.add(best_doc.key)

    stubs = [d for d in documents if d.is_stub]
    live = [d for d in documents if not d.is_stub]
    matched = [d for d in live if d.source is not None]
    library_only = [d for d in live if d.source is None]
    highlights_only = [s for s in sources if s.matched_doc_key is None]
    return JoinResult(
        documents=documents,
        sources=sources,
        matched=matched,
        library_only=library_only,
        highlights_only=highlights_only,
        stubs=stubs,
    )
