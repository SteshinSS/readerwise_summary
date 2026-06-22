"""The structured library snapshot that powers the agentic chat (PRODUCT_PLAN §8, v2).

`generate.py` writes this alongside the HTML report; `chat.py` loads it. It carries everything
the librarian needs *in context* — the interest profile and, per document, its theme, tags,
reading time and both summaries — plus the (capped) full article text so the chat can pull a
document on demand. Bundling the text makes the snapshot self-contained: the chat works even if
the original export folder later moves or is deleted, and reading is "on demand" in the sense
that full text only enters the model's context when the read_full_text tool is called.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import config
from . import textutils as T
from .models import Cluster, Document, Profile
from .parsing import JoinResult


def _hl(h) -> dict[str, Any]:
    return {
        "text": h.text,
        "note": h.note,
        "date": h.highlighted_at.date().isoformat() if h.highlighted_at else None,
    }


def _doc_dict(doc: Document, cluster_name: dict[int, str]) -> dict[str, Any]:
    s, sm = doc.summary, doc.smart
    return {
        "key": doc.key,
        "title": doc.title,
        "url": doc.reader_url,
        "bucket": doc.bucket,
        "path": doc.path,
        "cluster_id": doc.cluster_id,
        "cluster_name": (cluster_name.get(doc.cluster_id)
                         if doc.cluster_id is not None else None),
        "tags": s.tags if s else [],
        "vibe": s.vibe if s else None,
        "content_type": s.content_type if s else None,
        "language": s.language if s else None,
        "reading_minutes": doc.reading_minutes,
        "effort": doc.effort,
        "word_count": doc.word_count,
        "basic_summary": s.summary if s else None,
        "smart": None if not sm else {
            "tldr": sm.tldr,
            "why_you": sm.why_you,
            "how_it_sits": sm.how_it_sits,
            "takeaways": sm.takeaways,
        },
        "matched": doc.matched,
        "n_highlights": doc.source.n_highlights if doc.source else 0,
        "highlights": [_hl(h) for h in doc.source.highlights] if doc.source else [],
        # The full text the chat can pull on demand (capped to bound the snapshot + context).
        "full_text": T.truncate(doc.text, config.CHAT_FULLTEXT_MAX_CHARS),
    }


def build_snapshot(join: JoinResult, clusters: list[Cluster], profile: Profile, *,
                   models: dict[str, str], mock: bool, title: str,
                   exports_dir: str) -> dict[str, Any]:
    live = [d for d in join.documents if not d.is_stub]
    by_key = {d.key: d for d in live}
    cluster_name = {c.id: c.name for c in clusters}

    cluster_dicts = []
    for c in clusters:
        present = [k for k in c.doc_keys if k in by_key]
        cluster_dicts.append({
            "id": c.id, "name": c.name, "description": c.description, "count": len(present),
        })

    return {
        "meta": {
            "title": title,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mock": mock,
            "models": models,
            "exports_dir": exports_dir,
            "snapshot_version": config.SNAPSHOT_VERSION,
            "n_docs": len(join.documents),
            "n_live": len(live),
            "n_clusters": len(clusters),
            "n_highlights": sum(len(s.highlights) for s in join.sources),
            "n_matched": len(join.matched),
        },
        "profile": {
            "facets": [
                {"topic": f.topic, "weight": f.weight, "recency": f.recency,
                 "evidence": f.evidence}
                for f in profile.facets
            ],
            "about_me": profile.about_me,
            "synthesis": profile.synthesis,
        },
        "clusters": cluster_dicts,
        "docs": [_doc_dict(d, cluster_name) for d in live],
    }


def write_snapshot(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_snapshot(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
