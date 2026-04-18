# Snafu — new feature concepts

Reference document for the 20 programming concepts being added to Snafu on top of the original notes. Each section is self-contained; cross-references use the `NN-name` identifiers.

## Contents

1. [Pattern matching](#01--pattern-matching)
2. [Multiple dispatch](#02--multiple-dispatch)
3. [Pipeline operator `|>`](#03--pipeline-operator-)
4. [Sum types (algebraic data types / variants)](#04--sum-types-algebraic-data-types--variants--tagged-unions)
5. [Lenses (optics)](#05--lenses-aka-optics)
6. [Algebraic effects and handlers](#06--algebraic-effects-and-handlers)
7. [Protocols (Clojure-style)](#07--protocols-clojure-style)
8. [Context managers](#08--context-managers)
9. [Exceptions](#09--exceptions)
10. [Async/await over effects + channels](#10--asyncawait-as-sugar-over-effects--channels)
11. [Functional reactive programming](#11--functional-reactive-programming--reactive-streams)
12. [Transducers](#12--transducers)
13. [Regex + Perl-style operators](#13--regex-as-first-class--perl-style-operators)
14. [String interpolation](#14--string-interpolation)
15. [Iterator protocol](#15--iterator-protocol)
16. [Module system + Python compatibility](#16--module-system-with-python-compatibility)
17. [eval and scope](#17--eval-and-scope)
18. [Tail calls by semantics](#18--tail-calls-by-semantics)
19. [Debugging protocol](#19--debugging-protocol)
20. [Identity vs equality vs deep equality](#20--identity-vs-equality-vs-deep-equality)

---

# 01 — Pattern matching

Pattern matching lets you *test* a value against structural shapes and *destructure* it — extracting pieces — in the same expression. It generalizes if/elif chains, type checks, tuple unpacking, and variant discrimination.

## Forms

- **Literal**: `1`, `"foo"`, `und`, `true`, `false` — matches exactly.
- **Variable**: `x` — matches anything, binds it to `x`.
- **Wildcard**: `_` — matches anything, binds nothing.
- **As-pattern**: `all@[h, t]` — binds the whole thing AND destructures.
- **List**: `[x, y, z]` (exact length), `[h, ...t]` (head/tail), `[x, _, y]` (skip middle).
- **Dict / ordered-set**: `{k1: v1, k2: v2}`, `{name: n, **rest}`.
- **Typed**: `Num(x)`, `Str(s)` — matches by type and binds.
- **Sum variant**: `Some(x)`, `Err(msg)` — see `04-sum-types.md`.
- **Guard**: `x if x > 0 -> ...` — pattern matches AND guard is truthy.
- **Or-pattern**: `1 | 2 | 3 -> ...`.
- **Regex**: `r/(\d+)-(\d+)/ as [a, b] -> ...` — regex groups as a list.
- **Nested**: `{user: {name: n, age: a if a >= 18}}`.

## Snafu syntax

```
mt x {
  0                    -> "zero"
  1 | 2 | 3            -> "small"
  n if n < 0           -> "negative"
  [h, ...t]            -> "list with head " + h
  {name: n, age: a}    -> "person " + n + " aged " + a
  Some(v)              -> "got " + v
  None                 -> "nothing"
  _                    -> "other"
}
```

Also at function heads (Haskell-style — your notes already have this):

```
fct 0 = 1
fct n = n * fct(n - 1)

len []         = 0
len [h, ...t]  = 1 + len(t)
```

This is sugar for multiple dispatch + `mt` on the first arg.

## Why Snafu wants it

- Replaces long `if`/`elif`/`isinstance` ladders — shorter and safer.
- Makes sum types/variants actually usable.
- Pattern-match on *source* forms: `mt ast_node { Call(fn, args) -> ... }` — critical for macros and the self-modifying interpreter.
- Destructuring is already elsewhere in your notes (`a, *b, c = [1,2,3,4]`); `mt` generalizes it.

## Exhaustiveness

Since Snafu is dynamic, non-exhaustive `mt` falls through to `und` (or raises `MatchErr` in `sd` strict mode). No compile-time check; you get runtime behaviour.

## Bindings escape the arm

A variable bound in a pattern is in scope only inside that arm. If the same name appears in multiple arms it's fine — different bindings.

## Integration with other features

- **Multiple dispatch**: `fct 0 = ...; fct n = ...` is sugar for two `fct` methods dispatched by value/type.
- **Algebraic effects**: a handler's cases are a `mt` on the effect type.
- **Regex**: regex match objects destructure directly.
- **Lenses**: `lens(pat)` builds a prism that only focuses if the pattern matches.


---

# 02 — Multiple dispatch

Functions (especially operators) pick their implementation based on the runtime types of **all** arguments, not just the first (the "receiver"). CLOS (Common Lisp), Julia, Clojure multimethods, and Dylan all work this way.

## Contrast

**Single dispatch** (Python, Java, C++, Smalltalk):
```
a.plus(b)              # picks method based on type of a only
```
If `a` is a Matrix and `b` is a Scalar, `Matrix.plus` runs and must itself figure out `b`'s type. If you want `Scalar.plus(Matrix)` instead you hack around with `__radd__` or similar reverse-methods.

**Multiple dispatch**:
```
plus(a, b)             # picks method based on types of BOTH a and b
```
You define `plus(Matrix, Scalar)`, `plus(Scalar, Matrix)`, `plus(Matrix, Matrix)` — each is its own method, no reverse-method hack.

## Why Snafu needs it

Your notes already sketch it:
```
op['*', Matrix, Scalar] = l a*b
op['*', Scalar, Matrix] = l a*b
op['*', Quaternion, Vec3] = l ...
```

Single dispatch is painful for:
- Arithmetic across number types (bignum × complex × quaternion × matrix)
- Collection operations (`union(Set, FrozenSet)`, `concat(Str, List)`)
- Pretty-printing / formatting / serialization
- Comparison across heterogeneous types

Multiple dispatch is the correct abstraction here.

## Snafu proposal

Every operator is sugar for a multi-dispatched function. `a + b` = `add(a, b)`. Define specialized methods:

```
df add(Num a, Num b)       = a + b           # builtin number add
df add(Matrix a, Matrix b) = matmul(a, b)
df add(Str a, Str b)       = cat(a, b)
df add(Matrix a, Num b)    = scalar_mul(a, b)
df add(Num a, Matrix b)    = scalar_mul(b, a)
```

Pattern-matching function heads (Haskell-style from your notes) are **the same feature** — a def where one argument position has a concrete value is a method dispatched on that value:

```
df fct 0 = 1
df fct n = n * fct(n - 1)
```

Value-level pattern heads dispatch on equality; type-level heads dispatch on type; both coexist.

## Specificity

When multiple methods match, the **most specific** wins. Specificity is determined by the prototype chain depth:
- Exact-value match beats type match
- Derived-type match beats ancestor-type match
- Multiple-arg specificity is per-argument; ties on some args, winner on others

If two methods are equally specific (incomparable partial order), Snafu raises `DispatchAmbig` — you add a tie-breaker method.

## Open extension

Because dispatch is at the call site (not "method belongs to class"), you can add new methods for existing types from any module. Want `add(MyType, Num)` for a type you didn't write? Just `df` it in your own module. This is what Clojure calls "open polymorphism" and it's why protocols + multi-dispatch are the right pair.

## Cost

Runtime type-inspection on every call. Snafu doesn't care — no-perf is the design. The interpreter can cache dispatch decisions per call-site if we want later.

## Interaction with algebraic effects

Effect handlers dispatch on effect type. Same machinery.


---

# 03 — Pipeline operator `|>`

```
x |> f |> g |> h     ==     h(g(f(x)))
```

Left-to-right flow instead of inside-out nesting. Elixir, F#, OCaml, Julia, Hack, Gleam all have it. Unix pipes are the same idea.

## Variants

Three flavours, different languages pick different defaults:

1. **First-arg pipe** (`|>`): `x |> f(a, b)` = `f(x, a, b)` — Elixir style. `x` inserted as the first arg.
2. **Last-arg pipe** (`|>>`): `x |>> f(a, b)` = `f(a, b, x)` — Haskell / OCaml style.
3. **Placeholder pipe**: `x |> f(a, _, b)` — explicit slot. Most flexible, noisier.

## Snafu proposal

Take `|>` as first-arg by default, `_` as explicit slot:

```
x |> f                       # f(x)
x |> f(opts)                 # f(x, opts)          (first-arg default)
x |> f(opts, _)              # f(opts, x)          (explicit slot)
x |> f(a, _, b)              # f(a, x, b)
x |> f(_, _)                 # f(x, x)             (all slots get x)
```

Bare name auto-calls: `x |> f` means `f(x)`, not "reference f and pipe x into nothing".

## Why it matters

- Flat chain reads like English: `data |> parse |> validate |> normalize |> save`
- Pairs with function composition (`+` in your notes): `x |> (f + g + h)` is the same
- Eliminates a class of nesting bugs where you got the argument order wrong

## Multi-line chains

Newlines before `|>` are OK (statement continuation):
```
data
  |> parse
  |> validate(schema)
  |> normalize
  |> save(db)
```

## Piping into async

If the piped-into function returns a future, the next stage auto-awaits:
```
url |> fetch |> parse_json |> handle        # awaits fetch and parse_json implicitly
```

## Piping into effects

The pipeline itself is a normal expression, so it participates in any surrounding handler. A `do` inside any stage performs up to the enclosing `hd`.

## Interaction with transducers

Transducers compose with `+`, not `|>`:
```
tdr = xm(double) + xfl(pos) + xtk(10)
data |> tdr.al                               # apply the whole pipeline
```

Keep `|>` for value flow, `+` for transformer composition.


---

# 04 — Sum types (algebraic data types / variants / tagged unions)

A **sum type** is a type that can be exactly one of several named shapes, each optionally carrying its own data.

Classic examples:
```
Maybe  = Some(x)      | None
Result = Ok(value)    | Err(message)
Shape  = Circle(r)    | Rect(w, h)  | Triangle(a, b, c)
AST    = Num(n) | Sym(s) | Call(fn, args) | If(c, t, e) | Fn(params, body)
Tree   = Leaf         | Node(left, value, right)
```

## Contrast

- **Product type**: has all its fields at once. Tuples `(x, y, z)` and records `{name, age, email}` are products.
- **Sum type**: is exactly one of several shapes at a time. Each shape is called a *variant* or *constructor*.
- **Class hierarchy**: the OO workaround for sum types. Every variant becomes a subclass. Pros: familiar. Cons: anyone can add new subclasses (no closed set), no exhaustiveness, each variant drags an object-identity / shared-vtable layer, and `isinstance` chains are clunky compared to pattern matching.

## Why you want them

- **Parser ASTs**: every node is exactly one kind. Sum types are the canonical shape.
- **Error handling**: `Ok | Err` instead of exceptions or null.
- **`Maybe`**: "might not have a value" without using `und` for everything.
- **State machines**: each state is a variant with its own data.
- **Replacing flag+payload tricks**: instead of `{kind: "circle", radius: 5, w: null, h: null}`, have `Circle(5)` and `Rect(w, h)` with no dead fields.

## Snafu proposal

Declare with `sm`:

```
sm Maybe    = Some(v) | None
sm Result   = Ok(v)   | Err(e)
sm Tree     = Leaf    | Node(left, value, right)
sm AST      = Num(n)  | Sym(s) | Call(fn, args) | If(c, t, e)
```

Variants become two things at once:

1. **Constructors** (callable): `Some(5)` builds a value.
2. **Patterns** (for `mt`): `Some(x)` destructures.

Variants inherit from their declared sum type, which inherits from `obj`. So `Some(5).p == Maybe`, `Leaf.p == Tree`.

## Usage

```
m = Some(5)

mt m {
  Some(v)   -> p("got " + v)
  None      -> p("nothing")
}
```

With pattern-matching function heads + multiple dispatch:
```
df depth(Leaf _)           = 0
df depth(Node(l, _, r))    = 1 + max(depth(l), depth(r))
```

## Recursive sum types

`Tree` refers to itself. Fine — constructors can take arguments of the parent sum type.

## Parameterized variants

Not a static-type language, so "`Maybe a`" is just `Maybe` — the contained value is whatever you put in. No parameterization at the type level is needed.

## Interaction with protocols

```
pr Show {
  show(self)
}

im Show for Maybe {
  show(Some(v)) = "Some(" + show(v) + ")"
  show(None)    = "None"
}
```

The `im` uses `mt`-style heads to dispatch on variants.

## Interaction with lenses

A **prism** is a lens that focuses on a particular variant of a sum type. `prism(Some)` gets the inner value if the outer is `Some`, else returns nothing. Write `name = lens(_.user) + prism(Some) + lens(_.name)` — traverse into a sum type transparently.


---

# 05 — Lenses (aka optics)

A **lens** is a first-class value representing *how to reach a nested piece of data* — usable for both reading and writing.

```
nm = lens(_.user.address.city)
nm.gt(rec)                       # deep read
nm.st(rec, "Paris")              # returns a modified record
nm.md(rec, str.upr)              # applies a function through the lens
```

Since Snafu mutates by default, `.st` can mutate in place rather than returning a new record. But the *composability* of lenses is the win, not immutability.

## Composition

Lenses compose like function composition:

```
a = lens(_.user)
b = lens(_.address)
c = lens(_.city)
pc = a + b + c                   # or a |> b |> c, same thing
pc.gt(rec)                       # rec.user.address.city
```

Use the `_` placeholder-lens builder, or pass explicit access paths.

## Why Snafu wants them

- **Generalizes multi-index writes** from the notes: `l[12,7,5] = (a,b,c)` becomes a traversal lens over specified indices.
- **Pairs with `.=` operator** from the notes: `rec .= lens(_.user.name) => "Bob"` — update-through-lens in place.
- **Deep transformations** become one-liners: `pc.md(rec, upr)`.
- **Uniform across data kinds**: works on dicts, lists, sum-type variants, records — the lens is the abstraction, not the target.
- **Essential once we have sum types**: you want to reach into `Some(Some(x))` without three layers of unwrap.

## Optic kinds

The Haskell optics library has a tower; Snafu can expose a subset:

- **Lens**: focuses on exactly one value. Always succeeds. Record field access.
- **Prism**: focuses on a variant of a sum type. May or may not hit. `prism(Some)` gets the inner value if the outer is `Some`.
- **Traversal**: focuses on zero or more values. Walks into many at once. `traverse(all)` over a list; `.md` maps the function across all foci.
- **Iso**: a reversible mapping. `list <-> tuple`, `celsius <-> fahrenheit`.

Start with lens + traversal, add prism with sum types, iso later.

## Snafu syntax for construction

Your notes already propose `(_.foo.bar[3])` as a lens builder. Two forms:

```
nm = lens(_.user.name)           # explicit lens(...) call
nm = _.user.name                 # bare _-path, auto-lens when used as one
```

The bare form works because `_` is a sentinel: `_.user.name` builds a lens expression, not evaluates anything. The first `_` access starts lens-mode; subsequent `.` / `[]` extend the path. Any non-access operation closes it back to a value.

## Traversals

```
evens = traverse(l => [i for i in 0..len(l) step 2])   # all even indices
evens.md(list, double)                                  # double all evens

all_names = lens(_.users) + traverse(all) + lens(_.name)
all_names.md(rec, upr)                                  # uppercase all user names
```

## Interaction with `.=`

```
rec.user.name .= "Bob"           # in-place, no lens needed
(_.user.name).st(rec, "Bob")     # same effect via lens
rec .= (_.user.name) => "Bob"    # "modify rec through this lens"
```

## Interaction with pattern matching

Prisms and patterns have overlap. `mt` with a `Some(x)` pattern reads like a prism. The distinction: patterns are single-use in a `mt`; lenses are stored and composed. Keep both; they're different jobs.


---

# 06 — Algebraic effects and handlers

The single most-general mechanism in the concept list. Subsumes exceptions, generators, async/await, reactive callbacks, and ambient context into one feature with one syntax. Languages: Koka, Eff, OCaml 5, Unison, Flix.

## The core idea

Code **performs** effects. Effects **suspend** the current computation and hand its **continuation** to the nearest enclosing **handler**. The handler chooses what to do:

- **Discard** the continuation → equivalent to raising an exception
- **Call it with a value** → like `return` from a block (normal resume)
- **Call it multiple times** → like non-determinism / backtracking / `amb`
- **Store it and call later** → like async/await
- **Call and then continue up** → like middleware / interception

That's the entire feature. Everything else is notation and conventions.

## One mechanism, many features

| Feature           | As an effect                                                  |
| ----------------- | ------------------------------------------------------------- |
| Exception         | `do Err(msg)`; handler doesn't resume                         |
| Generator `y`     | `do Yield(v)`; handler stores continuation, returns v to caller |
| Async `aw`        | `do Await(fut)`; handler stores continuation, resumes on resolve |
| Ambient context   | `do Ask(name)`; handler supplies a value                      |
| Reactive `on`     | `do Change(x, v)`; handler broadcasts to subscribers          |
| Backtracking      | `do Choose([1,2,3])`; handler tries each branch with copied state |
| Logging           | `do Log(msg)`; handler writes somewhere                       |
| Dependency inject | `do GetDB()`; handler returns the active DB                   |

Snafu's `on`, `y`, exceptions, and futures collapse into one feature. We give each a sugar keyword for readability, but they're all `do`+`hd` under the hood.

## Snafu proposal

**Declare** an effect:
```
ef Yield(v)                      # one-shot emit
ef Ask(name)                     # request a value
ef Fail(msg)                     # exception-style
ef Choose(options)               # non-determinism
```

**Perform** an effect inside code:
```
gen3 = f () {
  do Yield(1)
  do Yield(2)
  do Yield(3)
  42                             # final value
}
```

**Handle** an effect around a computation:
```
hd gen3() with {
  Yield(v) k     -> p(v); k(und)           # print v, resume with und
  r              -> p("done, ret=" + r)    # final return handler
}
```

Inside a handler case:
- The pattern binds the effect payload (e.g. `v`).
- `k` is the continuation — call `k(x)` to resume the computation from the `do` site with `x` as the effect's result.
- Not calling `k` is like an uncaught exception — computation stops.

## What continuations mean here

`k` is a **delimited continuation**: it captures the computation from the `do` point up to the `hd` boundary, not the whole call stack. This is what makes effects composable — calling `k` runs that delimited segment, not "the rest of the program".

## Handler selection

When code performs `do Eff(v)`, Snafu walks up the dynamic call stack looking for the nearest `hd` that handles `Eff`. First match wins. This is dynamic scoping, and it's the right default for effects.

## Why this is worth the cognitive cost

Adding five separate features — exceptions, generators, async, reactive, ambient — each with its own syntax and its own interactions, is combinatorially painful. One feature with five sugars is simpler.

Users can define their own effects without waiting for a language version.

## Interaction with sugar keywords

- `rs Err(...)` is `do Err(...)` in an `Exc`-handler context
- `y v` is `do Yield(v)` in a generator-handler context
- `aw fut` is `do Await(fut)` in an async-handler context
- `on a.ch { body }` installs a subscription; writes to `a` `do Change(a, newval)` which the subscription handler picks up

Each sugar picks a standard effect and a standard handler shape. Custom effects skip the sugar and use `do`/`hd` directly.

## Trade-offs

- **Implementation requires delimited continuations**, which Snafu already needs for `cc`/call-cc, state-time-travel, and the self-modifying interpreter. So it's no extra cost.
- **Stack traces through effects** are trickier than through plain returns; the interpreter tracks the full dynamic chain.
- **Dynamic scoping of handlers** is powerful but surprising — a `do Log` far down the stack reaches the handler at the top. This is the same "action at a distance" `on` has.


---

# 07 — Protocols (Clojure-style)

A **protocol** is a named set of function signatures that types can declare they implement, from anywhere in the code (not just at type definition time). Like Haskell typeclasses but runtime-dispatched and open.

## Contrast

- **Java interface**: type must declare `implements Foo` at its definition site. Closed.
- **Haskell typeclass**: explicit instances, compile-time checked, can be added later in a separate module.
- **Python duck typing**: implicit, no declaration, no check, no discoverability.
- **Clojure protocol**: explicit declaration, **open** (any type can implement any protocol from anywhere), runtime-dispatched.

Snafu wants Clojure's version.

## Why Snafu wants them

- **Name a contract**: `Iter`, `Eq`, `Ord`, `Seq`, `Cat` (concatenable), `Show` (pretty-print).
- **Work with multiple dispatch**: protocol methods *are* multi-dispatched functions, grouped under a name.
- **Open**: a library can make existing types (even built-ins) implement new protocols. Python's explicit-ABC approach is too heavy; full duck typing is too implicit. Protocols are the middle.
- **Introspection**: can ask "does this value implement `Iter`?" at runtime.
- **Still duck-compatible**: a type that just happens to have the right methods can be "structurally" recognized as implementing the protocol without an explicit `im`.

## Snafu proposal

**Declare** a protocol:
```
pr Iter {
  it(self)               # returns an iterator
}

pr Itor ex Iter {        # protocol inheritance
  nx(self)               # advance, return value or Done
}

pr Eq {
  eq(a, b)
}

pr Ord ex Eq {
  lt(a, b)
  le(a, b) = l lt(a,b) || eq(a,b)        # default method
  gt(a, b) = l !le(a,b)
  ge(a, b) = l !lt(a,b)
}
```

**Implement** a protocol for a type:
```
im Iter for List {
  it(l) = l.mk_iter()
}

im Ord for MyType {
  eq(a, b) = a.key == b.key
  lt(a, b) = a.key <  b.key
  # le, gt, ge come from defaults
}
```

**Use** protocol methods:
```
for x in mylist {            # `for` requires Iter; dispatches to List's impl
  ...
}
```

## Dispatch

Protocol methods are dispatched by multiple dispatch (see `02-multiple-dispatch.md`) over all declared arguments. A method in a protocol is just a function grouped under a name.

## Open extension

Anyone can `im Ord for SomeoneElsesType` from any module. The implementation lives alongside the caller's code, not inside the type.

## Introspection

```
protocols(x)                 # list of protocols x implements
implements(x, Ord)           # bool
needs(Ord)                   # list of required methods
```

## Structural fallback

If no `im` is declared but the type happens to have `it`, `nx`, etc. with matching signatures, `implements(x, Iter)` can still be true. Optional feature — default off (strict protocol model), opt in with a `ps` (protocol structural) marker.

## Interaction with sum types

```
pr Show {
  show(self)
}

im Show for Maybe {
  show(Some(v)) = "Some(" + show(v) + ")"
  show(None)    = "None"
}
```

Pattern-match on variants directly. Each `show(Variant)` is a separate multi-dispatched method.

## Derived implementations

Common protocols (`Eq`, `Show`, `Ord`) get auto-derive syntax:
```
sm Tree = Leaf | Node(l, v, r) deriving Eq, Show, Ord
```

Auto-generates field-by-field equality, structural show, lexicographic ordering. Useful for ADTs where the "obvious" implementation is right.

## Trade-offs

- Explicit `im` is more boilerplate than pure duck typing.
- Open extension makes it harder to know which impl runs — but `implements(x, Ord)` + introspection is the fix.
- Protocol inheritance is a DAG, not a tree; default methods can overlap. Follow C3 linearization for ordering if needed.


---

# 08 — Context managers

A protocol for "set up a resource, use it in a block, always tear down on exit — whether via normal flow or exception". Files, locks, transactions, temp directories, HTTP sessions, profiler scopes, and so on.

## Python analog

```python
with open('f') as f:
    use(f)
# f is closed here, even on exception
```

## Why Snafu wants them

Your notes already have `bf` (before), `af` (after), `bt` (between). Those are statement-level hooks around a loop or block, but they don't solve the "resource auto-closes even if an exception fires mid-use" case cleanly. `wi` does.

## Snafu proposal

Keyword: `wi` (with).
Protocol: `Ctx` with methods `en(self)` (enter, return value to bind) and `ex(self, err)` (exit, `err` is `und` if clean).

```
wi open("f") as fp {
  use(fp)
}
# fp.ex(und) runs on normal exit
# fp.ex(exception) runs on exception, then re-raises (unless ex returns false)
```

Multiple bindings:
```
wi open("a") as fa, open("b") as fb, lock(m) as _ {
  ...
}
```

Exits run in reverse order (LIFO), so `fb` closes before `fa`.

## Bare `wi` block for anonymous scope

```
wi {
  x = heavy_computation()
  y = another()
  final_result = combine(x, y)
}
# x and y are out of scope here; final_result leaks out per normal scoping
```

With no resource, `wi` is just a scope. Useful for RAII-style cleanup with `bf`/`af`:
```
wi {
  bf { setup() }
  af { teardown() }
  body()
}
```

## Implementing a context manager

```
pr Ctx {
  en(self)
  ex(self, err)
}

im Ctx for File {
  en(f) = f                    # just return self
  ex(f, err) = f.close()       # ignore err, always close
}
```

## Terse decorator form

```
fp = open("f") @wi             # "participate in enclosing wi; close on scope exit"
```

`@wi` marks a value as auto-closed when the enclosing `wi` block ends. If there's no enclosing `wi`, the value is closed on GC. Cheap RAII.

## Interaction with algebraic effects

`wi` is sugar for installing a handler that runs `ex` on any of:
- Normal fallthrough
- An unhandled exception passing through
- A `do Exit` effect
- A cancellation

So `wi` is just a standard handler for the `Exit`/`Exc`/`Cancel` effect family. One-feature-many-sugars principle.

## Interaction with transactions

A DB transaction context commits on clean exit, rolls back on exception:
```
wi db.transaction() as tx {
  tx.insert(...)
  tx.update(...)
}
```

Just an implementation of `Ctx`.

## Interaction with `bf`/`af`/`bt`

These remain useful *inside loops* (run every iteration) and for one-off effects that aren't about resources. `wi` is specifically for resource lifecycle.


---

# 09 — Exceptions

Even though Snafu's `und` propagation + algebraic effects cover a lot of error-handling ground, structured exceptions remain the right tool for: IO errors, parse errors, invariant violations, interrupts, and user-level errors that humans reach for naturally.

## Raising

```
rs ValErr("bad input: " + x)
```

`rs` = raise. The argument is any object; conventionally an `Exc` subtype.

## Catching

```
ty {
  risky()
} ex ValErr e {
  p("bad value: " + e.msg)
} ex IOErr e {
  p("io: " + e.msg)
} ex e {                       # catch-all; only last
  p("other: " + e)
} fi {                         # finally
  cleanup()
}
```

- `ty` (try) opens the block
- `ex TYPE name { … }` is an except clause; you can have many
- `ex name { … }` with no type is a catch-all
- `fi { … }` is finally; runs on any exit path
- First matching `ex` clause wins; order matters

## Exception types

Exceptions are just objects, conventionally inheriting from `Exc`:

```
VE = Exc.new(nm: "ValErr")
IOE = Exc.new(nm: "IOErr")
```

Or a terser form with fields:

```
ex VE(msg)                     # declares VE with a msg field
ex IOE(msg, errno)
ex NetErr ex IOE               # NetErr inherits from IOE
```

Multiple inheritance works. Use sum types for closed exception families:

```
sm ParseErr = EOF | UnexpectedTok(tok, pos) | SyntaxErr(msg, pos)
```

Then catch variants with pattern matching in the `ex` clause.

## Chaining (raise from)

When one exception is raised while handling another, preserve the cause:

```
ty { risky() } ex e {
  rs WrappedErr("failed") fr e
}
```

`fr e` sets `new_exc.ca = e`. Walking the `.ca` chain recovers the full context. Traceback printer shows both.

## Implicit chaining

If an exception is raised inside an `ex` block without `fr`, Snafu auto-chains to the one being handled — like Python 3's `__context__`. Use `fr und` to explicitly break the chain.

## Re-raise

```
ex e { log(e); rs }            # bare rs re-raises the current exception
```

Works only inside an `ex` block.

## Backtrace

Every exception carries `e.tb` — a list of frames. Frame attributes:
- `fl` — file
- `ln` — line
- `fn` — function name
- `sc` — scope (locals at point of raise, if state recording is on)
- `ast` — AST node at the raise point

## Interaction with `und`

Default mode: `und` propagates silently, exceptions are explicit.

In `sd` (strict) mode:
```
sd { result = x / 0 }          # raises DivErr
{ result = x / 0 }             # result = und
```

`sd` can be per-block or top-level. Global strict mode: `sd` at program start.

## Interaction with algebraic effects

Under the hood:
- `rs E` = `do Exc(E)`
- `ex T e { … }` = handler that on `Exc(e)` where `e` isa `T`, doesn't resume; any other effect continues propagating
- `fi { … }` = handler that runs the cleanup on every exit path

So exceptions are an effect. They get dedicated syntax because they're common and because programmers already know try/except shape.

## Unhandled exceptions

Propagate to top of program. Default top handler: print backtrace, exit with non-zero status. Override with a top-level `ex` or effect handler.

## Interaction with async/green threads

An unhandled exception in a green thread fires a `Panic` event on the thread's parent channel. Parent can receive it and decide what to do. No process-wide crash unless parent also ignores it.


---

# 10 — Async/await as sugar over effects + channels

Rather than add async as a separate feature with its own function-coloring (`async def` vs `def` in Python), Snafu treats async/await as syntactic sugar over algebraic effects + channels. Any function can await; the behaviour depends on the enclosing handler (an async handler runs things concurrently, a sync fallback runs things serially blocking).

## The model

A **future** is a placeholder for a value that will be resolved later. `aw fut` suspends the current computation until `fut` resolves, then resumes with the value.

Under the hood: `aw fut` performs `do Await(fut)`. The handler — Snafu's event loop / scheduler — captures the continuation, subscribes to `fut`'s resolution, and resumes the continuation when resolved.

## Snafu proposal

```
as f1 = fetch("url-1")         # `as` spawns the computation, returns a future
as f2 = fetch("url-2")
r1 = aw f1                      # suspends until f1 resolves
r2 = aw f2
```

Parallel wait:
```
r1, r2 = aw [fetch("a"), fetch("b")]      # list of futures → list of values
```

First-to-resolve:
```
r = aw_any [f1, f2]            # whichever resolves first; others are cancelled
```

## No function coloring

In Python you can't `await` inside a plain `def`; you must `async def`. This creates two parallel APIs. Snafu avoids it: `aw` is a `do` effect. Any function can perform it. If no async handler is installed, the default handler blocks the current green thread until the future resolves — the whole program stays responsive because other green threads keep running.

## Channels + select

Futures are the single-consumer case. Channels generalize:

```
ch c = channel()
c <! "hello"                   # send (non-blocking if buffered, else blocking)
v = <! c                       # receive (blocks until a value)
```

Select:
```
sl {
  v = <! c1        -> p("from c1: " + v)
  v = <! c2        -> p("from c2: " + v)
  c3 <! "ping"     -> p("sent to c3")
  to(5000)         -> p("timeout")
}
```

`sl` picks whichever branch can fire first; others stay pending. Pairs with green threads for CSP-style programming.

## Spawning green threads

```
gt { body() }                  # spawn a green thread running body()
h = gt { compute() }           # h is a handle / future for the result
r = aw h                       # wait for it
```

## Cancellation

A future has `cancel()`. Cancelling throws `Cancelled` into the waiting continuation at its next suspension point. Clean cleanup happens via `fi` / `wi`.

## Timeouts

```
aw f tm 5000                   # awaits with 5000ms timeout; raises TimeoutErr
aw f tm 5000 or und            # or returns und on timeout
```

Syntactically `tm N` is a modifier clause on `aw`.

## Scheduling policy

Snafu's default scheduler is cooperative round-robin on green threads — each green thread runs until it `aw`s, yields via `y`, or blocks on a channel. For true parallelism we spawn multiple OS threads, each running its own green-thread scheduler, and pin green threads to OS threads (or let them migrate).

## Blocking IO

Snafu wraps Python's blocking IO to spawn an OS thread for the blocking call and resume the green thread when it completes. From the user's perspective: `aw fs.read("f")` feels async.

## Interaction with effects

The async handler is just an effect handler for `Await`. A user can install a different async handler:
- **Simulated scheduler** for testing (controls time, deterministic)
- **Priority scheduler** for realtime
- **Tracing scheduler** for debugging

## Interaction with exceptions

Rejection = exception-in-future. `aw fut` re-raises the exception at the await site. Propagates through pipelines: `url |> fetch |> parse` raises if fetch fails, parse is never called.

## Interaction with Python's asyncio

Bridge: Snafu futures can be built from `asyncio.Future` and vice-versa. The Snafu scheduler drives asyncio's event loop when both are active. Snafu's `aw` works on a Python awaitable transparently.


---

# 11 — Functional reactive programming / reactive streams

**Event streams** — sequences of values over time — are first-class values. You `map`/`filter`/`merge`/`debounce` them the way you do collections. Languages/libraries: Rx (JS/Swift/C#/Java), Elm, Bacon.js, Flapjax.

## Contrast with `on` triggers

Your notes' `on a.ch { body }` is a one-shot imperative callback. Reactive streams make that callback **composable** and **transformable** — you can map and filter the event flow, merge multiple sources, window over time, etc.

```
clicks   = ev("click", button)
presses  = ev("keypress", window)
quits    = clicks.fl(_.target == "quit")
         + presses.fl(_.key == "Esc")        # stream merge via +
quits.sb(_ -> exit(0))                        # subscribe
```

## Primitives

- `ev(kind, source)` — build a stream from an event source (DOM event, channel, file watcher, …)
- `stream.m(f)` — map each event through f
- `stream.fl(pred)` — filter
- `stream.sc(init, f)` — scan (running accumulator, emits intermediate values)
- `stream.rd(init, f)` — reduce (emits only the final value, only if stream is finite)
- `a + b` — merge two streams (events from either, in order of arrival)
- `a & b` — zip (pair events; one event per pair, each source contributes one)
- `stream.db(ms)` — debounce (drop events that arrive within `ms` of a previous one)
- `stream.th(ms)` — throttle (emit at most one per `ms` window)
- `stream.tk(n)` — take first n events, then end
- `stream.dr(n)` — drop first n events
- `stream.tu(predicate)` — take until predicate is true
- `stream.sb(f)` — subscribe with callback; returns unsubscribe handle
- `stream.al()` — collect all events into a list (only for finite streams)
- `stream.aw()` — await next event (returns a future)

## Behaviors vs events

- **Event**: discrete pulses. Clicks, keypresses, messages.
- **Behavior**: a continuous value you can always query. Current mouse position, current time, current model state.

Snafu unifies them: a behavior is a stream that always has a "current" cached value; `beh.vl` returns it without blocking. An event stream's `vl` is the last emitted value (or `und` if none yet).

## Built on channels

Under the hood: a stream is a broadcast channel with a transformation pipeline. Multiple subscribers see all events. `sb` = "spawn a green thread that reads and calls the callback".

## Built on effects

`emit Event(v)` is a `do Emit(v)` effect, handled by the stream machinery. Same uniformity as async/await.

## Hot vs cold streams

- **Hot**: always emitting, subscribers join in-progress. Button clicks. Default for `ev`.
- **Cold**: starts emitting when first subscribed, restarts for each subscriber. File-read stream. Use `.co()` to convert hot→cold, `.ho()` for the reverse.

## Interaction with transducers

Transducers (see `12-transducers.md`) are pipeline transformations that work on any sequence. A stream is a sequence. So:

```
pipeline = xm(double) + xfl(pos) + xtk(10)
pipeline.al(clicks)            # apply to a stream → stream
pipeline.al(somelist)          # same pipeline → list
```

Write the transformation once, apply to data or events.

## Back-pressure

If a subscriber is slow and upstream fires fast, events queue. Snafu streams default to unbounded queue (simplicity first). Opt in to bounded with `.bd(n)` — drops / blocks / errors depending on policy.

## Interaction with `on` sugar

```
on a.ch { body }
```
is just sugar for:
```
changes_of_a.sb(_ -> body)
```
where `changes_of_a` is a built-in stream that fires on writes to `a`. `on` keeps its imperative feel; streams give the compositional face.

## Bindings via streams

A bound variable `b = ~a` (tracks a) can be modeled as `b = changes_of_a.m(f)` — a derived stream. When you ask `b.vl`, you get the current computed value. Reading `b` auto-collapses to `b.vl`.


---

# 12 — Transducers

A **transducer** is a composable transformation over sequences of values, decoupled from the kind of sequence. Clojure coined the name; Rust's iterator adapters are similar in spirit.

## Motivation

You know map/filter/take, `.m(f)`, `.fl(pred)`, `.tk(n)`. You can chain them on a list:

```
l.m(double).fl(pos).tk(10)
```

But what if you want the same on a stream? A channel? A generator? A file line-iterator? Normally you'd need `map_stream`, `filter_stream`, `map_chan`, `filter_chan` — N transformations × M containers = mess.

A transducer expresses the transformation independently of the container. You define the pipeline once, apply it to anything reducible.

## Snafu proposal

Transducer constructors (letters x, m, fl, tk, etc., small set):

```
xm(f)          # transducer version of map
xfl(pred)      # filter
xtk(n)         # take first n
xdr(n)         # drop first n
xsc(init, f)   # scan (emit running accumulator)
xch(pred)      # chunk: group consecutive elements matching pred
xdd()          # deduplicate (drop consecutive repeats)
xpp()          # pass through (identity)
```

Compose with `+`:

```
pipeline = xm(double) + xfl(pos) + xtk(10)
```

Apply to anything reducible:

```
pipeline.al(somelist)             # list → list
pipeline.al(somestream)           # stream → stream
pipeline.al(somechannel)          # channel → channel
pipeline.al(somegen)              # generator → generator

pipeline.rd(0, add, somelist)     # reduce with a pipeline: Σ pipeline.al(list)
```

`.al(coll)` runs the pipeline, produces the same *kind* of output. `.rd(init, f, coll)` folds.

## Why it beats "just use iterators"

- **No intermediate collections** when applied to lists. `l.m(f).fl(p).tk(n)` with naive methods creates two throwaway lists; transducers don't.
- **Same pipeline across container kinds** — write once, apply to sync or async sequences.
- **Composable as values**: pass pipelines to functions, store in vars, build from fragments.
- **Works with channels (CSP)**: attach a transducer to a channel, get a transformed channel.

## Sequence vs accumulator separation

Conceptually, a transducer is a function `reducer → reducer`:
- A reducer is `(acc, val) → acc`
- A transducer takes a reducer and returns a new reducer that does extra work first
- `xm(f) = reducer -> ((acc, val) -> reducer(acc, f(val)))`

Composition is reducer wrapping. That's why `+` works — the mathematical composition.

## Stateful transducers

`xtk(n)` needs to count. Transducers can carry state per-application (the reducer factory creates a fresh state each time):

```
xtk(3).al([1,2,3,4,5,6])    # [1,2,3]
xtk(3).al([1,2,3,4,5,6])    # [1,2,3]  — fresh state
```

## Terminating transducers

`xtk(n)` wants to stop early. The reduction protocol includes an "early termination" signal. `rd` respects it.

## Interaction with FRP

Streams are sequences over time. Transducers apply identically. `clicks |> xtk(10) |> xdb(500)` gives "first 10 clicks, debounced to 500ms".

## Interaction with lenses

A traversal lens is a transducer scoped to a structural focus. `(_.users) + traverse(all) + xm(age_up_one).al` ages every user by one year.

## Terse syntax proposal

Unix-pipe-style with streams:

```
l |> xm(double) |> xfl(pos) |> xtk(10) |> al
```

The `|>` + transducer + `al` chain reads naturally and avoids building the pipeline as a named value if you don't need to.


---

# 13 — Regex as first-class + Perl-style operators

Per A.13: no separate compile step (Snafu doesn't care about perf), and borrow Perl's `s///` / `m//` / `tr///` operator syntax.

## Regex literals

```
r/\d+\s+(\w+)/i                # compile at parse
r"pattern with / in it"        # alternate delimiter when you need /
```

Flags (Perl-ish):
- `i` case-insensitive
- `m` multiline (`^`/`$` match line boundaries)
- `s` dotall (`.` matches newline)
- `x` extended (ignore whitespace and comments)
- `g` global (all matches, not just first)
- `u` unicode (full Unicode property support)

## Operations

```
re = r/\d+/g
re.ma(str)              # first match as Match object, or und
re.al(str)              # list of all Matches
re.ct(str)              # count of matches

m = re.ma("hello 42 world 7")
m.gr(0)                 # whole match: "42"
m.gr(1)                 # group 1 (if any)
m.gr("name")            # named group
m.sp                    # start offset
m.ep                    # end offset
m.pr                    # string before match
m.po                    # string after match
m.al                    # list of all groups
```

## Perl-style operators

Bind subject with `=~`:

```
"hello" =~ s/e/a/                      # "hallo"
"hello" =~ s/(.)\1/X/                  # "heXo"  (backreference)
"hello" =~ m/l+/                       # Match("ll")
"hello" =~ tr/a-z/A-Z/                 # "HELLO"  (transliteration)
```

Without a subject, the operators are standalone regex objects:

```
upr = s/(.)/\1.upr()/g                 # a sub-transformer function-value
upr("hello")                           # "HELLO"
```

## Substitution with a function

```
s/(\d+)/(m -> int(m.gr(1)) * 2)/g
```
Replacement can be a string (with `\1`-style backreferences) or a function taking the Match and returning the replacement string.

## Named groups

```
r/(?P<year>\d{4})-(?P<mo>\d{2})-(?P<dy>\d{2})/
```

Match `m.gr("year")` etc. Pattern match:

```
mt dateStr {
  r/(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})/ -> build_date(y, m, d)
  _                                          -> und
}
```

The `r/…/` acts as a pattern; named groups become bindings.

## SNOBOL / SPITBOL extensions

From your notes. Combinators for more readable patterns:

```
rx.any("abc")                  # any of these chars, one-or-more
rx.br("xyz")                   # BREAK: match until a char in set
rx.len(3)                      # exactly n chars
rx.arb                         # arbitrary (greedy .*)
rx.bal("()")                   # balanced parens
rx.span("0-9")                 # SPAN: one-or-more from set
```

Use with `+` (concat) to build a regex:

```
p = rx.br(":") + ":" + rx.span("0-9")
```

## "Anything but X" extension

Your notes: `(^blah)*?`. Implement as a sugar over negative lookahead:

```
(^blah)*         # = (?:(?!blah).)*
```

## N-dimensional / structural regex

Your notes mention arbitrary nesting and treating code elements as whole units. That goes beyond regex — it's parser-combinator territory. We'll cover that in a separate concept if needed, but expose it via regex-on-tokens / regex-on-AST views.

## Compile-time literal check

Even without perf-compilation, Snafu parses `r/.../` at parse time and reports regex syntax errors there, not at match time. This catches typos early.


---

# 14 — String interpolation

Per A.14: `${expr}` for substitution. Per A.5: Python semantics for quotes + PHP semantics for multi-line.

## Basic form

```
name = "World"
"Hello, ${name}!"              # "Hello, World!"

count = 3
"${count} items"               # "3 items"

"${count == 1 ? 'one' : 'many'}"   # ternary inside interpolation
```

## Quote rules (Python + PHP hybrid)

- `"…"` — interpolates. PHP-style and f-string-style collapsed into one.
- `'…'` — no interpolation. Treats `${x}` literally. Python single-quote shares this semantics in Snafu.
- `r"…"` — raw: no escape sequences (`\n` is two chars). Interpolates unless also prefixed with `b`.
- `b"…"` — bytes.
- `"""…"""` — triple-quoted, multi-line, interpolates.
- `'''…'''` — triple-quoted, multi-line, no interpolation.
- `<<<EOT … EOT` — PHP heredoc: multi-line, interpolates, delimiter-based.
- `<<<'EOT' … EOT` — PHP nowdoc: multi-line, no interpolation.

## Format specs

Python f-string-style specifiers after a colon:

```
x = 3.14159
"pi = ${x:.2f}"                # "pi = 3.14"

n = 255
"hex = ${n:#x}"                # "hex = 0xff"
"bin = ${n:#b}"                # "bin = 0b11111111"

s = "hi"
"|${s:>10}|"                   # "|        hi|"    (right-pad to 10)
"|${s:<10}|"                   # "|hi        |"    (left)
"|${s:^10}|"                   # "|    hi    |"    (center)
```

Custom format spec is delegated to the value's `Show`/`Fmt` protocol method, so user types can define their own.

## Nesting

Nested interpolations work:
```
"outer ${f("inner ${x}")}"                       # different string delimiters
"outer ${"inner ${x}"}"                          # same delimiter, recursive parse
```

The parser handles `${…}` by counting braces, so nested `{` inside the expr is fine:
```
"${ dict["key"] }"
"${ { 1, 2, 3 } |> max }"
```

## Multi-line heredoc

```
msg = <<<EOT
  Hello, ${name}!
  Count is ${count}.
EOT
```

Common-leading-whitespace is stripped to match the terminator column (Python-ish `textwrap.dedent`).

Nowdoc for no-interpolation templates (code literals, regex templates):

```
pattern = <<<'RX'
  ^\d{3}-\d{4}$
  (?i: hello | hi )
RX
```

## Relation to variable-variables (`$a`, `$$a`, `$(x)a`)

The `$` sigil is overloaded by context:
- **Inside a string**: `${...}` is always expression-interpolation. A bare `$a` inside a string is a shorthand for `${a}` (single-identifier case).
- **Outside a string**: `$a` / `${a}` / `$$a` / `$(x)a` are variable-variable references (see `15-variable-variables.md` if we end up writing that, or the grammar spec section).

Both uses agree on `${expr}` meaning "evaluate expr, substitute result".

## Expressions that can appear inside `${…}`

Any Snafu expression. Including function calls with side effects — though you should avoid side effects in interpolation; it confuses readers.

Statements (assignments, control flow) are not allowed inside `${…}` — expressions only.

## Escaping

- `\${x}` — literal `${x}`, no interpolation
- `${"$"}${"{"}x${"}"}` — hack if you really need it composed

## Locale-aware variants

`${x:.2f}` is not locale-aware (always `.` decimal). For locale-aware formatting use an explicit function: `"${fmt_num(x, locale)}"`. Keeping interpolation simple and deterministic is worth it.


---

# 15 — Iterator protocol

For `for x in y`, n-dimensional iteration, transducers, and async streams to work uniformly across builtins and user types, we need a protocol for "values in a sequence".

## Levels

Per your notes' "iterables can have their indexes reset, and arbitrary variables can be passed to/from them":

1. **Iterable**: can produce an iterator. Method: `it(self)`.
2. **Iterator**: stateful, yields values. Method: `nx(self)` returns the next value or performs `do StopItor`.
3. **Reversible iterator**: also supports `pv(self)` (previous). Your "inverse of continue" concept.
4. **Resettable iterator**: supports `rs(self)` (go back to start). Your notes want this.
5. **Indexable iterator**: supports `at(self, n)` (skip directly to position n). Enables your "generator comprehensions that cache and are indexable".
6. **Multi-dimensional iterable**: supports iteration over n axes; each step advances one axis.

## Protocol stack

```
pr Iter {
  it(self)                        # returns an iterator
}

pr Itor ex Iter {
  nx(self)                        # next or do StopItor
}

pr Revible ex Itor {
  pv(self)                        # previous or do StopItor
}

pr Rstable ex Itor {
  rs(self)                        # reset to start
}

pr Indexable ex Itor {
  at(self, n)                     # jump to nth element
}

pr NdItor ex Itor {
  dim(self)                       # number of axes
  at_nd(self, indices)            # at for multi-dim
}
```

Types implement as many as they can. `List` implements all of them. A streaming network socket implements only `Itor`.

## End-of-iteration: `do StopItor`

Two designs for "end of sequence":
- **Sentinel**: `nx` returns `und` or a special `Done`. Simple, but collides with legitimate `und`/`Done` values.
- **Effect**: `nx` performs `do StopItor`. Uniform with algebraic effects.

Snafu picks the effect approach: `nx` performs `do StopItor`. The surrounding `for` installs a handler that catches it and exits the loop.

Sentinel optionality: if you prefer, call `.to_sentinel(iter)` which wraps with a handler and returns `und` on done. Most code won't need it.

## `for` desugaring

```
for x in coll { body(x) }
```
becomes
```
hd {
  it = coll.it()
  lp { body(it.nx()) }           # loop; StopItor breaks out
} with StopItor -> und            # handler catches end
```

## Nested `for`

Sugar:
```
for row in matrix, x in row {
  body(row, x)
}
```
is desugared to nested `for`.

Multi-dimensional shorthand:
```
for x (i, j) in matrix.nd(2) {
  body(x, i, j)
}
```
binds `x` to each scalar and `(i, j)` to its indices, using the NdItor protocol.

## Custom generators with `y`

```
ct my_gen(n) {
  for i in 0..n {
    y i * i
  }
}

for sq in my_gen(5) {
  p(sq)                           # 0, 1, 4, 9, 16
}
```

`ct` declares a coroutine (stateful function returning an iterator). `y v` = `do Yield(v)`. Calling `.nx()` on the returned iterator resumes the body until the next `y`.

## Passing values into generators

Your notes: "arbitrary variables can be passed to/from them". This is generator `send`:

```
it = my_gen(5)
next_val = it.nx()              # plain next
computed = it.sd(42)            # send 42 into the body; y expression receives it
```

Inside the body, `x = y v` binds `x` to whatever was sent in (or `und` on plain `.nx()`).

## Iteration over streams / channels / async

Streams and channels implement `Itor` with an async `nx` that awaits the next value. `for x in stream { … }` just works.

## Caching / indexable comprehensions

Generator comprehensions `[x: expr]` evaluate lazily and cache seen values. Re-iteration doesn't re-compute; `at(n)` lookups work in O(1) for already-seen positions, pay-once for new ones.

## Interaction with transducers

Transducers apply to any Iter. `xm(f).al(someIter)` produces an iterator that applies f to each nx.


---

# 16 — Module system with Python compatibility

Per A.16: terse aliased access to all of Python's ecosystem, on-demand import, user-extensible alias tables.

## Goals

1. Zero ceremony for simple programs (no `import` needed for well-known names).
2. Terse prefix for Python modules (2-letter aliases).
3. Snafu modules interop cleanly with each other.
4. `use` / `unuse` for namespace prefix shortcuts.
5. User-definable aliases.

## Module unit

A Snafu source file is a module. Its top-level bindings form its exports unless `xp` declares a specific export list.

```
# file: geom.snf
pi_approx = 3.14
xp [area, perim]

df area(r)  = pi_approx * r * r
df perim(r) = 2 * pi_approx * r

df _helper(x) = …              # not exported if xp is used
```

Without `xp`, all top-level bindings are exported.

## `us` (use) / `un` (unuse) — wait, `un` conflicts with until

Keep the notes' `use` / `unuse` full form. Two-letter alias `us` for use. Unuse is less common; spell it out.

```
us geom                          # import module; access as geom.area
us geom as g                     # alias
us geom { p(area(5)) }           # unqualified access inside block
us geom, math { p(sin(area(5))) } # multiple modules; last wins on name clash
unuse geom                        # drop the binding
```

## Python compatibility table

A built-in registry maps two-letter aliases to Python dotted paths. A first cut:

```
n8  -> numpy
nq  -> numpy
pd  -> pandas
pl  -> matplotlib.pyplot
sp  -> scipy
sk  -> sklearn
tc  -> torch
tf  -> tensorflow
os  -> os
sy  -> sys
rq  -> requests
js  -> json
re  -> re
dt  -> datetime
td  -> timedelta  (datetime.timedelta)
cs  -> csv
xm  -> xml.etree.ElementTree
bs  -> bs4
sq  -> sqlite3
sa  -> sqlalchemy
fs  -> pathlib / os
th  -> threading
ap  -> asyncio
cp  -> subprocess
it  -> itertools
ft  -> functools
ic  -> collections
op  -> operator
ma  -> math
rn  -> random
pk  -> pickle
hs  -> hashlib
cg  -> cryptography
rg  -> re (regex)
```

Users extend via `~/.snafu/aliases.snf`:
```
# user alias file
pq = some.obscure.package
cv = cv2
```

## On-demand loading

First mention of `n8` triggers an implicit `import numpy` at the host Python level. No explicit `us n8` required — the name resolves by walking the alias chain if undefined in the normal resolution path.

Explicit `us n8` is still allowed (and recommended in module headers for clarity) but optional.

## Resolution chain for unqualified names

When the interpreter sees a bare name `foo`:

1. Current (local) scope
2. Enclosing lexical scopes
3. Module-level scope
4. `us`-block imported namespaces, in declaration order (last wins)
5. Snafu built-ins
6. Python alias table (triggers on-demand import)
7. `und`

This is a single lookup chain. Users can inspect it (`sc` scope introspection).

## Python values round-trip

When Snafu calls into Python:
- **Primitives** (int/float/str/bool/None) map to Snafu number/str/bool/`und` — direct.
- **Lists/dicts/tuples** map to Snafu lists/ordered-sets — by value copy, **or** wrapped in a proxy if mutation should round-trip (configurable per-call).
- **Callables** wrap; calling the Python function from Snafu auto-converts args.
- **Classes** wrap; Snafu can instantiate (`np.array(…)`), subclass (Python sees Snafu-backed instance), check isinstance.
- **Generators** wrap to Snafu iterators.
- **NumPy arrays / pandas DataFrames** pass through as opaque handles with their methods exposed; convert to Snafu list via `.fl()`.

## What doesn't round-trip cleanly

- **Snafu symbolic numbers** arriving in NumPy need `.fl()` (flatten) first to collapse to a plain float.
- **Algebraic effects** don't cross the Python boundary. A `do` inside a Python-called Snafu callback resolves within Snafu; Python code can't `do` Snafu effects.
- **Python async** bridges via asyncio; Snafu's green-thread scheduler drives the asyncio loop. Most `await`-returning Python APIs work, but "naked" asyncio primitives (sleep, gather) are best used through Snafu wrappers.
- **Python metaclasses** + Snafu protocols: Snafu's MRO may disagree with Python's. Keep them separate — use Snafu protocols for Snafu types, Python metaclasses for Python types; don't mix.

## `xp` (export) list

```
xp [add, sub, mul]               # public API
```

Everything else is module-internal. Soft enforcement (Snafu is dynamic): you *can* reach in via `module._priv`, but it signals intent.

## Import cycles

Detected at resolution time. `us a` while `a` is still evaluating its own `us b` which `us a`s → raise `CycleErr` with full chain. Or tolerate cycles Python-style (partially-initialized module); toggle with a flag at program top.

## REPL implications

The REPL's top scope is implicitly a module. Names you define are exported (even though "exporting" from the REPL means little). You can `us` inside the REPL freely.


---

# 17 — eval and scope

Per A.17: `ev` sees top, caller, and any explicit context passed.

## `ev` evaluates a string as Snafu code

```
ev("1 + 2")                      # 3
ev("x + 1", sc: {x: 5})          # 6
ev("x + 1", sc: ca)              # uses caller's scope (default)
ev("x + 1", sc: tp)              # uses top-level (program) scope
```

## Default scope

Called without `sc:`, `ev` uses a scope chain that looks up names in:

1. Any locally introduced bindings by the evaluated code itself
2. The caller's scope (full chain including enclosing lexical scopes)
3. The top-level (program) scope
4. Built-ins + Python alias table

Writes go to the caller's scope unless you pass an explicit `sc:`, in which case writes go there.

## Special scope names

To disambiguate when names collide at multiple chain levels:

- `tp.x` — top-level (program/module) `x`
- `ca.x` — caller's `x` (one up from `ev` in the dynamic call stack)
- `ev.x` — `ev`'s own local `x` (the evaluated code's own bindings)
- `sc.x` — alias for whichever scope is currently active

`tp`, `ca`, `ev`, `sc` are scope objects (see `sc[x].y` in your notes). First-class values.

## Evaluating code blocks vs strings

Per the "all code is executed strings" decision (#21):

- A code block `{…}` is syntactic sugar for a compiled string tagged with its **lexical** scope at the point of definition. Calling it runs in that scope.
- A raw string `"…"` with `.ca()` runs in the **caller's** scope (dynamic) by default.
- Either can be called with explicit `sc:`.

```
blk = { x + 1 }                  # lexical scope at definition site
blk()                            # x is found in the definition site's scope
blk.ca(sc: {x: 5})               # override scope

s = "x + 1"
s.ca()                           # uses caller's x
s.ca(sc: {x: 5})                 # override
s.ca(sc: tp)                     # use top-level x
```

The *only* semantic difference between a code block and a string is the default scope: lexical for blocks, dynamic for strings.

## Return values

`ev` / `.ca()` returns the value of the last expression in the evaluated code. Multi-statement strings work — each statement runs; the last's value is returned.

```
ev("x = 5; x * 2")               # 10  (and x=5 is written to caller's scope)
```

## Parse errors

`ParseErr` — a regular exception. `ev("1 +")` raises at parse time, not at "eval time", and the error carries offset / line info.

## Syntax errors vs runtime errors

Distinguish clearly:
- `ParseErr` — syntactically invalid input.
- `NameErr` — name not found in the resolution chain.
- `TypeErr` — wrong type for an operation.
- Others per the standard exception hierarchy.

## Security

No sandbox by default. Snafu is a dynamic language; `ev` is a power tool, not a safety barrier. If you need sandboxed eval, pass a scope containing only safe names:

```
sandbox = {x: 5, y: 10, add: std.add}
ev(user_input, sc: sandbox)      # can only see what's in sandbox
```

Writes to `sc` go to the sandbox dict — the caller's scope is untouched. Still not cryptographically safe (the user can reach out via builtin lookups if not restricted), but enough for normal use.

## Meta-circular note

At interpreter level `it[n]`, `ev` inside level-n code uses the level-n interpreter. Changes to `it[n-1]` affect how level-n code parses / runs. `ev` pushes one more level for the duration of its call if you pass `lv: +1`.

```
ev(code, lv: +1)                 # evaluate using a deeper interpreter level
```

Per D.16: the total interpreter level count is fixed at program start; `ev` with `lv: +1` is a temporary push that pops on return. Can't go deeper than the configured max.

## REPL

The REPL is continuous `ev` with `sc: tp`, all inputs executed and their last values printed. Statements execute; expressions print their value.

## Interaction with state time-travel

If state recording (`ps`) is on, `ev` records as a single composite step — you can step through its inner execution (with `sa -1` inside it) or step past it (with `sa -1` from outside).


---

# 18 — Tail calls by semantics

Per A.18: tail-call elimination (TCO) as a **language semantic**, not an optimization. Snafu is not optimized, but stack overflow in a function-recursion loop is an implementation leak — it exposes Python's call-stack limit through Snafu's syntax. We don't want that.

## The problem

```
f = l n -> f(n + 1)
f(0)                             # does this loop forever or blow the stack?
```

If the interpreter is a naive tree-walker on top of Python, each Snafu call adds a Python frame. At ~1000 deep, Python's `RecursionError` fires. That's a language-visible behaviour that depends on the implementation — bad design.

## The fix: trampolining

Tail-position calls are **semantically jumps**, not stack pushes. The interpreter, when it sees a call in tail position, replaces the current Snafu frame instead of pushing a new one.

Implementation:
- Interpreter maintains its own call-frame stack (separate from Python's).
- In tail position, pop the current frame before evaluating the call, then push the new one. Net frame count: same. No Python-level recursion.
- In non-tail position, push normally.

This makes infinite tail-recursion use **O(1)** Snafu frames (even though each step uses O(1) Python frames transiently).

## Tail position — what counts

- Last expression in a function body
- Last expression in a `{ … }` block that is itself in tail position
- Value-expression of the last branch of `mt` / `if` / effect handler
- Argument to a *tail call* that is itself in tail position? **No** — evaluating arguments is work. Only the outer call is tail.
- Pipeline `x |> f |> g`: `g(f(x))` — only the `g` call is tail.

Tail-position analysis is syntactic. Done once at parse time; the compiled block knows which call sites are tail calls.

## Mutual recursion

```
even = l n -> n == 0 ? true  : odd(n-1)
odd  = l n -> n == 0 ? false : even(n-1)
```

Both calls are in tail position. Trampoline handles them — neither blows the stack.

## Explicit marker?

Some languages require an opt-in keyword for TCO (Scheme has it implicit; Scala requires `@tailrec`). Snafu does it implicitly since tail position is syntactically detectable with zero ambiguity. No keyword needed.

## Interaction with effect handlers

A `do E(v)` in tail position does **not** TCO — performing an effect captures the continuation, which needs a frame. Effects always push. This is OK: effects are the suspension points; they're not where you loop.

A call inside an effect handler that's in the handler's tail position does TCO normally.

## Interaction with exception handlers

A call in tail position inside a `ty` block is **not** a tail call — the `ty` frame must remain on the stack to catch exceptions. If you want TCO + exception handling, the `ty` has to end before the call.

This matches intuition: "you can't catch an exception after the call if you've thrown away the stack frame that was supposed to catch it."

## Interaction with `fi` (finally)

`fi` keeps the frame alive until the whole call returns — so a call in tail position of a block that has `fi` around it is not a tail call. Move `fi`'s cleanup into a `wi` context manager if you need TCO.

## Self vs mutual tail calls

No distinction. Both are handled.

## What this is NOT

Not an optimization pass. Not a speed improvement (performance parity with or without). Just a semantic guarantee that syntactically-tail-calls don't consume stack. The interpreter enforces it as part of the language spec.

## Debugging impact

A debugger can still walk the frame chain, but tail-called frames have been replaced — you see only the current frame, not the caller that tail-called into it. This is exactly like `goto` from the debugger's viewpoint. If you need the full history, turn off TCO for debugging (`dbg.no_tco()`), or use state-time-travel which records frames regardless.


---

# 19 — Debugging protocol

Snafu already has **state time-travel** (`sa`, `sp`, `ps` from your notes). That's an interactive debugger waiting to happen. The debugging protocol is the contract between the interpreter and debugger tools (command-line, IDE, logger, profiler).

## Protocol

A **debugger** is any object implementing `Dbg`:

```
pr Dbg {
  on_step(self, fr)              # called at each statement (line granularity)
  on_call(self, fr, fn, args)    # before a call
  on_return(self, fr, val)       # after a return
  on_raise(self, fr, exc)        # on exception raise (not yet handled)
  on_catch(self, fr, exc)        # when an exception is caught
  on_assign(self, fr, name, val) # after assignment
  on_read(self, fr, name)        # on read (expensive — off by default)
  on_effect(self, fr, eff)       # on `do` effect perform
  on_break(self, fr, bp)         # on hitting a breakpoint
  on_yield(self, fr, val)        # on generator yield
  on_resume(self, fr, val)       # on generator resume
}
```

Not all methods need to be implemented — missing methods are no-ops. A profiler implements only `on_call` / `on_return`.

## Installing a debugger

```
db(my_dbg)                       # install for the rest of the program
wi db(my_dbg) { ... }            # scoped install — removed on block exit
```

Multiple debuggers can be installed; all fire per event in install order.

## Frames

A **frame** is an object with:

- `sc` — scope (readable AND writable)
- `ln` — current line number
- `fl` — source file
- `fn` — function name (or `und` for top-level)
- `up` — parent frame (dynamic)
- `ast` — AST node currently executing
- `st` — state buffer index (if `ps` is on), for time-travel
- `lc` — local-call count (for profiling)
- `id` — unique id

Mutating `frame.sc` live-patches variables — the next step sees the change. Dangerous and powerful.

## Breakpoints

**Source-level**:
```
bp "myfile.snf:42"                # break when line 42 of myfile executes
bp "myfile.snf:42" if x > 3       # conditional breakpoint
bp fn_name                         # break on entry to this function
```

**Programmatic**:
```
bp()                             # break right here (like ipdb.set_trace)
```

Breakpoints are removable: `bp.rm(id)` or `bp.cl()` (clear all).

## REPL integration

At a `bp()`, control drops into a Snafu REPL whose top scope is the current frame's scope. Commands:

- `s` — step (enter calls)
- `n` — next (step over calls)
- `o` — step out (finish current frame)
- `c` — continue
- `u` / `d` — move up / down frame chain
- `p expr` — print value
- `ev "code"` — run code in current frame's scope
- `sa -1`, `sa +1` — time-travel backward / forward
- `ls` — list nearby source
- `bt` — backtrace

## Time-travel integration

If `ps` / `sa` is in use, the debugger has full history. `sa -N` rewinds N steps without re-running. `sa +N` replays forward. This is a reversible debugger — the nicest kind.

Without `ps`, time-travel is unavailable; the debugger is forward-only like a traditional debugger.

## Non-local control

A debugger handler can raise exceptions, call `rs`, modify the return value of `on_return`, or call the continuation with a different value after `on_effect`. Powerful, and a footgun — use carefully. Can even swap the AST node being executed (after `on_step`, change `frame.ast`).

## Profiling as a debugger subset

A profiler is a `Dbg` implementing only `on_call` (start timer, increment counter) and `on_return` (stop timer, tally). No special infrastructure.

```
pf = Profiler.new()
wi db(pf) { run_program() }
pf.report()
```

## Logging / tracing as a subset

A tracing debugger implements `on_step` and `on_effect` to emit log entries. Useful for "what did this program actually do?" forensic investigations.

## Interaction with concurrency

Each green thread has its own frame chain. Debuggers see events from all threads (tagged with thread id). A debugger can pause one thread, leave others running, or pause all.

## Interaction with the self-modifying interpreter

When interpreter code at `it[n]` is modified during execution, the debugger sees a `InterpreterChanged` event with the diff. Frames pending evaluation at the affected AST nodes may get recompiled before next `on_step`. Your notes' question of "what happens when code changes mid-run" is answered here: the debugger observes the change, and the interpreter re-walks the modified AST on the next step.

## Standard debuggers ship with Snafu

- `Db.pdb()` — Python-pdb-style REPL debugger
- `Db.tr()` — tracing logger
- `Db.pf()` — profiler
- `Db.tv()` — time-travel debugger (requires `ps`)


---

# 20 — Identity vs equality vs deep equality

Three concepts, three operators. Every dynamic language has this confusion; we spec it once up front.

## Identity — `is`

Same object in memory. Two names, one thing.

```
a = {1, 2, 3}
b = a
c = {1, 2, 3}
a is b                     # true  — same object
a is c                     # false — different objects, identical contents
```

`is` never overloads. It's the raw "same-reference" check. For immutable values (numbers, strings, booleans), interning means `1 is 1` is `true`, but don't rely on it for equality decisions — use `==`.

## Default equality — `==`

Overridable by types via the `Eq` protocol. For built-ins:

- Numbers: value equality across the number tower (`1 == 1.0 == 1+0i`).
- Strings: character-by-character.
- Lists / ordered-sets: same length + `==` on each element, recursively.
- Dicts: same keys + `==` on corresponding values.
- Custom types: `Eq.eq(a, b)` if implemented; otherwise `is`.

```
{1, 2, 3} == {1, 2, 3}           # true
[1, [2, 3]] == [1, [2, 3]]       # true (recursive ==)
1.0 == 1                         # true (num tower)
```

## Structural / strict equality — `===`

Ignores custom `Eq` overrides. Compares by structure: same type, same shape, same members recursively. This is what you want for test assertions, serialization round-trip checks, and debugging.

```
1.0 === 1                        # false — different types
1 === 1                          # true
[1, 2] === [1, 2]                # true
```

For user types, `===` falls back to "same type AND same field values recursively", never calls custom `eq`.

## Not-equal variants

- `<>` — inverse of `==`
- `!==` — inverse of `===`
- `is not` — inverse of `is`

Use whatever reads best. `a <> b` and `!(a == b)` are equivalent; pick per context.

## Custom equality

```
pr Eq {
  eq(a, b)
}

im Eq for Person {
  eq(a, b) = l a.id == b.id       # identity-by-id
}
```

Now `Person(...)== Person(...)` uses `eq`. `Person(...) === Person(...)` still compares all fields structurally.

## Hashing

`hs(x)` returns a hash. Contract: `a == b` implies `hs(a) == hs(b)`.

Types in dict keys or sets must have `Hs`:

```
pr Hs ex Eq {
  hs(self)
}
```

For most types, default `hs` walks structure. Custom `eq` means custom `hs` — if you override one, override the other, or the dict will look you in the eye and lie about whether the key is present.

## NaN

- `nan == nan` → `false` (IEEE 754 semantics)
- `nan === nan` → `true` (structural: same thing)
- `nan is nan` → `true` if interned; usually `true`

IEEE-`nan` semantics for `==` is surprising but standard. Most languages preserve it. Snafu does too.

## und (None)

- `und == und` → `und` (propagation — you can't even ask!)
- `und === und` → `true` (structural)
- `und is und` → `true` (singleton)

`und == und` being `und` is weird but consistent with "any op involving `und` is `und`". If that's too surprising, use `===` or `is` for explicit `und` checks. Pattern match is cleanest:

```
mt x { und -> ..., _ -> ... }
```

## Collections and reference vs value semantics

A list is mutable. `[1, 2, 3] == [1, 2, 3]` is `true` by value. But after `b = [1, 2, 3]; b.append(4)`, the original list is changed — if another variable pointed to the same list, it sees the change.

Default Snafu dict / set / list: reference semantics on the container, value semantics on equality. If you want immutable persistent collections, use `fr` (frozen) variants: `fr[1, 2, 3]`, `fr{a: 1}`.

## Interaction with multiple dispatch

Dispatch uses type identity (`is` for types). `df f(Num x)` matches whenever `x.type is Num` or a derived type.

## Interaction with sum types

```
Some(5) == Some(5)               # true — same variant, == on inner
Some(5) == None                  # false — different variants
Some(5) === Some(5)              # true
Some([1,2]) == Some([1,2])       # true — recursive ==
```

## Summary

| Op    | Meaning                    | Overridable | Use for                       |
| ----- | -------------------------- | ----------- | ----------------------------- |
| `is`  | Same object in memory      | No          | Singleton checks, identity    |
| `==`  | Semantic equality          | Yes (`Eq`)  | Most user-level comparisons   |
| `===` | Structural/strict equality | No          | Tests, diffing, serialization |

Python collapses `==` and `===` (confusingly, since custom `__eq__` can lie). JS has `==` and `===` but they're about type coercion, not structural vs custom. Lisp has `eq`/`eql`/`equal`/`equalp` — four levels, overkill. Three is the sweet spot.


---

