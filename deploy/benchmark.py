"""Measure latency against the deployed API, reproducibly.

The README publishes latency percentiles. A published number that a reader cannot
reproduce is exactly the kind of claim this project exists to argue against, so
the measurement lives here rather than in a shell history.

Two things this script makes explicit, because both change the numbers by more
than the numbers themselves:

**Cold start.** The first request after an idle period pulls an ~800 MB container
image and opens a fresh TLS connection to CockroachDB Cloud. It costs seconds, not
milliseconds, and a single cold sample in a 20-request run moves p95 by 3-4x. The
default is therefore to warm the function and report **warm** figures, with the
cold sample reported separately rather than blended in — blending produces a p95
that describes the container runtime, not the application.

**Network position.** These are end-to-end client-observed times, so they include
the round trip from wherever the script runs to eu-central-1. Measured from a
different continent the same deployment reads 30-40 ms slower. The number is only
meaningful alongside where it was taken from.

Usage::

    python deploy/benchmark.py                     # warm, n=40, sequential
    python deploy/benchmark.py --n 100 --concurrency 8
    python deploy/benchmark.py --endpoint /api/v1/metrics
    python deploy/benchmark.py --include-cold      # report the cold sample too
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BASE = "https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com"
DEFAULT_ENDPOINT = "/api/v1/health"

#: Requests discarded before measuring, to take container cold start out of the
#: sample. Three is enough to cover the image pull plus TLS handshake.
WARMUP_REQUESTS = 3


def _timed_get(url: str, timeout: float) -> tuple[float, int | None]:
    """Return (elapsed_ms, status). ``status`` is None on transport failure."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            return (time.perf_counter() - started) * 1000.0, response.status
    except urllib.error.HTTPError as exc:
        return (time.perf_counter() - started) * 1000.0, exc.code
    except Exception:
        return (time.perf_counter() - started) * 1000.0, None


def percentile(sorted_samples: list[float], p: float) -> float:
    """Nearest-rank percentile. Explicit because implementations disagree."""
    if not sorted_samples:
        return float("nan")
    index = min(len(sorted_samples) - 1, int(len(sorted_samples) * p / 100.0))
    return sorted_samples[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--include-cold",
        action="store_true",
        help="skip warmup and report the first (cold) sample separately",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="sweep concurrency across [1, 2, 4, 8, 16, 32] and output load curve",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args()

    url = args.base.rstrip("/") + args.endpoint

    if args.sweep:
        concurrencies = [1, 2, 4, 8, 16, 32]
        curve_results = []
        print(f"Sweeping load curves across concurrency levels {concurrencies} against {url}...")
        for c in concurrencies:
            with ThreadPoolExecutor(max_workers=c) as pool:
                res = list(pool.map(lambda _: _timed_get(url, args.timeout), range(args.n)))
            ok_s = sorted(ms for ms, status in res if status == 200)
            if ok_s:
                curve_results.append({
                    "concurrency": c,
                    "samples": len(ok_s),
                    "failures": sum(1 for _, st in res if st != 200),
                    "p50_ms": round(percentile(ok_s, 50), 1),
                    "p95_ms": round(percentile(ok_s, 95), 1),
                    "p99_ms": round(percentile(ok_s, 99), 1),
                    "mean_ms": round(statistics.fmean(ok_s), 1),
                })

        if args.json:
            print(json.dumps({"url": url, "curve": curve_results}, indent=2))
            return 0

        print("\n| Concurrency | Samples | Failures | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |")
        print("|---|---|---|---|---|---|---|")
        for r in curve_results:
            print(f"| {r['concurrency']:11d} | {r['samples']:7d} | {r['failures']:8d} | {r['p50_ms']:8.1f} | {r['p95_ms']:8.1f} | {r['p99_ms']:8.1f} | {r['mean_ms']:9.1f} |")
        return 0

    cold_ms: float | None = None
    if args.include_cold:
        cold_ms, cold_status = _timed_get(url, args.timeout)
        if cold_status != 200:
            print(f"cold request failed: status={cold_status}", file=sys.stderr)
    else:
        for _ in range(WARMUP_REQUESTS):
            _timed_get(url, args.timeout)

    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(
                pool.map(lambda _: _timed_get(url, args.timeout), range(args.n))
            )
    else:
        results = [_timed_get(url, args.timeout) for _ in range(args.n)]

    ok = sorted(ms for ms, status in results if status == 200)
    failures = [status for _, status in results if status != 200]

    if not ok:
        print("every request failed", file=sys.stderr)
        return 1

    report = {
        "url": url,
        "samples": len(ok),
        "failures": len(failures),
        "concurrency": args.concurrency,
        "warm": not args.include_cold,
        "min_ms": round(ok[0], 1),
        "p50_ms": round(percentile(ok, 50), 1),
        "p90_ms": round(percentile(ok, 90), 1),
        "p95_ms": round(percentile(ok, 95), 1),
        "p99_ms": round(percentile(ok, 99), 1),
        "max_ms": round(ok[-1], 1),
        "mean_ms": round(statistics.fmean(ok), 1),
    }
    if cold_ms is not None:
        # Reported beside the warm figures, never inside them.
        report["cold_start_ms"] = round(cold_ms, 1)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"{url}")
    print(
        f"n={report['samples']}  concurrency={args.concurrency}  "
        f"{'warm' if report['warm'] else 'includes cold'}  failures={report['failures']}"
    )
    for key in ("min_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms"):
        print(f"  {key.replace('_ms', '').rjust(4)}  {report[key]:8.1f} ms")
    if cold_ms is not None:
        print(f"  cold  {cold_ms:8.1f} ms   (reported separately, not in percentiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
