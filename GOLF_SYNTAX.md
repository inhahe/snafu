# Snafu Code Golf Syntax Reference

All terse syntax additions for competitive code golf.

## Backtick lambda (`` `expr` ``)

Shortest anonymous function form. Implicit args `a`, `b`, `c` (first, second, third positional).

```
m([1,2,3], `a*2`)           # [2, 4, 6]
fl([1,2,3,4,5], `a>2`)      # [3, 4, 5]
srt(words, `len(a)`)         # sort by length
[1,2,3] |> m(`a*a`)         # [1, 4, 9]
rdc([1,2,3,4], `a+b`, 0)    # 10
```

Comparison with other lambda forms:
```
f (x) -> x * 2              # 18 chars (explicit params)
f -> a * 2                   # 12 chars (implicit, arrow)
`a * 2`                      # 7 chars  (backtick)
`a*2`                        # 5 chars  (minimal)
```

## Null-coalesce `??` and safe navigation `?.`

```
x ?? 0                       # if x is und, use 0
d["key"] ?? "default"        # dict lookup with default
obj?.name                    # und if obj is und (no error)
obj?.method()                # und if obj is und
a?.b?.c                      # chain safely
```

## Auto-coercion

```
"123" + 1                    # 124 (string parsed as number)
[1,2,3] + 4                 # [1,2,3,4] (append element)
"hello" - "l"                # "heo" (remove all occurrences)
```

## Bitwise operators

```
5 & 3                        # 1  (AND — infix operator)
5 | 3                        # 7  (OR — infix operator)
bxor(5, 3)                   # 6  (XOR — prelude function)
bnot(5)                      # -6 (NOT — prelude function)
shl(1, 4)                    # 16 (shift left — prelude function)
shr(16, 2)                   # 4  (shift right — prelude function)
```

Note: `&` and `|` are infix operators. `bxor`, `bnot`, `shl`, `shr` are prelude functions. The `^^` operator is boolean XOR (not bitwise).

## One-letter aliases

| Alias | Full name | Example |
|-------|-----------|---------|
| `S` | split | `S("a,b,c", ",")` → `["a","b","c"]` |
| `J` | join | `J(",", [1,2,3])` → `"1,2,3"` |
| `R` | reverse | `R([1,2,3])` → `[3,2,1]` |
| `U` | unique | `U([1,2,2,3])` → `[1,2,3]` |
| `Z` | zip | `Z([1,2],[3,4])` → `[[1,3],[2,4]]` |
| `T` | transpose | `T([[1,2],[3,4]])` → `[[1,3],[2,4]]` |
| `F` | flatten | `F([[1,2],[3]])` → `[1,2,3]` |
| `D` | digits | `D(123)` → `[1,2,3]` |
| `P` | print | `P("hi")` (same as `p`) |
| `G` | group_by | `G([1,2,3,4], `a%2`)` → dict |
| `C` | combinations | `C([1,2,3], 2)` → `[[1,2],[1,3],[2,3]]` |
| `X` | permutations | `X([1,2,3])` → all 6 orderings |
| `W` | words (split on whitespace) | `W("hello world")` → `["hello","world"]` |
| `L` | lines (split on newline) | `L("a\nb\nc")` → `["a","b","c"]` |
| `N` | numbers (parse all ints) | `N("3 cats 7 dogs")` → `[3, 7]` |
| `I` | read all stdin | `I()` → entire stdin as string |

## Digits and bases

```
D(123)                       # [1, 2, 3]
D(255, 16)                   # [15, 15]
UD([1,2,3])                  # 123
UD([15,15], 16)              # 255
to_base(255, 16)             # "ff"
from_base("ff", 16)          # 255
```

## Combinatorics

```
X([1,2,3])                   # [[1,2,3],[1,3,2],[2,1,3],...] (6 permutations)
C([1,2,3,4], 2)              # [[1,2],[1,3],[1,4],[2,3],[2,4],[3,4]]
powerset([1,2,3])            # [[], [1], [2], [3], [1,2], [1,3], [2,3], [1,2,3]]
```

## Matrix / 2D operations

```
T([[1,2],[3,4]])             # [[1,3],[2,4]] (transpose)
rotate([1,2,3,4,5], 2)      # [3,4,5,1,2]
window([1,2,3,4,5], 3)      # [[1,2,3],[2,3,4],[3,4,5]]
```

## Infinite generators

```
from_n(0)                    # 0, 1, 2, 3, ... (must take/break)
from_n(5)                    # 5, 6, 7, 8, ...
cycle([1,2,3])               # 1, 2, 3, 1, 2, 3, ...
repeat_val(0)                # 0, 0, 0, 0, ...

# Usage:
take(from_n(1), 5)           # [1, 2, 3, 4, 5]
take(cycle([1,2]), 6)        # [1, 2, 1, 2, 1, 2]
```

## Tacit trains (fork / hook)

Point-free function composition for math-heavy golf:

```
# fork(f, g, h)(x) = g(f(x), h(x))
avg = fork(sum, f(a,b)->a/b, len)
avg([2, 4, 6])               # 4

# hook(f, g)(x) = f(x, g(x))
# "apply f to x and g(x)"
double_check = hook(f(a,b)->a==b, R)
double_check([1,2,1])        # true (list equals its reverse = palindrome!)
```

## String padding

```
"hi".pad(10)                 # "hi        " (right-pad)
"hi".lpad(10)                # "        hi" (left-pad)
"hi".cpad(10)                # "    hi    " (center)
"hi".lpad(5, "0")            # "000hi"     (custom fill)
```

## Min/max by key

```
min_by(["abc","z","hi"], `len(a)`)    # "z"
max_by([[1],[1,2,3],[1,2]], `len(a)`) # [1,2,3]
```

## Character arithmetic

```
"a" + 1                      # "b" (next char)
"z" - 1                      # "y" (prev char)
"A" + 32                     # "a" (case shift)
```

## Miscellaneous

```
# Flatten with depth
flat([[1,[2]],[3,[4,[5]]]], 1)  # [1,[2],3,[4,[5]]]
flat([[1,[2]],[3,[4,[5]]]], oo) # [1,2,3,4,5]

# Scan from right
sr(+, [1,2,3,4])             # [10, 9, 7, 4]

# For-each (side effects, returns und)
[1,2,3].each(`p(a)`)         # prints 1, 2, 3

# Regex findall shorthand
"abc 123 def 456" ~/ r/\d+/  # ["123", "456"]

# Divisors
divisors(12)                 # [1, 2, 3, 4, 6, 12]

# Auto-print in file mode
# Last non-und expression is automatically printed when running a .snf file
```

## List comprehensions

Python-style with guards, directly inside `[...]`:

```
[x*2 for x in 1..=5]                    # [2, 4, 6, 8, 10]
[x for x in 1..=20 if x%3==0]           # [3, 6, 9, 12, 15, 18]
[x+y for x in [1,2] for y in [10,20]]   # [11, 21, 12, 22]
[[i,j] for i in 0..3 for j in 0..3 if i<>j]  # pairs i!=j
```

## Where clauses (`whr`)

Bind helper values after the main expression:

```
area whr { area = w * h; w = 10; h = 5 }    # 50
```

## Declarative queries (`qr`)

Filter, map, and sort in one expression:

```
qr 1..=20 whr `a%2==0`                      # [2, 4, 6, ..., 20]
qr data whr `a>0` sel `a*2` srt `a`         # filter, double, sort
```

## Stack-based mode (`stk`)

Forth-style evaluation — values push, operators pop and push:

```
stk { 3 4 + }                # 7
stk { 2 3 * 5 + }            # 11
stk { 10 dup * }             # 100
```

Words: `dup`, `swap`, `rot`, `over`, `drop`, `nip`, `tuck`.

## Pipeline tee / tap

```
data |> tee(len, sum)         # [length, total] — apply multiple fns
data |> tap(`p(a)`) |> f     # debug print, pass data through
```

## Fork-map (parallel execution)

```
fk_map([1,2,3,4], `a*a`)     # returns list of Futures
# Each element processed in its own thread
m(futures, `aw a`)            # [1, 4, 9, 16]
```

## Dynamic scope (`dy`)

```
dy { greeting = "hi"; greet() }  # greet() can see 'greeting' without closure
```

## Logic variables

```
x = lv("x")
y = lv("y")
solve([x,y], `x.deref()+y.deref()==10`, 1..=9)
```

## Contracts on functions

```
df div(a, b) req b<>0 = a/b     # raises ContractErr if b==0
```

## Short method aliases

Every commonly-used method has a 2-3 char alias. Both long and short names work.

### String methods

| Long | Short | Example |
|------|-------|---------|
| `.split(sep)` | `.sp(sep)` | `"a,b".sp(",")` → `["a","b"]` |
| `.strip()` | `.tr()` | `" hi ".tr()` → `"hi"` |
| `.replace(a,b)` | `.rpl(a,b)` | `"hi".rpl("i","o")` → `"ho"` |
| `.starts(x)` | `.sw(x)` | `"hi".sw("h")` → `true` |
| `.ends(x)` | `.ew(x)` | `"hi".ew("i")` → `true` |
| `.repeat(n)` | `.rp(n)` | `"ab".rp(3)` → `"ababab"` |
| `.contains(x)` | `.has(x)` | `"hi".has("i")` → `true` |
| `.words()` | `.ws()` | `"a b".ws()` → `["a","b"]` |
| `.lines()` | `.ln()` | `"a\nb".ln()` → `["a","b"]` |
| `.chars()` | `.cs()` | `"abc".cs()` → `["a","b","c"]` |

### List methods

| Long | Short | Example |
|------|-------|---------|
| `.map(f)` | `.m(f)` | `[1,2,3].m(\`a*2\`)` → `[2,4,6]` |
| `.filter(f)` | `.fl(f)` | `[1,2,3].fl(\`a>1\`)` → `[2,3]` |
| `.reduce(f,i)` | `.rd(f,i)` | `[1,2,3].rd(\`a+b\`,0)` → `6` |
| `.contains(x)` | `.has(x)` | `[1,2,3].has(2)` → `true` |
| `.intersperse(v)` | `.isp(v)` | `[1,2,3].isp(0)` → `[1,0,2,0,3]` |
| `.group_by(f)` | `.gb(f)` | `[1,2,3,4].gb(\`a%2\`)` |
| `.sort_by(f)` | `.sb(f)` | `["cc","a"].sb(\`len(a)\`)` |
| `.take_while(f)` | `.tw(f)` | `[1,2,3,4].tw(\`a<3\`)` → `[1,2]` |
| `.drop_while(f)` | `.dw(f)` | `[1,2,3,4].dw(\`a<3\`)` → `[3,4]` |
| `.flat_map(f)` | `.fm(f)` | `[1,2].fm(\`[a,a*10]\`)` → `[1,10,2,20]` |

### Dict methods

| Long | Short | Example |
|------|-------|---------|
| `.filter_vals(f)` | `.fv(f)` | `d.fv(\`a>0\`)` |
| `.map_vals(f)` | `.mv(f)` | `d.mv(\`a*10\`)` |
| `.map_keys(f)` | `.mk(f)` | `d.mk(\`a.upr()\`)` |
| `.without(k)` | `.wo(k)` | `d.wo("key")` |
| `.merge(d2)` | `.mg(d2)` | `d.mg(d2)` |
| `.update(d2)` | `.up(d2)` | `d.up(d2)` (mutating) |

### Chaining example

```
[1,2,3,4,5,6,7,8,9,10]
  .fl(`a%2==0`)         # filter evens
  .m(`a*a`)             # square
  .tw(`a<50`)           # take while < 50
  .fm(`[a, -a]`)        # flat_map: each → [x, -x]
# → [4, -4, 16, -16, 36, -36]
```

## Try-pipe and Result helpers

```
5 |?> f(x) -> x * 2               # ["ok", 10]
0 |?> f(x) -> 1/x                 # ["err", "division by zero"]

unwrap(["ok", 42])                 # 42
unwrap_or(["err", "bad"], -1)      # -1
is_ok(["ok", 5])                   # true
is_err(["err", "x"])               # true
```

## Quantifiers

```
some x in [1,2,3,4,5] if x > 3    # true
every x in [1,2,3] if x > 0       # true
```

## Defer (scope-exit cleanup)

```
{ defer p("cleanup"); p("work") }  # prints "work" then "cleanup"
```

## Python module aliases

Two-char aliases auto-import Python modules on first use. No `us` or `py.import` needed.

| Alias | Module | Example |
|-------|--------|---------|
| `ma` | `math` | `ma.sqrt(16)` → `4.0` |
| `js` | `json` | `js.dumps([1,2])` → `"[1, 2]"` |
| `os` | `os` | `os.getcwd()` |
| `sy` | `sys` | `sy.argv` |
| `rn` | `random` | `rn.randint(1,10)` |
| `dt` | `datetime` | `dt.datetime.now()` |
| `rq` | `requests` | `rq.get("http://...")` |
| `n8` | `numpy` | `n8.array([1,2,3])` |
| `pd` | `pandas` | `pd.read_csv("f.csv")` |
| `pl` | `matplotlib.pyplot` | `pl.plot(xs, ys)` |
| `sq` | `sqlite3` | `sq.connect(":memory:")` |
| `cs` | `csv` | `cs.reader(file)` |
| `fs` | `pathlib` | `fs.Path(".")` |
| `it` | `itertools` | `it.chain(a, b)` |
| `ft` | `functools` | `ft.lru_cache` |
| `ic` | `collections` | `ic.Counter(list)` |
| `th` | `threading` | `th.Thread(...)` |
| `ap` | `asyncio` | `ap.run(...)` |
| `cp` | `subprocess` | `cp.run(cmd)` |
| `pk` | `pickle` | `pk.dumps(obj)` |
| `hs` | `hashlib` | `hs.md5(b"hi")` |

## Golf comparison

FizzBuzz:
```
# Verbose (47 chars):
for i in 1..=15 { p(mt [i%3,i%5] { [0,0] -> "FizzBuzz", [0,_] -> "Fizz", [_,0] -> "Buzz", _ -> i }) }

# Terse with golf features (shorter with aliases + backtick):
m(1..=15, `mt[a%3,a%5]{[0,0]->"FizzBuzz",[0,_]->"Fizz",[_,0]->"Buzz",_->a}`).each(P)
```
