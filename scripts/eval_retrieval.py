#!/usr/bin/env python3
"""
Retrieval evaluation harness — CaseTally
Measures Precision@3, Recall@5, MRR, and p95 latency across benchmark queries.

Usage:
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --backend http://localhost:3001
"""

import argparse
import json
import re
import statistics
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Benchmark dataset
# Each entry has a query + the U.S. Code title numbers that should appear
# in the top results. A result is "relevant" if its citation starts with
# an expected title number (e.g. "35 U.S.C. § 102" → title 35).
# ---------------------------------------------------------------------------
BENCHMARK: List[Dict] = [
    {
        "query": "freedom of speech First Amendment",
        "expected_titles": [42, 18, 5, 47],
        "label": "First Amendment / civil rights",
    },
    {
        "query": "patent eligibility requirements invention",
        "expected_titles": [35],
        "label": "Patents (Title 35)",
    },
    {
        "query": "bankruptcy discharge debt relief",
        "expected_titles": [11],
        "label": "Bankruptcy (Title 11)",
    },
    {
        "query": "copyright infringement damages reproduction",
        "expected_titles": [17],
        "label": "Copyrights (Title 17)",
    },
    {
        "query": "federal income tax rates brackets",
        "expected_titles": [26],
        "label": "Internal Revenue (Title 26)",
    },
    {
        "query": "wire fraud criminal penalties",
        "expected_titles": [18],
        "label": "Crimes (Title 18)",
    },
    {
        "query": "immigration visa requirements alien",
        "expected_titles": [8],
        "label": "Immigration (Title 8)",
    },
    {
        "query": "antitrust monopoly Sherman Act competition",
        "expected_titles": [15],
        "label": "Commerce / Antitrust (Title 15)",
    },
    {
        "query": "social security disability benefits",
        "expected_titles": [42],
        "label": "Social Security (Title 42)",
    },
    {
        "query": "employment discrimination race gender",
        "expected_titles": [42, 29, 5],
        "label": "Employment discrimination (Title 42/29/5)",
    },
    {
        "query": "controlled substances drug scheduling",
        "expected_titles": [21],
        "label": "Controlled substances (Title 21)",
    },
    {
        "query": "firearms background check purchase",
        "expected_titles": [18, 26],
        "label": "Firearms (Title 18/26)",
    },
    {
        "query": "minimum wage overtime Fair Labor Standards",
        "expected_titles": [29, 5],
        "label": "Labor / minimum wage (Title 29/5)",
    },
    {
        "query": "clean water act pollution discharge permit",
        "expected_titles": [33],
        "label": "Clean Water Act (Title 33)",
    },
    {
        "query": "habeas corpus wrongful imprisonment",
        "expected_titles": [28, 18],
        "label": "Habeas corpus (Title 28)",
    },
]


def extract_title(citation: str) -> Optional[int]:
    """Extract U.S. Code title number from citation like '18 U.S.C. § 1343'."""
    m = re.match(r"^(\d+)\s+U\.S\.C\.", citation)
    return int(m.group(1)) if m else None


def search(backend: str, query: str, top_k: int) -> Tuple[List[Dict], int]:
    """POST /v1/search and return (results, took_ms)."""
    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "bm25_k": 30,
        "vector_k": 30,
        "weight_bm25": 0.5,
        "weight_vector": 0.5,
    }).encode()

    req = urllib.request.Request(
        f"{backend}/v1/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    wall_ms = int((time.perf_counter() - t0) * 1000)

    return data.get("results", []), data.get("took_ms", wall_ms)


def is_relevant(result: Dict, expected_titles: List[int]) -> bool:
    return extract_title(result.get("citation", "")) in expected_titles


def precision_at_k(results: List[Dict], expected_titles: List[int], k: int) -> float:
    top = results[:k]
    if not top:
        return 0.0
    return sum(1 for r in top if is_relevant(r, expected_titles)) / k


def recall_at_k(results: List[Dict], expected_titles: List[int], k: int) -> float:
    top = results[:k]
    found = {extract_title(r.get("citation", "")) for r in top}
    hits = len(set(expected_titles) & found)
    return hits / len(expected_titles) if expected_titles else 0.0


def reciprocal_rank(results: List[Dict], expected_titles: List[int]) -> float:
    for i, r in enumerate(results, 1):
        if is_relevant(r, expected_titles):
            return 1.0 / i
    return 0.0


def run_eval(backend: str, top_k: int) -> None:
    print(f"\nCaseTally Retrieval Evaluation")
    print(f"Backend : {backend}")
    print(f"top_k   : {top_k}")
    print("=" * 88)
    print(f"  {'Query label':<42} {'P@3':>5} {'R@5':>5} {'MRR':>5} {'ms':>6}")
    print("-" * 88)

    p3_all, r5_all, rr_all, lat_all = [], [], [], []

    for item in BENCHMARK:
        try:
            results, took_ms = search(backend, item["query"], top_k)
        except Exception as exc:
            print(f"  ERROR — {item['label']}: {exc}")
            continue

        p3 = precision_at_k(results, item["expected_titles"], 3)
        r5 = recall_at_k(results, item["expected_titles"], 5)
        rr = reciprocal_rank(results, item["expected_titles"])

        p3_all.append(p3)
        r5_all.append(r5)
        rr_all.append(rr)
        lat_all.append(took_ms)

        label = item["label"][:41]
        print(f"  {label:<42} {p3:>5.2f} {r5:>5.2f} {rr:>5.2f} {took_ms:>5}ms")

    if not p3_all:
        print("  No results — is the backend running?")
        return

    lat_sorted = sorted(lat_all)
    p50 = lat_sorted[len(lat_sorted) // 2]
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)]

    print("=" * 88)
    print(
        f"  {'MEAN':<42} {statistics.mean(p3_all):>5.2f}"
        f" {statistics.mean(r5_all):>5.2f}"
        f" {statistics.mean(rr_all):>5.2f}"
        f" {int(statistics.mean(lat_all)):>5}ms"
    )
    print(f"\n  Latency — p50: {p50}ms   p95: {p95}ms")
    print(f"  Queries run : {len(p3_all)} / {len(BENCHMARK)}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CaseTally retrieval evaluation harness")
    parser.add_argument("--backend", default="http://localhost:3001")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    run_eval(args.backend, args.top_k)
