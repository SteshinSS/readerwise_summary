"""Internal data model (plain dataclasses) shared across the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Highlight:
    text: str
    note: Optional[str] = None
    color: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    location_type: Optional[str] = None
    location: Optional[str] = None
    highlighted_at: Optional[datetime] = None


@dataclass
class Source:
    """A highlighted source from the CSV, reconstructed by grouping rows on Book Title."""

    title: str
    author: Optional[str]
    document_tags: list[str]
    highlights: list[Highlight]
    matched_doc_key: Optional[str] = None

    @property
    def latest(self) -> Optional[datetime]:
        stamps = [h.highlighted_at for h in self.highlights if h.highlighted_at]
        return max(stamps) if stamps else None

    @property
    def n_highlights(self) -> int:
        return len(self.highlights)


@dataclass
class DocSummary:
    """Layer 1 output (context-free)."""

    summary: str
    tags: list[str]
    vibe: str
    content_type: str
    language: str


@dataclass
class SmartSummary:
    """Layer 3 output (personalised, cluster-aware)."""

    tldr: str
    why_you: str
    how_it_sits: str
    takeaways: list[str]


@dataclass
class Document:
    """One Reader export document plus everything we derive about it."""

    doc_id: Optional[str]
    title: str
    bucket: str                       # "Library" | "Feed"
    path: str
    text: str
    word_count: int
    is_stub: bool                     # failed export / empty content -> skip LLM stages
    reader_url: Optional[str]
    source: Optional[Source] = None   # matched highlights, if any

    summary: Optional[DocSummary] = None
    embedding: Optional[list[float]] = None
    cluster_id: Optional[int] = None
    smart: Optional[SmartSummary] = None

    reading_minutes: int = 0
    effort: str = ""
    error: Optional[str] = None       # set if an LLM stage failed for this doc

    @property
    def key(self) -> str:
        """Stable identity: the ULID when present, else a hash of the path."""
        if self.doc_id:
            return self.doc_id
        return "p_" + hashlib.sha1(self.path.encode("utf-8")).hexdigest()[:16]

    @property
    def matched(self) -> bool:
        return self.source is not None


@dataclass
class Cluster:
    id: int
    name: str
    description: str
    doc_keys: list[str]


@dataclass
class Facet:
    topic: str
    weight: float
    recency: str
    evidence: list[str]


@dataclass
class Profile:
    facets: list[Facet]
    about_me: str            # appended verbatim, per plan §6
    synthesis: str

    @property
    def is_empty(self) -> bool:
        return not self.facets and not self.about_me.strip()
