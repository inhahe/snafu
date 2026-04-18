# Snafu Language Specification

Version 1.7. Last updated 2026-04-17.

This document is the source of truth for the Snafu language. The original design notes (`01 - New note - Megafuck.txt`) and the feature concepts document (`CONCEPTS.md`) are background; where they disagree with this spec, this spec wins.

---

## 0. Reading guide

### Notation

- `code` — Snafu source, example fragment
- *italics* — term introduced in place
- **bold** — emphasis
- `X?` in grammar — optional
- `X*` in grammar — zero or more
- `X+` in grammar — one or more
- `X | Y` in grammar — choice
- `// comment` in examples — explanation, not part of Snafu code

Section numbers are stable references. A feature's full definition lives in exactly one section; cross-references point there.

### Terms

- **Value**: any runtime entity — number, string, list, object, function, effect, scope, etc.
- **Name**: an identifier bound to a value in some scope.
- **Scope**: a mapping from names to values, with an optional parent link.
- **Object**: any value with a prototype chain. In Snafu, every value is an object.
- **Prototype**: the object from which another object was derived via `new`.
- **Form** / **expression** / **statement**: see §9.
- **Code block** `{…}`: a compiled, lexically-scope-bound code object (see §5, §9).
- **Interpreter level**: see §35.

---

## 1. Design philosophy

Snafu's design priorities, in order:

1. **Terseness.** Canonical keywords are 1–3 characters. Longer full-word aliases exist for most keywords for discoverability, but the short form is the "real" name.
2. **Dynamism.** Everything is modifiable at runtime: bindings, classes (prototypes), methods, operators, the parser, the interpreter.
3. **Meta-circularity.** The interpreter is itself written in Snafu (or equivalently exposed). Multiple interpreter levels can be stacked; each level's source is modifiable.
4. **Uniformity.** Code is data — specifically, strings. Code blocks are sugar over strings-with-lexical-scope. A single concept (algebraic effects) subsumes exceptions, generators, async, reactive callbacks, and ambient context.
5. **No concern for performance.** The language spec chooses the semantically clean option even when it's slow. Speed is the implementation's problem, not the language's.
6. **No memory safety, type safety, or optimization features.** These are out of scope. Snafu is dynamic, mutable, and trusting.

### Consequences

- Multiple dispatch is the primary dispatch model (§13).
- Prototype-based OO; no class/instance split (§14).
- Eager evaluation by default; lazy is opt-in (§6, §21).
- Undefined (`und`) propagates silently by default; strict mode (`sd`) raises exceptions (§7).
- Structured exceptions are sugar over algebraic effects (§19, §20).
- Tail calls do not consume stack (§33) — semantic, not optimization.

### Non-goals

- Static type checking.
- Compile-time guarantees of any kind (besides syntax validity).
- Binary size, startup time, or runtime performance targets.
- Sandbox or security isolation by default.

---

## 2. Canonical symbol table

The following are reserved. The short form is canonical; longer aliases are equivalent and interchangeable.

### Control flow

| Short | Long        | Purpose                                                    |
| ----- | ----------- | ---------------------------------------------------------- |
| `if`  | `if`        | Conditional                                                |
| `el`  | `else`      | Else clause                                                |
| `eli` | `elif`      | Else-if                                                    |
| `mt`  | `match`     | Pattern match (§12)                                        |
| `for` | `for`       | Iteration                                                  |
| `in`  | `in`        | Iteration source (part of `for`)                           |
| `wh`  | `while`     | While loop                                                 |
| `un`  | `until`     | Until loop                                                 |
| `lp`  | `loop`      | Infinite loop / n-repeat                                   |
| `bf`  | `before`    | Before-block (runs before each iteration)                  |
| `bt`  | `between`   | Between-block (runs between iterations)                    |
| `af`  | `after`     | After-block (runs after each iteration)                    |
| `br`  | `break`     | Break out of loop                                          |
| `cn`  | `continue`  | Continue loop                                              |
| `r`   | `return`    | Return from function                                       |
| `y`   | `yield`     | Yield value from generator                                 |
| `yf`  | `yield_from`| Yield from subgenerator                                    |
| `goto`| `goto`      | Unconditional jump to label                                |
| `cf`  | `comefrom`  | Reactive jump point                                        |
| `rm`  | `resume`    | Resume at last control-flow change                         |
| `lbl` | `label`     | Define a label                                             |
| `by`  | `by`        | Step clause in range: `0..10 by 2`                         |

### Exceptions and strict mode

| Short | Long        | Purpose                               |
| ----- | ----------- | ------------------------------------- |
| `ty`  | `try`       | Try block (§19)                       |
| `ex`  | `except`    | Except clause                         |
| `fi`  | `finally`   | Finally clause                        |
| `rs`  | `raise`     | Raise exception                       |
| `fr`  | `from`      | Chain causing exception               |
| `sd`  | `strict`    | Strict-mode block (raises on `und`)   |
| `ld`  | `loose`     | Loose-mode block (reverses `sd`)      |

### Functions and dispatch

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `df`  | `def`       | Define named function (§11)                     |
| `f`   | `fn`        | Anonymous function / function value             |

### Types and protocols

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `sm`  | `sum`       | Sum type declaration (§16)                      |
| `pr`  | `protocol`  | Protocol declaration (§15)                      |
| `im`  | `impl`      | Implement protocol for type                     |
| `dv`  | `derive`    | Auto-derive protocol impls                      |

### Effects, macros, and concurrency keywords

| Short | Long        | Purpose                              |
| ----- | ----------- | ------------------------------------ |
| `ef`  | `effect`    | Declare an effect (§20); soft keyword|
| `pf`  | `perform`   | Perform an effect (§20); soft keyword|
| `hd`  | `handle`    | Handle effects (§20); soft keyword   |
| `mc`  | `macro`     | Macro declaration (§30); soft keyword|

### Contracts

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `req` | `require`   | Precondition on function (§37f); soft keyword   |
| `ens` | `ensure`    | Postcondition on function (§37f); soft keyword  |

### Queries and comprehensions

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `qr`  | `query`     | Declarative query expression (§37h); soft keyword |
| `whr` | `where`     | Where clause / query filter (§37g); soft keyword |
| `sel` | `select`    | Query select clause (§37h); soft keyword        |
| `srt` | `sort`      | Query sort clause (§37h); soft keyword          |

### Stack-based and logic

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `stk` | `stack`     | Stack-based (Forth-style) block (§37i); soft keyword |
| `fk`  | `fork`      | Universe fork (§37k); soft keyword              |
| `dy`  | `dynamic`   | Dynamic scoping block (§37j); soft keyword      |
| `rec` | `record`    | Execution recording block (§37l); soft keyword  |

### Scope

| Short | Long        | Purpose                                                 |
| ----- | ----------- | ------------------------------------------------------- |
| `sc`  | `scope`     | Current scope (§10)                                     |
| `ca`  | `caller`    | Caller's scope                                          |
| `tp`  | `top`       | Top-level (module) scope                                |
| `ev`  | `eval`      | Evaluated-string's own scope (inside `.ca()` body)      |

### Concurrency

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `gt`  | `green`     | Spawn green thread (§22)                        |
| `as`  | `async`/`as`| Binding keyword in `wi` (§37b); soft keyword    |
| `aw`  | `await`     | Await/join a future handle (§22)                |
| `sl`  | `select`    | Channel select (§22); soft keyword              |
| `xs`  | `execset`   | Execution set — concurrent statements (§24); soft keyword |

### Reactive

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `on`  | `on`        | Reactive trigger install                        |
| `of`  | `off`       | Trigger remove                                  |

### Modules

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `us`  | `use`       | Import / namespace-prefix shortcut              |
| `xp`  | `export`    | Declare module exports                          |

### State and time-travel

These are **prelude functions** (not reserved keywords). See §34 and §37.

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `ps`  | `pushstate` | Push current state into state buffer (special form) |
| `sa`  | `atomic`    | State-buffer access by index (prelude fn)       |
| `sp`  | `snap`      | State-buffer access by name or index (prelude fn)|
| `st`  | `state`     | Current program state snapshot (special form, 0-arg call) |
| `restore` | `restore` | Restore bindings from snapshot (special form) |

### Self-modification

These are **global-scope bindings** set at program startup (not reserved keywords). See §35.

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `src` | `source`    | Current program's source text (Str binding)     |
| `ast` | `ast`       | Current program's AST (Block node binding)      |

### Debugging

`bp()` is a **prelude special form** (not a reserved keyword). See §37.

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `bp`  | `breakpoint`| Inline debugger REPL (special form in prelude)  |

### Generators / coroutines

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `ct`  | `coroutine` | Declare a coroutine/generator; soft keyword     |

### Literals, sentinels, and operators

| Name     | Meaning                                          |
| -------- | ------------------------------------------------ |
| `und`    | Undefined / null (see §7)                        |
| `true`   | Boolean true                                     |
| `false`  | Boolean false                                    |
| `oo`     | Infinity                                         |
| `new`    | Object construction (§14)                        |
| `is`     | Identity comparison operator                     |
| `not`    | Used in `is not`, `not in` compound operators    |
| `??`     | Null-coalesce operator (§8)                      |
| `?.`     | Safe navigation operator (§8)                    |
| `~/`     | Regex findall operator (§8)                      |
| `&`      | Bitwise AND operator (§8)                        |
| `\|`     | Bitwise OR operator (§8)                         |
| `` ` ``  | Backtick lambda delimiter (§11)                  |
| `_`      | Wildcard / slot / placeholder (not reserved)     |
| `s`      | Conventional name for self (not reserved)        |

### Context

| Short | Long        | Purpose                                         |
| ----- | ----------- | ----------------------------------------------- |
| `wi`  | `with`      | Context manager (§37b)                          |
| `as`  | `as`        | Binding name in `wi` (soft keyword, also used in concurrency) |

### Other identifiers used in prelude

See §37 for the standard prelude. None of its names are reserved at the lexical level — you can shadow them — but doing so is discouraged.

### Number-type names

`Num`, `Int`, `Rat`, `Flt`, `Cx`, `Big`, `Bool`, `Str`, `Lst`, `Dct`, `Set`, `Tup`, `Fn`, `Obj`, `Sym`, `Chn`, `Ftr`, `Iter`, `Itor`. These are the built-in type-prototype names; they're ordinary prototypes, just pre-installed. (`Qn`, `Mx`, `Tnsr` are specified but not implemented.)

---

## 3. Lexical structure

### Source encoding

UTF-8 only. A source file **may** begin with a UTF-8 BOM (EF BB BF); if present, it's consumed silently. No other encoding is accepted.

### Newlines

`LF` (0x0A), `CR` (0x0D), or `CRLF` (0x0D 0x0A) — all normalized to LF for lexical purposes.

### Whitespace

Spaces (0x20), horizontal tabs (0x09), and newlines are whitespace. A run of whitespace is one separator token.

### Comments

- `# …` — line comment, to end of line.
- `#{ … }#` — block comment, nestable.

Comments do not nest inside strings. Strings do not nest inside comments.

### Identifiers

```
identifier = id_start id_cont*
id_start   = letter | '_'
id_cont    = letter | digit | '_'
letter     = Unicode letter category L
digit      = '0'–'9'
```

Identifiers are case-sensitive. Non-ASCII letters are allowed. A leading `_` is allowed but has no special meaning.

### Keywords

Most names in §2 are hard-reserved keywords. A small set are **soft keywords** -- they act as keywords in statement/expression positions where their keyword meaning applies, but are legal as identifiers in other contexts (parameter names, attribute names, `expect_name` positions):

Soft keywords: `r`, `f`, `y`, `yf`, `ct`, `as`, `ex`, `in`, `not`, `by`, `xs`, `pf`, `ef`, `hd`, `mc`, `sl`, `whr`, `qr`, `stk`, `sel`, `srt`, `fk`, `req`, `ens`, `dy`, `rec`.

Context-sensitivity rules:
- `r` is a return statement unless followed by `=`, `.=`, `+=`, `-=`, `*=`, `/=`, `:=`, `~=`, `.`, or `[` (which indicate assignment or access to a variable named `r`).
- `y` is a yield expression unless followed by `=`, `+=`, `-=`, `*=`, `/=`, `.=`, `:=`, `~=` (which indicate assignment to a variable named `y`).
- `f` is a function literal when followed by `->`, `{`, or `(params)` then `->` or `{`. Otherwise it is a variable reference.
- `pf` is a perform statement unless followed by an assignment operator (`=`, `+=`, etc.).
- `ef` is an effect declaration when followed by an identifier; otherwise it is a variable reference.
- `hd` is a handle statement when followed by `{`; otherwise it is a variable reference.
- `mc` is a macro declaration when followed by an identifier or keyword; otherwise it is a variable reference.
- `xs` is an execution set when followed by `{`; otherwise it is a variable reference.
- `sl` is a select in prelude function form (always a variable reference since it's not a statement keyword).
- `ct`, `as`, `ex`, `in`, `not`, `by` may appear as identifiers in name-only positions (field names, parameter names, attribute names).

Hard-reserved keywords cannot be used as identifiers.

### Tokens

The lexer emits these token kinds:

- identifiers
- keywords
- numeric literals (§4)
- string literals (§5)
- regex literals (§26)
- operator/punctuation tokens (§8)
- statement separators (§9)
- comments (discarded)

### Numeric literal forms (lexical level; semantics in §4)

- Decimal integer: `[0-9][0-9_]*`
- Decimal float: `[0-9_]+ '.' [0-9_]+ ('e' [+-]? [0-9_]+)?`
- Exponent form: `[0-9_]+ 'e' [+-]? [0-9_]+`
- Binary: `[01_]+ 'b'`
- Hex: `[0-9a-fA-F][0-9a-fA-F_]* 'h'`
- Octal: `[0-7][0-7_]* 'o'`
- Base36: `[0-9a-zA-Z][0-9a-zA-Z_]* '_'` — but underscores can't appear in base36 payload; use the trailing `_` only as the marker.
- Imaginary suffix: `i` or `j` for complex; `j`, `k` for quaternion components (see §4).

`_` in numeric literals is a visual separator and is ignored: `1_000_000` is `1000000`.

The notes' "multi-dot fractions" (`3.141.593`) are **not** supported — conflicts with `..` range operator. A numeric literal has at most one `.`.

### String literal forms (lexical level; semantics in §5)

- `"…"` — interpolating, single-line
- `'…'` — literal, single-line, no interpolation
- `"""…"""` — interpolating, multi-line
- `'''…'''` — literal, multi-line
- `r"…"` / `r'…'` — raw (no escape processing); `r"…"` still interpolates unless also `br`
- `b"…"` / `b'…'` — bytes literal
- `rb"…"` — raw bytes
- `<<<EOT … EOT` — heredoc, interpolates
- `<<<'EOT' … EOT` — nowdoc, no interpolation

Escape sequences in interpolating strings: `\n \r \t \\ \" \' \0 \xNN \uNNNN \UNNNNNNNN \${` (literal `${` without interpolation).

### Regex literals

`r/ pattern /flags` — lex as a single token. Escape `/` with `\/`. Flags: `imsxgu`.

An alternative delimiter when `/` is inconvenient: `r#/ pattern /#` (with `#`-padding, any count, matched on close).

### Operator tokens

Full precedence and semantics in §8. The lexer recognizes these (longest match):

```
+  -  *  /  //  %  **  ^^
==  !=  <>  ===  !==
<  >  <=  >=  !<  !>
<<=  >>=  ..
!  &&  ||
<-  ->  !<-  !->  !&&  !||  !^^
=  :=  +=  -=  *=  /=  //=  %=  **=  <>=  ===  !===  <-=  ->=  !<-=  !->=  &&=  ||=  ^^=  !&&=  !||=  !^^=
.=  [:]=  ()=
.  ..  ...
?  :
|>  |>>
@  $  ~  `
=~  ??  ?.  ~/
\
;  ,  (  )  [  ]  {  }
```

**APL-style operator modifiers** (see §37a for full semantics):

```
+.  -.  *.  /.  **.  //.  %.  ==.  <>.  <.  >.  <=.  >=.  &&.  ||.  ^^.   # element-wise
+..  -..  *..  **..  /..  %..  ==..  <>..  <..  >..                       # outer product
+/  -/  */  **/  %/                                                        # reduce (prefix)
+\  -\  *\  **\  %\                                                        # scan (prefix)
```

Multi-character tokens are greedy (longest match). `**` is always power, `***` is `**` then `*` (rarely useful; parenthesize).

**Note:** `#` is a comment prefix only (see §3 comments). It is **not** a unary length operator at the lexer level -- the lexer consumes `#` as a comment before operator matching. Use `len(x)` for length.

### `$` at the lexical level

`$` introduces a variable-variable reference (§10) or an interpolation site inside a string. Grammar decides which based on context.

### Line continuation

Expressions can span multiple lines implicitly when:
- An open bracket `([{` is unclosed.
- The last token on a line is a binary infix operator (including `+`, `-`, `*`, `/`, `%`, `**`, `//`, all comparison operators, `&&`, `||`, `^^`, `|>`, `|>>`, `=`, `:=`, `~=`, `.=`, compound-assign ops, `,`, `.`, `?`, `:`, and all element-wise/outer-product operators).
- The first non-whitespace token on the next line is a binary infix operator (especially `|>`, `+`, `-`, `*`, `/`, `.`, comparison ops, etc.).
- A backslash `\` at end of line suppresses newline as statement separator.

### Statement separators

- Newline terminates a statement if at syntactic statement-end (emitted as a `NEWLINE` token by the lexer).
- `;` always terminates a statement (the lexer emits it as a `NEWLINE` token, identical to newline for the parser).
- Both `\n` and `;` are therefore interchangeable as statement separators.
- `,` separates items in list/call contexts; can separate statements but with lower precedence than `;`.
- Precedence: `space < , < ;` — see §9.

---

## 4. Numbers

### Number tower

Built-in numeric types, in tower order:

1. `Int` — arbitrary-precision integer (bignum).
2. `Rat` — arbitrary-precision rational, stored as `(num, den)` of bignums.
3. `Flt` — IEEE 754 double-precision.
4. `Cx` — complex number, `(re, im)` each being `Int | Rat | Flt`.

A type higher in the tower can represent all values of types below it. Arithmetic between two types produces a value of the higher type (promotion).

**Quaternions** (`Qn`) were originally specified but are not implemented. See §40.

**Big numbers** (`Big`) is an alias for `Int` — all integers are arbitrary-precision.

### Symbolic numbers

Every numeric operation result is, by default, kept in **symbolic** form: an expression tree retaining its origin. `1 + 2` is represented internally as `Add(1, 2)` until a reduction is forced.

**Reduction triggers** (force flattening):
- Display: `p(x)` prints a reduced value.
- Bitwise op: `x & 5` requires an Int.
- Comparison: `x < y` requires comparable-flat values.
- Explicit: `flat(x)` (see §37).
- Used as a dict key / set element.
- Sent to a Python interop boundary.

Reduction applies algebraic simplification where easy: `1 + 0 → 1`, `x * 1 → x`, `x - x → 0`, `x / x → 1` (when `x ≠ 0`). More sophisticated simplification (factoring, expansion) is opt-in via `simp(x, level: N)`.

### Exact rationals

Division produces `Rat`, not `Flt`, unless one operand is `Flt`:

```
1 / 3          # Rat(1, 3)
1.0 / 3        # Flt(0.3333…)
```

`Rat(0, 0)` is `und`, not an exception. Other zero denominators → `oo` (infinity) with the sign of numerator.

### Infinity and NaN

`oo` is positive infinity. `-oo` is negative. `nan` is not-a-number (IEEE NaN — only arises in `Flt`). `und` is distinct from `nan`.

### Literal forms (recap of §3)

```
42                 # Int
1_000_000          # Int with separators
3.14               # Flt
1e10               # Flt
1.5e-3             # Flt
2/3                # Rat — parsed as (Int 2) / (Int 3), always rational
1010b              # Int 10 (binary)
ffh                # Int 255 (hex)
0xffh              # Int 255 (also hex; 0x prefix optional)
777o               # Int 511 (octal)
zz_                # Int 1295 (base36)
3i                 # Cx(0, 3)
1+2i               # Cx(1, 2)
2j                 # Qn(0, 0, 2, 0)   — NO: 2j is ambiguous with 2i form in complex
1+2i+3j+4k         # Qn(1, 2, 3, 4)
```

**Complex numbers:** `3i` is a pure-imaginary complex literal (`Cx(0, 3)`). The `i` suffix on a numeric literal creates the imaginary component. Complex values are Python `complex` objects internally. Attribute access: `.re` (real part), `.im` (imaginary part), `.conj()` (conjugate), `.abs()` (magnitude). The `cx(re, im)` prelude function constructs complex numbers programmatically.

### Matrix and tensor

`Mx` and `Tnsr` are built-in but are not part of the number tower. They are constructed with:

```
mx([[1,2],[3,4]])        # 2x2 matrix
tnsr([...], shape: [2,3,4])
```

Element-wise arithmetic is default; `@` is matrix multiplication; `.T` is transpose.

### Number-related functions (§37 for full list)

- `flat(x)` — force reduce symbolic expression
- `cf(x)` — continued fraction representation
- `simp(x, level: N)` — aggressive symbolic simplification
- `int(x)`, `flt(x)`, `rat(x)`, `cx(x)`, `qn(x)` — coerce
- `abs(x)` or `|x|` (§8)
- `sgn(x)` — sign: -1, 0, +1
- `floor`, `ceil`, `round`, `trunc`
- `sqrt`, `cbrt`, `nthroot(x, n)`, `x // n` — nth root (§8)
- `exp`, `log`, `ln`, `log2`, `log10`, `##` (log operator, §8)
- `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`, `cosh`, `tanh`
- `fact(n)` or `n!`

---

## 5. Strings

### String values

`Str` is a sequence of Unicode code points. Indexing is by code point, not byte. Length is `len(s)` (or the `.len()` method).

### Quoting rules

| Delimiter       | Multi-line | Interpolates | Escapes processed | Bytes |
| --------------- | ---------- | ------------ | ----------------- | ----- |
| `"…"`           | No         | Yes          | Yes               | No    |
| `'…'`           | No         | No           | Yes (limited)     | No    |
| `"""…"""`       | Yes        | Yes          | Yes               | No    |
| `'''…'''`       | Yes        | No           | Limited           | No    |
| `r"…"` / `r'…'` | No         | `r"`: yes; `r'`: no | No           | No    |
| `b"…"`          | No         | Yes          | Yes               | Yes   |
| `b'…'`          | No         | No           | Limited           | Yes   |
| `<<<EOT…EOT`    | Yes        | Yes          | Yes               | No    |
| `<<<'EOT'…EOT`  | Yes        | No           | Limited           | No    |

"Limited" escapes means `\\` (backslash) and `\<delim>` (to include the delimiter) are processed; others pass through.

### Interpolation

`${expr}` evaluates `expr` and substitutes its string form:

```
name = "World"
"Hello, ${name}!"                     # "Hello, World!"
"${ 1 + 2 }"                          # "3"
"${ func(x, y) }"                     # evaluates func, substitutes
"${x:.2f}"                            # format spec after colon (§5.3)
```

A bare `$name` (no braces) inside a string is shorthand for `${name}` when `name` is a single identifier.

Nested interpolation works:
```
"outer ${f("inner ${x}")}"
```

**Escaping**: `\${` is literal `${`.

### Format specs

Python f-string-style, after a `:` inside `${…}`:

- `:.Nf` — N decimal places
- `:N` / `:>N` / `:<N` / `:^N` — pad to width N (right/left/center)
- `:Nd`, `:Nx`, `:No`, `:Nb` — decimal/hex/octal/binary
- `:#x`, `:#o`, `:#b` — with 0x/0o/0b prefix
- `:+` — always show sign
- `:,` — thousands separator (English locale only; locale-aware via `fmt(x, ...)`)
- `:E` — scientific

Format specs delegate to the value's `Show` / `Fmt` protocol (§15) — user types can define custom specs.

### Heredocs (PHP-style)

```
msg = <<<EOT
  Hello, ${name}!
  Line 2.
EOT
```

Common leading whitespace is stripped to match the closing terminator's column (Python `textwrap.dedent` semantics). Terminator must be on a line by itself. Any identifier works for the delimiter; pick one not appearing in the body.

Nowdoc (`<<<'EOT'…EOT`) is identical except no interpolation and no escape processing.

### Strings as code

Every `Str` can be executed as Snafu code:

```
"p(42)".ca()                          # prints 42, returns und
"x + 1".ca(sc: {x: 5})                # returns 6
code = "for i in 0..10 { p(i) }"
code.ca()                             # run it
```

`.ca()` method on a string parses and evaluates. Default scope = global (top-level). In the current implementation, `"code".ca()` evaluates in the global scope, while `ev("code")` evaluates in the caller's scope (see §31).

Code blocks `{…}` are **sugar** for a string literal tagged with its lexical scope at definition. Semantic difference:
- Code block `{body}`: scope is lexical at definition site.
- String `"body"`: scope is dynamic (caller) unless `sc:` is passed.

Both compile-once-and-cache; repeated `.ca()` doesn't re-parse.

### String operations

- `a + b` — concat
- `a * n` — repeat (integer n)
- `a == b` — element equality
- `a < b` — lexicographic
- `s[i]` — code point at index i (may be negative)
- `s[i:j]` — slice (§6)
- `len(s)` — length
- `in`: `"sub" in s` — substring containment
- Methods: `.upr()`, `.lwr()`, `.strip()`, `.lstrip()`, `.rstrip()`, `.split(sep)`, `.join(iter)`, `.replace(a, b)`, `.starts(x)`, `.ends(x)`, `.find(x)`, `.count(x)`, `.cp()` — see §37.

### Bytes vs strings

`b"…"` is a `Bytes` value — a sequence of integers 0–255. Not the same as `Str`. Conversion: `s.en("utf-8")` → bytes; `b.de("utf-8")` → string.

---

## 6. Collections

Snafu collapses list/dict/ordered-set into a single primary collection — the **ordered key-value collection** (OKVC) — with specialized fast-paths.

### The unified collection

Syntax: `[…]` for **all** collections — lists, dicts, and mixed. `{…}` is reserved for code blocks only (§9). Lua-style: one literal form, keys optional.

```
[1, 2, 3]                # list — implicit keys 0, 1, 2
["a", "b", "c"]          # list
["x": 1, "y": 2]         # dict — explicit keys
[1, 2, "k": 3]           # mixed — 0→1, 1→2, "k"→3
[1, 2, 6: 5, "blah"]     # positional 0→1, 1→2, explicit 6→5, positional 7→"blah"
```

Per the notes: `[1, 2, 6: 5, "blah"][2]` is `6` (positional — the third element at insertion position 2 happens to be the `6` of the `6: 5` pair's key-slot? No — let me be precise). The rule:

- Entries without `k:` are positional; they take the next unused positional index starting from 0.
- Entries with `k: v` assign explicit keys.
- Positional index counter advances past any explicit integer keys it hits.

So for `[1, 2, 6: 5, "blah"]`:
- positional 0 → 1
- positional 1 → 2
- explicit 6 → 5 (positional counter jumps to 7)
- positional 7 → "blah"

Indexing `[1, 2, 6: 5, "blah"][2]` looks up position 2 → `und` (there's a gap at positions 2..5). Indexing `[6]` → `5`. Indexing `[7]` → `"blah"`.

Access:

```
c[2]                     # by integer/string key — unified lookup
c[k]                     # works with any hashable key
c.k[k]                   # dict-style view (skip positional semantics)
c.i[0]                   # list-style view (positional only, ignore string keys)
```

There is no `{…}`-disambiguator for keyed access — `[…]` does both.

### Multi-index access

```
l[1, 3, 5]               # returns [l[1], l[3], l[5]] — a new collection
l[1, 3, 5] = (a, b, c)   # assigns l[1]=a, l[3]=b, l[5]=c
```

### Slicing

```
l[a:b]                   # from index a to b (exclusive)
l[a:b:s]                 # with step s
l[a:b:w:i]               # sliding window: width w, stride i
```

`l[::2:1]` on `[0,1,2,3,4,5]` yields `[[0,1],[1,2],[2,3],[3,4],[4,5]]` — all width-2 windows.

Negative indices count from end. Omitted `a` means 0; omitted `b` means length; omitted `s` means 1.

### Two-way dicts

```
d = [1: "a", 2: "b"]
d[1]                     # "a"
d.inv["a"]               # 1 — reverse lookup
~d["a"]                  # same; ~ is the "invert" operator when applied to dicts
d.inv_get("a")           # 1 — find the first key whose value equals the argument
```

`~d` returns a fully inverted dict (swapping keys and values). `.inv_get(val)` returns the first key `k` where `d[k] == val`, or `und` if no match. Unlike `~d`, `.inv_get()` does not build an intermediate dict -- it performs a linear scan and stops at the first match.

Inverting requires values to be hashable. For non-injective dicts (duplicate values), `~d` keeps the last key encountered for each value (no dict-of-lists -- later entries overwrite earlier ones).

### Frozen (persistent) collections

```
fr[1, 2, 3]              # frozen list
fr["x": 1]               # frozen dict
fr["x": 1, "y": 2]       # frozen dict
```

No literal set form. For a set: `st([1, 2, 3])` builds a set from a list, or use a dict-of-trues `["a": true, "b": true]`. Set operations (below) work on lists/dicts regardless of whether the form is set-shaped.

Frozen collections are immutable. Hashable. Suitable as dict keys / set members. Structural-shared when modified via `assoc` / `dissoc`:

```
fl = fr[1, 2, 3]
fl2 = fl.assoc(1, 99)    # fr[1, 99, 3]; fl unchanged
```

### Sets

No literal syntax. Constructed via:

```
s = st([1, 2, 3])        # build a set from an iterable
s = st{1, 2, 3}          # NO — {} is always a code block; this doesn't work
s = [1, 2, 3].to_set()   # method form
```

A set is internally a dict with values `true` (implementation detail; `Set` is its own protocol-level type).

### Set operations

```
a | b                    # union
a & b                    # intersection
a - b                    # difference (relative complement)
a ^ b                    # symmetric difference
a <= b                   # subset
a < b                    # proper subset
a >= b                   # superset
```

These work on any `Set` / `Dct` / `Lst` (lists treated as multisets).

### Stack / queue ops

```
l.psh(x)                 # push to end
l.pop()                  # pop from end, returns value
l.pfr(x)                 # push to front
l.ppr()                  # pop from front
l.pk()                   # peek at end, no remove
l.pkf()                  # peek at front
```

Any `Lst` functions as deque.

### Variables as stacks

From the notes: every variable has a stack behavior via:

```
psh(x, v)                # push v onto variable x
pop(x)                   # pop from variable x; x becomes the top
```

Implementation: `psh` wraps `x` in an internal stack; subsequent reads of `x` return the top; reassigning `x = y` replaces the whole stack. This is off by default; enable per-variable with `st_stack(x)` or per-scope.

### Iteration

Lists and dicts implement `Iter` (§21). Iterating a dict yields `(k, v)` tuples by default; `.keys()` and `.values()` give the single-element views.

### Multi-dimensional iteration

```
for x in matrix              # yields each scalar, row-major
for row in matrix.rows       # yields rows
for x (i,j) in matrix.nd(2)  # yields each with its indices
```

### Construction helpers

```
rg(0, 10)                    # range [0,1,…,9]
0..10                        # same as rg(0, 10) — half-open
0..=10                       # inclusive
rp(x, n)                     # n copies of x
zp(a, b)                     # zip
en(a)                        # enumerate, yields (i, x)
```

---

## 7. `und` — undefined

### Nature

`und` is the single null value. `None`, `Null`, `Nil` do not exist in Snafu — `und` is the only such thing.

`und` has its own type (`Und`) and is a singleton (`und is und` always true).

### Propagation (default)

By default, any operation involving `und` produces `und`:

```
und + 1                      # und
und == und                   # und   (NOT true — propagation is strict!)
und.attr                     # und
und()                        # und
```

This is the "loose" mode and is the default.

**Exception: `is`, `===`, `mt` patterns** — these never propagate. They compare `und` structurally:

```
und is und                   # true
und === und                  # true
mt x { und -> ..., _ -> ... } # matches und case when x is und
```

### Strict mode — `sd`

In a `sd` block, operations on `und` raise `UndErr`:

```
sd {
  result = x / 0             # raises DivErr (not und)
  v = some_func()            # if returns und and is used arithmetically: UndErr
}
```

Enable for the whole program with a top-level `sd` statement:

```
sd                          # all following code strict
# … rest of program
```

Per-scope override inside strict: `ld { … }` ("loose") re-enables propagation in that block.

### Testing for `und`

```
x is und                     # preferred test
x === und                    # also works; always true/false
mt x { und -> ..., _ -> ... }
```

`x == und` does NOT work — it returns `und` (propagation).

### `und` in collections

```
[1, und, 3][1]               # und — just a value in the list
["k": und]                   # valid; key k present with und value
```

Collections treat `und` as any other value.

---

## 8. Expressions and operators

### Precedence table

Higher number = tighter binding. Evaluated left-to-right within a precedence level unless marked right-assoc.

| Level | Operators                                                  | Assoc      |
| ----- | ---------------------------------------------------------- | ---------- |
| 100   | `()` call, `[]` index, `{}` key-index, `.` attr            | left       |
| 95    | unary `+ - ! ~ * /` (in prefix position), `op/` reduce, `op\` scan | right      |
| 90    | `**`, `//` (nth root)                                      | right      |
| 85    | `*`, `/`, `%`                                              | left       |
| 80    | `+`, `-`                                                   | left       |
| 75    | `..` (range), `..=` (inclusive range)                      | left       |
| 70    | `==` `<>` `===` `!==` `<` `>` `<=` `>=` `!<` `!>` `is` `in` | non-assoc  |
| 65    | `!` boolean not (prefix)                                   | right      |
| 62    | `&` bitwise AND (§8)                                        | left       |
| 60    | `&&`, `!&&` (nand)                                         | left       |
| 55    | `^^`, `!^^` (xor, xnor)                                    | left       |
| 50    | `\|\|`, `!\|\|` (or, nor)                                  | left       |
| 48    | `\|` bitwise OR (§8)                                        | left       |
| 45    | `<-`, `->`, `!<-`, `!->` (implication)                     | right      |
| 40    | `?:` (ternary)                                             | right      |
| 35    | `\|>`, `\|>>` (pipeline)                                   | left       |
| 32    | `??` null-coalesce (§8)                                     | right      |
| 30    | `:=` (alias bind), `~=` (tracking bind)                    | right      |
| 25    | `=` and compound `+= -= *= …`                              | right      |
| 20    | `,` (list/tuple separator in value position)                | left       |
| 10    | `;` (statement separator)                                   | left       |

### APL-style operator modifiers

Any arithmetic or comparison operator can be suffixed with a modifier:

| Modifier | Syntax      | Precedence                | Meaning                                |
| -------- | ----------- | ------------------------- | -------------------------------------- |
| `.`      | `op.`       | Same as base op           | Element-wise (broadcasts across lists) |
| `/`      | `op/`       | Unary prefix, high (95)   | Reduce (fold list with op)             |
| `\`      | `op\`       | Unary prefix, high (95)   | Scan (running reduce)                  |
| `..`     | `op..`      | Same as base op           | Outer product (all pairs)              |

Reduce and scan operators (`+/`, `*\`, etc.) are parsed as unary prefix operators at the same precedence as other unary operators (level 95). Element-wise (`+.`, `*.`) and outer-product (`+..`, `*..`) are binary operators at the same precedence as their base operator. See §37a for full semantics and examples.

### Arithmetic operators

```
a + b                        # add
a - b                        # sub
a * b                        # mul
a / b                        # div (rational-preserving if both Int)
a // b                       # nth root: a^(1/b) — !! not floor div !!
a % b                        # modulo
a ** b                       # power
```

Note: `//` is nth root, not floor division (differs from Python). Floor division is `fl_div(a, b)` or `(a / b).floor()`.

### Comparison

```
a == b                       # semantic equality (overridable via Eq, §32)
a <> b                       # not-equal
a === b                      # structural equality (never overridable)
a !== b                      # not-structurally-equal
a < b                        # less
a > b                        # greater
a <= b                       # less-or-equal
a >= b                       # greater-or-equal
a !< b                       # not-less
a !> b                       # not-greater
a is b                       # identity
a is not b                   # alias for !(a is b)
a in c                       # membership
a not in c                   # alias
```

Chain comparisons (Python-style): `a < b < c` = `a < b && b < c`. Each sub-comparison evaluates once.

### Boolean

```
! x                          # not
a && b                       # and (short-circuit)
a || b                       # or (short-circuit)
a ^^ b                       # xor (no short-circuit)
a !&& b                      # nand
a !|| b                      # nor
a !^^ b                      # xnor
a <- b                       # a implied by b = (!b || a)
a -> b                       # a implies b = (!a || b)
a !<- b                      # !( a <- b )
a !-> b                      # !( a -> b )
```

`true` and `false` are the canonical booleans. Truthiness (for `if`, `&&`, etc.): `und`, `0`, `0.0`, `""`, `[]`, `{}` are falsy; everything else is truthy. In `sd` mode, only `true`/`false` are accepted in boolean position; others raise `TruthErr`.

### Pipeline

```
x |> f                       # f(x)
x |> f(y)                    # f(x, y)          — first-arg pipe
x |> f(_, y)                 # f(x, y)          — explicit slot
x |> f(y, _)                 # f(y, x)
x |>> f(y)                   # f(y, x)          — last-arg pipe
```

`|>` is first-arg default. `|>>` is last-arg. `_` is the explicit placeholder slot.

### Ternary

```
cond ? a : b                 # if cond then a else b
```

Right-associative: `a ? b : c ? d : e` = `a ? b : (c ? d : e)`.

### Range

```
a..b                         # half-open: a, a+1, …, b-1
a..=b                        # closed: a, a+1, …, b
a..b by s                    # step s
```

Range is an `Iter`. Lazy (doesn't materialize).

### Length and absolute value

```
len(x)                       # length of x (use len(), not #)
|x|                          # absolute value / magnitude / vector norm
```

**Note:** `#` is reserved as a comment prefix and cannot be used as a unary length operator. Use `len(x)` instead.

`|x|` is a paired-delimiter form: it must be on one line with balanced pipes. For ambiguity with `||` (or), a leading space or newline is required: `| x |` or `|x|` in a position where `||` can't start.

### Binding operators

```
b = a                        # copy value of a into b; b and a now independent
b := a                       # alias: b and a refer to same value; assignments to either affect both
b ~= a                       # tracking: b is recomputed from a on every read of b
```

For `~=`: the right-hand side must be an expression, not just a variable. `b ~= x + 1` means: reading `b` returns current `x + 1`. See §10.

### Compound assignment

All binary operators have `op=` form:

```
x += y                       # x = x + y
x -= y
x *= y
x /= y
x //= y                      # nth-root assign
x %= y
x **= y
x <>= y                      # x = (x <> y) — weird; rarely useful
x &&= y                      # x = x && y (short-circuit: only assigns if x is truthy)
x ||= y
x ^^= y
```

### `.=` and friends

```
x .= f                       # x = f(x)        — monadic-style "modify through a function"
x .= lens => value           # x = lens.st(x, value)
```

`.=` is "update `x` with the result of applying something to it". The RHS can be a function value (applied to current x), a lens followed by `=>` and a new value (lens.st), or a method reference.

### Regex bind — `=~`

```
"hello" =~ r/l+/             # matches regex against string, returns Match object or und
```

The `=~` operator applies a regex object (from a `r/…/` literal) to a string. If the string is on the left and the regex on the right (or vice versa), the regex's `.ma()` method is called. Returns a Match object on success, `und` on failure.

See §26 for regex details.

### Null-coalesce — `??`

```
x ?? default                     # if x is und, evaluates and returns default; otherwise x
d["key"] ?? "fallback"           # dict lookup with default
chain ?? fallback ?? last        # right-associative chaining
```

Short-circuit: `default` is only evaluated if `x` is `und`.

### Safe navigation — `?.`

```
obj?.name                        # und if obj is und; otherwise obj.name
obj?.method()                    # und if obj is und; otherwise call method
a?.b?.c                          # chaining: if any step is und, result is und
```

`?.` is a postfix operator at the same precedence as `.` (level 100). It returns `und` immediately if the target is `und`, without raising `AttrErr`.

### Bitwise operators — `&`, `|`

```
5 & 3                            # 1  (bitwise AND — infix operator)
5 | 3                            # 7  (bitwise OR — infix operator)
bxor(5, 3)                       # 6  (bitwise XOR — prelude function)
bnot(5)                          # -6 (bitwise NOT — prelude function)
shl(1, 4)                        # 16 (shift left — prelude function)
shr(16, 2)                       # 4  (shift right — prelude function)
```

`&` and `|` are infix operators in the precedence table. `bxor`, `bnot`, `shl`, `shr` are prelude functions. Note: `^^` is boolean XOR, not bitwise — use `bxor` for bitwise XOR.

### Regex findall — `~/`

```
"abc 123 def 456" ~/ r/\d+/     # ["123", "456"]
```

`~/` applies the regex on the right to the string on the left and returns a list of all matches (like Python's `re.findall`). Returns `und` if the right operand is not a compiled regex.

### Unary operators

```
+ x                          # positive (identity for numbers)
- x                          # negation
! x                          # boolean not
~ x                          # inverse / complement (multi-dispatched)
* x                          # positional-arg unpacking in call site (not unary elsewhere)
** x                         # keyword-arg unpacking in call site
| x |                        # absolute value
```

**Note:** `#` cannot be used as a unary length operator because the lexer consumes it as a comment. Use `len(x)`.

`~` dispatches: on dicts it's `d.inv`; on numbers it's bit-complement; on functions it's functional inverse (see §11).

### Operator → function mapping

Every operator is sugar for a named function. Overloading happens via multi-dispatch on that function (§13).

| Operator | Function  | Operator | Function |
| -------- | --------- | -------- | -------- |
| `+`      | `add`     | `==`     | `eq`     |
| `-`      | `sub`     | `<>`     | `ne`     |
| `*`      | `mul`     | `===`    | `seq`    |
| `/`      | `div`     | `!==`    | `sne`    |
| `//`     | `nth_root`| `<`      | `lt`     |
| `%`      | `mod`     | `>`      | `gt`     |
| `**`     | `pow`     | `<=`     | `le`     |
| `&&`     | `band`    | `>=`     | `ge`     |
| `\|\|`   | `bor`     | `is`     | `ident`  |
| `^^`     | `bxor`    | `in`     | `contains` |
| `!`      | `bnot`    | `..`     | `rg_halfopen` |
| `~`      | `inv`     | `..=`    | `rg_closed` |
| `\|…\|`  | `abs`     | `\|>`    | `pipe_first` |
|          |           | `\|>>`   | `pipe_last`  |
| `.`      | `attr`    | `=~`     | `re_bind`    |
| `&`      | `bitand`  | `\|`     | `bitor`      |
| `??`     | `null_co` | `~/`     | `re_findall` |
| `?.`     | `safe_nav`|          |              |

To add an operator for new types, `im` the corresponding function.

### Operator definition

```
df add(Matrix a, Matrix b) = matmul(a, b)
# Now `a + b` on two Matrix values calls this.
```

No extra keyword needed — defining the named function defines the operator.

### Operator composition (math-style)

Function composition with `+`:

```
c = f + g                    # c(x) = g(f(x)) — left-to-right pipeline
c = g . f                    # same as f + g in Haskell style; Snafu uses +
```

Per the notes, `f + g` means "f then g", i.e., `g(f(x))`. This matches pipeline direction (`x |> f |> g`).

Function exponentiation with `^`:

```
f^2(x) = f(f(x))
f^3(x) = f(f(f(x)))
f^0(x) = x   (identity)
f^-1(x) = functional inverse (not yet implemented — raises InterpErr)
```

`f^n` where `f` is a function and `n` is a non-negative integer. The resulting value is a new function that applies `f` exactly `n` times. `f^0` returns an identity function (returns its first argument). Negative exponents (inverse) are specified but not yet implemented.

**Implementation:** `f^n` is parsed as a `FnPower` AST node. At evaluation, the function and exponent are evaluated; the exponent is coerced to `int`. For `n == 0`, an identity lambda is returned. For `n > 0`, a composed function is returned that calls `f` once with the original arguments and then `n - 1` more times, each time passing the previous result as the sole argument.

---

## 9. Statements and blocks

### Statement separators

A statement is terminated by:
- Newline (if the parser is at a valid statement boundary). The lexer emits a `NEWLINE` token.
- `;` (always). The lexer also emits this as a `NEWLINE` token, so `\n` and `;` are interchangeable to the parser.
- `,` (in list/tuple/call contexts, as separator; can also end a statement with lower precedence than `;`)

Precedence: **space < , < ;**

Example: `a = 1, b = 2, c = 3` — three assignments, equivalent to `a = 1; b = 2; c = 3`. But `a = 1, 2, 3` parses as `a = (1, 2, 3)` because the `,` binds tighter than `=`… **No.** `=` has higher precedence than `,` (§8), so `a = 1, 2, 3` is `(a = 1), 2, 3` — three statements with the first being an assignment. To assign a tuple, use `a = (1, 2, 3)`.

### Blocks

A **block** is `{ stmt* }`. Every block is a value — its value is the value of its last statement.

```
x = { 1; 2; 3 }              # x == 3
y = {                        # multi-line
  a = 10
  b = 20
  a + b
}                            # y == 30
```

An empty block `{}` is `und`. This is not confusable with an empty dict `{}` because context disambiguates: value position = dict; block position = block. If truly ambiguous (e.g., returning from a function), wrap: `{ {} }` is a block returning an empty dict.

### Block scope

Each block is a new scope. Assignments inside a block to new names create local bindings. Per the notes: assigning to a **used name** in a subscope does NOT create a local — it mutates the outer binding. No `global` / `nonlocal` keyword needed.

```
x = 1
{ x = 2 }                    # x in outer scope is now 2
{ y = 5 }                    # y in outer scope is now 5 (new binding bubbles up? NO)
```

Wait — re-clarifying per the notes: a new name assigned inside a block **does not** escape. Only assignments to names **already defined in an outer scope** affect the outer scope. This is sane: new names are local; re-assignment is shared.

```
x = 1
{
  x = 2                      # x is OUTER x (reassignment)
  y = 5                      # y is LOCAL (new name)
}
# here: x == 2, y is unbound
```

### Top-level

The top of a program / module is a block. Its scope is the top-level (`tp`) scope.

### Code-block-as-value

Per §5.4, `{…}` in value position is a code block — a compiled string with a lexical-scope tag. The block value has:
- `.ca(…)` — execute in a specified scope
- `.src` — the string form
- `.ast` — the AST form

```
b = { x + 1 }                # stored but not executed
b()                          # or b.ca() — executes in definition-site scope
```

A block in statement position is executed immediately. A block in expression position is a value (not executed until called).

Disambiguation: if a `{...}` appears where a statement is expected, it's executed. If it appears where a value is expected, it's a code-block value. Both are parsed the same; only the context differs.

### Expression statement

A lone expression is a statement. Its value is discarded (unless it's the last statement of the enclosing block).

```
f(x)                         # call, result discarded
x + 1                        # computed, result discarded (pure no-op unless + has side effects)
```

### Context-sensitive keywords in statements

`y` and `r` are context-sensitive at the statement level:
- `y expr` is a yield statement, but `y = expr` or `y += expr` (etc.) is assignment to a variable named `y`.
- `r expr` is a return statement, but `r = expr`, `r.attr`, or `r[i]` is variable usage/assignment to `r`.

This allows using `y` and `r` as ordinary variable names when they appear in assignment or member-access contexts, while preserving their keyword behavior in return/yield positions.

---

## 10. Scope

### Lexical scope

Every scope has:
- a dictionary of local bindings (name → value)
- an optional parent scope (the enclosing scope at definition time)

Name lookup walks up the parent chain until found. This is lexical scoping.

### Scope objects

Scopes are first-class values. The distinguished names:

```
sc                           # current scope (the one executing right now)
ca                           # caller's scope (one frame up dynamic chain)
tp                           # top-level scope of the current module
ev                           # for code inside ev'd strings: the eval's own locals
```

Access:
```
sc.x                         # current x
ca.x                         # caller's x
tp.x                         # module-level x
sc.p                         # parent scope
sc[-1].y                     # navigate up by one — y in parent
sc[-3].z                     # 3 scopes up
sc["x"]                      # dict-like lookup
sc.setattr("x", 5)           # explicit write
```

Scopes implement `Dct`-like protocol (iteration, membership) plus parent navigation.

### Variable-variables — `$`

```
a = "x"
$a                           # looks up "x" in current scope
```

Rules:
- `$identifier` — look up the identifier in current scope, then look up its value (a string) as a name, also in current scope. Two-step lexical lookup.
- `${expr}` — evaluate `expr`, use its string result as a name, look up in current scope.
- `$$x` — look up `x`, then look up that, then look up that. One level of indirection beyond `$x`.
- `$(x)` — same as `${x}` for a single identifier.
- `a$(expr)b` — identifier concatenation: compute `expr` to a string, concatenate `a` + result + `b`, look up in current scope.

**Scope disambiguation**:
- `$x` — lexical (enclosing chain)
- `sc.$x` — dynamic: resolve `x` in current-scope lexically, then the resulting name in current scope **at point of execution** (meaningful in eval'd strings where "current" shifts)
- `ca.$x` — resolve name in caller's scope
- `tp.$x` — resolve name in top-level scope

### Bound variables

Per the notes: two kinds of binding.

**Alias** (`:=`): `b := a` — `b` and `a` are the same binding slot. `a = 5` also sets `b`. `b = 7` also sets `a`.

**Tracking** (`~=`): `b ~= a` or `b ~= expr` — reads of `b` recompute the RHS; writes to `b` raise `BindErr` (tracked vars are read-only through their name).

```
a = 5
b = a                        # b = 5, copy; no link
a = 7                        # b is still 5

b := a                       # alias; now b is 7
a = 10                       # b is now 10
b = 20                       # a is now 20

c ~= a * 2                   # tracking
a = 5                        # c is now 10 (on next read)
a = 100                      # c is now 200
c = 3                        # BindErr — c is tracking, can't assign
```

Implementation: tracking uses a taint graph (§23). When `a` is written, all tracking deps of `a` are marked dirty; next read re-evaluates.

#### Transitive alias chains

Alias bindings follow chains transitively. When `b := a` is evaluated and `a` is already an alias to another variable, `b` points directly to the ultimate target:

```
c = 5
b := c                       # b aliases c
a := b                       # a aliases c (not b) — chain is followed
c = 99
a                            # 99 — a reads through to c
```

**Implementation:** When evaluating `:=`, the interpreter looks up the RHS name and checks if the binding is already an `_Alias`. If so, the new alias points to the existing alias's target scope and name, bypassing intermediaries. This means alias chains never grow longer than one link. Reads and writes through any alias in the chain operate directly on the original variable.

### Scope manipulation

```
sc.keys()                    # list names in current scope
sc.delete("x")               # remove binding
sc.merge(other_scope)        # copy all bindings from other
sc.fork()                    # deep-copy the scope (including parent chain)
```

### Namespace dumping

```
us module_x                  # brings module_x names into current scope prefixed with module_x.
us module_x { body }         # inside body, module_x.X can be written as just X
us *module_x                 # dump ALL names from module_x into current scope unqualified
us *module_x, *module_y      # multiple; later wins on conflict
```

See §25 for full module semantics.

### Dynamic scope opt-in

Algebraic effects (§20) use dynamic scoping by nature (handler lookup walks the dynamic call stack). For plain variables, use `ca.x`, `tp.x`, or explicit `sc` navigation.

---

## 11. Functions

### Named function definition

```
df name(params) body
df name(params) = expr            # single-expression shorthand
```

Examples:
```
df sq(x) = x * x

df factorial(n) {
  if n <= 1 { 1 }
  else { n * factorial(n - 1) }
}
```

### Anonymous function — `f` as context-sensitive keyword

`f` is context-sensitive in expression position:
- `f(params) ->` or `f(params) {` = anonymous function literal
- `f -> expr` or `f { body }` = anonymous function literal (implicit params)
- `f(args)` without `->` or `{` after the `)` = call to a variable named `f`
- `f = expr` = assignment to a variable named `f`

The parser looks ahead past the parenthesized group to decide.

```
f () body                         # no params
f (x, y) body
f (x, y) -> expr                  # single-expression, right-arrow form
f -> expr                         # no explicit params; use implicit a, b
```

The `->` is for the single-expression form. Block form uses `{…}`.

Implicit-args form (replaces old `l`):
- `f -> a * 2` — one-arg-lambda; parameter is named `a` (first positional). For multiple implicit positional args, use `a0, a1, a2, …`. Keyword args go into `b`.

Examples:
```
sq = f (x) -> x * x
add = f (x, y) -> x + y
sq2 = f -> a * a                 # implicit-a
m(f -> a + 1, [1,2,3])           # map a lambda

weirdcat = f { p("hi"); p("there"); a + b }    # block form with implicit a, b
```

### Backtick lambda — `` `expr` ``

The shortest anonymous function form. Implicit parameters `a`, `b`, `c` (first, second, third positional):

```
`a * 2`                          # equivalent to f -> a * 2
m([1,2,3], `a*2`)                # [2, 4, 6]
fl([1,2,3,4,5], `a>2`)           # [3, 4, 5]
rdc([1,2,3,4], `a+b`, 0)         # 10
srt(words, `len(a)`)             # sort by length
```

Backtick lambdas are parsed as `Lambda` nodes with `implicit=True`. The body between backticks is a single expression. This is the most compact lambda syntax for code golf.

### Parameters

```
df f(x, y, z)                    # positional
df f(x, y=10, z=20)              # with defaults
df f(x, *args)                   # variadic positional
df f(x, **kwargs)                # variadic keyword
df f(x, *args, **kwargs)         # both
df f(x, /, y, *, z)              # positional-only / keyword-only (Python-ish)
```

Defaults are evaluated **per call** (fresh evaluation), not once at definition — unlike Python. So `df f(x=[])` gets a fresh empty list every call.

### Named return values

```
df divmod(a, b) { r quo=a/b, rem=a%b }
result = divmod(7, 3)            # returns ["quo": 2, "rem": 1] — a dict
result["quo"]                    # 2
result["rem"]                    # 1
```

`r name1=expr1, name2=expr2` returns a dict with string keys. The parser detects the `ident =` pattern after `r` and builds a `ListExpr` with key-value pairs (string keys from the names, values from the expressions). This is syntactic sugar for returning `["name1": expr1, "name2": expr2]`.

Named returns are useful for functions that produce multiple related values. The caller accesses results by key:

```
df stats(lst) {
  r mean=sum(lst)/len(lst), count=len(lst)
}
s = stats([1,2,3,4])
p(s["mean"])                     # 2.5
p(s["count"])                    # 4
```

### Typed params

Type annotations are used for multiple dispatch (§13), not type checking:

```
df add(Num a, Num b) = …
df add(Str a, Str b) = …
```

Types can be built-in prototypes (`Num`, `Str`, `Lst`), sum variants (`Some`, `None`), or user prototypes.

### Value-pattern heads

```
df fct 0 = 1
df fct n = n * fct(n - 1)
```

Sugar for multi-dispatch on first arg with `mt`:

```
df fct x = mt x {
  0 -> 1
  n -> n * fct(n - 1)
}
```

Pattern-head dispatch is specific-to-general: exact-value beats type beats wildcard.

### Guards

```
df abs(x) | x < 0 = -x
df abs(x) | x >= 0 = x
```

Or with `where` clauses:
```
df bmi(w, h) = w / (h ^ 2)   where h_m = h / 100
```

`where` is a trailing let-block. Scope is function-body-only. (Haskell-equivalent.)

### Function call

```
f(x, y)                        # positional
f(x, y=2)                      # keyword
f(*list, **dict)               # unpacking
f.ca(args=[...], kwargs={...}) # explicit (function-as-value .ca)
```

### Closures

Full lexical closures. A function captures its defining scope by reference (not by value) — changes to captured variables are visible.

```
df counter() {
  n = 0
  f -> { n += 1; n }           # closure over n
}
c = counter()
c()                            # 1
c()                            # 2
```

### First-class functions

Functions are values. Pass them, store them, compose them. `+` is function composition (§8). `^n` is n-fold composition.

### Methods

A function is a method of its first-argument type by dispatch, but also accessible via dot:

```
l = [1, 2, 3]
l.len()                        # 3 — dispatches to len(Lst)
len(l)                         # same thing
```

`o.m(args)` is sugar for `m(o, *args)` — the receiver is just the first argument. No special method binding.

### Decorators

Decorators can be applied to `df` (function) and `ct` (coroutine) declarations:

```
@dec
df f(x) = x * 2

# equivalent to
df f(x) = x * 2
f = dec(f)
```

Multiple decorators stack bottom-up:
```
@a
@b
df f() { … }                   # f = a(b(original_f))
```

Decorators can be any callable; they receive the function and return a value (usually a new function). Decorators can be passed as params to `df`:

```
@dec(param)
df f() { … }                   # dec(param) called first, result decorates f
```

### Partial application

```
add3 = prt(add, 3)             # add3(x) = add(3, x)
add_last = prt(add, _, 10)     # add_last(x) = add(x, 10)
```

`prt` is in the prelude (§37). `_` is the slot placeholder (same as in `|>`).

### Functional inverse

```
f^-1(y)                        # find x such that f(x) == y
~f                             # same as f^-1
```

**Not yet implemented.** `f^-1` raises `InterpErr` ("inverse functions not yet implemented"). `~f` on a callable is not supported (raises `TypeErr`). The spec envisions algebraic inversion for single-expression functions; this remains deferred.

---

## 12. Pattern matching

### `mt` expression

```
mt value {
  pattern1         -> expr_or_block1
  pattern2 if guard -> expr_or_block2
  ...
  _                -> default_expr
}
```

Patterns tried top-to-bottom; first match wins.

### Pattern forms

- **Literal**: `0`, `"foo"`, `und`, `true`, `false` — match by `===`.
- **Variable**: `x` — match anything, bind to `x`.
- **Wildcard**: `_` — match, don't bind.
- **As-pattern**: `name@pattern` — bind the whole to `name` AND destructure.
- **List**: `[p1, p2]` (exact len), `[p1, ...rest]` (head/tail), `[p1, _, p3]` (skip).
- **Dict**: `[k: p, ...]`, `[k: p, **rest]` — a key-bearing `[…]` pattern matches as a dict-shape.
- **Set**: `st([p1, p2, p3])` — must contain at least these elements.
- **Typed**: `Num(x)`, `Str(s)`, `Lst(l)` — match by type, bind contents.
- **Variant**: `Some(x)`, `None`, `Err(m)` — sum-type variants (§16).
- **Regex**: `r/(\d+)/ as [x]` — groups destructure to list.
- **Or**: `p1 | p2 | p3` — any.
- **Guard**: `pattern if condition` — pattern matches AND guard truthy.
- **Nested**: arbitrarily deep.

### Examples

```
mt x {
  0                          -> "zero"
  1 | 2 | 3                  -> "small"
  n if n < 0                 -> "negative"
  [h, ...t]                  -> "list: " + h
  [name: n, age: a if a>=18] -> "adult " + n
  Some(v)                    -> "got " + v
  None                       -> "nothing"
  _                          -> "other"
}
```

### Bindings scope

Bindings in a pattern are scoped to that arm only.

### Exhaustiveness

Not statically checked. A non-matching `mt` returns `und` (default mode) or raises `MatchErr` (strict mode).

### Function-head patterns

See §11. `df fct 0 = 1; df fct n = n * fct(n-1)` desugars to a multi-dispatched function with an internal `mt`.

### `mt` as statement

`mt` can be used as a statement (value discarded), or as an expression (returns the matched arm's value).

---

## 13. Multiple dispatch

### Model

A function name can have multiple definitions (methods), each with its own argument-type specification. At call time, Snafu picks the **most specific** applicable method.

### Declaring methods

```
df add(Num a, Num b)       = a + b                    # internal-add; user-overridable
df add(Str a, Str b)       = cat(a, b)
df add(Matrix a, Matrix b) = matmul(a, b)
df add(Matrix a, Num b)    = scalar_mul(a, b)
df add(Num a, Matrix b)    = scalar_mul(b, a)
```

### Specificity

For each argument position:
- Value-pattern (`0`, `"foo"`): most specific.
- Derived type: more specific than ancestor type.
- Base type: less specific than derived.
- No type (bare `x`): least specific — wildcard.

Total specificity across all args: tuple-wise comparison. Method A is more specific than B iff A is `>=` B in every position and `>` in at least one.

Ambiguous methods (neither more specific) → `DispatchAmbig` exception at call site.

### Adding methods externally

A method can be added for any existing type from any module. The dispatch table is global per function name.

```
# in module foo.snf
df add(MyType a, Num b) = … 
```

This extends `add` — calls from anywhere now see this method.

### Dispatch cost

Runtime type check on all args, every call. Interpreter caches dispatch decisions per call site (call-site caching).

### Interaction with sum types

```
sm Tree = Leaf | Node(l, v, r)

df sum(Leaf)              = 0
df sum(Node(l, v, r))     = v + sum(l) + sum(r)
```

Each variant is a dispatchable type.

---

## 14. Object model

### Everything is an object

Every value in Snafu has:
- A **prototype** — the object it was derived from (or a built-in root).
- **Attributes** — a dict of name→value.
- **Methods** — attributes that are callable (resolved via dispatch).

### Prototypes, not classes

There is no `class` keyword. Create an object and derive from it.

```
Point = new()                        # new prototype
Point.x = 0
Point.y = 0
Point.dist = f (p) -> sqrt((s.x-p.x)^2 + (s.y-p.y)^2)

p1 = new(Point)                      # derive: p1's prototype is Point
p1.x = 3
p1.y = 4
p1.dist(new(Point))                  # 5.0
```

### `new`

```
new()                                # raw empty object, prototype is Obj
new(parent)                          # single-inheritance
new(parent1, parent2)                # multiple inheritance
new(parent, init_kwargs, decorators) # with init params and decorators
```

**Signature**:
```
new(*parents, init: dict, dec: list) 
```

Positional args are prototypes. `init` passes kwargs to the combined `__init__`. `dec` is a list of decorators to wrap the resulting object.

### Multiple inheritance

Per the notes: `new(a, b, c)` inherits from all three. Attribute lookup order is C3 linearization (same as Python MRO).

### `obj.new()` method

Every object inherits `new` from `Obj`:

```
p1.new()                             # creates a new object with p1 as prototype
p1.new(p2)                           # p1 AND p2 as parents — add p2 to parents
```

### Attribute lookup

Walk prototype chain until found. First hit wins. If not found, return `und`.

```
p = new()
p.x                                  # und (nothing set, no inheritance)
```

### Attribute set

```
o.x = 5                              # sets on o itself; doesn't affect prototype
```

Setting never mutates the prototype (unlike some prototype languages). To change a prototype's attribute, set on the prototype object directly.

### Attribute delete

```
del o.x                              # remove x from o's own attrs
                                     # if x exists on prototype, now visible from o
```

### Object delete (`del o`)

Per the decision (Python-ish): `del o` **unbinds the name**. The object itself survives if other references exist. If no references remain, GC collects it.

Effects on children:
- If `o` is a prototype of `c`, `c` still has `o` in its MRO (the prototype reference is held by `c`).
- If all references to `o` are gone (including child references), the object is freed. Children then see a dangling prototype link — looked-up attrs return `und`.

In practice: `del o` only unbinds the name. The object stays alive as long as its children reference it.

### Attribute hooks

```
o.__get__(name)                      # override read
o.__set__(name, value)               # override write
o.__del__(name)                      # override delete
```

Setting any of these defines a hook. Hooks are called via regular attr access. To bypass (raw access): `o.!attr_name` — the `!` prefix skips hooks.

### Identity

Every object has `id(o)` — a unique integer. `is` compares by id. Immutable values (numbers, strings, true/false, und) are interned — equal values have equal ids.

Reverse: `obj(id)` — get the object from id (only works if still referenced).

### Deep copy

```
cp(o)                                # full structural copy
cp(o, depth: 2)                      # copy 2 levels deep
```

Even system resources (sockets, files) are copied by `cp` — the new handle points to the same underlying OS resource.

---

## 15. Protocols

### Protocol declaration

```
pr Eq {
  eq(a, b)                           # signature only
}

pr Ord ex Eq {
  lt(a, b)
  le(a, b) = lt(a, b) || eq(a, b)    # default impl
  gt(a, b) = !le(a, b)
  ge(a, b) = !lt(a, b)
}
```

`ex` declares protocol-inheritance (implementer must satisfy the parent protocol). Default impls are provided for convenience; implementers can override.

### Implementation

```
im Ord for MyType {
  eq(a, b) = a.key == b.key
  lt(a, b) = a.key <  b.key
  # le, gt, ge inherited from defaults
}
```

Implementations can be added for any type from any module (open polymorphism).

### Derivation — `dv`

For common protocols, auto-generate implementations:

```
sm Tree = Leaf | Node(l, v, r) dv [Eq, Show, Ord, Hs]
```

Derivable protocols and their generated impls:

| Protocol | Generated behaviour                                       |
| -------- | --------------------------------------------------------- |
| `Eq`     | Same variant AND all fields recursively `==`.             |
| `Show`   | `"VariantName(field1_show, field2_show, ...)"`.           |
| `Ord`    | Variants by declaration order, then field-by-field.       |
| `Hs`     | Combine variant-tag hash + field hashes.                  |
| `Cp`     | Variant-preserving deep copy.                             |
| `Js`     | JSON encode/decode with variant tag.                      |
| `Rd`     | Parse from `Show` output (inverse of `Show`).             |

User-defined protocols can also be derivable by implementing a `derivable-for` hook.

### Introspection

```
implements(x, Ord)                   # bool
protocols(x)                         # list of protocols x satisfies
methods(Ord)                         # signatures required by Ord
instances(Ord)                       # all types implementing Ord
```

### Structural fallback

With `strict_protocols=false` (default), a type that structurally has the right methods but no explicit `im` still counts as implementing the protocol. With `strict_protocols=true`, only explicit `im` counts.

### Standard protocols (selection)

- `Eq`, `Ord` — §32.
- `Hs` — hashable.
- `Show`, `Rd`, `Fmt` — display / parse / format.
- `Iter`, `Itor`, `Revible`, `Rstable`, `Indexable`, `NdItor` — iteration (§21).
- `Cp` — deep copy.
- `Js` — JSON.
- `Ctx` — context manager (§8.wi).
- `Ft` — functor (map-like).
- `Mn` — monad (bind/return — advanced).

---

## 16. Sum types

### Declaration

```
sm Maybe   = Some(v) | None
sm Result  = Ok(v)   | Err(e)
sm Tree    = Leaf    | Node(l, v, r)
sm AST     = Num(n)  | Sym(s) | Call(fn, args) | If(c, t, e)
```

Each variant is both:
- A **constructor** (callable): `Some(5)` builds the value.
- A **pattern** (for `mt`): `Some(x)` destructures.

Variants inherit from their sum type (`Some.p == Maybe`).

### With derivation

```
sm Shape = Circle(r) | Rect(w, h) | Tri(a, b, c) dv [Eq, Show, Ord]
```

### Recursive sum types

Direct self-reference is allowed:
```
sm List = Nil | Cons(h, List)
l = Cons(1, Cons(2, Cons(3, Nil)))
```

### Usage

```
m = Some(5)

mt m {
  Some(v) -> p("got " + v)
  None    -> p("nothing")
}
```

### Multiple dispatch on variants

```
df depth(Leaf _)           = 0
df depth(Node(l, _, r))    = 1 + max(depth(l), depth(r))
```

### Variant fields

Variants are tuples of their fields. Access by pattern, or by position:

```
t = Node(Leaf, 5, Leaf)
t.v                                # 5 — if named fields (see below)
t[0], t[1], t[2]                  # positional
```

Named-field syntax:
```
sm Point = Pt(x, y)
p = Pt(3, 4)
p.x                                # 3
```

Field names are the parameter names in the declaration.

### Open vs closed

Sum types are **closed** — you cannot add new variants after declaration. For open sets of types, use prototypes + protocols.

---

## 17. Control flow

### Conditional

```
if cond { then_block }
if cond { then_block } el { else_block }
if cond { then_block } eli other_cond { block2 } el { block3 }

# expression form
x = if cond { 1 } el { 2 }
x = cond ? 1 : 2                  # ternary (§8)
```

### Loops

```
for x in iter { body }            # for-in
for x in iter if cond { body }    # filter: body only when cond true
for x in iter wh cond { body }    # while-loop termination: stop when cond false
for x in iter un cond { body }    # stop when cond true
for y { body }                    # for _ in y — iteration without binding name
for [y: expr] { body }            # brief list-comp form (§6)

wh cond { body }                  # while loop
un cond { body }                  # until loop (= while !cond)
lp { body }                       # infinite loop
lp n { body }                     # n-repeat loop
```

### Loop modifiers

- `bf { code }` — runs before each iteration
- `bt { code }` — runs between iterations (not after last)
- `af { code }` — runs after each iteration
- `el { code }` — runs once, after the loop exits normally (not on break)
- `fi { code }` — runs once, regardless of how the loop exits

```
for x in [1,2,3] {
  p(x)
} bt {
  p("---")
} el {
  p("finished naturally")
} fi {
  p("cleanup")
}
```

### Break and continue

```
br                                 # break innermost
br 2                               # break out of 2 levels
cn                                 # continue innermost
cn 2                               # continue, jumping to start of loop 2 levels out
cn +3                              # advance 3 iterations
cn -1                              # go back one iteration (Revible iterators only)
```

### For/if/wh/un chained

```
for x in y if z un q { body }      # combine; reads left-to-right
```

### Loop with index

```
for (i, x) in en(y) { body }       # en = enumerate prelude fn
```

---

## 18. Goto, comefrom, resume, labels, sub

### Labels

```
lbl name                           # declare a label at this point
```

Labels mark a position in a block's statement list. They are scoped to their enclosing block.

### Goto

```
goto label_name                    # unconditional jump to label
```

`goto` raises a `_GotoSignal` that propagates up through enclosing blocks until a matching `lbl` is found. Both forward and backward jumps within the same block work. If the signal escapes all blocks, it becomes an error.

**Implementation note:** `goto` works within a single block's statement list. It does not jump across function boundaries. Variables not yet assigned at the target position are `und`.

### Comefrom

```
cf label_name                      # install a comefrom hook
```

`cf` registers a hook for a label name within the same block. When execution reaches a `lbl` statement whose name has an active `cf` hook, execution jumps to the statement after the `cf` declaration instead of continuing past the label.

**Scope:** `cf` hooks are block-scoped -- they only trigger within the block where they are declared.

**Current limitation:** Unlike the spec's original design, `cf` does not support policy/weight parameters, multiple `cf`s per label, or `uncomefrom`. A single `cf` per label per block is supported.

### Resume — `rm`

```
rm                                 # return to just after last control-flow change
```

`rm` raises a `_ResumeSignal` that returns execution to the statement after the most recent `goto` jump. The interpreter tracks the last jump site (block + statement index) in `_last_jump`. If no jump has occurred, `rm` simply continues to the next statement.

### `sub(label1, label2)` — special form

Execute the code between two labels and return:

```
lbl start
  x = 1
  y = 2
lbl end

result = sub(start, end)            # executes x = 1; y = 2; returns last value
```

`sub` is a special form recognized by name at call sites (it is not a reserved keyword). It finds the enclosing block's statement list, locates the two labels, and evaluates all statements between them (exclusive of the labels themselves). Labels must exist in the same block; otherwise `InterpErr` is raised.

---

## 19. Exceptions

### Raising

```
rs ValErr("bad input: " + x)
```

### Catching

```
ty {
  risky()
} ex ValErr e {
  p("bad value: " + e.msg)
} ex IOErr e {
  p("io: " + e.msg)
} ex e {
  p("other: " + e)
} fi {
  cleanup()
}
```

### Exception types

Declared as prototypes:
```
VE = new(Exc); VE.nm = "ValErr"
```

Terse form:
```
ex VE(msg)                         # declares VE inheriting from Exc with a msg field
ex NetErr ex IOE                   # NetErr inherits from IOE
```

Or as sum types:
```
sm ParseErr = EOF | UnexpectedTok(tok, pos) | SyntaxErr(msg, pos)
```

### Chaining

```
ty { risky() } ex e {
  rs WrappedErr("failed") fr e
}
```

`fr e` sets `new.ca = e`. Implicit chaining when raising inside `ex`: auto-populates `.ca`. Break chain with `fr und`.

### Re-raise

```
ex e { log(e); rs }                # bare rs re-raises current
```

Bare `rs` (with no argument) re-raises the currently-handled exception from the internal exception stack (`exc_stack`). It only works inside an `ex` block; using bare `rs` outside an `ex` block raises `SnafuError("bare rs outside except")`.

### Backtrace

`e.tb` — list of frames. Frame attrs: `fl`, `ln`, `fn`, `sc`, `ast`, `id`.

### Interaction with `und`

Default (loose): `und` propagates silently. Strict mode `sd`: operations on `und` raise `UndErr`.

### Standard exception hierarchy

```
Exc                                # root
  ArgErr                           # bad argument
  TypeErr                          # wrong type
  ValErr                           # bad value
  NameErr                          # undefined name
  AttrErr                          # missing attribute
  IxErr                            # bad index
  KeyErr                           # missing key
  DivErr                           # division by zero (strict mode)
  UndErr                           # operation on und (strict mode)
  MatchErr                         # non-matching mt (strict mode)
  IOErr                            # IO failure
    FileErr, NetErr, ...
  ParseErr                         # parse failure
  DispatchAmbig                    # multiple dispatch ambiguity
  RecurErr                         # runtime recursion limit (should be unreachable if TCO works)
  Cancelled                        # green-thread cancellation
  TimeoutErr                       # await timeout
  ProtocolErr                      # protocol not implemented
  BindErr                          # binding-related (e.g. write to tracked var)
  ContractErr                      # contract (req/ens) violation
  SubErr                           # sub() boundary violation
  InterpErr                        # interpreter-level issue (level n doesn't exist, etc.)
```

---

## 20. Algebraic effects

### Effect declaration — `ef`

```
ef Yield(v)                        # declares an effect type with one field
ef Ask(name)                       # another effect type
ef Fail(msg)                       # effect with a message field
ef Done                            # no-field effect (value, not constructor)
```

`ef` declares an effect type. Internally, effects are implemented as lightweight sum types with a single variant. An effect with fields creates a constructor (callable); an effect with no fields creates a value (not callable). The declared name is bound in the current scope.

### Performing — `pf`

```
pf Yield(1)                        # raise an effect signal
v = pf Ask("cfg")                  # effect can return a value via handler
```

`pf expr` evaluates `expr` and raises an `_EffectSignal` that propagates up the Python call stack. The nearest matching `hd` handler catches it.

### Handling — `hd`

```
hd {
  v = pf Ask("name")
  p("got: " + v)
} with {
  Ask(n) k -> k("Alice")           # match effect, resume with value
  r        -> "done: " + r         # return handler (normal completion)
}
```

**Syntax:** `hd { body } with { cases }`. The body is executed; if it completes normally, the return handler (`r -> expr`) processes the result. If an `_EffectSignal` is raised, cases are matched top-to-bottom using pattern matching.

**Cases:** Each case has the form `Pattern cont_name -> body`. The continuation `cont_name` (typically `k`) is bound to a one-shot function. Calling `k(value)` returns `value` as the result of the `pf` expression in the body. Not calling `k` discards the continuation (like an exception).

**Return handler:** A case with a bare variable pattern and no continuation name (e.g., `r -> expr`) is treated as the return handler. It fires when the body completes normally; the variable is bound to the body's return value.

### Limitations

**Simple mode (no continuation parameter):** When no handler case names a continuation, the implementation uses Python exceptions (`_EffectSignal`). `k` is not available; unmatched effects propagate.

**Resumable mode (continuation parameter present):** When any handler case names a continuation variable (e.g., `Ask(q) k -> k("value")`), the body runs in a separate thread. `pf` blocks and sends effects through a queue; calling `k(v)` resumes the body with `v` as the return value of the `pf` expression. See §37r for details.

Limitations:
- Multi-shot continuations (calling `k` more than once) are not supported.
- Effects do not cross thread boundaries (each `gt` thread has its own exception stack).

### Handler lookup

`pf` raises a Python exception that propagates up through `try`/`except` blocks until a `hd ... with { }` catches it. Pattern matching on the effect value determines which case fires. Unmatched effects propagate further.

---

## 21. Iterators

### Protocols

```
pr Iter   { it(self) }
pr Itor ex Iter {
  nx(self)                          # next or pf StopItor
}
pr Revible ex Itor {
  pv(self)                          # previous
}
pr Rstable ex Itor {
  rs(self)                          # reset to start
}
pr Indexable ex Itor {
  at(self, n)                       # jump to nth
}
pr NdItor ex Itor {
  dim(self)                         # number of axes
  at_nd(self, indices)              # multi-dim at
}
```

### End marker

End-of-iteration is `pf StopItor`. `for` installs a handler for this effect.

### `for` desugaring

```
for x in coll { body(x) }
```
desugars to:
```
hd {
  it = coll.it()
  lp { body(it.nx()) }
} with {
  StopItor _ -> und
}
```

### Generators — `ct`

```
ct squares(n) {
  for i in 0..n {
    y i * i
  }
}

for sq in squares(5) { p(sq) }
```

`ct` declares a coroutine/generator. The syntax is `ct name(params) { body }`. Decorators are supported via `@dec ct name(...)`.

**Implementation:** Coroutines are implemented via Python threading. Calling a `ct`-declared function returns a `SnafuGenerator` object. The generator body runs in a daemon thread, communicating yields through a queue. Each `y expr` puts the value on the queue; iteration via `for x in gen()` or manual `next()` consumes from it.

The returned generator implements Python's iterator protocol (`__iter__`/`__next__`), so it works with `for x in gen() { }` naturally.

### Sending values into generators — `.sd(val)`

Generators support bidirectional communication. The `.sd(val)` method sends a value into the generator, which becomes the return value of the `y` expression inside the coroutine body:

```
ct echo() {
  lp {
    received = y "ready"             # y is an expression; its value is the sent value
    p("got: " + received)
  }
}

g = echo()
p(g.sd("hello"))                    # prints "got: hello", returns "ready"
```

**Implementation:** When the generator yields, it puts the value on the yield queue and then blocks on a send queue. `.sd(val)` puts `val` on the send queue and reads the next yield. Regular iteration via `for` / `next()` sends `und` implicitly.

The `.nx()` method on a generator object calls `__next__()` for manual iteration.

### yield from — `yf`

```
ct outer() {
  yf inner()                      # delegate to inner; forward all y's
  y "after inner"
}
```

`yf sub` = `for x in sub { y x }` -- delegates to a sub-generator.

### List comprehensions with guards

List comprehensions use inline `for`/`in`/`if` syntax inside `[…]`:

```
[x * 2 for x in [1,2,3,4,5]]           # [2, 4, 6, 8, 10]
[x for x in 1..=10 if x % 2 == 0]      # [2, 4, 6, 8, 10]
[x + y for x in [1,2] for y in [10,20]] # [11, 21, 12, 22] — nested
[[i,j] for i in 0..3 for j in 0..3 if i <> j]  # pairs where i != j
```

**Syntax:** `[expr for pattern in iter (if guard)? (for pattern in iter (if guard)?)* ]`

Multiple `for` clauses nest (outer first). Each `for` clause can have an optional `if guard` that filters. Pattern matching is supported in the iteration variable position.

### Lazy ranges and lazy comprehensions

Ranges (`a..b`) and list comprehensions `[expr for x in y]` are lazy iterators. They become materialized lists only when asked:

```
lst(1..100)                       # materialize
[1..100]                          # lazy — not materialized
```

Generator comprehensions `[x: expr]` (brief form) are lazy-with-caching: results are stored as yielded so re-iteration / indexing doesn't recompute.

---

## 22. Concurrency

### Green threads — `gt`

```
gt { body() }                     # spawn; returns a Future handle
h = gt { compute() }             # handle is a Future object
r = aw h                          # wait for result
```

`gt { body }` spawns the body in a Python daemon thread. The body executes in a child scope of the current scope. Returns a `Future` object (`SnafuObj` with `type_name="Future"`).

**Future attributes:**
- `_result` — the return value (set when body completes)
- `_error` — exception if body raised one
- `_thread` — the underlying Python `Thread`

### Await — `aw`

```
r = aw handle                     # join the thread, return result or re-raise error
```

`aw expr` evaluates `expr`, which must be a `Future`. It calls `.join()` on the thread, then checks for errors (re-raises if any) and returns the result.

### Channels — `ch(n)`

```
c = ch()                          # unbuffered channel (queue size 0)
c = ch(10)                        # buffered channel of capacity 10
c.send(val)                       # send a value (blocks if full)
v = c.recv()                      # receive a value (blocks if empty)
c.close()                         # mark channel closed
```

Channels are `SnafuObj` wrappers around Python `queue.Queue`. Sending to a closed channel raises `ValErr`. Receiving from a closed empty channel raises `ValErr`.

### Select — `sl(c1, c2, ...)`

```
result = sl(c1, c2, c3)           # wait for first ready channel
# result is [index, value] — index of the channel that had data
```

`sl` is a prelude function (not a statement form). It polls the given channels in a loop, returning `[index, value]` for the first channel with available data. An optional `timeout_ms` keyword argument causes it to return `und` after the timeout.

### Execution sets — `xs`

```
xs {
  a = compute_a()
  b = compute_b()
  c = compute_c()
}
```

`xs { stmts }` runs each statement in its own Python thread concurrently. All threads share the same scope. Threads are joined in order; if any raised an exception, it is re-raised after all threads complete. The value of the `xs` block is the value of the last statement.

**Note:** Unlike the original design, the current implementation does not analyze data dependencies — all statements run concurrently regardless. Circular or ordering dependencies must be managed by the programmer (e.g., using channels).

---

## 23. Reactive / on / off

### `on` — reactive triggers

```
on x.ch { body }                  # body runs whenever x is assigned a new value
```

`on var_name.ch { body }` installs a trigger on the named variable. Whenever the variable is assigned in the global scope, the trigger body executes. The `.ch` suffix (for "change") is required syntax.

**Implementation:** The first `on` statement installs an `on_assign_hook` on the global scope. This hook fires after every `scope.assign()` call in the global scope, checking if the assigned name has registered triggers. Trigger bodies execute in the scope they were defined in. Exceptions in trigger bodies are silently caught (they do not propagate to the assignment site).

Multiple triggers can be registered for the same variable. They fire in registration order.

### `of` — remove triggers

```
of x.ch                           # remove all triggers on variable x
```

`of var_name.ch` removes all triggers registered for the given variable name. The `.ch` suffix is required.

### `on expr { body }` — condition-based triggers

```
x = 0
on x > 5 { p("x exceeded 5!") }
x = 3                            # nothing happens
x = 6                            # prints "x exceeded 5!"
x = 10                           # prints "x exceeded 5!" again
```

`on expr { body }` installs a condition trigger. The condition expression is re-evaluated after every assignment (in any scope that has the global `on_assign_hook`). Whenever the condition is truthy, the body executes.

**Distinction from `on x.ch`:** The `on x.ch { }` form fires whenever `x` is assigned (regardless of value). The `on expr { }` form fires whenever `expr` evaluates to truthy after any assignment, which can involve any variables or complex expressions.

**Implementation:** The parser distinguishes the two forms by looking ahead: if the token after `on` is `ident.ch`, it produces an `On` node. Otherwise, it parses a general expression and produces a `CondTrigger` node. Condition triggers are stored in `_cond_triggers` (a list of `(cond_node, scope, body_node)` tuples). The global `on_assign_hook` checks all condition triggers after every assignment.

### `of all` — remove condition triggers

```
of all                           # remove all condition-based triggers
```

`of all` clears the `_cond_triggers` list. It does not affect `on x.ch` triggers (those are removed with `of x.ch`).

**Note:** The originally specified `on a.del`, `on a.exe`, `on a.rd`, `on a.cpy`, `on a.ref` forms are not implemented.

---

## 24. Execution sets

See §22 for the `xs { }` statement. Summary:

```
xs {
  a = compute_a()
  b = compute_b()
  c = compute_c()
}
```

Each statement runs in its own Python thread. All threads share the same scope. Threads are joined in order; any exception is re-raised after all complete.

**Note:** The originally specified dataflow scheduling (dependency analysis, deferred variable reads, `CycleErr`) is not implemented. All statements run concurrently without ordering guarantees.

---

## 25. Modules

### Module == file

Each `.snf` file is a module. Names defined at the top level are module-level bindings.

### Exports

```
xp [add, sub, mul]                # only these are visible externally
```

Without `xp`, all top-level names are exported (all names not starting with `__`).

**Implementation:** `xp` stores its names list as `__exports__` in the module's scope. When another module imports via `us`, the importer checks for `__exports__` and only exposes those names.

### Import

```
us math                           # imports math.snf; access as math.sin(0)
us *math                          # dump all names from math.snf into current scope
```

**Implementation details:**
- `us module` loads `module.snf` from the current working directory, executes it in a fresh `Interpreter`, caches the resulting scope (modules are loaded once), and creates a namespace object (a `SnafuObj` with the module's exported names as attributes).
- `us *module` copies all exported names directly into the caller's scope (no namespace prefix).
- Module results are cached in `module_cache` -- subsequent `us` of the same module returns the cached scope.
- The child interpreter inherits the parent's strict-mode setting.

**Not yet implemented:** `us module as alias`, `us module { block }`, multiple imports in one `us` statement, Python alias table.

### Python alias table (not yet implemented)

The spec describes built-in two-char aliases mapping to Python modules. These are not yet implemented. For Python interop, use `py.import("module_name")` (see §37).

Originally specified aliases:

```
n8    -> numpy            nq    -> numpy          pd    -> pandas
pl    -> matplotlib.pyplot  sp  -> scipy
tc    -> torch            tf    -> tensorflow     sk    -> sklearn
os    -> os               sy    -> sys            rq    -> requests
js    -> json             re    -> re             dt    -> datetime
cs    -> csv              sq    -> sqlite3        sa    -> sqlalchemy
fs    -> pathlib          th    -> threading      ap    -> asyncio
cp    -> subprocess       it    -> itertools      ft    -> functools
ic    -> collections      op    -> operator       ma    -> math
rn    -> random           pk    -> pickle         hs    -> hashlib
rg    -> regex            xm    -> xml.etree.ElementTree
bs    -> bs4              cg    -> cryptography
```

User-extensible at `~/.snafu/aliases.snf`:
```
pq = some.obscure.package
cv = cv2
```

### On-demand loading

First use of an unqualified name triggers the import chain (§10).

### Resolution order

1. Local scope
2. Enclosing lexical scopes
3. Module-level scope
4. Active `us` blocks (last wins on collision)
5. Snafu built-ins (prelude — §37)
6. Python alias table (triggers import if name not yet loaded)
7. `und` (or `NameErr` in strict mode)

### Python value interop

- Primitives, lists, dicts, tuples: round-trip by conversion.
- Callables: wrap, auto-convert args/return.
- Classes: instantiate, subclass, isinstance.
- Generators: map to Snafu iterators.
- NumPy arrays / pandas dataframes: opaque handles with method access; `.fl()` to get a Snafu collection.
- Async: bridge via asyncio.

Limits:
- Symbolic numbers must `.fl()` before entering NumPy.
- Algebraic effects don't cross into Python and back.
- Python metaclasses aren't respected by Snafu dispatch.

### Import cycles

Detected at resolution time. Default: tolerate (partially-initialized module). Opt-in strict with program-top-level: `opt strict_cycles true`.

---

## 26. Regex

### Literals

```
r/\d+\s+(\w+)/i                   # parse-time compiled
r"pattern with / in it"           # string-delim alternative
```

Flags: `i` case-insensitive; `m` multiline; `s` dotall; `x` extended; `g` global; `u` unicode.

### Match object

```
m = r/(\d+)-(\d+)/.ma("42-7")
m.gr(0)                           # "42-7" (whole)
m.gr(1)                           # "42"
m.gr(2)                           # "7"
m.gr("year")                      # named group
m.sp, m.ep                        # start, end
m.pr, m.po                        # before, after
m.al                              # list of all groups
```

### Operations

```
re.ma(s)                          # first match
re.al(s)                          # all matches (list)
re.ct(s)                          # count
re.fi(s)                          # find next from current position
re.sub(s, replacement)            # substitute
re.spl(s)                         # split on matches
```

### Perl operators

```
"hello" =~ s/e/a/                 # substitute → "hallo"
"hello" =~ m/l+/                  # match → Match object
"hello" =~ tr/a-z/A-Z/            # transliterate → "HELLO"
```

Standalone (no subject yet) — these are value-returning transformers:
```
upr = s/(.)/\1.upr()/g
upr("hello")                      # "HELLO"
```

### Substitution with a function

```
s/(\d+)/(m -> int(m.gr(1)) * 2)/g
```

Replacement may be a string (with `\1`-style backrefs) or a function taking the Match.

### Patterns in `mt`

```
mt ds {
  r/(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})/ -> Date(y, m, d)
  _ -> und
}
```

Named groups become bindings in the arm.

### SNOBOL combinators

```
rx.any("abc")                     # one-or-more from set
rx.br("xyz")                      # BREAK: until a char in set
rx.len(3)                         # exactly 3 chars
rx.arb                            # arbitrary (.*)
rx.bal("()")                      # balanced parens
rx.span("0-9")                    # SPAN: one-or-more from set
rx.a + rx.b                       # concat via +
```

### Anything-but extension

```
(^blah)*                          # zero-or-more repetitions of anything not starting with "blah"
```

Desugars to `(?:(?!blah).)*`.

### Source regex substitution

```
s/pattern/repl/g on src           # substitute on the program's own source
```

See §35.

---

## 27. Lenses

### Construction

```
l = lens("name")                  # lens focusing on string attribute "name"
l = lens(0)                       # lens focusing on integer index 0
```

`lens(key)` is a prelude function that creates a `SnafuLens` object. The key must be a `Str` (for attribute/dict access) or `Int` (for list index access).

For string keys, the getter accesses attributes on `SnafuObj` or dict/list keys. For integer keys, the getter uses index access.

### Operations

```
l.gt(obj)                         # get: read the focused value from obj
l.st(obj, val)                    # set: write val at the focused position, return obj
l.md(obj, fn)                     # modify: apply fn to the focused value, return obj
```

`.st()` and `.md()` mutate the object in place and return it (for `SnafuObj`, `dict`, and `list` targets).

### Composition

```
c = lens("user") + lens("name")
c.gt(rec)                         # rec.user.name (nested access)
c.st(rec, "Bob")                  # set rec.user.name = "Bob"
```

`+` composes two lenses. The left lens focuses into the outer structure, and the right lens focuses within the result. Composition works because `_add` detects two `SnafuLens` operands and builds a composite getter/setter.

---

## 28. Pipeline and composition (recap)

### Pipeline

`|>`: first-arg insert. `|>>`: last-arg insert. `_`: explicit slot (§8). Both are implemented and working.

**Iter-first convention:** Higher-order functions in the prelude use iter-first argument order: `m(iter, f)`, `fl(iter, pred)`, `rdc(iter, f, init)`. This makes pipeline chains read naturally: `[1,2,3] |> m(f -> a * 2)` maps the double function over the list.

### Function composition

`f + g`: left-to-right — `(f+g)(x) = g(f(x))`.

### Function exponentiation

`f^n`: n-fold composition (non-negative `n` only). `f^0`: identity (returns first argument). `f^-1`: inverse -- specified but not yet implemented (raises `InterpErr`).

```
df inc(x) = x + 1
inc^3(0)                         # 3 — inc(inc(inc(0)))
inc^0(42)                        # 42 — identity
```

Operators on function values extend to function exponentiation:
- `f + g`: composition
- `f - g`: remove g from f's chain (no-op if g not present)
- `f * n`: equivalent to `f ^ n` for integer n
- `f / g`: `f + g^-1` (apply f, then inverse of g) -- requires inverse support

### Auto-await in pipelines

```
url |> fetch |> parse_json |> handle
```
If `fetch` returns a future, `parse_json` implicitly awaits. Non-future values pass through unchanged.

---

## 29. Transducers

### Constructors

All transducer constructors are prelude functions that return `SnafuTransducer` objects:

```
xm(f)                             # map: transform each element with f
xfl(pred)                         # filter: keep elements where pred is truthy
xtk(n)                            # take: keep only the first n elements
xdr(n)                            # drop: skip the first n elements
xsc(init, f)                      # scan: running accumulator (like fold but emit each step)
```

### Composition

Transducers compose with `+` (the `_add` function detects two `SnafuTransducer` operands and chains their transform functions):

```
pipe = xm(f -> a * 2) + xfl(f -> a > 5) + xtk(3)
```

Composition is right-to-left internally (the left transducer wraps the right transducer's reducer), but reads left-to-right in terms of data flow.

### Application

```
pipe.al(data)                     # apply transducer pipeline to data, returns a list
```

The `.al(data)` method materializes the transducer pipeline over the given iterable, returning a list. Internally, it builds a reducer chain and folds the data through it. Early termination (from `xtk`) uses a `_Reduced` sentinel to break the fold.

### Example

```
double_pos = xm(f -> a * 2) + xfl(f -> a > 0)
result = double_pos.al([1, -2, 3, -4, 5])   # [2, 6, 10]
```

---

## 30. Macros

### Macro declaration

```
mc name(params) { body }
```

`mc` declares a macro. The macro's parameters receive **unevaluated AST nodes** (not runtime values). The body executes at call time (not parse time), and if it returns an AST node, that node is evaluated in the caller's scope.

```
mc unless(cond, body) {
  ast_new("If", cond=ast_new("UnaryOp", op="!", operand=cond), then=body)
}
```

### Invocation

When a macro name is called, the interpreter detects the `SnafuMacro` and passes the raw AST argument nodes (without evaluating them) to the macro's function. The return value is then:
- If it's an AST `Node`: evaluated in the current scope.
- Otherwise: returned as-is.

### AST helpers

These special forms support macro authoring:

- `ast_of(expr)` — returns the raw AST node for `expr` without evaluating it.
- `eval_ast(node)` — evaluates an AST node in the current scope.
- `ast_new(type_name, **fields)` — creates a new AST node of the given type. Type names are the Python dataclass names (`"NumLit"`, `"Ident"`, `"BinOp"`, `"If"`, `"Call"`, etc.). Fields are passed as keyword arguments.
- `ast_src(node)` — converts an AST node back to a source-like string representation.

### Limitations

- Macros run at **call time**, not parse time. They cannot introduce new syntax forms — only transform existing AST nodes.
- No automatic hygiene (gensym). Macro-introduced names are ordinary identifiers.
- `@` as a preprocessor prefix is used for decorators only, not parse-time macros.

---

## 31. Eval

### `ev` function

```
ev(s)                             # evaluates in caller's scope (special form)
```

**Implementation:** `ev("code")` is a special form recognized at the call site. When the interpreter sees a call to `ev` with a string argument, it parses and evaluates the string in the **current scope** (the scope at the call site). This gives `ev` access to local variables. The `sc:` and `lv:` keyword arguments from the spec are not yet implemented.

### Return value

Value of the last expression in `s`.

### Parse errors

`ParseErr` with file/line info. The string is parsed fresh each call.

### String `.ca()`

Alternative form:
```
"expr".ca()                       # evaluates in global scope (NOT caller scope)
```

**Key difference:** `ev("code")` evaluates in the caller's scope (special form), while `"code".ca()` evaluates in the global scope. This is because `.ca()` is a regular method on strings and does not have access to the caller's locals.

### Interpreter level push (not yet implemented)

`lv: +N` is specified but not yet implemented in v1.0. See §40.

### Sandboxing

No default sandbox. Pass a restricted scope for basic isolation:
```
safe_scope = {add: add, mul: mul}
ev(user_code, sc: safe_scope)
```

Writes go to the passed scope — caller's is untouched. Not cryptographically safe.

---

## 32. Equality, identity, hashing

### Three operators

- `is` — same object. Never overridable. Interned primitives: same value → same id.
- `==` — semantic equality. Overridable via `Eq`.
- `===` — structural equality. Not overridable. Implemented via `_structural_eq()` which compares by Snafu type name (`type_name()` comparison, not Python `type()`), then recursively checks contents for lists, dicts, and variant fields.

### Not-equals

- `<>` — `!(a == b)`
- `!==` — `!(a === b)`

### NaN / und

- `nan == nan` → `false` (IEEE)
- `nan === nan` → `true`
- `nan is nan` → typically `true` (interned)
- `und == und` → `und` (propagation)
- `und === und` → `true`
- `und is und` → `true` (singleton)

### Hashing

```
hs(x)                             # hash
```

Contract: `a == b` ⇒ `hs(a) == hs(b)`. Dict keys and set elements require `Hs`.

### Custom equality

```
im Eq for Person {
  eq(a, b) = a.id == b.id
}
im Hs for Person {
  hs(p) = hs(p.id)
}
```

Override one, override the other — collections will lie if you don't.

### Number tower equality

`1 == 1.0 == 1+0i == 1+0i+0j+0k` — all true via tower promotion.

`1 === 1.0` — false (different types).

Matrices, tensors: element-wise within type, not auto-equal to scalars.

---

## 33. Tail calls

### Explicit TCO via `tail()`

Tail-call optimization is available via the `tail(fn, args...)` prelude function. `tail()` returns a `_TailCall` sentinel that the trampoline in `_call_value()` resolves iteratively:

```
df factorial(n, acc=1) {
  if n <= 1 { r acc }
  r tail(factorial, n - 1, n * acc)
}
```

This avoids Python stack growth for self-recursive and mutually-recursive functions.

**Implicit TCO** (automatic detection of tail position) is not implemented. The programmer must explicitly use `tail()` to opt in.

### Rule (spec)

### Tail positions

- Last expression in a function body.
- Value of the last statement in a block that is itself the tail of some context.
- Body expression of matched arm in `mt` / handler case.
- Branch of `if` / ternary in tail position.
- Last stage of `|>` pipeline.

**Not** tail:
- Inside a `ty` block (needs frame for catch).
- Inside a `fi` block (needs frame for finally).
- Inside a `wi` block (needs frame for cleanup).
- Inside a `hd` block (needs frame for handler context).
- Pipeline intermediate stages (`|>` argument evaluations).

### Mutual recursion

Mutual tail calls behave identically — trampolined.

### No keyword

Implicit. Snafu guarantees it as part of language semantics.

### Debugging

Tail-called frames are replaced, so the stack doesn't show the caller. If the debugger needs the history, use state-time-travel (§34) or `db.no_tco()`.

---

## 34. State and time-travel

### State buffer

The interpreter maintains a `state_buffer` list of snapshots. Snapshots are created explicitly via `ps()`.

### Push — `ps()`

```
ps()                              # push anonymous snapshot, returns index
ps("checkpoint1")                 # push named snapshot
```

`ps()` is a special form that deep-copies all bindings in the current scope chain into a flat dict and appends a snapshot to the state buffer. Each snapshot is a dict with keys:
- `name` — the optional name string (or `None`)
- `bindings` — a dict of all variable names to their deep-copied values
- `index` — the position in the state buffer

### Access — `sa(n)`, `sp(name_or_n)`

```
sa(-1)                            # last snapshot (by buffer index, negative = from end)
sa(0)                             # first snapshot
sp("checkpoint1")                 # find snapshot by name (searches backwards)
sp(-1)                            # same as sa(-1) when called with an integer
```

`sa` and `sp` are prelude functions. `sa(n)` indexes into the state buffer directly. `sp(name)` searches backwards for a snapshot with the given name.

### Current state — `st()`

```
snapshot = st()                   # snapshot current state without pushing to buffer
```

`st()` is a special form (zero-argument call) that returns a snapshot dict of the current scope, with `index: -1` to indicate it is not in the buffer.

**Note:** `st(iterable)` with an argument falls through to the `st` prelude function (set constructor).

### Restoration — `restore(snapshot)`

```
restore(sa(-1))                   # restore bindings from the last snapshot
restore(sp("checkpoint1"))        # restore bindings from named checkpoint
```

`restore(snapshot)` is a special form that iterates over `snapshot.bindings` and assigns each key-value pair back into the current scope.

### Limitations

- Snapshots are scope-level deep copies, not full program state (no instruction pointer, call stack, or generator state).
- Forward time-travel (`sa[+N]`, forking) is not implemented.
- Per-variable history (`x.pa[-3]`) is not implemented.
- Automatic per-statement recording is not implemented; snapshots are manual via `ps()`.

---

## 35. Self-modification

### Source and AST access

At program startup, `run()` exposes:
- `src` — the program's original source text as a `Str`.
- `ast` — the program's parsed AST tree (a `Block` node containing the top-level statements).

```
p(src)                            # print the program's own source
p(len(ast.stmts))                 # number of top-level statements
```

These are ordinary global-scope bindings, set once at startup. Modifying `src` or `ast` does not retroactively affect the running program (the AST has already been parsed and evaluation is in progress).

### AST manipulation functions

- `ast_of(expr)` — special form: returns the raw AST node for `expr` without evaluating it. The returned node is a Python dataclass instance.
- `eval_ast(node)` — special form: evaluates an AST node in the current scope. The argument is first evaluated (so you can pass a variable holding an AST node), and if the result is a `Node`, it is interpreted.
- `ast_new(type_name, **fields)` — special form: creates a new AST node. `type_name` is a string matching a `Node` subclass name (e.g., `"NumLit"`, `"BinOp"`, `"Ident"`, `"If"`, `"Call"`, `"Block"`). Fields are keyword arguments matching the dataclass fields.
- `ast_src(node)` — prelude function: converts an AST node back to a source-like string representation.

### AST node structure

AST nodes are Python dataclasses. All nodes inherit from `Node` (which carries `line` and `col`). Attribute access works via Python's `getattr()` fallback in `get_attr()`. Common node types:

- `NumLit(value)`, `StrLit(pieces)`, `BoolLit(value)`, `Ident(name)`
- `BinOp(op, lhs, rhs)`, `UnaryOp(op, operand)`
- `Call(fn, args, kwargs)`, `Lambda(params, body, implicit)`
- `If(cond, then, elif_clauses, else_)`, `Block(stmts)`
- `Assign(target, value, op)`, `FnDecl(name, params, body, decorators)`
- And many more (see `_AST_TYPES` registry in interpreter source).

### Interpreter levels (implemented in v1.6)

`lv(N)` sets the interpreter depth. At level 1 (default), code runs directly. At level 2+, each statement is passed through a user-modifiable **Snafu-written meta-interpreter** before execution.

```
lv(2)                          # enable level-2 interpretation
isrc[1]                        # default: "f(node, scope) -> eval_ast(node, scope)"
```

The meta-interpreter is a Snafu function `f(node, scope)` that receives each statement's AST node and the program scope. It decides what to do — typically calls `eval_ast(node, scope)` but can modify, log, or transform the AST first.

**Modifying the interpreter (in Snafu, not Python):**

```
# Log every statement before executing:
lv(2)
isrc[1] = "f(node, scope) -> { p(\">> \" + ast_src(node)); eval_ast(node, scope) }"
x = 5                          # prints ">> Assign(...)" then executes

# Double all expression results:
lv(2)
isrc[1] = "f(node, scope) -> eval_ast(node, scope) * 2"
1 + 2                          # returns 6 instead of 3
```

**API:**

- `lv(N)` — set interpreter level (1 = direct, 2+ = meta-interpreted)
- `interp_level()` — query current level
- `isrc[n]` — read/write the meta-interpreter source string at level n
- `iast[n]` — read the parsed AST of the meta-interpreter at level n
- `eval_ast(node, scope)` — evaluate an AST node in a given scope (the second argument is critical for meta-interpreters to pass the program scope through)

**Re-entry prevention:** the meta-interpreter's own body runs directly (level 0) to avoid infinite recursion. Only top-level program statements go through the meta-interpreter.

---

## 36. Debugging protocol

### Dbg protocol

```
pr Dbg {
  on_step(self, fr)
  on_call(self, fr, fn, args)
  on_return(self, fr, val)
  on_raise(self, fr, exc)
  on_catch(self, fr, exc)
  on_assign(self, fr, name, val)
  on_read(self, fr, name)
  on_effect(self, fr, eff)
  on_break(self, fr, bp)
  on_yield(self, fr, val)
  on_resume(self, fr, val)
}
```

Default impl: all no-ops. Implement only what you need.

### Install

```
db(my_dbg)                        # install for rest of program
wi db(my_dbg) { … }               # scoped; auto-uninstalled
```

Multiple debuggers: all fire, in install order.

### Frames

Frame attrs:
- `sc`, `ln`, `fl`, `fn`, `up` (parent frame)
- `ast`, `st` (state-buffer index), `lc` (local-call count), `id`

Mutating `fr.sc` live-patches.

### Breakpoints

```
bp "file.snf:42"                  # source-level
bp "file.snf:42" if x > 3         # conditional
bp fn_name                        # on entry to fn_name
bp()                              # break right here
bp.rm(id)                         # remove
bp.cl()                           # clear all
```

### Standard debuggers

- `Db.pdb()` — pdb-style REPL
- `Db.tr()` — tracer
- `Db.pf()` — profiler
- `Db.tv()` — time-travel debugger (requires `ps`)

### REPL at breakpoint

Commands: `s` step, `n` next, `o` step-out, `c` continue, `u`/`d` frame-nav, `p expr`, `ev "code"`, `sa -1`/`+1`, `ls`, `bt`.

---

## 37. Standard prelude

Names pre-bound in `tp` (top-level scope). All are overridable (shadowable).

### I/O

- `p(*args, sep=" ", end="\n")` — print to stdout
- `pe(*args, sep=" ", end="\n")` — print to stderr
- `inp(prompt="")` — read line from stdin
- `read(path)` — read entire file as string (UTF-8)
- `write(path, content)` — write string to file (UTF-8)
- `open(path, mode="r")` — open file, returns a `File` object with `.rd()`, `.rl()`, `.wr(s)`, `.cl()`, `.lines()` methods. Supports context manager protocol (`.en()`, `.ex()`) for use with `wi`.

### Collections

- `len(x)` — length
- `lst(iter)` — materialize iterable to list
- `st(iter)` — materialize iterable to set
- `dct(iter)` — materialize iterable of pairs to dict
- `range(a, b=None, step=1)` — range (returns materialized list)
- `en(iter)` — enumerate; returns `[[0, x], [1, y], ...]`
- `zp(*iters)` — zip; returns list of lists
- `rp(val, n)` — repeat: `[val] * n`
- `uniq(iter)` — deduplicate preserving order
- `rev(iter)` — reverse
- `flat(iter)` — flatten one level of nesting
- `take(iter, n)` — first n elements
- `drop(iter, n)` — skip first n elements
- `srt(iter, k=None, rv=False)` — sort with optional key fn and reverse flag
- `sum(iter, init=0)` — sum
- `min(*args)`, `max(*args)` — variadic or single-iterable
- `join(sep, iter)` — join elements with separator string
- `any_of(iter, pred)` — true if pred is truthy for any element
- `all_of(iter, pred)` — true if pred is truthy for all elements
- `find_first(iter, pred)` — first element where pred is truthy, or `und`

### Higher-order

Higher-order functions use **iter-first** argument order (Elixir/Gleam convention):

- `m(iter, f)` — map
- `fl(iter, pred)` — filter
- `rdc(iter, f, init=und)` — reduce/fold
- `map_fn(f, iter)` — legacy fn-first map (also available)

### Type coercion

- `int(x)` — convert to integer
- `flt(x)` — convert to float
- `str(x)` — convert to string

### Math

- `abs(x)` — absolute value
- `sqrt(x)` — square root
- `exp(x)` — e^x
- `log(x)`, `ln(x)` — natural logarithm (both are the same)
- `log2(x)` — base-2 logarithm
- `log10(x)` — base-10 logarithm
- `sin(x)`, `cos(x)`, `tan(x)` — trigonometric
- `asin(x)`, `acos(x)`, `atan(x)` — inverse trigonometric
- `atan2(y, x)` — two-argument arctangent
- `sinh(x)`, `cosh(x)`, `tanh(x)` — hyperbolic
- `floor(x)`, `ceil(x)`, `round(x)`, `trunc(x)` — rounding
- `sgn(x)` — sign: -1, 0, or 1
- `gcd(a, b)` — greatest common divisor
- `lcm(a, b)` — least common multiple
- `fact(n)` — factorial
- `prd(iter)` — product of elements
- `pi`, `e`, `tau` — mathematical constants
- `oo` — positive infinity (also a keyword/literal)

### Random

- `rand()` — random float in [0, 1)
- `randint(a, b)` — random integer in [a, b]
- `choice(lst)` — random element from list
- `shuffle(lst)` — shuffle list in place, returns it

### Strings

- `chr(n)` — code point to character
- `ord(s)` — first character to code point
- `fmt(x, spec)` — format value with Python format spec

### Functions

- `prt(f, *bound)` — partial application. `und` in bound positions acts as a placeholder slot filled by later arguments.
- `flip(f)` — swap first two arguments
- `cnst(v)` — constant function: returns `v` regardless of arguments
- `tail(fn, *args, **kwargs)` — explicit tail-call optimization (returns `_TailCall` sentinel for trampoline)
- `fork(f, g, h)` — tacit fork: `fork(f,g,h)(x) = g(f(x), h(x))`
- `hook(f, g)` — tacit hook: `hook(f,g)(x) = f(x, g(x))`
- `tee(*fns)` — apply multiple functions, return list of results (§37p)
- `tap(fn)` — apply function for side effect, return original data (§37p)

### Memoization

- `memo(fn)` -- wrap a function with a cache. Returns a memoized version that caches results keyed by positional arguments.

### Lazy values

- `lazy(fn)` -- create a lazy thunk from a zero-argument function. The function is not called until `force()`.
- `force(x)` -- evaluate a lazy thunk, caching the result. Subsequent `force()` calls return the cached value. If `x` is not a `LazyThunk`, returns `x` unchanged.

### JSON serialization

- `to_json(val, indent=None)` -- serialize a Snafu value to a JSON string. `und` maps to `null`; `Rat` converts to float; variants serialize as `{"__variant__": name, "fields": [...]}`.
- `from_json(s)` -- parse a JSON string into Snafu values. `null` maps to `und`; arrays to lists; objects to dicts.

### Actors

- `actor(handler_fn)` -- create a message-processing actor with `.send()`, `.send_async()`, `.stop()` methods (§37w).

### Types and objects

- `type(x)` — type name string (`"Int"`, `"Str"`, `"Lst"`, `"Fn"`, `"Obj"`, `"Cx"`, etc.)
- `isa(x, type_name)` — type check (supports tower promotion: `isa(1, "Num")` is true)
- `id(x)` — unique object identity integer
- `hs(x)` — hash value
- `cp(o)` — deep copy
- `new(*parents, **init)` — create new object with prototype chain
- `implements(x, Proto)` — protocol membership check (basic)

### Concurrency

- `ch(n=0)` — create a channel (prelude function form, equivalent to the `ch` keyword)
- `sl(*channels, timeout_ms=None)` — select across channels (prelude function form)
- `signal()` — create a signal object with `.connect(fn)`, `.disconnect(fn)`, `.emit(*args)`
- `atom(initial)` — create a mutable container with `.get()`, `.set(v)`, `.swap(fn)`, `.cas(old, new)`
- `sleep(ms)` — sleep for `ms` milliseconds
- `fk_id()` — current fork branch ID (§37k)
- `fk_join()` — wait for child forks, return results (§37k)
- `fk_map(lst, fn)` — parallel map via forking (§37k)
- `fk_tree()` — fork hierarchy tree (§37k)

### Logic and constraints

- `lv(name=None)` — create a logic variable (§37m)
- `unify(a, b)` — unify two values, binding logic variables (§37m)
- `solve(vars, constraint_fn, domain=None)` — backtracking constraint solver (§37n)

### Coercion

- `cv(from_type, to_type, fn)` — register a type coercion function (§37o)

### Golf utilities

- `S`, `J`, `R`, `U`, `Z`, `T`, `F`, `D`, `P`, `W`, `L`, `N`, `I`, `G`, `C`, `X` — one-letter aliases (§37s)
- `UD(digits, base=10)` — undigits (§37s)
- `to_base(n, base)`, `from_base(s, base)` — base conversion (§37s)
- `powerset(iter)` — all subsets (§37s)
- `rotate(lst, n)`, `window(lst, n)` — list manipulation (§37s)
- `from_n(start)`, `cycle(lst)`, `repeat_val(v)` — infinite generators (§37s)
- `min_by(iter, fn)`, `max_by(iter, fn)` — extrema by key (§37s)
- `sr(fn, lst)` — scan from right (§37s)
- `succ(x)`, `pred(x)` — successor/predecessor (§37s)
- `divisors(n)` — sorted divisors (§37s)
- `bnot(x)`, `bxor(a,b)`, `shl(x,n)`, `shr(x,n)` — bitwise functions (§8)
- `save_state(path)`, `load_state(path)` — state persistence (§37s)

### Recording and replay

- `play(trace)` — replay a trace captured by `rec { }` (§37l)

### Complex numbers

- `cx(re, im)` — construct a complex number
- `re(z)` — real part (or z itself if not complex)
- `im(z)` — imaginary part (or 0 if not complex)

### Meta / eval

- `ev(code)` — eval in caller scope (special form)
- `"code".ca()` — eval string in global scope
- `ast_of(expr)` — return raw AST node (special form)
- `eval_ast(node)` — evaluate AST node in current scope (special form)
- `ast_new(type, **fields)` — create new AST node (special form)
- `ast_src(node)` — AST node to source string
- `bp()` — breakpoint: drops into an interactive debugger REPL with access to current scope

### State time-travel

- `ps(name=None)` — push state snapshot (special form)
- `sa(n)` — access snapshot by buffer index
- `sp(name_or_n)` — access snapshot by name or index
- `st()` — snapshot current state without pushing (special form, zero args only)
- `restore(snapshot)` — restore bindings from snapshot (special form)

### Scope

- `tp` — reference to the top-level (global) scope object

### Python interop

- `py.import(name)` — import a Python module via `importlib.import_module`

### Transducers

- `xm(f)` — map transducer
- `xfl(pred)` — filter transducer
- `xtk(n)` — take transducer
- `xdr(n)` — drop transducer
- `xsc(init, f)` — scan transducer

### Lenses

- `lens(key)` — create a lens for string attribute or integer index

### Exception constructors

All exception types are available as callable constructors: `Exc`, `ArgErr`, `TypeErr`, `ValErr`, `NameErr`, `AttrErr`, `IxErr`, `KeyErr`, `DivErr`, `UndErr`, `MatchErr`, `IOErr`, `ParseErr`, `DispatchAmbig`, `BindErr`, `ContractErr`, `InterpErr`

### String methods

Available on all `Str` values: `.upr()`, `.lwr()`, `.strip()`, `.lstrip()`, `.rstrip()`, `.split(sep)`, `.starts(x)`, `.ends(x)`, `.find(x)`, `.count(x)`, `.replace(a, b)`, `.join(iter)`, `.ca()`, `.len()`, `.rev()`, `.chars()`, `.contains(s)`, `.repeat(n)`, `.idx(s)`, `.lines()`, `.words()`, `.fmt(spec)`, `.upper()`, `.lower()`, `.bytes()`, `.trim()`

### List methods

`.len()`, `.psh(x)`, `.pop()`, `.first()`, `.last()`, `.rev()`, `.cp()`, `.srt(k=None, rv=False)`, `.flat()`, `.any(pred)`, `.all(pred)`, `.find(pred)`, `.idx(val)`, `.contains(val)`, `.map(f)`, `.filter(f)`, `.reduce(f, init=und)`, `.take(n)`, `.drop(n)`, `.zip(other)`, `.en()`, `.sum()`, `.min()`, `.max()`, `.uniq()`, `.sort_by(f)`, `.group_by(f)`, `.chunk(n)`, `.intersperse(val)`

### Dict methods

`.len()`, `.keys()`, `.values()`, `.items()`, `.pairs()`, `.cp()`, `.inv()`, `.inv_get(val)`, `.has(k)`, `.merge(other)`, `.map_vals(f)`, `.map_keys(f)`, `.filter_vals(f)`, `.get(k, default=und)`, `.set(k, v)`, `.without(k)`, `.update(other)`, `.to_list()`, `.flip()`

### Tuple (frozen list) methods

`.len()`, `.first()`, `.last()`, `.rev()`, `.contains(val)`, `.idx(val)`, `.map(f)`, `.filter(f)`, `.take(n)`, `.drop(n)`

### Generator methods

`.sd(val)` — send value into generator, `.nx()` — get next value

---

## 37a. APL-style array operations

Snafu supports APL-inspired operator modifiers for element-wise, reduce, scan, and outer-product operations on lists.

### Element-wise — `op.`

Any binary arithmetic or comparison operator followed by `.` applies element-wise across two lists (or a list and a scalar):

```
[1, 2, 3] +. [4, 5, 6]          # [5, 7, 9]
[1, 2, 3] *. 10                  # [10, 20, 30]
10 *. [1, 2, 3]                  # [10, 20, 30]
[1, 2, 3] **. [2, 3, 4]         # [1, 8, 81]
```

**Scalar extension:** If one operand is a scalar (non-list) and the other is a list, the scalar is broadcast to match the list's length. If both are lists, they must have equal length or the shorter is extended with `und`.

Supported base operators: `+`, `-`, `*`, `/`, `**`, `//`, `%`, `==`, `<>`, `<`, `>`, `<=`, `>=`, `&&`, `||`, `^^`.

### Reduce — `op/`

A reduce operator folds a list using the base operator:

```
+/ [1, 2, 3, 4]                  # 10 (= 1+2+3+4)
*/ [1, 2, 3, 4]                  # 24 (= 1*2*3*4)
**/ [2, 3, 2]                    # 512 (= 2 ** (3 ** 2) — right-to-left? No: left-to-right fold)
```

Reduce on an empty list returns `und`. Reduce on a single-element list returns that element.

Reduce operators are parsed as unary prefix operators at the same precedence as other unary operators (level 95 in the precedence table).

Supported: `+/`, `-/`, `*/`, `**/`, `%/`.

### Scan — `op\`

A scan operator computes running (cumulative) reductions:

```
+\ [1, 2, 3, 4]                  # [1, 3, 6, 10]
*\ [1, 2, 3, 4]                  # [1, 2, 6, 24]
```

Scan on an empty list returns `[]`.

Supported: `+\`, `-\`, `*\`, `**\`, `%\`.

### Outer product — `op..`

The outer product operator applies the base operation to all pairs from two lists, producing a 2D list (list of lists):

```
[1, 2, 3] *.. [4, 5]            # [[4, 5], [8, 10], [12, 15]]
[1, 2] +.. [10, 20, 30]         # [[11, 21, 31], [12, 22, 32]]
```

For each element `a` in the left operand and each element `b` in the right operand, compute `a op b`. The result is `[[a1 op b1, a1 op b2, ...], [a2 op b1, a2 op b2, ...], ...]`.

Supported: `+..`, `-..`, `*..`, `**..`, `/..`, `%..`, `==..`, `<>..`, `<..`, `>..`.

---

## 37b. Context managers — `wi`

The `wi` (with) statement provides scoped resource management:

```
wi expr as name { body }
wi expr1 as name1, expr2 as name2 { body }
```

**Protocol:** On entry, `wi` calls `.en()` (enter) on the expression value if it exists. The return value of `.en()` is bound to `name` (if `as name` is specified; otherwise the original value is available). On exit (normal or exception), `wi` calls `.ex(err)` (exit) on the original expression value -- with `und` for normal exit or the exception for error exit.

**Multiple bindings:** Comma-separated `expr as name` pairs create multiple context bindings. All are entered in order and exited in reverse order.

```
wi open("file.txt") as f {
  data = f.read()
}
# f.ex(und) called on normal exit; f.ex(exc) on exception
```

---

## 37c. Strict and loose mode — `sd` / `ld`

### Scoped strict mode

```
sd {
  x = und + 1                    # raises UndErr
}
```

Operations on `und` inside a `sd` block raise `UndErr` instead of propagating silently.

### Permanent strict mode

```
sd                               # bare sd — all following code is strict
```

A bare `sd` without a block body enables strict mode permanently for the rest of the program.

### Loose mode — `ld`

```
sd {
  # strict here
  ld {
    x = und + 1                  # returns und (propagation)
  }
  # strict again
}
```

`ld` reverses `sd` within its block. Like `sd`, a bare `ld` without a body permanently disables strict mode.

---

## 38. Formal grammar (EBNF-ish)

Approximate. Operator precedence from §8 applies to expression parsing (precedence-climbing parser recommended).

```
program       = statement*

statement     = declaration
              | expression_stmt
              | assignment
              | control_flow
              | block

declaration   = "df" IDENT params body
              | "ct" IDENT params body
              | "sm" IDENT "=" variants derivation?
              | "pr" IDENT protocol_inherit? "{" proto_method* "}"
              | "im" IDENT "for" type_expr "{" impl_method* "}"
              | "ef" IDENT "(" param_list? ")"
              | "mc" IDENT params body
              | "xp" "[" name_list "]"
              | "us" use_spec
              | "lbl" IDENT

variants      = variant ("|" variant)*
variant       = IDENT ("(" param_list ")")?

derivation    = "dv" "[" proto_list "]"

proto_method  = IDENT "(" param_list ")" ("=" expr)?

impl_method   = IDENT "(" pattern_params ")" "=" expr
              | IDENT "(" pattern_params ")" body

params        = "(" param_list? ")"
param_list    = param ("," param)*
param         = type_expr? IDENT ("=" expr)?
              | "*" IDENT
              | "**" IDENT
              | "/"
              | "*"
              | pattern                     # pattern-head
              | IDENT "|" guard_expr        # guard

body          = "{" statement* "}"
              | "=" expr
              | "->" expr

assignment    = lvalue assign_op expr
              | lvalue ":=" expr            # alias
              | lvalue "~=" expr            # tracking

assign_op     = "=" | "+=" | "-=" | "*=" | "/=" | "//=" | "%=" | "**="
              | "<>=" | "===" | "!===" | "<-=" | "->=" | "!<-=" | "!->="
              | "&&=" | "||=" | "^^=" | "!&&=" | "!||=" | "!^^="
              | ".="

lvalue        = IDENT
              | lvalue "." IDENT
              | lvalue "[" index_expr "]"
              | lvalue "{" key_expr "}"
              | "(" lvalue_list ")"         # tuple unpack
              | "[" lvalue_list "]"         # list unpack

control_flow  = if_stmt | for_stmt | while_stmt | loop_stmt
              | match_stmt | try_stmt | with_stmt
              | break_stmt | continue_stmt | return_stmt
              | yield_stmt | goto_stmt | comefrom_stmt | resume_stmt
              | raise_stmt
              | on_stmt | off_stmt | xs_stmt | sd_stmt | ld_stmt
              | handle_stmt | perform_stmt
              | gt_stmt | aw_stmt

if_stmt       = "if" expr body ("eli" expr body)* ("el" body)?
for_stmt      = "for" for_pattern ("if"|"wh"|"un") expr? body loop_tail?
while_stmt    = "wh" expr body loop_tail?
loop_stmt     = "lp" (INT)? body loop_tail?
match_stmt    = "mt" expr "{" match_arm+ "}"
match_arm     = pattern ("if" expr)? "->" (expr | body)
try_stmt      = "ty" body ("ex" type_expr? IDENT? body)+ ("fi" body)?
with_stmt     = "wi" with_binding ("," with_binding)* body
with_binding  = expr ("as" IDENT)?
handle_stmt   = "hd" (body | expr) "with" "{" handler_case+ "}"
handler_case  = pattern IDENT? "->" (expr | body)
sd_stmt       = "sd" body?                          # strict mode (block or permanent)
ld_stmt       = "ld" body?                          # loose mode (block or permanent)

loop_tail     = ("bf" body)? ("bt" body)? ("af" body)?
                ("el" body)? ("fi" body)?

for_pattern   = pattern "in" expr

expression    = ternary
ternary       = pipe ("?" expr ":" expr)?
pipe          = bind (("|>"|"|>>") call)*
bind          = assignment_expr
              | implies
implies       = or (("<-"|"->"|"!<-"|"!->") or)*
or            = xor (("||"|"!||") xor)*
xor           = and (("^^"|"!^^") and)*
and           = not (("&&"|"!&&") not)*
not           = "!" not | cmp
cmp           = range (cmp_op range)*
cmp_op        = "=="|"<>"|"==="|"!=="|"<"|">"|"<="|">="|"is"|"in"|"!<"|"!>"
range         = addition (("..",|"..=") addition)?
addition      = multiplication (("+"|"-") multiplication)*
multiplication = unary (("*"|"/"|"%") unary)*
unary         = ("+"|"-"|"~"|"#") unary | power
power         = postfix (("**"|"//") unary)?
postfix       = primary postfix_op*
postfix_op    = "(" call_args? ")" | "[" index_expr "]" | "{" key_expr "}" | "." IDENT
primary       = NUMBER | STRING | REGEX | IDENT | "(" expr ")" | "[" list_expr "]"
              | "{" dict_or_block "}" | "und" | "true" | "false" | "_" | "$" varvar
              | fn_literal | sum_variant_literal | paren_tuple
              | "|" expr "|"                # abs

dict_or_block = "{" statement* "}"   # block if any stmt-shape
              | "{" (pair ("," pair)*)? "}"   # dict
pair          = expr ":" expr | expr

fn_literal    = "f" ("(" param_list? ")")? ("->" expr | body)

varvar        = IDENT | "(" expr ")" | "$" varvar | "{" expr "}"

(...and so on.)
```

A full LALR-ready grammar is derivable; this EBNF is for the human reader.

---

## 39. Implementation notes (Python interpreter)

### Target

Python 3.11+. Single-file implementation acceptable for v0.1 (5000-15000 lines); modularize as needed.

### Core architecture

1. **Lexer** — hand-rolled; emits tokens per §3. `#` is always a comment; `;` emits `NEWLINE` tokens.
2. **Parser** — recursive descent with Pratt-style precedence climb for expressions. Produces AST. Context-sensitive keywords (`f`, `r`, `y`) use lookahead to disambiguate.
3. **AST** — dataclass-based node types; every node carries source location (`line`, `col`).
4. **Interpreter** — tree-walking. Uses Python's native call stack (no trampolining yet -- see §33). Method dispatch via `eval_{NodeType}` methods.
5. **Runtime** — dict-backed `Scope` objects with parent chain; multi-dispatch tables per function name.
6. **Prelude** — Python-implemented built-ins wrapped to look like Snafu functions, installed in `install_prelude()`.

### Key runtime structures

- **`Scope`** — name→value dict (`bindings`) + `parent` pointer. Lookup walks the parent chain.
- **`Interpreter`** — holds `global_scope`, `dispatch_tables` (multi-dispatch), `protocols`, `impls`, `exc_stack` (for bare `rs` re-raise), `module_cache`, and `strict` flag.
- **`SnafuObj`** — runtime object: `parents` tuple (prototype chain), `attrs` dict, `type_name` string.
- **`SnafuGenerator`** — coroutine wrapper using Python threading and a `queue.Queue` for yield communication.
- **`MultiDispatch`** — function name with multiple typed methods; dispatches by type-tuple scoring.
- **Control-flow exceptions** — `_Return`, `_Break`, `_Continue`, `_GotoSignal`, `_ResumeSignal`, `_EffectSignal` — used for non-local control flow within the tree-walking interpreter.
- **`SnafuTransducer`** — composable transducer with a `transform` function (reducer -> reducer).
- **`SnafuLens`** — lens with `getter` and `setter` functions.
- **`SnafuMacro`** — wraps a function that receives unevaluated AST nodes.

### Evaluation model

The interpreter is tree-walking: `eval_node(node, scope)` dispatches to `eval_{NodeType}` methods via `getattr`. Function calls use Python's native call stack (no trampolining). This means Snafu recursion is bounded by Python's recursion limit.

### Multiple dispatch

Each function name has a `MultiDispatch` table (`dispatch_tables` dict on `Interpreter`). Dispatch at call time:
1. Compute type-tuple of arguments via `type_name()`.
2. Scan method table, compute `_match_score` per method (20 for exact value match, 10 for exact type, 5 for ancestor type, 0 for wildcard).
3. Pick the method with the highest total score. Ties raise `DispatchAmbig`.

No call-site caching in v1.0.

### Goto/comefrom

`goto` raises a `_GotoSignal` Python exception that propagates up through `eval_block` loops. Each block scans its statement list for a matching `lbl` and resumes there. `cf` hooks are registered per-block as a dict mapping label names to resume indices.

### Exception handling

Uses Python's native `try`/`except`. `SnafuError` (and subclasses) are Python exceptions. The `exc_stack` list tracks currently-handled exceptions for bare `rs` re-raise.

### Coroutines / generators

`ct` declarations create a factory function. When called, the factory spawns a `SnafuGenerator` that runs the body in a Python daemon thread. `y expr` puts values on a `queue.Queue`; the generator's `__next__` reads from it. End-of-body signals `_YIELD_SENTINEL`.

### Python interop

- `py.import(name)` calls Python's `importlib.import_module`.
- Python objects accessed via fallback `getattr()` in `get_attr()`.
- No automatic wrapping/unwrapping of Snafu callables for Python consumption yet.

### Features using Python-native mechanisms

- **Algebraic effects** — simple mode uses Python exceptions (`_EffectSignal`); resumable mode uses threading with queues for true continuation resumption (§37r).
- **Generators/coroutines** — implemented via Python threading and `queue.Queue`, not effect-based.
- **Green threads** — implemented via Python `threading.Thread` (daemon threads), not a custom scheduler.
- **Tail calls** — explicit via `tail()` + trampoline in `_call_value()`, not implicit.
- **Reactive triggers** — implemented via scope assignment hooks on the global scope.
- **State time-travel** — implemented via deep-copy snapshots of scope bindings.
- **Macros** — call-time AST transformation, not parse-time expansion.

### Not yet implemented

Multi-level meta-circular interpretation (`lv > 1`, `isrc`, `iast`) and full Python interop wrapping. See §40.

---

## 40. Deferred and dropped features

### Dropped (will not be added)

- **Equation solving** (`<x+y=2>` syntax) — complexity too high, narrow use.
- **User-facing tainting** (`tnt`, `unt`, `rft`) — no compelling use case; taint graph stays as an interpreter-internal mechanism for `~=` and `on`.
- **INTERCAL features** (`abstain`, `ignore`, `remember`) — even for an esoteric-flavoured language, too weird.
- **Multi-dot numeric literals** (`3.141.593`) — conflicts with `..` range; minimal benefit.
- **Every-variable-is-a-list** — too pervasive; ambiguous semantics.
- **Mutable numbers** — decided immutable (§4).
- **`amb` special form** — subsumed by effect handlers (multi-resumption not implemented though).
- **Quaternion numbers** (`Qn`) — dropped from scope.

### Implemented in v1.0

All of the following are working in the current interpreter:

- **Core language:** numbers (Int, Flt, Rat, Cx), strings with interpolation, booleans, `und`, lists, dicts, sets, unified `[]` collections, frozen collections (`fr[...]`)
- **Control flow:** `if`/`eli`/`el`, `for`/`in`, `wh`, `un`, `lp`, `br`/`cn`, `mt` (pattern matching), `by` (range step)
- **Functions:** `df` named, `f` anonymous (context-sensitive), closures, `*args`/`**kwargs`, defaults, decorators
- **Return/yield:** `r` (context-sensitive return), `y`/`yf` (context-sensitive yield), bidirectional yield (`.sd()`)
- **Coroutines:** `ct name(params) { body }` with threading-based generators
- **Exceptions:** `ty`/`ex`/`fi`, `rs` (including bare re-raise), `fr` chaining
- **Pattern matching:** literal, variable, wildcard, list `[h, ...t]`, dict, variant, guard, or patterns
- **Sum types:** `sm` declarations, variant constructors and matching
- **Protocols:** `pr` declarations, `im` implementations
- **Multiple dispatch:** type-based, value-based, specificity ranking
- **Prototypes:** `new()`, prototype chain, attribute lookup
- **Labels/goto/comefrom/resume/sub:** `lbl`, `goto`, `cf`, `rm`, `sub(lbl1, lbl2)`
- **Strict mode:** `sd` (scoped and permanent), `ld` (reverses strict)
- **Context managers:** `wi expr as name { body }` with `.en()`/`.ex()` protocol
- **Modules:** `us module`, `us *module`, `xp [names]`
- **Pipeline:** `|>` (first-arg), `|>>` (last-arg)
- **Eval:** `ev("code")` in caller scope, `"code".ca()` in global scope
- **APL operators:** element-wise (`op.`), reduce (`op/`), scan (`op\`), outer product (`op..`)
- **Structural equality:** `===`/`!==` with recursive comparison
- **Python interop:** `py.import(name)` for importing Python modules
- **Algebraic effects:** `ef` declarations, `pf` perform, `hd { } with { }` handlers with resumable continuations (§37r)
- **Concurrency:** `gt` (green threads via Python threading), `aw` (await/join), `ch(n)` (channels), `sl` (select), `xs { }` (execution sets)
- **Reactive:** `on x.ch { body }` (assignment triggers), `of x.ch` (remove triggers)
- **Macros:** `mc name(params) { body }` with AST manipulation (`ast_of`, `eval_ast`, `ast_new`, `ast_src`)
- **Self-modification:** `src` (source string), `ast` (parsed AST), AST node construction and evaluation
- **State time-travel:** `ps()`, `sa(n)`, `sp(name)`, `st()`, `restore(snapshot)`
- **Tail calls:** explicit via `tail()` + trampoline
- **Complex numbers:** `3i` literals, `.re`/`.im`/`.conj()`, `cx(re, im)` constructor
- **Variable-variables:** `$name`, `${expr}`, `$$name`
- **Regex literals:** `r/pattern/flags` with `.ma()`, `.al()`, `.sub()`, `.spl()`
- **Regex bind:** `=~` operator
- **Lenses:** `lens(key)`, `.gt()`, `.st()`, `.md()`, composition with `+`
- **Transducers:** `xm`, `xfl`, `xtk`, `xdr`, `xsc`, composition with `+`, `.al(data)`
- **Signals:** `signal()` with `.connect()`, `.disconnect()`, `.emit()`
- **Atoms:** `atom(val)` with `.get()`, `.set()`, `.swap()`, `.cas()`
- **Breakpoints:** `bp()` inline debugger REPL
- **File I/O:** `read`, `write`, `open` with File objects

### Added in v1.1

- **Backtick lambda:** `` `expr` `` — shortest anonymous function form with implicit `a`, `b`, `c` params (§11)
- **Null-coalesce:** `??` — returns right side only when left is `und` (§8)
- **Safe navigation:** `?.` — returns `und` instead of error when target is `und` (§8)
- **Bitwise operators:** `&` (AND), `|` (OR), `bnot`, `bxor`, `shl`, `shr` (§8)
- **Regex findall:** `~/` — `string ~/ regex` returns all matches (§8)
- **One-letter aliases:** `S`/`J`/`R`/`U`/`Z`/`T`/`F`/`D`/`P`/`W`/`L`/`N`/`I`/`G`/`C`/`X` (§37s)
- **Digits/bases:** `D`, `UD`, `to_base`, `from_base` (§37s)
- **Combinatorics:** `X` (permutations), `C` (combinations), `powerset` (§37s)
- **Matrix ops:** `T` (transpose), `rotate`, `window` (§37s)
- **Infinite generators:** `from_n`, `cycle`, `repeat_val` (§37s)
- **Tacit trains:** `fork(f, g, h)`, `hook(f, g)` (§37s)
- **Auto-coercion:** list+element, string-string, char arithmetic (§37s)
- **Auto-print in file mode** (§37s)
- **State persistence:** `save_state`, `load_state` (§37s)
- **Misc utilities:** `min_by`, `max_by`, `flat(depth)`, `sr`, `succ`, `pred`, `divisors` (§37s)

### Added in v1.2

- **List comprehensions with guards:** `[expr for x in iter if guard]` with nested clauses (§21)
- **Where clauses:** `expr whr { bindings }` (§37g)
- **Method-missing:** `__mm__` attribute on objects for fallback dispatch (§37q)
- **Stack-based mode:** `stk { }` with Forth words (`dup`, `swap`, `rot`, `over`, `drop`, `nip`, `tuck`) (§37i)
- **Logic variables:** `lv()` and `unify()` for unification (§37m)
- **Resumable effect continuations:** `hd { } with { Pattern k -> k(val) }` resumes body via threading (§37r)

### Added in v1.3

- **Declarative queries:** `qr source whr filter sel select srt sort` (§37h)
- **Contracts:** `req` (precondition) and `ens` (postcondition) on `df` declarations (§37f)
- **Dynamic scoping:** `dy { }` block with dynamic variable visibility (§37j)
- **Constraint solver:** `solve(vars, constraint_fn, domain)` with backtracking (§37n)
- **Pipeline tee/tap:** `tee(data, f, g)`, `tap(data, f)` (§37p)
- **Execution recording:** `rec { }` / `play(trace)` (§37l)
- **Coercion protocol:** `cv(from_type, to_type, fn)` for multi-dispatch coercion (§37o)

### Added in v1.4

- **Universe forking:** `fk { body }` (scoped), `fk()` (true fork), `fk_map`, `fk_join`, `fk_tree`, `fk_id` (§37k)

### Added in v1.5

- **Named return values:** `r quo=a/b, rem=a%b` returns a dict with string keys (§11)
- **Two-way dict `.inv_get()`:** `d.inv_get(val)` finds the first key by value; `~d` inverts a dict (§6)
- **Memoization:** `memo(fn)` wraps with argument-keyed cache; usable as `@memo` decorator (§37t)
- **Lazy values:** `lazy(fn)` creates a thunk; `force(x)` evaluates and caches (§37u)
- **JSON serialization:** `to_json(val)` and `from_json(str)` (§37v)
- **Condition-based triggers:** `on expr { body }` fires whenever condition is truthy after any assignment; `of all` clears (§23)
- **Actors:** `actor(handler_fn)` with `.send()`, `.send_async()`, `.stop()` (§37w)
- **Function power `f^n`:** `f^n` composes `f` with itself `n` times; `f^0` is identity (§8, §28)
- **Transitive alias chains:** `:=` follows existing aliases, so `a := b := c` all point to `c` (§10)

### Added in v1.6

- **Multi-level meta-circular interpreter** (`lv(N)`, `isrc[n]`, `iast[n]`, `interp_level()`) — user-modifiable interpreter chain; default meta-interp is pass-through `eval_ast`
- **Implicit tail-call optimization** — automatic detection of self-recursive tail calls via `_detect_tail_calls`; both explicit `tail()` and implicit TCO work
- **Function inverse `f^-1`** — algebraic inversion for single-expression single-param functions; handles `+`, `-`, `*`, `/`, `**` with param on either side
- **Symbolic numbers** — `sym(val)` wraps in lazy expression tree; arithmetic propagates symbolically; `flat()` forces evaluation
- **Automatic per-statement state recording** — `auto_record(true/false)` enables fine-grained snapshots; `sa(n)` retrieves them
- **Ref (STM)** — `ref(initial)` creates coordinated mutable reference; `ref.set()`/`ref.swap()` only allowed inside `dosync { }`

### Added in v1.7

- **N-dimensional instruction pointer** (`ja(n)`, `jr(n)`, `ja(row,col)`, `jr(dr,dc)`) — 1D and 2D jumps within statement blocks
- **OS process spawning** — `exec(cmd)`, `shell(cmd)`, `exec_lines(cmd)` via subprocess
- **Python alias table** — 18 two-char aliases (`ma`=math, `js`=json, `os`=os, etc.) with auto-import on first use
- **Traversal lenses and prisms** — `traverse.md(list, fn)` for all-element focus; `prism("Variant")` for sum-type focus
- **Extra transducers** — `xch(n)` chunking, `xdd()` consecutive dedup, `xpp()` passthrough
- **Extended `us` import forms** — `us module { block }` for scoped unqualified access
- **`ev` keyword arguments** — `ev("code", sc=tp, lv=2)` for scope and interpreter-level control

### Deferred list

**All originally-specified features have been implemented.** The deferred list is empty.

### Added in v1.7.1

- **`us module as alias`** — `us math as mth; mth.sqrt(16)` with Python module fallback
- **`jl`** — N-dimensional label jump (alias for `goto`, completes the `ja`/`jr`/`jl` trio)
- **Multi-shot continuations** — `k(val)` can be called multiple times via replay-trace. Single-effect multi-shot works (e.g., `Choose`/`amb`); nested multi-effect is a known limitation

### Known limitations resolved in v1.7.2

All three previously-documented limitations have been fixed:

- **Nested multi-shot effects** — FIXED. Recursive replay-trace correctly handles bodies with multiple `pf` calls. `hd { a = pf Amb([1,2]); b = pf Amb([10,20]); a+b } with { Amb(opts) k -> m(opts, k) }` returns `[[11,21],[12,22]]`.
- **`y` as variable name** — FIXED. `y` is now a keyword only inside `ct` coroutine bodies. Outside coroutines, `y` is a regular identifier.
- **Thread safety** — FIXED. `RLock` protects shared interpreter state (triggers, state buffer, fork registry, dispatch tables, module cache). Hot paths remain unlocked for performance.

### Remaining design trade-offs

- **Python stack depth** — implicit TCO handles self-recursion, but mutual recursion or non-tail recursion still uses Python's stack (~1000 frames). Use explicit `tail()` for mutual TCO.
- **Concurrent scope access** — `Scope.assign`/`lookup` are not locked (performance). Programs with heavy concurrent writes to the same variable may see races. Use `atom`/`ref` for thread-safe shared state.

---

## 37d. Signals and slots

### Signal construction

```
sig = signal()
```

`signal()` is a prelude function that creates a `Signal` object (`SnafuObj` with `type_name="Signal"`).

### Connecting callbacks

```
sig.connect(f -> p("received: " + a))
sig.connect(handler_fn)
```

`.connect(fn)` adds a callback to the signal's listener list.

### Emitting

```
sig.emit(42)                      # fires all connected callbacks with arg 42
sig.emit("hello", "world")       # multiple args
```

`.emit(*args)` calls each connected listener with the given arguments, in registration order.

### Disconnecting

```
sig.disconnect(handler_fn)        # remove a specific callback
```

`.disconnect(fn)` removes the callback from the listener list (no-op if not found).

---

## 37e. Atoms (mutable containers)

### Construction

```
a = atom(0)                       # create an atom with initial value 0
```

`atom(initial)` is a prelude function that creates an `Atom` object (`SnafuObj` with `type_name="Atom"`).

### Operations

```
a.get()                           # read current value
a.set(5)                          # set value, returns new value
a.swap(f -> a + 1)                # apply function to current value, set result, return it
a.cas(old, new)                   # compare-and-swap: if current == old, set to new; returns bool
```

Atoms provide a simple mutable container. They are not thread-safe in the current implementation (no locking beyond Python's GIL).

---

## 37f. Contracts — `req` / `ens`

### Preconditions and postconditions

Functions declared with `df` can have `req` (precondition) and `ens` (postcondition) clauses:

```
df divide(a, b) req b <> 0 ens result <> 0 = a / b

df withdraw(account, amount) req amount > 0 ens result >= 0 {
  account.balance -= amount
  r account.balance
}
```

**Syntax:** `df name(params) req expr ens expr body`

Both `req` and `ens` are optional and can appear independently. `req` is checked before the function body executes. `ens` is checked after, with the special name `result` bound to the function's return value.

If either condition evaluates to falsy, a `ContractErr` is raised.

**Implementation:** The parser produces a `FnDecl` node with `precond` and `postcond` fields. At evaluation time, the function is wrapped: `req` evaluates in a scope containing the parameter bindings; `ens` evaluates in the same scope with `result` added.

---

## 37g. Where clauses — `whr`

### Syntax

```
expr whr { bindings }
```

A where clause evaluates the bindings block first, then evaluates `expr` in a child scope that includes those bindings:

```
area whr {
  area = w * h
  w = 10
  h = 5
}
# returns 50

bmi whr { bmi = weight / (height ** 2); weight = 70; height = 1.75 }
```

`whr` is a trailing modifier at the expression level (parsed at `min_prec == 0`). The bindings block is a regular `{…}` block whose assignments become visible to the leading expression.

---

## 37h. Declarative queries — `qr`

### Syntax

```
qr source whr filter_fn sel select_fn srt sort_fn
```

All three clauses (`whr`, `sel`, `srt`) are optional. `qr` evaluates `source` to get an iterable, then applies filter, select (map), and sort in that order:

```
people = [["name": "Alice", "age": 30], ["name": "Bob", "age": 25], ["name": "Carol", "age": 35]]

qr people whr `a["age"] > 26` sel `a["name"]` srt `a`
# returns ["Alice", "Carol"] sorted

qr 1..=20 whr `a % 3 == 0`
# returns [3, 6, 9, 12, 15, 18]
```

**Implementation:** The `Query` node evaluates `source`, then applies each clause as a function via `_call_value`:
- `whr fn` → `filter(source, fn)`
- `sel fn` → `map(source, fn)`
- `srt fn` → `sorted(source, key=fn)`

---

## 37i. Stack-based mode — `stk`

### Syntax

```
stk {
  values and operators in Forth style
}
```

A `stk` block evaluates in stack-based (Forth) mode. Values are pushed onto a stack; operators pop operands and push results:

```
stk { 3 4 + }                    # 7
stk { 2 3 * 5 + }                # 11
stk { 10 3 dup * swap drop }     # 9  (3*3=9, swap puts 10 on top, drop removes it)
```

### Stack words

| Word    | Effect                                         |
| ------- | ---------------------------------------------- |
| `dup`   | Duplicate top of stack                         |
| `swap`  | Swap top two elements                          |
| `rot`   | Rotate third element to top                    |
| `over`  | Copy second element to top                     |
| `drop`  | Remove top element                             |
| `nip`   | Remove second element                          |
| `tuck`  | Copy top element below second                  |

### Stack operators

Arithmetic operators `+`, `-`, `*`, `/`, `%`, `**` pop two operands and push the result.

Identifiers in a `stk` block resolve to values in the enclosing scope and are pushed onto the stack. The return value of a `stk` block is the top of the stack (or `und` if empty).

---

## 37j. Dynamic scoping — `dy`

### Syntax

```
dy {
  x = 42
  call_some_function()
}
```

A `dy` block establishes dynamic scope: bindings made inside the block are visible to any function called from within it, even if that function does not lexically close over them.

```
df greet() { p(greeting) }

dy {
  greeting = "hello"
  greet()                        # prints "hello" — found via dynamic scope
}
```

**Implementation:** The `dy` block pushes its bindings onto a class-level `Scope._dyn_stack`. When `Scope.lookup()` fails to find a name via the lexical parent chain, it falls back to searching the dynamic stack (most recent first).

Dynamic bindings are automatically removed when the `dy` block exits (even on exception).

---

## 37k. Universe forking — `fk`

### Scoped fork

```
future = fk {
  # runs in a parallel thread with a deep-copied scope
  expensive_computation()
}
result = aw future               # join and get result
```

`fk { body }` deep-copies the current scope and runs the body in a new thread. Returns a `Future` object. The original scope is unaffected by mutations inside the fork.

### True fork (no body)

```
fk()                             # raises _ForkSignal; eval_block clones execution
```

Bare `fk()` (or `fk` without a body) signals the interpreter to clone the current execution context. This is an advanced feature for non-deterministic execution.

### Helper functions

| Function      | Purpose                                                  |
| ------------- | -------------------------------------------------------- |
| `fk_id()`     | Return the current branch's fork ID                      |
| `fk_join()`   | Wait for all child forks, return results list             |
| `fk_map(lst, fn)` | Fork `fn(elem)` for each element in parallel; returns list of Futures |
| `fk_tree()`   | Return a tree object representing the fork hierarchy     |

```
# Parallel map with fk_map
futures = fk_map([1,2,3,4], `a * a`)
results = m(futures, `aw a`)     # [1, 4, 9, 16]
```

`fk_map` spawns a thread per element, each running `fn(elem)` with an independent fork ID. Each returned Future can be awaited with `aw`.

`fk_tree()` returns a `ForkNode` object with `.id`, `.result`, and `.children` attributes for inspecting the fork hierarchy.

---

## 37l. Execution recording — `rec` / `play`

### Recording

```
trace = rec {
  x = 1
  y = x + 2
  p(y)
}
```

`rec { body }` executes the body while recording each evaluated statement into a trace list. The trace is returned as a list of dicts, each with a `stmt` key containing the source representation.

### Replay

```
play(trace)                      # re-execute the recorded statements
```

`play(trace)` iterates over the trace entries and evaluates each `stmt` string in the interpreter's global scope, returning a list of results.

---

## 37m. Logic variables and unification

### Construction

```
x = lv("x")                     # create a logic variable named "x"
y = lv()                         # auto-named
```

`lv(name)` creates a `LogicVar` — an unbound variable that can be unified with values.

### Unification

```
unify(x, 42)                    # binds x to 42; returns true
unify(x, 42)                    # already bound to 42; returns true
unify(x, 99)                    # fails; returns false (42 != 99)
```

`unify(a, b)` attempts to make `a` and `b` equal by binding logic variables:
- If `a` is an unbound `LogicVar`, binds it to `b`.
- If `b` is an unbound `LogicVar`, binds it to `a`.
- If both are lists, unifies element-wise.
- Otherwise, checks `a == b`.

Logic variables support `.deref()` to follow binding chains.

---

## 37n. Constraint solver — `solve`

### Syntax

```
solve(vars, constraint_fn, domain=range)
```

`solve` performs backtracking search over the given domain, binding each logic variable in `vars` to values from `domain` until `constraint_fn()` returns truthy:

```
x = lv("x")
y = lv("y")
solve([x, y], f -> x.deref() + y.deref() == 10 && x.deref() > 0 && y.deref() > 0, 1..=9)
p(x.deref())                    # some value where x + y == 10
p(y.deref())
```

Default domain is `-100..=100`. The solver tries all combinations via depth-first backtracking.

---

## 37o. Coercion protocol — `cv`

### Registration

```
cv("Str", "Int", f(s) -> int(s))     # register Str -> Int coercion
cv("Int", "Str", f(n) -> str(n))     # register Int -> Str coercion
```

`cv(from_type, to_type, fn)` registers a coercion function in the global `_COERCIONS` registry. When multi-dispatch fails to find a direct type match, the dispatcher attempts coercions automatically.

### Automatic use

Registered coercions are tried during multi-dispatch when no direct method matches. The coerced match receives a lower priority score (1) than direct matches (10), ensuring direct matches always win.

---

## 37p. Pipeline tee and tap

### `tee` — apply multiple functions

```
data |> tee(`len(a)`, `sum(a)`)      # [length, total]
tee([1,2,3], len, sum)                # [3, 6]
tee(len, sum)                         # returns a function for later use
```

`tee` passes data through multiple functions and returns a list of all results. In pipe mode (first arg is data), it applies immediately. With all-callable args, it returns a composed function.

### `tap` — side-effect pass-through

```
data |> tap(`p("debug: " + str(a))`) |> process
tap([1,2,3], `p(a)`)                  # prints [1,2,3], returns [1,2,3]
```

`tap` applies a function for its side effect but returns the original data unchanged. Useful for logging/debugging in pipelines.

---

## 37q. Method-missing — `__mm__`

Objects can define a `__mm__` attribute as a fallback for missing attribute access:

```
obj = new()
obj.__mm__ = f(name) -> "you asked for: " + name

obj.anything                         # "you asked for: anything"
obj.foo()                            # calls __mm__("foo") — returns proxy
```

When attribute lookup on a `SnafuObj` fails (no match in own attrs or prototype chain), the interpreter checks for `__mm__` in the object's `attrs`. If found, it returns a `_MethodMissingProxy` that:
- As a value: calls `__mm__(name)` and returns the result.
- As a callable: calls `__mm__(name, *args)`.

The proxy lazily resolves on first non-call use (string conversion, equality, etc.).

---

## 37r. Resumable effect continuations

The `hd { } with { }` handler supports **resumable continuations** when handler cases name a continuation parameter:

```
hd {
  x = pf Ask("name")
  p("got: " + x)
  y = pf Ask("age")
  p("age: " + str(y))
} with {
  Ask(q) k -> k("Alice")         # k resumes the body with "Alice"
  r -> "done: " + r
}
```

When a case has the form `Pattern cont_name -> body`, `cont_name` is bound to a one-shot continuation function. Calling `k(value)` sends `value` back to the `pf` expression in the body, which resumes execution.

**Implementation:** When any handler case names a continuation, the body runs in a separate thread. The `pf` statement puts effects on a queue and blocks; the handler receives effects, matches patterns, and resumes the body via the continuation.

Without continuation parameters, the simpler exception-based path is used (no threading overhead).

---

## 37s. Golf prelude — one-letter aliases and utilities

### One-letter aliases (v1.1)

| Alias | Full name       | Purpose                                    |
| ----- | --------------- | ------------------------------------------ |
| `S`   | `split`         | `S("a,b", ",")` or `S("a b")` (whitespace)|
| `J`   | `join`          | `J(",", [1,2,3])` -> `"1,2,3"`            |
| `R`   | `reverse`       | `R([1,2,3])` -> `[3,2,1]`                 |
| `U`   | `unique`        | `U([1,2,2,3])` -> `[1,2,3]`               |
| `Z`   | `zip`           | `Z([1,2],[3,4])` -> `[[1,3],[2,4]]`        |
| `T`   | `transpose`     | `T([[1,2],[3,4]])` -> `[[1,3],[2,4]]`       |
| `F`   | `flatten`       | `F([[1,2],[3]])` -> `[1,2,3]`              |
| `D`   | `digits`        | `D(123)` -> `[1,2,3]`; `D(255,16)` -> `[15,15]` |
| `P`   | `print`         | Same as `p`                                |
| `W`   | `words`         | `W("hello world")` -> `["hello","world"]`  |
| `L`   | `lines`         | `L("a\nb")` -> `["a","b"]`                |
| `N`   | `numbers`       | `N("3 cats 7")` -> `[3, 7]`               |
| `I`   | `read stdin`    | `I()` -> entire stdin as string            |
| `G`   | `group_by`      | `G([1,2,3,4], \`a%2\`)` -> dict by key     |
| `C`   | `combinations`  | `C([1,2,3], 2)` -> `[[1,2],[1,3],[2,3]]`   |
| `X`   | `permutations`  | `X([1,2,3])` -> all 6 orderings            |

### Digits and bases (v1.1)

```
D(123)                           # [1, 2, 3]
D(255, 16)                       # [15, 15]  (digits in base 16)
UD([1,2,3])                      # 123       (undigits)
UD([15,15], 16)                  # 255
to_base(255, 16)                 # "ff"      (as string)
from_base("ff", 16)              # 255
```

### Combinatorics (v1.1)

```
X([1,2,3])                       # all 6 permutations
C([1,2,3,4], 2)                  # all 2-combinations
powerset([1,2,3])                # all subsets including empty
```

### Matrix ops (v1.1)

```
T([[1,2],[3,4]])                 # transpose
rotate([1,2,3,4,5], 2)          # [3,4,5,1,2]
window([1,2,3,4,5], 3)          # [[1,2,3],[2,3,4],[3,4,5]]
```

### Infinite generators (v1.1)

```
from_n(0)                        # 0, 1, 2, 3, ... (lazy)
from_n(5)                        # 5, 6, 7, ...
cycle([1,2,3])                   # 1, 2, 3, 1, 2, 3, ...
repeat_val(0)                    # 0, 0, 0, ...

take(from_n(1), 5)               # [1, 2, 3, 4, 5]
```

These return `SnafuGenerator` objects (threading-based lazy sequences). Use `take()` or `for`/`br` to consume.

### Tacit trains (v1.1)

```
# fork(f, g, h)(x) = g(f(x), h(x))
avg = fork(sum, f(a,b)->a/b, len)
avg([2, 4, 6])                   # 4

# hook(f, g)(x) = f(x, g(x))
double_check = hook(f(a,b)->a==b, R)
double_check([1,2,1])            # true (palindrome)
```

### Auto-coercion (v1.1)

The `+` and `-` operators have auto-coercion rules:
- `"123" + 1` -> `124` (string parsed as number)
- `[1,2,3] + 4` -> `[1,2,3,4]` (list append)
- `"hello" - "l"` -> `"heo"` (remove all occurrences)
- `"a" + 1` -> `"b"` (character arithmetic: single char + int)
- `"z" - 1` -> `"y"` (character arithmetic: single char - int)

### Miscellaneous utilities (v1.1)

- `min_by(iter, key_fn)` / `max_by(iter, key_fn)` — extrema by key function
- `flat(iter, depth)` — flatten with depth control; `flat(x, oo)` fully flattens
- `sr(fn, list)` — scan from right
- `succ(x)` / `pred(x)` — successor/predecessor (works on chars too)
- `divisors(n)` — sorted list of divisors

### Auto-print in file mode (v1.1)

When running a `.snf` file, the last non-`und` expression result is automatically printed. This also applies to `-e` command-line expressions.

### State persistence (v1.1)

- `save_state(path)` — serialize global scope bindings to a pickle file
- `load_state(path)` — restore bindings from a pickle file

---

## 37t. Memoization -- `memo`

### Usage

```
df fib(n) {
  if n <= 1 { n }
  else { fib(n-1) + fib(n-2) }
}
fib = memo(fib)                  # wrap with cache
fib(30)                          # fast — cached recursive calls
```

`memo(fn)` wraps a function with a dictionary cache keyed by positional arguments. On each call, if the argument tuple has been seen before, the cached result is returned without calling `fn`. Otherwise, `fn` is called, the result is cached, and then returned.

### As a decorator

```
@memo df fib(n) {
  if n <= 1 { n }
  else { fib(n-1) + fib(n-2) }
}
```

Since `memo` takes and returns a function, it works as a decorator via `@`.

### Cache key

The cache key is the tuple of positional arguments. Keyword arguments are not included in the cache key -- if the function is called with different keyword arguments but the same positional arguments, the cached result from the first call is returned.

If key construction fails (unhashable arguments), the function is called without caching.

---

## 37u. Lazy values -- `lazy` / `force`

### Construction

```
val = lazy(f -> expensive_computation())
```

`lazy(fn)` creates a `LazyThunk` wrapping a zero-argument function (or a function that will be called with zero arguments). The function is not invoked at construction time.

### Evaluation

```
result = force(val)              # calls the thunk, caches, and returns result
result2 = force(val)             # returns the cached result (no recomputation)
```

`force(x)` evaluates the thunk if it has not been evaluated yet, caches the result, and returns it. Subsequent calls to `force` on the same thunk return the cached value. If `x` is not a `LazyThunk`, `force` returns `x` unchanged (pass-through).

**Implementation:** `LazyThunk` has three slots: `fn` (the thunk function), `value` (the cached result, initially `und`), and `evaluated` (a boolean flag). On first `force()`, `fn` is called with zero arguments, the result is stored in `value`, and `evaluated` is set to `true`.

---

## 37v. JSON serialization -- `to_json` / `from_json`

### Serialization

```
to_json([1, 2, 3])                   # "[1, 2, 3]"
to_json(["name": "Alice", "age": 30]) # '{"name": "Alice", "age": 30}'
to_json(val, 2)                       # pretty-printed with indent=2
```

`to_json(val, indent=None)` converts a Snafu value to a JSON string. The conversion rules:

| Snafu type | JSON type |
| ---------- | --------- |
| `und`      | `null`    |
| `Bool`     | boolean   |
| `Int`, `Flt` | number  |
| `Rat`      | number (converted to float) |
| `Str`      | string    |
| `Lst`      | array     |
| `Dct`      | object (keys converted to strings) |
| Variant    | `{"__variant__": name, "fields": [...]}` |
| Other      | string (via `str()`) |

### Deserialization

```
from_json("[1, 2, 3]")               # [1, 2, 3]
from_json('{"x": null}')             # ["x": und]
```

`from_json(s)` parses a JSON string. `null` becomes `und`; arrays become lists; objects become dicts. Numbers and strings map directly.

---

## 37w. Actors -- `actor`

### Construction

```
a = actor(f(msg) -> msg * 2)
```

`actor(handler_fn)` creates a message-processing actor that runs in a background thread. The actor processes messages one at a time by calling `handler_fn(msg)` for each message.

### Methods

| Method | Description |
| ------ | ----------- |
| `.send(msg)` | Send a message and block until the handler returns. Returns the handler's result. If the handler raises, the exception propagates to the caller. |
| `.send_async(msg)` | Send a message without waiting for a result. Returns `und` immediately. |
| `.stop()` | Stop the actor's processing loop. The background thread exits after the current message (if any). |

### Example

```
df counter_handler(msg) {
  if msg == "inc" { counter = counter + 1 }
  elif msg == "get" { r counter }
}

counter = 0
c = actor(counter_handler)
c.send("inc")
c.send("inc")
p(c.send("get"))                 # 2
c.stop()
```

**Implementation:** Each actor wraps a `SnafuObj` with `type_name="Actor"`. Internally, a Python `threading.Thread` runs a loop that reads from a message queue. `.send()` puts a message on the queue and waits on a result queue for the handler's return value. `.send_async()` puts a message on the queue without waiting. `.stop()` sends a sentinel to break the processing loop.

---

## End of spec v1.5
