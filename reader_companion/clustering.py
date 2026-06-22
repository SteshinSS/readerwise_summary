"""F4 — clustering: group documents on their embeddings (numpy-only KMeans), then name
each cluster with the LLM. Clustering is core: it gives every Layer-3 summary its peer set
and structures the report (PRODUCT_PLAN §5.1)."""

from __future__ import annotations

import math

import numpy as np

from . import config
from . import textutils as T
from .llm import Provider
from .models import Cluster, Document
from .schemas import ClusterName

SYSTEM = (
    "You name thematic clusters of documents for a personal reading library. Names are short, "
    "specific, and human — never generic like 'Misc' or 'Articles'. Follow the schema."
)


# --------------------------------------------------------------------------------------
# numpy KMeans (cosine ≈ euclidean on L2-normalised vectors)
# --------------------------------------------------------------------------------------
def _normalize(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return X / norms


def _dist2(X: np.ndarray, C: np.ndarray) -> np.ndarray:
    """Squared euclidean distances, n×k, via the ||x-c||² identity (no big broadcast)."""
    xn = (X * X).sum(1)[:, None]
    cn = (C * C).sum(1)[None, :]
    return np.maximum(xn + cn - 2.0 * (X @ C.T), 0.0)


def _kpp_init(X: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n = X.shape[0]
    centers = np.empty((k, X.shape[1]), dtype=X.dtype)
    centers[0] = X[rng.integers(n)]
    d2 = ((X - centers[0]) ** 2).sum(1)
    for c in range(1, k):
        total = d2.sum()
        probs = d2 / total if total > 0 else np.full(n, 1.0 / n)
        centers[c] = X[rng.choice(n, p=probs)]
        d2 = np.minimum(d2, ((X - centers[c]) ** 2).sum(1))
    return centers


def _kmeans_once(X, k, rng, max_iter):
    centers = _kpp_init(X, k, rng)
    labels = np.full(X.shape[0], -1)
    for _ in range(max_iter):
        d = _dist2(X, centers)
        new = d.argmin(1)
        if np.array_equal(new, labels):
            break
        labels = new
        for c in range(k):
            mask = labels == c
            if mask.any():
                centers[c] = X[mask].mean(0)
            else:  # reseed an empty cluster to the worst-served point
                centers[c] = X[d.min(1).argmax()]
    inertia = float(_dist2(X, centers)[np.arange(len(labels)), labels].sum())
    return labels, inertia


def kmeans(X, k, seed, restarts, max_iter):
    best_labels, best_inertia = None, math.inf
    for r in range(restarts):
        rng = np.random.default_rng(seed + r)
        labels, inertia = _kmeans_once(X, k, rng, max_iter)
        if inertia < best_inertia:
            best_labels, best_inertia = labels, inertia
    return best_labels


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    uniq = np.unique(labels)
    n = len(labels)
    if len(uniq) < 2:
        return -1.0
    g = X @ X.T
    sq = np.clip(np.diag(g), 0, None)
    D = np.sqrt(np.maximum(sq[:, None] + sq[None, :] - 2 * g, 0.0))
    scores = np.zeros(n)
    for i in range(n):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            # Singleton cluster: by definition silhouette is 0, not 1. Skipping this is
            # what prevents the score from rewarding lots of one-document clusters.
            scores[i] = 0.0
            continue
        a = D[i, same].mean()
        b = math.inf
        for c in uniq:
            if c == labels[i]:
                continue
            mask = labels == c
            if mask.any():
                b = min(b, D[i, mask].mean())
        m = max(a, b)
        scores[i] = 0.0 if m == 0 else (b - a) / m
    return float(scores.mean())


def choose_k(X: np.ndarray, seed: int) -> int:
    n = len(X)
    if n <= 2:
        return 1
    if n == 3:
        return 2
    if n > 1200:  # avoid O(n²) silhouette on very large libraries
        return int(max(2, min(config.MAX_CLUSTERS, round(math.sqrt(n / 2)))))
    # Keep at least ~2 documents per cluster on average so peers exist for Layer 3.
    upper = min(config.MAX_CLUSTERS, max(2, n // 2))
    best_k, best_s = 1, -2.0
    for k in range(2, upper + 1):
        labels = kmeans(X, k, seed, max(1, config.KMEANS_RESTARTS // 2), config.KMEANS_MAX_ITER)
        s = _silhouette(X, labels)
        if s > best_s:
            best_s, best_k = s, k
    return best_k


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def _name_cluster(members: list[Document], provider: Provider, model: str) -> ClusterName:
    mo, mc = config.M_MEMBERS
    lines = []
    for d in members[:30]:
        summ = d.summary.summary if d.summary else ""
        lines.append(f"- {d.title}: {T.truncate(summ, 240)}")
    user = (
        "These documents were grouped together by an embedding model. Give the group a short, "
        "specific theme name (2-5 words) and a one-sentence description of what ties them "
        f"together.\n\n{mo}\n" + "\n".join(lines) + f"\n{mc}"
    )
    return provider.structured(
        kind="cluster", model=model, system=SYSTEM, user=user, schema=ClusterName, effort=None,
    )


def cluster_documents(docs: list[Document], provider: Provider, *, n_clusters: int | None,
                      seed: int = config.RANDOM_SEED, name_model: str | None = None,
                      verbose: bool = True) -> list[Cluster]:
    # Cluster naming is cheap and low-stakes; default to the Layer-1 model.
    name_model = name_model or config.LAYER1_MODEL
    targets = [d for d in docs if d.embedding]
    if not targets:
        return []

    X = _normalize(np.asarray([d.embedding for d in targets], dtype=float))
    n = len(targets)

    if n == 1:
        labels = np.array([0])
    else:
        k = n_clusters if n_clusters else choose_k(X, seed)
        k = max(1, min(k, n))
        labels = np.zeros(n, dtype=int) if k == 1 else kmeans(
            X, k, seed, config.KMEANS_RESTARTS, config.KMEANS_MAX_ITER)

    for doc, lab in zip(targets, labels):
        doc.cluster_id = int(lab)

    if verbose:
        print(f"Clustering · {n} documents → {len(set(int(l) for l in labels))} clusters")

    clusters: list[Cluster] = []
    for cid in sorted({int(l) for l in labels}):
        members = [d for d in targets if d.cluster_id == cid]
        try:
            named = _name_cluster(members, provider, name_model)
            name, desc = named.name.strip(), named.description.strip()
        except Exception as e:
            name, desc = f"Cluster {cid + 1}", f"(naming failed: {e})"
        clusters.append(Cluster(id=cid, name=name, description=desc,
                                doc_keys=[m.key for m in members]))
    return clusters
