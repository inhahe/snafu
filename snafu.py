#!/usr/bin/env python3
"""
Snafu language interpreter v0.1

Implements the core subset of SPEC.md:
  - Numbers (Int, Flt, Rat), Str, Bool, Und, Lst, Dct, Fn, user prototypes
  - Arithmetic, comparison, boolean, pipeline operators
  - Control flow: if/eli/el, mt, for/in, wh, un, lp, br/cn, r
  - Functions: df named, f anonymous, closures, *args/**kwargs, defaults
  - Pattern matching with literal/var/wild/list/dict/variant/guard/or patterns
  - Sum types (sm), basic protocols (pr/im), prototypes + new()
  - Exceptions: ty/ex/fi, rs, fr
  - Pipeline |> and composition +
  - Strings with ${expr} interpolation
  - Collections: unified [...] for list/dict/mixed
  - Basic prelude: p, m, fl, rdc, srt, len, range, etc.

Deferred (raise NotImplemented at runtime or parse-reject):
  - Algebraic effects (pf/hd) — uses Python exceptions internally instead
  - Self-modification (src/ast/isrc/iast/lv>1)
  - State time-travel (ps/sa/sp)
  - Concurrency (gt/aw/ch/sl/atom/ref/agent)
  - Reactive (on/of)
  - Macros (mc)
  - Variable-variables ($)
  - Regex literals and Perl operators
  - Lenses
  - Tail-call optimization
  - Python module interop
  - Heredocs / nowdocs
  - Complex / quaternion numbers
  - Debugging (db, bp)

Usage:
    python snafu.py <file.snf>
    python snafu.py -e "expr"
    python snafu.py          # REPL
"""

from __future__ import annotations
import sys, re, math, operator, traceback, threading, queue as _queue_mod, random, time, types, itertools, pickle, json, subprocess, importlib
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional, List, Dict, Tuple, Callable, Union


# =============================================================================
#  SENTINELS AND VALUES
# =============================================================================

class UndType:
    """The singleton undefined value."""
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __repr__(self): return "und"
    def __str__(self):  return "und"
    def __bool__(self): return False
    def __eq__(self, other): return isinstance(other, UndType)
    def __hash__(self):  return hash("und__singleton")

UND = UndType()


class StopItor(Exception):
    """End-of-iteration effect (represented as Python exception)."""
    pass


# ---------- Generator support (via threading) ----------

_YIELD_SENTINEL = object()

class SnafuGenerator:
    """Generator object: coroutine body runs in a thread, yields via queue."""
    def __init__(self, body_fn):
        self._q = _queue_mod.Queue()
        self._send_q = _queue_mod.Queue()
        self._body_fn = body_fn
        self._started = False
        self._done = False
        self._needs_resume = False  # True after first yield has been read

    def _ensure_started(self):
        if not self._started:
            self._started = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self):
        try:
            self._body_fn(self._q, self._send_q)
        except Exception as e:
            self._run_exc = e
        else:
            self._run_exc = None
        finally:
            self._q.put(_YIELD_SENTINEL)

    def __iter__(self):
        self._ensure_started()
        return self

    def __next__(self):
        self._ensure_started()
        # If generator is waiting for resume (from a previous yield), send UND
        if self._needs_resume:
            self._send_q.put(UND)
        val = self._q.get()
        if val is _YIELD_SENTINEL:
            self._done = True
            raise StopIteration
        self._needs_resume = True
        return val

    def sd(self, sent_val):
        """Send a value into the generator and get next yielded value."""
        self._ensure_started()
        # Resume coroutine with the sent value
        self._send_q.put(sent_val)
        # Get next yielded value
        val = self._q.get()
        if val is _YIELD_SENTINEL:
            self._done = True
            raise StopIteration
        self._needs_resume = True
        return val


class SnafuError(Exception):
    """Root of Snafu-user-visible exceptions."""
    def __init__(self, msg="", cause=None):
        super().__init__(msg)
        self.msg = msg
        self.cause = cause
        self.tb_frames = []

class ArgErr(SnafuError):      pass
class TypeErr(SnafuError):     pass
class ValErr(SnafuError):      pass
class NameErr(SnafuError):     pass
class AttrErr(SnafuError):     pass
class IxErr(SnafuError):       pass
class KeyErr(SnafuError):      pass
class DivErr(SnafuError):      pass
class UndErr(SnafuError):      pass
class MatchErr(SnafuError):    pass
class IOErr(SnafuError):       pass
class ParseErr(SnafuError):    pass
class DispatchAmbig(SnafuError): pass
class BindErr(SnafuError):     pass
class InterpErr(SnafuError):   pass
class ContractErr(SnafuError): pass

# Control-flow exceptions (not user-visible)
class _Return(Exception):
    def __init__(self, value): self.value = value
class _Break(Exception):
    def __init__(self, level=1): self.level = level
class _Continue(Exception):
    def __init__(self, level=1, advance=1): self.level = level; self.advance = advance
class _GotoSignal(Exception):
    def __init__(self, label): self.label = label
class _ResumeSignal(Exception):
    pass

class _ForkSignal(Exception):
    """Raised by fk() (no body) to tell eval_block to clone & branch."""
    pass

class _JumpIndexSignal(Exception):
    """Raised by ja/jr to jump to an absolute or relative statement index."""
    def __init__(self, index, relative=False):
        self.index = index
        self.relative = relative

class _EffectSignal(Exception):
    """Raised by pf (perform) to signal an algebraic effect."""
    def __init__(self, effect_value, continuation=None):
        self.effect_value = effect_value
        self.continuation = continuation


# ---- Tail-call optimization sentinel (not an exception) ----
class _TailCall:
    """Sentinel returned by tail() to signal the trampoline in _call_value."""
    __slots__ = ('fn', 'args', 'kwargs')
    def __init__(self, fn, args, kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs


# ---- Implicit tail-call exception (for implicit TCO) ----
class _TailCallExc(Exception):
    """Raised by eval_Call for implicit tail calls; caught by function trampoline."""
    __slots__ = ('fn', 'args', 'kwargs')
    def __init__(self, fn, args, kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs


# ---- Symbolic expression (lazy numeric tree) ----
class SymExpr:
    """A symbolic numeric expression -- evaluated lazily."""
    __slots__ = ('op', 'args', '_cached')
    _SYM_OPS = {
        'add': '+', 'sub': '-', 'mul': '*', 'div': '/', 'pow': '**',
    }
    def __init__(self, op, args):
        self.op = op       # 'add', 'mul', 'sub', 'div', 'pow', 'lit', 'var'
        self.args = args
        self._cached = None
    def evaluate(self):
        if self._cached is not None:
            return self._cached
        if self.op == 'lit':
            self._cached = self.args[0]
            return self._cached
        vals = [a.evaluate() if isinstance(a, SymExpr) else a for a in self.args]
        if self.op == 'add':   self._cached = vals[0] + vals[1]
        elif self.op == 'sub': self._cached = vals[0] - vals[1]
        elif self.op == 'mul': self._cached = vals[0] * vals[1]
        elif self.op == 'div':
            if vals[1] == 0: raise DivErr("division by zero in sym")
            self._cached = vals[0] / vals[1]
        elif self.op == 'pow': self._cached = vals[0] ** vals[1]
        elif self.op == 'neg': self._cached = -vals[0]
        elif self.op == 'mod': self._cached = vals[0] % vals[1]
        else: self._cached = vals[0] if vals else 0
        return self._cached
    def __repr__(self):
        if self.op == 'lit':
            return f"sym({self.args[0]})"
        sym = self._SYM_OPS.get(self.op, self.op)
        if len(self.args) == 1:
            return f"({sym}{self.args[0]})"
        return f"({self.args[0]} {sym} {self.args[1]})"
    def __add__(self, other):  return SymExpr('add', [self, other])
    def __radd__(self, other): return SymExpr('add', [other, self])
    def __sub__(self, other):  return SymExpr('sub', [self, other])
    def __rsub__(self, other): return SymExpr('sub', [other, self])
    def __mul__(self, other):  return SymExpr('mul', [self, other])
    def __rmul__(self, other): return SymExpr('mul', [other, self])
    def __truediv__(self, other): return SymExpr('div', [self, other])
    def __rtruediv__(self, other): return SymExpr('div', [other, self])
    def __pow__(self, other):  return SymExpr('pow', [self, other])
    def __rpow__(self, other): return SymExpr('pow', [other, self])
    def __neg__(self):         return SymExpr('neg', [self])
    def __mod__(self, other):  return SymExpr('mod', [self, other])
    def __rmod__(self, other): return SymExpr('mod', [other, self])
    def __eq__(self, other):
        if isinstance(other, SymExpr):
            return self.evaluate() == other.evaluate()
        return self.evaluate() == other
    def __lt__(self, other):
        if isinstance(other, SymExpr): return self.evaluate() < other.evaluate()
        return self.evaluate() < other
    def __le__(self, other):
        if isinstance(other, SymExpr): return self.evaluate() <= other.evaluate()
        return self.evaluate() <= other
    def __gt__(self, other):
        if isinstance(other, SymExpr): return self.evaluate() > other.evaluate()
        return self.evaluate() > other
    def __ge__(self, other):
        if isinstance(other, SymExpr): return self.evaluate() >= other.evaluate()
        return self.evaluate() >= other
    def __hash__(self): return hash(self.evaluate())
    def __bool__(self): return bool(self.evaluate())
    def __int__(self): return int(self.evaluate())
    def __float__(self): return float(self.evaluate())


# ---- Alias binding sentinel ----
class _Alias:
    """Reference to another scope+name pair, for := alias bindings."""
    __slots__ = ('scope', 'name')
    def __init__(self, scope, name):
        self.scope = scope
        self.name = name


# ---- Lazy thunk for lazy/force ----
class LazyThunk:
    """A lazy value that evaluates its thunk on first force(), then caches."""
    __slots__ = ('fn', 'value', 'evaluated')
    def __init__(self, fn):
        self.fn = fn
        self.value = UND
        self.evaluated = False
    def force(self):
        if not self.evaluated:
            self.value = _call_value(self.fn, [], {})
            self.evaluated = True
        return self.value


# ---- Tracking binding sentinel ----
class _Tracking:
    """Lazy expression that re-evaluates on every read, for ~= bindings."""
    __slots__ = ('expr_node', 'scope', 'interp')
    def __init__(self, expr_node, scope, interp):
        self.expr_node = expr_node
        self.scope = scope
        self.interp = interp


class _MethodMissingProxy:
    """Proxy returned by method-missing: behaves as a value (mm(name)) and as a callable (mm(name, *args))."""
    __slots__ = ('_mm_fn', '_name', '_resolved')
    def __init__(self, mm_fn, name):
        self._mm_fn = mm_fn
        self._name = name
        self._resolved = None  # lazy: computed on first non-call use
    def __call__(self, *args, **kwargs):
        return _call_value(self._mm_fn, [self._name] + list(args), kwargs)
    def _resolve(self):
        if self._resolved is None:
            self._resolved = _call_value(self._mm_fn, [self._name], {})
        return self._resolved
    def __str__(self):
        return str(self._resolve())
    def __repr__(self):
        return repr(self._resolve())
    def __eq__(self, other):
        r = self._resolve()
        if isinstance(other, _MethodMissingProxy):
            return r == other._resolve()
        return r == other
    def __hash__(self):
        return hash(self._resolve())
    def __bool__(self):
        return bool(self._resolve())
    def __add__(self, other):
        return self._resolve() + (other._resolve() if isinstance(other, _MethodMissingProxy) else other)
    def __radd__(self, other):
        return other + self._resolve()


class Symbol:
    """A named symbol — used for sum-type variants, protocol tags, etc."""
    __slots__ = ("name",)
    def __init__(self, name): self.name = name
    def __repr__(self): return f":{self.name}"
    def __eq__(self, o): return isinstance(o, Symbol) and self.name == o.name
    def __hash__(self): return hash(("sym", self.name))


class LogicVar:
    """A logic variable for unification."""
    __slots__ = ('name', 'value', 'bound')
    def __init__(self, name=None):
        self.name = name or f"_lv{id(self)}"
        self.value = UND
        self.bound = False
    def bind(self, val):
        self.value = val
        self.bound = True
    def deref(self):
        if self.bound:
            if isinstance(self.value, LogicVar):
                return self.value.deref()
            return self.value
        return self
    def __repr__(self):
        if self.bound:
            return f"<lv {self.name}={self.deref()!r}>"
        return f"<lv {self.name} (unbound)>"


class SnafuObj:
    """A generic runtime object with a prototype chain and own-attrs dict."""
    __slots__ = ("parents", "attrs", "type_name")
    def __init__(self, parents=(), attrs=None, type_name=None):
        self.parents = tuple(parents)
        self.attrs = attrs if attrs is not None else {}
        self.type_name = type_name
    def __repr__(self):
        if self.type_name: return f"<{self.type_name} {id(self):x}>"
        return f"<obj {id(self):x}>"


class SnafuMacro:
    """A macro: receives unevaluated AST nodes, returns a value to evaluate."""
    __slots__ = ("name", "fn")
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn
    def __repr__(self):
        return f"<macro {self.name}>"


class Variant:
    """A sum-type variant instance. Acts both as a value and as a type check."""
    __slots__ = ("sum_type", "name", "fields", "field_names")
    def __init__(self, sum_type, name, fields, field_names):
        self.sum_type = sum_type
        self.name = name
        self.fields = tuple(fields)
        self.field_names = tuple(field_names)
    def __repr__(self):
        if self.fields:
            return f"{self.name}({', '.join(snafu_repr(f) for f in self.fields)})"
        return self.name
    def __eq__(self, o):
        if not isinstance(o, Variant): return False
        return (self.sum_type is o.sum_type and self.name == o.name
                and self.fields == o.fields)
    def __hash__(self): return hash((self.sum_type, self.name, self.fields))


class VariantCtor:
    """The constructor/pattern-matcher for a variant — callable and introspectable."""
    __slots__ = ("sum_type", "name", "field_names")
    def __init__(self, sum_type, name, field_names):
        self.sum_type = sum_type
        self.name = name
        self.field_names = tuple(field_names)
    def __call__(self, *args):
        if len(args) != len(self.field_names):
            raise ArgErr(f"{self.name} expects {len(self.field_names)} args, got {len(args)}")
        return Variant(self.sum_type, self.name, args, self.field_names)
    def __repr__(self):
        return f"<variant-ctor {self.name}>"


class SumType:
    """A sum-type declaration (holds its variant names)."""
    __slots__ = ("name", "variant_names")
    def __init__(self, name, variant_names):
        self.name = name
        self.variant_names = tuple(variant_names)
    def __repr__(self):
        return f"<sum {self.name}>"


class Protocol:
    """A protocol with a set of required method names."""
    __slots__ = ("name", "methods", "parents")
    def __init__(self, name, methods, parents=()):
        self.name = name
        self.methods = set(methods)
        self.parents = tuple(parents)
    def __repr__(self):
        return f"<protocol {self.name}>"


# =============================================================================
#  MULTI-DISPATCH
# =============================================================================

# Module-level coercion registry for cv() — (from_type, to_type) -> fn
_COERCIONS = {}

class MultiDispatch:
    """A function name with multiple typed/patterned methods."""
    def __init__(self, name):
        self.name = name
        self.methods = []   # list of (param_types_tuple, fn)

    def register(self, param_types, fn):
        # param_types is a tuple of type-specs (str type name, None for wildcard, or a Variant-ctor name, or a value for value-match)
        self.methods.append((param_types, fn))

    def __call__(self, *args, **kwargs):
        candidates = []
        for ptypes, fn in self.methods:
            score = _match_score(ptypes, args)
            if score is not None:
                candidates.append((score, fn, ptypes))
        if not candidates:
            # Try coercions: for each method, check if args can be coerced to match
            for ptypes, fn in self.methods:
                coerced_args, score = _try_coerce(ptypes, args)
                if coerced_args is not None:
                    candidates.append((score, fn, ptypes, coerced_args))
            if not candidates:
                raise ArgErr(f"no dispatch match for {self.name}({', '.join(type_name(a) for a in args)})")
            # Pick best coerced match
            candidates.sort(key=lambda p: sum(p[0]), reverse=True)
            best = candidates[0]
            return best[1](*best[3], **kwargs)
        # Pick the most specific: highest score sum
        candidates.sort(key=lambda p: sum(p[0]), reverse=True)
        best_score = candidates[0][0]
        ties = [c for c in candidates if c[0] == best_score]
        if len(ties) > 1:
            raise DispatchAmbig(f"ambiguous dispatch for {self.name}: {len(ties)} methods tie")
        return candidates[0][1](*args, **kwargs)

    def __repr__(self):
        return f"<multi-dispatch {self.name} ({len(self.methods)} methods)>"


def _match_score(ptypes, args):
    """Return None if no match, else a tuple of scores per arg (higher = more specific)."""
    if len(ptypes) != len(args):
        # variadic not handled here — for v0.1, methods match exact arity
        return None
    scores = []
    for pt, arg in zip(ptypes, args):
        if pt is None:
            scores.append(0)            # wildcard
        elif isinstance(pt, str):
            # Type-name spec
            if _value_isa(arg, pt):
                scores.append(10 if type_name(arg) == pt else 5)
            else:
                return None
        else:
            # Value match (for pattern heads with concrete values)
            try:
                if arg == pt: scores.append(20)
                else: return None
            except Exception:
                return None
    return tuple(scores)


def _try_coerce(ptypes, args):
    """Try to coerce args to match ptypes using _COERCIONS. Returns (coerced_args, score) or (None, None)."""
    if len(ptypes) != len(args):
        return None, None
    new_args = list(args)
    scores = []
    for i, (pt, arg) in enumerate(zip(ptypes, args)):
        if pt is None:
            scores.append(0)
        elif isinstance(pt, str):
            if _value_isa(arg, pt):
                scores.append(10 if type_name(arg) == pt else 5)
            else:
                from_t = type_name(arg)
                coerce_fn = _COERCIONS.get((from_t, pt))
                if coerce_fn is not None:
                    try:
                        new_args[i] = _call_value(coerce_fn, [arg], {})
                        scores.append(1)  # lower priority than direct match
                    except Exception:
                        return None, None
                else:
                    return None, None
        else:
            try:
                if arg == pt:
                    scores.append(20)
                else:
                    return None, None
            except Exception:
                return None, None
    return new_args, tuple(scores)


def type_name(value):
    """Return the Snafu type-name of a value (string)."""
    if isinstance(value, _MethodMissingProxy): value = value._resolve()
    if value is UND: return "Und"
    if isinstance(value, bool): return "Bool"
    if isinstance(value, int): return "Int"
    if isinstance(value, complex): return "Cx"
    if isinstance(value, float): return "Flt"
    if isinstance(value, Fraction): return "Rat"
    if isinstance(value, str): return "Str"
    if isinstance(value, list): return "Lst"
    if isinstance(value, range): return "Range"
    if isinstance(value, tuple): return "FrozenLst"
    if isinstance(value, types.MappingProxyType): return "FrozenDct"
    if isinstance(value, dict): return "Dct"
    if isinstance(value, Variant): return value.name
    if isinstance(value, SumType): return "Sum"
    if isinstance(value, Protocol): return "Protocol"
    if isinstance(value, VariantCtor): return "VariantCtor"
    if isinstance(value, SnafuTransducer): return "Transducer"
    if isinstance(value, SnafuLens): return "Lens"
    if isinstance(value, (SnafuTraversal, ComposedTraversal)): return "Traversal"
    if isinstance(value, SnafuPrism): return "Prism"
    if isinstance(value, MultiDispatch): return "Fn"
    if isinstance(value, SnafuMacro): return "Macro"
    if isinstance(value, Node): return "AST:" + type(value).__name__
    if isinstance(value, LogicVar): return "LogicVar"
    if isinstance(value, LazyThunk): return "Lazy"
    if isinstance(value, SymExpr): return "Sym"
    if callable(value): return "Fn"
    if isinstance(value, SnafuObj): return value.type_name or "Obj"
    return "Obj"


def _value_isa(value, type_name_str):
    """Check if value matches a type name (including ancestor types)."""
    tn = type_name(value)
    if tn == type_name_str: return True
    # Num tower
    num_tower = {"Int": ["Num"], "Flt": ["Num"], "Rat": ["Num"], "Cx": ["Num"]}
    if type_name_str == "Num" and tn in ("Int", "Flt", "Rat", "Cx"): return True
    if type_name_str == "Obj": return True    # everything is-a Obj
    if type_name_str == "Iter":
        return tn in ("Lst", "Dct", "Str") or hasattr(value, "__iter__")
    # Variant isa sum type
    if isinstance(value, Variant) and type_name_str == value.sum_type.name:
        return True
    return False


def _format_complex(z):
    """Format complex as a+bi style."""
    r, i = z.real, z.imag
    if r == 0:
        if i == 1: return "1i"
        if i == -1: return "-1i"
        if i == int(i): return f"{int(i)}i"
        return f"{i}i"
    rp = int(r) if r == int(r) else r
    ip = abs(i)
    if ip == int(ip): ip = int(ip)
    sign = "+" if i >= 0 else "-"
    return f"{rp}{sign}{ip}i"


def snafu_repr(v):
    """Repr for display purposes."""
    if isinstance(v, _MethodMissingProxy): v = v._resolve()
    if v is UND: return "und"
    if v is True: return "true"
    if v is False: return "false"
    if isinstance(v, complex): return _format_complex(v)
    if isinstance(v, str): return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(v, Fraction): return f"{v.numerator}/{v.denominator}"
    if isinstance(v, list): return "[" + ", ".join(snafu_repr(x) for x in v) + "]"
    if isinstance(v, tuple): return "fr[" + ", ".join(snafu_repr(x) for x in v) + "]"
    if isinstance(v, range):
        if v.step == 1: return f"{v.start}..{v.stop}"
        return f"range({v.start}, {v.stop}, {v.step})"
    if isinstance(v, types.MappingProxyType):
        parts = [f"{snafu_repr(k)}: {snafu_repr(val)}" for k, val in v.items()]
        return "fr[" + ", ".join(parts) + "]"
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            parts.append(f"{snafu_repr(k)}: {snafu_repr(val)}")
        return "[" + ", ".join(parts) + "]"
    if isinstance(v, Node): return f"<ast:{type(v).__name__}>"
    return repr(v)


def _ast_to_source(node):
    """Convert an AST node to a source-like string representation (for macros)."""
    if isinstance(node, NumLit): return str(node.value)
    if isinstance(node, StrLit):
        parts = []
        for kind, v in node.pieces:
            if kind == 'str': parts.append(v)
            else: parts.append('${' + v + '}')
        return '"' + ''.join(parts) + '"'
    if isinstance(node, BoolLit): return "true" if node.value else "false"
    if isinstance(node, UndLit): return "und"
    if isinstance(node, Ident): return node.name
    if isinstance(node, BinOp): return f"({_ast_to_source(node.lhs)} {node.op} {_ast_to_source(node.rhs)})"
    if isinstance(node, UnaryOp): return f"({node.op}{_ast_to_source(node.operand)})"
    if isinstance(node, Call):
        fn = _ast_to_source(node.fn)
        args = ", ".join(_ast_to_source(a[1]) for a in node.args)
        return f"{fn}({args})"
    return repr(node)


def snafu_str(v):
    """str() for p() and interpolation."""
    if isinstance(v, _MethodMissingProxy): v = v._resolve()
    if v is UND: return "und"
    if v is True: return "true"
    if v is False: return "false"
    if isinstance(v, complex): return _format_complex(v)
    if isinstance(v, Fraction): return f"{v.numerator}/{v.denominator}"
    if isinstance(v, list): return "[" + ", ".join(snafu_str(x) for x in v) + "]"
    if isinstance(v, tuple): return "fr[" + ", ".join(snafu_str(x) for x in v) + "]"
    if isinstance(v, range):
        if v.step == 1: return f"{v.start}..{v.stop}"
        return f"range({v.start}, {v.stop}, {v.step})"
    if isinstance(v, types.MappingProxyType):
        parts = [f"{snafu_str(k)}: {snafu_str(val)}" for k, val in v.items()]
        return "fr[" + ", ".join(parts) + "]"
    if isinstance(v, dict):
        parts = [f"{snafu_str(k)}: {snafu_str(val)}" for k, val in v.items()]
        return "[" + ", ".join(parts) + "]"
    if isinstance(v, SymExpr): return repr(v)
    if isinstance(v, Node): return _ast_to_source(v)
    return str(v)


def truthy(v):
    """Snafu's truthiness rules."""
    if v is UND: return False
    if isinstance(v, bool): return v
    if isinstance(v, complex): return v != 0
    if isinstance(v, (int, float, Fraction)): return v != 0
    if isinstance(v, str): return len(v) > 0
    if isinstance(v, (list, dict, range, tuple, types.MappingProxyType)): return len(v) > 0
    return True


# =============================================================================
#  SCOPE
# =============================================================================

class Scope:
    """A scope with a dict of bindings and a parent pointer."""
    _dyn_stack = []  # class-level dynamic scope stack for dy { } blocks
    __slots__ = ("bindings", "parent", "name", "on_assign_hook", "_defers")
    def __init__(self, parent=None, name=None):
        self.bindings = {}
        self.parent = parent
        self.name = name
        self.on_assign_hook = None
        self._defers = []

    def lookup(self, key):
        s = self
        while s is not None:
            b = s.bindings
            if key in b:
                val = b[key]
                # Fast path: most values are not _Alias or _Tracking
                t = type(val)
                if t is _Alias:
                    return val.scope.lookup(val.name)
                if t is _Tracking:
                    return val.interp.eval_node(val.expr_node, val.scope)
                return val
            s = s.parent
        # Fallback: check dynamic scope stack (dy { } blocks)
        for dyn in reversed(Scope._dyn_stack):
            if key in dyn:
                return dyn[key]
        raise NameErr(f"name '{key}' not found")

    def lookup_or_und(self, key):
        try:
            return self.lookup(key)
        except NameErr:
            return UND

    def assign(self, key, value):
        """Assign to the existing binding if found in an ancestor; else create locally."""
        s = self
        while s is not None:
            if key in s.bindings:
                val = s.bindings[key]
                if isinstance(val, _Alias):
                    val.scope.assign(val.name, value)
                    return
                s.bindings[key] = value
                self._fire_assign_hook(key, value)
                return
            s = s.parent
        self.bindings[key] = value
        self._fire_assign_hook(key, value)

    def _fire_assign_hook(self, key, value):
        """Walk up scope chain looking for an on_assign_hook and call it."""
        s = self
        while s is not None:
            if s.on_assign_hook is not None:
                s.on_assign_hook(key, value)
                return
            s = s.parent

    def _find_binding_scope(self, key):
        """Find the scope that contains the binding for key. Returns (scope, raw_value) or (None, None)."""
        s = self
        while s is not None:
            if key in s.bindings:
                return s, s.bindings[key]
            s = s.parent
        return None, None

    def define_local(self, key, value):
        """Always create/overwrite in this scope."""
        self.bindings[key] = value

    def contains(self, key):
        s = self
        while s is not None:
            if key in s.bindings: return True
            s = s.parent
        return False

    def child(self, name=None):
        c = Scope.__new__(Scope)
        c.bindings = {}
        c.parent = self
        c.name = name
        c.on_assign_hook = None
        c._defers = []
        return c


# =============================================================================
#  TOKENIZER
# =============================================================================

# Keyword list from SPEC §2
# v0.1 keyword set.  Some keywords from SPEC are NOT reserved yet to avoid
# conflicts with common param/var names (yield=`y`, etc. — deferred to v0.2).
KEYWORDS = {
    'if', 'el', 'eli', 'mt', 'for', 'in', 'wh', 'un', 'lp',
    'bf', 'bt', 'af', 'br', 'cn', 'r', 'y', 'yf', 'ct',
    'ty', 'ex', 'fi', 'rs', 'fr', 'sd', 'ld',
    'df', 'f',
    'sm', 'pr', 'im', 'dv',
    'new', 'is', 'not', 'und', 'true', 'false', 'oo',
    'wi', 'as',
    'us', 'xp',
    'lbl', 'goto', 'jl', 'cf',
    'by',
    'gt', 'aw',
    'on', 'of',
    'rm',
    'ef', 'pf', 'hd', 'mc', 'sl', 'xs',
    'whr', 'qr', 'stk', 'sel', 'srt',
    'fk', 'req', 'ens', 'dy', 'rec',
    'dosync',
    'ja', 'jr', 'pc',
    'pv', 'some', 'every', 'defer',
}

# Operators, longest first so longer forms match before shorter prefixes.
OPERATORS = sorted([
    '|>>', '|?>', '|>', '..=', '..', '...',
    '!==', '===', '!==', '<>=', '>=', '<=', '!<', '!>',
    '->', '<-', '!->', '!<-',
    '**=', '//=', '>>=', '<<=',
    '+=', '-=', '*=', '/=', '%=',
    '&&=', '||=', '^^=', '!&&=', '!||=', '!^^=',
    '.=', ':=', '~=',
    '==', '<>', '<=', '>=',
    '**', '//', '<<', '>>',
    '&&', '||', '^^', '!&&', '!||', '!^^',
    '=~', '??', '?.', '`', '~/',
    '+', '-', '*', '/', '%',
    '=', '<', '>', '!', '~', '#', '@', '$', '?', ':', '.', '^',
    ',', ';',
    '(', ')', '[', ']', '{', '}',
    '&', '|', '\\',
    # Element-wise operators (op.)
    '+.', '-.', '*.', '/.', '**.', '//.', '%.', '==.', '<>.', '<.', '>.', '<=.', '>=.',
    '&&.', '||.', '^^.',
    # Outer product operators (op..)
    '+..', '-..', '*..', '**..', '/..', '%..', '==..', '<>..', '<..', '>..',
    # Reduce (op/) and scan (op\) operators
    '+/', '-/', '*/', '**/', '%/',
    '+\\', '-\\', '*\\', '**\\', '%\\',
], key=lambda s: (-len(s), s))


@dataclass
class Token:
    kind: str
    value: Any
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.kind}={self.value!r} @{self.line}:{self.col})"


class Lexer:
    def __init__(self, source, filename="<input>"):
        self.src = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens = []

    def error(self, msg):
        raise ParseErr(f"{self.filename}:{self.line}:{self.col}: {msg}")

    def peek(self, offset=0):
        p = self.pos + offset
        return self.src[p] if p < len(self.src) else ''

    def advance(self, n=1):
        for _ in range(n):
            if self.pos < len(self.src):
                c = self.src[self.pos]
                if c == '\n':
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.pos += 1

    def match_str(self, s):
        if self.src[self.pos:self.pos+len(s)] == s:
            return True
        return False

    def emit(self, kind, value):
        self.tokens.append(Token(kind, value, self.line, self.col))

    def tokenize(self):
        while self.pos < len(self.src):
            c = self.peek()

            # Skip whitespace (but track newlines)
            if c in ' \t\r':
                self.advance()
                continue
            if c == '\n':
                # Emit NEWLINE unless this is a statement continuation.
                # Two heuristics: (a) the previous token implies continuation;
                # (b) the NEXT non-whitespace char starts an infix-style operator.
                if self.tokens and self.tokens[-1].kind != 'NEWLINE' and \
                   not self._last_implies_continuation() and \
                   not self._next_implies_continuation():
                    self.emit('NEWLINE', '\n')
                self.advance()
                continue

            # Line comment
            if c == '#':
                # Check block comment: #{ ... }#
                if self.peek(1) == '{':
                    self._skip_block_comment()
                    continue
                # Line comment
                while self.pos < len(self.src) and self.peek() != '\n':
                    self.advance()
                continue

            # String literals
            if c == '"':
                self._lex_string_double()
                continue
            if c == "'":
                self._lex_string_single()
                continue

            # Number
            if c.isdigit():
                self._lex_number()
                continue

            # Identifier or keyword
            if c.isalpha() or c == '_':
                self._lex_ident()
                continue

            # Semicolon acts as statement separator (emit as NEWLINE)
            if c == ';':
                if self.tokens and self.tokens[-1].kind != 'NEWLINE':
                    self.emit('NEWLINE', ';')
                self.advance()
                continue

            # Operator or punctuation
            matched = False
            for op in OPERATORS:
                if self.match_str(op):
                    self.emit('OP', op)
                    self.advance(len(op))
                    matched = True
                    break
            if matched: continue

            self.error(f"unexpected character {c!r}")

        # Strip trailing NEWLINE tokens
        while self.tokens and self.tokens[-1].kind == 'NEWLINE':
            self.tokens.pop()
        self.emit('EOF', None)
        return self.tokens

    def _next_implies_continuation(self):
        """Peek ahead past whitespace; if next char starts an infix operator,
        suppress the newline so multi-line expressions work."""
        i = self.pos + 1   # past the \n
        while i < len(self.src) and self.src[i] in ' \t\r':
            i += 1
        if i >= len(self.src):
            return False
        # Check if the next token is an infix-style continuation
        rest = self.src[i:i+3]
        for op in ('|>>', '|>', '..=', '..', '->', '<-', '===', '!==', '==',
                   '<>', '<=', '>=', '!<', '!>', '&&', '||', '^^',
                   '+=', '-=', '*=', '/=', '%=', '**=', '//=',
                   '.=', ':=', '~=', '?', ':',
                   '+', '-', '*', '/', '%', '<', '>', ',', '.'):
            if rest.startswith(op):
                # But don't treat `-` as continuation if next looks like a separate stmt
                # (hard to tell without more context; be conservative)
                return True
        return False

    def _last_implies_continuation(self):
        if not self.tokens: return True
        last = self.tokens[-1]
        if last.kind == 'OP' and last.value in {
            '+', '-', '*', '/', '%', '**', '//',
            '==', '<>', '===', '!==', '<', '>', '<=', '>=', '!<', '!>',
            '&&', '||', '^^', '!&&', '!||', '!^^',
            '<-', '->', '!<-', '!->',
            '|>', '|>>',
            '=', ':=', '~=', '.=',
            '+=', '-=', '*=', '/=', '%=', '**=', '//=',
            '&&=', '||=', '^^=',
            '?', ':', ',', ';', '(', '[', '{', '..', '..=',
            '.', '=~',
            '+.', '-.', '*.', '/.', '**.', '//.', '%.',
            '==.', '<>.', '<.', '>.', '<=.', '>=.',
            '&&.', '||.', '^^.',
            '+..', '-..', '*..', '**..', '/..', '%..',
            '==..', '<>..', '<..', '>..',
        }:
            return True
        return False

    def _skip_block_comment(self):
        assert self.peek() == '#' and self.peek(1) == '{'
        self.advance(2)
        depth = 1
        while self.pos < len(self.src) and depth > 0:
            if self.match_str('#{'):
                depth += 1
                self.advance(2)
            elif self.match_str('}#'):
                depth -= 1
                self.advance(2)
            else:
                self.advance()
        if depth > 0:
            self.error("unterminated block comment")

    def _lex_string_double(self):
        start_line, start_col = self.line, self.col
        self.advance()  # consume "
        # Check triple
        if self.peek() == '"' and self.peek(1) == '"':
            self.advance(2)
            self._lex_triple_double(start_line, start_col)
            return
        pieces = []     # list of ('str', text) or ('interp', Node-source-str)
        buf = []
        while self.pos < len(self.src):
            c = self.peek()
            if c == '"':
                self.advance()
                if buf: pieces.append(('str', ''.join(buf)))
                self.tokens.append(Token('STRING', pieces, start_line, start_col))
                return
            if c == '\\':
                self.advance()
                esc = self.peek()
                self.advance()
                buf.append(self._unescape(esc))
            elif c == '$' and self.peek(1) == '{':
                if buf: pieces.append(('str', ''.join(buf))); buf = []
                self.advance(2)
                depth = 1
                start = self.pos
                while self.pos < len(self.src) and depth > 0:
                    ch = self.peek()
                    if ch == '{': depth += 1
                    elif ch == '}': depth -= 1
                    if depth == 0: break
                    self.advance()
                if depth != 0:
                    self.error("unterminated interpolation")
                inner = self.src[start:self.pos]
                self.advance()  # consume closing }
                pieces.append(('interp', inner))
            elif c == '\n':
                self.error("newline in single-line string (use triple-quoted for multiline)")
            else:
                buf.append(c)
                self.advance()
        self.error("unterminated string")

    def _lex_triple_double(self, start_line, start_col):
        pieces = []
        buf = []
        while self.pos < len(self.src):
            if self.match_str('"""'):
                self.advance(3)
                if buf: pieces.append(('str', ''.join(buf)))
                self.tokens.append(Token('STRING', pieces, start_line, start_col))
                return
            c = self.peek()
            if c == '\\':
                self.advance()
                esc = self.peek()
                self.advance()
                buf.append(self._unescape(esc))
            elif c == '$' and self.peek(1) == '{':
                if buf: pieces.append(('str', ''.join(buf))); buf = []
                self.advance(2)
                depth = 1
                start = self.pos
                while self.pos < len(self.src) and depth > 0:
                    ch = self.peek()
                    if ch == '{': depth += 1
                    elif ch == '}': depth -= 1
                    if depth == 0: break
                    self.advance()
                if depth != 0:
                    self.error("unterminated interpolation")
                inner = self.src[start:self.pos]
                self.advance()
                pieces.append(('interp', inner))
            else:
                buf.append(c)
                self.advance()
        self.error("unterminated triple-quoted string")

    def _lex_string_single(self):
        start_line, start_col = self.line, self.col
        self.advance()  # consume '
        if self.peek() == "'" and self.peek(1) == "'":
            # triple single — nowdoc-like (no interp)
            self.advance(2)
            buf = []
            while self.pos < len(self.src):
                if self.match_str("'''"):
                    self.advance(3)
                    self.tokens.append(Token('STRING', [('str', ''.join(buf))], start_line, start_col))
                    return
                c = self.peek()
                if c == '\\' and self.peek(1) in "'\\":
                    self.advance()
                    buf.append(self.peek())
                    self.advance()
                else:
                    buf.append(c)
                    self.advance()
            self.error("unterminated triple-single string")
        buf = []
        while self.pos < len(self.src):
            c = self.peek()
            if c == "'":
                self.advance()
                self.tokens.append(Token('STRING', [('str', ''.join(buf))], start_line, start_col))
                return
            if c == '\\' and self.peek(1) in "\\'":
                self.advance()
                buf.append(self.peek())
                self.advance()
            elif c == '\n':
                self.error("newline in single-line string")
            else:
                buf.append(c)
                self.advance()
        self.error("unterminated string")

    def _unescape(self, c):
        return {'n': '\n', 't': '\t', 'r': '\r', '0': '\0',
                '"': '"', "'": "'", '\\': '\\', '$': '$'}.get(c, c)

    def _lex_number(self):
        start_line, start_col = self.line, self.col
        start = self.pos
        # Scan digits + underscores
        while self.pos < len(self.src) and (self.peek().isdigit() or self.peek() == '_'):
            self.advance()
        # Check for base suffix or float
        nxt = self.peek()
        # Hex / bin / oct / base36 suffixes: letter [bhok] after digits
        # Lookahead: if next is letter/digit (for hex), consume more then check suffix
        # Simple approach: check for 'b' 'h' 'o' suffix immediately
        # For hex like 'ffh', the initial [0-9] wouldn't match — handle separately
        text = self.src[start:self.pos]

        if nxt == '.' and self.peek(1).isdigit():
            self.advance()  # consume .
            while self.pos < len(self.src) and (self.peek().isdigit() or self.peek() == '_'):
                self.advance()
            # exponent?
            if self.peek() and self.peek() in 'eE':
                self.advance()
                if self.peek() in '+-': self.advance()
                while self.pos < len(self.src) and self.peek().isdigit():
                    self.advance()
            text = self.src[start:self.pos]
            text_clean = text.replace('_', '')
            # Check for imaginary suffix 'i' (but not 'in', 'if', etc.)
            if self.peek() == 'i' and not (self.pos + 1 < len(self.src) and (self.src[self.pos + 1].isalnum() or self.src[self.pos + 1] == '_')):
                self.advance()  # consume 'i'
                self.tokens.append(Token('NUMBER', ('cx', complex(0, float(text_clean))), start_line, start_col))
                return
            self.tokens.append(Token('NUMBER', ('flt', float(text_clean)), start_line, start_col))
            return

        if nxt and nxt in 'eE':
            self.advance()
            if self.peek() in '+-': self.advance()
            while self.pos < len(self.src) and self.peek().isdigit():
                self.advance()
            text = self.src[start:self.pos]
            text_clean = text.replace('_', '')
            # Check for imaginary suffix 'i'
            if self.peek() == 'i' and not (self.pos + 1 < len(self.src) and (self.src[self.pos + 1].isalnum() or self.src[self.pos + 1] == '_')):
                self.advance()
                self.tokens.append(Token('NUMBER', ('cx', complex(0, float(text_clean))), start_line, start_col))
                return
            self.tokens.append(Token('NUMBER', ('flt', float(text_clean)), start_line, start_col))
            return

        # Base suffixes
        if nxt == 'b':
            self.advance()
            text_clean = text.replace('_', '')
            self.tokens.append(Token('NUMBER', ('int', int(text_clean, 2)), start_line, start_col))
            return
        if nxt == 'o':
            self.advance()
            text_clean = text.replace('_', '')
            self.tokens.append(Token('NUMBER', ('int', int(text_clean, 8)), start_line, start_col))
            return
        if nxt == 'h':
            # Actually hex can have letters; for now treat digit-only + h as hex
            self.advance()
            text_clean = text.replace('_', '')
            self.tokens.append(Token('NUMBER', ('int', int(text_clean, 16)), start_line, start_col))
            return

        text_clean = text.replace('_', '')
        # Check for imaginary suffix 'i' (but not 'in', 'if', identifier continuation)
        if self.peek() == 'i' and not (self.pos + 1 < len(self.src) and (self.src[self.pos + 1].isalnum() or self.src[self.pos + 1] == '_')):
            self.advance()  # consume 'i'
            self.tokens.append(Token('NUMBER', ('cx', complex(0, int(text_clean))), start_line, start_col))
            return
        self.tokens.append(Token('NUMBER', ('int', int(text_clean)), start_line, start_col))

    def _lex_ident(self):
        start_line, start_col = self.line, self.col
        start = self.pos
        while self.pos < len(self.src) and (self.peek().isalnum() or self.peek() == '_'):
            self.advance()
        name = self.src[start:self.pos]

        # Regex literal: r/pattern/flags
        if name == 'r' and self.pos < len(self.src) and self.peek() == '/':
            # Only treat as regex if previous token indicates expression start
            is_expr_start = True
            if self.tokens:
                prev = self.tokens[-1]
                if prev.kind in ('IDENT', 'NUMBER', 'STRING', 'REGEX'):
                    is_expr_start = False
                elif prev.kind == 'OP' and prev.value in (')', ']', '}'):
                    is_expr_start = False
                elif prev.kind == 'KW' and prev.value not in ('r', 'if', 'el', 'eli', 'for', 'in', 'wh', 'lp', 'mt', 'y', 'yf', 'rs', 'sd', 'ld', 'und', 'true', 'false', 'oo'):
                    is_expr_start = False
            if is_expr_start:
                self.advance()  # consume '/'
                pattern_chars = []
                while self.pos < len(self.src) and self.peek() != '/':
                    c = self.peek()
                    if c == '\\' and self.pos + 1 < len(self.src):
                        pattern_chars.append(c)
                        self.advance()
                        pattern_chars.append(self.peek())
                        self.advance()
                    else:
                        pattern_chars.append(c)
                        self.advance()
                if self.pos >= len(self.src):
                    self.error("unterminated regex literal")
                self.advance()  # consume closing '/'
                # Collect flags
                flags_chars = []
                while self.pos < len(self.src) and self.peek() in 'imsxgu':
                    flags_chars.append(self.peek())
                    self.advance()
                pattern = ''.join(pattern_chars)
                flags = ''.join(flags_chars)
                self.tokens.append(Token('REGEX', (pattern, flags), start_line, start_col))
                return

        # Hex-number disambiguation: "ffh" would be an identifier ending in 'h'
        # (after a non-digit start).  Check for hex literal:
        # Skip if the name is a keyword or a known prelude name to avoid misidentification.
        if (self.peek() == '' or not (self.peek().isalnum() or self.peek() == '_')) and \
           name.endswith('h') and len(name) > 1 and name not in KEYWORDS and \
           name not in ('ch', 'each') and \
           all(c in '0123456789abcdefABCDEF_' for c in name[:-1]):
            try:
                val = int(name[:-1].replace('_', ''), 16)
                self.tokens.append(Token('NUMBER', ('int', val), start_line, start_col))
                return
            except ValueError:
                pass

        if name in KEYWORDS:
            self.tokens.append(Token('KW', name, start_line, start_col))
        else:
            self.tokens.append(Token('IDENT', name, start_line, start_col))


# =============================================================================
#  AST
# =============================================================================

@dataclass
class Node:
    line: int = 0
    col: int = 0

# ---- literals / references ----
@dataclass
class NumLit(Node):       value: Any = None
@dataclass
class StrLit(Node):       pieces: list = field(default_factory=list)     # list of ('str', s) / ('interp', Node)
@dataclass
class BoolLit(Node):      value: bool = False
@dataclass
class UndLit(Node):       pass
@dataclass
class OoLit(Node):        pass
@dataclass
class Ident(Node):        name: str = ""
@dataclass
class Wildcard(Node):     pass

# ---- expressions ----
@dataclass
class BinOp(Node):        op: str = ""; lhs: Node = None; rhs: Node = None
@dataclass
class UnaryOp(Node):      op: str = ""; operand: Node = None
@dataclass
class Ternary(Node):      cond: Node = None; then: Node = None; else_: Node = None
@dataclass
class Call(Node):         fn: Node = None; args: list = field(default_factory=list); kwargs: dict = field(default_factory=dict)
@dataclass
class CallArg(Node):      kind: str = "pos"; value: Node = None; key: str = None   # kind: pos, star, dstar, kw
@dataclass
class Index(Node):        target: Node = None; key: Node = None
@dataclass
class Slice(Node):        target: Node = None; start: Node = None; end: Node = None; step: Node = None; win: Node = None; inc: Node = None
@dataclass
class Attr(Node):         target: Node = None; name: str = ""
@dataclass
class SafeNav(Node):      target: Node = None; name: str = ""
@dataclass
class Pipe(Node):         op: str = "|>"; lhs: Node = None; rhs: Node = None
@dataclass
class Lambda(Node):       params: list = field(default_factory=list); body: Node = None; implicit: bool = False
@dataclass
class ListExpr(Node):     items: list = field(default_factory=list)   # list of CollElem
@dataclass
class CollElem(Node):     kind: str = "pos"; key: Node = None; value: Node = None   # kind: pos, kv, spread
@dataclass
class BlockExpr(Node):    stmts: list = field(default_factory=list)
@dataclass
class Assign(Node):       target: Node = None; op: str = "="; value: Node = None
@dataclass
class ParamSpec(Node):    kind: str = "pos"; name: str = ""; default: Node = None; type_name: str = None

# ---- statements ----
@dataclass
class ExprStmt(Node):     expr: Node = None
@dataclass
class If(Node):           cond: Node = None; then: Node = None; elifs: list = field(default_factory=list); else_: Node = None
@dataclass
class For(Node):          pattern: Node = None; iter: Node = None; filter: Node = None; body: Node = None; loop_tail: dict = field(default_factory=dict)
@dataclass
class While(Node):        cond: Node = None; body: Node = None; is_until: bool = False; loop_tail: dict = field(default_factory=dict)
@dataclass
class Loop(Node):         count: Node = None; body: Node = None; loop_tail: dict = field(default_factory=dict)
@dataclass
class Match(Node):        target: Node = None; arms: list = field(default_factory=list)
@dataclass
class MatchArm(Node):     pattern: Node = None; guard: Node = None; body: Node = None
@dataclass
class Try(Node):          body: Node = None; excepts: list = field(default_factory=list); finally_: Node = None
@dataclass
class Except(Node):       type_name: str = None; var_name: str = None; body: Node = None
@dataclass
class Raise(Node):        exc: Node = None; cause: Node = None
@dataclass
class Return(Node):       value: Node = None
@dataclass
class Break(Node):        level: int = 1
@dataclass
class Continue(Node):     level: int = 1; advance: int = 1
@dataclass
class Yield(Node):        value: Node = None; is_from: bool = False
@dataclass
class Block(Node):        stmts: list = field(default_factory=list)
@dataclass
class StrictBlock(Node):  body: Node = None
@dataclass
class LooseBlock(Node):   body: Node = None
@dataclass
class With(Node):         bindings: list = field(default_factory=list); body: Node = None
@dataclass
class WithBinding(Node):  var: str = None; expr: Node = None
@dataclass
class Use(Node):          items: list = field(default_factory=list); body: Node = None
@dataclass
class UseItem(Node):      name: str = ""; alias: str = None; star: bool = False
@dataclass
class Export(Node):       names: list = field(default_factory=list)

# ---- green threads / channels ----
@dataclass
class GreenThread(Node):  body: Node = None
@dataclass
class Await(Node):        expr: Node = None

# ---- reactive on/of ----
@dataclass
class On(Node):           var_name: str = ""; body: Node = None
@dataclass
class Off(Node):          var_name: str = ""
@dataclass
class CondTrigger(Node):  cond: Node = None; body: Node = None

# ---- function power f^n ----
@dataclass
class FnPower(Node):      fn: Node = None; power: Node = None

# ---- sub (label range exec) ----
@dataclass
class Sub(Node):          start: Node = None; end: Node = None

# ---- resume ----
@dataclass
class Resume(Node):       pass

# ---- variable-variables ($) ----
@dataclass
class VarVar(Node):       expr: Node = None; levels: int = 1

# ---- frozen collections ----
@dataclass
class FrozenExpr(Node):   items: Node = None

# ---- regex ----
@dataclass
class RegexLit(Node):     pattern: str = ""; flags: str = ""

# ---- goto / comefrom ----
@dataclass
class Label(Node):        name: str = ""
@dataclass
class Goto(Node):         target: Node = None
@dataclass
class ComeFrom(Node):     label: str = ""

# ---- reduce / scan / outer product ----
@dataclass
class ReduceOp(Node):     op: str = ""; operand: Node = None
@dataclass
class ScanOp(Node):       op: str = ""; operand: Node = None
@dataclass
class RangeBy(Node):      start: Node = None; end: Node = None; step: Node = None; inclusive: bool = False

# ---- declarations ----
@dataclass
class FnDecl(Node):       name: str = ""; params: list = field(default_factory=list); body: Node = None; decorators: list = field(default_factory=list); precond: Node = None; postcond: Node = None
@dataclass
class CoroutineDecl(Node): name: str = ""; params: list = field(default_factory=list); body: Node = None; decorators: list = field(default_factory=list)
@dataclass
class SumDecl(Node):      name: str = ""; variants: list = field(default_factory=list); derivations: list = field(default_factory=list)
@dataclass
class VariantSpec(Node):  name: str = ""; fields: list = field(default_factory=list)
@dataclass
class ProtoDecl(Node):    name: str = ""; parents: list = field(default_factory=list); methods: list = field(default_factory=list)
@dataclass
class ProtoMethod(Node):  name: str = ""; params: list = field(default_factory=list); default_body: Node = None
@dataclass
class ImplDecl(Node):     proto_name: str = ""; type_name: str = ""; methods: list = field(default_factory=list)

# ---- patterns ----
@dataclass
class PatLit(Node):       value: Any = None
@dataclass
class PatVar(Node):       name: str = ""
@dataclass
class PatWild(Node):      pass
@dataclass
class PatAs(Node):        name: str = ""; pattern: Node = None
@dataclass
class PatList(Node):      elems: list = field(default_factory=list); rest: str = None   # rest is var name for ...rest
@dataclass
class PatDict(Node):      pairs: list = field(default_factory=list); rest: str = None
@dataclass
class PatPair(Node):      key: Any = None; pattern: Node = None
@dataclass
class PatVariant(Node):   name: str = ""; fields: list = field(default_factory=list)
@dataclass
class PatOr(Node):        alts: list = field(default_factory=list)
@dataclass
class PatGuard(Node):     pattern: Node = None; guard: Node = None

# ---- algebraic effects ----
@dataclass
class EffectDecl(Node):   name: str = ""; fields: list = field(default_factory=list)
@dataclass
class Perform(Node):      expr: Node = None
@dataclass
class Handle(Node):       body: Node = None; cases: list = field(default_factory=list)
@dataclass
class HandleCase(Node):   pattern: Node = None; cont_name: str = None; body: Node = None

# ---- macros ----
@dataclass
class MacroDecl(Node):    name: str = ""; params: list = field(default_factory=list); body: Node = None

# ---- execution sets ----
@dataclass
class ExecSet(Node):      stmts: list = field(default_factory=list)

# ---- select ----
@dataclass
class Select(Node):       channels: list = field(default_factory=list); timeout: Node = None

# ---- list comprehensions ----
@dataclass
class ListComp(Node):     expr: Node = None; clauses: list = field(default_factory=list)  # list of (pattern, iter_expr, guard_or_None)

# ---- where clauses ----
@dataclass
class Where(Node):        expr: Node = None; bindings: Node = None

# ---- query ----
@dataclass
class Query(Node):        source: Node = None; filter_expr: Node = None; select_expr: Node = None; sort_expr: Node = None

# ---- stack combinator ----
@dataclass
class StkBlock(Node):     body: Node = None

# ---- universe fork ----
@dataclass
class Fork(Node):         body: Node = None

# ---- dynamic scope ----
@dataclass
class DynScope(Node):     body: Node = None

# ---- execution recording ----
@dataclass
class Record(Node):       body: Node = None

# ---- interpreter level (multi-level meta-circular) ----
@dataclass
class LvDecl(Node):       level: Node = None

# ---- dosync (STM transaction block) ----
@dataclass
class DoSync(Node):       body: Node = None

# ---- N-dimensional IP jumps ----
@dataclass
class JumpAbs(Node):      coords: list = field(default_factory=list)
@dataclass
class JumpRel(Node):      offsets: list = field(default_factory=list)

# ---- persistent variables ----
@dataclass
class PersistVar(Node):   name: str = ""; init: Node = None

# ---- quantifiers ----
@dataclass
class Quantifier(Node):   kind: str = "some"; var: str = ""; iter: Node = None; pred: Node = None

# ---- defer ----
@dataclass
class Defer(Node):        expr: Node = None

# ---- AST type registry (for ast_new) ----
_AST_TYPES = {}
def _build_ast_types():
    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and issubclass(_obj, Node) and _obj is not Node:
            _AST_TYPES[_name] = _obj
_build_ast_types()


# =============================================================================
#  PARSER
# =============================================================================

class Parser:
    def __init__(self, tokens, filename="<input>"):
        self.tokens = tokens
        self.pos = 0
        self.filename = filename
        self._in_coroutine = False

    def error(self, msg):
        t = self.peek()
        raise ParseErr(f"{self.filename}:{t.line}:{t.col}: {msg} (at {t.kind} {t.value!r})")

    def peek(self, offset=0):
        p = self.pos + offset
        if p < len(self.tokens):
            return self.tokens[p]
        return self.tokens[-1]  # EOF

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def check(self, kind, value=None):
        t = self.peek()
        if t.kind != kind: return False
        if value is not None and t.value != value: return False
        return True

    def match(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind, value=None):
        if not self.check(kind, value):
            desc = f"{kind}" + (f" {value!r}" if value else "")
            self.error(f"expected {desc}")
        return self.advance()

    # "Soft" keyword names — legal as identifiers in name-only contexts
    # (attribute names, field names, param names where unambiguous).
    _SOFT_KW = {'r', 'f', 'y', 'yf', 'ct', 'as', 'ex', 'in', 'not', 'by', 'xs', 'pf', 'ef', 'hd', 'mc', 'sl', 'whr', 'qr', 'stk', 'sel', 'srt', 'fk', 'req', 'ens', 'dy', 'rec', 'ja', 'jr', 'pc', 'jl', 'pv', 'some', 'every', 'defer'}

    def expect_name(self, allow_all_kw=False):
        """Accept IDENT or a soft-keyword; return the name as string.
        If allow_all_kw, also accept hard keywords (used for attr access after .)."""
        t = self.peek()
        if t.kind == 'IDENT':
            return self.advance().value
        if t.kind == 'KW':
            if allow_all_kw or t.value in self._SOFT_KW:
                return self.advance().value
        self.error(f"expected identifier (at {t.kind} {t.value!r})")

    def skip_newlines(self):
        while self.check('NEWLINE'):
            self.advance()

    def at_end(self):
        return self.check('EOF')

    # --------------- entry point ---------------
    def parse_program(self):
        stmts = []
        self.skip_newlines()
        while not self.at_end():
            stmt = self.parse_stmt()
            if stmt is not None:
                stmts.append(stmt)
            self.skip_newlines()
        return Block(stmts=stmts)

    # --------------- statements ---------------
    def parse_stmt(self):
        t = self.peek()
        if t.kind == 'OP' and t.value == '@':
            return self.parse_decorated()
        if t.kind == 'KW':
            kw = t.value
            if kw == 'df':      return self.parse_fn_decl()
            if kw == 'ct':      return self.parse_coroutine_decl()
            # y / yf: only yield inside coroutine bodies, and NOT followed by assignment ops
            if kw == 'y' and self._in_coroutine and not (self.peek(1).kind == 'OP' and self.peek(1).value in ('=', '+=', '-=', '*=', '/=', '.=', ':=', '~=', '.', '?.', '(')):
                return self.parse_yield(is_from=False)
            if kw == 'yf' and self._in_coroutine:
                return self.parse_yield(is_from=True)
            if kw == 'sm':      return self.parse_sum_decl()
            if kw == 'pr':      return self.parse_proto_decl()
            if kw == 'im':      return self.parse_impl_decl()
            if kw == 'if':      return self.parse_if()
            if kw == 'for':     return self.parse_for()
            if kw == 'wh':      return self.parse_while(is_until=False)
            if kw == 'un':      return self.parse_while(is_until=True)
            if kw == 'lp':      return self.parse_loop()
            if kw == 'mt':      return self.parse_match_stmt()
            if kw == 'ty':      return self.parse_try()
            if kw == 'rs':      return self.parse_raise()
            # r = return, but `r = expr` is assignment to var named 'r'
            if kw == 'r' and not (self.peek(1).kind == 'OP' and self.peek(1).value in ('=', '+=', '-=', '*=', '/=', '.=', ':=', '~=', '.', '[')):
                return self.parse_return()
            if kw == 'br':      return self.parse_break()
            if kw == 'cn':      return self.parse_continue()
            if kw == 'sd':      return self.parse_strict_loose('sd')
            if kw == 'ld':      return self.parse_strict_loose('ld')
            if kw == 'wi':      return self.parse_with()
            if kw == 'us':      return self.parse_use()
            if kw == 'xp':      return self.parse_export()
            if kw == 'lbl':     return self.parse_label()
            if kw == 'goto':    return self.parse_goto()
            if kw == 'jl':      return self.parse_jl()
            if kw == 'cf':      return self.parse_comefrom()
            if kw == 'gt':      return self.parse_green_thread()
            if kw == 'aw':      return self.parse_await()
            if kw == 'on':      return self.parse_on()
            if kw == 'of':      return self.parse_off()
            if kw == 'rm':      return self.parse_resume()
            if kw == 'ef' and self.peek(1).kind == 'IDENT':
                return self.parse_effect_decl()
            if kw == 'pf' and not (self.peek(1).kind == 'OP' and self.peek(1).value in ('=', '+=', '-=', '*=', '/=', '.=', ':=', '~=')):
                return self.parse_perform()
            if kw == 'hd' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_handle()
            if kw == 'mc' and self.peek(1).kind in ('IDENT', 'KW'):
                return self.parse_macro_decl()
            if kw == 'xs' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_exec_set()
            if kw == 'qr':
                return self.parse_query()
            if kw == 'stk' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_stk_block()
            if kw == 'fk' and self.peek(1).kind == 'OP' and self.peek(1).value in ('{', '('):
                return self.parse_fork()
            if kw == 'dy' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_dyn_scope()
            if kw == 'rec' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_record()
            if kw == 'dosync' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_dosync()
            if kw == 'ja' and self.peek(1).kind == 'OP' and self.peek(1).value == '(':
                return self.parse_jump_abs()
            if kw == 'jr' and self.peek(1).kind == 'OP' and self.peek(1).value == '(':
                return self.parse_jump_rel()
            if kw == 'pv' and self.peek(1).kind in ('IDENT', 'KW'):
                return self.parse_persist_var()
            if kw == 'defer':
                return self.parse_defer()
            # y/yf handled above with guard conditions
            # Otherwise fall through to expression statement
        # Expression statement or assignment
        return self.parse_expr_or_assign_stmt()

    def parse_persist_var(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'pv')
        name = self.expect_name()
        self.expect('OP', '=')
        init = self.parse_expr()
        return PersistVar(line=line, col=col, name=name, init=init)

    def parse_defer(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'defer')
        expr = self.parse_expr()
        return Defer(line=line, col=col, expr=expr)

    def parse_expr_or_assign_stmt(self):
        line, col = self.peek().line, self.peek().col
        expr = self.parse_expr()
        # Check for assignment
        if self.check('OP'):
            op = self.peek().value
            assign_ops = {'=', '+=', '-=', '*=', '/=', '//=', '%=', '**=',
                          '&&=', '||=', '^^=', '.=', ':=', '~='}
            if op in assign_ops:
                self.advance()
                value = self.parse_expr()
                return Assign(line=line, col=col, target=expr, op=op, value=value)
        return ExprStmt(line=line, col=col, expr=expr)

    def parse_fn_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'df')
        name = self.expect_name()
        params = self.parse_params()
        precond = None
        postcond = None
        if self.check('KW') and self.peek().value == 'req':
            self.advance()
            precond = self.parse_expr()
        if self.check('KW') and self.peek().value == 'ens':
            self.advance()
            postcond = self.parse_expr()
        body = self.parse_fn_body()
        return FnDecl(line=line, col=col, name=name, params=params, body=body, precond=precond, postcond=postcond)

    def parse_coroutine_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'ct')
        name = self.expect('IDENT').value
        params = self.parse_params()
        old_in_ct = self._in_coroutine
        self._in_coroutine = True
        body = self.parse_fn_body()
        self._in_coroutine = old_in_ct
        return CoroutineDecl(line=line, col=col, name=name, params=params, body=body)

    def parse_params(self):
        self.expect('OP', '(')
        params = []
        if not self.check('OP', ')'):
            params.append(self.parse_param())
            while self.match('OP', ','):
                params.append(self.parse_param())
        self.expect('OP', ')')
        return params

    def parse_param(self):
        line, col = self.peek().line, self.peek().col
        if self.match('OP', '*'):
            name = self.expect_name()
            return ParamSpec(line=line, col=col, kind='star', name=name)
        if self.match('OP', '**'):
            name = self.expect_name()
            return ParamSpec(line=line, col=col, kind='dstar', name=name)
        # Optionally a type annotation (IDENT) then the param name
        type_name = None
        if self.check('IDENT') and self.peek(1).kind == 'IDENT':
            type_name = self.advance().value
        name = self.expect_name()
        default = None
        if self.match('OP', '='):
            default = self.parse_expr()
        return ParamSpec(line=line, col=col, kind='pos', name=name, type_name=type_name, default=default)

    def parse_fn_body(self):
        if self.check('OP', '{'):
            return self.parse_block()
        if self.match('OP', '='):
            return self.parse_expr()
        if self.match('OP', '->'):
            return self.parse_expr()
        self.error("expected fn body: { ... } or = expr or -> expr")

    def parse_block(self):
        line, col = self.peek().line, self.peek().col
        self.expect('OP', '{')
        stmts = []
        self.skip_newlines()
        while not self.check('OP', '}') and not self.at_end():
            stmt = self.parse_stmt()
            if stmt is not None:
                stmts.append(stmt)
            self.skip_newlines()
        self.expect('OP', '}')
        return Block(line=line, col=col, stmts=stmts)

    def parse_sum_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'sm')
        name = self.expect('IDENT').value
        self.expect('OP', '=')
        variants = [self.parse_variant_spec()]
        while self.match('OP', '|'):
            variants.append(self.parse_variant_spec())
        derivations = []
        if self.match('KW', 'dv'):
            self.expect('OP', '[')
            if not self.check('OP', ']'):
                derivations.append(self.expect('IDENT').value)
                while self.match('OP', ','):
                    derivations.append(self.expect('IDENT').value)
            self.expect('OP', ']')
        return SumDecl(line=line, col=col, name=name, variants=variants, derivations=derivations)

    def parse_variant_spec(self):
        line, col = self.peek().line, self.peek().col
        name = self.expect('IDENT').value
        fields = []
        if self.match('OP', '('):
            if not self.check('OP', ')'):
                fields.append(self.expect_name())
                while self.match('OP', ','):
                    fields.append(self.expect_name())
            self.expect('OP', ')')
        return VariantSpec(line=line, col=col, name=name, fields=fields)

    def parse_proto_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'pr')
        name = self.expect('IDENT').value
        parents = []
        if self.match('KW', 'ex'):
            parents.append(self.expect('IDENT').value)
            while self.match('OP', ','):
                parents.append(self.expect('IDENT').value)
        self.expect('OP', '{')
        methods = []
        self.skip_newlines()
        while not self.check('OP', '}'):
            m_line, m_col = self.peek().line, self.peek().col
            m_name = self.expect('IDENT').value
            params = self.parse_params()
            default_body = None
            if self.match('OP', '='):
                default_body = self.parse_expr()
            elif self.check('OP', '{'):
                default_body = self.parse_block()
            methods.append(ProtoMethod(line=m_line, col=m_col, name=m_name, params=params, default_body=default_body))
            self.skip_newlines()
        self.expect('OP', '}')
        return ProtoDecl(line=line, col=col, name=name, parents=parents, methods=methods)

    def parse_impl_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'im')
        proto_name = self.expect('IDENT').value
        # 'for' keyword is not in KEYWORDS list (from SPEC). Check for the identifier 'for' — nope, 'for' IS a keyword.
        # Use KW 'for' then.
        self.expect('KW', 'for')
        type_name = self.expect('IDENT').value
        self.expect('OP', '{')
        methods = []
        self.skip_newlines()
        while not self.check('OP', '}'):
            m_line, m_col = self.peek().line, self.peek().col
            m_name = self.expect('IDENT').value
            params = self.parse_params()
            body = self.parse_fn_body()
            methods.append(FnDecl(line=m_line, col=m_col, name=m_name, params=params, body=body))
            self.skip_newlines()
        self.expect('OP', '}')
        return ImplDecl(line=line, col=col, proto_name=proto_name, type_name=type_name, methods=methods)

    def parse_if(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'if')
        cond = self.parse_expr()
        then = self.parse_block()
        elifs = []
        else_ = None
        # Allow newline between } and eli/el so multi-line if/else works
        while True:
            save = self.pos
            self.skip_newlines()
            if self.match('KW', 'eli'):
                ec = self.parse_expr()
                eb = self.parse_block()
                elifs.append((ec, eb))
            else:
                self.pos = save
                break
        save = self.pos
        self.skip_newlines()
        if self.match('KW', 'el'):
            else_ = self.parse_block()
        else:
            self.pos = save
        return If(line=line, col=col, cond=cond, then=then, elifs=elifs, else_=else_)

    def parse_for(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'for')
        pattern = self.parse_pattern()
        self.expect('KW', 'in')
        it = self.parse_expr()
        filt = None
        if self.match('KW', 'if'):
            filt = ('if', self.parse_expr())
        elif self.match('KW', 'wh'):
            filt = ('wh', self.parse_expr())
        elif self.match('KW', 'un'):
            filt = ('un', self.parse_expr())
        body = self.parse_block()
        loop_tail = self.parse_loop_tail()
        return For(line=line, col=col, pattern=pattern, iter=it, filter=filt, body=body, loop_tail=loop_tail)

    def parse_loop_tail(self):
        tail = {}
        for kw in ('bf', 'bt', 'af', 'el', 'fi'):
            save = self.pos
            self.skip_newlines()
            if self.match('KW', kw):
                tail[kw] = self.parse_block()
            else:
                self.pos = save
        return tail

    def parse_while(self, is_until=False):
        line, col = self.peek().line, self.peek().col
        self.advance()  # wh or un
        cond = self.parse_expr()
        body = self.parse_block()
        loop_tail = self.parse_loop_tail()
        return While(line=line, col=col, cond=cond, body=body, is_until=is_until, loop_tail=loop_tail)

    def parse_loop(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'lp')
        count = None
        if not self.check('OP', '{'):
            count = self.parse_expr()
        body = self.parse_block()
        loop_tail = self.parse_loop_tail()
        return Loop(line=line, col=col, count=count, body=body, loop_tail=loop_tail)

    def parse_match_stmt(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'mt')
        target = self.parse_expr()
        self.expect('OP', '{')
        arms = []
        self.skip_newlines()
        while not self.check('OP', '}'):
            pat = self.parse_pattern()
            guard = None
            if self.match('KW', 'if'):
                # Guard expression must stop before `->` (implication op at prec 15),
                # so parse with min_prec > 15.
                guard = self.parse_expr(min_prec=16)
            self.expect('OP', '->')
            if self.check('OP', '{'):
                body = self.parse_block()
            else:
                body = self.parse_expr()
            arms.append(MatchArm(pattern=pat, guard=guard, body=body))
            # Optional ',' or ';' or newline
            if self.check('OP', ',') or self.check('OP', ';'):
                self.advance()
            self.skip_newlines()
        self.expect('OP', '}')
        return Match(line=line, col=col, target=target, arms=arms)

    def parse_try(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'ty')
        body = self.parse_block()
        excepts = []
        finally_ = None
        while True:
            save = self.pos
            self.skip_newlines()
            if not self.match('KW', 'ex'):
                self.pos = save
                break
            e_line = self.peek().line
            tn = None
            vn = None
            if self.check('OP', '{'):
                pass
            elif self.check('IDENT') and self.peek(1).kind == 'IDENT':
                tn = self.advance().value
                vn = self.advance().value
            elif self.check('IDENT'):
                vn = self.advance().value
            eb = self.parse_block()
            excepts.append(Except(line=e_line, type_name=tn, var_name=vn, body=eb))
        save = self.pos
        self.skip_newlines()
        if self.match('KW', 'fi'):
            finally_ = self.parse_block()
        else:
            self.pos = save
        return Try(line=line, col=col, body=body, excepts=excepts, finally_=finally_)

    def parse_raise(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'rs')
        exc = None
        cause = None
        if not self.check('NEWLINE') and not self.check('EOF') and not self.check('OP', '}'):
            exc = self.parse_expr()
        if self.match('KW', 'fr'):
            cause = self.parse_expr()
        return Raise(line=line, col=col, exc=exc, cause=cause)

    def parse_return(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'r')
        value = None
        if not self.check('NEWLINE') and not self.check('EOF') and not self.check('OP', '}') and not self.check('OP', ';'):
            # Check for named return: r name1=expr1, name2=expr2
            if self.check('IDENT') and self.peek(1).kind == 'OP' and self.peek(1).value == '=':
                pairs = []
                while True:
                    name = self.expect_name()
                    self.expect('OP', '=')
                    val = self.parse_expr(min_prec=1)
                    pairs.append((name, val))
                    if not self.match('OP', ','):
                        break
                # Build a dict literal AST: ["name1": val1, "name2": val2]
                items = [CollElem(kind='kv', key=StrLit(pieces=[('str', k)]), value=v) for k, v in pairs]
                value = ListExpr(items=items)
            else:
                value = self.parse_expr()
        return Return(line=line, col=col, value=value)

    def parse_break(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'br')
        level = 1
        if self.check('NUMBER'):
            t = self.advance()
            level = t.value[1]
        return Break(line=line, col=col, level=level)

    def parse_continue(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'cn')
        level = 1
        advance = 1
        if self.check('OP', '+') or self.check('OP', '-'):
            sign = 1 if self.advance().value == '+' else -1
            if self.check('NUMBER'):
                advance = sign * self.advance().value[1]
        elif self.check('NUMBER'):
            level = self.advance().value[1]
        return Continue(line=line, col=col, level=level, advance=advance)

    def parse_yield(self, is_from):
        line, col = self.peek().line, self.peek().col
        self.advance()  # y or yf
        value = None
        if not self.check('NEWLINE') and not self.check('EOF') and not self.check('OP', '}'):
            value = self.parse_expr()
        return Yield(line=line, col=col, value=value, is_from=is_from)

    def parse_strict_loose(self, mode):
        line, col = self.peek().line, self.peek().col
        self.advance()
        if self.check('OP', '{'):
            body = self.parse_block()
        else:
            body = None  # top-level toggle
        cls = StrictBlock if mode == 'sd' else LooseBlock
        return cls(line=line, col=col, body=body)

    def parse_decorated(self):
        decs = []
        while self.check('OP', '@'):
            self.advance()
            decs.append(self.parse_expr())
            self.skip_newlines()
        # Now parse the function declaration
        stmt = self.parse_stmt()
        if isinstance(stmt, (FnDecl, CoroutineDecl)):
            stmt.decorators = decs
        else:
            self.error("decorators can only be applied to df/ct declarations")
        return stmt

    def parse_with(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'wi')
        bindings = []
        while True:
            expr = self.parse_expr()
            var = None
            if self.check('KW', 'as'):
                self.advance()
                var = self.expect_name()
            bindings.append(WithBinding(var=var, expr=expr))
            if not self.match('OP', ','):
                break
        body = self.parse_block()
        return With(line=line, col=col, bindings=bindings, body=body)

    def parse_use(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'us')
        items = []
        while True:
            item_line, item_col = self.peek().line, self.peek().col
            if self.match('OP', '*'):
                # us * from "module"
                # Not standard; for now skip
                name = self.expect_name()
                items.append(UseItem(line=item_line, col=item_col, name=name, star=True))
            else:
                name = self.expect_name()
                alias = None
                star = False
                if self.check('KW', 'as'):
                    self.advance()
                    alias = self.expect_name(allow_all_kw=True)
                elif self.check('OP', '.') and self.peek(1).kind == 'OP' and self.peek(1).value == '*':
                    self.advance()  # .
                    self.advance()  # *
                    star = True
                items.append(UseItem(line=item_line, col=item_col, name=name, alias=alias, star=star))
            if not self.match('OP', ','):
                break
        # Optional block form: us module { body }
        body = None
        if self.check('OP', '{'):
            body = self.parse_block()
        return Use(line=line, col=col, items=items, body=body)

    def parse_export(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'xp')
        names = []
        names.append(self.expect_name())
        while self.match('OP', ','):
            names.append(self.expect_name())
        return Export(line=line, col=col, names=names)

    def parse_label(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'lbl')
        name = self.expect_name()
        return Label(line=line, col=col, name=name)

    def parse_goto(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'goto')
        target = self.parse_expr()
        return Goto(line=line, col=col, target=target)

    def parse_jl(self):
        """jl target — alias for goto (N-dimensional jump-to-label)."""
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'jl')
        target = self.parse_expr()
        return Goto(line=line, col=col, target=target)

    def parse_comefrom(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'cf')
        name = self.expect_name()
        return ComeFrom(line=line, col=col, label=name)

    def parse_green_thread(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'gt')
        if self.check('OP', '{'):
            body = self.parse_block()
        else:
            body = ExprStmt(line=line, col=col, expr=self.parse_expr())
        return GreenThread(line=line, col=col, body=body)

    def parse_await(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'aw')
        expr = self.parse_expr()
        return Await(line=line, col=col, expr=expr)

    def parse_on(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'on')
        # Check if it's identifier.ch pattern or a general condition trigger
        if self.check('IDENT') and self.peek(1).kind == 'OP' and self.peek(1).value == '.':
            # Could be ident.ch or a general expression starting with ident.something
            # Peek further to see if it's specifically .ch followed by {
            saved_pos = self.pos
            var_name = self.expect_name()
            if self.check('OP', '.'):
                self.advance()
                if self.check('IDENT') and self.peek().value == 'ch' or (self.check('KW') and self.peek().value == 'ch'):
                    attr = self.expect_name(allow_all_kw=True)
                    if attr == 'ch':
                        body = self.parse_block()
                        return On(line=line, col=col, var_name=var_name, body=body)
            # Not ident.ch — restore and parse as condition trigger
            self.pos = saved_pos
        # General condition trigger: on expr { body }
        cond = self.parse_expr()
        body = self.parse_block()
        return CondTrigger(line=line, col=col, cond=cond, body=body)

    def parse_off(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'of')
        # Check for 'all' keyword to remove all condition triggers
        if self.check('IDENT') and self.peek().value == 'all':
            self.advance()
            return Off(line=line, col=col, var_name='__all_cond__')
        var_name = self.expect_name()
        self.expect('OP', '.')
        attr = self.expect_name(allow_all_kw=True)
        if attr != 'ch':
            self.error(f"expected .ch after variable name in 'of'")
        return Off(line=line, col=col, var_name=var_name)

    def parse_sub(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'sub')
        self.expect('OP', '(')
        start = self.parse_expr()
        self.expect('OP', ',')
        end = self.parse_expr()
        self.expect('OP', ')')
        return Sub(line=line, col=col, start=start, end=end)

    def parse_resume(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'rm')
        return Resume(line=line, col=col)

    # --------------- algebraic effects ---------------
    def parse_effect_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'ef')
        name = self.expect('IDENT').value
        fields = []
        if self.match('OP', '('):
            if not self.check('OP', ')'):
                fields.append(self.expect_name())
                while self.match('OP', ','):
                    fields.append(self.expect_name())
            self.expect('OP', ')')
        return EffectDecl(line=line, col=col, name=name, fields=fields)

    def parse_perform(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'pf')
        expr = self.parse_expr()
        return Perform(line=line, col=col, expr=expr)

    def parse_handle(self):
        """Parse: hd { body } with { Pattern k -> handler, ... }"""
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'hd')
        body = self.parse_block()
        # Expect 'with' as an identifier (not a keyword)
        t = self.peek()
        if not (t.kind == 'IDENT' and t.value == 'with'):
            self.error("expected 'with' after hd body")
        self.advance()
        self.expect('OP', '{')
        cases = []
        self.skip_newlines()
        while not self.check('OP', '}'):
            case_line, case_col = self.peek().line, self.peek().col
            pat = self.parse_pattern()
            cont_name = None
            # Check if there's a continuation name (an identifier before ->)
            if self.check('IDENT') or (self.check('KW') and self.peek().value in self._SOFT_KW):
                cont_name = self.expect_name()
            self.expect('OP', '->')
            if self.check('OP', '{'):
                case_body = self.parse_block()
            else:
                case_body = self.parse_expr()
            cases.append(HandleCase(line=case_line, col=case_col, pattern=pat, cont_name=cont_name, body=case_body))
            if self.check('OP', ',') or self.check('OP', ';'):
                self.advance()
            self.skip_newlines()
        self.expect('OP', '}')
        return Handle(line=line, col=col, body=body, cases=cases)

    # --------------- macros ---------------
    def parse_macro_decl(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'mc')
        name = self.expect_name()
        params = self.parse_params()
        body = self.parse_fn_body()
        return MacroDecl(line=line, col=col, name=name, params=params, body=body)

    # --------------- execution sets ---------------
    def parse_exec_set(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'xs')
        block = self.parse_block()
        return ExecSet(line=line, col=col, stmts=block.stmts)

    # --------------- query syntax ---------------
    def parse_query(self):
        """Parse: qr source_expr (whr filter_expr)? (sel select_expr)? (srt sort_expr)?"""
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'qr')
        # Use min_prec=1 so parse_expr does NOT consume 'whr' as a Where clause
        source = self.parse_expr(min_prec=1)
        filter_expr = None
        select_expr = None
        sort_expr = None
        if self.check('KW') and self.peek().value == 'whr':
            self.advance()
            filter_expr = self.parse_expr(min_prec=1)
        if self.check('KW') and self.peek().value == 'sel':
            self.advance()
            select_expr = self.parse_expr(min_prec=1)
        if self.check('KW') and self.peek().value == 'srt':
            self.advance()
            sort_expr = self.parse_expr(min_prec=1)
        return Query(line=line, col=col, source=source, filter_expr=filter_expr, select_expr=select_expr, sort_expr=sort_expr)

    # --------------- stack combinator block ---------------
    def parse_stk_block(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'stk')
        self.expect('OP', '{')
        # Parse Forth-style: each token is either a value or an operator
        # We wrap each token as an individual ExprStmt containing a simple node
        stmts = []
        self.skip_newlines()
        while not self.check('OP', '}') and not self.at_end():
            t = self.peek()
            if t.kind == 'NUMBER':
                self.advance()
                stmts.append(ExprStmt(line=t.line, col=t.col, expr=NumLit(line=t.line, col=t.col, value=t.value[1])))
            elif t.kind == 'STRING':
                self.advance()
                stmts.append(ExprStmt(line=t.line, col=t.col, expr=StrLit(line=t.line, col=t.col, pieces=t.value)))
            elif t.kind == 'KW' and t.value in ('true', 'false', 'und'):
                self.advance()
                if t.value == 'true':
                    stmts.append(ExprStmt(line=t.line, col=t.col, expr=BoolLit(line=t.line, col=t.col, value=True)))
                elif t.value == 'false':
                    stmts.append(ExprStmt(line=t.line, col=t.col, expr=BoolLit(line=t.line, col=t.col, value=False)))
                else:
                    stmts.append(ExprStmt(line=t.line, col=t.col, expr=UndLit(line=t.line, col=t.col)))
            elif t.kind == 'OP' and t.value in ('+', '-', '*', '/', '%', '**'):
                self.advance()
                # Wrap operator as an Ident so stack eval can recognize it
                stmts.append(ExprStmt(line=t.line, col=t.col, expr=Ident(line=t.line, col=t.col, name=t.value)))
            elif t.kind == 'IDENT' or (t.kind == 'KW' and t.value in self._SOFT_KW):
                self.advance()
                stmts.append(ExprStmt(line=t.line, col=t.col, expr=Ident(line=t.line, col=t.col, name=t.value)))
            elif t.kind == 'OP' and t.value == '(':
                # Parse a call expression (function call in stack context)
                expr = self.parse_primary()
                stmts.append(ExprStmt(line=t.line, col=t.col, expr=expr))
            else:
                self.skip_newlines()
                if self.check('OP', '}'):
                    break
                self.error(f"unexpected token in stk block: {t.kind} {t.value!r}")
            self.skip_newlines()
        self.expect('OP', '}')
        body = Block(line=line, col=col, stmts=stmts)
        return StkBlock(line=line, col=col, body=body)

    def parse_fork(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'fk')
        # fk { body } — scoped fork
        if self.check('OP', '{'):
            body = self.parse_block()
            return Fork(line=line, col=col, body=body)
        # fk() — true fork (no body)
        if self.check('OP', '('):
            self.advance()  # skip (
            self.expect('OP', ')')
            return Fork(line=line, col=col, body=None)
        # bare fk — also true fork (no parens needed)
        return Fork(line=line, col=col, body=None)

    def parse_dyn_scope(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'dy')
        body = self.parse_block()
        return DynScope(line=line, col=col, body=body)

    def parse_record(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'rec')
        body = self.parse_block()
        return Record(line=line, col=col, body=body)

    def parse_dosync(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'dosync')
        body = self.parse_block()
        return DoSync(line=line, col=col, body=body)

    def parse_jump_abs(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'ja')
        self.expect('OP', '(')
        coords = []
        if not self.check('OP', ')'):
            coords.append(self.parse_expr())
            while self.match('OP', ','):
                coords.append(self.parse_expr())
        self.expect('OP', ')')
        return JumpAbs(line=line, col=col, coords=coords)

    def parse_jump_rel(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'jr')
        self.expect('OP', '(')
        offsets = []
        if not self.check('OP', ')'):
            offsets.append(self.parse_expr())
            while self.match('OP', ','):
                offsets.append(self.parse_expr())
        self.expect('OP', ')')
        return JumpRel(line=line, col=col, offsets=offsets)

    # --------------- expressions (Pratt precedence) ---------------
    # Precedence levels (higher binds tighter)
    PREC = {
        '??': 5,
        '|>': 10, '|>>': 10, '|?>': 10,
        '<-': 15, '->': 15, '!<-': 15, '!->': 15,
        '|': 18,
        '||': 20, '!||': 20, '||.': 20,
        '^^': 25, '!^^': 25, '^^.': 25,
        '&&': 30, '!&&': 30, '&&.': 30,
        '&': 32,
        '~/': 40,
        '=~': 40,
        '==': 40, '<>': 40, '===': 40, '!==': 40,
        '<': 40, '>': 40, '<=': 40, '>=': 40, '!<': 40, '!>': 40,
        '==.': 40, '<>.': 40, '<.': 40, '>.': 40, '<=.': 40, '>=.': 40,
        '==..': 40, '<>..': 40, '<..': 40, '>..': 40,
        '..': 50, '..=': 50,
        '+': 60, '-': 60,
        '+.': 60, '-.': 60, '+..': 60, '-..': 60,
        '*': 70, '/': 70, '%': 70,
        '*.': 70, '/.': 70, '%.': 70, '*..': 70, '/..': 70, '%..': 70,
        '**': 80, '//': 80,
        '**.': 80, '//.': 80, '**..': 80,
    }
    RIGHT_ASSOC = {'**', '//', '<-', '->', '!<-', '!->'}
    KEYWORD_OPS = {'is': 40, 'in': 40, 'not': 40, 'is not': 40, 'not in': 40}

    def parse_expr(self, min_prec=0):
        left = self.parse_unary()
        # Ternary: allowed at top level only
        while True:
            t = self.peek()
            op = None
            if t.kind == 'OP' and t.value in self.PREC:
                op = t.value
            elif t.kind == 'KW' and t.value in self.KEYWORD_OPS:
                op = t.value
                # Check for two-token operators: `is not`, `not in`
                if op == 'is' and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].kind == 'KW' and self.tokens[self.pos + 1].value == 'not':
                    op = 'is not'
                elif op == 'not' and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].kind == 'KW' and self.tokens[self.pos + 1].value == 'in':
                    op = 'not in'
            if op is None: break
            prec = self.PREC.get(op, self.KEYWORD_OPS.get(op))
            if prec < min_prec: break
            self.advance()
            # Consume second token for two-token ops
            if op in ('is not', 'not in'):
                self.advance()
            next_prec = prec if op in self.RIGHT_ASSOC else prec + 1
            right = self.parse_expr(next_prec)
            if op in ('|>', '|>>', '|?>'):
                left = Pipe(line=t.line, col=t.col, op=op, lhs=left, rhs=right)
            else:
                # Constant folding: if both operands are numeric literals,
                # evaluate at parse time to avoid runtime overhead.
                # Note: '+' and '-' are excluded to preserve BinOp AST nodes
                # for ast_of() / self-modification support.
                if (isinstance(left, NumLit) and isinstance(right, NumLit)
                        and op in ('*', '/', '**', '//', '%')):
                    try:
                        result = apply_binop(op, left.value, right.value)
                        left = NumLit(line=t.line, col=t.col, value=result)
                    except Exception:
                        left = BinOp(line=t.line, col=t.col, op=op, lhs=left, rhs=right)
                else:
                    left = BinOp(line=t.line, col=t.col, op=op, lhs=left, rhs=right)
        # Check for 'by' clause on range expressions
        if isinstance(left, BinOp) and left.op in ('..', '..='):
            if self.check('KW') and self.peek().value == 'by':
                self.advance()
                step = self.parse_expr(min_prec=60)
                left = RangeBy(line=left.line, col=left.col, start=left.lhs, end=left.rhs, step=step, inclusive=(left.op == '..='))
        # Ternary at top level
        if min_prec == 0 and self.check('OP', '?'):
            self.advance()
            then = self.parse_expr()
            self.expect('OP', ':')
            else_ = self.parse_expr()
            left = Ternary(cond=left, then=then, else_=else_)
        # Where clause: expr whr { bindings }
        if min_prec == 0 and self.check('KW') and self.peek().value == 'whr':
            self.advance()
            bindings = self.parse_block()
            left = Where(line=left.line, col=left.col, expr=left, bindings=bindings)
        return left

    _REDUCE_OPS = {'+/', '-/', '*/', '**/', '%/'}
    _SCAN_OPS = {'+\\', '-\\', '*\\', '**\\', '%\\'}

    def parse_unary(self):
        t = self.peek()
        # Reduce prefix: +/ expr, */ expr, etc.
        if t.kind == 'OP' and t.value in self._REDUCE_OPS:
            self.advance()
            operand = self.parse_unary()
            return ReduceOp(line=t.line, col=t.col, op=t.value[:-1], operand=operand)
        # Scan prefix: +\ expr, *\ expr, etc.
        if t.kind == 'OP' and t.value in self._SCAN_OPS:
            self.advance()
            operand = self.parse_unary()
            return ScanOp(line=t.line, col=t.col, op=t.value[:-1], operand=operand)
        if t.kind == 'OP' and t.value in ('+', '-', '!', '~', '#'):
            self.advance()
            operand = self.parse_unary()
            return UnaryOp(line=t.line, col=t.col, op=t.value, operand=operand)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            t = self.peek()
            if t.kind == 'OP' and t.value == '(':
                self.advance()
                args, kwargs = self._parse_call_args()
                self.expect('OP', ')')
                expr = Call(line=t.line, col=t.col, fn=expr, args=args, kwargs=kwargs)
            elif t.kind == 'OP' and t.value == '[':
                self.advance()
                # Could be index_list, slice, or single index
                subs = self._parse_subscript()
                self.expect('OP', ']')
                if isinstance(subs, Slice):
                    subs.target = expr
                    expr = subs
                else:
                    expr = Index(line=t.line, col=t.col, target=expr, key=subs)
            elif t.kind == 'OP' and t.value == '?.':
                self.advance()
                name = self.expect_name(allow_all_kw=True)
                expr = SafeNav(line=t.line, col=t.col, target=expr, name=name)
            elif t.kind == 'OP' and t.value == '.':
                self.advance()
                name = self.expect_name(allow_all_kw=True)
                expr = Attr(line=t.line, col=t.col, target=expr, name=name)
            elif t.kind == 'OP' and t.value == '^':
                self.advance()
                power = self.parse_unary()
                expr = FnPower(line=t.line, col=t.col, fn=expr, power=power)
            else:
                break
        return expr

    def _parse_call_args(self):
        args, kwargs = [], {}
        if self.check('OP', ')'):
            return args, kwargs
        while True:
            # kwarg: IDENT = expr (also allow soft keywords as kwarg names)
            if (self.check('IDENT') or (self.check('KW') and self.peek().value in self._SOFT_KW)) and self.peek(1).kind == 'OP' and self.peek(1).value == '=':
                name = self.advance().value
                self.advance()  # =
                val = self.parse_expr()
                kwargs[name] = val
            elif self.match('OP', '*'):
                args.append(('star', self.parse_expr()))
            elif self.match('OP', '**'):
                kwargs['__dstar__' + str(len(kwargs))] = self.parse_expr()
            else:
                args.append(('pos', self.parse_expr()))
            if not self.match('OP', ','):
                break
        return args, kwargs

    def _parse_subscript(self):
        """Parse inside []: could be a slice (with :), a single expr, or a list of indices."""
        line, col = self.peek().line, self.peek().col
        # Peek ahead for `:` — if present before a closing `]` or `,`, it's a slice
        # Simple heuristic: try to parse an expr; if next is `:`, it's a slice.
        start = None
        if not self.check('OP', ':') and not self.check('OP', ']'):
            start = self.parse_expr()
        if self.check('OP', ':'):
            self.advance()
            end = None
            step = None
            win = None
            inc = None
            if not self.check('OP', ':') and not self.check('OP', ']'):
                end = self.parse_expr()
            if self.match('OP', ':'):
                if not self.check('OP', ':') and not self.check('OP', ']'):
                    step = self.parse_expr()
                if self.match('OP', ':'):
                    if not self.check('OP', ':') and not self.check('OP', ']'):
                        win = self.parse_expr()
                    if self.match('OP', ':'):
                        if not self.check('OP', ']'):
                            inc = self.parse_expr()
            return Slice(line=line, col=col, target=None, start=start, end=end, step=step, win=win, inc=inc)
        # Could be index_list
        if self.match('OP', ','):
            items = [start]
            if not self.check('OP', ']'):
                items.append(self.parse_expr())
                while self.match('OP', ','):
                    if self.check('OP', ']'): break
                    items.append(self.parse_expr())
            # Return as a ListExpr representing multi-index
            elems = [CollElem(kind='pos', value=i) for i in items]
            return ListExpr(items=elems)
        return start

    def parse_primary(self):
        t = self.peek()
        if t.kind == 'REGEX':
            self.advance()
            return RegexLit(line=t.line, col=t.col, pattern=t.value[0], flags=t.value[1])
        if t.kind == 'NUMBER':
            self.advance()
            kind, val = t.value
            if kind == 'flt':
                return NumLit(line=t.line, col=t.col, value=val)
            return NumLit(line=t.line, col=t.col, value=val)
        if t.kind == 'STRING':
            self.advance()
            return StrLit(line=t.line, col=t.col, pieces=t.value)
        if t.kind == 'KW':
            if t.value == 'und':   self.advance(); return UndLit(line=t.line, col=t.col)
            if t.value == 'true':  self.advance(); return BoolLit(line=t.line, col=t.col, value=True)
            if t.value == 'false': self.advance(); return BoolLit(line=t.line, col=t.col, value=False)
            if t.value == 'oo':    self.advance(); return OoLit(line=t.line, col=t.col)
            if t.value == 'f':
                # Context-sensitive:
                #   `f -> expr`       -> fn_literal
                #   `f { body }`      -> fn_literal
                #   `f = expr`        -> ambiguous (prefer var so `f = 5` works)
                #   `f (params) -> e` -> fn_literal (need to peek past parens)
                #   `f (params) { b }`-> fn_literal
                #   `f (args)`        -> call (f is a variable)
                nxt = self.peek(1)
                if nxt.kind == 'OP' and nxt.value in ('->', '{'):
                    return self.parse_fn_literal()
                if nxt.kind == 'OP' and nxt.value == '(':
                    # Scan past matching ) from current position and check what follows
                    depth = 0
                    i = self.pos + 1
                    while i < len(self.tokens):
                        tk = self.tokens[i]
                        if tk.kind == 'OP' and tk.value == '(': depth += 1
                        elif tk.kind == 'OP' and tk.value == ')':
                            depth -= 1
                            if depth == 0: break
                        i += 1
                    # Skip over NEWLINEs between ) and next token
                    j = i + 1
                    while j < len(self.tokens) and self.tokens[j].kind == 'NEWLINE':
                        j += 1
                    after = self.tokens[j] if j < len(self.tokens) else None
                    if after and after.kind == 'OP' and after.value in ('->', '{'):
                        return self.parse_fn_literal()
                # Fall through — f as bare identifier
                self.advance()
                return Ident(line=t.line, col=t.col, name='f')
            if t.value == 'new':   return self.parse_new()
            if t.value == 'mt':    return self.parse_match_stmt()
            if t.value == 'if':    return self.parse_if()
            if t.value == 'gt':    return self.parse_green_thread()
            if t.value == 'aw':    return self.parse_await()
            if t.value == 'hd' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_handle()
            if t.value == 'xs' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_exec_set()
            if t.value == 'qr':
                return self.parse_query()
            if t.value == 'stk' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_stk_block()
            if t.value == 'fk' and self.peek(1).kind == 'OP' and self.peek(1).value in ('{', '('):
                return self.parse_fork()
            if t.value == 'dy' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_dyn_scope()
            if t.value == 'rec' and self.peek(1).kind == 'OP' and self.peek(1).value == '{':
                return self.parse_record()
            if t.value == 'pf':
                nxt = self.peek(1)
                if nxt.kind not in ('EOF', 'NEWLINE') and not (nxt.kind == 'OP' and nxt.value in ('=', '+=', '-=', '*=', '/=', '.=', ':=', '~=')):
                    return self.parse_perform()
                self.advance()
                return Ident(line=t.line, col=t.col, name='pf')
            if t.value == 'fr':
                nxt = self.peek(1)
                if nxt.kind == 'OP' and nxt.value == '[':
                    self.advance()  # consume 'fr'
                    inner = self.parse_list_literal()
                    return FrozenExpr(line=t.line, col=t.col, items=inner)
                # fall through — fr as identifier (not common, but safe)
                self.advance()
                return Ident(line=t.line, col=t.col, name='fr')
        if t.kind == 'KW' and t.value == 'y':
            nxt = self.peek(1)
            # y followed by expression-start (not = or end) => yield expression
            if (nxt.kind not in ('EOF', 'NEWLINE')
                    and not (nxt.kind == 'OP' and nxt.value in ('=', '+=', '-=', '*=', '/=', '.=', ':=', '~=', '}', ')', ']', ',', '.', '?.', '('))
                    and not (nxt.kind == 'KW' and nxt.value in ('for', 'in', 'if', 'whr', 'sel', 'srt'))):
                return self.parse_yield(is_from=False)
            # Otherwise fall through to identifier
            self.advance()
            return Ident(line=t.line, col=t.col, name='y')
        if t.kind == 'KW' and t.value in ('some', 'every'):
            kind = self.advance().value
            var = self.expect_name()
            self.expect('KW', 'in')
            iter_expr = self.parse_expr(min_prec=50)  # stop before comparisons
            self.expect('KW', 'if')
            pred = self.parse_expr()
            return Quantifier(line=t.line, col=t.col, kind=kind, var=var, iter=iter_expr, pred=pred)
        if t.kind == 'IDENT' or (t.kind == 'KW' and t.value in self._SOFT_KW):
            # Handle `fr[...]` frozen collections
            if t.value == 'fr' and self.peek(1).kind == 'OP' and self.peek(1).value == '[':
                self.advance()  # consume 'fr'
                inner = self.parse_list_literal()  # returns ListExpr
                return FrozenExpr(line=t.line, col=t.col, items=inner)
            self.advance()
            return Ident(line=t.line, col=t.col, name=t.value)
        if t.kind == 'OP':
            if t.value == '`':
                # Backtick lambda: `expr` — shortest implicit-args anonymous fn
                self.advance()
                body = self.parse_expr()
                self.expect('OP', '`')
                return Lambda(line=t.line, col=t.col, params=[], body=body, implicit=True)
            if t.value == '$':
                # Variable-variable: $name, ${expr}, $$name, etc.
                line, col = t.line, t.col
                self.advance()
                levels = 1
                while self.check('OP', '$'):
                    self.advance()
                    levels += 1
                if self.check('OP', '{'):
                    self.advance()
                    expr = self.parse_expr()
                    self.expect('OP', '}')
                else:
                    name_tok = self.peek()
                    if name_tok.kind == 'IDENT' or (name_tok.kind == 'KW' and name_tok.value in self._SOFT_KW):
                        self.advance()
                        expr = Ident(line=name_tok.line, col=name_tok.col, name=name_tok.value)
                    else:
                        self.error("expected identifier after $")
                return VarVar(line=line, col=col, expr=expr, levels=levels)
            if t.value == '(':
                self.advance()
                expr = self.parse_expr()
                self.expect('OP', ')')
                return expr
            if t.value == '[':
                return self.parse_list_literal()
            if t.value == '{':
                # Block as value
                return self.parse_block()
            if t.value == '_':
                self.advance()
                return Wildcard(line=t.line, col=t.col)
        self.error(f"unexpected token in expression")

    def parse_fn_literal(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'f')
        # f (params) body | f body | f -> expr
        params = []
        implicit = True
        if self.check('OP', '('):
            params = self.parse_params()
            implicit = False
        if self.check('OP', '{'):
            body = self.parse_block()
        elif self.match('OP', '->'):
            body = self.parse_expr()
        elif self.match('OP', '='):
            body = self.parse_expr()
        else:
            self.error("expected fn body: (params) ..., { ... }, or -> expr")
        return Lambda(line=line, col=col, params=params, body=body, implicit=implicit)

    def parse_new(self):
        line, col = self.peek().line, self.peek().col
        self.expect('KW', 'new')
        # new(args...) — treat as call
        self.expect('OP', '(')
        args, kwargs = self._parse_call_args()
        self.expect('OP', ')')
        return Call(line=line, col=col, fn=Ident(name="new"), args=args, kwargs=kwargs)

    def parse_list_literal(self):
        line, col = self.peek().line, self.peek().col
        self.expect('OP', '[')
        items = []
        self.skip_newlines()
        while not self.check('OP', ']'):
            if self.match('OP', '...'):
                items.append(CollElem(kind='spread', value=self.parse_expr()))
            else:
                # Parse expr; if followed by :, it's a key:value
                first = self.parse_expr()
                # --- List comprehension: [expr for x in iter ...] ---
                if self.check('KW', 'for'):
                    return self._parse_list_comprehension(line, col, first)
                if self.match('OP', ':'):
                    # Special case: if first is an IDENT, treat as string key (Lua-style)
                    val = self.parse_expr()
                    items.append(CollElem(kind='kv', key=first, value=val))
                else:
                    items.append(CollElem(kind='pos', value=first))
            self.skip_newlines()
            if not self.match('OP', ','):
                break
            self.skip_newlines()
        self.expect('OP', ']')
        return ListExpr(line=line, col=col, items=items)

    def _parse_list_comprehension(self, line, col, expr):
        """Parse: expr for pat in iter (if guard)? (for pat in iter (if guard)?)*  ]"""
        clauses = []
        while self.check('KW', 'for'):
            self.advance()  # consume 'for'
            pattern = self.parse_pattern()
            self.expect('KW', 'in')
            iter_expr = self.parse_expr()
            guard = None
            if self.check('KW', 'if'):
                self.advance()
                guard = self.parse_expr()
            clauses.append((pattern, iter_expr, guard))
        self.expect('OP', ']')
        return ListComp(line=line, col=col, expr=expr, clauses=clauses)

    # --------------- patterns ---------------
    def parse_pattern(self):
        # Start by parsing one pattern, then check for |, @, if guard
        p = self._parse_pattern_core()
        # Or-pattern
        while self.check('OP', '|'):
            # Careful: | is also match separator — but we're inside pattern before ->, so it's or-pattern
            self.advance()
            rhs = self._parse_pattern_core()
            if isinstance(p, PatOr):
                p.alts.append(rhs)
            else:
                p = PatOr(alts=[p, rhs])
        return p

    def _parse_pattern_core(self):
        t = self.peek()
        if t.kind == 'NUMBER':
            self.advance()
            return PatLit(line=t.line, col=t.col, value=t.value[1])
        if t.kind == 'STRING':
            self.advance()
            # Flatten string to just string literal (no interp in patterns)
            flat = ''.join(p[1] for p in t.value if p[0] == 'str')
            return PatLit(line=t.line, col=t.col, value=flat)
        if t.kind == 'KW':
            if t.value == 'und':   self.advance(); return PatLit(line=t.line, col=t.col, value=UND)
            if t.value == 'true':  self.advance(); return PatLit(line=t.line, col=t.col, value=True)
            if t.value == 'false': self.advance(); return PatLit(line=t.line, col=t.col, value=False)
        if t.kind == 'IDENT' or (t.kind == 'KW' and t.value in self._SOFT_KW):
            # Could be PatVar, PatVariant, or PatAs.
            # Convention: uppercase first letter -> variant (even with no parens).
            name = t.value
            self.advance()
            if self.match('OP', '@'):
                inner = self._parse_pattern_core()
                return PatAs(line=t.line, col=t.col, name=name, pattern=inner)
            if self.check('OP', '('):
                self.advance()
                fields = []
                if not self.check('OP', ')'):
                    fields.append(self.parse_pattern())
                    while self.match('OP', ','):
                        fields.append(self.parse_pattern())
                self.expect('OP', ')')
                return PatVariant(line=t.line, col=t.col, name=name, fields=fields)
            if name and name[0].isupper():
                # Zero-arg variant pattern
                return PatVariant(line=t.line, col=t.col, name=name, fields=[])
            return PatVar(line=t.line, col=t.col, name=name)
        if t.kind == 'OP' and t.value == '_':
            self.advance()
            return PatWild(line=t.line, col=t.col)
        if t.kind == 'OP' and t.value == '[':
            return self._parse_pattern_list()
        if t.kind == 'OP' and t.value == '-':
            # Negative number literal
            self.advance()
            nt = self.peek()
            if nt.kind == 'NUMBER':
                self.advance()
                return PatLit(line=t.line, col=t.col, value=-nt.value[1])
        if t.kind == 'OP' and t.value == '(':
            self.advance()
            p = self.parse_pattern()
            self.expect('OP', ')')
            return p
        self.error(f"unexpected in pattern: {t.kind} {t.value!r}")

    def _parse_pattern_list(self):
        line, col = self.peek().line, self.peek().col
        self.expect('OP', '[')
        elems = []
        rest = None
        pairs = []
        is_dict = False
        while not self.check('OP', ']'):
            if self.match('OP', '...'):
                if self.check('IDENT'):
                    rest = self.advance().value
                break
            if self.match('OP', '**'):
                rest = self.advance().value
                break
            # Try to detect key:pattern (dict pattern)
            # Peek for IDENT/STRING/NUMBER followed by :
            save_pos = self.pos
            if (self.check('IDENT') or self.check('STRING') or self.check('NUMBER')) and self.peek(1).kind == 'OP' and self.peek(1).value == ':':
                is_dict = True
                kt = self.advance()
                if kt.kind == 'STRING':
                    key = ''.join(p[1] for p in kt.value if p[0] == 'str')
                elif kt.kind == 'NUMBER':
                    key = kt.value[1]
                else:
                    key = kt.value
                self.expect('OP', ':')
                pat = self.parse_pattern()
                pairs.append(PatPair(key=key, pattern=pat))
            else:
                self.pos = save_pos
                elems.append(self.parse_pattern())
            if not self.match('OP', ','):
                break
        self.expect('OP', ']')
        if is_dict:
            return PatDict(line=line, col=col, pairs=pairs, rest=rest)
        return PatList(line=line, col=col, elems=elems, rest=rest)


# =============================================================================
#  INTERPRETER
# =============================================================================

class Interpreter:
    def __init__(self):
        self.global_scope = Scope(name="<top>")
        self.strict = False
        self.dispatch_tables = {}     # name -> MultiDispatch
        self.sum_types = {}           # name -> SumType
        self.variants = {}            # name -> VariantCtor
        self.protocols = {}           # name -> Protocol
        self.impls = {}               # (proto, type) -> dict of method name -> fn
        self.exc_stack = []           # stack of currently-handled exceptions (for bare `rs`)
        self.module_cache = {}        # name -> Scope, for us/xp module system
        self._triggers = {}           # var_name -> list of (scope, body_node)
        self._cond_triggers = []      # list of (cond_node, scope, body_node)
        self._last_jump = None        # (stmts, index) for rm (resume)
        self._derivation_eq = {}      # sum_type_name -> eq_fn
        self._derivation_ord = {}     # sum_type_name -> ord_fn
        self.state_buffer = []        # list of snapshots (ps pushes here)
        self.source = None            # original source text (set by run())
        # ---- thread safety lock ----
        self._lock = threading.RLock()
        # ---- fork registry ----
        self._fork_id_counter = 0
        self._current_fork_id = 0
        self._fork_children = {}      # fork_id -> list of child fork_ids
        self._fork_results = {}       # fork_id -> result (set when branch completes)
        self._fork_threads = {}       # fork_id -> Thread
        self._fork_return_value = threading.local()  # thread-local: when set, fk() returns this
        # ---- Multi-level meta-circular interpreter ----
        self.interp_level = 1
        self.meta_interpreters = {}      # level -> callable (Snafu fn)
        self.meta_interp_sources = {}    # level -> source string
        # ---- Auto-recording (per-statement state recording) ----
        self.auto_record = False
        self._auto_step = 0
        self._state_max_size = 0  # 0 = unlimited
        # ---- Persistent variables (pv) ----
        self.source_file = None
        # ---- STM (dosync) ----
        self._in_dosync = threading.local()
        # ---- eval_node dispatch table (performance optimization) ----
        # Build name-based dispatch for error messages
        self._eval_dispatch_by_name = {}
        for name in dir(self):
            if name.startswith('eval_'):
                self._eval_dispatch_by_name[name[5:]] = getattr(self, name)
        # Build type-keyed dispatch (avoids __name__ lookup per call)
        self._eval_dispatch = {}
        # Map all known AST node types to their eval methods
        for cls_name, method in self._eval_dispatch_by_name.items():
            # Find the class in the module globals
            cls = globals().get(cls_name)
            if cls is not None:
                self._eval_dispatch[cls] = method
        self.install_prelude()

    # -----------------------------------------------------------
    def install_prelude(self):
        g = self.global_scope
        g.define_local("und", UND)
        g.define_local("true", True)
        g.define_local("false", False)
        g.define_local("oo", math.inf)

        # Print
        def snafu_p(*args, sep=" ", end="\n"):
            print(sep.join(snafu_str(a) for a in args), end=end)
            return UND
        g.define_local("p", snafu_p)

        # Collections
        g.define_local("len", lambda x: len(x))
        g.define_local("abs", abs_fn)
        g.define_local("range", lambda a, b=None, step=1: list(range(a, b, step)) if b is not None else list(range(a)))
        g.define_local("lst", lambda iterable: list(iterable))
        g.define_local("st", lambda iterable: set(iterable))
        g.define_local("en", lambda iterable: [[i, x] for i, x in enumerate(iterable)])
        g.define_local("zp", lambda *its: [list(t) for t in zip(*its)])
        # Iter-first: `xs |> m(f)` reads as "xs through m with f" (Elixir/Gleam order).
        def snafu_m(it, f):
            return [_call_value(f, [x], {}) for x in it]
        def snafu_fl(it, pred):
            return [x for x in it if truthy(_call_value(pred, [x], {}))]
        def snafu_rdc(it, f, init=UND):
            return _reduce(f, it, init)
        g.define_local("m", snafu_m)
        g.define_local("fl", snafu_fl)
        g.define_local("rdc", snafu_rdc)
        # Old order also available for standalone-call style
        g.define_local("map_fn", lambda f, it: [_call_value(f, [x], {}) for x in it])
        g.define_local("srt", lambda it, k=None, rv=False: _sort(it, k, rv))
        g.define_local("sum", lambda it, init=0: _sum(it, init))
        g.define_local("min", lambda *args: min(*args) if len(args) > 1 else min(args[0]))
        g.define_local("max", lambda *args: max(*args) if len(args) > 1 else max(args[0]))
        g.define_local("int", lambda x: _to_int(x))
        g.define_local("flt", lambda x: float(x))
        g.define_local("str", lambda x: snafu_str(x))

        # Collection utilities
        g.define_local("rev", lambda it: list(reversed(list(it))))
        g.define_local("flat", lambda it: [x for sub in it for x in (sub if isinstance(sub, list) else [sub])])
        g.define_local("take", lambda it, n: list(itertools.islice(it, n)))
        g.define_local("drop", lambda it, n: list(it)[n:])
        g.define_local("any_of", lambda it, pred: any(truthy(_call_value(pred, [x], {})) for x in it))
        g.define_local("all_of", lambda it, pred: all(truthy(_call_value(pred, [x], {})) for x in it))
        g.define_local("find_first", lambda it, pred: next((x for x in it if truthy(_call_value(pred, [x], {}))), UND))
        g.define_local("join", lambda sep, it: sep.join(snafu_str(x) for x in it))

        # Math
        g.define_local("sqrt", math.sqrt)

        # eval — fallback for when ev is used as a value (not special-form)
        g.define_local("ev", lambda code: _eval_string_as_code(code, self))
        g.define_local("exp", math.exp)
        g.define_local("log", math.log)
        g.define_local("ln", math.log)
        g.define_local("sin", math.sin)
        g.define_local("cos", math.cos)
        g.define_local("tan", math.tan)
        g.define_local("floor", math.floor)
        g.define_local("ceil", math.ceil)
        g.define_local("round", round)
        g.define_local("pi", math.pi)
        g.define_local("e", math.e)
        g.define_local("tau", math.tau)

        # Input
        g.define_local("inp", lambda prompt="": input(prompt))

        # Python interop
        py_ns = SnafuObj(type_name="py")
        def py_import(name):
            import importlib
            return importlib.import_module(name)
        py_ns.attrs["import"] = py_import
        g.define_local("py", py_ns)

        # Object construction
        g.define_local("new", self._new_fn)
        g.define_local("id", lambda x: id(x))
        g.define_local("type", lambda x: type_name(x))
        g.define_local("cp", _deep_copy)
        g.define_local("implements", lambda v, p: self._implements(v, p))
        g.define_local("hs", lambda x: hash(x) if hasattr(x, '__hash__') and x.__hash__ is not None else id(x))

        # Exception constructors — `ValErr("msg")` returns an exception instance.
        exc_classes = {
            "Exc": SnafuError, "ArgErr": ArgErr, "TypeErr": TypeErr,
            "ValErr": ValErr, "NameErr": NameErr, "AttrErr": AttrErr,
            "IxErr": IxErr, "KeyErr": KeyErr, "DivErr": DivErr,
            "UndErr": UndErr, "MatchErr": MatchErr, "IOErr": IOErr,
            "ParseErr": ParseErr, "DispatchAmbig": DispatchAmbig,
            "BindErr": BindErr, "InterpErr": InterpErr,
            "ContractErr": ContractErr,
        }
        for name, cls in exc_classes.items():
            def make_ctor(c, n):
                def ctor(msg=""):
                    inst = c(msg) if msg else c(n)
                    return inst
                ctor.__name__ = n
                ctor.__snafu_exc_class__ = c
                return ctor
            g.define_local(name, make_ctor(cls, name))

        # ---- Feature 1: File I/O ----
        def snafu_pe(*args, sep=" ", end="\n"):
            import sys as _sys
            print(sep.join(snafu_str(a) for a in args), end=end, file=_sys.stderr)
            return UND
        g.define_local("pe", snafu_pe)
        g.define_local("read", lambda path: open(path, 'r', encoding='utf-8').read())
        def snafu_write(path, content):
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(content)
            return UND
        g.define_local("write", snafu_write)

        def snafu_open(path, mode="r"):
            fh = open(path, mode, encoding='utf-8' if 'b' not in mode else None)
            obj = SnafuObj(type_name="File")
            obj.attrs['_fh'] = fh
            obj.attrs['rd'] = lambda: fh.read()
            obj.attrs['rl'] = lambda: fh.readline()
            obj.attrs['wr'] = lambda s: (fh.write(s), UND)[-1]
            obj.attrs['cl'] = lambda: (fh.close(), UND)[-1]
            obj.attrs['lines'] = lambda: fh.read().splitlines()
            obj.attrs['en'] = lambda: obj  # context manager enter returns self
            obj.attrs['ex'] = lambda err: (fh.close(), UND)[-1]  # context manager exit closes file
            return obj
        g.define_local("open", snafu_open)

        # ---- Feature 2: Math + Random ----
        g.define_local("rand", lambda: random.random())
        g.define_local("randint", lambda a, b: random.randint(a, b))
        g.define_local("choice", lambda lst: random.choice(lst))
        def snafu_shuffle(lst):
            random.shuffle(lst)
            return lst
        g.define_local("shuffle", snafu_shuffle)
        g.define_local("sgn", lambda x: 0 if x == 0 else (1 if x > 0 else -1))
        g.define_local("gcd", lambda a, b: math.gcd(a, b))
        g.define_local("lcm", lambda a, b: abs(a * b) // math.gcd(a, b) if a and b else 0)
        g.define_local("fact", lambda n: math.factorial(n))
        g.define_local("log2", lambda x: math.log2(x))
        g.define_local("log10", lambda x: math.log10(x))
        g.define_local("trunc", lambda x: math.trunc(x))
        g.define_local("asin", lambda x: math.asin(x))
        g.define_local("acos", lambda x: math.acos(x))
        g.define_local("atan", lambda x: math.atan(x))
        g.define_local("atan2", lambda y, x: math.atan2(y, x))
        g.define_local("sinh", lambda x: math.sinh(x))
        g.define_local("cosh", lambda x: math.cosh(x))
        g.define_local("tanh", lambda x: math.tanh(x))
        def snafu_prd(it):
            result = 1
            for x in it:
                result = result * x
            return result
        g.define_local("prd", snafu_prd)

        # ---- Feature 3: chr/ord/fmt ----
        g.define_local("chr", lambda n: chr(n))
        g.define_local("ord", lambda s: ord(s[0]))
        g.define_local("fmt", lambda x, spec: format(x, spec))

        # ---- Feature 4: Partial application ----
        def snafu_prt(f, *bound):
            def partial_fn(*args):
                merged = []
                arg_iter = iter(args)
                for b in bound:
                    if b is UND:
                        merged.append(next(arg_iter, UND))
                    else:
                        merged.append(b)
                merged.extend(arg_iter)
                return _call_value(f, merged, {})
            return partial_fn
        g.define_local("prt", snafu_prt)
        def snafu_flip(f):
            def flipped(*args):
                if len(args) >= 2:
                    args = list(args)
                    args[0], args[1] = args[1], args[0]
                return _call_value(f, list(args), {})
            return flipped
        g.define_local("flip", snafu_flip)
        g.define_local("cnst", lambda v: (lambda *a, **kw: v))

        # ---- Feature 6: sleep ----
        g.define_local("sleep", lambda ms: (time.sleep(ms / 1000), UND)[-1])

        # ---- Feature 7: uniq/dct/rp ----
        g.define_local("uniq", lambda it: list(dict.fromkeys(it)))
        g.define_local("dct", lambda it: dict(list(it)))
        g.define_local("rp", lambda v, n: [v] * int(n))

        # ---- Tail-call optimization (TCO) ----
        def snafu_tail(fn, *args, **kwargs):
            return _TailCall(fn, args, kwargs)
        g.define_local("tail", snafu_tail)

        # ---- bp() breakpoint — also register as a callable for type() checks ----
        def snafu_bp():
            # Actual bp is handled as a special form in eval_Call.
            # This fallback exists so type(bp) returns "Fn".
            return UND
        g.define_local("bp", snafu_bp)

        # ---- Atom (mutable container) ----
        def snafu_atom(initial):
            obj = SnafuObj(type_name="Atom")
            obj.attrs['_val'] = initial
            obj.attrs['get'] = lambda: obj.attrs['_val']
            def atom_set(v):
                obj.attrs['_val'] = v
                return v
            obj.attrs['set'] = atom_set
            def atom_swap(fn):
                obj.attrs['_val'] = _call_value(fn, [obj.attrs['_val']], {})
                return obj.attrs['_val']
            obj.attrs['swap'] = atom_swap
            def atom_cas(old, new):
                if obj.attrs['_val'] == old:
                    obj.attrs['_val'] = new
                    return True
                return False
            obj.attrs['cas'] = atom_cas
            return obj
        g.define_local("atom", snafu_atom)

        # ---- Complex number constructor ----
        g.define_local("cx", lambda re_part, im_part: complex(re_part, im_part))
        g.define_local("re", lambda z: z.real if isinstance(z, complex) else z)
        g.define_local("im", lambda z: z.imag if isinstance(z, complex) else 0)

        # ---- Channel constructor (for gt/aw/ch) ----
        def snafu_ch(n=0):
            q = _queue_mod.Queue(n)
            obj = SnafuObj(type_name="Channel")
            obj.attrs['_q'] = q
            obj.attrs['_closed'] = False
            def ch_send(v):
                if obj.attrs['_closed']:
                    raise ValErr("send on closed channel")
                q.put(v)
                return UND
            def ch_recv():
                if obj.attrs['_closed'] and q.empty():
                    raise ValErr("recv on closed channel")
                return q.get()
            def ch_close():
                obj.attrs['_closed'] = True
                return UND
            obj.attrs['send'] = ch_send
            obj.attrs['recv'] = ch_recv
            obj.attrs['close'] = ch_close
            return obj
        g.define_local("ch", snafu_ch)

        # ---- isa (type check) ----
        g.define_local("isa", lambda x, tn: _value_isa(x, tn))

        # ---- Transducers ----
        g.define_local("xm", lambda f: _make_transducer_map(f))
        g.define_local("xfl", lambda pred: _make_transducer_filter(pred))
        g.define_local("xtk", lambda n: _make_transducer_take(n))
        g.define_local("xdr", lambda n: _make_transducer_drop(n))
        g.define_local("xsc", lambda init, f: _make_transducer_scan(init, f))

        # ---- Lenses ----
        interp_self = self
        def snafu_lens(key):
            if isinstance(key, str):
                return SnafuLens(
                    getter=lambda obj: get_attr(obj, key, interp_self) if isinstance(obj, SnafuObj) else (obj[key] if isinstance(obj, (dict, list)) else getattr(obj, key)),
                    setter=lambda obj, val: _lens_set_attr(obj, key, val)
                )
            elif isinstance(key, int):
                return SnafuLens(
                    getter=lambda obj: obj[key],
                    setter=lambda obj, val: _lens_set_idx(obj, key, val)
                )
            else:
                raise TypeErr(f"lens key must be Str or Int, got {type_name(key)}")
        g.define_local("lens", snafu_lens)

        # ---- Feature: sl (select) for channels ----
        interp_ref = self
        def snafu_select(*channels, timeout_ms=None):
            """Wait on multiple channels, return [index, value] of first ready."""
            deadline = time.time() + timeout_ms / 1000 if timeout_ms is not None else None
            while True:
                for i, c in enumerate(channels):
                    if isinstance(c, SnafuObj) and '_q' in c.attrs:
                        if not c.attrs['_q'].empty():
                            return [i, c.attrs['_q'].get_nowait()]
                if deadline and time.time() > deadline:
                    return UND
                time.sleep(0.001)
        g.define_local("sl", snafu_select)

        # ---- Feature: fork helpers (fk_id, fk_join, fk_map, fk_tree) ----
        interp_fk = self

        def snafu_fk_id():
            """Return the current branch's fork ID."""
            return interp_fk._current_fork_id

        def snafu_fk_join():
            """Wait for all child forks of the current branch, return results list."""
            my_id = interp_fk._current_fork_id
            children = interp_fk._fork_children.get(my_id, [])
            results = []
            for cid in children:
                t = interp_fk._fork_threads.get(cid)
                if t is not None:
                    t.join()
                results.append(interp_fk._fork_results.get(cid, UND))
            return results

        def snafu_fk_map(lst, fn):
            """Fork for each element: run fn(elem) in N parallel forked scopes.
            Returns a list of Futures."""
            import copy as _copy
            if not isinstance(lst, list):
                raise TypeErr(f"fk_map: first argument must be a list, got {type_name(lst)}")
            futures = []
            for elem in lst:
                with interp_fk._lock:
                    interp_fk._fork_id_counter += 1
                    clone_id = interp_fk._fork_id_counter
                    parent_id = interp_fk._current_fork_id
                    interp_fk._fork_children.setdefault(parent_id, []).append(clone_id)
                future = SnafuObj(type_name="Future")
                future.attrs['_result'] = UND
                future.attrs['_error'] = None
                future.attrs['_fork_id'] = clone_id
                def fk_map_thread(cid=clone_id, e=elem, fut=future):
                    try:
                        result = _call_value(fn, [e], {})
                        fut.attrs['_result'] = result
                        interp_fk._fork_results[cid] = result
                    except Exception as ex:
                        fut.attrs['_error'] = ex
                        interp_fk._fork_results[cid] = UND
                t = threading.Thread(target=fk_map_thread, daemon=True)
                future.attrs['_thread'] = t
                interp_fk._fork_threads[clone_id] = t
                t.start()
                futures.append(future)
            return futures

        def snafu_fk_tree():
            """Return a SnafuObj representing the fork tree from the current branch."""
            def build_tree(fid):
                node = SnafuObj(type_name="ForkNode")
                node.attrs['id'] = fid
                node.attrs['result'] = interp_fk._fork_results.get(fid, UND)
                children = interp_fk._fork_children.get(fid, [])
                node.attrs['children'] = [build_tree(c) for c in children]
                return node
            return build_tree(interp_fk._current_fork_id)

        g.define_local("fk_id", snafu_fk_id)
        g.define_local("fk_join", snafu_fk_join)
        g.define_local("fk_map", snafu_fk_map)
        g.define_local("fk_tree", snafu_fk_tree)

        # ---- Feature: signal (pub/sub) ----
        def snafu_signal():
            obj = SnafuObj(type_name="Signal")
            listeners = []
            obj.attrs['connect'] = lambda fn: listeners.append(fn)
            obj.attrs['disconnect'] = lambda fn: listeners.remove(fn) if fn in listeners else None
            def emit(*args):
                for fn in listeners:
                    _call_value(fn, list(args), {})
                return UND
            obj.attrs['emit'] = emit
            return obj
        g.define_local("signal", snafu_signal)

        # ---- Feature: tp (top-level/global scope reference) ----
        g.define_local("tp", self.global_scope)

        # ---- Self-modification: ast_of / eval_ast / ast_new / ast_src ----
        # ast_of, eval_ast, ast_new are special forms in eval_Call.
        # Fallback definitions so type() works.
        g.define_local("ast_of", lambda x: x)
        g.define_local("eval_ast", lambda x: x)
        g.define_local("ast_new", lambda *a, **kw: UND)
        g.define_local("ast_src", lambda node: _ast_to_source(node) if isinstance(node, Node) else snafu_str(node))

        # ---- State time-travel: ps / sa / sp / st / restore ----
        # ps and st and restore are special forms in eval_Call (they need scope access).
        # sa and sp are regular functions.
        interp_self_for_state = self
        def snafu_sa(n):
            buf = interp_self_for_state.state_buffer
            if isinstance(n, int):
                idx = len(buf) + n if n < 0 else n
                if 0 <= idx < len(buf):
                    return buf[idx]
            return UND
        g.define_local("sa", snafu_sa)

        def snafu_sp(name_or_n):
            if isinstance(name_or_n, str):
                for s in reversed(interp_self_for_state.state_buffer):
                    if s.get('name') == name_or_n:
                        return s
                return UND
            return snafu_sa(name_or_n)
        g.define_local("sp", snafu_sp)

        # ps fallback (actual is a special form in eval_Call)
        g.define_local("ps", lambda name=None: interp_self_for_state._push_state(interp_self_for_state.global_scope, name))
        # restore fallback (actual is a special form in eval_Call)
        g.define_local("restore", lambda snapshot: None)

        # ---- State buffer management: ps_clear, ps_size, ps_max ----
        g.define_local("ps_clear", lambda: (interp_self_for_state.state_buffer.clear(), UND)[-1])
        g.define_local("ps_size", lambda: len(interp_self_for_state.state_buffer))
        g.define_local("ps_max", lambda n: setattr(interp_self_for_state, '_state_max_size', int(n)) or UND)

        # ---- Feature: OS Process Spawning (exec, shell, exec_lines) ----
        def snafu_exec(cmd, input_str=None):
            """Run a shell command, return [stdout, stderr, exit_code]."""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, input=input_str)
            return [result.stdout, result.stderr, result.returncode]
        def snafu_exec_lines(cmd):
            """Run and return stdout lines."""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.stdout.strip().split('\n') if result.stdout.strip() else []
        g.define_local("exec", snafu_exec)
        g.define_local("exec_lines", snafu_exec_lines)
        g.define_local("shell", lambda cmd: subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout)

        # ---- Feature: Traversal lenses and Prisms ----
        g.define_local("traverse", SnafuTraversal())
        def snafu_prism(name):
            return SnafuPrism(name)
        g.define_local("prism", snafu_prism)

        # ---- Feature: Extra transducers (xch, xdd, xpp) ----
        g.define_local("xch", _make_transducer_chunk)
        g.define_local("xdd", _make_transducer_dedup)
        g.define_local("xpp", _make_transducer_passthrough)

        # ================================================================
        #  GOLF PRELUDE — one-letter aliases, digits, combinatorics, etc.
        # ================================================================

        # ---- C1: One-letter aliases ----
        g.define_local("S", lambda s, sep=None: s.split(sep) if sep else s.split())
        g.define_local("J", lambda sep, it: sep.join(snafu_str(x) for x in it))
        g.define_local("R", lambda it: list(reversed(list(it))) if not isinstance(it, str) else it[::-1])
        g.define_local("U", lambda it: list(dict.fromkeys(it)))
        g.define_local("Z", lambda *its: [list(t) for t in zip(*its)])
        g.define_local("T", lambda matrix: [list(row) for row in zip(*matrix)])
        g.define_local("F", lambda it: [x for sub in it for x in (sub if isinstance(sub, list) else [sub])])
        g.define_local("P", snafu_p)
        g.define_local("W", lambda s: s.split())
        g.define_local("L", lambda s: s.split('\n'))
        g.define_local("N", lambda s: [int(x) for x in re.findall(r'-?\d+', s)])
        g.define_local("I", lambda: sys.stdin.read())
        g.define_local("G", lambda it, f: _list_group_by(list(it), f))

        # ---- C2: Digits and bases ----
        def _snafu_digits(n, base=10):
            n = int(n)
            if n < 0: return [-d for d in _snafu_digits(-n, base)]
            if n == 0: return [0]
            ds = []
            while n > 0:
                ds.append(n % base)
                n //= base
            return list(reversed(ds))

        def _snafu_undigits(ds, base=10):
            result = 0
            for d in ds:
                result = result * base + d
            return result

        def _snafu_to_base(n, b):
            n = int(n)
            if n == 0: return "0"
            digits_str = "0123456789abcdefghijklmnopqrstuvwxyz"
            neg = n < 0
            if neg: n = -n
            result = []
            while n > 0:
                result.append(digits_str[n % b])
                n //= b
            if neg: result.append('-')
            return ''.join(reversed(result))

        g.define_local("D", _snafu_digits)
        g.define_local("UD", _snafu_undigits)
        g.define_local("to_base", _snafu_to_base)
        g.define_local("from_base", lambda s, b: int(s, b))

        # ---- C3: Combinatorics ----
        g.define_local("X", lambda it: [list(p) for p in itertools.permutations(it)])
        g.define_local("C", lambda it, r: [list(c) for c in itertools.combinations(it, r)])
        def _snafu_powerset(it):
            items = list(it)
            return [list(s) for r in range(len(items)+1) for s in itertools.combinations(items, r)]
        g.define_local("powerset", _snafu_powerset)

        # ---- C4: Matrix ops ----
        g.define_local("rotate", lambda lst, n: lst[n:] + lst[:n])
        g.define_local("window", lambda lst, n: [lst[i:i+n] for i in range(len(lst)-n+1)])

        # ---- C5: Infinite generators ----
        def _snafu_from_n(start=0):
            def body(q, send_q):
                n = start
                while True:
                    q.put(n)
                    n += 1
                    try:
                        send_q.get(timeout=0)
                    except _queue_mod.Empty:
                        pass
            return SnafuGenerator(body)

        def _snafu_cycle(lst):
            def body(q, send_q):
                while True:
                    for x in lst:
                        q.put(x)
                        try:
                            send_q.get(timeout=0)
                        except _queue_mod.Empty:
                            pass
            return SnafuGenerator(body)

        def _snafu_repeat_val(val):
            def body(q, send_q):
                while True:
                    q.put(val)
                    try:
                        send_q.get(timeout=0)
                    except _queue_mod.Empty:
                        pass
            return SnafuGenerator(body)

        g.define_local("from_n", _snafu_from_n)
        g.define_local("cycle", _snafu_cycle)
        g.define_local("repeat_val", _snafu_repeat_val)

        # ---- C6: Bitwise functions ----
        g.define_local("bnot", lambda x: ~int(x))
        g.define_local("bxor", lambda a, b: int(a) ^ int(b))
        g.define_local("shl", lambda x, n: int(x) << int(n))
        g.define_local("shr", lambda x, n: int(x) >> int(n))

        # ---- C8: min_by / max_by ----
        g.define_local("min_by", lambda it, f: min(it, key=lambda x: _call_value(f, [x], {})))
        g.define_local("max_by", lambda it, f: max(it, key=lambda x: _call_value(f, [x], {})))

        # ---- C9: Tacit trains (fork/hook) ----
        def _snafu_fork(f, g_fn, h):
            def forked(*args, **kwargs):
                left = _call_value(f, list(args), kwargs)
                right = _call_value(h, list(args), kwargs)
                return _call_value(g_fn, [left, right], {})
            forked.__name__ = f"fork({getattr(f,'__name__','?')},{getattr(g_fn,'__name__','?')},{getattr(h,'__name__','?')})"
            return forked

        def _snafu_hook(f, g_fn):
            def hooked(*args, **kwargs):
                g_result = _call_value(g_fn, list(args), kwargs)
                return _call_value(f, list(args) + [g_result], kwargs)
            hooked.__name__ = f"hook({getattr(f,'__name__','?')},{getattr(g_fn,'__name__','?')})"
            return hooked

        g.define_local("fork", _snafu_fork)
        g.define_local("hook", _snafu_hook)

        # ---- C11: Flatten with depth (override simple flat) ----
        def _flat_with_depth(it, depth=1):
            if depth is UND:
                depth = 1
            if isinstance(depth, float) and depth == math.inf:
                depth = 9999
            return _snafu_flat_deep(list(it), int(depth))
        g.define_local("flat", _flat_with_depth)

        # ---- C12: Scan from right ----
        def _snafu_scan_right(f, lst):
            items = list(lst)
            if not items: return []
            result = [items[-1]]
            for x in reversed(items[:-1]):
                result.append(_call_value(f, [x, result[-1]], {}))
            return list(reversed(result))
        g.define_local("sr", _snafu_scan_right)

        # ---- C13: succ/pred ----
        def _snafu_succ(x):
            if isinstance(x, str) and len(x) == 1:
                return chr(ord(x[0]) + 1)
            return x + 1
        def _snafu_pred(x):
            if isinstance(x, str) and len(x) == 1:
                return chr(ord(x[0]) - 1)
            return x - 1
        g.define_local("succ", _snafu_succ)
        g.define_local("pred", _snafu_pred)

        # ---- C14: divisors ----
        g.define_local("divisors", lambda n: sorted([i for i in range(1, abs(int(n))+1) if n % i == 0]))

        # ---- Set operations (free functions) ----
        g.define_local("union", lambda a, b: list(set(a) | set(b)))
        g.define_local("inter", lambda a, b: list(set(a) & set(b)))
        g.define_local("diff", lambda a, b: list(set(a) - set(b)))
        g.define_local("symdiff", lambda a, b: list(set(a) ^ set(b)))
        g.define_local("subset", lambda a, b: set(a) <= set(b))
        g.define_local("superset", lambda a, b: set(a) >= set(b))

        # ---- take_while / drop_while / flat_map (free functions) ----
        g.define_local("take_while", lambda it, pred: _take_while(it, pred))
        g.define_local("drop_while", lambda it, pred: _drop_while(it, pred))
        g.define_local("flat_map", lambda it, fn: [y for x in it for y in _call_value(fn, [x], {})])

        # ---- unwrap / is_ok / is_err (Result helpers for |?>) ----
        g.define_local("unwrap", lambda r: r[1] if isinstance(r, list) and len(r) == 2 and r[0] == "ok" else (UND if isinstance(r, list) and r[0] == "err" else r))
        g.define_local("unwrap_or", lambda r, default: r[1] if isinstance(r, list) and len(r) == 2 and r[0] == "ok" else default)
        g.define_local("is_ok", lambda r: isinstance(r, list) and len(r) == 2 and r[0] == "ok")
        g.define_local("is_err", lambda r: isinstance(r, list) and len(r) == 2 and r[0] == "err")

        # ---- Feature: save_state / load_state (shelve/image persistence) ----
        interp_for_shelve = self
        def snafu_save_state(path):
            data = {
                'bindings': {},
                'state_buffer': interp_for_shelve.state_buffer,
            }
            s = interp_for_shelve.global_scope
            for k, v in s.bindings.items():
                if not k.startswith('__'):
                    try:
                        pickle.dumps(v)  # test serializability
                        data['bindings'][k] = v
                    except Exception:
                        pass  # skip non-serializable
            with open(path, 'wb') as fh:
                pickle.dump(data, fh)
            return path
        g.define_local("save_state", snafu_save_state)

        def snafu_load_state(path):
            with open(path, 'rb') as fh:
                data = pickle.load(fh)
            s = interp_for_shelve.global_scope
            for k, v in data.get('bindings', {}).items():
                s.assign(k, v)
            interp_for_shelve.state_buffer = data.get('state_buffer', [])
            return UND
        g.define_local("load_state", snafu_load_state)

        # ---- Feature: Logic Variables / Interpreter Level ----
        interp_for_lv = self
        def snafu_lv(name_or_level=None):
            # If called with an integer and no name (bare number), set interp level
            if isinstance(name_or_level, int) and not isinstance(name_or_level, bool):
                interp_for_lv.interp_level = name_or_level
                if name_or_level > 1:
                    interp_for_lv._install_default_meta_interpreters(name_or_level, g)
                return name_or_level
            return LogicVar(name_or_level)
        g.define_local("lv", snafu_lv)

        def snafu_unify(a, b):
            return _unify(a, b)
        g.define_local("unify", snafu_unify)

        # ---- Feature: Pipeline tee / tap ----
        # tee(f, g) returns a function; but in pipe context tee(data, f, g) is called directly
        def snafu_tee(*args):
            if len(args) >= 2 and all(callable(a) for a in args):
                # tee(f, g) — return a function for later application
                fns = args
                def apply(data):
                    return [_call_value(f, [data], {}) for f in fns]
                return apply
            elif len(args) >= 2 and not callable(args[0]):
                # tee(data, f, g, ...) — pipe mode: first arg is data
                data = args[0]
                fns = args[1:]
                return [_call_value(f, [data], {}) for f in fns]
            elif len(args) == 1:
                return args[0]
            return UND
        g.define_local("tee", snafu_tee)

        def snafu_tap(*args):
            if len(args) == 1 and callable(args[0]):
                # tap(f) — return a function
                fn = args[0]
                def apply(data):
                    _call_value(fn, [data], {})
                    return data
                return apply
            elif len(args) == 2:
                # tap(data, f) — pipe mode
                data, fn = args
                _call_value(fn, [data], {})
                return data
            return UND
        g.define_local("tap", snafu_tap)

        # ---- Feature: Constraint solver (solve) ----
        def snafu_solve(logic_vars, constraint_fn, domain=None):
            if domain is None:
                domain = range(-100, 101)
            domain = list(domain)
            vars_list = list(logic_vars)
            def backtrack(idx):
                if idx == len(vars_list):
                    return truthy(_call_value(constraint_fn, [], {}))
                for val in domain:
                    vars_list[idx].bind(val)
                    if backtrack(idx + 1):
                        return True
                    vars_list[idx].value = UND
                    vars_list[idx].bound = False
                return False
            backtrack(0)
            return UND
        g.define_local("solve", snafu_solve)

        # ---- Feature: Coercion protocol (cv) ----
        def snafu_cv(from_type, to_type, fn):
            _COERCIONS[(from_type, to_type)] = fn
            return UND
        g.define_local("cv", snafu_cv)

        # ---- Feature: Execution replay (play) ----
        interp_for_play = self
        def snafu_play(trace):
            results = []
            for entry in trace:
                if isinstance(entry, dict) and 'stmt' in entry:
                    results.append(_eval_string_as_code(entry['stmt'], interp_for_play))
            return results
        g.define_local("play", snafu_play)

        # ---- Feature: Memoization (memo) ----
        def snafu_memo(fn):
            cache = {}
            def memoized(*args, **kwargs):
                try:
                    key = args
                except Exception:
                    return _call_value(fn, list(args), kwargs)
                if key not in cache:
                    cache[key] = _call_value(fn, list(args), kwargs)
                return cache[key]
            memoized.__name__ = getattr(fn, '__name__', '<memo>')
            return memoized
        g.define_local("memo", snafu_memo)

        # ---- Feature: Lazy values ----
        g.define_local("lazy", lambda fn: LazyThunk(fn))
        g.define_local("force", lambda thunk: thunk.force() if isinstance(thunk, LazyThunk) else thunk)

        # ---- Feature: JSON serialization ----
        def snafu_to_json(val, indent=None):
            def convert(v):
                if v is UND: return None
                if isinstance(v, bool): return v
                if isinstance(v, (int, float)): return v
                if isinstance(v, Fraction): return float(v)
                if isinstance(v, str): return v
                if isinstance(v, list): return [convert(x) for x in v]
                if isinstance(v, dict): return {str(k): convert(v2) for k, v2 in v.items()}
                if isinstance(v, Variant): return {"__variant__": v.name, "fields": [convert(f) for f in v.fields]}
                return str(v)
            return json.dumps(convert(val), indent=indent)

        def snafu_from_json(s):
            def unconvert(v):
                if v is None: return UND
                if isinstance(v, list): return [unconvert(x) for x in v]
                if isinstance(v, dict):
                    return {k: unconvert(v2) for k, v2 in v.items()}
                return v
            return unconvert(json.loads(s))

        g.define_local("to_json", snafu_to_json)
        g.define_local("from_json", snafu_from_json)

        # ---- Feature: Actors ----
        def snafu_actor(handler_fn):
            obj = SnafuObj(type_name="Actor")
            msg_queue = _queue_mod.Queue()
            result_queue = _queue_mod.Queue()

            def run_actor():
                while True:
                    msg = msg_queue.get()
                    if msg is _YIELD_SENTINEL:
                        break
                    try:
                        result = _call_value(handler_fn, [msg], {})
                        result_queue.put(('ok', result))
                    except Exception as e:
                        result_queue.put(('err', e))

            t = threading.Thread(target=run_actor, daemon=True)
            t.start()

            def send(msg):
                msg_queue.put(msg)
                kind, val = result_queue.get()
                if kind == 'err':
                    raise val
                return val

            def send_async(msg):
                msg_queue.put(msg)
                return UND

            obj.attrs['send'] = send
            obj.attrs['send_async'] = send_async
            obj.attrs['stop'] = lambda: msg_queue.put(_YIELD_SENTINEL)
            return obj

        g.define_local("actor", snafu_actor)

        # ==============================================================
        # FEATURE 1: Multi-level meta-circular interpreter (lv/isrc/iast)
        # ==============================================================
        interp_for_meta = self
        # isrc — indexable object for meta-interpreter source strings
        isrc_obj = SnafuObj(type_name="InterpSource")
        isrc_obj.attrs['_interp'] = self
        g.define_local("isrc", isrc_obj)
        # iast — indexable object for meta-interpreter AST
        iast_obj = SnafuObj(type_name="InterpAST")
        iast_obj.attrs['_interp'] = self
        g.define_local("iast", iast_obj)

        # interp_level(n) — set level programmatically as a function call
        def snafu_interp_level(n=None):
            if n is None:
                return interp_for_meta.interp_level
            interp_for_meta.interp_level = int(n)
            if int(n) > 1:
                interp_for_meta._install_default_meta_interpreters(int(n), g)
            return int(n)
        g.define_local("interp_level", snafu_interp_level)

        # ==============================================================
        # FEATURE 4: Symbolic numbers
        # ==============================================================
        def snafu_sym(val):
            if isinstance(val, SymExpr):
                return val
            return SymExpr('lit', [val])
        g.define_local("sym", snafu_sym)

        # Override flat to also handle SymExpr evaluation
        _old_flat = g.lookup("flat")
        def _new_flat(it_or_sym, depth=1):
            if isinstance(it_or_sym, SymExpr):
                return it_or_sym.evaluate()
            return _old_flat(it_or_sym, depth)
        g.define_local("flat", _new_flat)

        # ==============================================================
        # FEATURE 5: Automatic per-statement state recording
        # ==============================================================
        interp_for_autorec = self
        def snafu_auto_record(enable, max_size=0):
            interp_for_autorec.auto_record = truthy(enable)
            if truthy(enable):
                interp_for_autorec._auto_step = 0
            if max_size:
                interp_for_autorec._state_max_size = int(max_size)
            return UND
        g.define_local("auto_record", snafu_auto_record)

        # ==============================================================
        # FEATURE 6: Ref (STM) — software transactional memory
        # ==============================================================
        interp_for_stm = self
        def snafu_ref(initial):
            obj = SnafuObj(type_name="Ref")
            obj.attrs['_val'] = initial
            obj.attrs['_lock'] = threading.Lock()
            def ref_get():
                return obj.attrs['_val']
            obj.attrs['get'] = ref_get
            def ref_set(v):
                if not getattr(interp_for_stm._in_dosync, 'active', False):
                    raise InterpErr("ref.set() must be inside dosync { }")
                obj.attrs['_val'] = v
                return v
            obj.attrs['set'] = ref_set
            def ref_swap(fn):
                if not getattr(interp_for_stm._in_dosync, 'active', False):
                    raise InterpErr("ref.swap() must be inside dosync { }")
                obj.attrs['_val'] = _call_value(fn, [obj.attrs['_val']], {})
                return obj.attrs['_val']
            obj.attrs['swap'] = ref_swap
            return obj
        g.define_local("ref", snafu_ref)

        # ==============================================================
        # STDLIB: HTTP (via urllib -- no external deps)
        # ==============================================================
        import urllib.request, urllib.parse

        def snafu_http_get(url, headers=None):
            req = urllib.request.Request(str(url))
            if headers:
                items = headers.items() if isinstance(headers, dict) else headers
                for k, v in items:
                    req.add_header(str(k), str(v))
            try:
                with urllib.request.urlopen(req) as resp:
                    body = resp.read().decode('utf-8')
                    return ["ok", body]
            except Exception as e:
                return ["err", str(e)]

        def snafu_http_post(url, data, headers=None):
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data).encode()
            elif isinstance(data, str):
                data = data.encode()
            req = urllib.request.Request(str(url), data=data, method='POST')
            if headers:
                items = headers.items() if isinstance(headers, dict) else headers
                for k, v in items:
                    req.add_header(str(k), str(v))
            try:
                with urllib.request.urlopen(req) as resp:
                    body = resp.read().decode('utf-8')
                    return ["ok", body]
            except Exception as e:
                return ["err", str(e)]

        g.define_local("http_get", snafu_http_get)
        g.define_local("http_post", snafu_http_post)

        # ==============================================================
        # STDLIB: URL parsing
        # ==============================================================
        g.define_local("url_encode", lambda s: urllib.parse.quote(str(s)))
        g.define_local("url_decode", lambda s: urllib.parse.unquote(str(s)))
        g.define_local("url_parse", lambda s: dict(urllib.parse.parse_qs(str(s))))

        # ==============================================================
        # STDLIB: Environment variables
        # ==============================================================
        import os as _os_mod
        g.define_local("env", lambda name, default=UND: _os_mod.environ.get(str(name), default if default is not UND else UND))
        g.define_local("env_set", lambda name, val: (_os_mod.environ.__setitem__(str(name), str(val)), UND)[-1])
        g.define_local("env_all", lambda: dict(_os_mod.environ))

        # ==============================================================
        # STDLIB: File system
        # ==============================================================
        g.define_local("exists", lambda path: _os_mod.path.exists(str(path)))
        g.define_local("is_file", lambda path: _os_mod.path.isfile(str(path)))
        g.define_local("is_dir", lambda path: _os_mod.path.isdir(str(path)))
        g.define_local("ls", lambda path=".": _os_mod.listdir(str(path)))
        g.define_local("mkdir", lambda path: (_os_mod.makedirs(str(path), exist_ok=True), UND)[-1])
        g.define_local("rm", lambda path: (_os_mod.remove(str(path)), UND)[-1])
        g.define_local("cwd", lambda: _os_mod.getcwd())
        g.define_local("cd", lambda path: (_os_mod.chdir(str(path)), UND)[-1])

        # ==============================================================
        # STDLIB: Date/time
        # ==============================================================
        import datetime as _dt_mod
        g.define_local("now", lambda: _dt_mod.datetime.now().isoformat())
        g.define_local("timestamp", lambda: time.time())
        g.define_local("date", lambda: _dt_mod.date.today().isoformat())

        # ==============================================================
        # STDLIB: Hashing
        # ==============================================================
        import hashlib as _hl_mod
        g.define_local("md5", lambda s: _hl_mod.md5(str(s).encode()).hexdigest())
        g.define_local("sha256", lambda s: _hl_mod.sha256(str(s).encode()).hexdigest())

        # ==============================================================
        # STDLIB: Command line args
        # ==============================================================
        g.define_local("args", lambda: sys.argv[2:] if len(sys.argv) > 2 else [])

        # ---- _recording init ----
        self._recording = None

    def _new_fn(self, *parents, **init):
        """Create a new object with given parents and initial attributes."""
        obj = SnafuObj(parents=parents, attrs=dict(init))
        return obj

    def _implements(self, value, proto_name):
        if isinstance(proto_name, str):
            return proto_name in self.protocols  # crude v0.1
        return False

    # -----------------------------------------------------------
    def eval_program(self, node, scope=None):
        if scope is None: scope = self.global_scope
        return self.eval_block(node, scope, new_scope=False)

    def eval_block(self, node, scope, new_scope=True):
        if new_scope:
            scope = scope.child()
        result = UND
        stmts = node.stmts
        # Store stmts in scope for sub() label-range execution
        scope.define_local('__block_stmts__', stmts)
        comefroms = {}  # label_name -> resume_index (stmt after the cf)
        i = 0
        _defer_exc = None
        try:
         _eval_node = self.eval_node
         while i < len(stmts):
            try:
                stmt = stmts[i]
                # ComeFrom: register hook and jump to the label
                if isinstance(stmt, ComeFrom):
                    comefroms[stmt.label] = i + 1
                    # Jump to the label immediately
                    found_lbl = False
                    for j, s in enumerate(stmts):
                        if isinstance(s, Label) and s.name == stmt.label:
                            i = j + 1  # resume after the label
                            found_lbl = True
                            break
                    if not found_lbl:
                        i += 1  # label not found in this block, just continue
                    continue
                # When hitting a label, check if a comefrom hook exists
                if isinstance(stmt, Label) and stmt.name in comefroms:
                    i = comefroms[stmt.name]
                    continue
                # Auto-recording: push state snapshot before each statement
                if self.auto_record:
                    self._push_state(scope, name=f"auto_{self._auto_step}")
                    self._auto_step += 1
                # Multi-level meta-circular: route through meta-interpreter if lv > 1
                if self.interp_level > 1:
                    result = self._meta_eval(stmt, scope, level=1)
                else:
                    result = _eval_node(stmt, scope)
                # Recording hook for rec { } blocks
                if getattr(self, '_recording', None) is not None:
                    self._recording.append({
                        'stmt': _ast_to_source(stmt) if isinstance(stmt, Node) else str(stmt),
                        'line': getattr(stmt, 'line', 0),
                    })
                i += 1
            except _GotoSignal as g:
                self._last_jump = (stmts, i)
                found = False
                for j, s in enumerate(stmts):
                    if isinstance(s, Label) and s.name == g.label:
                        i = j + 1  # resume after the label
                        found = True
                        break
                if not found:
                    raise  # propagate to enclosing block
            except _ResumeSignal:
                if self._last_jump is not None:
                    _, jump_idx = self._last_jump
                    i = jump_idx + 1
                    self._last_jump = None
                else:
                    i += 1  # no saved jump site, just continue
            except _ForkSignal:
                import copy as _copy
                # Deep-copy scope chain for the clone branch
                def _deep_copy_scope(sc):
                    if sc is None:
                        return None
                    new_sc = Scope(parent=_deep_copy_scope(sc.parent), name=sc.name)
                    for k, v in sc.bindings.items():
                        if k == '__block_stmts__':
                            new_sc.bindings[k] = v  # share AST nodes
                            continue
                        try:
                            new_sc.bindings[k] = _copy.deepcopy(v)
                        except Exception:
                            new_sc.bindings[k] = v
                    return new_sc
                clone_scope = _deep_copy_scope(scope)

                # Assign fork IDs
                with self._lock:
                    self._fork_id_counter += 1
                    clone_id = self._fork_id_counter
                    parent_id = self._current_fork_id
                    self._fork_children.setdefault(parent_id, []).append(clone_id)

                remaining = stmts[i:]   # includes the fk() statement itself
                interp = self

                def _fork_clone_thread(cid=clone_id, cscope=clone_scope, rem=remaining):
                    interp._fork_return_value.value = cid
                    clone_result = UND
                    for s in rem:
                        try:
                            clone_result = interp.eval_node(s, cscope)
                        except _Return as e:
                            clone_result = e.value
                            break
                        except _ForkSignal:
                            # Nested fk() inside clone — will be handled by
                            # the inner eval_block; if it escapes here just
                            # treat it as 0 for safety.
                            clone_result = UND
                            break
                        except (_Break, _Continue):
                            break
                        except Exception:
                            break
                    interp._fork_results[cid] = clone_result

                t = threading.Thread(target=_fork_clone_thread, daemon=True)
                self._fork_threads[clone_id] = t
                t.start()

                # Original branch: re-execute stmt[i] with fk() returning 0
                self._fork_return_value.value = 0
                result = self.eval_node(stmts[i], scope)
                self._fork_return_value.value = None
                i += 1
                # Continue with remaining statements normally (loop resumes)
            except _JumpIndexSignal as sig:
                if isinstance(sig.index, int):
                    if sig.relative:
                        new_i = i + sig.index
                    else:
                        new_i = sig.index
                    # If out of bounds for this block, re-raise to enclosing block
                    if new_i < 0 or new_i >= len(stmts):
                        raise
                    i = new_i
                else:
                    # 2D: [row, col] -> compute flat index from line groups
                    row_idx = sig.index[0] if len(sig.index) > 0 else 0
                    col_idx = sig.index[1] if len(sig.index) > 1 else 0
                    line_groups = {}
                    for si, s in enumerate(stmts):
                        ln = getattr(s, 'line', 0)
                        line_groups.setdefault(ln, []).append(si)
                    sorted_lines = sorted(line_groups.keys())
                    if sig.relative:
                        # Find current row/col from i
                        cur_row = 0
                        cur_col = 0
                        for ri, ln in enumerate(sorted_lines):
                            idxs = line_groups[ln]
                            if i in idxs:
                                cur_row = ri
                                cur_col = idxs.index(i)
                                break
                            elif i < (idxs[-1] if idxs else 0):
                                cur_row = ri
                                cur_col = 0
                                break
                        target_row = cur_row + row_idx
                        target_col = cur_col + col_idx
                    else:
                        target_row = row_idx
                        target_col = col_idx
                    if 0 <= target_row < len(sorted_lines):
                        target_ln = sorted_lines[target_row]
                        cols = line_groups[target_ln]
                        if 0 <= target_col < len(cols):
                            i = cols[target_col]
                        elif target_col >= len(cols):
                            i = cols[-1] + 1
                        else:
                            i = cols[0]
                    else:
                        raise  # out of bounds, propagate to enclosing block
                    if i < 0 or i >= len(stmts):
                        raise
        except (_Return, _Break, _Continue) as e:
            _defer_exc = e
        finally:
            # Run defers in LIFO order on block exit (normal or exceptional)
            if hasattr(scope, '_defers') and scope._defers:
                for d in reversed(scope._defers):
                    try:
                        self.eval_node(d, scope)
                    except Exception:
                        pass
                scope._defers = []
        if _defer_exc is not None:
            raise _defer_exc
        return result

    def eval_node(self, node, scope):
        if node is None: return UND
        method = self._eval_dispatch.get(type(node))
        if method is None:
            # Fallback: try name-based lookup (for dynamically created node types)
            method = self._eval_dispatch_by_name.get(type(node).__name__)
            if method is None:
                raise InterpErr(f"no eval method for {type(node).__name__}")
            # Cache for future calls
            self._eval_dispatch[type(node)] = method
        return method(node, scope)

    # ---- literals ----
    def eval_NumLit(self, node, scope):   return node.value
    def eval_BoolLit(self, node, scope):  return node.value
    def eval_UndLit(self, node, scope):   return UND
    def eval_OoLit(self, node, scope):    return math.inf
    def eval_Wildcard(self, node, scope): return UND

    def eval_RegexLit(self, node, scope):
        flags_int = 0
        for ch in node.flags:
            if ch == 'i': flags_int |= re.IGNORECASE
            elif ch == 'm': flags_int |= re.MULTILINE
            elif ch == 's': flags_int |= re.DOTALL
            elif ch == 'x': flags_int |= re.VERBOSE
        compiled = re.compile(node.pattern, flags_int)
        obj = SnafuObj()
        obj.attrs['_snafu_regex'] = True
        obj.attrs['_compiled'] = compiled
        obj.attrs['pattern'] = node.pattern
        obj.attrs['flags'] = node.flags
        def ma(s):
            m = compiled.search(s)
            if m is None:
                return UND
            return _wrap_match(m)
        def al(s):
            return compiled.findall(s)
        def sub(s, repl):
            return compiled.sub(repl, s)
        def spl(s):
            return [x for x in compiled.split(s) if x]
        obj.attrs['ma'] = ma
        obj.attrs['al'] = al
        obj.attrs['sub'] = sub
        obj.attrs['spl'] = spl
        return obj

    def eval_StrLit(self, node, scope):
        parts = []
        for kind, v in node.pieces:
            if kind == 'str':
                parts.append(v)
            else:
                # Re-parse interp expression
                tokens = Lexer(v, filename="<interp>").tokenize()
                ast_node = Parser(tokens).parse_expr()
                val = self.eval_node(ast_node, scope)
                parts.append(snafu_str(val))
        return ''.join(parts)

    def eval_Ident(self, node, scope):
        try:
            return scope.lookup(node.name)
        except NameErr:
            # Check Python alias table
            if node.name in _PY_ALIASES:
                return importlib.import_module(_PY_ALIASES[node.name])
            raise

    # ---- expressions ----
    def eval_BinOp(self, node, scope):
        op = node.op
        # Fast path: common operators that are in the dispatch table
        # (avoids endswith checks for element-wise/outer-product on every call)
        handler = _BINOP_DISPATCH.get(op)
        if handler is not None:
            left = self.eval_node(node.lhs, scope)
            right = self.eval_node(node.rhs, scope)
            # Inline the common case of apply_binop: no SnafuObj, no UND
            if left is not UND and right is not UND and not isinstance(left, SnafuObj) and not isinstance(right, SnafuObj):
                return handler(left, right)
            return apply_binop(op, left, right, self.strict)
        # Short-circuit boolean
        if op == '&&':
            left = self.eval_node(node.lhs, scope)
            if not truthy(left): return left
            return self.eval_node(node.rhs, scope)
        if op == '||':
            left = self.eval_node(node.lhs, scope)
            if truthy(left): return left
            return self.eval_node(node.rhs, scope)
        # Null-coalesce: short-circuit
        if op == '??':
            left = self.eval_node(node.lhs, scope)
            if left is not UND: return left
            return self.eval_node(node.rhs, scope)
        # Outer product: op.. suffix (check before element-wise since '..' ends with '.')
        if op.endswith('..') and len(op) > 2:
            base_op = op[:-2]
            left = self.eval_node(node.lhs, scope)
            right = self.eval_node(node.rhs, scope)
            return _outer_product(base_op, left, right, self.strict)
        # Element-wise: op. suffix (but not '..' or '..=' which are range ops)
        if op.endswith('.') and len(op) > 1 and op not in ('..', '..='):
            base_op = op[:-1]
            left = self.eval_node(node.lhs, scope)
            right = self.eval_node(node.rhs, scope)
            return _elementwise(base_op, left, right, self.strict)
        left = self.eval_node(node.lhs, scope)
        right = self.eval_node(node.rhs, scope)
        return apply_binop(op, left, right, self.strict)

    def eval_RangeBy(self, node, scope):
        s = self.eval_node(node.start, scope)
        e = self.eval_node(node.end, scope)
        step = self.eval_node(node.step, scope)
        if node.inclusive:
            e = e + 1
        return range(s, e, step)

    def eval_UnaryOp(self, node, scope):
        v = self.eval_node(node.operand, scope)
        if node.op == '+': return +v
        if node.op == '-': return -v
        if node.op == '!': return not truthy(v)
        if node.op == '~':
            if isinstance(v, int) and not isinstance(v, bool): return ~v
            if isinstance(v, dict): return {val: k for k, val in v.items()}
            raise TypeErr(f"no ~ for {type_name(v)}")
        if node.op == '#': return len(v)
        raise TypeErr(f"unknown unary op {node.op}")

    # ---- goto / comefrom ----
    def eval_Label(self, node, scope):
        return UND

    def eval_Goto(self, node, scope):
        if isinstance(node.target, Ident):
            raise _GotoSignal(node.target.name)
        target = self.eval_node(node.target, scope)
        if isinstance(target, str):
            raise _GotoSignal(target)
        raise TypeErr(f"goto target must be a label name")

    def eval_ComeFrom(self, node, scope):
        return UND

    # ---- green threads ----
    def eval_GreenThread(self, node, scope):
        child_scope = scope.child(name="<gt>")
        future = SnafuObj(type_name="Future")
        future.attrs['_result'] = UND
        future.attrs['_error'] = None
        interp = self
        body_node = node.body
        def thread_body():
            try:
                result = interp.eval_node(body_node, child_scope)
                future.attrs['_result'] = result
            except Exception as e:
                future.attrs['_error'] = e
        t = threading.Thread(target=thread_body, daemon=True)
        future.attrs['_thread'] = t
        t.start()
        return future

    def eval_Await(self, node, scope):
        handle = self.eval_node(node.expr, scope)
        if not isinstance(handle, SnafuObj) or handle.type_name != "Future":
            raise TypeErr(f"aw requires a Future, got {type_name(handle)}")
        t = handle.attrs.get('_thread')
        if t is not None:
            t.join()
        err = handle.attrs.get('_error')
        if err is not None:
            raise err
        return handle.attrs.get('_result', UND)

    # ---- reactive on/of ----
    def _ensure_assign_hook(self):
        """Install the assign hook on global scope if not already set."""
        if self.global_scope.on_assign_hook is None:
            interp = self
            def hook(key, value):
                # Snapshot trigger lists under the lock, then call hooks unlocked
                with interp._lock:
                    var_triggers = list(interp._triggers.get(key, []))
                    cond_triggers = list(interp._cond_triggers)
                for trig_scope, body in var_triggers:
                    try:
                        interp.eval_node(body, trig_scope)
                    except Exception:
                        pass
                for cond_node, cond_scope, body_node in cond_triggers:
                    try:
                        if truthy(interp.eval_node(cond_node, cond_scope)):
                            interp.eval_node(body_node, cond_scope)
                    except Exception:
                        pass
            self.global_scope.on_assign_hook = hook

    def eval_On(self, node, scope):
        var_name = node.var_name
        with self._lock:
            if var_name not in self._triggers:
                self._triggers[var_name] = []
            self._triggers[var_name].append((scope, node.body))
        self._ensure_assign_hook()
        return UND

    def eval_CondTrigger(self, node, scope):
        with self._lock:
            self._cond_triggers.append((node.cond, scope, node.body))
        self._ensure_assign_hook()
        return UND

    def eval_Off(self, node, scope):
        var_name = node.var_name
        with self._lock:
            if var_name == '__all_cond__':
                self._cond_triggers.clear()
            elif var_name in self._triggers:
                del self._triggers[var_name]
        return UND

    # ---- function power f^n ----
    def eval_FnPower(self, node, scope):
        fn = self.eval_node(node.fn, scope)
        n = self.eval_node(node.power, scope)
        if not callable(fn):
            raise TypeErr(f"^ requires callable, got {type_name(fn)}")
        n = int(n)
        if n == 0:
            return lambda *a, **k: a[0] if a else UND
        if n > 0:
            def composed(*args, **kwargs):
                result = _call_value(fn, list(args), kwargs)
                for _ in range(n - 1):
                    result = _call_value(fn, [result], {})
                return result
            return composed
        # Negative power: function inverse
        inv_fn = self._invert_function(fn, scope)
        abs_n = -n
        if abs_n == 1:
            return inv_fn
        # f^-2 = (f^-1)^2
        def composed_inv(*args, **kwargs):
            result = _call_value(inv_fn, list(args), kwargs)
            for _ in range(abs_n - 1):
                result = _call_value(inv_fn, [result], {})
            return result
        return composed_inv

    def _invert_function(self, fn, scope):
        """Try to derive the algebraic inverse of a single-expression function."""
        lam = getattr(fn, '__snafu_lambda__', None)
        if lam is None:
            raise InterpErr("cannot invert: not a Snafu function")
        if not lam.params or len([p for p in lam.params if p.kind == 'pos']) != 1:
            raise InterpErr("cannot invert: must have exactly 1 parameter")
        param_name = lam.params[0].name
        body = lam.body
        # Unwrap ExprStmt / Block wrappers to get the expression
        expr = body
        if isinstance(expr, Block) and len(expr.stmts) == 1:
            expr = expr.stmts[0]
        if isinstance(expr, BlockExpr) and len(expr.stmts) == 1:
            expr = expr.stmts[0]
        if isinstance(expr, ExprStmt):
            expr = expr.expr
        steps = _build_inverse_steps(expr, param_name)
        if steps is None:
            raise InterpErr("cannot invert: expression too complex")
        return _make_inverse_fn(steps, self, scope)

    # ---- sub (label range exec) ----
    def eval_Sub(self, node, scope):
        start_name = self.eval_node(node.start, scope)
        end_name = self.eval_node(node.end, scope)
        if isinstance(node.start, Ident): start_name = node.start.name
        if isinstance(node.end, Ident): end_name = node.end.name
        # Look for __block_stmts__ in scope
        stmts = None
        s = scope
        while s is not None:
            if '__block_stmts__' in s.bindings:
                stmts = s.bindings['__block_stmts__']
                break
            s = s.parent
        if stmts is None:
            raise InterpErr("sub: no enclosing block with labels found")
        # Find label indices
        start_idx = None
        end_idx = None
        for j, stmt in enumerate(stmts):
            if isinstance(stmt, Label):
                if stmt.name == start_name:
                    start_idx = j
                if stmt.name == end_name:
                    end_idx = j
        if start_idx is None:
            raise InterpErr(f"sub: label '{start_name}' not found")
        if end_idx is None:
            raise InterpErr(f"sub: label '{end_name}' not found")
        # Execute statements between start (exclusive) and end (exclusive)
        result = UND
        for stmt in stmts[start_idx + 1 : end_idx]:
            result = self.eval_node(stmt, scope)
        return result

    # ---- resume ----
    def eval_Resume(self, node, scope):
        raise _ResumeSignal()

    # ---- reduce / scan ----
    def eval_ReduceOp(self, node, scope):
        val = self.eval_node(node.operand, scope)
        items = list(val)
        if not items:
            return UND
        result = items[0]
        for x in items[1:]:
            result = apply_binop(node.op, result, x, self.strict)
        return result

    def eval_ScanOp(self, node, scope):
        val = self.eval_node(node.operand, scope)
        items = list(val)
        if not items:
            return []
        result = [items[0]]
        for x in items[1:]:
            result.append(apply_binop(node.op, result[-1], x, self.strict))
        return result

    def eval_Ternary(self, node, scope):
        c = self.eval_node(node.cond, scope)
        if truthy(c): return self.eval_node(node.then, scope)
        return self.eval_node(node.else_, scope)

    def eval_Pipe(self, node, scope):
        v = self.eval_node(node.lhs, scope)
        # Try-pipe: |?> — wrap in ok/err
        if node.op == '|?>':
            try:
                if isinstance(node.rhs, Call):
                    pos_args, kwargs = self._eval_call_args(node.rhs.args, node.rhs.kwargs, scope)
                    pos_args = [v] + pos_args
                    fn = self.eval_node(node.rhs.fn, scope)
                    result = _call_value(fn, pos_args, kwargs)
                else:
                    fn = self.eval_node(node.rhs, scope)
                    result = _call_value(fn, [v], {})
                return ["ok", result]
            except Exception as e:
                msg = e.msg if isinstance(e, SnafuError) else str(e)
                return ["err", msg]
        # rhs should be a callable or a Call node
        if isinstance(node.rhs, Call):
            # Evaluate existing args first
            pos_args, kwargs = self._eval_call_args(node.rhs.args, node.rhs.kwargs, scope)
            # Insert v at first slot (|>) or last (|>>)
            if node.op == '|>':
                pos_args = [v] + pos_args
            else:
                pos_args = pos_args + [v]
            fn = self.eval_node(node.rhs.fn, scope)
            return _call_value(fn, pos_args, kwargs)
        else:
            fn = self.eval_node(node.rhs, scope)
            return _call_value(fn, [v], {})

    _SPECIAL_FORM_NAMES = frozenset({'ev', 'bp', 'tail', 'sub', 'ast_of', 'eval_ast', 'ast_new', 'ps', 'st', 'restore'})

    def eval_Call(self, node, scope):
        # Fast path: skip all special-form checks for non-Ident or non-special names
        if isinstance(node.fn, Ident) and node.fn.name not in self._SPECIAL_FORM_NAMES:
            try:
                fn = scope.lookup(node.fn.name)
            except NameErr:
                if node.fn.name in _PY_ALIASES:
                    fn = importlib.import_module(_PY_ALIASES[node.fn.name])
                else:
                    raise
            # Macro invocation: pass unevaluated AST nodes, then eval the result
            if isinstance(fn, SnafuMacro):
                ast_args = [arg_node for _kind, arg_node in node.args]
                result = _call_value(fn.fn, ast_args, {})
                if isinstance(result, Node):
                    return self.eval_node(result, scope)
                return result
            pos_args, kwargs = self._eval_call_args(node.args, node.kwargs, scope)
            if getattr(node, '_is_tail_call', False):
                raise _TailCallExc(fn, pos_args, kwargs)
            return _call_value(fn, pos_args, kwargs)
        # Special form: ev("code", sc=scope, lv=level) evaluates in given or current scope
        if isinstance(node.fn, Ident) and node.fn.name == 'ev':
            if len(node.args) >= 1:
                code_str = self.eval_node(node.args[0][1], scope)
                if isinstance(code_str, str):
                    eval_scope = scope  # default: caller scope
                    if 'sc' in node.kwargs:
                        sc_val = self.eval_node(node.kwargs['sc'], scope)
                        if isinstance(sc_val, Scope):
                            eval_scope = sc_val
                    # lv= keyword: set interpreter level for evaluation
                    eval_level = None
                    if 'lv' in node.kwargs:
                        eval_level = self.eval_node(node.kwargs['lv'], scope)
                    if eval_level is not None and isinstance(eval_level, int) and eval_level > 1:
                        old_level = self.interp_level
                        self.interp_level = eval_level
                        try:
                            return _eval_string_as_code(code_str, self, eval_scope)
                        finally:
                            self.interp_level = old_level
                    return _eval_string_as_code(code_str, self, eval_scope)
        # Special form: bp() inline debugger
        if isinstance(node.fn, Ident) and node.fn.name == 'bp':
            return self._breakpoint(scope)
        # Special form: tail(fn, args...) for TCO — returns _TailCall sentinel
        if isinstance(node.fn, Ident) and node.fn.name == 'tail':
            pos_args, kwargs = self._eval_call_args(node.args, node.kwargs, scope)
            if not pos_args:
                raise ArgErr("tail() requires at least a function argument")
            fn = pos_args[0]
            return _TailCall(fn, pos_args[1:], kwargs)
        # Special form: sub(label1, label2) — execute between labels
        if isinstance(node.fn, Ident) and node.fn.name == 'sub':
            if len(node.args) == 2:
                start_node = node.args[0][1]
                end_node = node.args[1][1]
                start_name = start_node.name if isinstance(start_node, Ident) else self.eval_node(start_node, scope)
                end_name = end_node.name if isinstance(end_node, Ident) else self.eval_node(end_node, scope)
                # Look for __block_stmts__ in scope
                stmts = None
                s = scope
                while s is not None:
                    if '__block_stmts__' in s.bindings:
                        stmts = s.bindings['__block_stmts__']
                        break
                    s = s.parent
                if stmts is None:
                    raise InterpErr("sub: no enclosing block with labels found")
                start_idx = None
                end_idx = None
                for j, stmt in enumerate(stmts):
                    if isinstance(stmt, Label):
                        if stmt.name == start_name:
                            start_idx = j
                        if stmt.name == end_name:
                            end_idx = j
                if start_idx is None:
                    raise InterpErr(f"sub: label '{start_name}' not found")
                if end_idx is None:
                    raise InterpErr(f"sub: label '{end_name}' not found")
                result = UND
                for stmt in stmts[start_idx + 1 : end_idx]:
                    result = self.eval_node(stmt, scope)
                return result
        # Special form: ast_of(expr) — return the raw AST node WITHOUT evaluating
        if isinstance(node.fn, Ident) and node.fn.name == 'ast_of':
            if node.args:
                return node.args[0][1]  # raw AST node, unevaluated
            return UND
        # Special form: eval_ast(node) — evaluate an AST node in current scope
        if isinstance(node.fn, Ident) and node.fn.name == 'eval_ast':
            if node.args:
                ast_node = self.eval_node(node.args[0][1], scope)
                # Optional 2nd arg: scope to evaluate in
                eval_scope = scope
                if len(node.args) >= 2:
                    s = self.eval_node(node.args[1][1], scope)
                    if isinstance(s, Scope):
                        eval_scope = s
                if isinstance(ast_node, Node):
                    return self.eval_node(ast_node, eval_scope)
            return UND
        # Special form: ast_new(type_name, **fields) — create a new AST node
        if isinstance(node.fn, Ident) and node.fn.name == 'ast_new':
            if node.args:
                tname = self.eval_node(node.args[0][1], scope)
                if isinstance(tname, str) and tname in _AST_TYPES:
                    cls = _AST_TYPES[tname]
                    kws = {}
                    for k, v_node in node.kwargs.items():
                        kws[k] = self.eval_node(v_node, scope)
                    return cls(**kws)
                raise ValErr(f"ast_new: unknown AST type '{tname}'")
            return UND
        # Special form: ps() / ps("name") — push state snapshot
        if isinstance(node.fn, Ident) and node.fn.name == 'ps':
            name = None
            if node.args:
                name = self.eval_node(node.args[0][1], scope)
            return self._push_state(scope, name)
        # Special form: st() — snapshot current state without pushing
        if isinstance(node.fn, Ident) and node.fn.name == 'st':
            if not node.args:
                return {'name': None, 'bindings': self._snapshot_scope(scope), 'index': -1}
            # Fall through to regular call (st(iterable) = set constructor)
        # Special form: restore(snapshot) — restore bindings from snapshot into current scope
        if isinstance(node.fn, Ident) and node.fn.name == 'restore':
            if node.args:
                snapshot = self.eval_node(node.args[0][1], scope)
                if isinstance(snapshot, dict) and 'bindings' in snapshot:
                    for k, v in snapshot['bindings'].items():
                        scope.assign(k, v)
                return UND
            return UND
        fn = self.eval_node(node.fn, scope)
        # Macro invocation: pass unevaluated AST nodes, then eval the result
        if isinstance(fn, SnafuMacro):
            ast_args = [arg_node for _kind, arg_node in node.args]
            result = _call_value(fn.fn, ast_args, {})
            # If the macro returned an AST node, evaluate it
            if isinstance(result, Node):
                return self.eval_node(result, scope)
            return result
        pos_args, kwargs = self._eval_call_args(node.args, node.kwargs, scope)
        # Implicit tail-call optimization: if this call is in tail position, raise _TailCallExc
        if getattr(node, '_is_tail_call', False):
            raise _TailCallExc(fn, pos_args, kwargs)
        return _call_value(fn, pos_args, kwargs)

    def _eval_call_args(self, args, kwargs, scope):
        pos_args = []
        for kind, val in args:
            v = self.eval_node(val, scope)
            if kind == 'star':
                pos_args.extend(v)
            else:
                pos_args.append(v)
        kws = {}
        for k, v_node in kwargs.items():
            if k.startswith('__dstar__'):
                d = self.eval_node(v_node, scope)
                kws.update(d)
            else:
                kws[k] = self.eval_node(v_node, scope)
        return pos_args, kws

    def eval_Index(self, node, scope):
        target = self.eval_node(node.target, scope)
        key = self.eval_node(node.key, scope)
        return index_into(target, key, self.strict)

    def eval_Slice(self, node, scope):
        target = self.eval_node(node.target, scope)
        start = self.eval_node(node.start, scope) if node.start else None
        end = self.eval_node(node.end, scope) if node.end else None
        step = self.eval_node(node.step, scope) if node.step else None
        if start is UND: start = None
        if end is UND: end = None
        if step is UND: step = None
        if isinstance(target, (list, str, range, tuple)):
            return target[slice(start, end, step)]
        if isinstance(target, (dict, types.MappingProxyType)):
            keys = list(target.keys())[slice(start, end, step)]
            return {k: target[k] for k in keys}
        raise TypeErr(f"cannot slice {type_name(target)}")

    def eval_Attr(self, node, scope):
        target = self.eval_node(node.target, scope)
        return get_attr(target, node.name, self)

    def eval_SafeNav(self, node, scope):
        target = self.eval_node(node.target, scope)
        if target is UND:
            return UND
        return get_attr(target, node.name, self)

    def eval_Lambda(self, node, scope):
        return make_function(node, scope, self)

    def eval_VarVar(self, node, scope):
        val = self.eval_node(node.expr, scope)
        for _ in range(node.levels):
            if not isinstance(val, str):
                raise TypeErr(f"variable-variable requires string name, got {type_name(val)}")
            val = scope.lookup(val)
        return val

    def eval_FrozenExpr(self, node, scope):
        inner = self.eval_node(node.items, scope)
        if isinstance(inner, list):
            return tuple(inner)
        if isinstance(inner, dict):
            return types.MappingProxyType(inner)
        return inner

    def _breakpoint(self, scope):
        """Inline debugger REPL with the current scope."""
        print(f"[bp] Breakpoint hit. Scope vars: {list(scope.bindings.keys())}")
        while True:
            try:
                line = input("bp> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            stripped = line.strip()
            if stripped in ('c', 'continue', ''):
                break
            if stripped == 'vars':
                s = scope
                while s is not None:
                    for k, v in s.bindings.items():
                        print(f"  {k} = {snafu_repr(v)}")
                    s = s.parent
                continue
            try:
                result = _eval_string_as_code(line, self, scope)
                if result is not UND:
                    print(snafu_repr(result))
            except Exception as e:
                print(f"! {e}")
        return UND

    @staticmethod
    def _cheap_copy(v):
        """Copy mutable values, share immutable ones."""
        if isinstance(v, list):
            return list(v)  # shallow list copy
        if isinstance(v, dict):
            return dict(v)  # shallow dict copy
        # Everything else (int, float, str, bool, Fraction, tuple, functions,
        # SnafuObj, etc.) is immutable or intentionally shared.
        return v

    def _snapshot_scope(self, scope):
        """Snapshot all bindings — cheap copy (shallow-copy mutables, share immutables)."""
        result = {}
        s = scope
        while s is not None:
            for k, v in s.bindings.items():
                if k not in result and not k.startswith('__'):
                    result[k] = self._cheap_copy(v)
            s = s.parent
        return result

    def _push_state(self, scope, name=None):
        """Push a snapshot of the current scope chain onto the state buffer."""
        snapshot = {
            'name': name,
            'bindings': self._snapshot_scope(scope),
            'index': len(self.state_buffer),
        }
        with self._lock:
            self.state_buffer.append(snapshot)
            # Enforce max buffer size
            if self._state_max_size > 0:
                while len(self.state_buffer) > self._state_max_size:
                    self.state_buffer.pop(0)
            return len(self.state_buffer) - 1

    # ---- Feature 1: Multi-level meta-circular interpreter ----
    def _install_default_meta_interpreters(self, max_level, scope):
        with self._lock:
            for level in range(1, max_level):
                if level not in self.meta_interpreters:
                    # Try to load the full self-interpreter
                    self_interp_src = self._load_self_interpreter()
                    if self_interp_src:
                        self.meta_interp_sources[level] = self_interp_src
                        # Execute in a private scope to define seval
                        private_scope = scope.child(name="meta_interp")
                        _eval_string_as_code(self_interp_src, self, private_scope)
                        # The self-interpreter defines 'seval' -- wrap it
                        try:
                            seval_fn = private_scope.lookup('seval')
                            self.meta_interpreters[level] = seval_fn
                        except NameErr:
                            # Fallback to simple pass-through
                            src = 'f(node, scope) -> eval_ast(node)'
                            self.meta_interp_sources[level] = src
                            fn = _eval_string_as_code(src, self, scope)
                            self.meta_interpreters[level] = fn
                    else:
                        # Fallback
                        src = 'f(node, scope) -> eval_ast(node)'
                        self.meta_interp_sources[level] = src
                        fn = _eval_string_as_code(src, self, scope)
                        self.meta_interpreters[level] = fn

    def _load_self_interpreter(self):
        """Try to load examples/self_interp.snf, stripping demo code."""
        import os
        # Look relative to snafu.py's location
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'examples', 'self_interp.snf')
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # Strip everything after the demos section
        for marker in ['# ===== Demos', '# === Demos', '# Demo ']:
            idx = src.find(marker)
            if idx > 0:
                src = src[:idx]
                break
        return src.strip()

    _in_meta_eval = False

    def _meta_eval(self, node, scope, level=1):
        """Evaluate a node through the meta-interpreter chain.
        Prevents re-entry: the meta-interpreter's own body runs directly."""
        if self._in_meta_eval:
            return self.eval_node(node, scope)
        if level >= self.interp_level or level not in self.meta_interpreters:
            return self.eval_node(node, scope)
        meta_fn = self.meta_interpreters[level]
        self._in_meta_eval = True
        try:
            return _call_value(meta_fn, [node, scope], {})
        finally:
            self._in_meta_eval = False

    def eval_LvDecl(self, node, scope):
        n = self.eval_node(node.level, scope) if isinstance(node.level, Node) else node.level
        n = int(n)
        self.interp_level = n
        if n > 1:
            self._install_default_meta_interpreters(n, scope)
        return UND

    def eval_DoSync(self, node, scope):
        self._in_dosync.active = True
        try:
            return self.eval_node(node.body, scope)
        finally:
            self._in_dosync.active = False

    def eval_JumpAbs(self, node, scope):
        coords = [self.eval_node(c, scope) for c in node.coords]
        idx = coords[0] if len(coords) == 1 else coords
        raise _JumpIndexSignal(idx, relative=False)

    def eval_JumpRel(self, node, scope):
        offsets = [self.eval_node(o, scope) for o in node.offsets]
        idx = offsets[0] if len(offsets) == 1 else offsets
        raise _JumpIndexSignal(idx, relative=True)

    def eval_PersistVar(self, node, scope):
        import os, pickle as _pickle
        key = f"{self.source_file or '<repl>'}:{node.name}"
        persist_dir = os.path.expanduser("~/.snafu/persist")
        os.makedirs(persist_dir, exist_ok=True)
        path = os.path.join(persist_dir, key.replace('/', '_').replace('\\', '_').replace(':', '_') + ".pkl")
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    value = _pickle.load(f)
                scope.assign(node.name, value)
                return value
            except Exception:
                pass
        value = self.eval_node(node.init, scope)
        scope.assign(node.name, value)
        try:
            with open(path, 'wb') as f:
                _pickle.dump(value, f)
        except Exception:
            pass
        return value

    def eval_Quantifier(self, node, scope):
        it = self.eval_node(node.iter, scope)
        for item in it:
            child = scope.child()
            child.define_local(node.var, item)
            result = truthy(self.eval_node(node.pred, child))
            if node.kind == 'some' and result:
                return True
            if node.kind == 'every' and not result:
                return False
        return node.kind == 'every'

    def eval_Defer(self, node, scope):
        if not hasattr(scope, '_defers'):
            scope._defers = []
        scope._defers.append(node.expr)
        return UND

    def eval_ListExpr(self, node, scope):
        # Determine if all positional: list; else: dict-like (Snafu collection)
        has_kv = any(e.kind == 'kv' for e in node.items)
        if has_kv:
            result = {}
            pos_idx = 0
            for e in node.items:
                if e.kind == 'kv':
                    k = self.eval_node(e.key, scope) if isinstance(e.key, Node) else e.key
                    # If key is an Ident, use its NAME as string key (Lua-style)
                    if isinstance(e.key, Ident):
                        k = e.key.name
                    elif isinstance(e.key, Node):
                        k = self.eval_node(e.key, scope)
                    result[k] = self.eval_node(e.value, scope)
                    if isinstance(k, int) and k >= pos_idx: pos_idx = k + 1
                elif e.kind == 'spread':
                    src = self.eval_node(e.value, scope)
                    if isinstance(src, list):
                        for x in src: result[pos_idx] = x; pos_idx += 1
                    elif isinstance(src, dict):
                        result.update(src)
                else:
                    result[pos_idx] = self.eval_node(e.value, scope)
                    pos_idx += 1
            return result
        # All positional — return a list
        result = []
        for e in node.items:
            if e.kind == 'spread':
                src = self.eval_node(e.value, scope)
                if isinstance(src, list):
                    result.extend(src)
                else:
                    result.append(src)
            else:
                result.append(self.eval_node(e.value, scope))
        return result

    def eval_Block(self, node, scope):
        return self.eval_block(node, scope, new_scope=True)

    def eval_BlockExpr(self, node, scope):
        return self.eval_block(node, scope, new_scope=True)

    # ---- statements ----
    def eval_ExprStmt(self, node, scope):
        return self.eval_node(node.expr, scope)

    def eval_Assign(self, node, scope):
        # ~= tracking: store AST node, don't evaluate
        if node.op == '~=' and isinstance(node.target, Ident):
            tracking = _Tracking(node.value, scope, self)
            scope.assign(node.target.name, tracking)
            return UND
        # := alias: create an alias reference
        if node.op == ':=' and isinstance(node.target, Ident):
            if isinstance(node.value, Ident):
                rhs_name = node.value.name
                target_scope, raw = scope._find_binding_scope(rhs_name)
                if target_scope is None:
                    raise NameErr(f"name '{rhs_name}' not found for alias")
                # If the RHS is already an alias, follow it
                if isinstance(raw, _Alias):
                    alias = _Alias(raw.scope, raw.name)
                else:
                    alias = _Alias(target_scope, rhs_name)
                scope.assign(node.target.name, alias)
                return UND
            # Non-ident RHS: evaluate and assign normally
            value = self.eval_node(node.value, scope)
            scope.assign(node.target.name, value)
            return value
        value = self.eval_node(node.value, scope)
        return self._assign_to(node.target, value, scope, node.op)

    def _assign_to(self, target, value, scope, op='='):
        if isinstance(target, Ident):
            if op == '=':
                scope.assign(target.name, value)
            elif op == ':=':
                scope.assign(target.name, value)  # alias handled in eval_Assign; fallback plain assign
            elif op == '~=':
                scope.assign(target.name, value)  # tracking handled in eval_Assign; fallback plain assign
            elif op == '.=':
                old = scope.lookup(target.name) if scope.contains(target.name) else UND
                new_val = _call_value(value, [old], {})
                scope.assign(target.name, new_val)
                return new_val
            else:
                # compound
                old = scope.lookup(target.name) if scope.contains(target.name) else UND
                bop = op[:-1]  # strip =
                new_val = apply_binop(bop, old, value, self.strict)
                scope.assign(target.name, new_val)
            return value
        if isinstance(target, Attr):
            obj = self.eval_node(target.target, scope)
            if op == '.=':
                if isinstance(obj, SnafuObj):
                    old = obj.attrs.get(target.name, UND)
                elif isinstance(obj, dict):
                    old = obj.get(target.name, UND)
                elif hasattr(obj, target.name):
                    old = getattr(obj, target.name)
                else:
                    old = UND
                new_val = _call_value(value, [old], {})
                if isinstance(obj, SnafuObj):
                    obj.attrs[target.name] = new_val
                elif isinstance(obj, dict):
                    obj[target.name] = new_val
                elif hasattr(obj, target.name):
                    setattr(obj, target.name, new_val)
                else:
                    raise TypeErr(f"cannot set attribute on {type_name(obj)}")
                return new_val
            if isinstance(obj, SnafuObj):
                obj.attrs[target.name] = value
            elif isinstance(obj, dict):
                obj[target.name] = value
            elif hasattr(obj, target.name) or isinstance(obj, Node):
                setattr(obj, target.name, value)
            else:
                raise TypeErr(f"cannot set attribute on {type_name(obj)}")
            return value
        if isinstance(target, Index):
            obj = self.eval_node(target.target, scope)
            key = self.eval_node(target.key, scope)
            # isrc[n] = "source" — recompile meta-interpreter
            if isinstance(obj, SnafuObj) and obj.type_name == "InterpSource":
                level = int(key)
                src = value
                self.meta_interp_sources[level] = src
                fn = _eval_string_as_code(src, self, scope)
                self.meta_interpreters[level] = fn
                return value
            if op == '.=':
                old = index_into(obj, key, self.strict)
                new_val = _call_value(value, [old], {})
                if isinstance(obj, list):
                    if isinstance(key, int):
                        while len(obj) <= key: obj.append(UND)
                        obj[key] = new_val
                    else:
                        raise TypeErr("list index must be int")
                elif isinstance(obj, dict):
                    obj[key] = new_val
                else:
                    raise TypeErr(f"cannot index-assign into {type_name(obj)}")
                return new_val
            if isinstance(obj, list):
                if isinstance(key, int):
                    while len(obj) <= key: obj.append(UND)
                    obj[key] = value
                else:
                    raise TypeErr("list index must be int")
            elif isinstance(obj, dict):
                obj[key] = value
            else:
                raise TypeErr(f"cannot index-assign into {type_name(obj)}")
            return value
        if isinstance(target, ListExpr):
            # Tuple/list destructure
            _destructure_assign(target, value, scope, interp=self)
            return value
        raise TypeErr(f"cannot assign to {type(target).__name__}")

    def eval_If(self, node, scope):
        if truthy(self.eval_node(node.cond, scope)):
            return self.eval_node(node.then, scope)
        for cond, then in node.elifs:
            if truthy(self.eval_node(cond, scope)):
                return self.eval_node(then, scope)
        if node.else_:
            return self.eval_node(node.else_, scope)
        return UND

    def eval_For(self, node, scope):
        child = scope.child()
        # loop_tail
        tail = node.loop_tail
        if 'bf' in tail: self.eval_node(tail['bf'], child)
        result = UND
        completed_naturally = True
        it = self.eval_node(node.iter, scope)
        try:
            iter_ = iter(it)
            first = True
            for item in iter_:
                if not first and 'bt' in tail:
                    self.eval_node(tail['bt'], child)
                first = False
                match_bindings = match_pattern(node.pattern, item)
                if match_bindings is None:
                    continue
                iter_scope = child.child()
                for k, v in match_bindings.items():
                    iter_scope.define_local(k, v)
                if node.filter:
                    kind, fexpr = node.filter
                    fv = self.eval_node(fexpr, iter_scope)
                    if kind == 'if' and not truthy(fv): continue
                    if kind == 'wh' and not truthy(fv): break
                    if kind == 'un' and truthy(fv): break
                try:
                    result = self.eval_node(node.body, iter_scope)
                except _Break as e:
                    completed_naturally = False
                    if e.level > 1: raise _Break(e.level - 1)
                    break
                except _Continue as e:
                    if e.level > 1: raise _Continue(e.level - 1, e.advance)
                    continue
                if 'af' in tail: self.eval_node(tail['af'], iter_scope)
        finally:
            pass
        if completed_naturally and 'el' in tail:
            result = self.eval_node(tail['el'], child)
        if 'fi' in tail: self.eval_node(tail['fi'], child)
        return result

    def eval_While(self, node, scope):
        child = scope.child()
        tail = node.loop_tail
        if 'bf' in tail: self.eval_node(tail['bf'], child)
        result = UND
        completed_naturally = True
        first = True
        while True:
            cond_v = truthy(self.eval_node(node.cond, child))
            if node.is_until: cond_v = not cond_v
            if not cond_v: break
            if not first and 'bt' in tail:
                self.eval_node(tail['bt'], child)
            first = False
            try:
                result = self.eval_node(node.body, child)
            except _Break as e:
                completed_naturally = False
                if e.level > 1: raise _Break(e.level - 1)
                break
            except _Continue as e:
                if e.level > 1: raise _Continue(e.level - 1, e.advance)
                continue
            if 'af' in tail: self.eval_node(tail['af'], child)
        if completed_naturally and 'el' in tail:
            result = self.eval_node(tail['el'], child)
        if 'fi' in tail: self.eval_node(tail['fi'], child)
        return result

    def eval_Loop(self, node, scope):
        child = scope.child()
        tail = node.loop_tail
        count = None
        if node.count is not None:
            count = self.eval_node(node.count, scope)
        if 'bf' in tail: self.eval_node(tail['bf'], child)
        result = UND
        completed_naturally = True
        i = 0
        first = True
        while count is None or i < count:
            if not first and 'bt' in tail:
                self.eval_node(tail['bt'], child)
            first = False
            try:
                result = self.eval_node(node.body, child)
            except _Break as e:
                completed_naturally = False
                if e.level > 1: raise _Break(e.level - 1)
                break
            except _Continue as e:
                if e.level > 1: raise _Continue(e.level - 1, e.advance)
                i += 1
                continue
            if 'af' in tail: self.eval_node(tail['af'], child)
            i += 1
        if completed_naturally and 'el' in tail:
            result = self.eval_node(tail['el'], child)
        if 'fi' in tail: self.eval_node(tail['fi'], child)
        return result

    def eval_Match(self, node, scope):
        v = self.eval_node(node.target, scope)
        for arm in node.arms:
            bindings = match_pattern(arm.pattern, v)
            if bindings is None:
                continue
            arm_scope = scope.child()
            for k, val in bindings.items():
                arm_scope.define_local(k, val)
            if arm.guard:
                g = self.eval_node(arm.guard, arm_scope)
                if not truthy(g):
                    continue
            return self.eval_node(arm.body, arm_scope)
        if self.strict:
            raise MatchErr(f"no match for {snafu_repr(v)}")
        return UND

    def eval_Try(self, node, scope):
        result = UND
        try:
            result = self.eval_node(node.body, scope)
        except (_Return, _Break, _Continue, _GotoSignal):
            raise  # control-flow signals pass through unchanged
        except Exception as raw_e:
            # Wrap non-Snafu exceptions (Python ValueError etc.) so ty/ex catches them
            e = raw_e if isinstance(raw_e, SnafuError) else SnafuError(str(raw_e))
            handled = False
            for exc in node.excepts:
                if exc.type_name is None or _exc_matches(e, exc.type_name):
                    exc_scope = scope.child()
                    if exc.var_name:
                        exc_scope.define_local(exc.var_name, e)
                    self.exc_stack.append(e)
                    try:
                        result = self.eval_node(exc.body, exc_scope)
                        handled = True
                        break
                    finally:
                        self.exc_stack.pop()
            if not handled:
                if node.finally_:
                    self.eval_node(node.finally_, scope)
                raise
        if node.finally_:
            self.eval_node(node.finally_, scope)
        return result

    def eval_Raise(self, node, scope):
        if node.exc is None:
            # Bare `rs` — re-raise current exception
            if not self.exc_stack:
                raise SnafuError("bare rs outside except")
            raise self.exc_stack[-1]
        exc_val = self.eval_node(node.exc, scope)
        cause = self.eval_node(node.cause, scope) if node.cause else None
        if isinstance(exc_val, str):
            e = SnafuError(exc_val, cause=cause)
        elif isinstance(exc_val, SnafuError):
            e = exc_val
            if cause is not None: e.cause = cause
        else:
            e = SnafuError(str(exc_val), cause=cause)
        raise e

    def eval_Return(self, node, scope):
        v = self.eval_node(node.value, scope) if node.value else UND
        raise _Return(v)

    def eval_Break(self, node, scope):
        raise _Break(level=node.level)

    def eval_Continue(self, node, scope):
        raise _Continue(level=node.level, advance=node.advance)

    def eval_Yield(self, node, scope):
        val = self.eval_node(node.value, scope) if node.value else UND
        try:
            q = scope.lookup('__yield_queue__')
        except NameErr:
            raise InterpErr("y (yield) used outside coroutine")
        q.put(val)
        # Wait for a value to be sent back (bidirectional yield)
        try:
            send_q = scope.lookup('__send_queue__')
            sent = send_q.get()
        except NameErr:
            sent = UND
        return sent

    def eval_CoroutineDecl(self, node, scope):
        interp = self
        lam = Lambda(line=node.line, col=node.col, params=node.params, body=node.body, implicit=False)

        def coroutine_factory(*args, **kwargs):
            def body_fn(q, send_q):
                call_scope = scope.child(name=node.name)
                pos_idx = 0
                for p in lam.params:
                    if p.kind == 'star':
                        call_scope.define_local(p.name, list(args[pos_idx:]))
                        pos_idx = len(args)
                    elif p.kind == 'dstar':
                        call_scope.define_local(p.name, dict(kwargs))
                    else:
                        if pos_idx < len(args):
                            call_scope.define_local(p.name, args[pos_idx])
                            pos_idx += 1
                        elif p.name in kwargs:
                            call_scope.define_local(p.name, kwargs.pop(p.name))
                        elif p.default is not None:
                            call_scope.define_local(p.name, interp.eval_node(p.default, scope))
                        else:
                            raise ArgErr(f"missing argument '{p.name}' for {node.name}")
                call_scope.define_local('__yield_queue__', q)
                call_scope.define_local('__send_queue__', send_q)
                try:
                    interp.eval_node(lam.body, call_scope)
                except _Return:
                    pass
            return SnafuGenerator(body_fn)

        coroutine_factory.__name__ = node.name
        scope.define_local(node.name, coroutine_factory)
        if node.decorators:
            fn = scope.lookup(node.name)
            for dec_node in reversed(node.decorators):
                dec_fn = self.eval_node(dec_node, scope)
                fn = _call_value(dec_fn, [fn], {})
            scope.assign(node.name, fn)
        return UND

    # ---- declarations ----
    def eval_FnDecl(self, node, scope):
        # A Lambda-with-name
        lam = Lambda(line=node.line, col=node.col, params=node.params, body=node.body, implicit=False)
        fn = make_function(lam, scope, self, name=node.name)
        # Wrap with contracts if req/ens present
        if node.precond is not None or node.postcond is not None:
            raw_fn = fn
            precond_node = node.precond
            postcond_node = node.postcond
            interp_ref = self
            def contracted_fn(*args, **kwargs):
                # Build a temporary scope with param bindings for condition eval
                cond_scope = scope.child(name=node.name + ":contract")
                params = node.params
                pos_idx = 0
                for p in params:
                    if p.kind == 'pos':
                        if pos_idx < len(args):
                            cond_scope.define_local(p.name, args[pos_idx])
                            pos_idx += 1
                        elif p.name in kwargs:
                            cond_scope.define_local(p.name, kwargs[p.name])
                # Check precondition
                if precond_node is not None:
                    pre_result = interp_ref.eval_node(precond_node, cond_scope)
                    if not truthy(pre_result):
                        raise ContractErr("precondition failed")
                # Call the actual function
                result = raw_fn(*args, **kwargs)
                # Check postcondition (with 'result' bound)
                if postcond_node is not None:
                    cond_scope.define_local('result', result)
                    post_result = interp_ref.eval_node(postcond_node, cond_scope)
                    if not truthy(post_result):
                        raise ContractErr("postcondition failed")
                return result
            contracted_fn.__name__ = node.name
            contracted_fn.__snafu_lambda__ = lam
            fn = contracted_fn
        # Determine type annotations
        has_types = any(p.type_name for p in node.params if p.kind == 'pos') or _has_pattern_head(node.params)
        ptypes = tuple(p.type_name for p in node.params if p.kind == 'pos')
        # Check what already exists at this name
        existing = scope.lookup_or_und(node.name)
        if isinstance(existing, MultiDispatch):
            # Already a dispatch table -- register new method
            existing.register(ptypes, fn)
            scope.define_local(node.name, existing)
        elif has_types:
            # New typed overload -- create or upgrade to MultiDispatch
            with self._lock:
                dispatch = self.dispatch_tables.get(node.name)
                if dispatch is None:
                    dispatch = MultiDispatch(node.name)
                    self.dispatch_tables[node.name] = dispatch
                # If an existing plain function was stored, register it as wildcard
                if callable(existing) and existing is not UND and not isinstance(existing, MultiDispatch):
                    old_ptypes = tuple(None for _ in ptypes)  # wildcard
                    # Only add if dispatch has no methods yet (avoid re-adding)
                    if not dispatch.methods:
                        dispatch.register(old_ptypes, existing)
                dispatch.register(ptypes, fn)
            scope.define_local(node.name, dispatch)
        else:
            scope.define_local(node.name, fn)
        if node.decorators:
            fn = scope.lookup(node.name)
            for dec_node in reversed(node.decorators):
                dec_fn = self.eval_node(dec_node, scope)
                fn = _call_value(dec_fn, [fn], {})
            scope.assign(node.name, fn)
        return UND

    def eval_SumDecl(self, node, scope):
        variant_names = [v.name for v in node.variants]
        st = SumType(node.name, variant_names)
        self.sum_types[node.name] = st
        scope.define_local(node.name, st)
        for vs in node.variants:
            ctor = VariantCtor(st, vs.name, vs.fields)
            self.variants[vs.name] = ctor
            if not vs.fields:
                # Zero-arg variants are also instances
                scope.define_local(vs.name, ctor())
            else:
                scope.define_local(vs.name, ctor)
        # Handle derivations (dv [Eq, Show, Ord])
        if node.derivations:
            for proto_name in node.derivations:
                if proto_name == 'Eq':
                    def auto_eq(a, b, _st=st):
                        if not isinstance(a, Variant) or not isinstance(b, Variant):
                            return a == b
                        if a.sum_type is not _st or b.sum_type is not _st:
                            return a == b
                        return a.name == b.name and a.fields == b.fields
                    self._derivation_eq[st.name] = auto_eq
                elif proto_name == 'Ord':
                    _vnames = list(variant_names)
                    def auto_ord(a, b, _st=st, _vn=_vnames):
                        if not isinstance(a, Variant) or not isinstance(b, Variant):
                            return 0
                        ia = _vn.index(a.name) if a.name in _vn else -1
                        ib = _vn.index(b.name) if b.name in _vn else -1
                        if ia != ib:
                            return -1 if ia < ib else 1
                        for fa, fb in zip(a.fields, b.fields):
                            if fa < fb: return -1
                            if fa > fb: return 1
                        return 0
                    self._derivation_ord[st.name] = auto_ord
                # Show is already handled by Variant.__repr__
        return st

    def eval_ProtoDecl(self, node, scope):
        method_names = [m.name for m in node.methods]
        p = Protocol(node.name, method_names, tuple(node.parents))
        self.protocols[node.name] = p
        scope.define_local(node.name, p)
        return p

    def eval_ImplDecl(self, node, scope):
        impl_dict = {}
        for m in node.methods:
            lam = Lambda(line=m.line, col=m.col, params=m.params, body=m.body, implicit=False)
            fn = make_function(lam, scope, self, name=m.name)
            impl_dict[m.name] = fn
            # Also add as a dispatched method for that type
            if m.name not in self.dispatch_tables:
                self.dispatch_tables[m.name] = MultiDispatch(m.name)
                scope.define_local(m.name, self.dispatch_tables[m.name])
            ptypes = [node.type_name] + [p.type_name for p in m.params[1:]]
            # For single-arg proto methods, first param is type-matched
            if not ptypes[0]:
                ptypes[0] = node.type_name
            self.dispatch_tables[m.name].register(tuple(ptypes), fn)
        self.impls[(node.proto_name, node.type_name)] = impl_dict
        return UND

    def eval_StrictBlock(self, node, scope):
        old = self.strict
        self.strict = True
        try:
            if node.body:
                return self.eval_node(node.body, scope)
            return UND  # top-level toggle stays
        finally:
            if node.body:
                self.strict = old
            # if no body, leave strict=True permanently

    def eval_LooseBlock(self, node, scope):
        old = self.strict
        self.strict = False
        try:
            if node.body:
                return self.eval_node(node.body, scope)
            return UND
        finally:
            if node.body:
                self.strict = old

    def eval_With(self, node, scope):
        child = scope.child()
        entered = []
        for b in node.bindings:
            val = self.eval_node(b.expr, scope)
            # Try to call .en() (enter) on the value
            en_val = val
            try:
                en_fn = get_attr(val, 'en', self)
                if callable(en_fn):
                    en_val = _call_value(en_fn, [], {})
            except (AttrErr, TypeErr):
                pass
            if b.var:
                child.define_local(b.var, en_val)
            entered.append(val)
        try:
            result = self.eval_node(node.body, child)
        except Exception as exc:
            for val in reversed(entered):
                try:
                    ex_fn = get_attr(val, 'ex', self)
                    if callable(ex_fn): _call_value(ex_fn, [exc], {})
                except (AttrErr, TypeErr):
                    pass
            raise
        else:
            for val in reversed(entered):
                try:
                    ex_fn = get_attr(val, 'ex', self)
                    if callable(ex_fn): _call_value(ex_fn, [UND], {})
                except (AttrErr, TypeErr):
                    pass
        return result

    def eval_Use(self, node, scope):
        import os
        for item in node.items:
            mod_name = item.name
            with self._lock:
                cached = self.module_cache.get(mod_name)
            if cached is not None:
                mod_scope = cached
            else:
                # Search for module file
                mod_file = mod_name + ".snf"
                # Search current dir first, then any search paths
                search_paths = [os.getcwd()]
                found = None
                for sp in search_paths:
                    candidate = os.path.join(sp, mod_file)
                    if os.path.isfile(candidate):
                        found = candidate
                        break
                if found is None:
                    # Fallback: try importing as a Python module
                    try:
                        py_mod = importlib.import_module(mod_name)
                        bind_name = item.alias or item.name
                        scope.define_local(bind_name, py_mod)
                        continue
                    except ImportError:
                        raise IOErr(f"module '{mod_name}' not found")
                with open(found, 'r', encoding='utf-8') as f:
                    src = f.read()
                mod_interp = Interpreter()
                mod_interp.strict = self.strict
                tokens = Lexer(src, filename=found).tokenize()
                tree = Parser(tokens, filename=found).parse_program()
                mod_interp.eval_program(tree)
                mod_scope = mod_interp.global_scope
                with self._lock:
                    self.module_cache[mod_name] = mod_scope
            if item.star:
                # Copy all exported names (or all names) into current scope
                exports = mod_scope.bindings.get('__exports__', None)
                if exports:
                    for n in exports:
                        if mod_scope.contains(n):
                            scope.define_local(n, mod_scope.lookup(n))
                else:
                    for k, v in mod_scope.bindings.items():
                        if not k.startswith('__'):
                            scope.define_local(k, v)
            else:
                # Create a namespace object
                mod_obj = SnafuObj(type_name=mod_name)
                exports = mod_scope.bindings.get('__exports__', None)
                if exports:
                    for n in exports:
                        if mod_scope.contains(n):
                            mod_obj.attrs[n] = mod_scope.lookup(n)
                else:
                    for k, v in mod_scope.bindings.items():
                        if not k.startswith('__'):
                            mod_obj.attrs[k] = v
                bind_name = item.alias or item.name
                scope.define_local(bind_name, mod_obj)
        # Block form: us module { body } — import names into a child scope, run body, then names go out of scope
        if node.body is not None:
            block_scope = scope.child()
            # Re-import into block_scope with unqualified names for convenience
            for item in node.items:
                mod_name = item.name
                if mod_name in self.module_cache:
                    mod_scope = self.module_cache[mod_name]
                    for k, v in mod_scope.bindings.items():
                        if not k.startswith('__'):
                            block_scope.define_local(k, v)
            return self.eval_block(node.body, block_scope, new_scope=False)
        return UND

    def eval_Export(self, node, scope):
        scope.define_local('__exports__', node.names)
        return UND

    # ---- algebraic effects ----
    def eval_EffectDecl(self, node, scope):
        """ef Name(fields) - declares an effect type (similar to a sum-type variant)."""
        # Create a lightweight sum type for the effect with a single variant
        st = SumType(node.name, [node.name])
        self.sum_types[node.name] = st
        ctor = VariantCtor(st, node.name, node.fields)
        self.variants[node.name] = ctor
        if not node.fields:
            scope.define_local(node.name, ctor())
        else:
            scope.define_local(node.name, ctor)
        return UND

    def eval_Perform(self, node, scope):
        """pf Expr - perform an effect (raise an _EffectSignal).
        If a replay trace is active, return the traced value instead of raising."""
        val = self.eval_node(node.expr, scope)
        # Check replay trace (set by _run_with_trace for multi-shot continuations)
        trace = getattr(self, '_effect_trace', None)
        if trace is not None:
            idx = getattr(self, '_effect_trace_index', 0)
            if idx < len(trace):
                self._effect_trace_index = idx + 1
                return trace[idx]
        raise _EffectSignal(val, continuation=None)

    def eval_Handle(self, node, scope):
        """hd { body } with { Pattern k -> handler, ... }
        Multi-shot continuations: k(val) replays the body from scratch,
        intercepting pf calls using a replay trace of resume values.
        k can be called multiple times (multi-shot).
        """
        has_continuation = any(c.cont_name is not None for c in node.cases
                               if not (isinstance(c.pattern, PatVar) and c.cont_name is None))
        if not has_continuation:
            # Simple case: no continuations needed, use fast exception-based path
            return self._eval_handle_simple(node, scope)

        # Use the trace-based system for multi-shot continuations
        return self._run_with_trace(node.body, scope, node.cases, trace=[])

    def _run_with_trace(self, body_node, scope, handler_cases, trace):
        """Run body with a trace of resume values. Effects at trace positions
        are auto-resumed via eval_Perform's trace check. The first effect
        beyond the trace triggers the handler."""
        old_trace = getattr(self, '_effect_trace', None)
        old_index = getattr(self, '_effect_trace_index', 0)
        self._effect_trace = trace
        self._effect_trace_index = 0

        try:
            result = self.eval_node(body_node, scope.child())
            # Body completed without raising -- check for 'r' (return) handler case
            for case in handler_cases:
                if isinstance(case.pattern, PatVar) and case.cont_name is None:
                    r_scope = scope.child()
                    r_scope.define_local(case.pattern.name, result)
                    return self.eval_node(case.body, r_scope)
            return result
        except _EffectSignal as sig:
            # This effect is beyond the trace -- handle it
            for case in handler_cases:
                bindings = match_pattern(case.pattern, sig.effect_value)
                if bindings is not None:
                    case_scope = scope.child()
                    for k, v in bindings.items():
                        case_scope.define_local(k, v)
                    if case.cont_name:
                        # Build a continuation k that extends the trace
                        current_trace = list(trace)
                        def make_k(tr):
                            def k(resume_val=UND):
                                new_trace = tr + [resume_val]
                                return self._run_with_trace(body_node, scope, handler_cases, new_trace)
                            return k
                        case_scope.define_local(case.cont_name, make_k(current_trace))
                    return self.eval_node(case.body, case_scope)
            raise  # unhandled effect
        finally:
            self._effect_trace = old_trace
            self._effect_trace_index = old_index

    def _eval_handle_simple(self, node, scope):
        """Simple exception-based handle (no continuations)."""
        try:
            result = self.eval_node(node.body, scope)
            for case in node.cases:
                if isinstance(case.pattern, PatVar) and case.cont_name is None:
                    r_scope = scope.child()
                    r_scope.define_local(case.pattern.name, result)
                    return self.eval_node(case.body, r_scope)
            return result
        except _EffectSignal as sig:
            for case in node.cases:
                bindings = match_pattern(case.pattern, sig.effect_value)
                if bindings is not None:
                    case_scope = scope.child()
                    for k, v in bindings.items():
                        case_scope.define_local(k, v)
                    if case.cont_name:
                        case_scope.define_local(case.cont_name, lambda v=UND: v)
                    return self.eval_node(case.body, case_scope)
            raise

    # ---- macros ----
    def eval_MacroDecl(self, node, scope):
        """mc name(params) { body } - store a macro."""
        lam = Lambda(line=node.line, col=node.col, params=node.params, body=node.body, implicit=False)
        fn = make_function(lam, scope, self, name=node.name)
        macro = SnafuMacro(node.name, fn)
        scope.define_local(node.name, macro)
        return UND

    # ---- execution sets ----
    def eval_ExecSet(self, node, scope):
        """xs { stmts } - run statements concurrently."""
        results = [UND] * len(node.stmts)
        errors = [None] * len(node.stmts)
        threads = []
        for i, stmt in enumerate(node.stmts):
            def run(idx=i, s=stmt):
                try:
                    results[idx] = self.eval_node(s, scope)
                except Exception as e:
                    errors[idx] = e
            t = threading.Thread(target=run, daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        for e in errors:
            if e is not None:
                raise e
        return results[-1] if results else UND

    # ---- select ----
    def eval_Select(self, node, scope):
        """sl { channels } - wait on multiple channels."""
        channels = [self.eval_node(ch, scope) for ch in node.channels]
        timeout_ms = self.eval_node(node.timeout, scope) if node.timeout else None
        return self._select_channels(channels, timeout_ms)

    def _select_channels(self, channels, timeout_ms=None):
        deadline = time.time() + timeout_ms / 1000 if timeout_ms else None
        while True:
            for i, c in enumerate(channels):
                if isinstance(c, SnafuObj) and '_q' in c.attrs:
                    if not c.attrs['_q'].empty():
                        return [i, c.attrs['_q'].get_nowait()]
            if deadline and time.time() > deadline:
                return UND
            time.sleep(0.001)

    # ---- list comprehensions ----
    def eval_ListComp(self, node, scope):
        """[expr for pat in iter (if guard)? ...] — nested loop comprehension."""
        result = []
        self._eval_comp_clauses(node.expr, node.clauses, 0, scope, result)
        return result

    def _eval_comp_clauses(self, expr, clauses, idx, scope, result):
        if idx >= len(clauses):
            result.append(self.eval_node(expr, scope))
            return
        pattern, iter_expr, guard = clauses[idx]
        iterable = self.eval_node(iter_expr, scope)
        if isinstance(iterable, range):
            iterable = list(iterable)
        for item in iterable:
            child = scope.child()
            bindings = match_pattern(pattern, item)
            if bindings is None:
                continue
            for k, v in bindings.items():
                child.define_local(k, v)
            if guard is not None:
                if not truthy(self.eval_node(guard, child)):
                    continue
            self._eval_comp_clauses(expr, clauses, idx + 1, child, result)

    # ---- where clauses ----
    def eval_Where(self, node, scope):
        """expr whr { bindings } — evaluate bindings then expr in same child scope."""
        child = scope.child()
        # Evaluate bindings directly in child (no extra scope layer)
        self.eval_block(node.bindings, child, new_scope=False)
        return self.eval_node(node.expr, child)

    # ---- query ----
    def eval_Query(self, node, scope):
        """qr source (whr filter)? (sel select)? (srt sort)?"""
        source = self.eval_node(node.source, scope)
        if not isinstance(source, list):
            source = list(source)
        result = source
        if node.filter_expr is not None:
            filter_fn = self.eval_node(node.filter_expr, scope)
            result = [x for x in result if truthy(_call_value(filter_fn, [x], {}))]
        if node.select_expr is not None:
            select_fn = self.eval_node(node.select_expr, scope)
            result = [_call_value(select_fn, [x], {}) for x in result]
        if node.sort_expr is not None:
            sort_fn = self.eval_node(node.sort_expr, scope)
            result = sorted(result, key=lambda x: _call_value(sort_fn, [x], {}))
        return result

    # ---- stack combinator ----
    _STK_WORDS = {'dup', 'swap', 'rot', 'over', 'drop', 'nip', 'tuck'}

    _STK_OPS = {'+', '-', '*', '/', '%', '**'}

    def eval_StkBlock(self, node, scope):
        """stk { ... } — Forth-style stack-based evaluation."""
        stack = []
        for stmt in node.body.stmts:
            expr = stmt.expr if isinstance(stmt, ExprStmt) else stmt
            self._stk_eval(expr, stack, scope)
        return stack[-1] if stack else UND

    def _stk_eval(self, expr, stack, scope):
        # Number literals -> push
        if isinstance(expr, NumLit):
            stack.append(expr.value)
            return
        # String literals -> push
        if isinstance(expr, StrLit):
            stack.append(self.eval_StrLit(expr, scope))
            return
        # Bool/Und -> push
        if isinstance(expr, BoolLit):
            stack.append(expr.value)
            return
        if isinstance(expr, UndLit):
            stack.append(UND)
            return
        # Identifier: check if stack word, operator, or variable
        if isinstance(expr, Ident):
            name = expr.name
            if name in self._STK_WORDS:
                self._stk_word(name, stack)
                return
            if name in self._STK_OPS:
                # Pop two values, apply operator, push result
                b = stack.pop()
                a = stack.pop()
                stack.append(apply_binop(name, a, b, False))
                return
            # Otherwise push the value
            stack.append(scope.lookup(name))
            return
        # Call: evaluate function and args, push result
        if isinstance(expr, Call):
            fn = self.eval_node(expr.fn, scope)
            args = [self.eval_node(a[1], scope) for a in expr.args]
            stack.append(_call_value(fn, args, {}))
            return
        # Fallback: evaluate normally and push
        stack.append(self.eval_node(expr, scope))

    def _stk_word(self, name, stack):
        if name == 'dup':
            stack.append(stack[-1])
        elif name == 'swap':
            stack[-1], stack[-2] = stack[-2], stack[-1]
        elif name == 'rot':
            a = stack.pop(-3)
            stack.append(a)
        elif name == 'over':
            stack.append(stack[-2])
        elif name == 'drop':
            stack.pop()
        elif name == 'nip':
            del stack[-2]
        elif name == 'tuck':
            stack.insert(-2, stack[-1])

    # ---- Feature: Universe fork (fk) ----
    def eval_Fork(self, node, scope):
        import copy as _copy
        if node.body is not None:
            # Scoped fork: deep-copy scope, run body in a thread, return Future.
            # The clone gets an independent copy of all bindings; the original
            # scope is untouched (snapshot/restore for safety).
            saved = self._snapshot_scope(scope)

            # Build a deep-copied child scope for the clone thread
            clone_scope = scope.child(name="<fk>")
            for k, v in saved.items():
                try:
                    clone_scope.define_local(k, _copy.deepcopy(v))
                except Exception:
                    clone_scope.define_local(k, v)

            # Assign a fork id for this child
            with self._lock:
                self._fork_id_counter += 1
                clone_id = self._fork_id_counter
                parent_id = self._current_fork_id
                self._fork_children.setdefault(parent_id, []).append(clone_id)

            future = SnafuObj(type_name="Future")
            future.attrs['_result'] = UND
            future.attrs['_error'] = None
            future.attrs['_fork_id'] = clone_id
            interp = self
            body_node = node.body

            def fork_thread():
                old_id = getattr(interp._fork_return_value, 'value', None)
                interp._fork_return_value.value = None
                old_fork_id = interp._current_fork_id
                try:
                    result = interp.eval_node(body_node, clone_scope)
                    future.attrs['_result'] = result
                    interp._fork_results[clone_id] = result
                except _Return as e:
                    future.attrs['_result'] = e.value
                    interp._fork_results[clone_id] = e.value
                except Exception as e:
                    future.attrs['_error'] = e
                    interp._fork_results[clone_id] = UND

            t = threading.Thread(target=fork_thread, daemon=True)
            future.attrs['_thread'] = t
            self._fork_threads[clone_id] = t
            t.start()
            return future
        else:
            # True fork (no body): raise _ForkSignal so eval_block can
            # clone the execution context and continue both branches.
            # If _fork_return_value is set (we are inside a clone thread
            # re-executing the fk() statement), return that value instead.
            fk_ret = getattr(self._fork_return_value, 'value', None)
            if fk_ret is not None:
                val = fk_ret
                self._fork_return_value.value = None
                return val
            raise _ForkSignal()

    # ---- Feature: Dynamic scope (dy) ----
    def eval_DynScope(self, node, scope):
        # Use eval_block directly with new_scope=True so bindings end up in the child.
        # We create the child manually and push its bindings onto the dyn stack.
        child = scope.child(name="<dy>")
        Scope._dyn_stack.append(child.bindings)
        try:
            # Eval the block body without creating yet another scope
            if isinstance(node.body, Block):
                return self.eval_block(node.body, child, new_scope=False)
            return self.eval_node(node.body, child)
        finally:
            Scope._dyn_stack.pop()

    # ---- Feature: Execution recording (rec) ----
    def eval_Record(self, node, scope):
        trace = []
        old_recording = getattr(self, '_recording', None)
        self._recording = trace
        try:
            self.eval_node(node.body, scope)
        finally:
            self._recording = old_recording
        return trace


# =============================================================================
#  HELPER FUNCTIONS
# =============================================================================

def _unify(a, b):
    """Unify two values, binding logic variables as needed."""
    a = a.deref() if isinstance(a, LogicVar) else a
    b = b.deref() if isinstance(b, LogicVar) else b
    if isinstance(a, LogicVar):
        a.bind(b)
        return True
    if isinstance(b, LogicVar):
        b.bind(a)
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_unify(x, y) for x, y in zip(a, b))
    return a == b


def _has_pattern_head(params):
    return False   # v0.1 simplification


def _exc_matches(exc, type_name):
    # Walk MRO by name
    for cls in type(exc).__mro__:
        if cls.__name__ == type_name:
            return True
    return False


def _destructure_assign(target, value, scope, interp=None):
    """Destructure a value into a ListExpr target, supporting nesting."""
    if not isinstance(target, ListExpr):
        raise TypeErr("destructure target must be a list")
    if isinstance(value, (dict, range)):
        value = list(value.values()) if isinstance(value, dict) else list(value)
    elif not isinstance(value, list):
        value = list(value)
    items = target.items
    rest_idx = None
    for i, e in enumerate(items):
        if e.kind == 'spread':
            rest_idx = i
            break
    def assign_elem(node, val):
        if isinstance(node, Ident):
            scope.assign(node.name, val)
        elif isinstance(node, Wildcard):
            pass
        elif isinstance(node, ListExpr):
            _destructure_assign(node, val, scope, interp)
        elif interp is not None:
            interp._assign_to(node, val, scope)
        else:
            raise TypeErr(f"cannot destructure-assign to {type(node).__name__}")
    if rest_idx is None:
        for i, e in enumerate(items):
            assign_elem(e.value, value[i] if i < len(value) else UND)
    else:
        before = items[:rest_idx]
        after = items[rest_idx+1:]
        rest_elem = items[rest_idx]
        for i, e in enumerate(before):
            assign_elem(e.value, value[i] if i < len(value) else UND)
        mid_end = len(value) - len(after)
        if isinstance(rest_elem.value, Ident):
            scope.assign(rest_elem.value.name, value[len(before):mid_end])
        for i, e in enumerate(after):
            assign_elem(e.value, value[mid_end + i] if mid_end + i < len(value) else UND)


def _elementwise(op, left, right, strict=False):
    """Apply op element-wise. Scalar extension: if one side isn't a list, broadcast."""
    left_is_list = isinstance(left, (list, range))
    right_is_list = isinstance(right, (list, range))
    if left_is_list and right_is_list:
        ll, rl = list(left), list(right)
        n = max(len(ll), len(rl))
        return [apply_binop(op, ll[i] if i < len(ll) else UND,
                                rl[i] if i < len(rl) else UND, strict) for i in range(n)]
    elif left_is_list:
        return [apply_binop(op, x, right, strict) for x in left]
    elif right_is_list:
        return [apply_binop(op, left, x, strict) for x in right]
    else:
        return apply_binop(op, left, right, strict)


def _outer_product(op, left, right, strict=False):
    """Outer product: result[i][j] = left[i] op right[j]."""
    ll = list(left)
    rl = list(right)
    return [[apply_binop(op, a, b, strict) for b in rl] for a in ll]


def _wrap_match(m):
    """Wrap a Python re.Match into a SnafuObj."""
    obj = SnafuObj()
    obj.attrs['gr'] = lambda n=0: m.group(n)
    obj.attrs['sp'] = m.start()
    obj.attrs['ep'] = m.end()
    obj.attrs['groups'] = lambda: list(m.groups())
    return obj


def _snafu_obj_lookup(obj, name):
    """Lookup an attribute on a SnafuObj, traversing parent chain. Returns None if not found."""
    if name in obj.attrs:
        return obj.attrs[name]
    for p in obj.parents:
        result = _snafu_obj_lookup(p, name)
        if result is not None:
            return result
    return None


_BINOP_DUNDER_MAP = {'+': '__add__', '-': '__sub__', '*': '__mul__', '/': '__div__',
                     '**': '__pow__', '%': '__mod__', '==': '__eq__', '<>': '__ne__',
                     '<': '__lt__', '>': '__gt__', '<=': '__le__', '>=': '__ge__'}

def _binop_sub(left, right):
    # Character arithmetic: single char - int = shifted char
    if isinstance(left, str) and len(left) == 1 and isinstance(right, int) and not isinstance(right, bool):
        return chr(ord(left) - right)
    # String - string = remove all occurrences
    if isinstance(left, str) and isinstance(right, str):
        return left.replace(right, '')
    return left - right

def _binop_bitand(left, right):
    return int(left) & int(right)

def _binop_bitor(left, right):
    return int(left) | int(right)

def _binop_regex_findall(left, right):
    # Regex findall shorthand: string ~/ regex
    if isinstance(right, SnafuObj) and right.attrs.get('_snafu_regex'):
        compiled = right.attrs.get('_compiled')
        if compiled:
            return compiled.findall(left)
    return UND

def _binop_floordiv(left, right):
    # nth root
    if right == 0: raise DivErr("0th root")
    return left ** (Fraction(1, right) if isinstance(right, int) else (1/right))

def _binop_in(left, right):
    if isinstance(right, (list, dict, str, range)): return left in right
    return False

def _binop_not_in(left, right):
    if isinstance(right, (list, dict, str, range)): return left not in right
    return True

def _binop_impl(left, right):
    return (not truthy(left)) or truthy(right)

def _binop_rev_impl(left, right):
    return (not truthy(right)) or truthy(left)

def _binop_regex_match(left, right):
    # string =~ regex_obj -> match or UND
    if isinstance(left, str) and isinstance(right, SnafuObj) and right.attrs.get('_snafu_regex'):
        ma_fn = right.attrs.get('ma')
        if ma_fn:
            return ma_fn(left)
    elif isinstance(right, str) and isinstance(left, SnafuObj) and left.attrs.get('_snafu_regex'):
        ma_fn = left.attrs.get('ma')
        if ma_fn:
            return ma_fn(right)
    return UND

_BINOP_DISPATCH = {
    '+':      lambda l, r: _add(l, r),
    '-':      _binop_sub,
    '&':      _binop_bitand,
    '|':      _binop_bitor,
    '~/':     _binop_regex_findall,
    '*':      lambda l, r: _mul(l, r),
    '/':      lambda l, r: _div(l, r),
    '//':     _binop_floordiv,
    '%':      lambda l, r: l % r,
    '**':     lambda l, r: l ** r,
    '..':     lambda l, r: range(l, r),
    '..=':    lambda l, r: range(l, r + 1),
    '==':     lambda l, r: _eq(l, r),
    '<>':     lambda l, r: not _eq(l, r),
    '===':    lambda l, r: _structural_eq(l, r),
    '!==':    lambda l, r: not _structural_eq(l, r),
    '<':      lambda l, r: l < r,
    '>':      lambda l, r: l > r,
    '<=':     lambda l, r: l <= r,
    '>=':     lambda l, r: l >= r,
    '!<':     lambda l, r: not (l < r),
    '!>':     lambda l, r: not (l > r),
    'is':     lambda l, r: l is r,
    'is not': lambda l, r: l is not r,
    'in':     _binop_in,
    'not in': _binop_not_in,
    '^^':     lambda l, r: bool(l) != bool(r),
    '<-':     _binop_rev_impl,
    '->':     _binop_impl,
    '!<-':    lambda l, r: not _binop_rev_impl(l, r),
    '!->':    lambda l, r: not _binop_impl(l, r),
    '!&&':    lambda l, r: not (truthy(l) and truthy(r)),
    '!||':    lambda l, r: not (truthy(l) or truthy(r)),
    '!^^':    lambda l, r: truthy(l) == truthy(r),
    '=~':     _binop_regex_match,
}

def apply_binop(op, left, right, strict=False):
    # Operator overloading on SnafuObj (user-defined types)
    _dunder = _BINOP_DUNDER_MAP.get(op)
    if _dunder:
        if isinstance(left, SnafuObj):
            fn = _snafu_obj_lookup(left, _dunder)
            if fn is not None:
                return _call_value(fn, [left, right], {})
        _rdunder = '__r' + _dunder[2:]
        if isinstance(right, SnafuObj):
            fn = _snafu_obj_lookup(right, _rdunder)
            if fn is not None:
                return _call_value(fn, [right, left], {})
    # Und propagation (default mode)
    if left is UND or right is UND:
        if op in ('===', '!=='): return (left is right) if op == '===' else not (left is right)
        if op == 'is': return left is right
        if op == 'is not': return left is not right
        if not strict:
            return UND
        raise UndErr(f"und in {op}")

    handler = _BINOP_DISPATCH.get(op)
    if handler is not None:
        return handler(left, right)
    raise TypeErr(f"unknown op {op}")


def _add(a, b):
    # Character arithmetic: single char + int = shifted char
    if isinstance(a, str) and len(a) == 1 and isinstance(b, int) and not isinstance(b, bool):
        return chr(ord(a) + b)
    if isinstance(a, str) or isinstance(b, str):
        return snafu_str(a) + snafu_str(b)
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    # List + non-list = append
    if isinstance(a, list) and not isinstance(b, list):
        return a + [b]
    # Transducer composition
    if isinstance(a, SnafuTransducer) and isinstance(b, SnafuTransducer):
        t1, t2 = a.transform, b.transform
        return SnafuTransducer(lambda reducer, _t1=t1, _t2=t2: _t1(_t2(reducer)))
    # Lens composition
    if isinstance(a, SnafuLens) and isinstance(b, SnafuLens):
        def getter(obj, _a=a, _b=b):
            return _b.getter(_a.getter(obj))
        def setter(obj, val, _a=a, _b=b):
            return _a.setter(obj, _b.setter(_a.getter(obj), val))
        return SnafuLens(getter, setter)
    # Traversal composition
    if isinstance(a, (SnafuTraversal, ComposedTraversal)):
        return ComposedTraversal(a, b)
    # Function composition: (f + g)(x) = g(f(x))
    if callable(a) and callable(b) and not isinstance(a, (str, list, dict, int, float, bool)) and not isinstance(b, (str, list, dict, int, float, bool)):
        def composed(*args, **kwargs):
            return _call_value(b, [_call_value(a, list(args), kwargs)], {})
        composed.__name__ = f"({getattr(a,'__name__','?')}+{getattr(b,'__name__','?')})"
        return composed
    return a + b


def _mul(a, b):
    if isinstance(a, str) and isinstance(b, int): return a * b
    if isinstance(a, list) and isinstance(b, int): return a * b
    return a * b


def _div(a, b):
    if b == 0: raise DivErr("division by zero")
    if isinstance(a, int) and isinstance(b, int):
        # Preserve rationals
        return Fraction(a, b) if a % b != 0 else a // b
    return a / b


def _eq(a, b):
    if a is b: return True
    if isinstance(a, (int, float, Fraction)) and isinstance(b, (int, float, Fraction)):
        return a == b
    try:
        return a == b
    except Exception:
        return False


def _structural_eq(a, b):
    """Structural equality: same Snafu type AND same value, recursively. No custom overrides."""
    if a is UND and b is UND: return True
    if a is UND or b is UND: return False
    # NaN: structurally equal to itself (override IEEE)
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b): return True
    # Must be same Snafu type
    if type_name(a) != type_name(b): return False
    # Variant
    if isinstance(a, Variant) and isinstance(b, Variant):
        return (a.sum_type is b.sum_type and a.name == b.name and
                len(a.fields) == len(b.fields) and
                all(_structural_eq(x, y) for x, y in zip(a.fields, b.fields)))
    # Lists
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_structural_eq(x, y) for x, y in zip(a, b))
    # Dicts
    if isinstance(a, dict) and isinstance(b, dict):
        return (set(a.keys()) == set(b.keys()) and
                all(_structural_eq(a[k], b[k]) for k in a))
    # SnafuObj: identity only (mutable objects)
    if isinstance(a, SnafuObj): return a is b
    # Primitives
    try: return a == b
    except: return False


def _to_int(x):
    if isinstance(x, bool): return int(x)
    if isinstance(x, (int, float, Fraction)): return int(x)
    if isinstance(x, str):
        try: return int(x)
        except ValueError: raise ValErr(f"cannot convert '{x}' to int")
    raise TypeErr(f"cannot convert {type_name(x)} to int")


def abs_fn(x):
    return abs(x)


def _reduce(f, it, init):
    items = list(it)
    if init is UND:
        if not items: raise ValErr("reduce of empty with no init")
        acc = items[0]
        rest = items[1:]
    else:
        acc = init
        rest = items
    for x in rest:
        acc = _call_value(f, [acc, x], {})
    return acc


def _sort(it, key, rv):
    items = list(it)
    if key:
        return sorted(items, key=lambda x: _call_value(key, [x], {}), reverse=bool(rv))
    return sorted(items, reverse=bool(rv))


def _list_group_by(lst, f):
    """Group list elements by a key function, return dict of key -> list."""
    result = {}
    for x in lst:
        k = _call_value(f, [x], {})
        if k not in result:
            result[k] = []
        result[k].append(x)
    return result


def _list_intersperse(lst, val):
    """Insert val between each pair of elements."""
    if not lst:
        return []
    result = [lst[0]]
    for x in lst[1:]:
        result.append(val)
        result.append(x)
    return result


def _do_each(lst, fn):
    """Call fn on each element for side effects."""
    for x in lst:
        _call_value(fn, [x], {})


def _snafu_flat_deep(it, depth=1):
    """Flatten with depth control."""
    if depth == 0:
        return list(it)
    result = []
    for x in it:
        if isinstance(x, list) and depth > 0:
            result.extend(_snafu_flat_deep(x, depth - 1))
        else:
            result.append(x)
    return result


def _sum(it, init):
    total = init
    for x in it:
        total = _add(total, x) if isinstance(total, str) or isinstance(x, str) else total + x
    return total


def _deep_copy(v):
    import copy
    return copy.deepcopy(v)


def index_into(target, key, strict=False):
    if target is UND:
        if strict: raise UndErr("index into und")
        return UND
    # InterpSource: isrc[n] returns meta-interpreter source at level n
    if isinstance(target, SnafuObj) and target.type_name == "InterpSource":
        interp = target.attrs.get('_interp')
        if interp:
            level = int(key)
            return interp.meta_interp_sources.get(level, UND)
        return UND
    # InterpAST: iast[n] returns meta-interpreter AST at level n
    if isinstance(target, SnafuObj) and target.type_name == "InterpAST":
        interp = target.attrs.get('_interp')
        if interp:
            level = int(key)
            src = interp.meta_interp_sources.get(level)
            if src:
                tokens = Lexer(src, filename="<iast>").tokenize()
                tree = Parser(tokens, filename="<iast>").parse_program()
                return tree
        return UND
    if isinstance(target, (list, tuple)):
        if isinstance(key, int):
            if -len(target) <= key < len(target):
                return target[key]
            if strict: raise IxErr(f"list index {key} out of range")
            return UND
        raise TypeErr(f"list index must be Int, got {type_name(key)}")
    if isinstance(target, (dict, types.MappingProxyType)):
        if key in target: return target[key]
        if strict: raise KeyErr(f"no key {key!r}")
        return UND
    if isinstance(target, str):
        if isinstance(key, int):
            if -len(target) <= key < len(target): return target[key]
            if strict: raise IxErr(f"string index {key} out of range")
            return UND
        raise TypeErr(f"string index must be Int")
    raise TypeErr(f"cannot index {type_name(target)}")


# =============================================================================
#  TRANSDUCERS
# =============================================================================

class _Reduced:
    """Sentinel to signal early termination in transducers."""
    __slots__ = ('value',)
    def __init__(self, value):
        self.value = value


class SnafuTransducer:
    """A composable transducer."""
    def __init__(self, transform, finalizer=None):
        self.transform = transform  # fn: reducer -> reducer
        self._finalizer = finalizer  # optional fn(acc, reducer) -> acc

    def al(self, data):
        """Apply transducer to data, return list."""
        def list_reducer(acc, x):
            acc.append(x)
            return acc
        reducer = self.transform(list_reducer)
        result = []
        for x in data:
            result = reducer(result, x)
            if isinstance(result, _Reduced):
                result = result.value
                break
        # Call finalizer to flush any remaining state
        if self._finalizer is not None:
            result = self._finalizer(result, list_reducer)
        return result


def _make_transducer_map(f):
    def transform(reducer):
        def new_reducer(acc, x):
            return reducer(acc, _call_value(f, [x], {}))
        return new_reducer
    return SnafuTransducer(transform)


def _make_transducer_filter(pred):
    def transform(reducer):
        def new_reducer(acc, x):
            if truthy(_call_value(pred, [x], {})):
                return reducer(acc, x)
            return acc
        return new_reducer
    return SnafuTransducer(transform)


def _make_transducer_take(n):
    def transform(reducer):
        count = [0]
        def new_reducer(acc, x):
            if count[0] < n:
                count[0] += 1
                result = reducer(acc, x)
                if count[0] >= n:
                    return _Reduced(result)
                return result
            return _Reduced(acc)
        return new_reducer
    return SnafuTransducer(transform)


def _make_transducer_drop(n):
    def transform(reducer):
        count = [0]
        def new_reducer(acc, x):
            count[0] += 1
            if count[0] > n:
                return reducer(acc, x)
            return acc
        return new_reducer
    return SnafuTransducer(transform)


def _make_transducer_scan(init, f):
    def transform(reducer):
        state = [init]
        def new_reducer(acc, x):
            state[0] = _call_value(f, [state[0], x], {})
            return reducer(acc, state[0])
        return new_reducer
    return SnafuTransducer(transform)


def _make_transducer_chunk(n):
    """xch(n) — chunk into groups of n."""
    chunk_state = []  # shared state for finalizer access
    def transform(reducer):
        def chunk_reducer(acc, val):
            chunk_state.append(val)
            if len(chunk_state) >= n:
                result = reducer(acc, list(chunk_state))
                chunk_state.clear()
                return result
            return acc
        return chunk_reducer
    def finalizer(acc, reducer):
        if chunk_state:
            acc = reducer(acc, list(chunk_state))
            chunk_state.clear()
        return acc
    return SnafuTransducer(transform, finalizer=finalizer)


def _make_transducer_dedup():
    """xdd() — deduplicate consecutive elements."""
    def transform(reducer):
        prev = [object()]  # unique sentinel
        def dedup_reducer(acc, val):
            if val != prev[0]:
                prev[0] = val
                return reducer(acc, val)
            return acc
        return dedup_reducer
    return SnafuTransducer(transform)


def _make_transducer_passthrough():
    """xpp() — identity/passthrough transducer."""
    return SnafuTransducer(lambda reducer: reducer)


# =============================================================================
#  LENSES
# =============================================================================

class SnafuLens:
    def __init__(self, getter, setter):
        self.getter = getter  # fn(obj) -> value
        self.setter = setter  # fn(obj, val) -> new_obj (or mutate + return obj)

    def gt(self, obj):
        return self.getter(obj)

    def st(self, obj, val):
        return self.setter(obj, val)

    def md(self, obj, fn):
        return self.setter(obj, _call_value(fn, [self.getter(obj)], {}))


def _lens_set_attr(obj, key, val):
    """Set an attribute/key on obj, returning the (mutated) obj."""
    if isinstance(obj, SnafuObj):
        obj.attrs[key] = val
        return obj
    if isinstance(obj, dict):
        obj[key] = val
        return obj
    raise TypeErr(f"cannot lens-set attribute '{key}' on {type_name(obj)}")


def _lens_set_idx(obj, idx, val):
    """Set an index on obj, returning the (mutated) obj."""
    if isinstance(obj, list):
        obj[idx] = val
        return obj
    raise TypeErr(f"cannot lens-set index {idx} on {type_name(obj)}")


# =============================================================================
#  TRAVERSALS & PRISMS
# =============================================================================

class SnafuTraversal:
    """Traversal: focuses on all elements of a list/collection."""
    def gt(self, obj):
        if isinstance(obj, list):
            return obj[:]
        return [obj]

    def st(self, obj, val):
        if isinstance(obj, list):
            return [val] * len(obj)
        return val

    def md(self, obj, fn):
        if isinstance(obj, list):
            return [_call_value(fn, [x], {}) for x in obj]
        return _call_value(fn, [obj], {})

    def __add__(self, other):
        return ComposedTraversal(self, other)


class ComposedTraversal:
    """Composition of a traversal (outer) with another lens/traversal (inner)."""
    def __init__(self, outer, inner):
        self.outer = outer
        self.inner = inner

    def gt(self, obj):
        outer_vals = self.outer.gt(obj)
        result = []
        for v in outer_vals:
            inner_val = self.inner.gt(v) if hasattr(self.inner, 'gt') else v
            if isinstance(inner_val, list):
                result.extend(inner_val)
            else:
                result.append(inner_val)
        return result

    def md(self, obj, fn):
        if hasattr(self.inner, 'md'):
            return self.outer.md(obj, lambda x: self.inner.md(x, fn))
        return self.outer.md(obj, fn)

    def st(self, obj, val):
        if hasattr(self.inner, 'st'):
            return self.outer.md(obj, lambda x: self.inner.st(x, val))
        return self.outer.st(obj, val)


class SnafuPrism:
    """Prism: focuses on a variant of a sum type."""
    def __init__(self, variant_name):
        self.variant_name = variant_name

    def gt(self, obj):
        if isinstance(obj, Variant) and obj.name == self.variant_name:
            return obj.fields[0] if len(obj.fields) == 1 else list(obj.fields)
        return UND

    def st(self, obj, val):
        if isinstance(obj, Variant) and obj.name == self.variant_name:
            new_fields = (val,) if len(obj.fields) == 1 else tuple(val)
            return Variant(obj.sum_type, obj.name, new_fields, obj.field_names)
        return obj

    def md(self, obj, fn):
        if isinstance(obj, Variant) and obj.name == self.variant_name:
            old_val = obj.fields[0] if len(obj.fields) == 1 else list(obj.fields)
            new_val = _call_value(fn, [old_val], {})
            new_fields = (new_val,) if len(obj.fields) == 1 else tuple(new_val)
            return Variant(obj.sum_type, obj.name, new_fields, obj.field_names)
        return obj


# =============================================================================
#  PYTHON ALIAS TABLE
# =============================================================================

_PY_ALIASES = {
    'n8': 'numpy', 'pd': 'pandas', 'pl': 'matplotlib.pyplot',
    'os': 'os', 'sy': 'sys', 'rq': 'requests',
    'js': 'json', 'dt': 'datetime', 'cs': 'csv',
    'sq': 'sqlite3', 'fs': 'pathlib', 'th': 'threading',
    'ap': 'asyncio', 'cp': 'subprocess', 'it': 'itertools',
    'ft': 'functools', 'ic': 'collections', 'ma': 'math',
    'rn': 'random', 'pk': 'pickle', 'hs': 'hashlib',
}


def get_attr(target, name, interp):
    if target is UND:
        return UND
    if isinstance(target, Scope):
        if name == 'get': return lambda n: target.lookup(n)
        if name == 'set': return lambda n, v: target.assign(n, v)
        if name == 'define': return lambda n, v: target.define_local(n, v)
        if name == 'parent': return target.parent if target.parent else UND
        if name == 'vars': return target.bindings  # return actual bindings dict (mutable)
        return UND
    if isinstance(target, SnafuError):
        if name == 'msg':   return target.msg
        if name == 'cause': return target.cause if target.cause is not None else UND
        if name == 'tb':    return target.tb_frames
        if name == 'nm':    return type(target).__name__
        return UND
    if isinstance(target, SnafuObj):
        if name in target.attrs: return target.attrs[name]
        for p in target.parents:
            v = get_attr(p, name, interp)
            if v is not UND: return v
        # Method-missing fallback: __mm__
        if '__mm__' in target.attrs:
            mm_fn = target.attrs['__mm__']
            return _MethodMissingProxy(mm_fn, name)
        return UND
    if isinstance(target, LazyThunk):
        if name == 'force': return lambda: target.force()
        if name == 'evaluated': return target.evaluated
        if name == 'value': return target.value
        return UND
    if isinstance(target, LogicVar):
        if name == 'val':
            return lambda: target.deref()
        if name == 'bound':
            return target.bound
        if name == 'name':
            return target.name
        return UND
    if isinstance(target, Variant):
        # Named field access
        if name in target.field_names:
            idx = target.field_names.index(name)
            return target.fields[idx]
        return UND
    # Complex number attributes
    if isinstance(target, complex):
        if name == 're': return target.real
        if name == 'im': return target.imag
        if name == 'conj': return lambda: target.conjugate()
        if name == 'abs': return lambda: abs(target)
        raise AttrErr(f"no attr '{name}' on Cx")
    # Transducer methods
    if isinstance(target, SnafuTransducer):
        if name == 'al': return lambda data: target.al(data)
        raise AttrErr(f"no attr '{name}' on Transducer")
    # Lens methods
    if isinstance(target, SnafuLens):
        if name == 'gt': return lambda obj: target.gt(obj)
        if name == 'st': return lambda obj, val: target.st(obj, val)
        if name == 'md': return lambda obj, fn: target.md(obj, fn)
        raise AttrErr(f"no attr '{name}' on Lens")
    # Traversal methods
    if isinstance(target, (SnafuTraversal, ComposedTraversal)):
        if name == 'gt': return lambda obj: target.gt(obj)
        if name == 'st': return lambda obj, val: target.st(obj, val)
        if name == 'md': return lambda obj, fn: target.md(obj, fn)
        raise AttrErr(f"no attr '{name}' on Traversal")
    # Prism methods
    if isinstance(target, SnafuPrism):
        if name == 'gt': return lambda obj: target.gt(obj)
        if name == 'st': return lambda obj, val: target.st(obj, val)
        if name == 'md': return lambda obj, fn: target.md(obj, fn)
        raise AttrErr(f"no attr '{name}' on Prism")
    # Methods on primitive types: look up in dispatch table
    # For v0.1, support some common methods inline
    if isinstance(target, str):
        methods = {
            'upr': lambda: target.upper(),
            'lwr': lambda: target.lower(),
            'strip': lambda: target.strip(),
            'lstrip': lambda: target.lstrip(),
            'rstrip': lambda: target.rstrip(),
            'trim': lambda: target.strip(),
            'split': lambda *args: target.split(*args) if args else target.split(),
            'starts': lambda x: target.startswith(x),
            'ends': lambda x: target.endswith(x),
            'find': lambda x: target.find(x),
            'count': lambda x: target.count(x),
            'replace': lambda a, b: target.replace(a, b),
            'join': lambda it: target.join(snafu_str(x) for x in it),
            'ca': lambda: _eval_string_as_code(target, interp),
            'len': lambda: len(target),
            'rev': lambda: target[::-1],
            'chars': lambda: list(target),
            'contains': lambda s: s in target,
            'repeat': lambda n: target * n,
            'idx': lambda s: target.find(s),
            'lines': lambda: target.split('\n'),
            'words': lambda: target.split(),
            'fmt': lambda spec: format(target, spec),
            'upper': lambda: target.upper(),
            'lower': lambda: target.lower(),
            'bytes': lambda: [b for b in target.encode('utf-8')],
            'pad': lambda n, ch=' ': target.ljust(n, ch),
            'lpad': lambda n, ch=' ': target.rjust(n, ch),
            'cpad': lambda n, ch=' ': target.center(n, ch),
            # Short aliases
            'sp': lambda *args: target.split(*args) if args else target.split(),
            'tr': lambda: target.strip(),
            'rpl': lambda a, b: target.replace(a, b),
            'sw': lambda x: target.startswith(x),
            'ew': lambda x: target.endswith(x),
            'rp': lambda n: target * int(n),
            'has': lambda x: x in target,
            'ws': lambda: target.split(),
            'ln': lambda: target.split('\n'),
            'cs': lambda: list(target),
        }
        if name in methods: return methods[name] if name in ('len',) else _make_method(target, methods[name])
    if isinstance(target, tuple):
        # Frozen list (immutable) — read-only methods only
        methods = {
            'len': lambda: len(target),
            'first': lambda: target[0] if target else UND,
            'last': lambda: target[-1] if target else UND,
            'rev': lambda: tuple(reversed(target)),
            'contains': lambda val: val in target,
            'idx': lambda val: list(target).index(val) if val in target else -1,
            'map': lambda f: tuple(_call_value(f, [x], {}) for x in target),
            'filter': lambda f: tuple(x for x in target if truthy(_call_value(f, [x], {}))),
            'take': lambda n: target[:n],
            'drop': lambda n: target[n:],
        }
        if name in methods: return _make_method(target, methods[name])
    if isinstance(target, list):
        methods = {
            'len': lambda: len(target),
            'psh': lambda x: (target.append(x), target)[-1] or target,
            'pop': lambda: target.pop(),
            'first': lambda: target[0] if target else UND,
            'last': lambda: target[-1] if target else UND,
            'rev': lambda: list(reversed(target)),
            'cp': lambda: list(target),
            'srt': lambda k=None, rv=False: _sort(target, k, rv),
            'flat': lambda: [x for sub in target for x in (sub if isinstance(sub, list) else [sub])],
            'any': lambda pred: any(truthy(_call_value(pred, [x], {})) for x in target),
            'all': lambda pred: all(truthy(_call_value(pred, [x], {})) for x in target),
            'find': lambda pred: next((x for x in target if truthy(_call_value(pred, [x], {}))), UND),
            'idx': lambda val: target.index(val) if val in target else -1,
            'contains': lambda val: val in target,
            'map': lambda f: [_call_value(f, [x], {}) for x in target],
            'filter': lambda f: [x for x in target if truthy(_call_value(f, [x], {}))],
            'reduce': lambda f, init=UND: _reduce(f, target, init),
            'take': lambda n: target[:n],
            'drop': lambda n: target[n:],
            'zip': lambda other: [list(t) for t in zip(target, other)],
            'en': lambda: [[i, x] for i, x in enumerate(target)],
            'sum': lambda: _sum(target, 0),
            'min': lambda: min(target) if target else UND,
            'max': lambda: max(target) if target else UND,
            'uniq': lambda: list(dict.fromkeys(target)),
            'sort_by': lambda f: (target.sort(key=lambda x: _call_value(f, [x], {})), target)[-1],
            'group_by': lambda f: _list_group_by(target, f),
            'chunk': lambda n: [target[i:i+n] for i in range(0, len(target), n)],
            'intersperse': lambda val: _list_intersperse(target, val),
            'each': lambda fn: (_do_each(target, fn), UND)[-1],
            # Short aliases
            'fl': lambda pred: [x for x in target if truthy(_call_value(pred, [x], {}))],
            'm': lambda fn: [_call_value(fn, [x], {}) for x in target],
            'rd': lambda fn, init=UND: _reduce(fn, target, init),
            'has': lambda val: val in target,
            'isp': lambda val: _list_intersperse(target, val),
            'gb': lambda fn: _list_group_by(target, fn),
            'sb': lambda fn: sorted(target, key=lambda x: _call_value(fn, [x], {})),
            # Set operations
            'union': lambda other: list(set(target) | set(other)),
            'inter': lambda other: list(set(target) & set(other)),
            'diff': lambda other: list(set(target) - set(other)),
            'symdiff': lambda other: list(set(target) ^ set(other)),
            'subset': lambda other: set(target) <= set(other),
            'superset': lambda other: set(target) >= set(other),
            # take_while / drop_while / flat_map
            'take_while': lambda pred: _take_while(target, pred),
            'drop_while': lambda pred: _drop_while(target, pred),
            'flat_map': lambda fn: [y for x in target for y in _call_value(fn, [x], {})],
            'tw': lambda pred: _take_while(target, pred),
            'dw': lambda pred: _drop_while(target, pred),
            'fm': lambda fn: [y for x in target for y in _call_value(fn, [x], {})],
        }
        if name in methods: return _make_method(target, methods[name])
    if isinstance(target, (dict, types.MappingProxyType)):
        methods = {
            'len': lambda: len(target),
            'keys': lambda: list(target.keys()),
            'values': lambda: list(target.values()),
            'items': lambda: [list(kv) for kv in target.items()],
            'pairs': lambda: [list(kv) for kv in target.items()],
            'cp': lambda: dict(target),
            'inv': lambda: {v: k for k, v in target.items()},
            'inv_get': lambda val: next((k for k, v in target.items() if v == val), UND),
            'has': lambda k: k in target,
            'merge': lambda other: {**target, **other},
            'map_vals': lambda f: {k: _call_value(f, [v], {}) for k, v in target.items()},
            'map_keys': lambda f: {_call_value(f, [k], {}): v for k, v in target.items()},
            'filter_vals': lambda f: {k: v for k, v in target.items() if truthy(_call_value(f, [v], {}))},
            'get': lambda k, default=UND: target[k] if k in target else default,
            'set': lambda k, v: {**target, k: v},
            'without': lambda k: {kk: vv for kk, vv in target.items() if kk != k},
            'update': lambda other: (target.update(other), target)[-1] if isinstance(target, dict) else {**target, **other},
            'to_list': lambda: [[k, v] for k, v in target.items()],
            'flip': lambda: {v: k for k, v in target.items()},
            # Short aliases
            'fv': lambda fn: {k: v for k, v in target.items() if truthy(_call_value(fn, [v], {}))},
            'mv': lambda fn: {k: _call_value(fn, [v], {}) for k, v in target.items()},
            'mk': lambda fn: {_call_value(fn, [k], {}): v for k, v in target.items()},
            'wo': lambda k: {k2: v for k2, v in target.items() if k2 != k},
            'mg': lambda other: {**target, **other},
            'up': lambda other: (target.update(other), target)[-1] if isinstance(target, dict) else {**target, **other},
        }
        if name in methods: return _make_method(target, methods[name])
    # SnafuGenerator methods
    if isinstance(target, SnafuGenerator):
        if name == 'sd': return lambda val: target.sd(val)
        if name == 'nx': return lambda: next(target)
    # Fallback: Python object attribute access (for py.import interop)
    try:
        val = getattr(target, name)
        return val
    except AttributeError:
        pass
    raise AttrErr(f"no attr '{name}' on {type_name(target)}")


def _make_method(target, fn):
    # Wrap zero-arg methods so they can be called without args
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


def _eval_string_as_code(code_str, interp, scope=None):
    """Parse and evaluate a Snafu code string."""
    tokens = Lexer(code_str, filename="<ev>").tokenize()
    tree = Parser(tokens, filename="<ev>").parse_program()
    return interp.eval_program(tree, scope=scope or interp.global_scope)


def _take_while(it, pred):
    result = []
    for x in it:
        if not truthy(_call_value(pred, [x], {})): break
        result.append(x)
    return result

def _drop_while(it, pred):
    result = []
    dropping = True
    for x in it:
        if dropping and truthy(_call_value(pred, [x], {})):
            continue
        dropping = False
        result.append(x)
    return result


def _call_value(fn, args, kwargs):
    """Call a function value. _TailCall results are trampolined."""
    if fn is UND: return UND
    if isinstance(fn, MultiDispatch):
        result = fn(*args, **kwargs)
    elif isinstance(fn, VariantCtor):
        result = fn(*args)
    elif callable(fn):
        result = fn(*args, **kwargs)
    else:
        raise TypeErr(f"not callable: {type_name(fn)}")
    # Trampoline: if the called function returned a _TailCall, keep resolving
    while isinstance(result, _TailCall):
        tc = result
        fn2 = tc.fn
        if fn2 is UND:
            return UND
        if isinstance(fn2, MultiDispatch):
            result = fn2(*tc.args, **tc.kwargs)
        elif isinstance(fn2, VariantCtor):
            result = fn2(*tc.args)
        elif callable(fn2):
            result = fn2(*tc.args, **tc.kwargs)
        else:
            raise TypeErr(f"not callable: {type_name(fn2)}")
    return result


def _detect_tail_calls(node, fn_name):
    """Mark Call nodes in tail position that call fn_name as implicit tail calls."""
    if node is None:
        return
    if isinstance(node, Block):
        if node.stmts:
            _detect_tail_calls(node.stmts[-1], fn_name)
    elif isinstance(node, BlockExpr):
        if node.stmts:
            _detect_tail_calls(node.stmts[-1], fn_name)
    elif isinstance(node, ExprStmt):
        _detect_tail_calls(node.expr, fn_name)
    elif isinstance(node, If):
        _detect_tail_calls(node.then, fn_name)
        for cond, body in node.elifs:
            _detect_tail_calls(body, fn_name)
        if node.else_:
            _detect_tail_calls(node.else_, fn_name)
    elif isinstance(node, Call):
        if isinstance(node.fn, Ident) and node.fn.name == fn_name:
            node._is_tail_call = True
    elif isinstance(node, Return):
        if isinstance(node.value, Call):
            if isinstance(node.value.fn, Ident) and node.value.fn.name == fn_name:
                node.value._is_tail_call = True


def _build_inverse_steps(node, param_name):
    """Given an expression tree containing param_name, build inverse steps.
    Returns a list of (step_type, operand_node) or None if not invertible."""
    if isinstance(node, Ident) and node.name == param_name:
        return []  # base case: x = y
    if isinstance(node, BinOp):
        left_has = _ast_has_name(node.lhs, param_name)
        right_has = _ast_has_name(node.rhs, param_name)
        if left_has and not right_has:
            inner = _build_inverse_steps(node.lhs, param_name)
            if inner is None:
                return None
            if node.op == '+':  return inner + [('sub', node.rhs)]
            if node.op == '-':  return inner + [('add', node.rhs)]
            if node.op == '*':  return inner + [('div', node.rhs)]
            if node.op == '/':  return inner + [('mul', node.rhs)]
            if node.op == '**': return inner + [('root', node.rhs)]
        elif right_has and not left_has:
            inner = _build_inverse_steps(node.rhs, param_name)
            if inner is None:
                return None
            if node.op == '+':  return inner + [('sub', node.lhs)]
            if node.op == '-':  return [('sub_from', node.lhs)] + inner
            if node.op == '*':  return inner + [('div', node.lhs)]
            if node.op == '/':  return [('div_into', node.lhs)] + inner
    return None  # can't invert


def _ast_has_name(node, name):
    """Check if an AST node (or subtree) contains a reference to `name`."""
    if isinstance(node, Ident):
        return node.name == name
    if isinstance(node, BinOp):
        return _ast_has_name(node.lhs, name) or _ast_has_name(node.rhs, name)
    if isinstance(node, UnaryOp):
        return _ast_has_name(node.operand, name)
    if isinstance(node, Call):
        if _ast_has_name(node.fn, name):
            return True
        return any(_ast_has_name(a[1], name) for a in node.args)
    return False


def _make_inverse_fn(steps, interp, scope):
    """Build an inverse function from inversion steps."""
    def inverse_fn(y):
        result = y
        for step_type, operand_node in reversed(steps):
            operand = interp.eval_node(operand_node, scope)
            if step_type == 'sub':       result = result - operand
            elif step_type == 'add':     result = result + operand
            elif step_type == 'mul':     result = result * operand
            elif step_type == 'div':     result = result / operand
            elif step_type == 'root':    result = result ** (1.0 / operand)
            elif step_type == 'sub_from': result = operand - result
            elif step_type == 'div_into': result = operand / result
        return result
    inverse_fn.__name__ = "<inverse>"
    return inverse_fn


def make_function(lam_node, def_scope, interp, name=None):
    """Create a Python callable from a Lambda AST node, closing over def_scope."""
    # Implicit tail-call optimization: detect self-recursive tail calls
    if name:
        _detect_tail_calls(lam_node.body, name)

    def snafu_fn(*args, **kwargs):
        call_scope = def_scope.child(name=name or "<lambda>")
        # Bind params
        params = lam_node.params
        pos_idx = 0
        star_param = None
        dstar_param = None
        # Build param info
        for i, p in enumerate(params):
            if p.kind == 'star':
                star_param = p.name
                # rest positional
                call_scope.define_local(p.name, list(args[pos_idx:]))
                pos_idx = len(args)
            elif p.kind == 'dstar':
                dstar_param = p.name
                call_scope.define_local(p.name, dict(kwargs))
                kwargs = {}
            else:
                if pos_idx < len(args):
                    call_scope.define_local(p.name, args[pos_idx])
                    pos_idx += 1
                elif p.name in kwargs:
                    call_scope.define_local(p.name, kwargs.pop(p.name))
                elif p.default is not None:
                    call_scope.define_local(p.name, interp.eval_node(p.default, def_scope))
                else:
                    raise ArgErr(f"missing argument '{p.name}' for {name or '<lambda>'}")
        # Implicit-args lambda
        if lam_node.implicit and not params:
            _implicit_names = ('a', 'b', 'c')
            for i, x in enumerate(args):
                if i < len(_implicit_names):
                    call_scope.define_local(_implicit_names[i], x)
                call_scope.define_local(f'a{i}', x)
            # Set missing implicit names to UND so they don't raise NameErr
            for i in range(len(args), len(_implicit_names)):
                call_scope.define_local(_implicit_names[i], UND)
        # Eval body
        try:
            result = interp.eval_node(lam_node.body, call_scope)
            return result
        except _Return as e:
            return e.value
        except _TailCallExc as tc:
            # Implicit TCO: if self-recursive, return _TailCall for trampoline
            return _TailCall(tc.fn, tc.args, tc.kwargs)
    snafu_fn.__name__ = name or "<lambda>"
    snafu_fn.__snafu_lambda__ = lam_node
    snafu_fn.__snafu_def_scope__ = def_scope
    return snafu_fn


# =============================================================================
#  PATTERN MATCHING
# =============================================================================

def match_pattern(pattern, value):
    """Return dict of bindings on successful match, None on failure."""
    if isinstance(pattern, PatLit):
        if _eq(pattern.value, value): return {}
        return None
    if isinstance(pattern, PatWild):
        return {}
    if isinstance(pattern, PatVar):
        return {pattern.name: value}
    if isinstance(pattern, PatAs):
        inner = match_pattern(pattern.pattern, value)
        if inner is None: return None
        inner[pattern.name] = value
        return inner
    if isinstance(pattern, PatOr):
        for alt in pattern.alts:
            m = match_pattern(alt, value)
            if m is not None: return m
        return None
    if isinstance(pattern, PatList):
        if not isinstance(value, list): return None
        elems = pattern.elems
        rest = pattern.rest
        if rest is None:
            if len(elems) != len(value): return None
            bindings = {}
            for p, v in zip(elems, value):
                m = match_pattern(p, v)
                if m is None: return None
                bindings.update(m)
            return bindings
        # With rest: at least len(elems) items
        if len(value) < len(elems): return None
        bindings = {}
        for p, v in zip(elems, value[:len(elems)]):
            m = match_pattern(p, v)
            if m is None: return None
            bindings.update(m)
        bindings[rest] = value[len(elems):]
        return bindings
    if isinstance(pattern, PatDict):
        if not isinstance(value, dict): return None
        bindings = {}
        for pair in pattern.pairs:
            if pair.key not in value: return None
            m = match_pattern(pair.pattern, value[pair.key])
            if m is None: return None
            bindings.update(m)
        if pattern.rest:
            remaining = {k: v for k, v in value.items() if k not in {p.key for p in pattern.pairs}}
            bindings[pattern.rest] = remaining
        return bindings
    if isinstance(pattern, PatVariant):
        # Variant match — check variant name + destructure fields
        if not isinstance(value, Variant): return None
        if value.name != pattern.name: return None
        if len(pattern.fields) != len(value.fields): return None
        bindings = {}
        for fp, fv in zip(pattern.fields, value.fields):
            m = match_pattern(fp, fv)
            if m is None: return None
            bindings.update(m)
        return bindings
    return None


# =============================================================================
#  PUBLIC API
# =============================================================================

def run(source, filename="<input>", interp=None):
    if interp is None:
        interp = Interpreter()
    tokens = Lexer(source, filename).tokenize()
    tree = Parser(tokens, filename).parse_program()
    # Self-modification support: expose source and AST in global scope
    interp.source = source
    interp.source_file = filename
    interp.global_scope.define_local('src', source)
    interp.global_scope.define_local('ast', tree)
    return interp.eval_program(tree)


def run_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    result = run(src, filename=path)
    # Auto-print last expression in file mode
    if result is not None and result is not UND:
        print(snafu_repr(result))
    return result


def _unclosed(text):
    """Return True if text has unclosed brackets or ends with backslash continuation."""
    if text.rstrip().endswith('\\'):
        return True
    depth = 0
    in_str = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
    return depth > 0


def repl():
    interp = Interpreter()
    history = []
    print("Snafu v0.1 REPL.  Type /help for commands, Ctrl-D to exit.")
    while True:
        try:
            line = input("snafu> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            continue

        # --- Multi-line input: accumulate while brackets are unclosed ---
        while _unclosed(line):
            try:
                line += "\n" + input("...... ")
            except (EOFError, KeyboardInterrupt):
                break

        stripped = line.strip()

        # --- REPL slash commands ---
        if stripped.startswith('/'):
            parts = stripped.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == '/help':
                print("REPL commands:")
                print("  /help           show this help")
                print("  /history        show input history")
                print("  /clear          reset scope (fresh bindings)")
                print("  /save <path>    save history to file")
                print("  /load <path>    run a file in current REPL scope")
                print("  /type <expr>    show type of expression")
                print("  /ast <expr>     show AST of expression")
                print("  /time <expr>    time an expression")
                print("  /vm <expr>      run expression through bytecode VM")
                continue

            if cmd == '/history':
                if not history:
                    print("  (no history)")
                else:
                    for i, entry in enumerate(history, 1):
                        # Show first line, plus indicator if multi-line
                        first = entry.split('\n', 1)[0]
                        suffix = " ..." if '\n' in entry else ""
                        print(f"  {i}: {first}{suffix}")
                continue

            if cmd == '/clear':
                interp = Interpreter()
                print("  scope cleared")
                continue

            if cmd == '/save':
                if not arg:
                    print("  usage: /save <path>")
                    continue
                try:
                    with open(arg, 'w', encoding='utf-8') as f:
                        for entry in history:
                            f.write(entry + '\n')
                    print(f"  saved {len(history)} entries to {arg}")
                except OSError as e:
                    print(f"  ! IOErr: {e}")
                continue

            if cmd == '/load':
                if not arg:
                    print("  usage: /load <path>")
                    continue
                try:
                    with open(arg, 'r', encoding='utf-8') as f:
                        src = f.read()
                    result = run(src, filename=arg, interp=interp)
                    if result is not None and result is not UND:
                        print(snafu_repr(result))
                    print(f"  loaded {arg}")
                except OSError as e:
                    print(f"  ! IOErr: {e}")
                except SnafuError as e:
                    print(f"  ! {type(e).__name__}: {e.msg}")
                except Exception as e:
                    traceback.print_exc()
                continue

            if cmd == '/type':
                if not arg:
                    print("  usage: /type <expr>")
                    continue
                try:
                    val = run(arg, filename="<repl>", interp=interp)
                    print(f"  {type_name(val)}")
                except SnafuError as e:
                    print(f"  ! {type(e).__name__}: {e.msg}")
                except Exception as e:
                    traceback.print_exc()
                continue

            if cmd == '/ast':
                if not arg:
                    print("  usage: /ast <expr>")
                    continue
                try:
                    tokens = Lexer(arg, "<repl>").tokenize()
                    tree = Parser(tokens, "<repl>").parse_program()
                    print(f"  {tree}")
                except SnafuError as e:
                    print(f"  ! {type(e).__name__}: {e.msg}")
                except Exception as e:
                    traceback.print_exc()
                continue

            if cmd == '/time':
                if not arg:
                    print("  usage: /time <expr>")
                    continue
                try:
                    t0 = time.perf_counter()
                    val = run(arg, filename="<repl>", interp=interp)
                    elapsed = time.perf_counter() - t0
                    if val is not None and val is not UND:
                        print(snafu_repr(val))
                    if elapsed < 0.001:
                        print(f"  {elapsed * 1_000_000:.1f} us")
                    elif elapsed < 1.0:
                        print(f"  {elapsed * 1000:.2f} ms")
                    else:
                        print(f"  {elapsed:.3f} s")
                except SnafuError as e:
                    print(f"  ! {type(e).__name__}: {e.msg}")
                except Exception as e:
                    traceback.print_exc()
                continue

            if cmd == '/vm':
                if not arg:
                    print("  usage: /vm <expr>")
                    continue
                try:
                    import snafu_vm
                    val = snafu_vm.run_vm(arg, filename="<repl>")
                    if val is not None and val is not UND:
                        print(snafu_repr(val))
                except ImportError:
                    print("  ! snafu_vm.py not found")
                except SnafuError as e:
                    print(f"  ! {type(e).__name__}: {e.msg}")
                except Exception as e:
                    traceback.print_exc()
                continue

            # Unknown slash command
            print(f"  unknown command: {cmd}  (type /help)")
            continue

        # --- Normal input: parse and evaluate ---
        try:
            tokens = Lexer(stripped, "<repl>").tokenize()
            tree = Parser(tokens, "<repl>").parse_program()
            interp.source = stripped
            interp.source_file = "<repl>"
            interp.global_scope.define_local('src', stripped)
            interp.global_scope.define_local('ast', tree)
            result = interp.eval_program(tree)
            history.append(stripped)
            # Auto-print: show result for expressions, suppress for assignments/statements
            if result is not None and result is not UND:
                last = tree.stmts[-1] if tree.stmts else None
                is_stmt = isinstance(last, (Assign, If, For, While, Loop,
                                            FnDecl, SumDecl, ProtoDecl, ImplDecl,
                                            Try, On, Off, CondTrigger))
                if not is_stmt:
                    print(snafu_repr(result))
        except SnafuError as e:
            print(f"! {type(e).__name__}: {e.msg}")
        except Exception as e:
            traceback.print_exc()


def main():
    args = sys.argv[1:]
    if not args:
        repl()
        return
    if args[0] == '-e':
        if len(args) < 2: print("usage: snafu.py -e <expr>"); sys.exit(1)
        result = run(args[1], filename="<cmdline>")
        if result is not None and result is not UND:
            print(snafu_repr(result))
        return
    run_file(args[0])


if __name__ == '__main__':
    main()
