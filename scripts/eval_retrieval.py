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
from typing import Any, Dict, List, Optional, Tuple

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
    # -----------------------------------------------------------------------
    # Employment group: colloquial phrasing, added as a regression test.
    #
    # These are written the way a person actually asks, not the way a statute is
    # written, which is the failure this group exists to catch. The federal
    # protections live in Title 42 (Title VII at 42 U.S.C. 2000e, ADA at 12112)
    # and Title 29 (ADEA at 623, FMLA at 2615, NLRA at 158).
    #
    # Expectations are title numbers rather than citations on purpose. Ingestion
    # collapses Title VII's subsections under the parent citation
    # "42 U.S.C. § 2000e", so there is no "2000e-2" citation to assert on.
    #
    # The first is the README's headline example. The other three are held out:
    # they must not be used to tune the rewrite prompt, or this group stops
    # measuring generalisation and starts measuring overfitting.
    # -----------------------------------------------------------------------
    {
        "query": "can my boss fire me",
        "expected_titles": [42, 29],
        "label": "Wrongful termination (headline)",
        "group": "employment",
    },
    {
        "query": "can I be fired for my age",
        "expected_titles": [42, 29],
        "label": "Age discrimination (held out)",
        "group": "employment",
    },
    {
        "query": "my employer fired me for being pregnant",
        "expected_titles": [42, 29],
        "label": "Pregnancy discrimination (held out)",
        "group": "employment",
    },
    {
        "query": "can I get fired for joining a union",
        "expected_titles": [42, 29],
        "label": "Union retaliation (held out)",
        "group": "employment",
    },
]


def extract_title(citation: str) -> Optional[int]:
    """Extract U.S. Code title number from citation like '18 U.S.C. § 1343'."""
    m = re.match(r"^(\d+)\s+U\.S\.C\.", citation)
    return int(m.group(1)) if m else None


def rewrite_query(backend: str, query: str) -> str:
    """POST /v1/rewrite and return the rewritten query string."""
    payload = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        f"{backend}/v1/rewrite",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("rewritten", query)
    except Exception:
        return query


def search(backend: str, query: str, top_k: int) -> Tuple[List[Dict], int]:
    """POST /v1/search and return (results, took_ms)."""
    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "bm25_k": 50,
        "vector_k": 50,
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


def run_eval(backend: str, top_k: int, use_rewrite: bool = False, sleep_s: float = 0.0) -> None:
    print("\nCaseTally Retrieval Evaluation")
    print(f"Backend : {backend}")
    print(f"top_k   : {top_k}")
    print(f"rewrite : {'on' if use_rewrite else 'off'}")
    print("=" * 88)
    print(f"  {'Query label':<42} {'P@3':>5} {'R@5':>5} {'MRR':>5} {'ms':>6}")
    print("-" * 88)

    p3_all, r5_all, rr_all, lat_all = [], [], [], []
    # Per-group tallies. The "core" 15 are reported separately from any group
    # added later, so adding queries cannot silently move the headline numbers
    # this project quotes and make a regression look like an improvement.
    groups: Dict[str, Dict[str, List[float]]] = {}
    current_group = None

    for item in BENCHMARK:
        group = item.get("group", "core")
        if group != current_group:
            if current_group is not None:
                print("-" * 88)
            current_group = group
        try:
            query = item["query"]
            if use_rewrite:
                query = rewrite_query(backend, query)
            results, took_ms = search(backend, query, top_k)
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

        g = groups.setdefault(group, {"p3": [], "r5": [], "rr": [], "lat": []})
        g["p3"].append(p3)
        g["r5"].append(r5)
        g["rr"].append(rr)
        g["lat"].append(took_ms)

        label = item["label"][:41]
        print(f"  {label:<42} {p3:>5.2f} {r5:>5.2f} {rr:>5.2f} {took_ms:>5}ms")

        # Default 0.0, so the documented plain and rewrite invocations behave
        # exactly as before. Only needed when rewriting, where 19 back-to-back
        # LLM calls can cross the per-minute token limit.
        if sleep_s:
            time.sleep(sleep_s)

    if not p3_all:
        print("  No results — is the backend running?")
        return

    lat_sorted = sorted(lat_all)
    p50 = lat_sorted[len(lat_sorted) // 2]
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)]

    print("=" * 88)
    for name, g in groups.items():
        print(
            f"  {'MEAN (' + name + ', n=' + str(len(g['p3'])) + ')':<42}"
            f" {statistics.mean(g['p3']):>5.2f}"
            f" {statistics.mean(g['r5']):>5.2f}"
            f" {statistics.mean(g['rr']):>5.2f}"
            f" {int(statistics.mean(g['lat'])):>5}ms"
        )
    if len(groups) > 1:
        print(
            f"  {'MEAN (all, n=' + str(len(p3_all)) + ')':<42}"
            f" {statistics.mean(p3_all):>5.2f}"
            f" {statistics.mean(r5_all):>5.2f}"
            f" {statistics.mean(rr_all):>5.2f}"
            f" {int(statistics.mean(lat_all)):>5}ms"
        )
    print(f"\n  Latency — p50: {p50}ms   p95: {p95}ms")
    print(f"  Queries run : {len(p3_all)} / {len(BENCHMARK)}")
    print()


# ---------------------------------------------------------------------------
# Decomposition mode
#
# The plain and rewrite modes above go over HTTP to /v1/search, which is a
# single-query endpoint. The answer path does not use it: it decomposes the
# question into 3 or 4 sub-queries, searches each one, fuses the rankings, and
# then selects the chunks the model sees. No endpoint exposes that without also
# generating an answer, and generating answers would burn tokens this
# measurement does not need, so this mode imports the services and calls them
# directly. It must therefore run where `app` is importable, i.e. in the API
# pod.
#
# Nothing here reimplements retrieval or selection. decompose_query,
# search_multi and _select_context are the production functions, called with
# the production arguments, so what is scored is what users get.
# ---------------------------------------------------------------------------


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


def context_title_coverage(chunks: List[Dict], expected_titles: List[int]) -> Tuple[int, int]:
    """How many of the expected titles appear in the chunks sent to the model.

    This is the question the per-query ranking metrics cannot answer: the model
    can only cite a statute it was actually given, so coverage of the selected
    context is the ceiling on what any answer can get right.
    """
    found = {extract_title(c.get("citation", "")) for c in chunks}
    hits = len(set(expected_titles) & found)
    return hits, len(expected_titles)


def run_decompose_eval(
    top_k: int,
    runs: int,
    sleep_s: float,
    json_out: Optional[str],
) -> None:
    from app.db import SessionLocal
    from app.dependencies import groq_service, search_service
    from app.routers.chat import (
        ANSWER_TOP_K,
        CANDIDATE_K,
        MAX_CHUNKS_PER_CITATION,
        _select_context,
    )

    print("\nCaseTally Retrieval Evaluation — decomposition mode")
    print(f"top_k scored     : {top_k} (same slice the other modes score)")
    print(f"candidate pool   : {CANDIDATE_K}   context sent: {ANSWER_TOP_K}")
    print(f"runs             : {runs}   sleep between Groq calls: {sleep_s}s")
    print("=" * 96)

    records: List[Dict[str, Any]] = []

    for run_i in range(1, runs + 1):
        print(f"\n--- run {run_i} of {runs} ---")
        print(f"  {'Query label':<42} {'P@3':>5} {'R@5':>5} {'MRR':>5} {'ctx':>6} {'ms':>7}")
        print("-" * 96)

        for item in BENCHMARK:
            query = item["query"]
            expected = item["expected_titles"]
            group = item.get("group", "core")

            try:
                decomposed = groq_service.decompose_query(query)
            except Exception as exc:
                if _is_rate_limit(exc):
                    print(f"\n  ABORT: Groq rate limit hit on {query!r}: {exc}")
                    if json_out and records:
                        with open(json_out, "w") as fh:
                            json.dump(records, fh)
                        print(f"  partial results written to {json_out}")
                    raise SystemExit(2)
                print(f"  ERROR decompose {item['label']}: {exc}")
                continue

            if not decomposed:
                # Production would fall back to a single rewrite here. Record it
                # rather than silently scoring a different path.
                print(f"  SKIP (decompose empty) {item['label']}")
                records.append({
                    "run": run_i, "group": group, "label": item["label"],
                    "query": query, "decompose_empty": True,
                })
                continue

            t0 = time.perf_counter()
            results = search_service.search_multi(
                session_factory=SessionLocal,
                queries=[d["query"] for d in decomposed],
                labels=[d["issue"] for d in decomposed],
                top_k=CANDIDATE_K,
                bm25_k=50,
                vector_k=50,
                weight_bm25=0.5,
                weight_vector=0.5,
            )
            search_ms = int((time.perf_counter() - t0) * 1000)

            # Scored on the same slice the HTTP modes score, so the columns are
            # comparable: /v1/search is called with top_k=5 there, and the fused
            # ordering here is identical whether it is cut at 5 or at 30.
            fused = results.get("results", [])[:top_k]
            p3 = precision_at_k(fused, expected, 3)
            r5 = recall_at_k(fused, expected, 5)
            rr = reciprocal_rank(fused, expected)

            chunks = _select_context(
                results, ANSWER_TOP_K, MAX_CHUNKS_PER_CITATION, query=query
            )
            ctx_hits, ctx_total = context_title_coverage(chunks, expected)

            records.append({
                "run": run_i,
                "group": group,
                "label": item["label"],
                "query": query,
                "expected_titles": expected,
                "sub_queries": [d["query"] for d in decomposed],
                "issues": [d["issue"] for d in decomposed],
                "p3": p3, "r5": r5, "rr": rr,
                "ctx_hits": ctx_hits, "ctx_total": ctx_total,
                "ctx_citations": [c.get("citation") for c in chunks],
                "fused_citations": [c.get("citation") for c in fused],
                "search_ms": search_ms,
                "n_sub_errors": len(results.get("errors") or []),
            })

            print(f"  {item['label'][:41]:<42} {p3:>5.2f} {r5:>5.2f} {rr:>5.2f}"
                  f" {str(ctx_hits) + '/' + str(ctx_total):>6} {search_ms:>6}ms")

            # Paced because the decompose call is the only Groq spend here and
            # the account's limit is per-minute tokens, not per-request.
            time.sleep(sleep_s)

    if json_out:
        with open(json_out, "w") as fh:
            json.dump(records, fh)
        print(f"\n  raw records written to {json_out}")

    scored = [r for r in records if "p3" in r]
    if not scored:
        print("\n  nothing scored")
        return

    print("\n" + "=" * 96)
    for group in ("core", "employment"):
        rows = [r for r in scored if r["group"] == group]
        if not rows:
            continue
        n_q = len({r["label"] for r in rows})
        print(f"\n  {group} group, {n_q} queries x {runs} runs = {len(rows)} observations")
        for metric in ("p3", "r5", "rr"):
            vals = [r[metric] for r in rows]
            # Spread across runs is reported on the per-run means, because that
            # is the number that would be quoted; per-query variance is noise.
            per_run = [
                statistics.mean([r[metric] for r in rows if r["run"] == i])
                for i in range(1, runs + 1)
                if any(r["run"] == i for r in rows)
            ]
            print(f"    {metric:<4} mean {statistics.mean(vals):.3f}"
                  f"   per-run means {[round(v, 3) for v in per_run]}"
                  f"   spread {max(per_run) - min(per_run):.3f}")
        ctx_h = sum(r["ctx_hits"] for r in rows)
        ctx_t = sum(r["ctx_total"] for r in rows)
        full = sum(1 for r in rows if r["ctx_hits"] == r["ctx_total"])
        none = sum(1 for r in rows if r["ctx_hits"] == 0)
        print(f"    context: {ctx_h}/{ctx_t} expected titles present"
              f" ({ctx_h / ctx_t:.3f})"
              f"   all titles: {full}/{len(rows)}   no titles: {none}/{len(rows)}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CaseTally retrieval evaluation harness")
    parser.add_argument("--backend", default="http://localhost:3001")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rewrite", action="store_true", help="Rewrite queries via LLM before retrieval")
    parser.add_argument(
        "--mode",
        choices=["plain", "rewrite", "decompose"],
        default=None,
        help="plain and rewrite go over HTTP to /v1/search; decompose runs the "
             "answer path's retrieval in-process and must run where app is importable",
    )
    parser.add_argument("--runs", type=int, default=1, help="repeat the sweep, for decompose mode")
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="seconds between Groq calls. Defaults to 7.5 for decompose, which "
             "needs pacing to stay under the per-minute token limit, and to 0 "
             "for rewrite, so the documented invocation is unchanged",
    )
    parser.add_argument("--json-out", default=None, help="write raw per-query records here")
    args = parser.parse_args()

    mode = args.mode or ("rewrite" if args.rewrite else "plain")
    if mode == "decompose":
        run_decompose_eval(
            args.top_k, args.runs, 7.5 if args.sleep is None else args.sleep, args.json_out
        )
    else:
        run_eval(
            args.backend,
            args.top_k,
            use_rewrite=(mode == "rewrite"),
            sleep_s=0.0 if args.sleep is None else args.sleep,
        )
