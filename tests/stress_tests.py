"""
Snafu interpreter stress tests.

Standalone test runner (not part of the unit test suite) that exercises
edge cases and extreme inputs.  Each test runs in a subprocess with a
10-second timeout.

Usage:
    python tests/stress_tests.py
"""

import sys, os, subprocess, time, textwrap

TIMEOUT = 10

# The child-process script template.  The runner writes the source and
# check expression into a small self-contained Python script, runs it
# via subprocess, and inspects the exit code + stdout.
_CHILD_TEMPLATE = textwrap.dedent(r'''
import sys, os, io, traceback
sys.path.insert(0, {repo_root!r})
sys.setrecursionlimit(5000)
import snafu

source = {source!r}
check_expr = {check_expr!r}

old_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    result = snafu.run(source, filename="<stress>")
finally:
    sys.stdout = old_stdout

if check_expr is not None:
    ok = eval(check_expr, {{"result": result, "snafu": snafu}})
    if not ok:
        print("CHECK_FAILED: " + repr(result), file=sys.stderr)
        sys.exit(1)

print("OK")
''')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_test(name, source, check_expr=None):
    """Run *source* in a subprocess with a TIMEOUT-second deadline.

    *check_expr* is a Python expression string evaluated in the child
    with ``result`` bound to the evaluation result.  It must yield True
    for the test to pass.  If None, the test passes as long as evaluation
    doesn't crash.

    Returns (name, status, detail) where status is PASS/FAIL/TIMEOUT.
    """
    script = _CHILD_TEMPLATE.format(
        repo_root=REPO_ROOT,
        source=source,
        check_expr=check_expr,
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if proc.returncode == 0 and "OK" in proc.stdout:
            return (name, "PASS", "ok")
        detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        return (name, "FAIL", detail)
    except subprocess.TimeoutExpired:
        return (name, "TIMEOUT", f"exceeded {TIMEOUT}s")
    except Exception as e:
        return (name, "FAIL", f"runner error: {e}")


# ============================================================================
#  TEST DEFINITIONS
# ============================================================================

TESTS = []


def stress(name, source, check_expr=None):
    """Register a stress test.

    *check_expr* is a Python expression string evaluated with ``result``
    (the Snafu evaluation result) and ``snafu`` (the module) in scope.
    """
    TESTS.append((name, source, check_expr))


# ---------------------------------------------------------------------------
# 1. Deep recursion (implicit TCO)
# ---------------------------------------------------------------------------

stress(
    "deep_recursion_countdown",
    "df cd(n) { if n <= 0 { 0 } el { cd(n - 1) } }; cd(50000)",
    "result == 0",
)

stress(
    "deep_recursion_huge_factorial",
    "df fact(n, a=1) { if n <= 1 { a } el { fact(n - 1, n * a) } }; fact(10000) > 0",
    "result is True",
)

# Mutual recursion lacks implicit TCO -- test at a depth within Python
# stack limits (sys.setrecursionlimit(5000) in the child, ~8 frames per
# mutual call pair, so 200 is safe).
stress(
    "deep_mutual_recursion",
    "df is_even(n) { if n == 0 { true } el { is_odd(n - 1) } }\n"
    "df is_odd(n) { if n == 0 { false } el { is_even(n - 1) } }\n"
    "is_even(200)",
    "result is True",
)

# ---------------------------------------------------------------------------
# 2. Concurrent stress
# ---------------------------------------------------------------------------

stress(
    "concurrent_atom_increment",
    "counter = atom(0)\n"
    "futures = []\n"
    "for i in 0..20 {\n"
    "    futures = futures + [gt { lp 100 { counter.swap(`a + 1`) } }]\n"
    "}\n"
    "for f in futures { aw f }\n"
    "counter.get()",
    "result == 2000",
)

stress(
    "concurrent_producers_consumers",
    "c = ch(100)\n"
    "results = atom([])\n"
    "producers = []\n"
    "for i in 0..10 {\n"
    "    producers = producers + [gt {\n"
    "        for j in 0..100 { c.send(i * 100 + j) }\n"
    "    }]\n"
    "}\n"
    "consumers = []\n"
    "for i in 0..10 {\n"
    "    consumers = consumers + [gt {\n"
    "        for j in 0..100 {\n"
    "            v = c.recv()\n"
    "            results.swap(`a + [v]`)\n"
    "        }\n"
    "    }]\n"
    "}\n"
    "for f in producers { aw f }\n"
    "for f in consumers { aw f }\n"
    "len(results.get())",
    "result == 1000",
)

# ---------------------------------------------------------------------------
# 3. Fork stress
# ---------------------------------------------------------------------------

stress(
    "nested_forks_3_levels",
    "f1 = fk {\n"
    "    f2 = fk {\n"
    "        f3 = fk { 42 }\n"
    "        aw f3\n"
    "    }\n"
    "    aw f2\n"
    "}\n"
    "aw f1",
    "result == 42",
)

stress(
    "fk_map_20_parallel",
    "items = lst(0..20)\n"
    "futures = fk_map(items, `a * a`)\n"
    "results = []\n"
    "for f in futures {\n"
    "    results = results + [aw f]\n"
    "}\n"
    "results",
    "isinstance(result, list) and len(result) == 20 and result[0] == 0 and result[4] == 16",
)

# ---------------------------------------------------------------------------
# 4. Large collections
# ---------------------------------------------------------------------------

stress(
    "pipeline_100k_elements",
    "lst(0..100000).m(`a * 2`).fl(`a % 3 == 0`).take(10)",
    "isinstance(result, list) and len(result) == 10 and result[0] == 0 and result[1] == 6",
)

stress(
    "apl_reduce_10k",
    "+/ lst(0..10000)",
    "result == 49995000",
)

stress(
    "large_list_sort",
    "data = lst(0..10000).rev()\n"
    "sorted_data = data.srt()\n"
    "sorted_data[0] == 0 && sorted_data[9999] == 9999",
    "result is True",
)

# ---------------------------------------------------------------------------
# 5. Scope chain depth
# ---------------------------------------------------------------------------

# The recursive-descent parser hits Python's stack limit around 100+ nested
# blocks.  Test with 50 levels (raised sys.setrecursionlimit in child).
stress(
    "scope_chain_depth_50",
    "xx = 0; " + "{ " * 50 + "xx = 42; xx" + " }" * 50,
    "result == 42",
)

stress(
    "scope_chain_depth_200",
    "xx = 0; " + "{ " * 200 + "xx = 42; xx" + " }" * 200,
    "result == 42",
)

# ---------------------------------------------------------------------------
# 6. Regex edge cases
# ---------------------------------------------------------------------------

# Snafu regex literals use the r/pattern/flags syntax.

stress(
    "regex_empty_pattern_empty_string",
    'rx = r/(?:)/\n'
    'mat = rx.ma("")\n'
    'type(mat) == "Obj"',
    "result is True",
)

stress(
    "regex_unicode_pattern",
    'rx = r/\\w+/\n'
    'result = rx.al("hello world cafe")\n'
    'len(result) == 3',
    "result is True",
)

stress(
    "regex_many_matches",
    'text = "a" * 10000\n'
    'rx = r/a/\n'
    'matches = rx.al(text)\n'
    'len(matches) == 10000',
    "result is True",
)

# ---------------------------------------------------------------------------
# 7. Self-modification
# ---------------------------------------------------------------------------

stress(
    "ast_of_and_eval_ast",
    "node = ast_of(1 + 2)\n"
    "result = eval_ast(node)\n"
    "result",
    "result == 3",
)

stress(
    "isrc_modify_meta_interp",
    'isrc[1] = "f(node, scope) -> eval_ast(node)"\n'
    'ev("1 + 2")',
    "result == 3",
)

# ---------------------------------------------------------------------------
# 8. Effect handler nesting
# ---------------------------------------------------------------------------

# When a handler body completes normally and a handler case is a plain
# PatVar (no continuation), it receives the body's return value.
# Inner: pf 10 caught by x -> x+1 = 11
# Middle: body returns 11, caught by return handler x -> x*2 = 22
# Outer: body returns 22, caught by return handler x -> x+100 = 122
stress(
    "effect_handler_3_levels",
    "hd {\n"
    "    hd {\n"
    "        hd {\n"
    "            pf 10\n"
    "        } with {\n"
    "            x -> x + 1\n"
    "        }\n"
    "    } with {\n"
    "        x -> x * 2\n"
    "    }\n"
    "} with {\n"
    "    x -> x + 100\n"
    "}",
    "result == 122",
)

stress(
    "effect_handler_with_continuation",
    'hd {\n'
    '    x = pf "hello"\n'
    '    x + " world"\n'
    '} with {\n'
    '    msg k -> k(msg + "!")\n'
    '}',
    'result == "hello! world"',
)

stress(
    "effect_handler_multi_shot",
    "hd {\n"
    "    x = pf 5\n"
    "    x * 10\n"
    "} with {\n"
    "    n k -> k(n) + k(n + 1)\n"
    "}",
    "result == 110",
)

# ---------------------------------------------------------------------------
# 9. Reactive cascade
# ---------------------------------------------------------------------------

# Variable names must not be Snafu keywords (y is keyword for yield).
# Cascading triggers: changing xx fires yy trigger, changing yy fires zz trigger.
stress(
    "reactive_cascade_3_vars",
    "xx = 0\n"
    "yy = 0\n"
    "zz = 0\n"
    "on yy.ch { zz = yy + 10 }\n"
    "on xx.ch { yy = xx + 1 }\n"
    "xx = 5\n"
    "[xx, yy, zz]",
    "isinstance(result, list) and result[0] == 5 and result[1] == 6 and result[2] == 16",
)

stress(
    "reactive_multiple_triggers",
    "counter = 0\n"
    "val = 0\n"
    "on val.ch { counter = counter + 1 }\n"
    "for i in 1..6 { val = i }\n"
    "counter",
    "result == 5",
)

# ---------------------------------------------------------------------------
# 10. Pattern matching stress
# ---------------------------------------------------------------------------

_words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_arms = ", ".join(f'{i} -> "{_words[i]}"' for i in range(20))

stress(
    "match_20_arms",
    f'v = 17; mt v {{ {_arms}, _ -> "other" }}',
    'result == "seventeen"',
)

stress(
    "match_deeply_nested_list_pattern",
    "data = [[[42]]]\n"
    "mt data {\n"
    "    [[[a]]] -> a * 2,\n"
    "    _ -> 0\n"
    "}",
    "result == 84",
)

stress(
    "match_with_guards",
    "df classify(n) {\n"
    "    mt n {\n"
    '        x if x < 0 -> "neg",\n'
    '        0 -> "zero",\n'
    '        x if x < 100 -> "small",\n'
    '        x if x < 1000 -> "medium",\n'
    '        _ -> "large"\n'
    "    }\n"
    "}\n"
    "[classify(-5), classify(0), classify(50), classify(500), classify(5000)]",
    'result == ["neg", "zero", "small", "medium", "large"]',
)

# ---------------------------------------------------------------------------
# 11. Generator stress
# ---------------------------------------------------------------------------

stress(
    "generator_10000_values",
    "ct gen(n) {\n"
    "    for i in 0..n { y i }\n"
    "}\n"
    "total = 0\n"
    "for v in gen(10000) { total = total + v }\n"
    "total",
    "result == 49995000",
)

# Generator send protocol:
#   g.sd(0) -> first yield = total (0), then sets received=0, total=0+0=0
#   g.sd(10) -> yield total (0), sets received=10, total=0+10=10
#   g.sd(20) -> yield total (10), sets received=20, total=10+20=30
#   g.sd(30) -> yield total (30), sets received=30, total=30+30=60
stress(
    "generator_with_send",
    "ct accumulator() {\n"
    "    total = 0\n"
    "    lp {\n"
    "        received = y total\n"
    "        total = total + received\n"
    "    }\n"
    "}\n"
    "g = accumulator()\n"
    "r0 = g.sd(0)\n"
    "r1 = g.sd(10)\n"
    "r2 = g.sd(20)\n"
    "r3 = g.sd(30)\n"
    "[r0, r1, r2, r3]",
    "isinstance(result, list) and result == [0, 0, 10, 30]",
)

stress(
    "generator_chained_pipeline",
    "ct squares(n) {\n"
    "    for i in 0..n { y i * i }\n"
    "}\n"
    "total = 0\n"
    "for v in squares(1000) {\n"
    "    if v % 2 == 0 { total = total + v }\n"
    "}\n"
    "total",
    "result == " + str(sum(i * i for i in range(1000) if (i * i) % 2 == 0)),
)

# ---------------------------------------------------------------------------
# 12. Operator overloading
# ---------------------------------------------------------------------------

stress(
    "operator_overload_all_dunders",
    "proto = new()\n"
    "proto.__add__ = f(self, other) -> new(proto, x=self.x + other.x, y=self.y + other.y)\n"
    "proto.__mul__ = f(self, other) -> new(proto, x=self.x * other.x, y=self.y * other.y)\n"
    "proto.__eq__ = f(self, other) -> self.x == other.x && self.y == other.y\n"
    "proto.__lt__ = f(self, other) -> self.x < other.x\n"
    "v1 = new(proto, x=1, y=2)\n"
    "v2 = new(proto, x=3, y=4)\n"
    "sum_v = v1 + v2\n"
    "prod_v = v1 * v2\n"
    "eq = v1 == v1\n"
    "lt = v1 < v2\n"
    "[sum_v.x, sum_v.y, prod_v.x, prod_v.y, eq, lt]",
    "isinstance(result, list) and result == [4, 6, 3, 8, True, True]",
)

stress(
    "operator_overload_chained",
    "proto = new()\n"
    "proto.__add__ = f(self, other) -> new(proto, val=self.val + other.val)\n"
    "proto.__mul__ = f(self, other) -> new(proto, val=self.val * other.val)\n"
    "a = new(proto, val=2)\n"
    "b = new(proto, val=3)\n"
    "c = new(proto, val=4)\n"
    "r = a + b\n"
    "r = r * c\n"
    "r.val",
    "result == 20",
)

# ---------------------------------------------------------------------------
# Extra: stress combinations
# ---------------------------------------------------------------------------

stress(
    "many_closures",
    "fns = []\n"
    "for i in 0..100 {\n"
    "    fns = fns + [f(x) -> x + i]\n"
    "}\n"
    "total = 0\n"
    "for fn_item in fns {\n"
    "    total = total + fn_item(0)\n"
    "}\n"
    "total",
    "result == " + str(sum(range(100))),
)

stress(
    "deep_list_comprehension",
    "[x * y for x in lst(0..100) for y in lst(0..10) if (x * y) % 7 == 0].take(20)",
    "isinstance(result, list) and len(result) == 20",
)

stress(
    "large_dict_operations",
    'd = ["_": 0]\n'
    "for i in 0..1000 {\n"
    "    d[str(i)] = i * i\n"
    "}\n"
    'd["999"]',
    "result == 998001",
)

stress(
    "string_heavy_interpolation",
    "parts = []\n"
    "for i in 0..1000 {\n"
    '    parts = parts + ["item_${i}"]\n'
    "}\n"
    'len(parts) == 1000 && parts[0] == "item_0" && parts[999] == "item_999"',
    "result is True",
)


# ============================================================================
#  RUNNER
# ============================================================================

def main():
    print(f"Running {len(TESTS)} stress tests (timeout={TIMEOUT}s each)\n")
    pass_count = 0
    fail_count = 0
    timeout_count = 0

    for name, source, check_expr in TESTS:
        t0 = time.time()
        name_out, status, detail = run_test(name, source, check_expr)
        elapsed = time.time() - t0

        if status == "PASS":
            pass_count += 1
            marker = "PASS"
        elif status == "TIMEOUT":
            timeout_count += 1
            marker = "TIMEOUT"
        else:
            fail_count += 1
            marker = "FAIL"

        print(f"  [{marker:7s}] {name_out:<45s} ({elapsed:.2f}s)")
        if status != "PASS":
            for line in detail.split("\n")[:6]:
                print(f"           {line}")

    print(f"\n{'='*60}")
    print(f"  PASS: {pass_count}  FAIL: {fail_count}  TIMEOUT: {timeout_count}  TOTAL: {len(TESTS)}")
    print(f"{'='*60}")

    if fail_count + timeout_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
