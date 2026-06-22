# Reader Companion

A cross-library intelligence layer on top of [Readwise Reader](https://read.readwise.io).

Readwise Reader is excellent at *collecting* and *reading* — but once you have hundreds of saved
articles, it can't tell you **what to read next**, **why a given piece matters to you
specifically**, or position each article against the rest of your library. This tool adds that
layer, working entirely from your **exports** (no Readwise API, no token).

It produces a single self-contained **HTML report**: a browsable, sortable, filterable table of
every article with auto-generated **tags**, a **theme/cluster**, reading time + vibe, and a
personalised **smart summary** that positions each piece relative to the rest of your library and
your stated interests.

See [`PRODUCT_PLAN.md`](PRODUCT_PLAN.md) for the full design rationale.

---

## Quick start

```bash
# 1. Install (Python 3.10+; tested on 3.14)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Preview the whole thing offline — no API key, no cost (uses placeholder summaries)
python generate.py --mock --out report.html
open report.html

# 3. Real run: describe yourself, then generate
cp about_me.example.txt about_me.txt   # then edit it
export OPENAI_API_KEY=sk-...
python generate.py --out report.html
open report.html
```

By default it reads `./Reader_Uploaded_Files` (the library HTML export) and `./readwise-data.csv`
(the highlights export), and `./about_me.txt` if present.

### Getting the two exports from Readwise

- **Library HTML** → Reader → export your library; you get `Reader_Uploaded_Files/` containing
  `Library/` and `Feed/`, one `<Title> (<id>).html` per document.
- **Highlights CSV** → Readwise → export highlights as CSV (`readwise-data.csv`).

---

## What it does (pipeline)

```
PARSE + JOIN     library HTML (content) + highlights CSV (engagement), joined on fuzzy title
LAYER 1          basic, context-free summary + tags + vibe per doc        gpt-5-mini
EMBED + CLUSTER  embed each doc, group into named themes                  text-embedding-3-small
PROFILE          temporal, evidence-backed interest profile + your about-me
LAYER 3          rich "smart summary" per doc, conditioned on the full    gpt-5 (low reasoning)
                 text + every Layer-1 summary in the same cluster + your profile
RENDER           one self-contained HTML report
```

Work scales linearly: *N* `gpt-5-mini` calls + *N* embeddings + *N* `gpt-5` calls, plus one
profile call and one naming call per cluster. The run is a one-shot batch over a frozen export
snapshot (re-export and re-run to refresh).

The report has three parts: a **header** with library stats, an **interest-profile panel** (facets
with evidence + your about-me, so you can sanity-check what the system thinks you're into), and the
**table**, grouped by theme, with expandable rows (TL;DR → Why you · How it sits in your library ·
Takeaways · Basic summary · Your highlights · deep link into Reader).

---

## Useful flags

| Flag | Purpose |
|---|---|
| `--mock` | Offline preview with deterministic placeholder summaries/embeddings. No key, no cost. |
| `--limit N` | Process only the first N documents (cheap dry run on a big library). |
| `--clusters N` | Force a fixed number of themes (default: auto-selected by silhouette). |
| `--no-cache` | Disable the on-disk API-response cache (`.cache/`). |
| `--concurrency N` | Parallel model calls (default 4). |
| `--match-threshold` | Title-similarity cutoff for the CSV↔HTML join (default 0.60). |
| `--layer1-model` / `--layer3-model` / `--embed-model` | Override the models. |
| `--layer1-effort` / `--layer3-effort` | Reasoning effort (`none`/`minimal`/`low`/`medium`/`high`). |

Run `python generate.py --help` for the full list.

### Caching

API responses are cached on disk (keyed by model + prompt + schema) so a re-run after an
interruption, a crash, or a prompt tweak is nearly free and resumable. This doesn't change results;
disable with `--no-cache` or clear with `rm -rf .cache/`.

---

## Privacy

Everything is local **except the model calls**. To produce summaries and embeddings, each
document's text and your highlights are sent to OpenAI. Your `OPENAI_API_KEY` is read from the
environment (or a local `.env`) and is never written to disk or committed. Nothing else leaves your
machine. Use `--mock` to run the full pipeline with no network calls at all.

Every personalised claim in a smart summary is instructed to trace to a real artifact — a
highlight, a tag, or your about-me — and to say so honestly when a document is a weak fit, rather
than inventing a reason.

---

## Notes, decisions & limitations

- **Models** are the plan's fixed choices (`gpt-5-mini`, `gpt-5` at low reasoning effort,
  `text-embedding-3-small`), all overridable via flags. The provider layer is small and isolated
  (`reader_companion/llm.py`), so swapping providers later is contained.
- **Clustering** is implemented locally with numpy (k-means++ with silhouette-based *k* selection),
  so there's no heavyweight ML dependency. It aims for ~2+ docs per theme so each smart summary has
  peers to compare against.
- **The join is fuzzy and imperfect by design.** Library filenames carry the Reader document id;
  the CSV identifies a source by title/author with no shared id, so matching is on normalised title.
  Documents fall into *matched* (content + highlights), *library-only* (content; the majority), and
  *highlights-only* (highlights whose document title differs or wasn't exported — these still feed
  your profile and are listed at the bottom of the report).
- **Failed/empty exports** (Reader sometimes exports an error stub) are detected and skipped
  gracefully; they're listed in the report footer.
- **Export-only costs** (per the plan): no behavioural signals (no progress/opened/saved dates), no
  content publish dates, no write-back into Reader. The report deep-links into Reader instead.
- There is also a richer **Readwise Markdown export** (`Readwise/`, with source URLs, categories and
  Readwise's own summaries). The MVP deliberately uses the CSV per the plan; the Markdown export is
  a natural future enrichment source.

Run the offline tests with `python tests/test_basics.py`.

---

## Roadmap

- A ranked, explained **"read next"** recommender (modes: *Surprise me · Quick reads · Deep dive ·
  Following your recent thread*).
- An **agentic librarian chat** — talk to an entity that read everything you saved.
- **Incremental updates** (content-hash caching so re-runs only reprocess changed docs).
- Live **API sync + write-back** into Reader (push clusters as tags, picks to ⭐️ Shortlist).
