#!/usr/bin/env python3
"""Reader Companion — agentic librarian chat over your Readwise library (PRODUCT_PLAN §8).

Chat with an entity that has read and summarised everything you saved. Every summary stays in
context; the librarian pulls an article's full text on demand when it needs more than the
summary. Ask things like:

    "In what order should I read my articles about compute governance?"
    "What's the single best thing to read tonight if I have 15 minutes?"
    "Which of my saved pieces disagree with each other on LLM evals?"

Usage:
    export OPENAI_API_KEY=sk-...
    python generate.py            # produces report.html AND library.json (the chat snapshot)
    python chat.py                # start chatting

See `python chat.py --help` for options.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from reader_companion import config
from reader_companion.librarian import Librarian
from reader_companion.snapshot import load_snapshot

# ANSI styling, but only when writing to a real terminal.
_TTY = sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if _TTY else s


def _status(text: str) -> None:
    """Transient single-line status (cleared when the answer prints)."""
    if _TTY:
        sys.stdout.write("\r\x1b[2m  " + text + "\x1b[0m\x1b[K")
        sys.stdout.flush()


def _clear_status() -> None:
    if _TTY:
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()


def _effort(value: str | None):
    if value is None:
        return "__default__"
    v = value.strip().lower()
    return None if v in ("", "none", "off") else v


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Chat with an agentic librarian over your Readwise library snapshot.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--snapshot", default=config.SNAPSHOT_PATH,
                   help="Library snapshot written by generate.py.")
    p.add_argument("--model", default=config.CHAT_MODEL, help="Chat model.")
    p.add_argument("--effort", default=None,
                   help="Reasoning effort (none/minimal/low/medium/high). Default: "
                        f"{config.CHAT_EFFORT}.")
    p.add_argument("--ask", default=None,
                   help="Ask a single question, print the answer, and exit (non-interactive).")
    return p.parse_args(argv)


def _on_event(kind: str, detail) -> None:
    if kind == "thinking":
        _status("thinking…")
    elif kind == "tool":
        _clear_status()
        print(_c("2", f"  · {detail}"))


def _print_banner(snap: dict) -> None:
    meta = snap.get("meta", {})
    title = meta.get("title", "Your Reading Library")
    print(_c("1", f"\n📚 {title} — librarian chat"))
    bits = [f"{meta.get('n_live', len(snap.get('docs', [])))} documents",
            f"{meta.get('n_clusters', 0)} themes",
            f"{meta.get('n_highlights', 0)} highlights"]
    print(_c("2", "   " + " · ".join(bits) + f" · snapshot generated {meta.get('generated', '?')}"))
    if meta.get("mock"):
        print(_c("33", "   ⚠︎ snapshot was generated with --mock: summaries are placeholders, "
                       "so answers will be poor. Re-run generate.py without --mock."))
    print(_c("2", "   Ask about what to read next, in what order, or on which topic. "
                  "Type /help for commands, /exit to quit.\n"))


def _print_help() -> None:
    print(_c("2",
             "  Commands:\n"
             "    /reset   forget the conversation (keep the library loaded)\n"
             "    /help    show this help\n"
             "    /exit    quit (also: Ctrl-D)\n"
             "  Just type a question to chat. The librarian can read an article's full text\n"
             "  on demand when a summary isn't enough."))


def _run_once(lib: Librarian, question: str) -> None:
    answer = lib.ask(question, on_event=_on_event)
    _clear_status()
    print("\n" + _c("1", "librarian ›") + " " + answer)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:  # optional .env convenience, mirroring generate.py
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. The chat needs it to call the model.",
              file=sys.stderr)
        return 2

    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        print(f"ERROR: snapshot {args.snapshot!r} not found.\n"
              f"Run the report generator first — it writes the snapshot:\n"
              f"    python generate.py --out report.html\n"
              f"(or point --snapshot at an existing one).", file=sys.stderr)
        return 2

    snap = load_snapshot(args.snapshot)
    if not snap.get("docs"):
        print(f"ERROR: snapshot {args.snapshot!r} has no documents.", file=sys.stderr)
        return 1

    lib = Librarian(snap, model=args.model, effort=_effort(args.effort))

    # Non-interactive single question.
    if args.ask:
        try:
            _run_once(lib, args.ask)
        except Exception as e:
            print(f"\n! error: {e}", file=sys.stderr)
            return 1
        return 0

    _print_banner(snap)
    while True:
        try:
            user = input(_c("1", "you › ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye 👋")
            break
        if not user:
            continue
        if not _TTY:  # piped/scripted input isn't echoed by a terminal — echo it for clean logs
            print(user)
        low = user.lower()
        if low in ("/exit", "/quit", ":q", "exit", "quit"):
            print("bye 👋")
            break
        if low == "/help":
            _print_help()
            continue
        if low == "/reset":
            lib.reset()
            print(_c("2", "  (conversation reset)"))
            continue
        try:
            _run_once(lib, user)
        except KeyboardInterrupt:
            _clear_status()
            print(_c("2", "  (interrupted)"))
            continue
        except Exception as e:
            _clear_status()
            print(f"\n! error: {e}", file=sys.stderr)
            continue
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
