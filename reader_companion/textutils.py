"""Small, dependency-light text helpers: HTML->text, title normalisation, fuzzy matching."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

from . import config

# ULID: 26 chars, Crockford base32. Reader filenames end with " (<ulid>).html".
_ULID_RE = re.compile(r"^(?P<title>.*) \((?P<id>[0-9A-Za-z]{26})\)$")

_ERROR_MARKERS = (
    "oops, something went wrong",
    "please try again later",
)

# A few extremely common words ignored when tokenising titles for the fuzzy join.
_TITLE_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "your", "you",
    "with", "from", "is", "are", "how", "this", "that", "it", "at", "by",
}


_BLOCK_TAGS = [
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figure",
    "section", "article", "header", "footer", "tr", "ul", "ol", "table", "pre",
]


def html_to_text(html: str) -> str:
    """Extract readable plain text from a Reader content HTML fragment.

    Inline elements (<b>, <a>, <code>…) stay on the same line; block-level elements and
    <br> introduce line breaks. This keeps sentences intact for the models and for word
    counts, while preserving paragraph structure.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Keep image alt text — it often carries real meaning in these exports.
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        img.replace_with(f" {alt} " if alt else " ")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # Mark the end of each block so it becomes its own line.
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    text = soup.get_text(separator=" ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def parse_filename(stem: str) -> tuple[str, str | None]:
    """Split '<Title> (<ulid>)' into (title, doc_id). doc_id is None if absent."""
    m = _ULID_RE.match(stem)
    if m:
        return m.group("title").strip(), m.group("id")
    return stem.strip(), None


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def reading_minutes(words: int) -> int:
    return max(1, round(words / config.WORDS_PER_MINUTE)) if words else 0


def effort_label(minutes: int) -> str:
    for lo, hi, label in config.EFFORT_BUCKETS:
        if lo <= minutes < hi:
            return label
    return config.EFFORT_BUCKETS[-1][2]


def is_error_stub(text: str) -> bool:
    """Reader sometimes exports an error page or near-empty body — skip those."""
    low = text.lower()
    if any(m in low for m in _ERROR_MARKERS) and len(text) < 200:
        return True
    return word_count(text) < 5


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_title(title: str) -> str:
    """Lowercase, drop accents/emoji/punctuation, collapse whitespace."""
    s = _strip_accents(title.lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _title_tokens(norm: str) -> set[str]:
    return {t for t in norm.split() if t and t not in _TITLE_STOP}


def title_match_score(a: str, b: str) -> float:
    """Robust 0..1 similarity for the CSV<->HTML join.

    Uses the larger of (a) sequence ratio over the normalised strings and
    (b) Jaccard overlap of meaningful tokens. This separates true matches
    (near 1.0) from coincidental short-title overlaps (near 0).
    """
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _title_tokens(na), _title_tokens(nb)
    jac = (len(ta & tb) / len(ta | tb)) if (ta and tb) else 0.0
    return max(seq, jac)


def truncate(text: str, max_chars: int) -> str:
    if text and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n…[truncated]"
    return text or ""


def first_sentences(text: str, n: int = 2, max_chars: int = 320) -> str:
    """Cheap sentence-ish extraction (used only by the offline mock provider)."""
    chunk = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    out = " ".join(chunk[:n]).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "…"
    return out or (text or "")[:max_chars]


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]+")
_COMMON = {
    "the", "and", "for", "you", "your", "with", "that", "this", "are", "was", "have",
    "has", "but", "not", "can", "will", "from", "they", "their", "what", "when",
    "how", "all", "any", "our", "out", "get", "use", "using", "into", "than", "then",
    "them", "these", "those", "there", "here", "about", "also", "more", "most",
    "some", "such", "just", "like", "one", "two", "new", "now", "via", "per",
    # The following are only ever stripped by the offline mock provider (keywords() is
    # mock-only): our truncation marker plus profile-formatting labels, so the fake
    # preview text doesn't pick them up as "topics". No effect on real runs.
    "truncated", "evidence", "weight", "synthesis", "verbatim", "recency",
    "recent", "ongoing", "earlier", "facets",
}


def keywords(text: str, k: int = 6) -> list[str]:
    """Top-k frequent content words (used only by the offline mock provider)."""
    freq: dict[str, int] = {}
    for w in _WORD_RE.findall((text or "").lower()):
        if len(w) <= 3 or w in _COMMON:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
