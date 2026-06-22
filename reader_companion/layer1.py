"""F2 — Layer 1: a short, context-free summary + tags + vibe per document (gpt-5-mini),
then an embedding per document for clustering."""

from __future__ import annotations

from . import config
from . import textutils as T
from .llm import Provider
from .models import Document, DocSummary
from .schemas import Layer1Summary
from .util import map_concurrent

SYSTEM = (
    "You are a precise librarian's assistant. You write tight, faithful, context-free "
    "summaries of individual documents and tag them by topic. Summarise only what the "
    "document itself says — no speculation, no pitching it to an audience. Follow the "
    "provided schema exactly."
)


def _user_prompt(doc: Document, max_chars: int) -> str:
    body = T.truncate(doc.text, max_chars)
    co, cc = config.M_CONTENT
    return (
        f"Summarise the following document.\n\n"
        f"Title: {doc.title}\n"
        f"Section: {doc.bucket} "
        f"({'saved by the user' if doc.bucket == 'Library' else 'an RSS / newsletter feed item'})\n\n"
        f"{co}\n{body}\n{cc}\n\n"
        "Write a faithful 2-4 sentence summary, choose 3-7 short topical tags, identify the "
        "content type, judge the reading vibe (dense<->entertaining), and the language."
    )


def _embed_text(doc: Document) -> str:
    parts = [doc.title]
    if doc.summary:
        parts.append(doc.summary.summary)
        if doc.summary.tags:
            parts.append("Tags: " + ", ".join(doc.summary.tags))
    return T.truncate("\n".join(parts), config.EMBED_MAX_CHARS)


def run_layer1(docs: list[Document], provider: Provider, *, model: str, effort: str | None,
               workers: int, max_chars: int, verbose: bool = True) -> list[Document]:
    targets = [d for d in docs if not d.is_stub]

    def work(doc: Document) -> None:
        try:
            res: Layer1Summary = provider.structured(
                kind="layer1", model=model, system=SYSTEM,
                user=_user_prompt(doc, max_chars), schema=Layer1Summary, effort=effort,
            )
            doc.summary = DocSummary(
                summary=res.summary.strip(),
                tags=[t.strip().lower() for t in res.tags if t.strip()],
                vibe=res.vibe,
                content_type=res.content_type.strip().lower(),
                language=res.language.strip(),
            )
        except Exception as e:  # keep the batch resilient
            doc.error = f"layer1: {e}"

    map_concurrent(work, targets, workers, "Layer 1 · summaries", verbose)
    return targets


def embed_documents(docs: list[Document], provider: Provider, *, model: str,
                    verbose: bool = True) -> list[Document]:
    targets = [d for d in docs if not d.is_stub and d.summary and not d.error]
    if not targets:
        return []
    if verbose:
        print(f"Embedding · {len(targets)} documents ({model})")
    vectors = provider.embed(model=model, texts=[_embed_text(d) for d in targets])
    for doc, vec in zip(targets, vectors):
        doc.embedding = vec or None
    return targets
