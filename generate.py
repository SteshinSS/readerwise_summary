#!/usr/bin/env python3
"""Reader Companion — generate a personalised HTML report from your Readwise exports.

Usage (typical):
    export OPENAI_API_KEY=sk-...
    python generate.py --exports ./Reader_Uploaded_Files \
                       --highlights ./readwise-data.csv \
                       --about ./about_me.txt \
                       --out report.html

Preview the whole pipeline offline, no API key, no cost:
    python generate.py --mock --out report.html

See PRODUCT_PLAN.md for the design and `python generate.py --help` for all options.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from reader_companion import config
from reader_companion import clustering, layer1, layer3, parsing, render, snapshot
from reader_companion.cache import Cache
from reader_companion.llm import make_provider
from reader_companion.profile import build_profile


def _find_highlights(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    here = Path(".")
    preferred = here / "readwise-data.csv"
    if preferred.exists():
        return str(preferred)
    csvs = sorted(here.glob("*.csv"))
    return str(csvs[0]) if csvs else None


def _read_about(explicit: str | None) -> str:
    candidates = [explicit] if explicit else ["about_me.txt"]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c).read_text("utf-8").strip()
    if explicit:
        print(f"  ! about-me file not found: {explicit}", file=sys.stderr)
    return ""


def _effort(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    return None if v in ("", "none", "off") else v


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a personalised HTML report from Readwise Reader exports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--exports", default="./Reader_Uploaded_Files",
                   help="Reader library export folder (contains Library/ and Feed/).")
    p.add_argument("--highlights", default=None,
                   help="Readwise highlights CSV (default: ./readwise-data.csv or first *.csv).")
    p.add_argument("--about", default=None,
                   help="Free-text 'about me' file (default: ./about_me.txt if present).")
    p.add_argument("--out", default="report.html", help="Output HTML file.")
    p.add_argument("--snapshot", default=config.SNAPSHOT_PATH,
                   help="Structured library snapshot for the agentic chat (chat.py).")
    p.add_argument("--no-snapshot", action="store_true",
                   help="Skip writing the chat snapshot.")
    p.add_argument("--title", default="Your Reading Library", help="Report title.")

    p.add_argument("--mock", action="store_true",
                   help="Offline mode: deterministic fake summaries/embeddings, no API key, no cost.")
    p.add_argument("--no-cache", action="store_true", help="Disable the on-disk response cache.")
    p.add_argument("--cache-dir", default=config.CACHE_DIR, help="Response cache directory.")

    p.add_argument("--clusters", type=int, default=None,
                   help="Force a fixed number of clusters (default: auto via silhouette).")
    p.add_argument("--match-threshold", type=float, default=config.MATCH_THRESHOLD,
                   help="Title-similarity threshold for the CSV<->HTML join (0-1).")
    p.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY,
                   help="Parallel LLM calls.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only the first N documents (dev/cost control).")

    p.add_argument("--layer1-model", default=config.LAYER1_MODEL)
    p.add_argument("--layer3-model", default=config.LAYER3_MODEL)
    p.add_argument("--embed-model", default=config.EMBED_MODEL)
    p.add_argument("--profile-model", default=None,
                   help="Model for profile synthesis (default: the Layer-3 model).")
    p.add_argument("--layer1-effort", default=config.LAYER1_EFFORT,
                   help="Reasoning effort for Layer 1 (none/minimal/low/medium/high).")
    p.add_argument("--layer3-effort", default=config.LAYER3_EFFORT,
                   help="Reasoning effort for Layer 3.")
    p.add_argument("-q", "--quiet", action="store_true", help="Less console output.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    verbose = not args.quiet

    # Optional .env convenience.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if not args.mock and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Set it, or run with --mock for an offline "
              "preview.", file=sys.stderr)
        return 2

    t0 = time.time()
    cache = Cache(args.cache_dir, enabled=not args.no_cache)
    provider = make_provider(args.mock, cache)
    if verbose:
        mode = "MOCK (offline)" if args.mock else f"OpenAI ({provider.name})"
        print(f"Reader Companion · provider: {mode} · cache: "
              f"{'off' if args.no_cache else args.cache_dir}\n")

    # --- F1: parse + join -------------------------------------------------------------
    documents = parsing.load_documents(args.exports)
    if args.limit:
        kept, n = [], 0
        for d in documents:
            if d.is_stub:
                continue
            kept.append(d)
            n += 1
            if n >= args.limit:
                break
        documents = kept
        if verbose:
            print(f"(--limit) processing first {len(documents)} documents")

    highlights_csv = _find_highlights(args.highlights)
    sources = parsing.load_highlights(highlights_csv) if highlights_csv else []
    if verbose:
        print(f"Parsed · {len(documents)} documents"
              + (f", {sum(len(s.highlights) for s in sources)} highlights "
                 f"across {len(sources)} sources" if sources else ", no highlights CSV found"))

    jr = parsing.join(documents, sources, threshold=args.match_threshold)
    if verbose:
        print(f"Joined · matched {len(jr.matched)} · library-only {len(jr.library_only)} · "
              f"highlights-only {len(jr.highlights_only)} · skipped {len(jr.stubs)}\n")

    if not [d for d in documents if not d.is_stub]:
        print("ERROR: no usable documents found in the exports folder.", file=sys.stderr)
        return 1

    # --- F2: Layer 1 + embeddings -----------------------------------------------------
    layer1.run_layer1(documents, provider, model=args.layer1_model,
                      effort=_effort(args.layer1_effort), workers=args.concurrency,
                      max_chars=config.LAYER1_MAX_CHARS, verbose=verbose)
    layer1.embed_documents(documents, provider, model=args.embed_model, verbose=verbose)

    # --- F4: cluster ------------------------------------------------------------------
    clusters = clustering.cluster_documents(
        documents, provider, n_clusters=args.clusters,
        name_model=args.layer1_model, verbose=verbose)

    # --- F3: profile ------------------------------------------------------------------
    about_me = _read_about(args.about)
    profile = build_profile(sources, about_me, provider,
                            model=args.profile_model or args.layer3_model,
                            effort=_effort(args.layer3_effort), verbose=verbose)

    # --- F5: Layer 3 ------------------------------------------------------------------
    layer3.run_layer3(documents, clusters, profile, provider,
                      model=args.layer3_model, effort=_effort(args.layer3_effort),
                      workers=args.concurrency, max_chars=config.LAYER3_MAX_CHARS,
                      verbose=verbose)

    # --- F6: render -------------------------------------------------------------------
    data = render.build_report_data(
        jr, clusters, profile,
        models={"layer1": args.layer1_model, "layer3": args.layer3_model,
                "embed": args.embed_model},
        mock=args.mock, title=args.title,
    )
    render.write_report(args.out, data)

    # --- chat snapshot (feeds the agentic librarian in chat.py) -----------------------
    if not args.no_snapshot:
        snap = snapshot.build_snapshot(
            jr, clusters, profile,
            models={"layer1": args.layer1_model, "layer3": args.layer3_model,
                    "embed": args.embed_model},
            mock=args.mock, title=args.title, exports_dir=args.exports,
        )
        snapshot.write_snapshot(args.snapshot, snap)

    failed = [d for d in documents if not d.is_stub and d.error]
    if verbose:
        print()
        if not args.mock:
            print(f"API calls · {getattr(provider, 'calls', 0)} completions, "
                  f"{getattr(provider, 'embed_calls', 0)} embedding batches · "
                  f"cache hits {cache.hits}/{cache.hits + cache.misses}")
        if failed:
            print(f"⚠︎ {len(failed)} document(s) failed an LLM stage (shown in the report footer).")
    print(f"\n✓ Report written to {args.out}  ({len(jr.matched) + len(jr.library_only)} documents, "
          f"{len(clusters)} themes) in {time.time() - t0:.1f}s")
    print(f"  Open it in a browser:  open {args.out}")
    if not args.no_snapshot:
        print(f"  Chat with your library:  python chat.py  (snapshot: {args.snapshot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
