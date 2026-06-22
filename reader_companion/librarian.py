"""The agentic librarian chat (PRODUCT_PLAN §8, v2).

An entity that has "read everything you saved". Every document's summaries, tags, theme and
the reader's interest profile are placed in the model's context up front; the model can then
pull any article's full text on demand via the `read_full_text` tool when the summaries aren't
enough (e.g. to judge a precise reading order, compare specific arguments, or extract steps).

This module is pure logic + transport: it builds the prompt, runs the tool-calling loop against
the OpenAI Chat Completions API, and exposes a small `Librarian` class. The CLI in `chat.py`
drives it; nothing here touches stdin/stdout, so it is equally usable from a notebook or a web
handler later.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from . import config
from . import textutils as T

# on_event(kind, detail): "thinking" before each model call, "tool" when a tool runs.
EventHook = Callable[[str, Optional[str]], None]

SYSTEM = """\
You are the reader's personal librarian. You have read and summarised their entire Readwise \
Reader library. Everything you know about it is below: the reader's interest profile (in their \
own words and as inferred from what they highlighted), and a catalog of every saved document \
with its theme, tags, reading time, and two summaries — a faithful "basic summary" of what the \
piece says, and a personalised "smart summary" (TL;DR, why it might matter to THIS reader, how \
it sits among their other saved pieces, and concrete takeaways).

Your job is to help them get value out of this backlog: decide WHAT to read and IN WHAT ORDER, \
find pieces on a topic, compare or connect saved articles, and explain WHY something is worth \
their time — grounded in their profile and highlights, not generic praise.

You have a tool, read_full_text(doc_key), that returns an article's full text. The summaries are \
usually enough, but call it when they are not — to judge the precise reading order of several \
dense pieces, compare specific arguments, verify a detail, or pull out concrete steps. Read the \
few documents that actually matter rather than guessing; you may call it several times before \
answering.

Guidelines:
- Be concrete and specific. Recommend actual documents by their title.
- When you propose a reading order, briefly justify the order (e.g. foundational before \
advanced, short before deep, or following the reader's recent thread).
- Cite documents by title; include the Reader link when one is available.
- Ground "why you" claims in the reader's profile, about-me, or highlights. If the library has \
little or nothing on what they asked about, say so honestly instead of stretching weak matches.
- Keep answers focused. Use short numbered or bulleted lists when ordering or recommending."""

_TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_full_text",
        "description": (
            "Return the full text of one saved document, so you can go beyond its summary. "
            "Use it to judge precise reading order, compare specific arguments, verify a "
            "detail, or extract concrete steps. Pass the exact key shown in [brackets] next "
            "to the document in the catalog."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_key": {
                    "type": "string",
                    "description": "The exact document key from the catalog, e.g. the value "
                                   "in [brackets] after the title.",
                },
            },
            "required": ["doc_key"],
            "additionalProperties": False,
        },
    },
}]


def _fmt_profile(profile: dict[str, Any]) -> str:
    lines: list[str] = []
    facets = profile.get("facets") or []
    if facets:
        lines.append("Interest facets (strongest first):")
        for f in facets:
            ev = f.get("evidence") or []
            ev_s = f"; evidence: {', '.join(ev)}" if ev else ""
            lines.append(f"- {f['topic']} (weight {float(f.get('weight', 0)):.2f}, "
                         f"{f.get('recency', 'unknown')}){ev_s}")
    if profile.get("synthesis"):
        lines.append(f"\nSynthesis: {profile['synthesis']}")
    if profile.get("about_me"):
        lines.append(f"\nReader's about-me (verbatim):\n{profile['about_me']}")
    return "\n".join(lines) if lines else "(no profile signal available)"


def _fmt_doc(d: dict[str, Any]) -> str:
    sm = d.get("smart") or {}
    meta = [d.get("cluster_name") or "Uncategorised"]
    if d.get("reading_minutes"):
        meta.append(f"{d['reading_minutes']} min")
    if d.get("vibe"):
        meta.append(str(d["vibe"]))
    if d.get("content_type"):
        meta.append(str(d["content_type"]))
    if d.get("matched"):
        meta.append(f"★ highlighted ({d.get('n_highlights', 0)})")

    out = [f"[{d['key']}] {d['title']}"]
    out.append(f"    theme/meta: {' · '.join(meta)}")
    if d.get("tags"):
        out.append(f"    tags: {', '.join(d['tags'])}")
    if sm.get("tldr"):
        out.append(f"    tl;dr: {sm['tldr']}")
    elif d.get("basic_summary"):
        out.append(f"    summary: {d['basic_summary']}")
    if sm.get("why_you"):
        out.append(f"    why you: {sm['why_you']}")
    if sm.get("how_it_sits"):
        out.append(f"    how it sits: {sm['how_it_sits']}")
    if sm.get("takeaways"):
        out.append(f"    takeaways: {'; '.join(sm['takeaways'])}")
    if sm.get("tldr") and d.get("basic_summary"):
        out.append(f"    basic summary: {d['basic_summary']}")
    hls = d.get("highlights") or []
    if hls:
        shown = hls[:config.CHAT_HIGHLIGHTS_IN_CONTEXT]
        quotes = "; ".join(f'"{T.truncate(h["text"], 200)}"' for h in shown if h.get("text"))
        if quotes:
            more = "" if len(hls) <= len(shown) else f" (+{len(hls) - len(shown)} more)"
            out.append(f"    your highlights: {quotes}{more}")
    if d.get("url"):
        out.append(f"    link: {d['url']}")
    return "\n".join(out)


def build_system_prompt(snapshot: dict[str, Any]) -> str:
    docs = snapshot.get("docs", [])
    meta = snapshot.get("meta", {})
    catalog = "\n\n".join(_fmt_doc(d) for d in docs)
    n_docs = len(docs)
    n_themes = meta.get("n_clusters", len(snapshot.get("clusters", [])))
    parts = [
        SYSTEM,
        "\nREADER PROFILE\n" + _fmt_profile(snapshot.get("profile", {})),
        f"\nLIBRARY CATALOG ({n_docs} documents across {n_themes} themes)\n" + catalog,
    ]
    return "\n".join(parts)


class Librarian:
    """Stateful chat session over one library snapshot."""

    def __init__(self, snapshot: dict[str, Any], *, model: str | None = None,
                 effort: str | None = "__default__", max_retries: int = 4):
        self.snapshot = snapshot
        self.docs = snapshot.get("docs", [])
        self.by_key = {d["key"]: d for d in self.docs}
        self._by_norm_title = {T.normalize_title(d["title"]): d for d in self.docs}
        self.model = model or config.CHAT_MODEL
        self.effort = config.CHAT_EFFORT if effort == "__default__" else effort
        self.max_retries = max_retries
        self.system_prompt = build_system_prompt(snapshot)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        self._client = None

    # -- transport -------------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI  # lazy: import only when a real chat starts
            self._client = OpenAI()
        return self._client

    def _create(self, *, use_tools: bool):
        def do():
            kwargs: dict[str, Any] = dict(model=self.model, messages=self.messages)
            if use_tools:
                kwargs["tools"] = _TOOLS
            if self.effort:
                kwargs["reasoning_effort"] = self.effort
            return self.client.chat.completions.create(**kwargs)

        import openai
        transient = (openai.RateLimitError, openai.APITimeoutError,
                     openai.APIConnectionError, openai.InternalServerError)
        delay = 2.0
        for attempt in range(self.max_retries):
            try:
                return do()
            except transient:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

    # -- tools -----------------------------------------------------------------------
    def _resolve(self, ref: str) -> Optional[dict[str, Any]]:
        ref = (ref or "").strip()
        if not ref:
            return None
        if ref in self.by_key:
            return self.by_key[ref]
        norm = T.normalize_title(ref)
        if norm in self._by_norm_title:
            return self._by_norm_title[norm]
        # Forgiving fall back: best fuzzy title match if it's clearly the same doc.
        best, best_score = None, 0.0
        for d in self.docs:
            score = T.title_match_score(ref, d["title"])
            if score > best_score:
                best, best_score = d, score
        return best if best_score >= 0.6 else None

    def read_full_text(self, ref: str) -> tuple[str, Optional[dict[str, Any]]]:
        d = self._resolve(ref)
        if not d:
            return (f"No document matches {ref!r}. Pass the exact key shown in [brackets] in "
                    f"the catalog.", None)
        text = (d.get("full_text") or "").strip()
        if not text:
            return (f"(Full text for {d['title']!r} is not available in this snapshot.)", d)
        header = (f"FULL TEXT — {d['title']} "
                  f"({d.get('reading_minutes', '?')} min, {d.get('word_count', '?')} words)")
        if d.get("url"):
            header += f"\nReader link: {d['url']}"
        return (header + "\n\n" + text, d)

    def _dispatch(self, tool_call, on_event: Optional[EventHook]) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        if name == "read_full_text":
            ref = args.get("doc_key") or args.get("title") or ""
            result, doc = self.read_full_text(ref)
            if on_event:
                label = doc["title"] if doc else ref
                on_event("tool", f"reading full text · {label}")
            return result
        return f"Unknown tool: {name}"

    # -- public API ------------------------------------------------------------------
    def reset(self) -> None:
        """Forget the conversation (keep the loaded library)."""
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def ask(self, user_message: str, *, on_event: Optional[EventHook] = None) -> str:
        """Run one user turn through the agentic loop and return the assistant's answer."""
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(config.CHAT_MAX_TOOL_ITERS):
            if on_event:
                on_event("thinking", None)
            resp = self._create(use_tools=True)
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                **({"tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in tool_calls]} if tool_calls else {}),
            })
            if not tool_calls:
                return msg.content or ""
            for tc in tool_calls:
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": self._dispatch(tc, on_event),
                })

        # Tool budget exhausted — ask once more for a final answer, no further tools.
        if on_event:
            on_event("thinking", None)
        resp = self._create(use_tools=False)
        content = resp.choices[0].message.content or ""
        self.messages.append({"role": "assistant", "content": content})
        return content
