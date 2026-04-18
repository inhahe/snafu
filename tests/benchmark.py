"""Snafu interpreter benchmarks.

Runs 5 benchmark programs, measures wall time for each, then profiles
fib(25) with cProfile to find the top 10 hottest functions.
"""

import sys, os, time, cProfile, pstats, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snafu

# ---------------------------------------------------------------------------
# Benchmark programs
# ---------------------------------------------------------------------------

BENCHMARKS = [
    ("fib(30) — recursive fibonacci", """
df fib(n) { if n <= 1 { n } el { fib(n-1) + fib(n-2) } }
fib(30)
"""),

    ("sum(0..100000) — large range + reduce", """
rdc(0..100000, f (a, b) -> a + b, 0)
"""),

    ("m(0..10000, `a*a`) — map over 10K elements", """
m(0..10000, f (a) -> a * a)
"""),

    ("[x*x for x in 0..10000] — comprehension", """
[x*x for x in 0..10000]
"""),

    ("nested loops — 100x100 iterations", """
s = 0
for i in 0..100 {
    for j in 0..100 {
        s = s + i * j
    }
}
s
"""),
]

PROFILE_PROGRAM = """
df fib(n) { if n <= 1 { n } el { fib(n-1) + fib(n-2) } }
fib(25)
"""


def run_benchmarks():
    print("=" * 65)
    print("  Snafu Interpreter Benchmarks")
    print("=" * 65)
    print()

    results = []
    for name, source in BENCHMARKS:
        # Suppress any stdout from the program
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            start = time.perf_counter()
            result = snafu.run(source.strip())
            elapsed = time.perf_counter() - start
        finally:
            sys.stdout = old_stdout

        results.append((name, elapsed, result))
        # Show a summary of the result (truncate long lists)
        result_str = repr(result)
        if len(result_str) > 60:
            result_str = result_str[:57] + "..."
        print(f"  {name}")
        print(f"    time:   {elapsed:.4f}s")
        print(f"    result: {result_str}")
        print()

    # Summary table
    print("-" * 65)
    print(f"  {'Benchmark':<45} {'Time':>10}")
    print("-" * 65)
    for name, elapsed, _ in results:
        print(f"  {name:<45} {elapsed:>9.4f}s")
    print("-" * 65)
    total = sum(e for _, e, _ in results)
    print(f"  {'TOTAL':<45} {total:>9.4f}s")
    print()

    return results


def profile_fib25():
    print("=" * 65)
    print("  cProfile: fib(25) — top 10 hottest functions")
    print("=" * 65)
    print()

    pr = cProfile.Profile()
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        pr.enable()
        snafu.run(PROFILE_PROGRAM.strip())
        pr.disable()
    finally:
        sys.stdout = old_stdout

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s)
    ps.sort_stats('cumulative')
    ps.print_stats(10)
    print(s.getvalue())

    # Also show by tottime
    s2 = io.StringIO()
    ps2 = pstats.Stats(pr, stream=s2)
    ps2.sort_stats('tottime')
    ps2.print_stats(10)
    print("  Sorted by tottime:")
    print(s2.getvalue())


if __name__ == '__main__':
    run_benchmarks()
    profile_fib25()
