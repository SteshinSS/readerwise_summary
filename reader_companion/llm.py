"""Provider abstraction for the LLM/embedding calls.

Two implementations:
  * OpenAIProvider — the real thing (chat.completions.parse + embeddings), with caching and
    retry/backoff. Lazily imports `openai` so the mock path needs no API key or package.
  * MockProvider — deterministic, offline, content-aware. Produces valid, plausible-looking
    outputs so the whole pipeline + report can be exercised without spending a cent. The
    prompts wrap their variable inputs in markers (config.M_*) which the mock extracts.

Prompt construction lives in the layer modules; this file is pure transport.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod

from pydantic import BaseModel

from . import config
from .cache import Cache
from .schemas import (
    ClusterName,
    Layer1Summary,
    Layer3Summary,
    ProfileFacet,
    ProfileOut,
)
from . import textutils as T


def _between(text: str, markers: tuple[str, str]) -> str:
    """Return the text between a marker pair, or '' if absent."""
    start, end = markers
    i = text.find(start)
    j = text.find(end)
    if i == -1 or j == -1 or j < i:
        return ""
    return text[i + len(start):j].strip()


class Provider(ABC):
    name = "base"

    @abstractmethod
    def structured(self, *, kind: str, model: str, system: str, user: str,
                   schema: type[BaseModel], effort: str | None = None) -> BaseModel:
        ...

    @abstractmethod
    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        ...


# --------------------------------------------------------------------------------------
# Real provider
# --------------------------------------------------------------------------------------
class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, cache: Cache, max_retries: int = 5):
        from openai import OpenAI  # lazy: keeps mock runs free of the dependency
        self.client = OpenAI()
        self.cache = cache
        self.max_retries = max_retries
        self.calls = 0
        self.embed_calls = 0

    def _retry(self, fn):
        import openai
        transient = (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )
        delay = 2.0
        for attempt in range(self.max_retries):
            try:
                return fn()
            except transient:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

    def structured(self, *, kind, model, system, user, schema, effort=None):
        ck = Cache.key("structured", config.PROMPT_VERSION, model, effort,
                       schema.__name__, system, user)
        cached = self.cache.get(ck)
        if cached is not None:
            return schema.model_validate(cached)

        def do():
            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
            if effort:
                kwargs["reasoning_effort"] = effort
            try:
                return self.client.chat.completions.parse(**kwargs)
            except AttributeError:
                return self.client.beta.chat.completions.parse(**kwargs)

        completion = self._retry(do)
        self.calls += 1
        msg = completion.choices[0].message
        if getattr(msg, "refusal", None):
            raise RuntimeError(f"Model refused ({kind}): {msg.refusal}")
        obj = msg.parsed
        if obj is None:
            raise RuntimeError(f"No parsed output for {kind}")
        self.cache.set(ck, obj.model_dump())
        return obj

    def embed(self, *, model, texts):
        out: list[list[float] | None] = [None] * len(texts)
        pending: list[str] = []
        slots: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            ck = Cache.key("embed", model, t)
            cached = self.cache.get(ck)
            if cached is not None:
                out[i] = cached
            else:
                pending.append(t)
                slots.append((i, ck))

        batch = 128
        for s in range(0, len(pending), batch):
            chunk = pending[s:s + batch]
            resp = self._retry(lambda c=chunk: self.client.embeddings.create(model=model, input=c))
            self.embed_calls += 1
            for j, d in enumerate(resp.data):
                idx, ck = slots[s + j]
                out[idx] = d.embedding
                self.cache.set(ck, d.embedding)
        return [v if v is not None else [] for v in out]


# --------------------------------------------------------------------------------------
# Offline deterministic mock
# --------------------------------------------------------------------------------------
class MockProvider(Provider):
    """Content-aware fakes — good enough to validate plumbing, clustering and rendering."""

    name = "mock"

    def structured(self, *, kind, model, system, user, schema, effort=None):
        if kind == "layer1":
            return self._layer1(user)
        if kind == "cluster":
            return self._cluster(user)
        if kind == "profile":
            return self._profile(user)
        if kind == "layer3":
            return self._layer3(user)
        raise ValueError(f"mock: unknown kind {kind!r}")

    def embed(self, *, model, texts):
        return [self._vector(t) for t in texts]

    # -- builders --
    def _layer1(self, user: str) -> Layer1Summary:
        content = _between(user, config.M_CONTENT) or user
        wc = T.word_count(content)
        if wc < 120:
            vibe, ctype = "conversational", "note"
        elif wc > 1500:
            vibe, ctype = "dense", "article"
        else:
            vibe, ctype = "balanced", "article"
        return Layer1Summary(
            summary=T.first_sentences(content, n=3) or "(empty document)",
            tags=T.keywords(content, k=5) or ["uncategorized"],
            content_type=ctype,
            vibe=vibe,
            language="English",
        )

    def _cluster(self, user: str) -> ClusterName:
        members = _between(user, config.M_MEMBERS) or user
        kws = T.keywords(members, k=3)
        topic = " / ".join(kws[:2]) if kws else "Assorted reads"
        return ClusterName(
            name=topic.title()[:40] or "Assorted Reads",
            description=f"Documents about {', '.join(kws) or 'various topics'}.",
        )

    def _profile(self, user: str) -> ProfileOut:
        about = _between(user, config.M_ABOUT)
        highlights = _between(user, config.M_HIGHLIGHTS)
        corpus = f"{about}\n{highlights}".strip()
        kws = T.keywords(corpus, k=5)
        facets: list[ProfileFacet] = []
        for n, kw in enumerate(kws):
            facets.append(ProfileFacet(
                topic=kw,
                weight=round(max(0.2, 1.0 - n * 0.18), 2),
                recency="recent" if highlights else "unknown",
                evidence=[f"mentioned in {'highlights' if highlights else 'about-me'}: '{kw}'"],
            ))
        if not facets:
            return ProfileOut(facets=[], synthesis="Not enough signal to infer a profile (mock).")
        return ProfileOut(
            facets=facets,
            synthesis="(mock) Reader appears interested in " + ", ".join(kws) + ".",
        )

    def _layer3(self, user: str) -> Layer3Summary:
        content = _between(user, config.M_CONTENT) or user
        profile = _between(user, config.M_PROFILE)
        siblings = _between(user, config.M_SIBLINGS)
        top = (T.keywords(profile, k=1) or ["your interests"])[0]
        many = siblings and "this is the only document" not in siblings.lower()
        return Layer3Summary(
            tldr=T.first_sentences(content, n=1) or "(empty document)",
            why_you=f"(mock) Touches on {top}, which shows up in your profile.",
            how_it_sits=("(mock) One of several in this theme — compare with its siblings."
                         if many else "(mock) A relatively rare topic in your library."),
            takeaways=[s for s in T.first_sentences(content, n=4).split(". ") if s][:3]
                       or ["See the document for details."],
        )

    def _vector(self, text: str) -> list[float]:
        import hashlib
        dim = config.EMBED_DIM_MOCK
        v = [0.0] * dim
        for tok in T._WORD_RE.findall((text or "").lower()):
            if len(tok) <= 3 or tok in T._COMMON:
                continue
            h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
            v[h % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


def make_provider(mock: bool, cache: Cache) -> Provider:
    return MockProvider() if mock else OpenAIProvider(cache)
