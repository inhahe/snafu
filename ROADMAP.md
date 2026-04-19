# Snafu Roadmap — Post-Feature-Complete

The language is feature-complete (443 tests, 7160 lines, ~165 features).
These are the next major workstreams.

---

## 1. Example Programs

Write 6-8 substantial programs that exercise features in combination.

### Planned examples:

1. **`examples/calculator.snf`** — Interactive calculator with variables, history, and undo (uses: REPL loop, eval, pattern matching, state time-travel)

2. **`examples/todo_app.snf`** — Persistent todo list with add/remove/list/save/load (uses: persistent vars `pv`, file I/O, pattern matching, string methods)

3. **`examples/minigrep.snf`** — Simple grep clone: search files with regex (uses: regex `=~`, file I/O, pipeline, command-line args via `os.args`)

4. **`examples/json_transform.snf`** — Read JSON, transform with pipelines, write back (uses: `from_json`/`to_json`, pipeline, comprehensions, where-clauses)

5. **`examples/parallel_primes.snf`** — Find primes via trial division using universe forking for parallelism (uses: `fk_map`, ranges, comprehensions, APL reduce)

6. **`examples/actor_chat.snf`** — Multi-actor chat simulation: actors send messages, process them serially (uses: actors, channels, green threads, pattern matching on messages)

7. **`examples/lisp.snf`** — A tiny Lisp interpreter written in Snafu (uses: sum types for AST, pattern matching, eval, recursion, closures — also serves as warm-up for task 7)

8. **`examples/effects_demo.snf`** — Demo of algebraic effects: logging effect, state effect, nondeterministic choice with multi-shot continuations (uses: ef/pf/hd, resumable k)

---

## 2. Stress Testing

Write adversarial programs that push edge cases.

### Test categories:

1. **Deep recursion** — verify implicit TCO handles 100K+ depth
2. **Concurrent stress** — 50+ green threads writing to shared channels
3. **Fork bomb** — nested `fk()` calls, verify cleanup
4. **Scope chain depth** — 1000+ nested scopes
5. **Large collections** — million-element lists, APL ops on them
6. **Regex edge cases** — catastrophic backtracking, empty matches, unicode
7. **Self-modification** — AST surgery mid-execution
8. **Effect handler nesting** — 5+ levels of `hd` with different effects
9. **Reactive cascade** — `on` trigger that modifies another `on`-watched variable
10. **Memory pressure** — state recording with `auto_record(true)` + large data
11. **Type coercion chains** — multiple `cv` registrations, dispatch through coercion
12. **Macro self-reference** — macro that generates a macro

### Deliverable: `tests/stress_tests.py` — separate from the unit tests (may be slow).

---

## 3. Performance Profiling + Optimization

### Phase 1: Profile

1. Run the existing test suite under `cProfile`
2. Identify the top 10 hottest functions
3. Measure: tokens/sec, AST-nodes/sec, function-calls/sec
4. Benchmark against Python on equivalent programs (Fibonacci, list manipulation)

### Phase 2: Optimize the Python interpreter

Likely hot spots and fixes:
- **Scope.lookup** — walks parent chain on every name access. Fix: flatten common names into a fast dict; cache lookups.
- **apply_binop** — giant if/elif chain. Fix: dispatch table (dict of op → function).
- **eval_node** — `getattr(self, f"eval_{type(node).__name__}")` on every node. Fix: build a dispatch dict at init.
- **_call_value** — trampoline loop. Fix: inline common cases (plain Python callable).
- **Lexer** — OPERATORS sorted list scanned linearly. Fix: trie or hash-based lookup.
- **String interpolation** — re-lexes/re-parses on every string. Fix: compile interpolations at parse time.

### Phase 3: Benchmark again, measure speedup.

---

## 4. README — User-Facing Documentation

### `README.md` in project root. Sections:

1. **What is Snafu?** — one-paragraph pitch
2. **Quick start** — install (just Python 3.11+), run REPL, run a file
3. **Language tour** — 20 small examples covering the major features:
   - Variables, arithmetic, strings
   - Control flow (if/for/mt)
   - Functions and lambdas (df/f/backtick)
   - Collections and pipelines
   - Sum types and pattern matching
   - Generators
   - Error handling
   - OOP with prototypes
   - APL-style array ops
   - Code golf features
4. **Full feature list** — link to SPEC.md
5. **Examples** — links to the example programs
6. **Golf syntax cheat sheet** — link to GOLF_SYNTAX.md
7. **Architecture** — brief overview of snafu.py's structure

---

## 7. Self-Interpreter in Snafu

Write a Snafu interpreter IN Snafu. This becomes the content of `isrc[1]` when
the user sets `lv 2`.

### Approach:

The self-interpreter needs to:
1. **Parse** Snafu source into an AST (or reuse `ast_of` / the host parser)
2. **Evaluate** AST nodes by pattern-matching on node types
3. **Manage scope** (dict with parent pointer)
4. **Handle** all major expression/statement forms

### Simplification: use the host parser

Since `ast_of(expr)` already gives us the AST, the self-interpreter only needs
to be an **evaluator**, not a parser. It receives AST nodes and pattern-matches:

```
df snafu_eval(node, scope) {
    mt type(node) {
        "AST:NumLit"   -> node.value
        "AST:StrLit"   -> node.pieces  # simplified
        "AST:BinOp"    -> apply_op(node.op, snafu_eval(node.lhs, scope), snafu_eval(node.rhs, scope))
        "AST:Ident"    -> scope_lookup(scope, node.name)
        "AST:Call"      -> ...
        "AST:If"        -> ...
        _               -> eval_ast(node)  # fallback to host for unimplemented forms
    }
}
```

### Deliverable: `examples/self_interp.snf` — a working (subset) Snafu interpreter.

Then wire it into `isrc[1]` so `lv 2` uses it.

---

## 8. Bytecode Compiler + VM

Compile Snafu to bytecode and run on a stack-based VM for 10-50x speedup.

### Architecture:

```
Source → Lexer → Parser → AST → Compiler → Bytecode → VM
                                                ↓
                                          Python C extension (optional)
```

### Phase 1: Bytecode design

Opcodes (stack-based, like CPython):
```
LOAD_CONST n        push constants[n]
LOAD_NAME n         push from scope by name index
STORE_NAME n        pop and store in scope
LOAD_ATTR n         pop obj, push obj.attr[n]
STORE_ATTR n        pop val, pop obj, obj.attr[n] = val

BINARY_ADD          pop 2, push sum
BINARY_SUB          pop 2, push diff
BINARY_MUL          ...
COMPARE_EQ          ...

CALL_FUNCTION n     pop n args + fn, call, push result
MAKE_FUNCTION       pop body bytecode + defaults, push fn
RETURN_VALUE        pop and return

JUMP_ABSOLUTE n     IP = n
JUMP_IF_FALSE n     pop, if falsy jump to n
POP_JUMP_IF_TRUE n

BUILD_LIST n        pop n items, push list
BUILD_DICT n        pop n key-value pairs, push dict

SETUP_TRY n         push exception handler at offset n
POP_TRY             remove handler
RAISE               pop exception, raise
```

### Phase 2: Compiler

Walk the AST, emit bytecode. One function = one code object (bytecode + constants + names).

### Phase 3: VM

Python-implemented VM (stack machine). Later: rewrite in C for true speed.

### Python module bridge

The VM calls Python modules via a `CALL_PYTHON` opcode or by wrapping Python
callables as Snafu functions (same as current interpreter).

### Deliverable: `snafu_vm.py` — compiler + VM. Falls back to tree-walker for uncompiled features.

### Expected speedup: 5-20x over tree-walking (based on CPython vs. AST-interpreter benchmarks).

---

## Execution order

1. **README** (quick — 1 pass)
2. **Example programs** (parallel with README)
3. **Stress tests** (after examples, to exercise the features)
4. **Performance profiling** (after stress tests identify hot paths)
5. **Python interpreter optimization** (after profiling)
6. **Self-interpreter** (after optimization — needs a fast host)
7. **Bytecode VM** (last — biggest effort, builds on everything else)

---

## Status tracking

- [x] README.md (424 lines)
- [x] 13 example programs (1230 lines, incl. Lisp interpreter + self-interpreter)
- [x] Stress test suite (34 tests, all passing)
- [x] Performance profiling (5 benchmarks + cProfile)
- [x] Python interpreter optimization (8 opts, 1.6x speedup)
- [x] Self-interpreter in Snafu (217 lines, fib/fact/closures working)
- [x] Bytecode compiler + VM (1145 lines, 3.1x speedup on fib(30))
- [x] Meta-interpreter bug fix (re-entry prevention + scope-aware eval_ast)

## Phase 2 — In progress

### 2a. C++ Interpreter — Full Coverage (`snafu_c/`)
**Ultimate goal: the C++ interpreter must cover ALL ~165 features.**

Currently a C implementation (2480 lines) covering the core subset. Plan to
rewrite in C++ for full coverage — C++ gives us `std::vector`, `std::string`,
`std::unordered_map`, `std::variant`, `std::shared_ptr` (for GC), lambdas,
and exceptions, which dramatically simplify implementing the full language.

**Phase 1 (DONE):** C core subset — 2480 lines, 20x speedup on fib(30).
Covers: int/float, strings, lists, dicts, if/for/while/loop, functions,
closures, recursion, TCO, break/continue, basic prelude.

**Phase 2 (TODO):** Rewrite as C++ and add:
- `std::vector<Value>` for lists (replaces manual dynamic arrays)
- `std::unordered_map<std::string, Value>` for dicts and scopes
- `std::shared_ptr<Value>` for reference-counted GC
- Pattern matching (all 10 pattern types)
- Sum types + variant constructors
- Regex via `<regex>` header
- Pipeline, APL ops, string interpolation
- Generators (C++20 coroutines or thread-based)
- Green threads + channels
- Algebraic effects (exception-based continuations)
- Macros, self-modification, state time-travel
- Universe forking, reactive triggers, actors
- All remaining features

**Phase 3 (TODO):** Python bridge via embedded CPython (`Python.h`) so
`py.import("math")` works from C++ via `PyImport_ImportModule`.

**Phase 4 (TODO):** Bytecode compiler in C++ for another 5-10x speedup.

**Performance targets:**
- Phase 1 (done): fib(30) in 1.4s (20x vs Python tree-walker)
- Phase 2: fib(30) in <1s, full language coverage
- Phase 4: fib(30) in <0.1s (bytecode VM in C++)

### 2b. Self-Interpreter — Full Coverage (`examples/self_interp.snf`)
**Ultimate goal: the self-interpreter must cover ALL ~165 features.**
No `eval_ast` fallback — every AST node type handled in pure Snafu.

**Phase 1 (DONE):** 27 node types — core + functional + control flow.
Covers: NumLit, StrLit, BoolLit, UndLit, OoLit, Ident, BinOp (20+ ops),
UnaryOp, Call, ExprStmt, Block, Assign (incl. destructuring + attr + index),
If/elif/else, For, While/Until, Loop, FnDecl/Lambda, Return, Break/Continue,
Match (4 pattern types), SumDecl, Try/Except, ListExpr, Index, Attr,
Ternary, Pipe, ListComp, Where, Quantifier, Defer, With, Decorators.

**Phase 2 (DONE):** All remaining node types added — 75 match arms, 34 demos.
- Generators: CoroutineDecl, Yield (requires coroutine state machine in Snafu)
- Algebraic effects: EffectDecl, Perform, Handle, HandleCase (requires continuation capture)
- Goto/comefrom/resume: Label, Goto, ComeFrom, Resume, JumpAbs, JumpRel
- Macros: MacroDecl (AST transformation in Snafu)
- Self-modification: access to isrc/iast from within the self-interpreter
- Reactive: On, Off, CondTrigger (requires scope hooks)
- Concurrency: GreenThread, Await, ExecSet, Fork (requires threading primitives)
- Queries: Query (filter/map/sort chain)
- Stack mode: StkBlock (Forth evaluator in Snafu)
- Logic: LogicVar, unification
- Misc: Slice, SafeNav, VarVar, FnPower, RegexLit, DynScope, DoSync,
  PersistVar, Record, StrictBlock, LooseBlock, Raise (with fr chaining)

**Phase 3 (TODO):** Wire the complete self-interpreter into `isrc[1]` so that
`lv 2` uses a fully Snafu-native interpreter. At that point, modifying `isrc[1]`
genuinely modifies how every language feature works — the ultimate meta-circular goal.

### 2c. Completed in this phase
- [x] Documentation site (`docs/` — 1422 lines HTML+CSS, tour, reference, packages)
- [x] Library modules (`lib/` — math_utils.snf, string_utils.snf)
- [x] Standard library expansion (HTTP, filesystem, datetime, hashing, env, URL)
- [x] Self-interpreter wired into `isrc[1]` (Phase 3 complete)
- [x] C++ interpreter expanded (5495 lines — macros, time-travel, forking, reactive, actors, comprehensions, where, defer, quantifiers, 15 prelude fns)

### 2d. Completed
- [x] C++ Phase 4: Bytecode compiler + VM (920 lines, fib(30) in 0.74s = 38x vs Python)
- [x] Lint/check tool (`snafu_lsp.py` — 424 lines, unused vars, undefined refs, shadowing)

### 2e. Completed
- [x] Package manager (`snafu_pkg.py` — init/create/publish/install/list/search/remove)
- [x] Web playground (`playground/index.html` — Pyodide-based, runs in browser, 8 examples, share-via-URL)

### 2f. Completed
- [x] C++ Phase 3: Python bridge via embedded CPython (`py.import("math").sqrt(16)` works from C++)
