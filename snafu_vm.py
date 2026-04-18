#!/usr/bin/env python3
"""
Snafu bytecode compiler and stack-based VM.

Compiles the common-case AST nodes (literals, arithmetic, assignment,
control flow, function calls) to a compact bytecode and executes them
on a stack machine.  Exotic features (pattern matching, algebraic
effects, macros, self-modification, etc.) fall back transparently to
the tree-walking interpreter via an EVAL_AST opcode.

Function bodies are compiled to bytecode as well, so recursive calls
like fib(30) run entirely on the VM without tree-walking overhead.

Usage:
    python snafu_vm.py <file.snf>
    python snafu_vm.py -e "expr"
    python snafu_vm.py --bench          # fib(30) benchmark
    python snafu_vm.py --dis "expr"     # disassemble
"""

from __future__ import annotations
import sys, os, time, math
from dataclasses import dataclass, field
from typing import Any, List

# ---------------------------------------------------------------------------
#  Import the lexer, parser, and runtime helpers from snafu.py
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import snafu
from snafu import (
    Lexer, Parser, Interpreter, Scope,
    UND, UndType, _Return, _Break, _Continue, _TailCall, _TailCallExc,
    truthy, snafu_str, snafu_repr, _call_value, _add, _mul, _div, _eq,
    _binop_sub, apply_binop, make_function, match_pattern,
    # AST nodes we compile
    Node, NumLit, StrLit, BoolLit, UndLit, OoLit, Ident, BinOp, UnaryOp,
    Call, Index, Attr, Assign, ExprStmt, If, For, While, Loop,
    Block, BlockExpr, Return, Break, Continue, FnDecl, Lambda,
    ListExpr, CollElem, Ternary, Pipe,
    # AST nodes for fallback awareness
    ParamSpec, PatVar,
    # Errors
    SnafuError, TypeErr, DivErr, NameErr, ArgErr,
)

# ---------------------------------------------------------------------------
#  Opcodes
# ---------------------------------------------------------------------------
LOAD_CONST       = 1
LOAD_NAME        = 2
STORE_NAME       = 3
LOAD_ATTR        = 4
STORE_ATTR       = 5

BINARY_ADD       = 10
BINARY_SUB       = 11
BINARY_MUL       = 12
BINARY_DIV       = 13
BINARY_MOD       = 14
BINARY_POW       = 15
BINARY_EQ        = 16
BINARY_LT        = 17
BINARY_GT        = 18
BINARY_LE        = 19
BINARY_GE        = 20
BINARY_NE        = 21
BINARY_GENERIC   = 25

UNARY_NEG        = 30
UNARY_NOT        = 31
UNARY_POS        = 32
UNARY_LEN        = 33

JUMP             = 40
JUMP_IF_FALSE    = 41
JUMP_IF_TRUE     = 42
JUMP_IF_FALSE_KP = 43   # if falsy keep TOS and jump; else pop TOS
JUMP_IF_TRUE_KP  = 44   # if truthy keep TOS and jump; else pop TOS

CALL             = 50
RETURN           = 51
MAKE_VM_FN       = 52   # arg = const index of (code_obj, param_names, fn_name)

BUILD_LIST       = 60
BUILD_DICT       = 61
INDEX            = 62

POP              = 70
DUP              = 71

BREAK            = 75
CONTINUE         = 76

PRINT            = 80
EVAL_AST         = 90
FOR_ITER         = 91
STORE_LOCAL      = 92
HALT             = 99

_OP_NAMES = {
    1: 'LOAD_CONST', 2: 'LOAD_NAME', 3: 'STORE_NAME',
    4: 'LOAD_ATTR', 5: 'STORE_ATTR',
    10: 'BINARY_ADD', 11: 'BINARY_SUB', 12: 'BINARY_MUL',
    13: 'BINARY_DIV', 14: 'BINARY_MOD', 15: 'BINARY_POW',
    16: 'BINARY_EQ', 17: 'BINARY_LT', 18: 'BINARY_GT',
    19: 'BINARY_LE', 20: 'BINARY_GE', 21: 'BINARY_NE',
    25: 'BINARY_GENERIC',
    30: 'UNARY_NEG', 31: 'UNARY_NOT', 32: 'UNARY_POS', 33: 'UNARY_LEN',
    40: 'JUMP', 41: 'JUMP_IF_FALSE', 42: 'JUMP_IF_TRUE',
    43: 'JUMP_IF_FALSE_KP', 44: 'JUMP_IF_TRUE_KP',
    50: 'CALL', 51: 'RETURN', 52: 'MAKE_VM_FN',
    60: 'BUILD_LIST', 61: 'BUILD_DICT', 62: 'INDEX',
    70: 'POP', 71: 'DUP',
    75: 'BREAK', 76: 'CONTINUE',
    80: 'PRINT', 90: 'EVAL_AST', 91: 'FOR_ITER', 92: 'STORE_LOCAL',
    99: 'HALT',
}


# ---------------------------------------------------------------------------
#  CodeObject
# ---------------------------------------------------------------------------
class CodeObject:
    __slots__ = ('bytecode', 'constants', 'names', 'name', '_ops', '_args')

    def __init__(self, bytecode, constants, names, name="<module>"):
        self.bytecode = bytecode
        self.constants = constants
        self.names = names
        self.name = name
        # Pre-split for VM speed (avoids tuple unpack per instruction)
        self._ops = [op for op, _ in bytecode]
        self._args = [arg for _, arg in bytecode]


# ---------------------------------------------------------------------------
#  Compiler
# ---------------------------------------------------------------------------
class Compiler:
    """Walk the AST and emit bytecode into a CodeObject."""

    def __init__(self):
        self.code: List[tuple] = []
        self.constants: List[Any] = []
        self.names: List[str] = []
        self._name_index: dict = {}
        # Loop tracking for break/continue: stack of (loop_top, break_patches)
        self._loop_stack: List[tuple] = []

    # -- helpers --

    def emit(self, op: int, arg: int = 0):
        self.code.append((op, arg))

    def add_const(self, value) -> int:
        idx = len(self.constants)
        self.constants.append(value)
        return idx

    def add_name(self, name: str) -> int:
        if name in self._name_index:
            return self._name_index[name]
        idx = len(self.names)
        self.names.append(name)
        self._name_index[name] = idx
        return idx

    def to_code_object(self, name: str = "<module>") -> CodeObject:
        return CodeObject(self.code, self.constants, self.names, name)

    # -- main dispatch --

    def compile(self, node):
        if node is None:
            self.emit(LOAD_CONST, self.add_const(UND))
            return
        method = getattr(self, f'compile_{type(node).__name__}', None)
        if method is not None:
            method(node)
        else:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    # -- literals --

    def compile_NumLit(self, node):
        self.emit(LOAD_CONST, self.add_const(node.value))

    def compile_StrLit(self, node):
        pieces = node.pieces
        if len(pieces) == 1 and pieces[0][0] == 'str':
            self.emit(LOAD_CONST, self.add_const(pieces[0][1]))
        else:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    def compile_BoolLit(self, node):
        self.emit(LOAD_CONST, self.add_const(node.value))

    def compile_UndLit(self, node):
        self.emit(LOAD_CONST, self.add_const(UND))

    def compile_OoLit(self, node):
        self.emit(LOAD_CONST, self.add_const(math.inf))

    # -- references --

    def compile_Ident(self, node):
        self.emit(LOAD_NAME, self.add_name(node.name))

    def compile_Attr(self, node):
        self.compile(node.target)
        self.emit(LOAD_ATTR, self.add_name(node.name))

    # -- binary operations --

    _SIMPLE_BINOP = {
        '+':  BINARY_ADD,  '-':  BINARY_SUB,  '*':  BINARY_MUL,
        '/':  BINARY_DIV,  '%':  BINARY_MOD,  '**': BINARY_POW,
        '==': BINARY_EQ,   '<':  BINARY_LT,   '>':  BINARY_GT,
        '<=': BINARY_LE,   '>=': BINARY_GE,   '<>': BINARY_NE,
    }

    def compile_BinOp(self, node):
        op = node.op
        # Short-circuit: &&
        if op == '&&':
            self.compile(node.lhs)
            self.emit(DUP)
            jmp = len(self.code)
            self.emit(JUMP_IF_FALSE_KP, 0)
            self.emit(POP)
            self.compile(node.rhs)
            self.code[jmp] = (JUMP_IF_FALSE_KP, len(self.code))
            return
        # Short-circuit: ||
        if op == '||':
            self.compile(node.lhs)
            self.emit(DUP)
            jmp = len(self.code)
            self.emit(JUMP_IF_TRUE_KP, 0)
            self.emit(POP)
            self.compile(node.rhs)
            self.code[jmp] = (JUMP_IF_TRUE_KP, len(self.code))
            return
        # Short-circuit: ??
        if op == '??':
            self.compile(node.lhs)
            self.emit(DUP)
            jmp = len(self.code)
            self.emit(JUMP_IF_TRUE_KP, 0)
            self.emit(POP)
            self.compile(node.rhs)
            self.code[jmp] = (JUMP_IF_TRUE_KP, len(self.code))
            return
        # Simple binary ops
        simple = self._SIMPLE_BINOP.get(op)
        if simple is not None:
            self.compile(node.lhs)
            self.compile(node.rhs)
            self.emit(simple)
            return
        # Generic fallback for rare ops
        self.compile(node.lhs)
        self.compile(node.rhs)
        self.emit(BINARY_GENERIC, self.add_const(op))

    # -- unary operations --

    def compile_UnaryOp(self, node):
        op = node.op
        if op in ('-', '!', '+', '#'):
            self.compile(node.operand)
            self.emit({'-': UNARY_NEG, '!': UNARY_NOT,
                       '+': UNARY_POS, '#': UNARY_LEN}[op])
        else:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    # -- ternary --

    def compile_Ternary(self, node):
        self.compile(node.cond)
        jf = len(self.code)
        self.emit(JUMP_IF_FALSE, 0)
        self.compile(node.then)
        je = len(self.code)
        self.emit(JUMP, 0)
        self.code[jf] = (JUMP_IF_FALSE, len(self.code))
        self.compile(node.else_)
        self.code[je] = (JUMP, len(self.code))

    # -- index --

    def compile_Index(self, node):
        self.compile(node.target)
        self.compile(node.key)
        self.emit(INDEX)

    # -- assignment --

    def compile_Assign(self, node):
        if node.op == '=' and isinstance(node.target, Ident):
            self.compile(node.value)
            self.emit(DUP)
            self.emit(STORE_NAME, self.add_name(node.target.name))
            return
        if node.op in ('+=', '-=', '*=', '/=', '%=', '**=') and isinstance(node.target, Ident):
            ni = self.add_name(node.target.name)
            self.emit(LOAD_NAME, ni)
            self.compile(node.value)
            base_op = node.op[:-1]
            s = self._SIMPLE_BINOP.get(base_op)
            if s is not None:
                self.emit(s)
            else:
                self.emit(BINARY_GENERIC, self.add_const(base_op))
            self.emit(DUP)
            self.emit(STORE_NAME, ni)
            return
        if node.op == '=' and isinstance(node.target, Attr):
            self.compile(node.target.target)
            self.compile(node.value)
            self.emit(STORE_ATTR, self.add_name(node.target.name))
            return
        # Fallback
        idx = self.add_const(node)
        self.emit(LOAD_CONST, idx)
        self.emit(EVAL_AST, 0)

    # -- statements --

    def compile_ExprStmt(self, node):
        self.compile(node.expr)

    # -- blocks --

    def _compile_stmts(self, stmts):
        if not stmts:
            self.emit(LOAD_CONST, self.add_const(UND))
            return
        for i, stmt in enumerate(stmts):
            self.compile(stmt)
            if i < len(stmts) - 1:
                self.emit(POP)

    def compile_Block(self, node):
        self._compile_stmts(node.stmts)

    def compile_BlockExpr(self, node):
        self._compile_stmts(node.stmts)

    # -- if/elif/else --

    def compile_If(self, node):
        self.compile(node.cond)
        jf = len(self.code)
        self.emit(JUMP_IF_FALSE, 0)
        self.compile(node.then)

        if node.elifs or node.else_:
            jump_ends = []
            jump_ends.append(len(self.code))
            self.emit(JUMP, 0)
            self.code[jf] = (JUMP_IF_FALSE, len(self.code))

            for econd, ebody in node.elifs:
                self.compile(econd)
                ejf = len(self.code)
                self.emit(JUMP_IF_FALSE, 0)
                self.compile(ebody)
                jump_ends.append(len(self.code))
                self.emit(JUMP, 0)
                self.code[ejf] = (JUMP_IF_FALSE, len(self.code))

            if node.else_:
                self.compile(node.else_)
            else:
                self.emit(LOAD_CONST, self.add_const(UND))

            end = len(self.code)
            for je in jump_ends:
                self.code[je] = (JUMP, end)
        else:
            # No else: then-path leaves value; false-path needs UND
            jo = len(self.code)
            self.emit(JUMP, 0)
            self.code[jf] = (JUMP_IF_FALSE, len(self.code))
            self.emit(LOAD_CONST, self.add_const(UND))
            self.code[jo] = (JUMP, len(self.code))

    # -- while loop --

    def compile_While(self, node):
        if node.loop_tail:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)
            return
        self.emit(LOAD_CONST, self.add_const(UND))
        loop_top = len(self.code)
        break_patches = []
        self._loop_stack.append((loop_top, break_patches))
        self.compile(node.cond)
        if node.is_until:
            # until-loop: jump if TRUE (condition is met => stop)
            jx = len(self.code)
            self.emit(JUMP_IF_TRUE, 0)
        else:
            jx = len(self.code)
            self.emit(JUMP_IF_FALSE, 0)
        self.emit(POP)
        self.compile(node.body)
        self.emit(JUMP, loop_top)
        if node.is_until:
            self.code[jx] = (JUMP_IF_TRUE, len(self.code))
        else:
            self.code[jx] = (JUMP_IF_FALSE, len(self.code))
        self._loop_stack.pop()
        # Patch all break jumps to point here (after the loop)
        for bp in break_patches:
            self.code[bp] = (JUMP, len(self.code))

    # -- for loop --

    def compile_For(self, node):
        # Accept both Ident and PatVar as simple loop patterns
        pat = node.pattern
        if isinstance(pat, Ident):
            var_name = pat.name
        elif isinstance(pat, PatVar):
            var_name = pat.name
        else:
            var_name = None
        if node.filter or node.loop_tail or var_name is None:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)
            return
        ni = self.add_name(var_name)
        iter_ni = self.add_name(f"__iter_{var_name}__")
        self.compile(node.iter)
        self.emit(STORE_LOCAL, iter_ni)
        self.emit(LOAD_CONST, self.add_const(UND))
        loop_top = len(self.code)
        break_patches = []
        self._loop_stack.append((loop_top, break_patches))
        self.emit(LOAD_NAME, iter_ni)
        fi = len(self.code)
        self.emit(FOR_ITER, 0)
        self.emit(STORE_LOCAL, ni)
        self.emit(POP)
        self.compile(node.body)
        self.emit(JUMP, loop_top)
        self.code[fi] = (FOR_ITER, len(self.code))
        self._loop_stack.pop()
        # Patch all break jumps to point here (after the loop)
        for bp in break_patches:
            self.code[bp] = (JUMP, len(self.code))

    # -- loop (fallback) --

    def compile_Loop(self, node):
        idx = self.add_const(node)
        self.emit(LOAD_CONST, idx)
        self.emit(EVAL_AST, 0)

    # -- function call --

    def compile_Call(self, node):
        # p() fast path
        if isinstance(node.fn, Ident) and node.fn.name == 'p' and not node.kwargs:
            args = node.args
            if len(args) == 1 and args[0][0] == 'pos':
                self.compile(args[0][1])
                self.emit(PRINT)
                return

        # Only compile simple positional calls
        if node.kwargs or any(k != 'pos' for k, _ in node.args):
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)
            return

        self.compile(node.fn)
        for _, arg_node in node.args:
            self.compile(arg_node)
        self.emit(CALL, len(node.args))

    # -- function declaration (compiled bodies!) --

    def _is_simple_fn(self, node):
        """Check if a FnDecl can have its body compiled to VM bytecode."""
        if node.decorators or node.precond is not None or node.postcond is not None:
            return False
        # Only simple positional params (no *args, **kwargs, typed dispatch)
        for p in node.params:
            if p.kind != 'pos':
                return False
            if p.type_name is not None:
                return False
        return True

    def compile_FnDecl(self, node):
        if not self._is_simple_fn(node):
            # Fall back to tree-walker for complex functions
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)
            return
        # Compile the body into a child CodeObject
        body_compiler = Compiler()
        body_compiler.compile(node.body)
        body_compiler.emit(RETURN)
        body_code = body_compiler.to_code_object(node.name)
        # Param info: list of (name, default_node_or_None)
        param_info = [(p.name, p.default) for p in node.params]
        # Store (code_obj, param_info, fn_name) as a const
        bundle = (body_code, param_info, node.name)
        ci = self.add_const(bundle)
        self.emit(MAKE_VM_FN, ci)
        self.emit(DUP)
        self.emit(STORE_NAME, self.add_name(node.name))

    # -- lambda --

    def _is_simple_lambda(self, node):
        if node.implicit:
            return False
        for p in node.params:
            if p.kind != 'pos':
                return False
            if p.type_name is not None:
                return False
        return True

    def compile_Lambda(self, node):
        if not self._is_simple_lambda(node):
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)
            return
        body_compiler = Compiler()
        body_compiler.compile(node.body)
        body_compiler.emit(RETURN)
        body_code = body_compiler.to_code_object("<lambda>")
        param_info = [(p.name, p.default) for p in node.params]
        bundle = (body_code, param_info, "<lambda>")
        ci = self.add_const(bundle)
        self.emit(MAKE_VM_FN, ci)

    # -- return --

    def compile_Return(self, node):
        if node.value:
            self.compile(node.value)
        else:
            self.emit(LOAD_CONST, self.add_const(UND))
        self.emit(RETURN)

    # -- break / continue --

    def compile_Break(self, node):
        if self._loop_stack:
            _, break_patches = self._loop_stack[-1]
            break_patches.append(len(self.code))
            self.emit(JUMP, 0)  # placeholder, patched at loop end
        else:
            # Outside a compiled loop — fall back to tree-walker
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    def compile_Continue(self, node):
        if self._loop_stack:
            loop_top, _ = self._loop_stack[-1]
            self.emit(POP)      # discard current iteration result
            self.emit(JUMP, loop_top)
        else:
            # Outside a compiled loop — fall back to tree-walker
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    # -- list literal --

    def compile_ListExpr(self, node):
        items = node.items
        all_pos = all(isinstance(e, CollElem) and e.kind == 'pos' for e in items)
        all_kv = all(isinstance(e, CollElem) and e.kind == 'kv' for e in items)
        if all_pos:
            for elem in items:
                self.compile(elem.value)
            self.emit(BUILD_LIST, len(items))
        elif all_kv:
            for elem in items:
                self.compile(elem.key)
                self.compile(elem.value)
            self.emit(BUILD_DICT, len(items))
        else:
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)

    # -- pipe --

    def compile_Pipe(self, node):
        if node.op == '|>' and isinstance(node.rhs, Call):
            # lhs |> f(a, b) => f(lhs, a, b)
            # Only handle simple positional args
            if node.rhs.kwargs or any(k != 'pos' for k, _ in node.rhs.args):
                idx = self.add_const(node)
                self.emit(LOAD_CONST, idx)
                self.emit(EVAL_AST, 0)
                return
            self.compile(node.rhs.fn)  # push fn
            self.compile(node.lhs)     # push lhs (first arg)
            for _, arg_node in node.rhs.args:
                self.compile(arg_node)
            self.emit(CALL, 1 + len(node.rhs.args))
        elif node.op == '|>':
            # lhs |> f => f(lhs)
            self.compile(node.rhs)
            self.compile(node.lhs)
            self.emit(CALL, 1)
        else:
            # Other pipe ops (|>>, |?>) -- fallback
            idx = self.add_const(node)
            self.emit(LOAD_CONST, idx)
            self.emit(EVAL_AST, 0)


# ---------------------------------------------------------------------------
#  VM-compiled function wrapper
# ---------------------------------------------------------------------------

class _VMFunction:
    """A callable whose body executes on the VM instead of tree-walking."""
    __slots__ = ('code_obj', 'param_names', 'param_defaults', 'nparams',
                 'name', 'def_scope', 'vm')

    def __init__(self, code_obj, param_info, name, def_scope, vm):
        self.code_obj = code_obj
        self.param_names = [p[0] for p in param_info]
        self.param_defaults = [p[1] for p in param_info]
        self.nparams = len(param_info)
        self.name = name
        self.def_scope = def_scope
        self.vm = vm

    def __call__(self, *args, **kwargs):
        cs = Scope.__new__(Scope)
        cs.bindings = {}
        cs.parent = self.def_scope
        cs.name = self.name
        cs.on_assign_hook = None
        cs._defers = []
        pn = self.param_names
        pd = self.param_defaults
        nargs = len(args)
        for i in range(self.nparams):
            if i < nargs:
                cs.bindings[pn[i]] = args[i]
            elif pd[i] is not None:
                cs.bindings[pn[i]] = self.vm.interp.eval_node(pd[i], self.def_scope)
            else:
                raise ArgErr(f"missing argument '{pn[i]}' for {self.name}")
        rv = self.vm._run(self.code_obj, cs)
        if type(rv) is _Returned:
            return rv.value
        return rv

    def __repr__(self):
        return f"<vm-fn {self.name}>"

    @property
    def __name__(self):
        return self.name


# ---------------------------------------------------------------------------
#  VM
# ---------------------------------------------------------------------------

# Sentinel for function returns (avoids expensive exception raising/catching)
class _Returned:
    __slots__ = ('value',)
    def __init__(self, v):
        self.value = v

_RETURNED_UND = _Returned(UND)  # pre-allocated for bare returns


class VM:
    """Stack-based virtual machine for Snafu bytecode."""

    def __init__(self, interp: Interpreter = None):
        if interp is None:
            interp = Interpreter()
        self.interp = interp

    def execute(self, code_obj: CodeObject, scope: Scope = None) -> Any:
        """Public entry: run code, unwrap _Returned if needed."""
        result = self._run(code_obj, scope)
        if type(result) is _Returned:
            return result.value
        return result

    def _run(self, code_obj: CodeObject, scope: Scope = None) -> Any:
        """Internal: run code, return _Returned on RETURN opcode."""
        if scope is None:
            scope = self.interp.global_scope

        stack = []
        ip = 0
        ops = code_obj._ops
        args_arr = code_obj._args
        constants = code_obj.constants
        names = code_obj.names
        bc_len = len(ops)

        _UND = UND
        _truthy = truthy
        _snafu_str = snafu_str
        _bindings = scope.bindings
        s_lookup = scope.lookup
        s_assign = scope.assign
        s_def_local = scope.define_local
        sa = stack.append
        sp = stack.pop
        _Scope = Scope
        _VMFn = _VMFunction
        _self_run = self._run

        _iters = {}

        while ip < bc_len:
            op = ops[ip]
            arg = args_arr[ip]
            ip += 1

            # ------ HOT PATH ------

            if op == LOAD_NAME:
                _n = names[arg]
                if _n in _bindings:
                    sa(_bindings[_n])
                else:
                    sa(s_lookup(_n))
                continue

            if op == LOAD_CONST:
                sa(constants[arg])
                continue

            if op == CALL:
                nargs = arg
                if nargs == 1:
                    _a0 = sp()
                    fn = sp()
                    if type(fn) is _VMFn and fn.nparams == 1:
                        _cs = _Scope.__new__(_Scope)
                        _cs.bindings = {fn.param_names[0]: _a0}
                        _cs.parent = fn.def_scope
                        _cs.name = fn.name
                        _cs.on_assign_hook = None
                        _cs._defers = []
                        _rv = _self_run(fn.code_obj, _cs)
                        sa(_rv.value if type(_rv) is _Returned else _rv)
                    elif type(fn) is _VMFn:
                        sa(fn(_a0))
                    else:
                        sa(_call_value(fn, [_a0], {}))
                elif nargs == 0:
                    fn = sp()
                    if type(fn) is _VMFn and fn.nparams == 0:
                        _cs = _Scope.__new__(_Scope)
                        _cs.bindings = {}
                        _cs.parent = fn.def_scope
                        _cs.name = fn.name
                        _cs.on_assign_hook = None
                        _cs._defers = []
                        _rv = _self_run(fn.code_obj, _cs)
                        sa(_rv.value if type(_rv) is _Returned else _rv)
                    elif type(fn) is _VMFn:
                        sa(fn())
                    else:
                        sa(_call_value(fn, [], {}))
                elif nargs == 2:
                    _a1 = sp(); _a0 = sp()
                    fn = sp()
                    if type(fn) is _VMFn and fn.nparams == 2:
                        _cs = _Scope.__new__(_Scope)
                        _pn = fn.param_names
                        _cs.bindings = {_pn[0]: _a0, _pn[1]: _a1}
                        _cs.parent = fn.def_scope
                        _cs.name = fn.name
                        _cs.on_assign_hook = None
                        _cs._defers = []
                        _rv = _self_run(fn.code_obj, _cs)
                        sa(_rv.value if type(_rv) is _Returned else _rv)
                    elif type(fn) is _VMFn:
                        sa(fn(_a0, _a1))
                    else:
                        sa(_call_value(fn, [_a0, _a1], {}))
                else:
                    al = []
                    for _ in range(nargs):
                        al.append(sp())
                    al.reverse()
                    fn = sp()
                    if type(fn) is _VMFn and fn.nparams == nargs:
                        _cs = _Scope.__new__(_Scope)
                        _cs.bindings = dict(zip(fn.param_names, al))
                        _cs.parent = fn.def_scope
                        _cs.name = fn.name
                        _cs.on_assign_hook = None
                        _cs._defers = []
                        _rv = _self_run(fn.code_obj, _cs)
                        sa(_rv.value if type(_rv) is _Returned else _rv)
                    elif type(fn) is _VMFn:
                        sa(fn(*al))
                    else:
                        sa(_call_value(fn, al, {}))
                continue

            if op == BINARY_ADD:
                r = sp(); l = sp()
                sa(l + r if type(l) is int and type(r) is int else _add(l, r))
                continue

            if op == BINARY_SUB:
                r = sp(); l = sp()
                sa(l - r if type(l) is int and type(r) is int else _binop_sub(l, r))
                continue

            if op == BINARY_LT:
                r = sp(); l = sp()
                sa(l < r)
                continue

            if op == JUMP_IF_FALSE:
                _v = sp()
                if _v is False or _v is _UND or _v == 0:
                    ip = arg
                elif _v is not True and not _truthy(_v):
                    ip = arg
                continue

            if op == JUMP:
                ip = arg
                continue

            if op == RETURN:
                return _Returned(sp())

            # ------ WARM PATH ------

            if op == STORE_NAME:
                s_assign(names[arg], sp())
                continue

            if op == BINARY_MUL:
                r = sp(); l = sp()
                sa(l * r if type(l) is int and type(r) is int else _mul(l, r))
                continue

            if op == BINARY_GT:
                r = sp()
                sa(sp() > r)
                continue

            if op == BINARY_LE:
                r = sp()
                sa(sp() <= r)
                continue

            if op == BINARY_GE:
                r = sp()
                sa(sp() >= r)
                continue

            if op == BINARY_EQ:
                r = sp()
                sa(_eq(sp(), r))
                continue

            if op == BINARY_NE:
                r = sp()
                sa(not _eq(sp(), r))
                continue

            if op == BINARY_DIV:
                r = sp(); l = sp()
                sa(_div(l, r))
                continue

            if op == BINARY_MOD:
                r = sp()
                sa(sp() % r)
                continue

            if op == BINARY_POW:
                r = sp()
                sa(sp() ** r)
                continue

            if op == BINARY_GENERIC:
                r = sp(); l = sp()
                sa(apply_binop(constants[arg], l, r))
                continue

            if op == UNARY_NEG:
                sa(-sp())
                continue

            if op == UNARY_NOT:
                sa(not _truthy(sp()))
                continue

            if op == UNARY_POS:
                sa(+sp())
                continue

            if op == UNARY_LEN:
                sa(len(sp()))
                continue

            if op == JUMP_IF_TRUE:
                if _truthy(sp()):
                    ip = arg
                continue

            if op == JUMP_IF_FALSE_KP:
                if not _truthy(stack[-1]):
                    ip = arg
                else:
                    sp()
                continue

            if op == JUMP_IF_TRUE_KP:
                top = stack[-1]
                if top is not _UND and _truthy(top):
                    ip = arg
                else:
                    sp()
                continue

            if op == STORE_LOCAL:
                s_def_local(names[arg], sp())
                continue

            if op == POP:
                if stack:
                    sp()
                continue

            if op == DUP:
                sa(stack[-1])
                continue

            if op == MAKE_VM_FN:
                body_code, param_info, fn_name = constants[arg]
                fn = _VMFunction(body_code, param_info, fn_name, scope, self)
                sa(fn)
                continue

            if op == BUILD_LIST:
                n = arg
                if n == 0:
                    sa([])
                else:
                    items = []
                    for _ in range(n):
                        items.append(sp())
                    items.reverse()
                    sa(items)
                continue

            if op == BUILD_DICT:
                n = arg
                d = {}
                pairs = []
                for _ in range(n):
                    v = sp(); k = sp()
                    pairs.append((k, v))
                for k, v in reversed(pairs):
                    d[k] = v
                sa(d)
                continue

            if op == INDEX:
                key = sp()
                obj = sp()
                sa(snafu.index_into(obj, key))
                continue

            if op == LOAD_ATTR:
                obj = sp()
                sa(snafu.get_attr(obj, names[arg], self.interp))
                continue

            if op == STORE_ATTR:
                val = sp()
                obj = sp()
                nm = names[arg]
                if isinstance(obj, snafu.SnafuObj):
                    obj.attrs[nm] = val
                elif isinstance(obj, dict):
                    obj[nm] = val
                elif hasattr(obj, nm):
                    setattr(obj, nm, val)
                else:
                    raise TypeErr(f"cannot set attribute on {snafu.type_name(obj)}")
                sa(val)
                continue

            if op == PRINT:
                val = sp()
                print(_snafu_str(val))
                sa(_UND)
                continue

            if op == FOR_ITER:
                obj = sp()
                ik = id(obj)
                if ik not in _iters:
                    try:
                        _iters[ik] = iter(obj)
                    except TypeError:
                        _iters[ik] = iter(list(obj))
                try:
                    sa(next(_iters[ik]))
                except StopIteration:
                    del _iters[ik]
                    ip = arg
                continue

            if op == EVAL_AST:
                node = sp()
                sa(self.interp.eval_node(node, scope))
                continue

            if op == HALT:
                break

        return stack[-1] if stack else _UND


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def compile_ast(tree, name="<module>") -> CodeObject:
    compiler = Compiler()
    compiler.compile(tree)
    return compiler.to_code_object(name)


def run_vm(source: str, filename: str = "<input>", interp: Interpreter = None) -> Any:
    tokens = Lexer(source, filename).tokenize()
    tree = Parser(tokens, filename).parse_program()

    if interp is None:
        interp = Interpreter()
    interp.source = source
    interp.source_file = filename
    interp.global_scope.define_local('src', source)
    interp.global_scope.define_local('ast', tree)

    compiler = Compiler()
    compiler.compile(tree)
    code_obj = compiler.to_code_object(filename)
    vm = VM(interp)
    return vm.execute(code_obj)


def disassemble(code_obj: CodeObject, indent=0):
    prefix = "  " * indent
    print(f"{prefix}=== {code_obj.name} ===")
    for i, (op, arg) in enumerate(code_obj.bytecode):
        nm = _OP_NAMES.get(op, f"OP_{op}")
        extra = ""
        if op == LOAD_CONST:
            val = code_obj.constants[arg]
            if isinstance(val, Node):
                extra = f"  ({type(val).__name__})"
            elif isinstance(val, tuple) and len(val) == 3 and isinstance(val[0], CodeObject):
                extra = f"  (fn-bundle: {val[2]})"
            else:
                extra = f"  ({snafu_repr(val)})"
        elif op in (LOAD_NAME, STORE_NAME, LOAD_ATTR, STORE_ATTR, STORE_LOCAL):
            extra = f"  ({code_obj.names[arg]})"
        elif op in (JUMP, JUMP_IF_FALSE, JUMP_IF_TRUE, JUMP_IF_FALSE_KP,
                     JUMP_IF_TRUE_KP, FOR_ITER):
            extra = f"  -> {arg}"
        elif op == CALL:
            extra = f"  ({arg} args)"
        elif op == BINARY_GENERIC:
            extra = f"  ({code_obj.constants[arg]})"
        elif op == MAKE_VM_FN:
            extra = f"  ({code_obj.constants[arg][2]})"
        print(f"{prefix}  {i:4d}  {nm:<24s} {arg:<6d}{extra}")
    # Recurse into nested code objects
    for c in code_obj.constants:
        if isinstance(c, tuple) and len(c) == 3 and isinstance(c[0], CodeObject):
            print()
            disassemble(c[0], indent + 1)
    print()


# ---------------------------------------------------------------------------
#  Benchmark
# ---------------------------------------------------------------------------

def benchmark():
    src = 'df fib(n) { if n < 2 { n } el { fib(n-1) + fib(n-2) } }; fib(30)'

    print("Benchmarking fib(30) ...")
    print()

    # Tree-walker
    t0 = time.perf_counter()
    r1 = snafu.run(src)
    t1 = time.perf_counter()
    tw_time = t1 - t0

    # VM
    t2 = time.perf_counter()
    r2 = run_vm(src)
    t3 = time.perf_counter()
    vm_time = t3 - t2

    print(f"Tree-walker: {r1} in {tw_time:.3f}s")
    print(f"VM:          {r2} in {vm_time:.3f}s")
    if vm_time > 0:
        print(f"Speedup:     {tw_time / vm_time:.1f}x")
    else:
        print("Speedup:     (VM too fast to measure)")
    print()
    assert r1 == r2, f"Results differ: tree-walker={r1}, VM={r2}"
    print("Results match.")


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------

def run_tests():
    tests = [
        ("while",       "x = 0; wh x < 10 { x = x + 1 }; x",                  10),
        ("until",       "x = 0; un x >= 5 { x = x + 1 }; x",                   5),
        ("index",       "[10, 20, 30][1]",                                       20),
        ("attr",        "o = new(); o.x = 5; o.x",                              5),
        ("ternary",     "5 > 3 ? 'yes' : 'no'",                                 "yes"),
        ("ternary-f",   "1 > 3 ? 'yes' : 'no'",                                 "no"),
        ("break",       "x = 0; wh true { x = x + 1; if x == 5 { br } }; x",   5),
        ("continue",    "s = 0; for i in range(0, 10) { if i % 2 == 0 { cn }; s = s + i }; s", 25),
        ("nested-brk",  "s = 0; for i in range(0, 5) { wh true { s = s + i; br } }; s", 10),
        ("list-build",  "[1, 2, 3]",                                             [1, 2, 3]),
        ("dict-build",  '["a": 1, "b": 2]',                                     {"a": 1, "b": 2}),
        ("for-break",   "x = 0; for i in range(0, 100) { x = i; if i >= 9 { br } }; x", 9),
    ]

    passed = 0
    failed = 0
    for name, src, expected in tests:
        try:
            result = run_vm(src)
            if result == expected:
                print(f"  PASS  {name}")
                passed += 1
            else:
                print(f"  FAIL  {name}: expected {expected!r}, got {result!r}")
                failed += 1
        except Exception as e:
            print(f"  FAIL  {name}: raised {type(e).__name__}: {e}")
            failed += 1

    print()
    print(f"{passed} passed, {failed} failed out of {passed + failed} tests.")
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print("Snafu VM. Usage: python snafu_vm.py [-e expr | file.snf | --bench | --dis | --test]")
        sys.exit(0)

    if args[0] == '--bench':
        benchmark()
    elif args[0] == '--test':
        run_tests()
    elif args[0] == '-e':
        if len(args) < 2:
            print("Usage: snafu_vm.py -e <expr>")
            sys.exit(1)
        result = run_vm(args[1])
        if result is not UND:
            print(snafu_repr(result))
    elif args[0] == '--dis':
        if len(args) < 2:
            print("Usage: snafu_vm.py --dis <expr-or-file>")
            sys.exit(1)
        src = args[1]
        if os.path.isfile(src):
            with open(src, 'r', encoding='utf-8') as f:
                src = f.read()
        tokens = Lexer(src, "<dis>").tokenize()
        tree = Parser(tokens, "<dis>").parse_program()
        co = compile_ast(tree, "<dis>")
        disassemble(co)
    else:
        path = args[0]
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        result = run_vm(src, path)
        if result is not None and result is not UND:
            print(snafu_repr(result))
