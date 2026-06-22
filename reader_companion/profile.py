"""F3 — the interest profile: temporal, tag-aware, evidence-backed, and folding in the
user's free-text "about me" (PRODUCT_PLAN §6). Built once and fed into every Layer-3 call."""

from __future__ import annotations

from .models import Facet, Profile, Source
from .llm import Provider
from .schemas import ProfileOut
from . import config

SYSTEM = (
    "You build an honest, evidence-grounded interest profile of a reader from the highlights "
    "they made (with notes and tags) and a free-text 'about me'. Recent highlights matter more "
    "than older ones. EVERY facet must be backed by concrete evidence — a highlighted phrase, a "
    "tag, or a line from the about-me. Never invent interests that aren't supported by the input. "
    "Fold the about-me into the facets where relevant. Follow the schema."
)

_BLOB_CHAR_BUDGET = 16_000


def build_highlights_blob(sources: list[Source]) -> str:
    """Flatten all highlights (matched + highlights-only), most recent first, evidence-style."""
    rows: list[tuple[float, str]] = []
    for src in sources:
        for hl in src.highlights:
            if not (hl.text or hl.note):
                continue
            ts = hl.highlighted_at.timestamp() if hl.highlighted_at else 0.0
            date = hl.highlighted_at.date().isoformat() if hl.highlighted_at else "undated"
            who = src.title + (f" — {src.author}" if src.author else "")
            line = f"[{date}] {who}: \"{hl.text}\""
            if hl.note:
                line += f"  (note: {hl.note})"
            extra = list(hl.tags) + list(src.document_tags)
            if extra:
                line += f"  [tags: {', '.join(sorted(set(extra)))}]"
            rows.append((ts, line))
    rows.sort(key=lambda r: r[0], reverse=True)

    out, used = [], 0
    for _, line in rows:
        if used + len(line) > _BLOB_CHAR_BUDGET:
            out.append("…[older highlights omitted]")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def build_profile(sources: list[Source], about_me: str, provider: Provider, *,
                  model: str, effort: str | None, verbose: bool = True) -> Profile:
    about_me = (about_me or "").strip()
    blob = build_highlights_blob(sources)

    if not blob and not about_me:
        if verbose:
            print("Profile · no highlights and no about-me — building an empty profile")
        return Profile(facets=[], about_me="",
                       synthesis="No highlights or about-me were provided, so personalisation "
                                 "is limited to each document's own content.")

    ao, ac = config.M_ABOUT
    ho, hc = config.M_HIGHLIGHTS
    user = (
        "Build the reader's interest profile.\n\n"
        f"ABOUT ME (the reader's own words):\n{ao}\n{about_me or '(none provided)'}\n{ac}\n\n"
        "HIGHLIGHTS (most recent first; each shows date, source, optional note, and tags):\n"
        f"{ho}\n{blob or '(no highlights)'}\n{hc}\n\n"
        "Produce interest facets (strongest first) with weights (0-1), recency, and concrete "
        "evidence, plus a short synthesis of who this reader is and what they're into now."
    )
    if verbose:
        n_hl = sum(len(s.highlights) for s in sources)
        print(f"Profile · synthesising from {n_hl} highlights across {len(sources)} sources ({model})")
    try:
        res: ProfileOut = provider.structured(
            kind="profile", model=model, system=SYSTEM, user=user,
            schema=ProfileOut, effort=effort,
        )
        facets = [Facet(topic=f.topic.strip(), weight=float(f.weight), recency=f.recency,
                        evidence=[e.strip() for e in f.evidence if e.strip()])
                  for f in res.facets]
        return Profile(facets=facets, about_me=about_me, synthesis=res.synthesis.strip())
    except Exception as e:
        # Don't sink the whole run; fall back to an about-me-only profile.
        print(f"  ! profile generation failed ({e}); using about-me only")
        return Profile(facets=[], about_me=about_me,
                       synthesis="(Automatic profile synthesis failed; showing your about-me only.)")
