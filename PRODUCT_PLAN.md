# Reader Companion — Product Plan

*Working title; not load-bearing. Other candidates: Curator, Concierge, Marginalia, Shelf.*

> **Scope (v1 / MVP).** A **local script** the user downloads and runs over a **frozen snapshot of
> exports** — no live API, no token, no incremental updates. Inputs: the **Reader library export
> (HTML)** for content, the **Readwise highlights export (CSV)** for engagement, and a free-text
> **"about me."** Output: a single self-contained **HTML report** (a table of every article with
> tags + a personalized smart summary). The ranked recommender and the agentic chat are **roadmap**
> (§8), not MVP. Models are fixed: `gpt-5-mini` (basic summary) and `gpt-5` at *low* reasoning
> effort (rich summary).

---

## 1. One-liner

**A local tool that reads your exported Readwise library and produces a personalized, browsable
report — every article tagged, clustered, and given a smart summary that explains what it is, how
it differs from the rest of your library, and why *you'd* want to read it.**

---

## 2. The problem

You save far more than you read. Reader, by design, treats each saved item independently. The
result is *collection guilt*: a large, valuable, but illegible pile. Three jobs are unmet:

1. **"Where do I even begin?"** — No prioritization or birds-eye view across the backlog.
2. **"Is this one worth my time, and why?"** — Reader's per-document summary says what an article
   *is*, but not how it relates to everything else you saved or to what you care about.
3. **"I want the right thing but can't phrase it precisely."** — No way to query the whole library
   conversationally *(addressed in v2, not MVP)*.

The MVP attacks #1 and #2 directly: a single report that makes the whole library legible at a
glance and tells you, per article, why it might matter to you.

**Who it's for (initially):** you — a power Reader user with a large, diverse library and a habit of
highlighting.

---

## 3. What Reader already does — and our wedge

This sharpens *what not to build*:

| Reader already has | Implication for us |
|---|---|
| **Per-document auto-summary** ("Ghostreader") | Don't sell "summaries." Sell **relative, personalized** summaries. (The CSV doesn't carry Reader's, so we generate our own.) |
| **Per-document chat** | Our chat (v2) must be **library-wide and agentic**, not single-doc Q&A. |
| **Tags, Views, ⭐️ Shortlist, filter DSL** | We can't write back without the API, so we mirror the *concepts* in our report and **deep-link** into Reader. |
| **Triage + Feed** | Export-only gives only **Library vs Feed**, not triage. |

**Our wedge:** Reader is per-document; everything valuable here is **cross-document** — clustering,
relative positioning, a profile of *you*, and (later) a chat over the whole library. All of it needs
only the *content* and the *highlights*, both of which the exports provide.

---

## 4. Data foundation — export-only, CSV highlights (load-bearing)

The product is exactly as good as the export files.

### 4.1 Reader library export (`Reader_Uploaded_Files/`) — the document universe
- **One HTML file per document**, foldered `Library/` (saved) and `Feed/` (RSS).
- **Filename = `<Title> (<doc-ULID>).html`.** The ULID *is* the Reader document id → working
  deep-links `https://read.readwise.io/read/<id>` (verified against the live app).
- **Body = cleaned content (HTML), no metadata header.** A few docs fail to export (error stub) —
  skip gracefully.
- **Per doc:** title, doc id, Library/Feed bucket, full content.
- **Derivable:** word count, reading-time, language, topics, difficulty, "vibe."
- **NOT present:** author, source URL, category, tags, dates, reading progress, opened timestamps.
- **Coverage: ALL docs.** This is the content backbone *and* the source of full text for Layer-3.

### 4.2 Readwise highlights export — **CSV** (engagement layer; a subset)
- **One row per highlight.** Expected columns (confirm against a real export): `Highlight`,
  `Book Title`, `Book Author`, `Amazon Book ID`, `Note`, `Color`, `Tags`, `Location Type`,
  `Location`, **`Highlighted at`**, `Document tags`.
- **Per highlight:** text, optional note, **timestamp (`Highlighted at`) → recency**, color,
  highlight `Tags`, document-level `Document tags` (your explicit categorization), source title +
  author. Reconstruct a source by grouping rows on `Book Title`.
- **CSV does *not* carry:** per-document Summary, source URL, explicit category — none fatal (we
  generate summaries from HTML, cite via Reader deep-links, infer category as needed).
- **Coverage: only highlighted docs.**

### 4.3 Joining the two
No shared id; the library filename has the *document* ULID, the CSV identifies a source by
title/author. **Join on normalized title** (fuzzy). Populations: **matched** (content + highlights),
**library-only** (content; the majority), **highlights-only** (highlights, no content — degrade).

### 4.4 What export-only costs us (state it plainly)
- **No behavioral signals** (progress, opened/saved dates) ⇒ no "abandoned" / "never opened" nudges.
- **No content-timeliness** (no publish/save dates). `Highlighted at` powers profile recency, *not*
  content-freshness ranking.
- **No triage; category only where inferable.**
- **No write-back** to Reader (needs API). Output is a standalone report; the user acts in Reader via
  deep-links.
- **Static snapshot** — by design for the MVP (§9). No updates; re-run from scratch on a new export.

### 4.5 Upside
Recency via `Highlighted at`; explicit user tags; **everything local** (no rate limits, full text
always available); **private/offline** except the OpenAI calls.

---

## 5. Pipeline (eager / fully pre-computed)

Your original idea — **(1) summarize each doc → (2) profile → (3) re-summarize with context** — is
the backbone, now made concrete and **fully eager** (everything pre-computed in one batch run):

```
PARSE EXPORTS (local)
  • library HTML → content + id + bucket;  highlights CSV → highlights/notes/tags/recency
  • join on normalized title
        │
  LAYER 1 — Basic summary  [gpt-5-mini, one call/doc]
  • short context-free summary of each article (from full text)
  • also extract topics/tags + classify effort (reading time) + vibe
  • embed each doc
        │
  CLUSTER  [embeddings → clusters]
  • assign every doc to a cluster; name each cluster
        │
  PROFILE  [from highlights + recency + tags + your "about me"]  (see §6)
        │
  LAYER 3 — Rich contextual summary  [gpt-5, reasoning effort: low, one call/doc]
  • context = (1) full article text
              (2) the Layer-1 basic summaries of ALL OTHER docs in the same cluster
              (3) the user profile
  • output: the personalized "smart summary" (TL;DR + why-you + how-it-differs + takeaways)
        │
  RENDER → self-contained HTML report  (table: title · tags · cluster · smart summary · link)
```

### 5.1 Why cluster *before* Layer-3
Clustering does two jobs here:
- **It gives each Layer-3 summary its relevant peers.** A rich summary can only say "different from
  your other saved articles" if it sees the right neighbors — the other docs in the same cluster.
- **It structures the report** (§F6), grouping the table by theme so the library's shape is visible
  ("you have 12 saved on X").
Clustering is therefore core, not a fallback.

### 5.2 Models (fixed for v1)
| Stage | Model | Why |
|---|---|---|
| Layer 1 — basic summary + tags | **`gpt-5-mini`** | cheap, high-volume; one call per doc |
| Embeddings — clustering | OpenAI embeddings (default `text-embedding-3-small`, configurable) | vectorize for clustering |
| Layer 3 — rich contextual summary | **`gpt-5`, reasoning effort: low** | quality synthesis across the cluster + profile |

---

## 6. The interest profile (temporal; includes your "about me")

The profile is built once per run and fed into every Layer-3 call.

**Inputs, strongest first:**
- **Highlights & notes** — you literally marked these. **Primary signal.**
- **Recency (`Highlighted at`)** — time-decay weighting, so "recently interested in X" is real.
- **Your tags** (`Tags`, `Document tags`) — explicit categorizations; high confidence.
- **"About me" (free text you provide)** — used **two ways**: (1) as an **input** to profile
  generation (the model folds it into the inferred interest facets), and (2) **appended verbatim**
  to the profile object so Layer-3 always sees your own words, not just the model's paraphrase.
- **Content topics** — to place un-highlighted docs.

**Shape:** a **structured set of interest facets** (topic · weight · recency · evidence) **plus** the
verbatim "about me" block. Every "because you…" in a smart summary should trace to a real artifact
(a highlight, a tag, or your about-me) — the guard against invented interests.

---

## 7. Feature set (MVP)

### F1 — Export ingestion
Parse library HTML (content + id + bucket) and highlights CSV (group rows by title → highlights,
notes, tags, colors, timestamps). Join on normalized title; bucket into matched / library-only /
highlights-only.

### F2 — Layer 1: basic summary + tagging  (`gpt-5-mini`)
One call per doc over the full text → a short context-free summary, topic **tags**, and a
classification of **effort** (reading time from word count) and **vibe** (dense ↔ entertaining).
Embed each doc. These basic summaries are both shown in the report *and* used as Layer-3 context.

### F3 — Interest profile
As in §6 — temporal, tag-aware, includes the user's "about me" (generate + append).

### F4 — Clustering
Cluster on embeddings and name each cluster. Clusters drive both the Layer-3 context (each summary's
peer set) and the report's grouping ("you have 12 saved on X").

### F5 — Layer 3: rich contextual summary  (`gpt-5`, low effort)
Eager, one call per doc. Context = full article text + all Layer-1 summaries of other docs in the
same cluster + the user profile. Output the **smart summary**:
- **TL;DR** (one line)
- **Why you** (personalized hook, traceable to evidence)
- **How it sits in your library** (rare vs. one-of-many; agrees/disagrees with cluster siblings)
- **What you'll get** (key takeaways)
- **Effort & vibe**

### F6 — HTML report (the MVP deliverable)
A **single self-contained HTML file** (inline CSS/JS; opens in a browser, no server):
- A **sortable, filterable table**, one row per article: **Title** (deep-linked to Reader), **Theme/
  Cluster**, **Tags**, **Reading time + vibe**, and the **Smart summary** (TL;DR inline, expandable
  to the full rich summary).
- **Grouped/segmented by cluster**, so the library's shape is visible at a glance.
- A **header panel** showing the inferred **interest profile** (facets + your about-me), so you can
  see — and sanity-check — what the system thinks you're into.
- Filter by tag/cluster/effort; sort by anything. This *is* the "where do I begin" view for MVP.

---

## 8. Roadmap (post-MVP)

- **Ranked "read next" recommender** — turn the report into an explained, ranked queue with modes
  (*Surprise me · Quick reads · Deep dive · Following your recent thread*) and a daily/weekly digest.
  (The smart summaries already contain the per-article rationale; this adds ordering + delivery.)
- **Agentic librarian chat (v2)** — chat over the whole library: semantic search over
  summaries+highlights, **fetch full article text on demand** (read local HTML, fully offline),
  recommend/rank, always cited with Reader deep-links. The "talk to an entity that read everything"
  vision.
- **Incremental updates** — content-hash caching so re-runs after a new export only reprocess
  changed docs (deliberately omitted from MVP, §9).
- **Connections & tensions** — "these 3 saved pieces argue opposite things about X."
- **Backlog hygiene** — near-dups, dead links, "you'll likely never read these 40."
- **Live API + write-back** (§13) — structured metadata, behavioral signals, and pushing
  clusters/picks back into Reader as tags/Shortlist.

---

## 9. Run model, privacy & freshness

- **One-shot batch over a frozen snapshot (MVP).** No incremental updates; a re-run ingests the
  whole export set again. (Incremental caching is roadmap.)
- **Work scales linearly with the number of articles** — *N* `gpt-5-mini` calls (Layer 1) + *N*
  embeddings + *N* `gpt-5` calls (Layer 3). Pre-computing everything up front is fine.
- **Everything is local** except the OpenAI calls; full text is always available from the exports.
- **Secret handling:** the user provides `OPENAI_API_KEY` via environment variable; never committed
  (already in `.gitignore`). Article text is sent to OpenAI for summarization/embedding — called out
  in the README so the privacy tradeoff is explicit.
- **Honesty** — every personalized claim traces to a real highlight/tag/about-me.

---

## 10. What changed vs. your original plan

| Your step | Verdict | Change & why |
|---|---|---|
| 1. Summarize each doc context-free | **Keep** | Now the **`gpt-5-mini`** Layer-1 pass; generated from local HTML (CSV carries no summary). |
| 2. Profile from (subset of) summaries | **Keep & strengthen** | Built from **highlights + `Highlighted at` recency + your tags + your "about me"** (generated *and* appended). Structured, temporal, evidence-backed. |
| 3. Re-summarize with full text + all other summaries + profile | **Keep — and now eager, scoped to the cluster** | Context = full text + **all sibling summaries in the same cluster** + profile (your exact ask). **`gpt-5`, low effort.** |
| 4. Smart agentic chat | **Deferred to v2** | Per your scoping — MVP ships the report; chat comes next. |
| Clustering "if it doesn't fit" | **Now core & mandatory** | It gives each smart summary its peer set (the cluster siblings) and structures the report. |

---

## 11. MVP build slice (still no code — the script's shape)

The deliverable is one local script. End-to-end flow:

1. **Inputs:** an exports folder (`Reader_Uploaded_Files/` + the highlights `.csv`), an
   `about_me.txt`, and `OPENAI_API_KEY` in the environment.
2. **Parse + join** exports (F1).
3. **Layer 1** over all docs — `gpt-5-mini`: basic summary + tags + effort/vibe; embed (F2).
4. **Cluster** + name clusters (F4).
5. **Build profile** from highlights + about-me (F3).
6. **Layer 3** over all docs — `gpt-5` low effort: rich smart summary with cluster + profile context
   (F5).
7. **Render** the self-contained HTML report (F6).

Sketch of the run (UX, not implementation):
`python generate.py --exports ./exports --about ./about_me.txt --out report.html`

---

## 12. Open questions / decisions for you

1. **Confirm CSV headers** against a real export so parsing is exact (we depend most on
   `Highlighted at`).
2. **Embeddings model** — default `text-embedding-3-small`, or another? (Drives clustering quality
   and cost.)
3. **Clustering granularity** — roughly how many clusters / how fine-grained? This shapes the peer
   set each smart summary compares against and how the report is grouped.
4. **"About me" input** — a text file (`about_me.txt`), a CLI flag, or an interactive prompt?
5. **Scale** — roughly how many saved docs and highlights? Sets run time and the cluster cap.
6. **Report richness** — table-only for v1, or also a per-article detail page? (Recommendation:
   table with expandable rows — one file, no navigation.)

---

## 13. Future: the API upgrade path (out of scope for v1)

When/if you opt into the API, it adds — without changing the core pipeline — **structured metadata
for every doc**, **behavioral signals** (progress, opened/saved → "abandoned"/"never opened" nudges
and content-freshness), **incremental live sync** (no manual re-export), and **write-back** (push
clusters as tags, picks to ⭐️ Shortlist, summaries to notes). The pipeline (§5), profile (§6), and
report (§7) are designed so this is an *additive* data source, not a rewrite.
