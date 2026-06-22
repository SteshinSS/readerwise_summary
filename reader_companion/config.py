"""Central configuration and tunable defaults.

Everything here is overridable from the command line (see generate.py). Values are kept
in one place so the cost/quality knobs are easy to find.
"""

from __future__ import annotations

# --- Models (fixed for v1 per PRODUCT_PLAN §5.2; overridable via CLI) ---------------
LAYER1_MODEL = "gpt-5-mini"          # cheap, high-volume basic summary + tagging
LAYER3_MODEL = "gpt-5"               # quality synthesis for the smart summary
EMBED_MODEL = "text-embedding-3-small"

# Reasoning effort (only meaningful for the reasoning-capable gpt-5 family).
LAYER1_EFFORT = "low"                # keep Layer 1 cheap
LAYER3_EFFORT = "low"               # per the plan: gpt-5 at *low* effort

# --- Reading time / effort ----------------------------------------------------------
WORDS_PER_MINUTE = 220
# (lower_minutes_inclusive, upper_minutes_exclusive, label)
EFFORT_BUCKETS = [
    (0, 4, "Quick"),
    (4, 12, "Medium"),
    (12, 30, "Long"),
    (30, float("inf"), "Epic"),
]

# --- Deep links ---------------------------------------------------------------------
# The ULID in each export filename *is* the Reader document id (verified against the app).
READER_URL = "https://read.readwise.io/read/{doc_id}"

# --- Join (fuzzy title match between CSV sources and HTML documents) -----------------
MATCH_THRESHOLD = 0.60               # max(seq_ratio, token_jaccard) >= this => match

# --- Token/cost bounds --------------------------------------------------------------
LAYER1_MAX_CHARS = 24_000            # truncate document text fed to Layer 1
LAYER3_MAX_CHARS = 24_000            # truncate document text fed to Layer 3
MAX_SIBLINGS = 20                    # cap cluster peers shown to Layer 3 (nearest first)
EMBED_MAX_CHARS = 8_000              # truncate text fed to the embedding model

# --- Clustering ---------------------------------------------------------------------
MAX_CLUSTERS = 12                    # ceiling when auto-selecting k
RANDOM_SEED = 7
KMEANS_RESTARTS = 8
KMEANS_MAX_ITER = 100
EMBED_DIM_MOCK = 256                 # dimensionality of deterministic mock embeddings

# --- Concurrency --------------------------------------------------------------------
DEFAULT_CONCURRENCY = 4             # parallel LLM calls (IO-bound)

# --- Cache --------------------------------------------------------------------------
CACHE_DIR = ".cache/reader_companion"
# Bump when a prompt or schema changes so stale cached responses are ignored.
PROMPT_VERSION = "1"

# --- Markers ------------------------------------------------------------------------
# Wrap the variable content inside prompts so the offline mock provider can extract the
# real input and produce a realistic-looking preview. The real providers just see them
# as ordinary text.
M_CONTENT = ("<<<CONTENT>>>", "<<<END CONTENT>>>")
M_MEMBERS = ("<<<MEMBERS>>>", "<<<END MEMBERS>>>")
M_ABOUT = ("<<<ABOUT>>>", "<<<END ABOUT>>>")
M_HIGHLIGHTS = ("<<<HIGHLIGHTS>>>", "<<<END HIGHLIGHTS>>>")
M_PROFILE = ("<<<PROFILE>>>", "<<<END PROFILE>>>")
M_SIBLINGS = ("<<<SIBLINGS>>>", "<<<END SIBLINGS>>>")
