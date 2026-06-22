"""Offline tests for the deterministic parts of the pipeline (no API key needed).

Run:  .venv/bin/python tests/test_basics.py
Exits non-zero on the first failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reader_companion import textutils as T
from reader_companion import clustering, parsing
from reader_companion.cache import Cache
from reader_companion.llm import MockProvider

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "Reader_Uploaded_Files"
CSV = ROOT / "readwise-data.csv"

_checks = 0


def check(cond, msg):
    global _checks
    _checks += 1
    if not cond:
        raise AssertionError(msg)


def test_filename_parsing():
    title, ulid = T.parse_filename("Getting Started with Reader (01kvqdzf01ke74vweknm8c24b6)")
    check(title == "Getting Started with Reader", f"title was {title!r}")
    check(ulid == "01kvqdzf01ke74vweknm8c24b6", f"ulid was {ulid!r}")
    title2, ulid2 = T.parse_filename("No Id Here")
    check(ulid2 is None, "expected no ulid")
    check(title2 == "No Id Here", f"title2 was {title2!r}")


def test_html_and_stub():
    check(T.html_to_text("<p>Hello <b>world</b></p>") == "Hello world", "html_to_text basic")
    check(T.is_error_stub("Error\nOops, something went wrong. Please try again later.\nOK"),
          "error page should be a stub")
    check(T.is_error_stub("tiny"), "near-empty should be a stub")
    check(not T.is_error_stub("This is a perfectly normal sentence with enough words in it."),
          "normal text is not a stub")


def test_title_matching():
    # The real join cases from the sample data.
    s_match = T.title_match_score(
        "🚨 BREAKING: Temperatures are now set to reach up to...",
        "🚨 BREAKING Temperatures are now set to reach up to...")
    check(s_match >= 0.8, f"breaking titles should match strongly, got {s_match:.2f}")
    s_diff = T.title_match_score(
        "Effortlessly save popular documents in two clicks",
        "Quickly add great reads from the Readwise community to your library")
    check(s_diff < 0.6, f"unrelated titles should not match, got {s_diff:.2f}")
    s_short = T.title_match_score("X", "Log in to X X")
    check(s_short < 0.6, f"short coincidental titles should not match, got {s_short:.2f}")


def test_reading_time():
    check(T.reading_minutes(0) == 0, "zero words -> 0 min")
    check(T.reading_minutes(220) == 1, "220 words -> ~1 min")
    check(T.effort_label(2) == "Quick", "2 min is Quick")
    check(T.effort_label(20) == "Long", "20 min is Long")


def test_parse_and_join_sample():
    if not EXPORTS.exists() or not CSV.exists():
        print("  (skipping sample-data test — fixtures not present)")
        return
    docs = parsing.load_documents(str(EXPORTS))
    check(len(docs) >= 10, f"expected >=10 docs, got {len(docs)}")
    buckets = {d.bucket for d in docs}
    check("Library" in buckets and "Feed" in buckets, f"buckets were {buckets}")
    check(any(d.is_stub for d in docs), "expected at least one error-stub doc (Log in to X X)")
    check(all(d.reader_url and d.reader_url.startswith("https://read.readwise.io/read/")
              for d in docs if d.doc_id), "deep links should be built from the ULID")

    sources = parsing.load_highlights(str(CSV))
    check(len(sources) >= 1, "expected at least one highlight source")
    jr = parsing.join(docs, sources)
    # BREAKING should match; the renamed "Effortlessly..." source should be highlights-only.
    check(len(jr.matched) >= 1, "expected at least one matched document")
    titles_only = {s.title for s in jr.highlights_only}
    check("Effortlessly save popular documents in two clicks" in titles_only,
          "the renamed source should land in highlights-only")
    check(all(d.is_stub for d in jr.stubs), "stubs bucket should only hold stubs")


def test_clustering_with_mock():
    # Deterministic mock embeddings -> clustering should produce sane groups.
    docs = parsing.load_documents(str(EXPORTS)) if EXPORTS.exists() else []
    if not docs:
        print("  (skipping clustering test — fixtures not present)")
        return
    provider = MockProvider()
    live = [d for d in docs if not d.is_stub]
    from reader_companion import layer1
    layer1.run_layer1(docs, provider, model="mock", effort=None, workers=1,
                      max_chars=20000, verbose=False)
    layer1.embed_documents(docs, provider, model="mock", verbose=False)
    clusters = clustering.cluster_documents(docs, provider, n_clusters=None, verbose=False)
    check(len(clusters) >= 1, "expected at least one cluster")
    clustered = [d for d in live if d.cluster_id is not None]
    check(len(clustered) == len(live), "every live doc should be assigned to a cluster")
    check(all(c.name for c in clusters), "every cluster should have a name")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\nAll {len(tests)} tests passed ({_checks} checks).")


if __name__ == "__main__":
    main()
