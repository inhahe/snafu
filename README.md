# Snafu

A terse, dynamic, multi-paradigm language with ~165 features spanning 15+ paradigms. Inspired by Python, K/APL, Haskell, Lisp, and INTERCAL.

## What Makes Snafu Unique

Most languages pick 2-3 paradigms. Snafu picks all of them — and adds features no other language has:

### Infinite meta-circular interpreter stack

The interpreter is a Snafu function. You can modify it — and modify the interpreter that interprets the interpreter, ad infinitum:

```
lv(2)                              # 2 levels: program → meta-interpreter → host
isrc[1] = "f(node, scope) -> { p(\">> \" + ast_src(node)); eval_ast(node, scope) }"
x = 5                              # prints ">> x = 5" then executes

lv(3)                              # 3 levels: program → meta-interp 1 → meta-interp 2 → host
isrc[2] = "f(node, scope) -> { p(\"L2: \" + ast_src(node)); eval_ast(node, scope) }"
# Level 2 interprets level 1, which interprets your program.
# Modify isrc[n] at ANY level to change how that level works.
# Each level is a Snafu function you can replace, inspect, or transform.
```

### N-dimensional instruction pointer

Code isn't limited to linear execution. Jump in 2D (or N-D) across your program:

```
# 1D jumps (like goto but by index)
x = 0; jr(2); x = 99; x = 1; x   # skips x=99, returns 1

# 2D jumps (row, column in the source grid)
ja(3, 0)                           # jump to row 3, column 0
jr(1, 2)                           # move 1 row down, 2 statements right

# Lines are rows, ;-separated statements are columns.
# Combined with goto/lbl for labeled jumps.
```

### Fork the universe

```
x = 1
future = fk { x = 99; x }         # runs in a deep-copied parallel universe
[aw future, x]                     # [99, 1] — original x unchanged
```

### INTERCAL's comefrom — reverse goto

```
x = 0
cf inc                             # "when 'inc' is reached, come HERE instead"
x = 99                             # comefrom redirects here after label 'inc' fires
goto done
lbl inc                            # comefrom intercepts — jumps back to 'x = 99'
x = x + 1                          # this runs when cf first jumps to the label
lbl done
x                                  # → 1 (comefrom redirected flow)
```

### APL-style array operators

```
+/ [1, 2, 3, 4, 5]                # 15  (reduce with +)
+\ [1, 2, 3, 4, 5]                # [1, 3, 6, 10, 15]  (scan / prefix sums)
[1,2,3] *. [4,5,6]                # [4, 10, 18]  (element-wise multiply)
[1,2,3] *.. [4,5]                  # [[4,5],[8,10],[12,15]]  (outer product)
```

### Algebraic effects with resumable continuations

```
ef Choose(options)
hd {
    a = pf Choose([1, 2, 3])       # perform effect — suspends here
    a * a
} with {
    Choose(opts) k -> m(opts, k)   # handler calls k() for EACH option
}
# → [1, 4, 9]  — nondeterministic choice!
```

### Program history and rollback

Snapshot your program's entire state, rewind to any point, or auto-record every step:

```
x = 1; ps()                       # push state snapshot
x = 2; ps()
x = 99
restore(sa(-2))                    # rewind to first snapshot
x                                  # → 1

# Auto-record every assignment (with bounded memory):
auto_record(true, 1000)            # keep last 1000 snapshots
# ... program runs ...
restore(sa(-50))                   # rewind 50 steps

# Named checkpoints:
ps("before_risky_op")
risky_operation()
restore(sp("before_risky_op"))     # undo if something went wrong

# Memory management:
ps_max(500)                        # cap buffer at 500 snapshots
ps_size()                          # check current buffer size
ps_clear()                         # flush all snapshots
```

### Reactive variable triggers

```
log = []
on x.ch { log.psh(x) }            # fire whenever x is assigned
x = 1; x = 2; x = 3
log                                # [1, 2, 3]
```

### Backtick lambdas + one-letter aliases for code golf

```
[1,2,3,4,5].fl(`a>2`).m(`a*10`)   # [30, 40, 50]
+/ D(12345)                        # 15 (digit sum in 11 chars)
T([[1,2],[3,4]])                   # [[1,3],[2,4]] (transpose)
```

### Logic variables + constraint solving

```
x = lv(); y = lv()
solve([x, y], `x.val() + y.val() == 10 && x.val() * y.val() == 21`, 0..=10)
[x.val(), y.val()]                 # [3, 7]
```

### Forth-style stack mode

```
stk { 3 4 + 2 * }                 # 14
stk { 10 dup * }                   # 100
```

### Function inverse — algebraically derived

```
f_fn = f(x) -> x * 2 + 10
inv = f_fn^-1                      # automatically inverts the math
inv(20)                            # 5.0
```

...plus pattern matching, sum types, generators, prototypes, macros, decorators, contracts, context managers, dynamic scoping, persistent variables, try-pipe error handling, actors, channels, green threads, execution sets, and much more.

## Quick Start

```
python snafu.py                    # REPL
python snafu.py script.snf         # run a file
python snafu.py -e "1 + 2"         # eval expression
```

## Language Tour

### Variables and Arithmetic

Snafu has integers (arbitrary precision), floats, rationals, and complex numbers. Division of integers produces exact rationals.

```
x = 42
pi = 3.14159
ratio = 1 / 3                     # Rat(1, 3), not 0.333...
z = 1 + 2i                        # complex
hex = ffh                          # 255
bin = 1010b                        # 10
```

### Strings with Interpolation

Double-quoted strings interpolate `${expr}` (or bare `$name`). Single-quoted strings are literal.

```
name = "world"
p("Hello, ${name}!")               # Hello, world!
p("2 + 2 = ${2 + 2}")             # 2 + 2 = 4
```

### Collections

A single `[...]` literal covers lists, dicts, and mixed collections. `{...}` is always a code block.

```
nums = [1, 2, 3, 4, 5]
dict = ["name": "Alice", "age": 30]
mixed = [1, 2, "key": "val"]
nums[0]                            # 1
dict["name"]                       # "Alice"
```

### Control Flow

```
# if / elif / else
if x > 0 { p("pos") }
eli x == 0 { p("zero") }
el { p("neg") }

# for loop with ranges
for i in 1..=5 { p(i) }

# while
wh x > 0 { x = x - 1 }

# pattern matching
mt value {
  0          -> "zero"
  1 | 2 | 3  -> "small"
  n if n < 0 -> "negative"
  _          -> "other"
}
```

### Functions

Three forms, from verbose to terse.

```
# named function
df square(x) = x * x

# anonymous function
double = f(x) -> x * 2

# backtick lambda (shortest -- for golf and pipelines)
m([1,2,3], `a*2`)                  # [2, 4, 6]
```

### Pipelines and Composition

```
[1,2,3,4,5] |> fl(`a%2==0`) |> m(`a*a`)   # [4, 16]

# compose functions with +
both = (f(x) -> x + 1) + (f(x) -> x * 2)
```

### Pattern Matching and Sum Types

Destructure lists, dicts, and sum type variants in `mt` blocks or function heads.

```
sm Shape = Circle(r) | Rect(w, h)

df area(s) {
  mt s {
    Circle(r)  -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }
}

area(Circle(5))                    # 78.53975
```

### Generators

```
ct fibonacci() {
  a = 0; b = 1
  lp {
    y a                            # yield
    tmp = a; a = b; b = tmp + b
  }
}

take(fibonacci(), 8)               # [0, 1, 1, 2, 3, 5, 8, 13]
```

### APL-Style Array Operations

Operator modifiers turn any arithmetic op into element-wise, reduce, scan, or outer product.

```
[1,2,3] +. [10,20,30]             # [11, 22, 33]  element-wise
+/ [1,2,3,4]                      # 10             reduce (sum)
+\ [1,2,3,4]                      # [1, 3, 6, 10]  scan (running sum)
[1,2,3] *.. [4,5]                 # [[4,5],[8,10],[12,15]]  outer product
```

### Error Handling

```
ty {
  result = risky_operation()
} ex ValErr e {
  p("caught: " + str(e))
} fi {
  cleanup()
}
```

### Prototype-Based OOP

No classes -- objects clone from prototypes via `new`.

```
Animal = new()
Animal.name = "unknown"
Animal.speak = f(self) -> self.name + " says hello"
dog = new(Animal); dog.name = "Rex"
p(dog.speak(dog))                  # Rex says hello
```

### Algebraic Effects

Effects generalize exceptions, generators, and async into one mechanism.

```
ef Ask(prompt)
hd {
  name = pf Ask("what's your name?")
  p("Hello, " + name)
} with {
  Ask(q) k -> k("Alice")          # resume with value
}
```

### Concurrency

```
h = gt { expensive_computation() } # spawn thread, get future
result = aw h                      # await result

c = ch()                           # channel
gt { c.send(42) }; p(c.recv())    # 42
```

### Code Golf Features

One-letter aliases, backtick lambdas, auto-coercion, and method shorthands.

```
# FizzBuzz in one line
m(1..=15, `mt[a%3,a%5]{[0,0]->"FizzBuzz",[0,_]->"Fizz",[_,0]->"Buzz",_->a}`).each(P)

# One-letter aliases
S("a,b,c", ",")                   # split -> ["a","b","c"]
R([1,2,3])                        # reverse -> [3,2,1]
F([[1,2],[3]])                     # flatten -> [1,2,3]
D(255, 16)                        # digits -> [15,15]
```

### Python Module Aliases

21 two-char aliases auto-import Python modules on first use:

```
ma.sqrt(16)                        # math.sqrt
js.dumps([1,2,3])                  # json.dumps
rn.randint(1, 100)                 # random.randint
os.getcwd()                        # os.getcwd
# Full list: ma js os sy rn dt rq n8 pd pl sq cs fs it ft ic th ap cp pk hs
```

See [GOLF_SYNTAX.md](GOLF_SYNTAX.md) for the complete alias table.

### List Comprehensions

```
[x*x for x in 1..=5]              # [1, 4, 9, 16, 25]
[x for x in 1..=20 if x%3==0]     # [3, 6, 9, 12, 15, 18]
```

### Self-Modification

Programs can read and manipulate their own source, AST, and even their interpreter at runtime.

```
p(src)                             # print own source code
node = ast_of(1 + 2)              # get AST without evaluating
node.rhs = ast_of(10)              # modify it
eval_ast(node)                     # evaluate modified AST -> 11

# Modify the interpreter itself (in Snafu, not Python!):
lv(2)                              # enable meta-interpretation
isrc[1] = "f(node, scope) -> { p(\">> \" + ast_src(node)); eval_ast(node, scope) }"
x = 5                              # prints ">> Assign(...)" then executes
```

### Universe Forking

Fork execution into parallel branches with a deep-copied scope.

```
future = fk { expensive_computation() }
result = aw future
```

### Decorators, Memoization, and Method Chaining

```
@memo df fib(n) { if n <= 1 { n } el { fib(n-1) + fib(n-2) } }
fib(50)                            # instant -- cached

[1,2,3,4,5,6,7,8,9,10].fl(`a%2==0`).m(`a*a`).tw(`a<50`)
# -> [4, 16, 36]
```

### Reactive Triggers and Stack-Based Mode

```
x = 0; on x.ch { p("x changed!") }
x = 5                             # prints: x changed!

stk { 3 4 + }                     # 7 (Forth-style)
```

## Full Feature List

### Core Types
- Arbitrary-precision integers (`Int` / `Big`)
- IEEE 754 floats (`Flt`)
- Exact rationals (`Rat`)
- Complex numbers (`Cx`)
- Strings with `${expr}` interpolation
- Booleans (`true`, `false`)
- Undefined (`und`) with silent propagation
- Infinity (`oo`), NaN
- Bytes literals (`b"..."`)
- Symbols

### Collections
- Unified `[...]` literal for lists, dicts, and mixed
- Slicing with step and sliding windows (`l[a:b:w:i]`)
- Multi-index access (`l[1,3,5]`)
- Frozen (persistent/immutable) collections (`fr[...]`)
- Sets via `st([...])` with union/intersection/difference
- Two-way dicts (`.inv`, `~d`)
- Stack/queue ops (`.psh`, `.pop`, `.pfr`, `.ppr`)
- Variables as stacks (`psh`/`pop`)

### Control Flow
- `if`/`eli`/`el` conditionals
- `for`/`in` iteration with destructuring
- `wh` (while), `un` (until), `lp` (loop)
- `br` (break), `cn` (continue), `r` (return)
- `bf`/`bt`/`af` (before/between/after loop blocks)
- `goto`, `cf` (comefrom), `lbl` (label)
- `defer` (scope-exit cleanup)
- `some`/`every` quantifiers

### Functions
- `df` named functions with defaults, `*args`, `**kwargs`
- `f(params) -> expr` anonymous functions
- Backtick lambda (`` `a*2` ``)
- Implicit parameters (`a`, `b`, `c`)
- Named return values (`r x=1, y=2`)
- Closures
- Decorators (`@decorator`)
- Memoization (`memo`)
- Tail-call semantics

### Pattern Matching
- Literal, variable, wildcard (`_`) patterns
- List destructuring (`[h, ...t]`)
- Dict destructuring (`{name: n, **rest}`)
- Sum type variant matching (`Some(x)`)
- Guard patterns (`n if n > 0`)
- Or-patterns (`1 | 2 | 3`)
- As-patterns (`all@[h, ...t]`)
- Regex patterns
- Pattern-matched function heads

### Type System
- Sum types / algebraic data types (`sm`)
- Protocols (`pr`) with default implementations
- Protocol implementation (`im`) -- open polymorphism
- Auto-derivation (`dv [Eq, Show, Ord, ...]`)
- Multiple dispatch
- Coercion protocol (`cv`)
- Structural protocol fallback

### Object Model
- Prototype-based OOP (`new`), prototype chain inheritance
- Method-missing (`__mm__`), context managers (`wi`/`as`)

### Error Handling
- `ty`/`ex`/`fi` (try/except/finally)
- `rs` (raise), `fr` (from -- chained exceptions)
- Strict mode (`sd`) -- raises on `und` access
- Loose mode (`ld`) -- restores silent propagation
- Try-pipe (`|?>`) returning `["ok", val]` / `["err", msg]`
- Result helpers (`unwrap`, `unwrap_or`, `is_ok`, `is_err`)
- Contracts (`req`/`ens` -- pre/postconditions)

### Algebraic Effects
- Effect declaration (`ef`)
- Perform (`pf`) -- raise an effect
- Handle (`hd ... with { ... }`)
- Resumable continuations (`k`)
- Iteration as effects (`StopItor`)

### Iterators and Generators
- `ct` (coroutine/generator declaration)
- `y` (yield), `yf` (yield from)
- Bidirectional generators (`.sd(val)`)
- Lazy ranges (`1..10`, `1..=10`)
- List comprehensions with guards
- Infinite generators (`from_n`, `cycle`, `repeat_val`)
- `take`, `drop`, `take_while`, `drop_while`

### APL-Style Array Operations
- Element-wise (`+.`, `*.`, `==.`, etc.)
- Reduce (`+/`, `*/`, etc.)
- Scan (`+\`, `*\`, etc.)
- Outer product (`+..`, `*..`, etc.)
- Scalar extension / broadcasting

### Pipeline and Composition
- Pipeline operator (`|>`)
- Function composition (`+`)
- `tee` (apply multiple functions)
- `tap` (side-effect pass-through)
- Tacit trains (`fork`, `hook`)

### Concurrency
- Green threads (`gt`)
- Futures and await (`aw`)
- Channels (`ch`) with send/recv
- Channel select (`sl`)
- Execution sets (`xs { ... }`) -- parallel statements
- Universe forking (`fk`)
- Fork-map (`fk_map`)
- Actors (`actor`)

### Reactive Programming
- `on x.ch { ... }` -- triggers on variable change; `on expr { ... }` -- condition triggers
- `of x.ch` / `of all` -- remove triggers

### Metaprogramming and Self-Modification
- `ev` / `.ca()` -- eval strings as code
- `src` / `ast` -- access own source and AST at runtime
- `ast_of`, `eval_ast`, `ast_new`, `ast_src` -- AST manipulation
- Macros (`mc`), variable-variables (`$name`), dynamic scoping (`dy`)
- Lexical scoping, `sc`/`ca`/`tp` scope access, modules (`us`/`xp`)

### Code Golf Toolbox
- One-letter aliases (`S`, `J`, `R`, `U`, `Z`, `T`, `F`, `D`, `P`, `W`, `L`, `N`, `I`, `G`, `C`, `X`)
- Short method aliases (`.sp`, `.tr`, `.rpl`, `.m`, `.fl`, `.rd`, etc.)
- Backtick lambdas
- Auto-coercion (`"123" + 1` -> `124`)
- Character arithmetic (`"a" + 1` -> `"b"`)
- Null-coalesce (`??`) and safe navigation (`?.`)
- Auto-print last expression in file mode
- Digits/undigits (`D`/`UD`), base conversion
- Combinatorics (`X`, `C`, `powerset`)
- Where clauses (`whr`)
- Declarative queries (`qr ... whr ... sel ... srt`)
- Stack-based mode (`stk`)

### Debugging and State
- Breakpoints (`bp`), debugger protocol (`Db`), tracer, profiler, time-travel debugger
- Execution recording (`rec`/`play`)
- State snapshots (`ps`/`sa`/`sp`), `save_state`/`load_state`, lazy values (`lazy`/`force`)
- JSON serialization (`to_json`/`from_json`)

### Numeric and Math
- Trig, hyperbolic, `sqrt`, `cbrt`, `exp`, `log`, `ln`, `log2`, `log10`
- `abs`, `sgn`, `floor`, `ceil`, `round`, `trunc`, `fact`, `divisors`
- Symbolic expressions with lazy reduction

### Logic, Regex, and More
- Logic variables (`lv`), unification (`unify`), constraint solver (`solve`)
- Regex literals (`r/pattern/flags`), match (`=~`), findall (`~/`), destructuring groups
- Heredocs/nowdocs, matrix/tensor ops (`mx`/`tnsr`), transducers, lenses, signals/slots, atoms

## Files

| File | Description |
|------|-------------|
| `snafu.py` | The interpreter (~7200 lines of Python). Lexer, parser, evaluator, and prelude all in one file. |
| `SPEC.md` | The full language specification (v1.7). Source of truth for all semantics. |
| `GOLF_SYNTAX.md` | Reference card for code golf features: backtick lambdas, one-letter aliases, method shorthands, combinatorics. |
| `CONCEPTS.md` | Design notes for 20 major features (pattern matching, effects, protocols, etc.). Background reading. |
| `GRAMMAR.epeg` | Formal grammar in extended PEG notation. |
| `ROADMAP.md` | Implementation status and planned work. |
| `examples/` | Example programs: `fizzbuzz.snf`, `showcase.snf`, `safe_div.snf`, `tree.snf`. |
| `tests/` | Test suite. |

## Links

- [SPEC.md](SPEC.md) -- full language specification
- [GOLF_SYNTAX.md](GOLF_SYNTAX.md) -- code golf reference
- [CONCEPTS.md](CONCEPTS.md) -- feature design notes
- [examples/](examples/) -- example programs
