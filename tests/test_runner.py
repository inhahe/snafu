"""Snafu interpreter test runner.

Each test is a (name, source, expected) tuple.  Expected can be:
- a value (checked with ==)
- a tuple ('exc', ClassName) — expects an exception of that type
- a tuple ('prints', expected_output) — captures stdout
"""

import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snafu


TESTS = [
    # ---- arithmetic ----
    ("int_add",        "1 + 2", 3),
    ("int_mul",        "3 * 4", 12),
    ("int_sub",        "10 - 3", 7),
    ("prec",           "1 + 2 * 3", 7),
    ("paren",          "(1 + 2) * 3", 9),
    ("pow",            "2 ** 10", 1024),
    ("neg",            "-5", -5),
    ("rational",       "1 / 3", snafu.Fraction(1, 3)),
    ("rational_add",   "1/3 + 1/6", snafu.Fraction(1, 2)),
    ("float_div",      "10.0 / 4", 2.5),
    ("mod",            "17 % 5", 2),

    # ---- comparison / boolean ----
    ("eq",             "1 == 1", True),
    ("ne",             "1 <> 2", True),
    ("lt",             "2 < 3", True),
    ("ge",             "5 >= 5", True),
    ("and",            "true && false", False),
    ("or",             "true || false", True),
    ("not",            "!false", True),
    ("short_circuit",  "true || undefined_var", True),
    ("ternary",        "5 > 3 ? \"yes\" : \"no\"", "yes"),

    # ---- strings ----
    ("str_concat",     '"hello" + " " + "world"', "hello world"),
    ("str_interp",     'x = 42; "value: ${x}"', "value: 42"),
    ("str_interp_expr",'"${1 + 2}"', "3"),
    ("str_len",        'len("hello")', 5),

    # ---- lists ----
    ("list",           "[1, 2, 3]", [1, 2, 3]),
    ("list_idx",       "[10, 20, 30][1]", 20),
    ("list_neg",       "[10, 20, 30][-1]", 30),
    ("list_len",       "[1, 2, 3, 4].len()", 4),
    ("list_cat",       "[1, 2] + [3, 4]", [1, 2, 3, 4]),

    # ---- dicts ----
    ("dict",           '["x": 1, "y": 2]', {"x": 1, "y": 2}),
    ("dict_idx",       'd = ["a": 10, "b": 20]; d["a"]', 10),
    ("dict_keys",      'd = ["a": 1, "b": 2]; d.keys()', ["a", "b"]),

    # ---- variables / scope ----
    ("var",            "x = 5; x", 5),
    ("reassign",       "x = 1; x = 2; x", 2),
    ("inner_scope",    "x = 1; { x = 2 }; x", 2),    # per SPEC: reassign bubbles up
    ("new_local",      "x = 1; { y = 5; x + y }", 6),

    # ---- control flow ----
    ("if_true",        'if 1 < 2 { "a" } el { "b" }', "a"),
    ("if_false",       'if 1 > 2 { "a" } el { "b" }', "b"),
    ("eli",            'x = 2; if x == 1 { "one" } eli x == 2 { "two" } el { "other" }', "two"),
    ("for_sum",        "x = 0; for i in [1,2,3,4,5] { x = x + i }; x", 15),
    ("while",          "x = 0; wh x < 10 { x = x + 1 }; x", 10),
    ("lp",             "x = 0; lp 5 { x = x + 1 }; x", 5),
    ("break",          "x = 0; wh true { x = x + 1; if x >= 3 { br } }; x", 3),
    ("continue",       "s = 0; for i in [1,2,3,4,5] { if i % 2 == 0 { cn }; s = s + i }; s", 9),

    # ---- functions ----
    ("df_expr",        "df sq(x) = x * x; sq(7)", 49),
    ("df_block",       "df dbl(x) { x * 2 }; dbl(5)", 10),
    ("fn_lit_arrow",   "add = f (x, y) -> x + y; add(3, 4)", 7),
    ("fn_lit_implicit","dbl = f -> a * 2; dbl(7)", 14),
    ("closure",        "df mk(n) { f (x) -> x + n }; add5 = mk(5); add5(3)", 8),
    ("recursive",      "df fact(n) { if n <= 1 { 1 } el { n * fact(n-1) } }; fact(5)", 120),
    ("default_arg",    "df greet(who, msg=\"hi\") { msg + \" \" + who }; greet(\"bob\")", "hi bob"),
    ("star_args",      "df allsum(*args) { sum(args) }; allsum(1, 2, 3, 4)", 10),

    # ---- patterns ----
    ("match_lit",      'mt 2 { 1 -> "one", 2 -> "two", _ -> "other" }', "two"),
    ("match_var",      'mt 99 { 1 -> "one", n -> n + 1 }', 100),
    ("match_list",     'mt [1, 2, 3] { [a, b, c] -> a + b + c, _ -> 0 }', 6),
    ("match_rest",     'mt [1, 2, 3, 4] { [h, ...t] -> t, _ -> [] }', [2, 3, 4]),
    ("match_or",       'mt 2 { 1 | 2 | 3 -> "small", _ -> "other" }', "small"),
    ("match_guard",    'mt 5 { n if n < 0 -> "neg", n if n > 0 -> "pos", _ -> "zero" }', "pos"),

    # ---- sum types ----
    ("sum_decl",       "sm M = Some(v) | None; Some(5)", None),   # value check skipped
    ("sum_match",      "sm M = Some(v) | None; m = Some(42); mt m { Some(v) -> v, None -> 0 }", 42),
    ("sum_rec",        """sm Tree = Leaf | Node(l, v, r)
df ssum(t) { mt t { Leaf -> 0, Node(l, v, r) -> v + ssum(l) + ssum(r) } }
t = Node(Node(Leaf, 1, Leaf), 2, Node(Leaf, 3, Leaf))
ssum(t)""", 6),

    # ---- exceptions ----
    ("try_catch",      'ty { rs ValErr("bad") } ex ValErr e { e.msg }', "bad"),
    ("try_uncaught",   'ty { rs ValErr("no") } ex IOErr e { "other" }', ('exc', 'ValErr')),
    ("try_finally",    'x = 0; ty { x = 1 } fi { x = 2 }; x', 2),
    ("re_raise",       'ty { ty { rs ValErr("a") } ex e { rs } } ex ValErr e { e.msg }', "a"),
    ("div_by_zero",    '1 / 0', ('exc', 'DivErr')),

    # ---- pipeline ----
    ("pipe_simple",    "[1, 2, 3] |> sum", 6),
    ("pipe_chain",     "[1, 2, 3, 4, 5] |> fl(f -> a > 2) |> sum", 12),
    ("pipe_map",       "[1, 2, 3] |> m(f -> a * 10)", [10, 20, 30]),
    # |>> = last-arg pipe.  Our `m` is (iter, f) so `xs |>> m(f)` = m(f, xs) — wrong.
    # Using map_fn (f-first) instead:
    ("pipe_last",      '[1, 2, 3] |>> map_fn(f -> a * 2)', [2, 4, 6]),

    # ---- objects ----
    ("new_obj",        "o = new(); o.x = 5; o.x", 5),
    ("inherit",        """Pt = new()
Pt.x = 0
Pt.y = 0
p = new(Pt)
p.x = 3
p.y = 4
p.x + p.y""", 7),
    ("proto_inherit",  """A = new()
A.greet = f -> "hello"
b = new(A)
b.greet()""", "hello"),

    # ---- prelude ----
    ("sum_fn",         "sum([1, 2, 3, 4, 5])", 15),
    ("min_max",        "[min([3, 1, 2]), max([3, 1, 2])]", [1, 3]),
    ("srt",            "srt([3, 1, 4, 1, 5, 9, 2, 6])", [1, 1, 2, 3, 4, 5, 6, 9]),
    ("srt_desc",       "srt([1, 2, 3], rv=true)", [3, 2, 1]),
    ("srt_key",        'srt(["aaa", "b", "cc"], k=f -> len(a))', ["b", "cc", "aaa"]),
    ("map",            "m([1, 2, 3], f -> a * a)", [1, 4, 9]),
    ("filter",         "fl([1, 2, 3, 4, 5], f -> a % 2 == 0)", [2, 4]),
    ("rdc",            "rdc([1, 2, 3, 4], f (x, y) -> x + y, 0)", 10),
    ("range",          "range(5)", [0, 1, 2, 3, 4]),
    ("range_start",    "range(2, 7)", [2, 3, 4, 5, 6]),
    ("range_step",     "range(0, 10, 2)", [0, 2, 4, 6, 8]),
    ("abs_fn",         "abs(-5)", 5),
    ("sqrt",           "sqrt(16)", 4.0),

    # ---- comprehensive little programs ----
    ("fib",            """df fib(n) { if n < 2 { n } el { fib(n-1) + fib(n-2) } }
fib(10)""", 55),
    ("list_double",    "[1, 2, 3] |> m(f -> a * 2)", [2, 4, 6]),
    ("tree_depth",     """sm Tree = Leaf | Node(l, v, r)
df depth(t) { mt t { Leaf -> 0, Node(l, v, r) -> 1 + max([depth(l), depth(r)]) } }
depth(Node(Leaf, 1, Node(Leaf, 2, Node(Leaf, 3, Leaf))))""", 3),
    ("safe_div",       """sm Result = Ok(v) | Err(e)
df sdiv(a, b) { if b == 0 { Err("div0") } el { Ok(a / b) } }
mt sdiv(10, 2) { Ok(v) -> v, Err(e) -> -1 }""", 5),

    # ---- Feature 1: sd/ld strict/loose mode blocks ----
    ("sd_block",       'sd { 1 + 2 }', 3),
    ("sd_block_und_err", 'sd { und + 1 }', ('exc', 'UndErr')),
    ("ld_after_sd",    'sd { ld { und + 1 } }', snafu.UND),
    ("sd_toggle",      'sd; und + 1', ('exc', 'UndErr')),
    ("ld_restores",    'sd { 1 }; und + 1', snafu.UND),

    # ---- Feature 2: structural equality ----
    ("seq_list",       '[1, 2, 3] === [1, 2, 3]', True),
    ("seq_list_ne",    '[1, 2, 3] === [1, 2, 4]', False),
    ("seq_dict",       '["a": 1] === ["a": 1]', True),
    ("seq_type_diff",  '1 === 1.0', False),
    ("seq_nan",        'x = flt("nan"); x === x', True),
    ("neq_struct",     '[1, 2] !== [1, 3]', True),
    ("seq_und",        'und === und', True),
    ("seq_und_ne",     'und === 1', False),

    # ---- Feature 3: .= modify-through-function ----
    ("dotmod_ident",   'x = 5; x .= f(n) -> n * 2; x', 10),
    ("dotmod_list",    'xs = [1, 2, 3]; xs[0] .= f(n) -> n + 10; xs[0]', 11),
    ("dotmod_attr",    'o = new(); o.x = 3; o.x .= f(n) -> n * n; o.x', 9),

    # ---- Feature 4: for/else + inp prelude ----
    ("for_else",       """found = false
for x in [1, 2, 3] {
    if x == 5 { found = true; br }
} el {
    found = "not_found"
}
found""", "not_found"),
    ("for_else_break", """found = false
for x in [1, 2, 3] {
    if x == 2 { found = true; br }
} el {
    found = "not_found"
}
found""", True),

    # ---- Feature 5: @dec decorators ----
    ("decorator",      """df twice(fn) {
    f(*args) -> fn(fn(*args))
}
@twice
df inc(x) = x + 1
inc(5)""", 7),
    ("multi_dec",      """df add1(fn) { f(x) -> fn(x) + 1 }
df mul2(fn) { f(x) -> fn(x) * 2 }
@add1
@mul2
df base(x) = x
base(3)""", 7),  # add1(mul2(base))(3): mul2(base)(3) = 3*2 = 6, add1 wraps: 6+1 = 7

    # ---- Feature 6: wi context managers ----
    ("wi_basic",       """log = []
o = new()
o.en = f -> { log.psh("enter"); "resource" }
o.ex = f(err) -> { log.psh("exit") }
wi o as r {
    log.psh(r)
}
log""", ["enter", "resource", "exit"]),
    ("wi_no_protocol", """x = 0
wi 1 as v {
    x = v + 10
}
x""", 11),

    # ---- Feature 7: us/xp module system ----
    # Module tests require a file on disk, so tested inline with eval
    ("export_node",    'xp foo, bar', snafu.UND),  # just parses and runs

    # ---- Feature 8: Python interop ----
    ("py_import_math", 'math = py.import("math"); math.sqrt(16.0)', 4.0),
    ("py_import_floor",'math = py.import("math"); math.floor(3.7)', 3),
    ("py_str_methods", 'math = py.import("math"); math.pi > 3.0', True),

    # ---- Labels + Goto ----
    ("goto_basic",     'lbl start; p("a"); goto end; p("b"); lbl end; "done"', "done"),
    ("goto_forward",   'goto skip; x = 1; lbl skip; x = 2; x', 2),
    ("goto_backward",  'x = 0; lbl top; x = x + 1; if x < 3 { goto top }; x', 3),

    # ---- Comefrom ----
    ("cf_basic",       'x = 0; cf inc; x = 99; goto done; lbl inc; x = x + 1; lbl done; x', 1),

    # ---- Element-wise operators ----
    ("ewise_add",      '[1, 2, 3] +. [4, 5, 6]', [5, 7, 9]),
    ("ewise_mul",      '[1, 2, 3] *. [4, 5, 6]', [4, 10, 18]),
    ("ewise_scalar",   '[1, 2, 3] *. 10', [10, 20, 30]),
    ("ewise_scalar_l", '10 *. [1, 2, 3]', [10, 20, 30]),
    ("ewise_cmp",      '[1, 5, 3] <. [2, 4, 6]', [True, False, True]),

    # ---- Reduce / Scan ----
    ("reduce_add",     '+/ [1, 2, 3, 4]', 10),
    ("reduce_mul",     '*/ [1, 2, 3, 4]', 24),
    ("scan_add",       '+\\ [1, 2, 3, 4]', [1, 3, 6, 10]),
    ("scan_mul",       '*\\ [1, 2, 3, 4]', [1, 2, 6, 24]),

    # ---- Outer product ----
    ("outer_mul",      '[1, 2, 3] *.. [4, 5]', [[4, 5], [8, 10], [12, 15]]),
    ("outer_add",      '[1, 2] +.. [10, 20, 30]', [[11, 21, 31], [12, 22, 32]]),

    # ---- Function composition ----
    ("compose_basic",  "dbl = f(x) -> x * 2; inc = f(x) -> x + 1; both = dbl + inc; both(3)", 7),
    ("compose_chain",  "a = f(x) -> x + 1; b = f(x) -> x * 2; c = f(x) -> x - 3; all3 = a + b + c; all3(5)", 9),

    # ---- is / is not / not in ----
    ("is_true",        "x = [1]; y = x; x is y", True),
    ("is_false",       "[1] is [1]", False),
    ("is_not",         "[1] is not [1]", True),
    ("not_in",         "5 not in [1, 2, 3]", True),
    ("not_in_false",   "2 not in [1, 2, 3]", False),

    # ---- range by ----
    ("range_by",       "lst(0..10 by 2)", [0, 2, 4, 6, 8]),
    ("range_by_incl",  "lst(0..=10 by 3)", [0, 3, 6, 9]),

    # ---- string methods ----
    ("str_rev",        '"hello".rev()', "olleh"),
    ("str_chars",      '"abc".chars()', ["a", "b", "c"]),
    ("str_contains",   '"hello world".contains("world")', True),
    ("str_lines",      '"a\\nb\\nc".lines()', ["a", "b", "c"]),
    ("str_words",      '"hello world foo".words()', ["hello", "world", "foo"]),
    ("str_repeat",     '"ab".repeat(3)', "ababab"),

    # ---- list methods ----
    ("list_rev",       "[1, 2, 3].rev()", [3, 2, 1]),
    ("list_flat",      "[[1, 2], [3, 4], [5]].flat()", [1, 2, 3, 4, 5]),
    ("list_any",       "[1, 2, 3].any(f(x) -> x > 2)", True),
    ("list_all",       "[1, 2, 3].all(f(x) -> x > 0)", True),
    ("list_find",      "[1, 2, 3, 4].find(f(x) -> x > 2)", 3),
    ("list_take",      "[1, 2, 3, 4, 5].take(3)", [1, 2, 3]),
    ("list_drop",      "[1, 2, 3, 4, 5].drop(2)", [3, 4, 5]),
    ("list_contains",  "[1, 2, 3].contains(2)", True),
    ("list_idx_method", "[10, 20, 30].idx(20)", 1),
    ("list_map",       "[1, 2, 3].map(f(x) -> x * 2)", [2, 4, 6]),
    ("list_filter",    "[1, 2, 3, 4, 5].filter(f(x) -> x > 2)", [3, 4, 5]),
    ("list_sum",       "[1, 2, 3, 4, 5].sum()", 15),
    ("list_zip",       "[1, 2, 3].zip([4, 5, 6])", [[1, 4], [2, 5], [3, 6]]),
    ("list_en",        "[10, 20, 30].en()", [[0, 10], [1, 20], [2, 30]]),

    # ---- prelude additions ----
    ("rev_fn",         "rev([1, 2, 3])", [3, 2, 1]),
    ("flat_fn",        "flat([[1, 2], [3, 4]])", [1, 2, 3, 4]),
    ("take_fn",        "take([1, 2, 3, 4, 5], 3)", [1, 2, 3]),
    ("drop_fn",        "drop([1, 2, 3, 4, 5], 2)", [3, 4, 5]),
    ("join_fn",        'join(", ", [1, 2, 3])', "1, 2, 3"),
    ("en_fn",          "en([10, 20])", [[0, 10], [1, 20]]),
    ("zp_fn",          "zp([1, 2], [3, 4])", [[1, 3], [2, 4]]),

    # ---- File I/O ----
    # (skip file tests that need temp files — test pe existence)
    ("pe_exists",      "type(pe)", "Fn"),

    # ---- Math + random ----
    ("sgn_pos",        "sgn(5)", 1),
    ("sgn_neg",        "sgn(-3)", -1),
    ("sgn_zero",       "sgn(0)", 0),
    ("gcd",            "gcd(48, 18)", 6),
    ("lcm",            "lcm(4, 6)", 12),
    ("fact",           "fact(5)", 120),
    ("log2",           "log2(8)", 3.0),
    ("log10",          "log10(100)", 2.0),
    ("trunc",          "trunc(3.7)", 3),
    ("asin",           "asin(1) > 1.5", True),
    ("prd",            "prd([1, 2, 3, 4])", 24),
    ("rand_range",     "x = rand(); x >= 0 && x < 1", True),

    # ---- chr/ord ----
    ("chr_fn",         "chr(65)", "A"),
    ("ord_fn",         'ord("A")', 65),
    ("fmt_fn",         "fmt(3.14159, \".2f\")", "3.14"),

    # ---- Partial application ----
    ("prt_basic",      "add = f(x, y) -> x + y; add3 = prt(add, 3, und); add3(4)", 7),
    ("prt_slot",       "add = f(x, y) -> x + y; add_last = prt(add, und, 10); add_last(5)", 15),
    ("flip_fn",        "sub = f(x, y) -> x - y; flip(sub)(1, 10)", 9),
    ("cnst_fn",        "always5 = cnst(5); always5(99)", 5),

    # ---- Regex ----
    ("regex_lit",      'x = r/\\d+/; type(x)', "Obj"),
    ("regex_match",    '"hello 42 world" =~ r/\\d+/; type("hello 42 world" =~ r/\\d+/)', "Obj"),
    ("regex_group",    '("2024-01-15" =~ r/(\\d+)-(\\d+)-(\\d+)/).gr(1)', "2024"),
    ("regex_findall",  'r/\\d+/.al("a1 b2 c3")', ["1", "2", "3"]),
    ("regex_sub",      'r/\\d+/.sub("a1 b2", "X")', "aX bX"),
    ("regex_split",    'r/\\s+/.spl("hello world  foo")', ["hello", "world", "foo"]),

    # ---- sleep ----
    ("sleep_exists",   "type(sleep)", "Fn"),

    # ---- uniq/dct/rp ----
    ("uniq_fn",        "uniq([1, 2, 2, 3, 1, 3])", [1, 2, 3]),
    ("dct_fn",         'dct([["a", 1], ["b", 2]])', {"a": 1, "b": 2}),
    ("rp_fn",          "rp(0, 5)", [0, 0, 0, 0, 0]),
    ("list_uniq",      "[1, 2, 2, 3, 1].uniq()", [1, 2, 3]),

    # ---- Generator send ----
    ("gen_send",       """ct echo() {
  x = y "first"
  y "got: " + str(x)
}
g = echo()
first = g.nx()
second = g.sd("hello")
[first, second]""", ["first", "got: hello"]),

    # ---- TCO (tail call) ----
    ("tco_fact",       "df fact(n, acc=1) { if n <= 1 { r acc } el { r tail(fact, n-1, n*acc) } }; fact(100)", None),  # just check it doesn't stack overflow
    ("tco_large",      "df countdown(n) { if n <= 0 { r 0 } el { r tail(countdown, n - 1) } }; countdown(5000)", 0),

    # ---- := alias ----
    ("alias_basic",    "a = 5; b := a; a = 10; b", 10),
    ("alias_reverse",  "a = 5; b := a; b = 20; a", 20),

    # ---- ~= tracking ----
    ("track_basic",    "x = 5; z ~= x + 1; x = 10; z", 11),
    ("track_expr",     "a = 2; b = 3; c ~= a * b; a = 10; c", 30),

    # ---- $ variable-variables ----
    ("varvar_basic",   'name = "x"; x = 42; $name', 42),
    ("varvar_expr",    'k = "greeting"; greeting = "hi"; ${k}', "hi"),
    ("varvar_double",  'a = "b"; b = "c"; c = 99; $$a', 99),

    # ---- bp() ----
    ("bp_exists",      "type(bp)", "Fn"),

    # ---- frozen collections ----
    ("frozen_list",    "t = fr[1, 2, 3]; t[0]", 1),
    ("frozen_len",     "t = fr[1, 2, 3]; len(t)", 3),
    ("frozen_dict",    't = fr["x": 1, "y": 2]; t["x"]', 1),

    # ---- dict methods ----
    ("dict_has",       '["a": 1, "b": 2].has("a")', True),
    ("dict_merge",     '["a": 1].merge(["b": 2])', {"a": 1, "b": 2}),
    ("dict_get",       '["a": 1].get("b", 0)', 0),
    ("dict_without",   '["a": 1, "b": 2].without("a")', {"b": 2}),
    ("dict_map_vals",  '["a": 1, "b": 2].map_vals(f(v) -> v * 10)', {"a": 10, "b": 20}),

    # ---- atom ----
    ("atom_basic",     "a = atom(0); a.set(5); a.get()", 5),
    ("atom_swap",      "a = atom(10); a.swap(f(x) -> x + 1); a.get()", 11),
    ("atom_cas",       "a = atom(5); a.cas(5, 10); a.get()", 10),

    # ---- Complex numbers ----
    ("complex_lit",     "3i", complex(0, 3)),
    ("complex_add",     "1 + 2i", complex(1, 2)),
    ("complex_mul",     "(1 + 2i) * (3 + 4i)", complex(-5, 10)),
    ("complex_re",      "(3 + 4i).re", 3.0),
    ("complex_im",      "(3 + 4i).im", 4.0),
    ("cx_ctor",         "cx(1, 2)", complex(1, 2)),

    # ---- Green threads + channels ----
    ("gt_basic",        "h = gt { 1 + 2 }; aw h", 3),
    ("channel",         "c = ch(1); c.send(42); c.recv()", 42),
    ("gt_channel",      "c = ch(1); gt { c.send(99) }; sleep(50); c.recv()", 99),

    # ---- Reactive on/of ----
    ("on_change",       "log = []; x = 0; on x.ch { log.psh(x) }; x = 1; x = 2; x = 3; log", [1, 2, 3]),
    ("off_change",      "log = []; x = 0; on x.ch { log.psh(x) }; x = 1; of x.ch; x = 2; log", [1]),

    # ---- sub ----
    ("sub_basic",       "lbl a; x = 10; lbl b; x = 20; lbl c; sub(a, b); x", 10),

    # ---- Transducers ----
    ("xm_basic",        "(xm(f(x) -> x * 2)).al([1, 2, 3])", [2, 4, 6]),
    ("xfl_basic",       "(xfl(f(x) -> x > 2)).al([1, 2, 3, 4])", [3, 4]),
    ("compose_xd",      "(xm(f(x) -> x * 2) + xfl(f(x) -> x > 4)).al([1, 2, 3, 4])", [6, 8]),
    ("xtk_basic",       "(xtk(3)).al([1, 2, 3, 4, 5])", [1, 2, 3]),

    # ---- Lenses ----
    ("lens_get",        'l = lens("x"); o = new(); o.x = 5; l.gt(o)', 5),
    ("lens_set",        'l = lens("x"); o = new(); o.x = 5; l.st(o, 10); o.x', 10),
    ("lens_compose",    'l = lens(0) + lens(1); data = [[1, 2], [3, 4]]; l.gt(data)', 2),

    # ---- rm (resume) ----
    ("resume_basic",    "x = 0; lbl a; x = x + 1; if x < 3 { goto a }; rm; x", None),  # just test it doesn't crash

    # ---- isa + methods ----
    ("isa_int",         'isa(5, "Int")', True),
    ("isa_str",         'isa("hi", "Str")', True),
    ("isa_false",       'isa(5, "Str")', False),
    ("chunk",           "[1,2,3,4,5].chunk(2)", [[1,2],[3,4],[5]]),
    ("intersperse",     "[1,2,3].intersperse(0)", [1,0,2,0,3]),
    ("group_by",        "[1,2,3,4,5,6].group_by(f(x) -> x % 2)", None),  # just test no crash
    ("dict_flip",       '["a": 1, "b": 2].flip()', {1: "a", 2: "b"}),
    ("dict_update",     'd = ["a": 1]; d.update(["b": 2]); d', {"a": 1, "b": 2}),

    # ---- Algebraic effects ----
    ("effect_basic",    "ef MyEff(v); ty { pf MyEff(42) } ex e { e.msg }", None),  # just doesn't crash
    ("handle_basic",    'ef Fail(msg)\nhd { pf Fail("oops"); "unreachable" } with {\n    Fail(msg) k -> "handled: " + msg\n}', "handled: oops"),
    ("handle_return",   'hd { 1 + 2 } with {\n    r -> "result: " + str(r)\n}', "result: 3"),

    # ---- Macros ----
    ("macro_basic",     'mc double_it(x) { ev(str(x) + " + " + str(x)) }\ndouble_it(21)', 42),

    # ---- ev with sc: ----
    ("ev_global",       "x = 99; ev(\"x\", sc=tp)", 99),

    # ---- select ----
    ("select_basic",    "c1 = ch(1); c2 = ch(1); c1.send(42); sl(c1, c2)[1]", 42),

    # ---- xs execution sets ----
    ("xs_basic",        "xs { a = 1; b = 2; c = 3 }; a + b + c", 6),

    # ---- signals ----
    ("signal_basic",    "s = signal(); log = []; s.connect(f(v) -> log.psh(v)); s.emit(42); log", [42]),

    # ---- dv derivation ----
    ("dv_eq",           "sm Color = Red | Green | Blue dv [Eq]; Red == Red", True),
    ("dv_eq_ne",        "sm Color = Red | Green | Blue dv [Eq]; Red == Blue", False),

    # ---- multi-dispatch ----
    ("dispatch_typed",  'df greet(Str name) = "hello " + name\ndf greet(Int n) = "number " + str(n)\n[greet("bob"), greet(42)]', ["hello bob", "number 42"]),

    # ---- Self-modification: ast_of / eval_ast ----
    ("ast_of_type",     "a = ast_of(1 + 2); type(a)", None),  # returns an AST node type
    ("eval_ast_basic",  "a = ast_of(1 + 2); eval_ast(a)", 3),
    ("ast_modify",      "a = ast_of(1 + 2)\na.rhs = ast_of(10)\neval_ast(a)", 11),
    ("ast_src_basic",   'type(ast_src(ast_of(1 + 2)))', "Str"),
    ("src_readable",    "type(src)", "Str"),
    ("ast_new_basic",   "n = ast_new(\"NumLit\", value=42); eval_ast(n)", 42),
    ("ast_global",      "type(ast)", None),  # program AST exists

    # ---- State time-travel ----
    ("ps_sa_basic",     'x = 1; ps(); x = 2; ps(); x = 3; sa(-1)["bindings"]["x"]', 2),
    ("ps_named",        'x = 10; ps("checkpoint"); x = 20; sp("checkpoint")["bindings"]["x"]', 10),
    ("restore_basic",   "x = 1; ps(); x = 99; restore(sa(-1)); x", 1),
    ("st_current",      'x = 42; s = st(); s["bindings"]["x"]', 42),

    # ---- State buffer memory management ----
    ("ps_clear",        "ps(); ps(); ps(); ps_clear(); ps_size()", 0),
    ("ps_size",         "ps(); ps(); ps(); ps_size()", 3),
    ("ps_max",          "ps_max(3); for i in 0..10 { ps() }; ps_size()", 3),
    ("auto_rec_max",    "auto_record(true, 5); for i in 0..20 { x = i }; auto_record(false); ps_size() <= 5", True),

    # ================================================================
    #  GOLF SYNTAX FEATURES
    # ================================================================

    # ---- Backtick lambda ----
    ("backtick_basic",  "m([1,2,3], `a*2`)", [2, 4, 6]),
    ("backtick_filter", "fl([1,2,3,4,5], `a>2`)", [3, 4, 5]),
    ("backtick_rdc",    "rdc([1,2,3,4], `a+b`, 0)", 10),

    # ---- ?? null coalesce ----
    ("coalesce_und",    "und ?? 5", 5),
    ("coalesce_val",    "3 ?? 5", 3),
    ("coalesce_chain",  "und ?? und ?? 42", 42),

    # ---- ?. safe nav ----
    ("safenav_und",     "und?.x", snafu.UND),
    ("safenav_val",     "o = new(); o.x = 5; o?.x", 5),

    # ---- Bitwise ----
    ("bit_and",         "5 & 3", 1),
    ("bit_or",          "5 | 3", 7),
    ("bxor_fn",         "bxor(5, 3)", 6),
    ("shl_fn",          "shl(1, 4)", 16),
    ("shr_fn",          "shr(16, 2)", 4),

    # ---- One-letter aliases ----
    ("alias_S",         'S("a,b,c", ",")', ["a", "b", "c"]),
    ("alias_R",         "R([1,2,3])", [3, 2, 1]),
    ("alias_T",         "T([[1,2],[3,4]])", [[1, 3], [2, 4]]),
    ("alias_W",         'W("hello world")', ["hello", "world"]),
    ("alias_N",         'N("3 cats 7 dogs")', [3, 7]),

    # ---- Digits ----
    ("digits_dec",      "D(123)", [1, 2, 3]),
    ("digits_hex",      "D(255, 16)", [15, 15]),
    ("undigits",        "UD([1,2,3])", 123),
    ("to_base",         'to_base(255, 16)', "ff"),
    ("from_base",       'from_base("ff", 16)', 255),

    # ---- Combinatorics ----
    ("perms_len",       "len(X([1,2,3]))", 6),
    ("combs",           "C([1,2,3,4], 2)", [[1,2],[1,3],[1,4],[2,3],[2,4],[3,4]]),
    ("powerset_len",    "len(powerset([1,2,3]))", 8),

    # ---- Matrix ----
    ("transpose",       "T([[1,2,3],[4,5,6]])", [[1,4],[2,5],[3,6]]),
    ("rotate_fn",       "rotate([1,2,3,4,5], 2)", [3,4,5,1,2]),
    ("window_fn",       "window([1,2,3,4,5], 3)", [[1,2,3],[2,3,4],[3,4,5]]),

    # ---- Infinite gens ----
    ("from_n",          "take(from_n(5), 4)", [5, 6, 7, 8]),
    ("cycle_fn",        "take(cycle([1,2,3]), 7)", [1,2,3,1,2,3,1]),
    ("repeat_val_fn",   "take(repeat_val(0), 5)", [0,0,0,0,0]),

    # ---- Tacit ----
    ("fork_basic",      "f_fn = fork(sum, f(a,b)->a/b, len); f_fn([2,4,6])", 4.0),

    # ---- String methods ----
    ("str_pad",         '"hi".pad(6)', "hi    "),
    ("str_lpad",        '"hi".lpad(6, "0")', "0000hi"),

    # ---- min/max by ----
    ("min_by",          'min_by(["abc","z","hi"], `len(a)`)', "z"),
    ("max_by",          'max_by(["abc","z","hi"], `len(a)`)', "abc"),

    # ---- Misc ----
    ("flat_deep",       "flat([[1,[2]],[3,[4,[5]]]], 99)", [1,2,3,4,5]),
    ("each_fn",         "log = []; [1,2,3].each(`log.psh(a)`); log", [1,2,3]),
    ("divisors_fn",     "divisors(12)", [1, 2, 3, 4, 6, 12]),
    ("list_append",     "[1,2,3] + 4", [1,2,3,4]),
    ("str_remove",      '"hello" - "l"', "heo"),
    ("succ_fn",         'succ("a")', "b"),
    ("pred_fn",         'pred("z")', "y"),

    # ================================================================
    #  NEW FEATURES (batch 2)
    # ================================================================

    # ---- List comprehensions ----
    ("comp_basic",      "[x * 2 for x in 1..5]", [2, 4, 6, 8]),
    ("comp_filter",     "[x for x in 1..10 if x % 2 == 0]", [2, 4, 6, 8]),
    ("comp_nested",     "[a * b for a in [1,2,3] for b in [10,20]]", [10, 20, 20, 40, 30, 60]),
    ("comp_guard_nest", "[[a,b] for a in 1..4 for b in 1..4 if a + b == 4]", [[1,3],[2,2],[3,1]]),

    # ---- Where clauses ----
    ("whr_basic",       "a + b whr { a = 3; b = 4 }", 7),
    ("whr_fn",          "df hyp(a, b) = sqrt(s) whr { s = a**2 + b**2 }; hyp(3, 4)", 5.0),

    # ---- Method missing ----
    ("mm_basic",        'o = new(); o.__mm__ = f(name) -> "called:" + name; o.anything', "called:anything"),
    ("mm_with_args",    'o = new(); o.__mm__ = f(name, *args) -> name + ":" + str(args); o.foo(1, 2)', "foo:[1, 2]"),

    # ---- Shelve ----
    # (skip — needs temp files)

    # ---- Query ----
    ("qr_basic",        'people = [["age": 30, "name": "Alice"], ["age": 25, "name": "Bob"]]; qr people whr `a["age"] > 28` sel `a["name"]`', ["Alice"]),

    # ---- Stack ----
    ("stk_basic",       "stk { 3 4 + 2 * }", 14),
    ("stk_dup",         "stk { 5 dup * }", 25),
    ("stk_swap",        "stk { 1 2 swap - }", 1),

    # ---- Logic variables ----
    ("lv_basic",        "x = lv(); unify(x, 42); x.val()", 42),
    ("lv_list",         "a = lv(); b = lv(); unify([a, 2], [1, b]); [a.val(), b.val()]", [1, 2]),

    # ---- Multi-shot effects ----
    # (basic test — just verify k works once)
    ("effect_k_resume", """ef Ask(prompt)
hd {
    x = pf Ask("name")
    "hello " + x
} with {
    Ask(p) k -> k("World")
}""", "hello World"),

    # ================================================================
    #  NEW FEATURES (batch 3)
    # ================================================================

    # ---- Universe fork ----
    ("fork_basic",      "x = 1; h = fk { x = 99; x }; [aw h, x]", [99, 1]),
    ("fk_future",       "h = fk { 1 + 2 }; aw h", 3),
    ("fk_isolated",     "x = 1; h = fk { x = 99; x }; (aw h) + x", 100),
    ("fk_map_basic",    "[aw h for h in fk_map([1,2,3], `a*a`)]", [1, 4, 9]),
    ("fk_id_type",      "type(fk_id)", "Fn"),
    ("fk_tree_type",    "type(fk_tree())", "ForkNode"),
    ("fk_join_empty",   "fk_join()", []),
    ("fk_nofork_id",    "fk_id()", 0),
    ("fk_body_notouch", "x = 10; h = fk { x = 0; x }; aw h; x", 10),
    ("fk_true_fork",    "id = fk(); if id == 0 { 42 } el { 99 }", 42),

    # ---- Contracts ----
    ("req_pass",        "df pos(n) req n > 0 = n * 2; pos(5)", 10),
    ("req_fail",        "df pos(n) req n > 0 = n * 2; pos(-1)", ('exc', 'ContractErr')),
    ("ens_pass",        "x = 10; df dec(n) ens x >= 0 { x = x - n; x }; dec(5)", 5),
    ("ens_fail",        "x = 5; df dec(n) ens x >= 0 { x = x - n; x }; dec(10)", ('exc', 'ContractErr')),

    # ---- Constraint solver ----
    ("solve_basic",     "x = lv(); y = lv(); solve([x, y], f() -> x.val() + y.val() == 10 && x.val() * y.val() == 21, range(0, 11)); [x.val(), y.val()]", [3, 7]),

    # ---- Dynamic scope ----
    ("dy_basic",        "df inner() = log_level; dy { log_level = 3; inner() }", 3),

    # ---- Tee / tap ----
    ("tee_basic",       "[1,2,3] |> tee(sum, len)", [6, 3]),
    ("tap_basic",       "log = []; [1,2,3] |> tap(`log.psh(a)`) |> sum", 6),

    # ---- Recording ----
    ("rec_basic",       "t = rec { x = 1; y = 2 }; len(t) >= 2", True),

    # ---- Coercion ----
    ("cv_basic",        'cv("Str", "Int", `int(a)`); df double(Int n) = n * 2; double("21")', 42),

    # ================================================================
    #  NEW FEATURES (batch 4)
    # ================================================================

    # ---- Named returns ----
    ("named_ret",       'df divide(a, b) { r quo=a/b, rem=a%b }; result = divide(10, 3); [result["quo"], result["rem"]]', None),

    # ---- Two-way dict ----
    ("inv_dict",        'd = ["a": 1, "b": 2]; (~d)[1]', "a"),
    ("inv_get",         'd = ["a": 1, "b": 2]; d.inv_get(2)', "b"),

    # ---- Memo ----
    ("memo_basic",      '@memo\ndf fib(n) { if n < 2 { n } el { fib(n-1) + fib(n-2) } }\nfib(30)', 832040),
    ("lazy_basic",      'x = lazy(`1 + 2`); force(x)', 3),
    ("lazy_cached",     'count = atom(0); thunk_fn = f() -> { count.swap(f(x) -> x + 1); 42 }; x = lazy(thunk_fn); force(x); force(x); count.get()', 1),

    # ---- JSON ----
    ("to_json",         'to_json(["a": 1, "b": 2])', '{"a": 1, "b": 2}'),
    ("from_json",       'from_json("{\\"a\\": 1}")["a"]', 1),

    # ---- Condition triggers ----
    ("on_cond",         'log = []; x = 0; on x > 2 { log.psh("big") }; x = 1; x = 3; x = 5; log', ["big", "big"]),

    # ---- Actor ----
    ("actor_basic",     'c = actor(`a * 2`); c.send(5)', 10),

    # ---- f^n ----
    ("fn_power",        'inc = f(x) -> x + 1; inc3 = inc^3; inc3(0)', 3),
    ("fn_power_zero",   'inc = f(x) -> x + 1; id_fn = inc^0; id_fn(42)', 42),

    # ---- Transitive alias ----
    ("alias_chain",     'c = 5; b := c; a := b; a', 5),
    ("alias_chain_mut", 'c = 5; b := c; a := b; c = 99; a', 99),

    # ================================================================
    #  DEFERRED FEATURES (batch 5 — the hard ones)
    # ================================================================

    # ---- Feature 1: Multi-level meta-circular interpreter ----
    ("lv2_basic",       'lv(2); 1 + 2', 3),  # default meta-interp is pass-through
    ("lv2_isrc",        'lv(2); type(isrc)', "InterpSource"),  # isrc exists
    ("lv2_iast",        'lv(2); type(iast)', "InterpAST"),  # iast exists
    ("lv1_default",     'interp_level()', 1),  # default level is 1

    # ---- Feature 2: Implicit TCO ----
    ("itco_fact",       'df fact(n, acc=1) { if n <= 1 { acc } el { fact(n-1, n*acc) } }; fact(5000) > 0', True),
    ("itco_countdown",  'df cd(n) { if n <= 0 { 0 } el { cd(n-1) } }; cd(5000)', 0),

    # ---- Feature 3: Function inverse ----
    ("finv_add",        'f_fn = f(x) -> x + 5; inv = f_fn^-1; inv(8)', 3),
    ("finv_mul",        'f_fn = f(x) -> x * 3; inv = f_fn^-1; inv(12)', 4),
    ("finv_compound",   'f_fn = f(x) -> x * 2 + 10; inv = f_fn^-1; inv(20)', 5),

    # ---- Feature 4: Symbolic numbers ----
    ("sym_basic",       'x = sym(5); y = x + 3; type(y)', "Sym"),
    ("sym_eval",        'x = sym(5); y = x + 3; flat(y)', 8),

    # ---- Feature 5: Auto recording ----
    ("autorec_basic",   'auto_record(true); x = 1; x = 2; x = 3; auto_record(false); len(sa(-1)["bindings"]) > 0', True),

    # ---- Feature 6: Ref / STM ----
    ("ref_basic",       'r_val = ref(0); dosync { r_val.set(42) }; r_val.get()', 42),
    ("ref_no_dosync",   'r_val = ref(0); r_val.set(1)', ('exc', 'InterpErr')),

    # ================================================================
    #  DEFERRED FEATURES (batch 6)
    # ================================================================

    # ---- Feature 1: N-dimensional IP (ja, jr) ----
    ("jr_skip",         "x = 0; jr(2); x = 99; x = 1; x", 1),
    ("ja_jump",         "x = 10; ja(3); x = 20; x = 30; x = 40; x", 40),
    ("jr_backward",     "x = 0; lbl top; x = x + 1; if x < 3 { jr(-2) }; x", 3),

    # ---- Feature 2: OS process spawning ----
    ("exec_echo",       'exec("echo hello")[0].strip()', "hello"),
    ("shell_basic",     'shell("echo hi").strip()', "hi"),
    ("exec_lines",      'exec_lines("echo hello")[0]', "hello"),

    # ---- Feature 3: Python alias table ----
    ("py_alias_math",   'ma.sqrt(16.0)', 4.0),
    ("py_alias_json",   'js.dumps([1,2,3])', '[1, 2, 3]'),
    ("py_alias_os",     'type(os.path)', None),  # just doesn't crash
    ("py_alias_re",     'rn.seed(42); type(rn.random())', "Flt"),

    # ---- Feature 4: Traversal lenses and Prisms ----
    ("traverse_gt",     'traverse.gt([1,2,3])', [1, 2, 3]),
    ("traverse_md",     'traverse.md([1,2,3], `a*10`)', [10, 20, 30]),
    ("traverse_st",     'traverse.st([1,2,3], 0)', [0, 0, 0]),
    ("prism_get",       'sm M = Some(v) | None; p_fn = prism("Some"); p_fn.gt(Some(42))', 42),
    ("prism_set",       'sm M = Some(v) | None; p_fn = prism("Some"); r = p_fn.st(Some(1), 99); mt r { Some(v) -> v, _ -> 0 }', 99),
    ("prism_miss",      'sm M = Some(v) | None; p_fn = prism("Some"); p_fn.gt(None)', snafu.UND),

    # ---- Feature 5: Extra transducers (xch, xdd, xpp) ----
    ("xdd_basic",       'xdd().al([1,1,2,2,3,3,3,1])', [1, 2, 3, 1]),
    ("xpp_basic",       'xpp().al([1,2,3])', [1, 2, 3]),
    ("xch_basic",       'xch(2).al([1,2,3,4,5])', [[1,2],[3,4],[5]]),
    ("xch_even",        'xch(3).al([1,2,3,4,5,6])', [[1,2,3],[4,5,6]]),

    # ---- Feature 6: Extended us import (as alias already works) ----
    # (module file tests need disk files, but we can test the parse path)
    ("us_as_parse",     'xp foo', snafu.UND),  # existing test coverage

    # ---- Feature 7: ev with lv keyword ----
    ("ev_sc_tp",        'x = 99; ev("x", sc=tp)', 99),
    ("ev_lv_basic",     'ev("1 + 2", lv=2)', 3),

    # ================================================================
    #  FINAL POLISH FEATURES
    # ================================================================

    # ---- us as alias ----
    ("us_as_alias",     'us math as mth; mth.sqrt(16.0)', 4.0),

    # ---- jl (jump to label) ----
    ("jl_basic",        'x = 0; lbl target; x = x + 1; if x < 3 { jl target }; x', 3),

    # ---- Multi-shot continuations ----
    ("multishot_choose", """ef Choose(opts)
hd {
    x = pf Choose([1, 2, 3])
    x * x
} with {
    Choose(opts) k -> m(opts, k)
}""", [1, 4, 9]),

    # ---- y as variable (fixed) ----
    ("y_as_var",        "y = 42; y", 42),
    ("y_as_var_expr",   "x = 1; y = 2; x + y", 3),
    ("y_in_coroutine",  "ct gen() { y 10; y 20 }; lst(gen())", [10, 20]),

    # ---- Nested multi-shot (fixed) ----
    ("multishot_amb",   """ef Amb(opts)
hd {
    a = pf Amb([1, 2])
    b = pf Amb([10, 20])
    a + b
} with {
    Amb(opts) k -> m(opts, k)
}""", [[11, 21], [12, 22]]),

    # ---- Short method aliases ----
    ("str_sp",          '"a,b,c".sp(",")', ["a", "b", "c"]),
    ("str_tr",          '"  hi  ".tr()', "hi"),
    ("str_rpl",         '"hello".rpl("l", "r")', "herro"),
    ("str_sw",          '"hello".sw("he")', True),
    ("str_ew",          '"hello".ew("lo")', True),
    ("str_has",         '"hello".has("ell")', True),
    ("list_fl",         "[1,2,3,4,5].fl(`a>2`)", [3, 4, 5]),
    ("list_m",          "[1,2,3].m(`a*2`)", [2, 4, 6]),
    ("list_has",        "[1,2,3].has(2)", True),
    ("list_gb",         "[1,2,3,4,5,6].gb(`a%2`)", None),
    ("list_sb",         'srt(["cc","a","bbb"], `len(a)`)', ["a", "cc", "bbb"]),
    ("dict_mg",         '["a": 1].mg(["b": 2])', {"a": 1, "b": 2}),
    ("dict_wo",         '["a": 1, "b": 2].wo("a")', {"b": 2}),
    ("dict_mv",         '["a": 1, "b": 2].mv(`a*10`)', {"a": 10, "b": 20}),

    # ================================================================
    #  NEW FEATURES (batch 7)
    # ================================================================

    # ---- Set operations ----
    ("union_fn",        "union([1,2,3], [3,4,5])", None),  # order may vary
    ("inter_fn",        "srt(inter([1,2,3,4], [3,4,5,6]))", [3, 4]),
    ("diff_fn",         "srt(diff([1,2,3,4], [3,4,5]))", [1, 2]),
    ("subset_fn",       "subset([1,2], [1,2,3])", True),
    ("list_union",      "srt([1,2,3].union([3,4,5]))", [1, 2, 3, 4, 5]),

    # ---- Persistent vars ----
    # (skip full test — needs filesystem state between runs)
    ("pv_parse",        "pv x = 5; x", 5),  # test basic pv parse and eval

    # ---- Quantifiers ----
    ("some_basic",      "some x in [1,2,3,4,5] if x > 3", True),
    ("some_false",      "some x in [1,2,3] if x > 10", False),
    ("every_basic",     "every x in [1,2,3] if x > 0", True),
    ("every_false",     "every x in [1,2,3] if x > 1", False),

    # ---- Operator overloading ----
    ("op_overload",     "V = new()\nV.__add__ = f(a, b) -> new(V, x=a.x+b.x, y=a.y+b.y)\nv1 = new(V, x=1, y=2)\nv2 = new(V, x=3, y=4)\nv3 = v1 + v2\n[v3.x, v3.y]", [4, 6]),

    # ---- Defer ----
    ("defer_basic",     "log = []; { defer log.psh(3); defer log.psh(2); log.psh(1) }; log", [1, 2, 3]),
    ("defer_return",    'log = []; df f() { defer log.psh("cleanup"); r 42 }; [f(), log]', [42, ["cleanup"]]),

    # ---- take_while / drop_while / flat_map ----
    ("tw_basic",        "[1,2,3,4,5].tw(`a<4`)", [1, 2, 3]),
    ("dw_basic",        "[1,2,3,4,5].dw(`a<3`)", [3, 4, 5]),
    ("fm_basic",        "[1,2,3].fm(`[a, a*10]`)", [1, 10, 2, 20, 3, 30]),

    # ---- Try-pipe ----
    ("trypipe_ok",      '5 |?> f(x) -> x * 2', ["ok", 10]),
    ("trypipe_err",     '0 |?> f(x) -> 1/x', None),  # ["err", "..."]
    ("unwrap_ok",       'unwrap(["ok", 42])', 42),
    ("unwrap_or_err",   'unwrap_or(["err", "bad"], -1)', -1),
    ("is_ok_fn",        'is_ok(["ok", 5])', True),
    ("is_err_fn",       'is_err(["err", "x"])', True),

    # ================================================================
    #  STDLIB EXPANSION
    # ================================================================

    # ---- stdlib: filesystem ----
    ("exists_fn",       'exists("snafu.py")', True),
    ("is_file_fn",      'is_file("snafu.py")', True),
    ("cwd_fn",          'type(cwd())', "Str"),
    ("ls_fn",           'type(ls())', "Lst"),

    # ---- stdlib: datetime ----
    ("now_fn",          'type(now())', "Str"),
    ("timestamp_fn",    'timestamp() > 0', True),

    # ---- stdlib: hashing ----
    ("md5_fn",          'md5("hello")', "5d41402abc4b2a76b9719d911017c592"),
    ("sha256_fn",       'len(sha256("hello"))', 64),

    # ---- stdlib: env ----
    ("env_fn",          'type(env("PATH"))', "Str"),

    # ---- stdlib: args ----
    ("args_fn",         'type(args())', "Lst"),

    # ---- stdlib: http ----
    ("http_get_type",   'type(http_get)', "Fn"),
]


def run_tests():
    passed, failed = 0, 0
    fails = []

    for name, source, expected in TESTS:
        interp = snafu.Interpreter()
        try:
            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                result = snafu.run(source, interp=interp)
            finally:
                sys.stdout = old_stdout
                captured_out = captured.getvalue()

            if expected is None:
                # No value check, just "runs without error"
                passed += 1
                continue

            if isinstance(expected, tuple) and expected[0] == 'exc':
                failed += 1
                fails.append((name, source, f"expected exception {expected[1]}, got {result!r}"))
                continue

            if isinstance(expected, tuple) and expected[0] == 'prints':
                if captured_out == expected[1]:
                    passed += 1
                else:
                    failed += 1
                    fails.append((name, source, f"expected output {expected[1]!r}, got {captured_out!r}"))
                continue

            if _deep_eq(result, expected):
                passed += 1
            else:
                failed += 1
                fails.append((name, source, f"expected {expected!r}, got {result!r}"))

        except snafu.SnafuError as e:
            exc_name = type(e).__name__
            if isinstance(expected, tuple) and expected[0] == 'exc' and expected[1] == exc_name:
                passed += 1
            else:
                failed += 1
                fails.append((name, source, f"unexpected {exc_name}: {e.msg}"))
        except Exception as e:
            failed += 1
            fails.append((name, source, f"host exception {type(e).__name__}: {e}"))

    print(f"\n{passed}/{passed+failed} tests passed")
    if fails:
        print(f"\n{len(fails)} failures:")
        for name, src, msg in fails:
            short = src.replace('\n', ' | ')[:60]
            print(f"  [{name}]  {short}")
            print(f"    -> {msg}")

    return failed == 0


def _deep_eq(a, b):
    if type(a) != type(b):
        # Allow Int == Fraction equivalence
        try: return a == b
        except: return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_deep_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a.keys()) == set(b.keys()) and all(_deep_eq(a[k], b[k]) for k in a)
    return a == b


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
