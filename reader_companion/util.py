"""Shared helpers: concurrent map with a progress indicator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def map_concurrent(fn: Callable[[T], None], items: Iterable[T], workers: int,
                   desc: str, verbose: bool = True) -> None:
    """Run ``fn`` over ``items`` (IO-bound) with a progress indicator.

    ``fn`` is expected to handle its own errors (e.g. record them on the item); this helper
    only parallelises and reports progress. Results are not collected.
    """
    items = list(items)
    total = len(items)
    if total == 0:
        return

    bar = None
    if verbose:
        try:
            from tqdm import tqdm
            bar = tqdm(total=total, desc=desc, unit="doc")
        except Exception:
            bar = None
            print(f"{desc}: 0/{total}", end="", flush=True)

    done = 0

    def tick():
        nonlocal done
        done += 1
        if bar is not None:
            bar.update(1)
        elif verbose:
            print(f"\r{desc}: {done}/{total}", end="", flush=True)

    if workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for _ in ex.map(fn, items):
                tick()
    else:
        for it in items:
            fn(it)
            tick()

    if bar is not None:
        bar.close()
    elif verbose:
        print()
