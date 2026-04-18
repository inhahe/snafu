#include "snafu.h"
#include "snafu_python.h"

#ifdef SNAFU_HAS_PYTHON
#include <Python.h>
#endif

/* ------------------------------------------------------------------ */
/*  Thread-local return value — avoids exception overhead              */
/* ------------------------------------------------------------------ */

static thread_local bool tl_return_flag = false;
static thread_local Value tl_return_value;

/* ------------------------------------------------------------------ */
/*  Forward decl                                                       */
/* ------------------------------------------------------------------ */

static Value eval_call(ASTNode *fn_node, std::vector<std::unique_ptr<ASTNode>> &args,
                       std::shared_ptr<Scope> scope);
static Value call_value(Value &fn, Value *args, int nargs, std::shared_ptr<Scope> scope);
static bool ast_has_fndecl(ASTNode *node);
static bool match_pattern(ASTNode *pattern, const Value &val, std::shared_ptr<Scope> scope);
static Value eval_dot_call(Value &target, const std::string &method,
                           Value *args, int nargs, std::shared_ptr<Scope> scope);

/* ------------------------------------------------------------------ */
/*  Arithmetic helpers                                                 */
/* ------------------------------------------------------------------ */

static Value binop_add(const Value &a, const Value &b) {
    if (a.is_int() && b.is_int())
        return Value::Int(a.ival + b.ival);
    if (a.is_float() && b.is_float())
        return Value::Float(a.fval + b.fval);
    if (a.is_int() && b.is_float())
        return Value::Float(static_cast<double>(a.ival) + b.fval);
    if (a.is_float() && b.is_int())
        return Value::Float(a.fval + static_cast<double>(b.ival));
    if (a.is_str() || b.is_str()) {
        return Value::Str(a.to_string() + b.to_string());
    }
    if (a.is_list() && b.is_list()) {
        Value r = Value::List(a.list_len() + b.list_len());
        for (auto &v : *a.list) r.list_push(v);
        for (auto &v : *b.list) r.list_push(v);
        return r;
    }
    snafu_die("cannot add these types");
    return Value::Und();
}

static Value binop_sub(const Value &a, const Value &b) {
    if (a.is_int() && b.is_int())
        return Value::Int(a.ival - b.ival);
    if (a.is_float() && b.is_float())
        return Value::Float(a.fval - b.fval);
    if (a.is_int() && b.is_float())
        return Value::Float(static_cast<double>(a.ival) - b.fval);
    if (a.is_float() && b.is_int())
        return Value::Float(a.fval - static_cast<double>(b.ival));
    snafu_die("cannot subtract these types");
    return Value::Und();
}

static Value binop_mul(const Value &a, const Value &b) {
    if (a.is_int() && b.is_int())
        return Value::Int(a.ival * b.ival);
    if (a.is_float() && b.is_float())
        return Value::Float(a.fval * b.fval);
    if (a.is_int() && b.is_float())
        return Value::Float(static_cast<double>(a.ival) * b.fval);
    if (a.is_float() && b.is_int())
        return Value::Float(a.fval * static_cast<double>(b.ival));
    if (a.is_str() && b.is_int()) {
        int n = static_cast<int>(b.ival);
        if (n <= 0) return Value::Str("");
        std::string out;
        out.reserve(a.sval->size() * n);
        for (int i = 0; i < n; i++) out += *a.sval;
        return Value::Str(out);
    }
    snafu_die("cannot multiply these types");
    return Value::Und();
}

static Value binop_div(const Value &a, const Value &b) {
    if (b.is_int() && b.ival == 0)
        snafu_die("division by zero");
    if (b.is_float() && b.fval == 0.0)
        snafu_die("division by zero");
    if (a.is_int() && b.is_int()) {
        if (a.ival % b.ival == 0)
            return Value::Int(a.ival / b.ival);
        return Value::Float(static_cast<double>(a.ival) / static_cast<double>(b.ival));
    }
    double da = a.to_num();
    double db = b.to_num();
    return Value::Float(da / db);
}

static Value binop_mod(const Value &a, const Value &b) {
    if (a.is_int() && b.is_int()) {
        if (b.ival == 0) snafu_die("modulo by zero");
        return Value::Int(a.ival % b.ival);
    }
    double da = a.to_num();
    double db = b.to_num();
    if (db == 0.0) snafu_die("modulo by zero");
    return Value::Float(fmod(da, db));
}

static Value binop_pow(const Value &a, const Value &b) {
    if (a.is_int() && b.is_int() && b.ival >= 0) {
        long long base = a.ival, exp = b.ival, result = 1;
        while (exp > 0) {
            if (exp & 1) result *= base;
            base *= base;
            exp >>= 1;
        }
        return Value::Int(result);
    }
    double da = a.to_num();
    double db = b.to_num();
    return Value::Float(pow(da, db));
}

static bool val_eq(const Value &a, const Value &b) {
    if (a.is_und() && b.is_und()) return true;
    if (a.is_und() || b.is_und()) return false;
    if (a.is_bool() && b.is_bool()) return a.bval == b.bval;
    if (a.is_str() && b.is_str()) return *a.sval == *b.sval;
    if ((a.is_int() || a.is_float()) && (b.is_int() || b.is_float()))
        return a.to_num() == b.to_num();
    if (a.is_list() && b.is_list()) {
        if (a.list->size() != b.list->size()) return false;
        for (size_t i = 0; i < a.list->size(); i++)
            if (!val_eq((*a.list)[i], (*b.list)[i]))
                return false;
        return true;
    }
    if (a.is_variant() && b.is_variant()) {
        if (a.variant->tag != b.variant->tag) return false;
        return val_eq(*a.variant->payload, *b.variant->payload);
    }
    return false;
}

/* ------------------------------------------------------------------ */
/*  apply_binop — fast dispatch by first character of operator         */
/* ------------------------------------------------------------------ */

static Value apply_binop(const std::string &op, const Value &a, const Value &b) {
    if (op.empty()) {
        snafu_die("empty operator");
        return Value::Und();
    }
    switch (op[0]) {
    case '+': return binop_add(a, b);
    case '-': return binop_sub(a, b);
    case '/': return binop_div(a, b);
    case '%': return binop_mod(a, b);
    case '*':
        if (op == "**") return binop_pow(a, b);
        return binop_mul(a, b);
    case '=':  /* == */
        return Value::Bool(val_eq(a, b));
    case '<':
        if (op == "<>") return Value::Bool(!val_eq(a, b));
        if (op == "<=") return Value::Bool(a.to_num() <= b.to_num());
        return Value::Bool(a.to_num() < b.to_num());
    case '>':
        if (op == ">=") return Value::Bool(a.to_num() >= b.to_num());
        return Value::Bool(a.to_num() > b.to_num());
    case '&':
        if (op == "&&") return Value::Bool(a.truthy() && b.truthy());
        /* bitwise & */
        if (op == "&") {
            if (a.is_int() && b.is_int())
                return Value::Int(a.ival & b.ival);
            snafu_die("bitwise & requires integers");
        }
        break;
    case '|':
        if (op == "||") return Value::Bool(a.truthy() || b.truthy());
        /* bitwise | */
        if (op == "|") {
            if (a.is_int() && b.is_int())
                return Value::Int(a.ival | b.ival);
            snafu_die("bitwise | requires integers");
        }
        break;
    case '.':  /* .. range */
        if (op == "..") {
            if (!a.is_int() || !b.is_int())
                snafu_die("range (..) requires integers");
            long long lo = a.ival, hi = b.ival;
            int n = (hi > lo) ? static_cast<int>(hi - lo) : 0;
            Value r = Value::List(n);
            for (long long i = lo; i < hi; i++)
                r.list_push(Value::Int(i));
            return r;
        }
        break;
    }
    snafu_die("unknown operator '%s'", op.c_str());
    return Value::Und();
}

/* ------------------------------------------------------------------ */
/*  match_pattern — try to match a pattern against a value             */
/* ------------------------------------------------------------------ */

static bool match_pattern(ASTNode *pattern, const Value &val, std::shared_ptr<Scope> scope) {
    if (!pattern) return false;

    switch (pattern->type) {
    case AST_IDENT:
        if (pattern->ident_name == "_")
            return true;  // wildcard
        // Variable binding
        scope->set_local(pattern->ident_name, val);
        return true;

    case AST_NUM:
        return val.is_int() && val.ival == pattern->num_val;

    case AST_FLOAT:
        return val.is_float() && val.fval == pattern->float_val;

    case AST_STR:
        return val.is_str() && *val.sval == pattern->str_val;

    case AST_BOOL:
        return val.is_bool() && val.bval == pattern->bool_val;

    case AST_UND:
        return val.is_und();

    case AST_UNARYOP:
        if (pattern->unary_op == "-" && pattern->operand) {
            if (pattern->operand->type == AST_NUM)
                return val.is_int() && val.ival == -pattern->operand->num_val;
            if (pattern->operand->type == AST_FLOAT)
                return val.is_float() && val.fval == -pattern->operand->float_val;
        }
        return false;

    case AST_LIST:
        if (!val.is_list()) return false;
        if (val.list->size() != pattern->items.size()) return false;
        for (size_t i = 0; i < pattern->items.size(); i++) {
            if (!match_pattern(pattern->items[i].get(), (*val.list)[i], scope))
                return false;
        }
        return true;

    case AST_CALL:
        // Variant pattern: Tag(inner)
        if (pattern->call_fn && pattern->call_fn->type == AST_IDENT) {
            if (!val.is_variant()) return false;
            if (val.variant->tag != pattern->call_fn->ident_name) return false;
            if (!pattern->call_args.empty()) {
                return match_pattern(pattern->call_args[0].get(),
                                   *val.variant->payload, scope);
            }
            return true;
        }
        return false;

    default:
        return false;
    }
}

/* ------------------------------------------------------------------ */
/*  eval — main evaluator                                              */
/* ------------------------------------------------------------------ */

Value eval(ASTNode *node, std::shared_ptr<Scope> scope) {
top:
    if (!node) return Value::Und();

    switch (node->type) {

    case AST_NUM:
        return Value::Int(node->num_val);

    case AST_FLOAT:
        return Value::Float(node->float_val);

    case AST_STR:
        return Value::Str(node->str_val);

    case AST_BOOL:
        return Value::Bool(node->bool_val);

    case AST_UND:
        return Value::Und();

    case AST_IDENT:
        return scope->get(node->ident_name);

    case AST_BINOP: {
        const std::string &op = node->binop_op;
        /* Fast path: common int+int operations */
        if (op == "+") {
            Value left  = eval(node->lhs.get(), scope);
            Value right = eval(node->rhs.get(), scope);
            if (left.is_int() && right.is_int())
                return Value::Int(left.ival + right.ival);
            return binop_add(left, right);
        }
        if (op == "-") {
            Value left  = eval(node->lhs.get(), scope);
            Value right = eval(node->rhs.get(), scope);
            if (left.is_int() && right.is_int())
                return Value::Int(left.ival - right.ival);
            return binop_sub(left, right);
        }
        if (op == "<") {
            Value left  = eval(node->lhs.get(), scope);
            Value right = eval(node->rhs.get(), scope);
            if (left.is_int() && right.is_int())
                return Value::Bool(left.ival < right.ival);
            return Value::Bool(left.to_num() < right.to_num());
        }
        /* short-circuit && */
        if (op == "&&") {
            Value left = eval(node->lhs.get(), scope);
            if (!left.truthy()) return left;
            return eval(node->rhs.get(), scope);
        }
        /* short-circuit || */
        if (op == "||") {
            Value left = eval(node->lhs.get(), scope);
            if (left.truthy()) return left;
            return eval(node->rhs.get(), scope);
        }
        /* null coalesce ?? */
        if (op == "??") {
            Value left = eval(node->lhs.get(), scope);
            if (!left.is_und()) return left;
            return eval(node->rhs.get(), scope);
        }
        Value left  = eval(node->lhs.get(), scope);
        Value right = eval(node->rhs.get(), scope);
        return apply_binop(op, left, right);
    }

    case AST_UNARYOP: {
        Value v = eval(node->operand.get(), scope);
        if (node->unary_op == "-") {
            if (v.is_int())   return Value::Int(-v.ival);
            if (v.is_float()) return Value::Float(-v.fval);
            snafu_die("cannot negate non-number");
        }
        if (node->unary_op == "+") return v;
        if (node->unary_op == "!") return Value::Bool(!v.truthy());
        snafu_die("unknown unary op '%s'", node->unary_op.c_str());
        return Value::Und();
    }

    case AST_CALL:
        return eval_call(node->call_fn.get(), node->call_args, scope);

    case AST_ASSIGN: {
        Value v = eval(node->assign_value.get(), scope);
        scope->set(node->assign_name, v);
        return v;
    }

    case AST_IF: {
        Value cond = eval(node->if_cond.get(), scope);
        if (tl_return_flag) return tl_return_value;
        if (cond.truthy()) {
            node = node->if_then.get();
            goto top;
        }
        for (size_t i = 0; i < node->elif_conds.size(); i++) {
            Value ec = eval(node->elif_conds[i].get(), scope);
            if (tl_return_flag) return tl_return_value;
            if (ec.truthy()) {
                node = node->elif_bodies[i].get();
                goto top;
            }
        }
        if (node->if_else) {
            node = node->if_else.get();
            goto top;
        }
        return Value::Und();
    }

    case AST_FOR: {
        Value iter_val = eval(node->for_iter.get(), scope);
        if (!iter_val.is_list())
            snafu_die("for-in requires a list");
        Value result = Value::Und();
        auto child = make_scope(scope);
        for (size_t i = 0; i < iter_val.list->size(); i++) {
            child->set_local(node->for_var, (*iter_val.list)[i]);
            try {
                result = eval(node->for_body.get(), child);
            } catch (BreakSignal &bs) {
                if (bs.level <= 1) break;
                bs.level--;
                throw;
            } catch (ContinueSignal &cs) {
                if (cs.level <= 1) continue;
                cs.level--;
                throw;
            }
        }
        return result;
    }

    case AST_WHILE: {
        Value result = Value::Und();
        auto child = make_scope(scope);
        while (true) {
            Value cond = eval(node->while_cond.get(), child);
            bool cv = cond.truthy();
            if (node->is_until) cv = !cv;
            if (!cv) break;
            try {
                result = eval(node->while_body.get(), child);
            } catch (BreakSignal &bs) {
                if (bs.level <= 1) break;
                bs.level--;
                throw;
            } catch (ContinueSignal &cs) {
                if (cs.level <= 1) continue;
                cs.level--;
                throw;
            }
        }
        return result;
    }

    case AST_BLOCK: {
        if (node->block_stmts.empty()) return Value::Und();
        /* Single-statement fast TCO path */
        if (node->block_stmts.size() == 1) {
            ASTType st = node->block_stmts[0]->type;
            if (st != AST_LABEL && st != AST_COMEFROM && st != AST_DEFER) {
                node = node->block_stmts[0].get();
                goto top;
            }
        }

        /* Two-statement blocks (very common in function bodies): avoid scanning for defer */
        {
            bool need_slow_path = false;
            for (auto &s : node->block_stmts) {
                ASTType st = s->type;
                if (st == AST_DEFER || st == AST_LABEL || st == AST_COMEFROM) {
                    need_slow_path = true;
                    break;
                }
            }
            if (!need_slow_path) {
                /* Fast path: skip scope creation — use parent scope directly.
                   Check return flag after each statement for early exit. */
                Value result = Value::Und();
                for (size_t i = 0; i < node->block_stmts.size(); i++) {
                    result = eval(node->block_stmts[i].get(), scope);
                    if (tl_return_flag) return tl_return_value;
                }
                return result;
            }
        }

        /* Slow path: block has defer/label/comefrom */
        Value result = Value::Und();
        auto child = make_scope(scope);

        // Pre-scan for labels and comefrom hooks
        std::unordered_map<std::string, size_t> label_map;
        std::unordered_map<std::string, size_t> comefrom_map;
        for (size_t si = 0; si < node->block_stmts.size(); si++) {
            if (node->block_stmts[si]->type == AST_LABEL)
                label_map[node->block_stmts[si]->label_name] = si;
            if (node->block_stmts[si]->type == AST_COMEFROM)
                comefrom_map[node->block_stmts[si]->label_name] = si;
        }

        size_t i = 0;
        try {
            while (i < node->block_stmts.size()) {
                try {
                    /* Defer: push to stack, don't evaluate now */
                    if (node->block_stmts[i]->type == AST_DEFER) {
                        child->defer_stack.push_back(
                            node->block_stmts[i]->defer_expr.get());
                        i++;
                        continue;
                    }
                    result = eval(node->block_stmts[i].get(), child);
                    if (tl_return_flag) {
                        // Run defers before propagating return
                        for (int di = static_cast<int>(child->defer_stack.size()) - 1; di >= 0; di--)
                            try { eval(child->defer_stack[di], child); } catch (...) {}
                        return tl_return_value;
                    }
                    // After evaluating a label, check if any comefrom targets it
                    if (node->block_stmts[i]->type == AST_LABEL) {
                        auto cf_it = comefrom_map.find(node->block_stmts[i]->label_name);
                        if (cf_it != comefrom_map.end()) {
                            i = cf_it->second + 1;
                            continue;
                        }
                    }
                } catch (GotoSignal &gs) {
                    auto it = label_map.find(gs.label);
                    if (it != label_map.end()) {
                        i = it->second;
                        continue;
                    }
                    throw;
                }
                i++;
            }
        } catch (...) {
            // Run defers in LIFO order even on exception
            for (int di = static_cast<int>(child->defer_stack.size()) - 1; di >= 0; di--) {
                try { eval(child->defer_stack[di], child); } catch (...) {}
            }
            throw;
        }
        // Run defers in LIFO order on normal exit
        for (int di = static_cast<int>(child->defer_stack.size()) - 1; di >= 0; di--) {
            try { eval(child->defer_stack[di], child); } catch (...) {}
        }
        return result;
    }

    case AST_FNDECL: {
        auto fd = std::make_shared<FnData>();
        fd->params = node->fndecl_params;
        fd->body = node->fndecl_body.get();
        fd->closure = scope;
        fd->name = node->fndecl_name;
        fd->may_capture = ast_has_fndecl(node->fndecl_body.get());
        fd->is_coroutine = node->is_coroutine;
        fd->is_macro = node->is_macro;
        Value fn = Value::Fn(fd);
        // Apply decorators (innermost first, then outward)
        for (int di = static_cast<int>(node->decorators.size()) - 1; di >= 0; di--) {
            Value dec = eval(node->decorators[di].get(), scope);
            Value dec_args[1] = {fn};
            fn = call_value(dec, dec_args, 1, scope);
        }
        if (node->fndecl_name == "<lambda>")
            return fn;
        scope->set(node->fndecl_name, fn);
        return Value::Und();
    }

    case AST_RETURN: {
        Value v = Value::Und();
        if (node->ret_value)
            v = eval(node->ret_value.get(), scope);
        tl_return_flag = true;
        tl_return_value = v;
        return v;
    }

    case AST_BREAK:
        throw BreakSignal(node->break_level);

    case AST_CONTINUE:
        throw ContinueSignal(node->break_level);

    case AST_EXPRSTMT:
        node = node->expr.get();
        goto top;

    case AST_LIST: {
        Value r = Value::List(static_cast<int>(node->items.size()));
        for (auto &item : node->items)
            r.list_push(eval(item.get(), scope));
        return r;
    }

    case AST_DICT_LIT: {
        Value r = Value::Dict();
        for (size_t i = 0; i < node->dict_keys.size(); i++) {
            Value key = eval(node->dict_keys[i].get(), scope);
            Value val = eval(node->items[i].get(), scope);
            if (!key.is_str())
                snafu_die("dict key must be a string");
            (*r.dict)[*key.sval] = val;
        }
        return r;
    }

    case AST_INDEX: {
        Value target = eval(node->index_target.get(), scope);
        Value key    = eval(node->index_key.get(), scope);
        if (target.is_list()) {
            if (!key.is_int())
                snafu_die("list index must be integer");
            long long idx = key.ival;
            int len = target.list_len();
            if (idx < 0) idx += len;
            if (idx < 0 || idx >= len)
                snafu_die("index %lld out of range (len %d)", key.ival, len);
            return (*target.list)[static_cast<size_t>(idx)];
        }
        if (target.is_str()) {
            if (!key.is_int())
                snafu_die("string index must be integer");
            long long idx = key.ival;
            int slen = static_cast<int>(target.sval->size());
            if (idx < 0) idx += slen;
            if (idx < 0 || idx >= slen)
                snafu_die("string index out of range");
            return Value::Str(std::string(1, (*target.sval)[static_cast<size_t>(idx)]));
        }
        if (target.is_dict()) {
            if (!key.is_str())
                snafu_die("dict key must be string");
            auto it = target.dict->find(*key.sval);
            if (it != target.dict->end())
                return it->second;
            return Value::Und();
        }
        snafu_die("cannot index into this type");
        return Value::Und();
    }

    case AST_DOT_ACCESS: {
        Value target = eval(node->dot_target.get(), scope);
        if (node->dot_safe && target.is_und()) return Value::Und();
        const std::string &field = node->dot_field;
        if (target.is_dict()) {
            auto it = target.dict->find(field);
            if (it != target.dict->end())
                return it->second;
            return Value::Und();
        }
        if (target.is_variant()) {
            if (field == "tag")
                return Value::Str(target.variant->tag);
            if (field == "val" || field == "value")
                return *target.variant->payload;
        }
        if (target.is_list()) {
            if (field == "len" || field == "length")
                return Value::Int(target.list_len());
        }
        if (target.is_str()) {
            if (field == "len" || field == "length")
                return Value::Int(static_cast<long long>(target.sval->size()));
        }
        if (target.is_pyobj()) {
#ifdef SNAFU_HAS_PYTHON
            PyObject *attr = PyObject_GetAttrString((PyObject *)target.pyobj, field.c_str());
            if (attr) {
                Value r = python_to_snafu(attr);
                Py_DECREF(attr);
                return r;
            }
            PyErr_Clear();
#endif
            return Value::Und();
        }
        snafu_die("field '%s' not found", field.c_str());
        return Value::Und();
    }

    case AST_DOT_CALL: {
        Value target = eval(node->dot_target.get(), scope);
        if (node->dot_safe && target.is_und()) return Value::Und();
        const std::string &method = node->dot_field;
        int nargs = static_cast<int>(node->dot_call_args.size());
        Value args_stack[8];
        Value *args = (nargs <= 8) ? args_stack : new Value[nargs];
        for (int i = 0; i < nargs; i++)
            args[i] = eval(node->dot_call_args[i].get(), scope);
        Value result = eval_dot_call(target, method, args, nargs, scope);
        if (args != args_stack) delete[] args;
        return result;
    }

    case AST_MATCH: {
        Value val = eval(node->match_expr.get(), scope);
        for (auto &arm : node->match_arms) {
            auto arm_scope = make_scope(scope);
            if (match_pattern(arm.pattern.get(), val, arm_scope)) {
                return eval(arm.body.get(), arm_scope);
            }
        }
        snafu_die("no matching pattern in match expression");
        return Value::Und();
    }

    case AST_SUMDECL: {
        // Create constructor functions for each variant
        for (auto &ctor : node->sumdecl_constructors) {
            std::string tag = ctor;
            Value constructor = Value::Builtin(
                [tag](Value *args, int nargs, Scope *) -> Value {
                    if (nargs == 0)
                        return Value::Variant(tag, Value::Und());
                    if (nargs == 1)
                        return Value::Variant(tag, args[0]);
                    // Multiple args: wrap in list
                    Value lst = Value::List(nargs);
                    for (int i = 0; i < nargs; i++)
                        lst.list_push(args[i]);
                    return Value::Variant(tag, lst);
                }
            );
            scope->set(ctor, constructor);
        }
        return Value::Und();
    }

    case AST_PIPE: {
        // a |> f  =>  f(a)
        Value lhs = eval(node->pipe_lhs.get(), scope);
        Value rhs = eval(node->pipe_rhs.get(), scope);
        // Call rhs with lhs as first argument
        Value args[1] = {lhs};
        return call_value(rhs, args, 1, scope);
    }

    case AST_APL_REDUCE: {
        // op/ list  =>  fold with op
        Value operand = eval(node->apl_operand.get(), scope);
        if (!operand.is_list() || operand.list->empty())
            snafu_die("reduce requires a non-empty list");
        const std::string &op = node->apl_op;
        Value acc = (*operand.list)[0];
        for (size_t i = 1; i < operand.list->size(); i++) {
            acc = apply_binop(op, acc, (*operand.list)[i]);
        }
        return acc;
    }

    case AST_APL_SCAN: {
        // op\ list  =>  scan with op (prefix sums)
        Value operand = eval(node->apl_operand.get(), scope);
        if (!operand.is_list() || operand.list->empty())
            snafu_die("scan requires a non-empty list");
        const std::string &op = node->apl_op;
        Value result = Value::List(static_cast<int>(operand.list->size()));
        Value acc = (*operand.list)[0];
        result.list_push(acc);
        for (size_t i = 1; i < operand.list->size(); i++) {
            acc = apply_binop(op, acc, (*operand.list)[i]);
            result.list_push(acc);
        }
        return result;
    }

    case AST_APL_EACH: {
        // op. list  =>  element-wise unary op (for now just +. and -. negate each)
        Value operand = eval(node->apl_operand.get(), scope);
        if (!operand.is_list())
            snafu_die("element-wise operator requires a list");
        // If the operand is a list of two lists, do pairwise
        // Otherwise, apply the op to each element
        const std::string &op = node->apl_op;
        Value result = Value::List(static_cast<int>(operand.list->size()));
        // If it's two lists [a, b] and op, do pairwise
        if (operand.list->size() == 2 &&
            (*operand.list)[0].is_list() && (*operand.list)[1].is_list()) {
            auto &l1 = *(*operand.list)[0].list;
            auto &l2 = *(*operand.list)[1].list;
            size_t len = std::min(l1.size(), l2.size());
            result = Value::List(static_cast<int>(len));
            for (size_t i = 0; i < len; i++) {
                result.list_push(apply_binop(op, l1[i], l2[i]));
            }
        } else {
            // Unary application: identity for +, negate for -
            for (auto &v : *operand.list) {
                if (op == "-") {
                    if (v.is_int()) result.list_push(Value::Int(-v.ival));
                    else if (v.is_float()) result.list_push(Value::Float(-v.fval));
                    else snafu_die("cannot negate non-number in element-wise op");
                } else {
                    result.list_push(v);
                }
            }
        }
        return result;
    }

    case AST_INTERP_STR: {
        std::string out;
        for (auto &part : node->interp_parts) {
            Value v = eval(part.get(), scope);
            out += v.to_string();
        }
        return Value::Str(out);
    }

    case AST_REGEX: {
        // Return a regex object as a builtin that does matching
        std::string pattern = node->regex_pattern;
        std::string flags_str = node->regex_flags;
        auto regex_flags = std::regex_constants::ECMAScript;
        for (char f : flags_str) {
            if (f == 'i') regex_flags |= std::regex_constants::icase;
        }
        bool global = (flags_str.find('g') != std::string::npos);
        std::shared_ptr<std::regex> re;
        try {
            re = std::make_shared<std::regex>(pattern, regex_flags);
        } catch (const std::regex_error &e) {
            snafu_die("invalid regex: %s", e.what());
        }
        return Value::Builtin(
            [re, global](Value *args, int nargs, Scope *) -> Value {
                if (nargs != 1 || !args[0].is_str())
                    snafu_die("regex expects a string argument");
                const std::string &s = *args[0].sval;
                if (global) {
                    Value matches = Value::List(0);
                    auto begin = std::sregex_iterator(s.begin(), s.end(), *re);
                    auto end = std::sregex_iterator();
                    for (auto it = begin; it != end; ++it) {
                        matches.list_push(Value::Str((*it)[0].str()));
                    }
                    return matches;
                } else {
                    std::smatch m;
                    if (std::regex_search(s, m, *re)) {
                        if (m.size() > 1) {
                            Value groups = Value::List(static_cast<int>(m.size()) - 1);
                            for (size_t i = 1; i < m.size(); i++)
                                groups.list_push(Value::Str(m[i].str()));
                            return groups;
                        }
                        return Value::Str(m[0].str());
                    }
                    return Value::Und();
                }
            }
        );
    }

    case AST_TRY: {
        try {
            return eval(node->try_body.get(), scope);
        } catch (SnafuError &e) {
            auto handler_scope = make_scope(scope);
            if (!node->try_var.empty()) {
                handler_scope->set_local(node->try_var, Value::Str(e.msg));
            }
            return eval(node->try_handler.get(), handler_scope);
        }
    }

    case AST_YIELD: {
        Value v = Value::Und();
        if (node->yield_value)
            v = eval(node->yield_value.get(), scope);
        // Look up the generator data stored in scope as __gen__
        if (!scope->has("__gen__"))
            snafu_die("y (yield) used outside of coroutine");
        Value gen_val = scope->get("__gen__");
        if (!gen_val.is_generator())
            snafu_die("y (yield) internal error: __gen__ is not a generator");
        auto &gd = gen_val.generator;
        {
            std::lock_guard<std::mutex> lock(gd->mtx);
            gd->yielded_value = v;
            gd->value_ready = true;
        }
        gd->cv_consumer.notify_all();
        // Now wait for next next() call
        {
            std::unique_lock<std::mutex> lock(gd->mtx);
            gd->cv_producer.wait(lock, [&gd]() { return gd->next_requested || gd->done; });
            gd->next_requested = false;
        }
        return Value::Und();
    }

    case AST_PERFORM: {
        Value v = eval(node->yield_value.get(), scope);
        throw EffectSignal{v};
    }

    case AST_EFFECT_DECL: {
        // ef Name(fields) -- create a constructor for the effect
        std::string name = node->effect_name;
        std::vector<std::string> fields = node->effect_fields;
        Value constructor = Value::Builtin(
            [name, fields](Value *args, int nargs, Scope *) -> Value {
                Value d = Value::Dict();
                (*d.dict)["__effect__"] = Value::Str(name);
                for (int i = 0; i < nargs && i < static_cast<int>(fields.size()); i++) {
                    (*d.dict)[fields[i]] = args[i];
                }
                return d;
            }
        );
        scope->set(node->effect_name, constructor);
        return Value::Und();
    }

    case AST_HANDLE: {
        try {
            return eval(node->handle_body.get(), scope);
        } catch (EffectSignal &es) {
            for (auto &arm : node->handle_arms) {
                auto arm_scope = make_scope(scope);
                if (match_pattern(arm.pattern.get(), es.value, arm_scope)) {
                    return eval(arm.body.get(), arm_scope);
                }
            }
            // No match: re-throw
            throw;
        }
    }

    case AST_GREEN_THREAD: {
        // gt { body } -- spawn a thread, return a Future
        auto fd = std::make_shared<FutureData>();
        ASTNode *body = node->gt_body.get();
        auto captured_scope = scope;
        fd->thread = std::make_shared<std::thread>([fd, body, captured_scope]() {
            try {
                Value result = eval(body, captured_scope);
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = result;
                fd->done = true;
                fd->cv.notify_all();
            } catch (ReturnSignal &rs) {
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = rs.value;
                fd->done = true;
                fd->cv.notify_all();
            } catch (SnafuError &) {
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = Value::Und();
                fd->done = true;
                fd->cv.notify_all();
            }
        });
        fd->thread->detach();
        return Value::Future(fd);
    }

    case AST_AWAIT: {
        Value v = eval(node->yield_value.get(), scope);
        if (!v.is_future())
            snafu_die("aw requires a future value");
        auto &fd = v.future;
        std::unique_lock<std::mutex> lock(fd->mtx);
        fd->cv.wait(lock, [&fd]() { return fd->done; });
        return fd->result;
    }

    case AST_TERNARY: {
        Value cond = eval(node->tern_cond.get(), scope);
        if (cond.truthy()) {
            node = node->tern_true.get();
            goto top;
        } else {
            node = node->tern_false.get();
            goto top;
        }
    }

    case AST_DESTRUCT_ASSIGN: {
        Value rhs = eval(node->destruct_value.get(), scope);
        if (!rhs.is_list())
            snafu_die("destructuring requires a list on the right side");
        if (static_cast<int>(node->destruct_names.size()) != rhs.list_len())
            snafu_die("destructuring: length mismatch (%d names, %d values)",
                      static_cast<int>(node->destruct_names.size()), rhs.list_len());
        for (size_t i = 0; i < node->destruct_names.size(); i++) {
            if (node->destruct_names[i] != "_")
                scope->set(node->destruct_names[i], (*rhs.list)[i]);
        }
        return rhs;
    }

    case AST_LABEL: {
        // Labels are handled by the block evaluator; standalone label is a no-op
        return Value::Und();
    }

    case AST_GOTO: {
        throw GotoSignal(node->label_name);
    }

    case AST_COMEFROM: {
        // Comefrom hooks are registered by block evaluator; standalone is no-op
        return Value::Und();
    }

    case AST_WITH: {
        Value ctx = eval(node->with_expr.get(), scope);
        // Call .en() on the context manager
        Value en_result = Value::Und();
        if (ctx.is_dict()) {
            auto it = ctx.dict->find("en");
            if (it != ctx.dict->end()) {
                Value en_fn = it->second;
                en_result = call_value(en_fn, nullptr, 0, scope);
            }
        }
        auto with_scope = make_scope(scope);
        if (!node->with_var.empty()) {
            with_scope->set_local(node->with_var, en_result);
        }
        Value result = Value::Und();
        try {
            result = eval(node->with_body.get(), with_scope);
        } catch (...) {
            // Call .ex() on exit
            if (ctx.is_dict()) {
                auto it = ctx.dict->find("ex");
                if (it != ctx.dict->end()) {
                    Value ex_fn = it->second;
                    call_value(ex_fn, nullptr, 0, scope);
                }
            }
            throw;
        }
        // Call .ex() on normal exit
        if (ctx.is_dict()) {
            auto it = ctx.dict->find("ex");
            if (it != ctx.dict->end()) {
                Value ex_fn = it->second;
                call_value(ex_fn, nullptr, 0, scope);
            }
        }
        return result;
    }

    case AST_WHERE: {
        // expr whr { bindings } — evaluate bindings in child scope, then expr
        auto child = make_scope(scope);
        // Execute binding statements directly in child scope (not via block which creates sub-scope)
        ASTNode *bindings = node->where_bindings.get();
        if (bindings && bindings->type == AST_BLOCK) {
            for (auto &s : bindings->block_stmts) {
                eval(s.get(), child);
            }
        } else if (bindings) {
            eval(bindings, child);
        }
        return eval(node->where_expr.get(), child);
    }

    case AST_COMPREHENSION: {
        // [expr for var in iter if cond]
        Value iter_val = eval(node->comp_iter.get(), scope);
        if (!iter_val.is_list())
            snafu_die("comprehension requires a list to iterate");
        Value result = Value::List(static_cast<int>(iter_val.list->size()));
        auto child = make_scope(scope);
        for (size_t ci = 0; ci < iter_val.list->size(); ci++) {
            child->set_local(node->comp_var, (*iter_val.list)[ci]);
            if (node->comp_cond) {
                Value cond = eval(node->comp_cond.get(), child);
                if (!cond.truthy()) continue;
            }
            result.list_push(eval(node->comp_expr.get(), child));
        }
        return result;
    }

    case AST_DEFER: {
        // Should not be reached directly — handled by block evaluator
        return Value::Und();
    }

    case AST_QUANTIFIER: {
        // some/every x in list if pred
        Value iter_val = eval(node->quant_iter.get(), scope);
        if (!iter_val.is_list())
            snafu_die("quantifier requires a list");
        auto child = make_scope(scope);
        if (node->quant_is_every) {
            // every: short-circuit false
            for (size_t qi = 0; qi < iter_val.list->size(); qi++) {
                child->set_local(node->quant_var, (*iter_val.list)[qi]);
                Value pred = eval(node->quant_pred.get(), child);
                if (!pred.truthy()) return Value::Bool(false);
            }
            return Value::Bool(true);
        } else {
            // some: short-circuit true
            for (size_t qi = 0; qi < iter_val.list->size(); qi++) {
                child->set_local(node->quant_var, (*iter_val.list)[qi]);
                Value pred = eval(node->quant_pred.get(), child);
                if (pred.truthy()) return Value::Bool(true);
            }
            return Value::Bool(false);
        }
    }

    case AST_REACTIVE_ON: {
        // on x.field { body } — register a reactive trigger
        Scope *r = scope->root();
        ReactiveTrigger trigger;
        trigger.var_name = node->reactive_var;
        trigger.field = node->reactive_field;
        trigger.body = node->reactive_body.get();
        r->triggers.push_back(trigger);
        g_trigger_count.fetch_add(1, std::memory_order_relaxed);
        return Value::Und();
    }

    case AST_REACTIVE_OFF: {
        // of x.field — remove reactive trigger
        Scope *r = scope->root();
        auto &trigs = r->triggers;
        size_t old_size = trigs.size();
        trigs.erase(
            std::remove_if(trigs.begin(), trigs.end(),
                [&](const ReactiveTrigger &t) {
                    return t.var_name == node->reactive_var &&
                           t.field == node->reactive_field;
                }),
            trigs.end());
        int removed = static_cast<int>(old_size - trigs.size());
        if (removed > 0) {
            g_trigger_count.fetch_sub(removed, std::memory_order_relaxed);
        }
        return Value::Und();
    }

    case AST_FORK: {
        // fk { body } — deep-copy scope, run in thread, return Future
        auto fd = std::make_shared<FutureData>();
        ASTNode *body = node->fork_body.get();
        // Deep-copy the scope for isolation
        auto forked_scope = make_scope(scope->parent);
        forked_scope->bindings = scope->bindings;
        fd->thread = std::make_shared<std::thread>([fd, body, forked_scope]() {
            try {
                Value result = eval(body, forked_scope);
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = result;
                fd->done = true;
                fd->cv.notify_all();
            } catch (ReturnSignal &rs) {
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = rs.value;
                fd->done = true;
                fd->cv.notify_all();
            } catch (SnafuError &) {
                std::lock_guard<std::mutex> lock(fd->mtx);
                fd->result = Value::Und();
                fd->done = true;
                fd->cv.notify_all();
            }
        });
        fd->thread->detach();
        return Value::Future(fd);
    }

    case AST_MACRO_DECL: {
        // Handled by AST_FNDECL with is_macro flag
        return Value::Und();
    }

    case AST_PRINT:
        return Value::Und();

    } /* end switch */

    snafu_die("unknown AST node type %d", node->type);
    return Value::Und();
}

/* ------------------------------------------------------------------ */
/*  Check if an AST subtree contains any function declaration          */
/* ------------------------------------------------------------------ */

static bool ast_has_fndecl(ASTNode *node) {
    if (!node) return false;
    if (node->type == AST_FNDECL) return true;
    switch (node->type) {
    case AST_BLOCK:
        for (auto &s : node->block_stmts)
            if (ast_has_fndecl(s.get())) return true;
        return false;
    case AST_IF:
        if (ast_has_fndecl(node->if_then.get())) return true;
        for (auto &b : node->elif_bodies)
            if (ast_has_fndecl(b.get())) return true;
        if (ast_has_fndecl(node->if_else.get())) return true;
        return false;
    case AST_FOR:
        return ast_has_fndecl(node->for_body.get());
    case AST_WHILE:
        return ast_has_fndecl(node->while_body.get());
    case AST_EXPRSTMT:
        return ast_has_fndecl(node->expr.get());
    default:
        return false;
    }
}

/* ------------------------------------------------------------------ */
/*  call_value — call a Value directly (for pipeline, builtins)        */
/* ------------------------------------------------------------------ */

static Value call_value(Value &fn, Value *args, int nargs, std::shared_ptr<Scope> scope) {
    if (fn.is_builtin()) {
        return (*fn.builtin_fn)(args, nargs, scope.get());
    }

    if (fn.is_fn()) {
        if (nargs != static_cast<int>(fn.fn->params.size()))
            snafu_die("function '%s' expects %d args, got %d",
                      fn.fn->name.c_str(),
                      static_cast<int>(fn.fn->params.size()), nargs);

        // Fast path for simple non-coroutine, non-closure-capturing functions
        if (!fn.fn->is_coroutine && !fn.fn->may_capture) {
            auto call_scope = make_scope(fn.fn->closure);
            call_scope->bindings.reserve(nargs + 1);
            for (int i = 0; i < nargs; i++)
                call_scope->bindings.emplace(fn.fn->params[i], args[i]);
            call_scope->bindings.emplace(fn.fn->name, fn);
            Value result = eval(fn.fn->body, call_scope);
            if (tl_return_flag) {
                tl_return_flag = false;
                return tl_return_value;
            }
            return result;
        }

        // If coroutine, create a Generator
        if (fn.fn->is_coroutine) {
            auto gd = std::make_shared<GeneratorData>();
            auto call_scope = make_scope(fn.fn->closure);
            for (int i = 0; i < nargs; i++)
                call_scope->set_local(fn.fn->params[i], args[i]);

            // Store generator in scope so y (yield) can find it
            Value gen_val = Value::Generator(gd);
            call_scope->set_local("__gen__", gen_val);

            ASTNode *body = fn.fn->body;
            gd->thread = std::make_shared<std::thread>([gd, body, call_scope]() {
                try {
                    // Wait for first next() call
                    {
                        std::unique_lock<std::mutex> lock(gd->mtx);
                        gd->started = true;
                        gd->cv_producer.wait(lock, [&gd]() { return gd->next_requested; });
                        gd->next_requested = false;
                    }
                    eval(body, call_scope);
                } catch (ReturnSignal &) {
                    // Normal end
                } catch (SnafuError &) {
                    // Error
                } catch (...) {
                    // Any other
                }
                // Signal done
                std::lock_guard<std::mutex> lock(gd->mtx);
                gd->done = true;
                gd->value_ready = true;
                gd->yielded_value = Value::Und();
                gd->cv_consumer.notify_all();
            });
            gd->thread->detach();
            // Wait for thread to be started
            while (!gd->started) {
                std::this_thread::yield();
            }
            return gen_val;
        }

        auto call_scope = make_scope(fn.fn->closure);
        for (int i = 0; i < nargs; i++)
            call_scope->set_local(fn.fn->params[i], args[i]);
        call_scope->set_local(fn.fn->name, fn);

        Value result = eval(fn.fn->body, call_scope);
        if (tl_return_flag) {
            tl_return_flag = false;
            return tl_return_value;
        }
        return result;
    }

    if (fn.is_pyobj()) {
        std::vector<Value> vargs(args, args + nargs);
        return python_call(fn, vargs);
    }

    snafu_die("not callable (type %d)", fn.type);
    return Value::Und();
}

/* ------------------------------------------------------------------ */
/*  eval_dot_call — method call dispatch                               */
/* ------------------------------------------------------------------ */

static Value eval_dot_call(Value &target, const std::string &method,
                           Value *args, int nargs, std::shared_ptr<Scope> scope) {
    /* ---------- Generator methods ---------- */
    if (target.is_generator()) {
        if (method == "next") {
            auto &gd = target.generator;
            {
                std::lock_guard<std::mutex> lock(gd->mtx);
                if (gd->done) return Value::Und();
                gd->next_requested = true;
            }
            gd->cv_producer.notify_all();
            // Wait for value
            {
                std::unique_lock<std::mutex> lock(gd->mtx);
                gd->cv_consumer.wait(lock, [&gd]() { return gd->value_ready; });
                gd->value_ready = false;
            }
            return gd->yielded_value;
        }
        snafu_die("generator has no method '%s'", method.c_str());
    }

    /* ---------- Future methods ---------- */
    if (target.is_future()) {
        if (method == "join" || method == "wait") {
            auto &fd = target.future;
            std::unique_lock<std::mutex> lock(fd->mtx);
            fd->cv.wait(lock, [&fd]() { return fd->done; });
            return fd->result;
        }
        snafu_die("future has no method '%s'", method.c_str());
    }

    /* ---------- Channel methods ---------- */
    if (target.is_channel()) {
        auto &cd = target.channel;
        if (method == "send") {
            if (nargs != 1) snafu_die("channel.send() takes 1 argument");
            std::unique_lock<std::mutex> lock(cd->mtx);
            if (cd->capacity > 0) {
                cd->cv_send.wait(lock, [&cd]() {
                    return static_cast<int>(cd->buf.size()) < cd->capacity || cd->closed;
                });
            }
            if (cd->closed) snafu_die("send on closed channel");
            cd->buf.push(args[0]);
            cd->cv_recv.notify_one();
            return Value::Und();
        }
        if (method == "recv") {
            std::unique_lock<std::mutex> lock(cd->mtx);
            cd->cv_recv.wait(lock, [&cd]() { return !cd->buf.empty() || cd->closed; });
            if (cd->buf.empty()) return Value::Und();
            Value v = cd->buf.front();
            cd->buf.pop();
            cd->cv_send.notify_one();
            return v;
        }
        if (method == "close") {
            std::lock_guard<std::mutex> lock(cd->mtx);
            cd->closed = true;
            cd->cv_recv.notify_all();
            cd->cv_send.notify_all();
            return Value::Und();
        }
        snafu_die("channel has no method '%s'", method.c_str());
    }

    /* ---------- Actor methods ---------- */
    if (target.is_actor()) {
        auto &ad = target.actor;
        if (method == "send") {
            if (nargs != 1) snafu_die("actor.send() takes 1 argument");
            // Put message on inbox, wait for response on outbox
            {
                std::lock_guard<std::mutex> lock(ad->mtx);
                if (ad->stopped) snafu_die("actor is stopped");
                ad->inbox.push(args[0]);
            }
            ad->cv_inbox.notify_one();
            // Wait for response
            {
                std::unique_lock<std::mutex> lock(ad->mtx);
                ad->cv_outbox.wait(lock, [&ad]() {
                    return !ad->outbox.empty() || ad->stopped;
                });
                if (ad->outbox.empty()) return Value::Und();
                Value resp = ad->outbox.front();
                ad->outbox.pop();
                return resp;
            }
        }
        if (method == "stop") {
            {
                std::lock_guard<std::mutex> lock(ad->mtx);
                ad->stopped = true;
            }
            ad->cv_inbox.notify_all();
            return Value::Und();
        }
        snafu_die("actor has no method '%s'", method.c_str());
    }

    /* ---------- String methods ---------- */
    if (target.is_str()) {
        const std::string &s = *target.sval;
        if (method == "len" || method == "length")
            return Value::Int(static_cast<long long>(s.size()));
        if (method == "upr" || method == "upper") {
            std::string r = s;
            for (auto &c : r) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
            return Value::Str(r);
        }
        if (method == "lwr" || method == "lower") {
            std::string r = s;
            for (auto &c : r) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
            return Value::Str(r);
        }
        if (method == "trim") {
            size_t start = s.find_first_not_of(" \t\n\r");
            if (start == std::string::npos) return Value::Str("");
            size_t end = s.find_last_not_of(" \t\n\r");
            return Value::Str(s.substr(start, end - start + 1));
        }
        if (method == "split") {
            std::string sep = " ";
            if (nargs >= 1 && args[0].is_str()) sep = *args[0].sval;
            Value result = Value::List(0);
            if (sep.empty()) {
                // Split into characters
                for (char c : s)
                    result.list_push(Value::Str(std::string(1, c)));
            } else {
                size_t pos = 0;
                while (true) {
                    size_t found = s.find(sep, pos);
                    if (found == std::string::npos) {
                        result.list_push(Value::Str(s.substr(pos)));
                        break;
                    }
                    result.list_push(Value::Str(s.substr(pos, found - pos)));
                    pos = found + sep.size();
                }
            }
            return result;
        }
        if (method == "replace") {
            if (nargs != 2 || !args[0].is_str() || !args[1].is_str())
                snafu_die("string.replace(old, new) requires 2 string arguments");
            std::string from = *args[0].sval;
            std::string to = *args[1].sval;
            std::string r = s;
            if (!from.empty()) {
                size_t pos = 0;
                while ((pos = r.find(from, pos)) != std::string::npos) {
                    r.replace(pos, from.size(), to);
                    pos += to.size();
                }
            }
            return Value::Str(r);
        }
        if (method == "contains") {
            if (nargs != 1 || !args[0].is_str())
                snafu_die("string.contains() requires 1 string argument");
            return Value::Bool(s.find(*args[0].sval) != std::string::npos);
        }
        if (method == "starts_with" || method == "startswith") {
            if (nargs != 1 || !args[0].is_str())
                snafu_die("string.starts_with() requires 1 string argument");
            const std::string &prefix = *args[0].sval;
            return Value::Bool(s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0);
        }
        if (method == "ends_with" || method == "endswith") {
            if (nargs != 1 || !args[0].is_str())
                snafu_die("string.ends_with() requires 1 string argument");
            const std::string &suffix = *args[0].sval;
            return Value::Bool(s.size() >= suffix.size() &&
                             s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0);
        }
        snafu_die("string has no method '%s'", method.c_str());
    }

    /* ---------- List methods ---------- */
    if (target.is_list()) {
        if (method == "len" || method == "length")
            return Value::Int(target.list_len());
        if (method == "push" || method == "append") {
            if (nargs != 1) snafu_die("list.push() takes 1 argument");
            target.list->push_back(args[0]);
            return target;
        }
        if (method == "pop") {
            if (target.list->empty()) snafu_die("pop on empty list");
            Value v = target.list->back();
            target.list->pop_back();
            return v;
        }
        if (method == "rev" || method == "reverse") {
            Value r = Value::List(target.list_len());
            for (int i = target.list_len() - 1; i >= 0; i--)
                r.list_push((*target.list)[i]);
            return r;
        }
        if (method == "sum") {
            long long isum = 0;
            double fsum = 0.0;
            bool is_float = false;
            for (auto &item : *target.list) {
                if (item.is_float()) { is_float = true; fsum += item.fval; }
                else if (item.is_int()) { isum += item.ival; fsum += static_cast<double>(item.ival); }
                else snafu_die("sum: non-numeric element");
            }
            return is_float ? Value::Float(fsum) : Value::Int(isum);
        }
        if (method == "map") {
            if (nargs != 1) snafu_die("list.map() takes 1 argument");
            Value &fn = args[0];
            Value r = Value::List(target.list_len());
            for (auto &item : *target.list) {
                Value call_arg = item;
                Value v = call_value(fn, &call_arg, 1, scope);
                r.list_push(v);
            }
            return r;
        }
        if (method == "filter") {
            if (nargs != 1) snafu_die("list.filter() takes 1 argument");
            Value &fn = args[0];
            Value r = Value::List(0);
            for (auto &item : *target.list) {
                Value call_arg = item;
                Value v = call_value(fn, &call_arg, 1, scope);
                if (v.truthy())
                    r.list_push(call_arg);
            }
            return r;
        }
        if (method == "sort") {
            Value r = Value::List(target.list_len());
            *r.list = *target.list;
            if (nargs >= 1) {
                // Sort with key function
                Value &key_fn = args[0];
                std::sort(r.list->begin(), r.list->end(),
                    [&key_fn, &scope](Value &a, Value &b) {
                        Value ka = call_value(key_fn, &a, 1, scope);
                        Value kb = call_value(key_fn, &b, 1, scope);
                        return ka.to_num() < kb.to_num();
                    });
            } else {
                std::sort(r.list->begin(), r.list->end(),
                    [](const Value &a, const Value &b) {
                        return a.to_num() < b.to_num();
                    });
            }
            return r;
        }
        if (method == "contains" || method == "has") {
            if (nargs != 1) snafu_die("list.contains() takes 1 argument");
            for (auto &item : *target.list) {
                if (val_eq(item, args[0])) return Value::Bool(true);
            }
            return Value::Bool(false);
        }
        if (method == "join") {
            std::string sep = "";
            if (nargs >= 1 && args[0].is_str()) sep = *args[0].sval;
            std::string out;
            for (size_t i = 0; i < target.list->size(); i++) {
                if (i > 0) out += sep;
                out += (*target.list)[i].to_string();
            }
            return Value::Str(out);
        }
        snafu_die("list has no method '%s'", method.c_str());
    }

    /* ---------- Dict methods ---------- */
    if (target.is_dict()) {
        // Try to find the method as a value in the dict (for context managers, etc.)
        auto it = target.dict->find(method);
        if (it != target.dict->end()) {
            Value fn = it->second;
            return call_value(fn, args, nargs, scope);
        }
        if (method == "keys") {
            Value r = Value::List(static_cast<int>(target.dict->size()));
            for (auto &kv : *target.dict)
                r.list_push(Value::Str(kv.first));
            return r;
        }
        if (method == "vals" || method == "values") {
            Value r = Value::List(static_cast<int>(target.dict->size()));
            for (auto &kv : *target.dict)
                r.list_push(kv.second);
            return r;
        }
        if (method == "has" || method == "contains") {
            if (nargs != 1 || !args[0].is_str())
                snafu_die("dict.has() requires 1 string argument");
            return Value::Bool(target.dict->count(*args[0].sval) > 0);
        }
        if (method == "len" || method == "length")
            return Value::Int(static_cast<long long>(target.dict->size()));
        snafu_die("dict has no method '%s'", method.c_str());
    }

    /* ---------- Python object methods ---------- */
    if (target.is_pyobj()) {
#ifdef SNAFU_HAS_PYTHON
        PyObject *attr = PyObject_GetAttrString((PyObject *)target.pyobj, method.c_str());
        if (attr) {
            if (PyCallable_Check(attr)) {
                /* Build argument list and call directly */
                std::vector<Value> vargs(args, args + nargs);
                Value callable;
                callable.type = VAL_PYOBJ;
                callable.pyobj = attr;
                Value result = python_call(callable, vargs);
                Py_DECREF(attr);
                return result;
            }
            /* Non-callable attribute -- return its value */
            Value result = python_to_snafu(attr);
            Py_DECREF(attr);
            return result;
        }
        PyErr_Clear();
#endif
        snafu_die("Python object has no attribute '%s'", method.c_str());
    }

    snafu_die("type has no method '%s'", method.c_str());
    return Value::Und();
}

/* ------------------------------------------------------------------ */
/*  eval_call — function call with evaluated args                      */
/* ------------------------------------------------------------------ */

static Value eval_call(ASTNode *fn_node,
                       std::vector<std::unique_ptr<ASTNode>> &arg_nodes,
                       std::shared_ptr<Scope> scope) {
    Value fn = eval(fn_node, scope);
    int nargs = static_cast<int>(arg_nodes.size());

    // Macro call: pass AST nodes unevaluated, result is evaluated
    if (fn.is_fn() && fn.fn->is_macro) {
        if (nargs != static_cast<int>(fn.fn->params.size()))
            snafu_die("macro '%s' expects %d args, got %d",
                      fn.fn->name.c_str(),
                      static_cast<int>(fn.fn->params.size()), nargs);
        auto call_scope = make_scope(fn.fn->closure);
        // Pass arg AST nodes as raw pointers stored in a dict with __ast__ marker
        for (int i = 0; i < nargs; i++) {
            // For macros, each argument becomes a thunk: a zero-arg fn that evaluates the AST
            ASTNode *arg_ast = arg_nodes[i].get();
            auto arg_scope = scope; // capture the caller's scope
            Value thunk = Value::Builtin(
                [arg_ast, arg_scope](Value *, int, Scope *) -> Value {
                    return eval(arg_ast, arg_scope);
                }
            );
            call_scope->set_local(fn.fn->params[i], thunk);
        }
        call_scope->set_local(fn.fn->name, fn);
        Value result;
        try {
            result = eval(fn.fn->body, call_scope);
        } catch (ReturnSignal &rs) {
            result = rs.value;
        }
        return result;
    }

    // Stack-allocate args for small counts
    Value args_stack[8];
    Value *args = (nargs <= 8) ? args_stack : new Value[nargs];
    for (int i = 0; i < nargs; i++) {
        args[i] = eval(arg_nodes[i].get(), scope);
    }

    Value result = call_value(fn, args, nargs, scope);
    if (args != args_stack) delete[] args;
    return result;
}
