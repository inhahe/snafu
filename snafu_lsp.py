#!/usr/bin/env python3
"""Snafu lint/check tool. Reports syntax errors and warnings.

Usage:
    python snafu_lsp.py <file.snf> [--json]
    python snafu_lsp.py <file.snf> --json   # machine-readable output
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snafu

# ---------------------------------------------------------------------------
#  Prelude names -- identifiers defined by the interpreter's install_prelude
# ---------------------------------------------------------------------------

PRELUDE_NAMES = {
    # constants
    "und", "true", "false", "oo",
    # print
    "p", "pe",
    # collections
    "len", "abs", "range", "lst", "st", "en", "zp",
    "m", "fl", "rdc", "map_fn", "srt", "sum", "min", "max",
    "int", "flt", "str", "rev", "flat", "take", "drop",
    "any_of", "all_of", "find_first", "join",
    # math
    "sqrt", "exp", "log", "ln", "sin", "cos", "tan",
    "floor", "ceil", "round", "pi", "e", "tau",
    "rand", "randint", "choice", "shuffle", "sgn",
    "gcd", "lcm", "fact", "log2", "log10", "trunc",
    "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "prd",
    # chr/ord/fmt
    "chr", "ord", "fmt",
    # input
    "inp",
    # python interop
    "py",
    # object
    "new", "id", "type", "cp", "implements", "hs",
    # exceptions
    "Exc", "ArgErr", "TypeErr", "ValErr", "NameErr", "AttrErr",
    "IxErr", "KeyErr", "DivErr", "UndErr", "MatchErr", "IOErr",
    "ParseErr", "DispatchAmbig", "BindErr", "InterpErr", "ContractErr",
    # io
    "read", "write", "open",
    # misc
    "prt", "flip", "cnst", "sleep", "uniq", "dct", "rp",
    "tail", "bp", "atom", "ev",
    # complex
    "cx", "re", "im",
    # state/time-travel
    "ps", "sa", "restore", "save_state",
    # json
    "to_json", "from_json",
    # concurrency
    "actor", "ch", "fk_map",
    # APL-style short names
    "R", "D", "T",
    # meta / AST
    "ast_of", "ast_new",
    # data structures
    "rotate", "window", "now",
}

# Keywords from the parser that serve as implicit names
KEYWORDS = snafu.KEYWORDS if hasattr(snafu, 'KEYWORDS') else set()


# ---------------------------------------------------------------------------
#  AST walker helper
# ---------------------------------------------------------------------------

def walk_ast(node, visitor):
    """Depth-first walk of the AST. Calls visitor(node) on each node.
    visitor may return False to skip children."""
    if node is None:
        return
    if not isinstance(node, snafu.Node):
        return
    if visitor(node) is False:
        return
    # Walk all fields that could contain child nodes
    for attr_name in dir(node):
        if attr_name.startswith('_'):
            continue
        try:
            val = getattr(node, attr_name)
        except AttributeError:
            continue
        if isinstance(val, snafu.Node):
            walk_ast(val, visitor)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, snafu.Node):
                    walk_ast(item, visitor)


# ---------------------------------------------------------------------------
#  Checkers
# ---------------------------------------------------------------------------

def collect_assigned_names(tree):
    """Return a dict: name -> list of (line, col) where the name is assigned."""
    assigned = {}
    def visitor(node):
        if isinstance(node, snafu.Assign):
            target = node.target
            if isinstance(target, snafu.Ident):
                assigned.setdefault(target.name, []).append((node.line, node.col))
        elif isinstance(node, snafu.FnDecl):
            assigned.setdefault(node.name, []).append((node.line, node.col))
            # Don't recurse into the function body for top-level analysis
            return False
        elif isinstance(node, (snafu.For,)):
            if isinstance(node.pattern, snafu.Ident):
                assigned.setdefault(node.pattern.name, []).append((node.line, node.col))
    walk_ast(tree, visitor)
    return assigned


def collect_referenced_names(tree):
    """Return a set of names referenced as identifiers (reads)."""
    refs = set()
    def visitor(node):
        if isinstance(node, snafu.Ident):
            refs.add(node.name)
        elif isinstance(node, snafu.Call):
            if isinstance(node.fn, snafu.Ident):
                refs.add(node.fn.name)
    walk_ast(tree, visitor)
    return refs


def check_unused_vars(tree):
    """Find variables that are assigned but never read."""
    warnings = []

    assigned = collect_assigned_names(tree)
    referenced = collect_referenced_names(tree)

    for name, locations in assigned.items():
        # Skip underscore-prefixed names (intentionally unused)
        if name.startswith('_'):
            continue
        # Skip if referenced anywhere
        if name in referenced:
            continue
        # Skip if it's a function (functions are often defined for external use)
        # Only warn for plain variable assignments
        line, col = locations[0]
        warnings.append(f"line {line}: variable '{name}' is assigned but never used")

    return warnings


def check_undefined_refs(tree):
    """Find identifiers that might not be defined."""
    warnings = []

    # Collect all definitions: top-level assignments, function declarations, for vars, etc.
    defined_names = set()

    def collect_defs(node):
        if isinstance(node, snafu.Assign):
            if isinstance(node.target, snafu.Ident):
                defined_names.add(node.target.name)
        elif isinstance(node, snafu.FnDecl):
            defined_names.add(node.name)
            # Also add param names to known names
            for param in node.params:
                if isinstance(param, snafu.ParamSpec):
                    defined_names.add(param.name)
                elif isinstance(param, str):
                    defined_names.add(param)
        elif isinstance(node, (snafu.CoroutineDecl,)):
            defined_names.add(node.name)
            for param in node.params:
                if isinstance(param, snafu.ParamSpec):
                    defined_names.add(param.name)
                elif isinstance(param, str):
                    defined_names.add(param)
        elif isinstance(node, snafu.SumDecl):
            defined_names.add(node.name)
            for v in node.variants:
                if isinstance(v, snafu.VariantSpec):
                    defined_names.add(v.name)
                elif isinstance(v, str):
                    defined_names.add(v)
        elif isinstance(node, snafu.For):
            if isinstance(node.pattern, snafu.Ident):
                defined_names.add(node.pattern.name)
            elif isinstance(node.pattern, snafu.PatVar):
                defined_names.add(node.pattern.name)
            else:
                _collect_pattern_names(node.pattern, defined_names)
        elif isinstance(node, snafu.Try):
            for exc in node.excepts:
                if isinstance(exc, snafu.Except) and exc.var_name:
                    defined_names.add(exc.var_name)
        elif isinstance(node, snafu.With):
            for binding in node.bindings:
                if isinstance(binding, snafu.WithBinding) and binding.var:
                    defined_names.add(binding.var)
        elif isinstance(node, snafu.Lambda):
            for param in node.params:
                if isinstance(param, snafu.ParamSpec):
                    defined_names.add(param.name)
                elif isinstance(param, str):
                    defined_names.add(param)
        elif isinstance(node, snafu.MatchArm):
            # Collect pattern variables
            _collect_pattern_names(node.pattern, defined_names)
        elif isinstance(node, snafu.ListComp):
            for clause in node.clauses:
                if isinstance(clause, (list, tuple)) and len(clause) >= 1:
                    pat = clause[0]
                    if isinstance(pat, snafu.Ident):
                        defined_names.add(pat.name)

    walk_ast(tree, collect_defs)

    # Now find references to undefined names
    def check_refs(node):
        if isinstance(node, snafu.Ident):
            name = node.name
            if (name not in defined_names and
                name not in PRELUDE_NAMES and
                name not in KEYWORDS and
                not name.startswith('_')):
                warnings.append(
                    f"line {node.line}: '{name}' may not be defined")

    walk_ast(tree, check_refs)

    return warnings


def _collect_pattern_names(pattern, names_set):
    """Collect variable names bound by a pattern."""
    if pattern is None:
        return
    if isinstance(pattern, snafu.PatVar):
        if pattern.name != '_':
            names_set.add(pattern.name)
    elif isinstance(pattern, snafu.PatAs):
        names_set.add(pattern.name)
        _collect_pattern_names(pattern.pattern, names_set)
    elif isinstance(pattern, snafu.PatList):
        for elem in pattern.elems:
            _collect_pattern_names(elem, names_set)
        if pattern.rest:
            names_set.add(pattern.rest)
    elif isinstance(pattern, snafu.PatDict):
        for pair in pattern.pairs:
            if isinstance(pair, snafu.PatPair):
                _collect_pattern_names(pair.pattern, names_set)
        if pattern.rest:
            names_set.add(pattern.rest)
    elif isinstance(pattern, snafu.PatVariant):
        for f in pattern.fields:
            _collect_pattern_names(f, names_set)
    elif isinstance(pattern, snafu.PatOr):
        for alt in pattern.alts:
            _collect_pattern_names(alt, names_set)
    elif isinstance(pattern, snafu.PatGuard):
        _collect_pattern_names(pattern.pattern, names_set)
    elif isinstance(pattern, snafu.Ident):
        # In pattern position, an ident is a binding (unless it matches a constructor)
        if pattern.name != '_':
            names_set.add(pattern.name)


def check_shadow_warnings(tree):
    """Warn when a local shadows an outer variable."""
    warnings = []

    # Collect top-level (outer scope) definitions
    outer_defs = set()

    def collect_outer(node):
        if isinstance(node, snafu.Assign):
            if isinstance(node.target, snafu.Ident):
                outer_defs.add(node.target.name)
            return False  # don't recurse
        elif isinstance(node, snafu.FnDecl):
            outer_defs.add(node.name)
            return False
        elif isinstance(node, (snafu.CoroutineDecl,)):
            outer_defs.add(node.name)
            return False
        elif isinstance(node, snafu.SumDecl):
            outer_defs.add(node.name)
            return False

    # Only collect top-level definitions in the Block
    if isinstance(tree, snafu.Block):
        for stmt in tree.stmts:
            collect_outer(stmt)

    # Now walk into function bodies and check for shadowing
    def check_fn_body(node):
        if isinstance(node, snafu.FnDecl):
            fn_name = node.name
            for param in node.params:
                param_name = None
                if isinstance(param, snafu.ParamSpec):
                    param_name = param.name
                elif isinstance(param, str):
                    param_name = param
                if param_name and param_name in outer_defs:
                    warnings.append(
                        f"line {node.line}: parameter '{param_name}' in "
                        f"'{fn_name}' shadows outer variable")
            # Also check assignments inside the body
            _check_inner_shadows(node.body, outer_defs, fn_name, warnings)
            return False  # don't recurse further (handled by _check_inner_shadows)

    walk_ast(tree, check_fn_body)

    return warnings


def _check_inner_shadows(body, outer_defs, fn_name, warnings):
    """Check assignments in a function body that shadow outer definitions."""
    def visitor(node):
        if isinstance(node, snafu.Assign):
            if isinstance(node.target, snafu.Ident):
                name = node.target.name
                if name in outer_defs and name not in PRELUDE_NAMES:
                    warnings.append(
                        f"line {node.line}: assignment to '{name}' in "
                        f"'{fn_name}' shadows outer variable")
        elif isinstance(node, snafu.FnDecl):
            return False  # don't recurse into nested functions
    walk_ast(body, visitor)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def check_file(path):
    """Parse a file and report diagnostics."""
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    errors = []
    warnings = []

    # Phase 1: Lexing
    try:
        lexer = snafu.Lexer(src, path)
        tokens = lexer.tokenize()
    except snafu.ParseErr as e:
        errors.append(str(e))
        return errors, warnings
    except Exception as e:
        errors.append(f"Lex error: {e}")
        return errors, warnings

    # Phase 2: Parsing
    try:
        parser = snafu.Parser(tokens, path)
        tree = parser.parse_program()
    except snafu.ParseErr as e:
        errors.append(str(e))
        return errors, warnings
    except Exception as e:
        errors.append(f"Parse error: {e}")
        return errors, warnings

    # Phase 3: Static checks
    try:
        warnings.extend(check_unused_vars(tree))
    except Exception:
        pass  # Don't crash the linter on checker bugs

    try:
        warnings.extend(check_undefined_refs(tree))
    except Exception:
        pass

    try:
        warnings.extend(check_shadow_warnings(tree))
    except Exception:
        pass

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python snafu_lsp.py <file.snf> [--json]")
        sys.exit(1)

    path = sys.argv[1]
    json_mode = '--json' in sys.argv

    if not os.path.isfile(path):
        if json_mode:
            print(json.dumps({"errors": [f"file not found: {path}"], "warnings": []}))
        else:
            print(f"ERROR: file not found: {path}")
        sys.exit(1)

    errors, warnings = check_file(path)

    if json_mode:
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        for e in errors:
            print(f"ERROR: {e}")
        for w in warnings:
            print(f"WARN:  {w}")
        if not errors and not warnings:
            print(f"{path}: OK")
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
