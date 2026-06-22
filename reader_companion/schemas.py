"""Pydantic schemas for the structured LLM outputs.

These are passed straight to the OpenAI Structured Outputs API (`response_format=<Model>`),
so every field is required and types stay simple (str / float / list / Literal) to keep the
generated JSON schema strict-mode compatible.
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

Vibe = Literal["dense", "technical", "balanced", "conversational", "entertaining"]
Recency = Literal["recent", "ongoing", "earlier", "unknown"]


class Layer1Summary(BaseModel):
    summary: str = Field(
        description="A faithful 2-4 sentence, context-free summary of what this document is "
        "and its main points. Describe only what the document says."
    )
    tags: List[str] = Field(
        description="3-7 short lowercase topical tags, e.g. 'machine learning', 'productivity'."
    )
    content_type: str = Field(
        description="The kind of document, e.g. article, tweet, newsletter, changelog, guide, "
        "paper, video, email."
    )
    vibe: Vibe = Field(description="Reading vibe on the dense<->entertaining spectrum.")
    language: str = Field(description="Primary language, e.g. 'English'.")


class ClusterName(BaseModel):
    name: str = Field(description="A short, specific 2-5 word theme name. Never generic ('Misc').")
    description: str = Field(description="One sentence on what ties this cluster together.")


class ProfileFacet(BaseModel):
    topic: str = Field(description="A concise interest area.")
    weight: float = Field(description="Relative strength of this interest, 0.0-1.0.")
    recency: Recency = Field(
        description="How recent the engagement is, based on highlight timestamps."
    )
    evidence: List[str] = Field(
        description="1-3 concrete artifacts justifying this facet: a highlighted phrase, a tag, "
        "or a short quote from the about-me. Never invent evidence."
    )


class ProfileOut(BaseModel):
    facets: List[ProfileFacet] = Field(description="Interest facets, strongest first.")
    synthesis: str = Field(
        description="2-4 sentence prose summary of who this reader is and what they are into now."
    )


class Layer3Summary(BaseModel):
    tldr: str = Field(description="One-line plain-language summary of the document.")
    why_you: str = Field(
        description="1-3 sentences on why THIS reader might care, grounded only in their "
        "profile / about-me / highlights. If the fit is weak, say so honestly."
    )
    how_it_sits: str = Field(
        description="1-3 sentences positioning it in their library: rare vs one-of-many in its "
        "theme; how it agrees or disagrees with the sibling documents in the same cluster."
    )
    takeaways: List[str] = Field(description="2-4 concrete things the reader will get from it.")
