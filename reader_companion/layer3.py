"""F5 — Layer 3: the rich, personalised "smart summary" (gpt-5, low effort).

Per document, context = full article text + every Layer-1 summary of the OTHER documents in
the same cluster + the user profile. Eager: one call per document."""

from __future__ import annotations

import math

from . import config
from . import textutils as T
from .llm import Provider
from .models import Cluster, Document, Profile, SmartSummary
from .schemas import Layer3Summary
from .util import map_concurrent

SYSTEM = (
    "You are a sharp personal librarian who has read the reader's entire library. For one "
    "document you write a smart, RELATIVE summary: what it is, why THIS reader specifically "
    "might want it, and how it sits among the other things they've saved on the same theme. "
    "Every personalised claim ('because you…') must trace to the reader's profile, about-me, or "
    "highlights — if the fit is weak, say so plainly rather than inventing a reason. Be concrete "
    "and specific; avoid generic praise. Follow the schema."
)


def _format_profile(profile: Profile) -> str:
    lines: list[str] = []
    if profile.facets:
        lines.append("Interest facets (strongest first):")
        for f in profile.facets:
            ev = f"; evidence: {', '.join(f.evidence)}" if f.evidence else ""
            lines.append(f"- {f.topic} (weight {f.weight:.2f}, {f.recency}){ev}")
    if profile.synthesis:
        lines.append(f"\nSynthesis: {profile.synthesis}")
    if profile.about_me:
        lines.append(f"\nReader's about-me (verbatim):\n{profile.about_me}")
    return "\n".join(lines) if lines else "(no profile signal available)"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _nearest_siblings(doc: Document, siblings: list[Document], cap: int) -> list[Document]:
    if len(siblings) <= cap:
        return siblings
    if doc.embedding:
        ranked = sorted(siblings, key=lambda s: _cosine(doc.embedding, s.embedding or []),
                        reverse=True)
        return ranked[:cap]
    return siblings[:cap]


def _user_prompt(doc, siblings, cluster_name, profile_block, max_chars) -> str:
    po, pc = config.M_PROFILE
    so, sc = config.M_SIBLINGS
    co, cc = config.M_CONTENT

    if siblings:
        sib_lines = "\n".join(
            f"- {s.title}: {T.truncate(s.summary.summary if s.summary else '', 240)}"
            for s in siblings
        )
    else:
        sib_lines = "(this is the only document in its theme)"

    body = T.truncate(doc.text, max_chars)
    basic = doc.summary.summary if doc.summary else ""
    return (
        f"READER PROFILE:\n{po}\n{profile_block}\n{pc}\n\n"
        f"OTHER DOCUMENTS IN THE SAME THEME (\"{cluster_name}\") — use these to position the "
        f"document (rare vs one-of-many; does it agree or disagree?):\n{so}\n{sib_lines}\n{sc}\n\n"
        "THE DOCUMENT TO SUMMARISE:\n"
        f"Title: {doc.title}\n"
        f"Section: {doc.bucket}\n"
        f"Basic summary: {basic}\n"
        f"{co}\n{body}\n{cc}\n\n"
        "Write: a one-line TL;DR; why this reader might care (grounded only in their profile / "
        "about-me / highlights — be honest if the fit is weak); how it sits in their library "
        "relative to the sibling documents above; and 2-4 concrete takeaways."
    )


def run_layer3(docs: list[Document], clusters: list[Cluster], profile: Profile,
               provider: Provider, *, model: str, effort: str | None, workers: int,
               max_chars: int, verbose: bool = True) -> list[Document]:
    cluster_name = {c.id: c.name for c in clusters}
    members: dict[int, list[Document]] = {}
    for d in docs:
        if d.cluster_id is not None:
            members.setdefault(d.cluster_id, []).append(d)

    profile_block = _format_profile(profile)
    targets = [d for d in docs if d.summary and not d.is_stub and not d.error]

    def work(doc: Document) -> None:
        try:
            sibs = [m for m in members.get(doc.cluster_id, [])
                    if m.key != doc.key and m.summary]
            sibs = _nearest_siblings(doc, sibs, config.MAX_SIBLINGS)
            name = cluster_name.get(doc.cluster_id, "Uncategorised")
            user = _user_prompt(doc, sibs, name, profile_block, max_chars)
            res: Layer3Summary = provider.structured(
                kind="layer3", model=model, system=SYSTEM, user=user,
                schema=Layer3Summary, effort=effort,
            )
            doc.smart = SmartSummary(
                tldr=res.tldr.strip(),
                why_you=res.why_you.strip(),
                how_it_sits=res.how_it_sits.strip(),
                takeaways=[t.strip() for t in res.takeaways if t.strip()],
            )
        except Exception as e:
            doc.error = f"layer3: {e}"

    map_concurrent(work, targets, workers, "Layer 3 · smart summaries", verbose)
    return targets
