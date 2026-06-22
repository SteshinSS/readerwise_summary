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


def _build_sample_snapshot():
    """Run the (mock) pipeline over the sample data and return a chat snapshot dict."""
    from reader_companion import layer1, layer3, snapshot
    from reader_companion.profile import build_profile
    docs = parsing.load_documents(str(EXPORTS))
    sources = parsing.load_highlights(str(CSV))
    jr = parsing.join(docs, sources)
    provider = MockProvider()
    layer1.run_layer1(docs, provider, model="mock", effort=None, workers=1,
                      max_chars=20000, verbose=False)
    layer1.embed_documents(docs, provider, model="mock", verbose=False)
    clusters = clustering.cluster_documents(docs, provider, n_clusters=None, verbose=False)
    profile = build_profile(sources, "I work in ML and care about LLM evals.", provider,
                            model="mock", effort=None, verbose=False)
    layer3.run_layer3(docs, clusters, profile, provider, model="mock", effort=None,
                      workers=1, max_chars=20000, verbose=False)
    return snapshot.build_snapshot(
        jr, clusters, profile,
        models={"layer1": "mock", "layer3": "mock", "embed": "mock"},
        mock=True, title="Test Library", exports_dir=str(EXPORTS))


def test_snapshot_build_and_load():
    if not (EXPORTS.exists() and CSV.exists()):
        print("  (skipping snapshot test — fixtures not present)")
        return
    from reader_companion import snapshot
    import json, tempfile, os
    snap = _build_sample_snapshot()
    check(snap["docs"], "snapshot should have documents")
    d = snap["docs"][0]
    for field in ("key", "title", "full_text", "smart", "tags", "cluster_name"):
        check(field in d, f"doc missing field {field!r}")
    check(snap["profile"]["about_me"], "about-me should be carried into the snapshot")
    check(all(dd.get("full_text") for dd in snap["docs"]), "every live doc should carry full text")
    # round-trip through disk
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        snapshot.write_snapshot(path, snap)
        loaded = snapshot.load_snapshot(path)
        check(len(loaded["docs"]) == len(snap["docs"]), "round-trip should preserve docs")
    finally:
        os.unlink(path)


def test_librarian_prompt_and_tool():
    if not (EXPORTS.exists() and CSV.exists()):
        print("  (skipping librarian prompt test — fixtures not present)")
        return
    from reader_companion.librarian import Librarian
    snap = _build_sample_snapshot()
    lib = Librarian(snap)
    sp = lib.system_prompt
    check("LIBRARY CATALOG" in sp and "READER PROFILE" in sp, "prompt should have catalog+profile")
    check("LLM evals" in sp, "about-me should be in the system prompt")
    # The full-text BODY must never be in the prompt — only summaries are (it enters via the tool).
    for d in snap["docs"]:
        ft = d.get("full_text") or ""
        if len(ft) > 2000:
            mid = ft[len(ft) // 2: len(ft) // 2 + 250]
            check(mid not in sp, f"full text leaked into the system prompt for {d['title']!r}")
    # resolve by exact key
    key = snap["docs"][0]["key"]
    txt, doc = lib.read_full_text(key)
    check(doc and doc["key"] == key, "read_full_text should resolve by key")
    check("FULL TEXT" in txt, "tool output should be the full text")
    # resolve by title
    title = snap["docs"][1]["title"]
    _, doc2 = lib.read_full_text(title)
    check(doc2 and doc2["title"] == title, "read_full_text should resolve by title")
    # unknown ref
    txt3, doc3 = lib.read_full_text("nonexistent zzz qqq")
    check(doc3 is None and "No document" in txt3, "unknown ref should be reported, not crash")


def test_librarian_agentic_loop():
    """Drive the tool-calling loop with a fake OpenAI client (no network)."""
    if not (EXPORTS.exists() and CSV.exists()):
        print("  (skipping librarian loop test — fixtures not present)")
        return
    import json
    from types import SimpleNamespace
    from reader_companion.librarian import Librarian

    def fn(name, args):
        return SimpleNamespace(name=name, arguments=args)

    def tool_call(cid, name, args):
        return SimpleNamespace(id=cid, type="function", function=fn(name, args))

    def resp(content=None, tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class FakeCompletions:
        def __init__(self, script):
            self.script, self.calls = list(script), []
        def create(self, **kwargs):
            self.calls.append(kwargs)
            return self.script.pop(0)

    class FakeClient:
        def __init__(self, script):
            self.chat = SimpleNamespace(completions=FakeCompletions(script))

    snap = _build_sample_snapshot()
    lib = Librarian(snap)
    key = snap["docs"][0]["key"]
    # Turn 1: the model asks to read a document. Turn 2: it answers.
    lib._client = FakeClient([
        resp(content="", tool_calls=[tool_call("c1", "read_full_text",
                                                json.dumps({"doc_key": key}))]),
        resp(content="Start with that one, then the rest.", tool_calls=None),
    ])
    events = []
    answer = lib.ask("What should I read first?", on_event=lambda k, d: events.append((k, d)))
    check(answer == "Start with that one, then the rest.", f"unexpected answer: {answer!r}")
    roles = [m["role"] for m in lib.messages]
    check(roles == ["system", "user", "assistant", "tool", "assistant"],
          f"unexpected message roles: {roles}")
    check("FULL TEXT" in lib.messages[3]["content"], "the tool result should carry full text")
    check(lib.messages[2].get("tool_calls"), "the tool-call turn should record tool_calls")
    check(any(k == "tool" for k, _ in events), "a tool event should have fired")
    # tools are offered on the model call
    check(lib._client.chat.completions.calls[0].get("tools"), "tools should be passed to the API")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\nAll {len(tests)} tests passed ({_checks} checks).")


if __name__ == "__main__":
    main()
