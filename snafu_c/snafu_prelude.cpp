#include "snafu.h"
#include "snafu_python.h"

/* ================================================================== */
/*  Built-in functions                                                 */
/* ================================================================== */

/* ---- p(args...) -- print ---- */
static Value bi_p(Value *args, int nargs, Scope *scope) {
    (void)scope;
    for (int i = 0; i < nargs; i++) {
        if (i > 0) std::cout << ' ';
        std::cout << args[i].to_string();
    }
    std::cout << '\n';
    return Value::Und();
}

/* ---- len(x) ---- */
static Value bi_len(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("len() takes exactly 1 argument");
    const Value &v = args[0];
    if (v.is_str())  return Value::Int(static_cast<long long>(v.sval->size()));
    if (v.is_list()) return Value::Int(v.list_len());
    if (v.is_dict()) return Value::Int(static_cast<long long>(v.dict->size()));
    snafu_die("len() not supported for this type");
    return Value::Und();
}

/* ---- sum(list) ---- */
static Value bi_sum(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs < 1) snafu_die("sum() takes at least 1 argument");
    const Value &v = args[0];
    if (!v.is_list()) snafu_die("sum() requires a list");
    long long isum = 0;
    double    fsum = 0.0;
    bool is_float = false;
    for (auto &item : *v.list) {
        if (item.is_float()) {
            is_float = true;
            fsum += item.fval;
        } else if (item.is_int()) {
            isum += item.ival;
            fsum += static_cast<double>(item.ival);
        } else {
            snafu_die("sum: non-numeric element");
        }
    }
    return is_float ? Value::Float(fsum) : Value::Int(isum);
}

/* ---- range(n) or range(a, b) or range(a, b, step) ---- */
static Value bi_range(Value *args, int nargs, Scope *scope) {
    (void)scope;
    long long start, end, step;
    if (nargs == 1) {
        if (!args[0].is_int()) snafu_die("range() requires int");
        start = 0; end = args[0].ival; step = 1;
    } else if (nargs == 2) {
        if (!args[0].is_int() || !args[1].is_int())
            snafu_die("range() requires int");
        start = args[0].ival; end = args[1].ival; step = 1;
    } else if (nargs == 3) {
        if (!args[0].is_int() || !args[1].is_int() || !args[2].is_int())
            snafu_die("range() requires int");
        start = args[0].ival; end = args[1].ival; step = args[2].ival;
        if (step == 0) snafu_die("range(): step cannot be 0");
    } else {
        snafu_die("range() takes 1-3 arguments");
        return Value::Und();
    }
    int n = 0;
    if (step > 0 && end > start) n = static_cast<int>((end - start + step - 1) / step);
    else if (step < 0 && end < start) n = static_cast<int>((start - end - step - 1) / (-step));
    Value r = Value::List(n > 0 ? n : 0);
    for (long long i = start; step > 0 ? i < end : i > end; i += step)
        r.list_push(Value::Int(i));
    return r;
}

/* ---- type(x) ---- */
static Value bi_type(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("type() takes exactly 1 argument");
    switch (args[0].type) {
    case VAL_INT:     return Value::Str("Int");
    case VAL_FLOAT:   return Value::Str("Flt");
    case VAL_STR:     return Value::Str("Str");
    case VAL_BOOL:    return Value::Str("Bool");
    case VAL_UND:     return Value::Str("Und");
    case VAL_LIST:    return Value::Str("Lst");
    case VAL_DICT:    return Value::Str("Dct");
    case VAL_FN:      return Value::Str("Fn");
    case VAL_BUILTIN: return Value::Str("Fn");
    case VAL_VARIANT:  return Value::Str("Var");
    case VAL_GENERATOR: return Value::Str("Gen");
    case VAL_FUTURE:   return Value::Str("Fut");
    case VAL_CHANNEL:  return Value::Str("Ch");
    case VAL_ACTOR:    return Value::Str("Actor");
    case VAL_PYOBJ:    return Value::Str("PyObj");
    }
    return Value::Str("?");
}

/* ---- str(x) ---- */
static Value bi_str(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("str() takes exactly 1 argument");
    return Value::Str(args[0].to_string());
}

/* ---- int(x) ---- */
static Value bi_int(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("int() takes exactly 1 argument");
    const Value &v = args[0];
    if (v.is_int())   return v;
    if (v.is_float()) return Value::Int(static_cast<long long>(v.fval));
    if (v.is_bool())  return Value::Int(v.bval ? 1 : 0);
    if (v.is_str())   return Value::Int(atoll(v.sval->c_str()));
    snafu_die("cannot convert to int");
    return Value::Und();
}

/* ---- abs(x) ---- */
static Value bi_abs(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("abs() takes exactly 1 argument");
    const Value &v = args[0];
    if (v.is_int())   return Value::Int(v.ival < 0 ? -v.ival : v.ival);
    if (v.is_float()) return Value::Float(fabs(v.fval));
    snafu_die("abs() requires numeric argument");
    return Value::Und();
}

/* ---- sqrt(x) ---- */
static Value bi_sqrt(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("sqrt() takes exactly 1 argument");
    double d;
    if (args[0].is_int())        d = static_cast<double>(args[0].ival);
    else if (args[0].is_float()) d = args[0].fval;
    else { snafu_die("sqrt() requires numeric"); d = 0; }
    return Value::Float(sqrt(d));
}

/* ---- m(list, fn) -- map ---- */
static Value bi_m(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("m() takes exactly 2 arguments");
    Value &lst = args[0];
    Value &fn  = args[1];
    if (!lst.is_list()) snafu_die("m(): first arg must be list");
    Value r = Value::List(lst.list_len());
    for (auto &item : *lst.list) {
        Value call_arg = item;
        Value v;
        if (fn.is_builtin()) {
            v = (*fn.builtin_fn)(&call_arg, 1, scope);
        } else if (fn.is_fn()) {
            auto cs = make_scope(fn.fn->closure);
            if (!fn.fn->params.empty())
                cs->set_local(fn.fn->params[0], call_arg);
            cs->set_local(fn.fn->name, fn);
            try {
                v = eval(fn.fn->body, cs);
            } catch (ReturnSignal &rs) {
                v = rs.value;
            }
        } else {
            snafu_die("m(): second arg must be a function");
        }
        r.list_push(v);
    }
    return r;
}

/* ---- fl(list, fn) -- filter ---- */
static Value bi_fl(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("fl() takes exactly 2 arguments");
    Value &lst = args[0];
    Value &fn  = args[1];
    if (!lst.is_list()) snafu_die("fl(): first arg must be list");
    Value r = Value::List(lst.list_len());
    for (auto &item : *lst.list) {
        Value call_arg = item;
        Value v;
        if (fn.is_builtin()) {
            v = (*fn.builtin_fn)(&call_arg, 1, scope);
        } else if (fn.is_fn()) {
            auto cs = make_scope(fn.fn->closure);
            if (!fn.fn->params.empty())
                cs->set_local(fn.fn->params[0], call_arg);
            cs->set_local(fn.fn->name, fn);
            try {
                v = eval(fn.fn->body, cs);
            } catch (ReturnSignal &rs) {
                v = rs.value;
            }
        } else {
            snafu_die("fl(): second arg must be a function");
        }
        if (v.truthy())
            r.list_push(call_arg);
    }
    return r;
}

/* ---- flt(x) -- convert to float ---- */
static Value bi_flt(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("flt() takes exactly 1 argument");
    const Value &v = args[0];
    if (v.is_float()) return v;
    if (v.is_int())   return Value::Float(static_cast<double>(v.ival));
    if (v.is_str())   return Value::Float(atof(v.sval->c_str()));
    if (v.is_bool())  return Value::Float(v.bval ? 1.0 : 0.0);
    snafu_die("cannot convert to float");
    return Value::Und();
}

/* ---- rev(list) -- reverse ---- */
static Value bi_rev(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("rev() takes exactly 1 argument");
    const Value &v = args[0];
    if (!v.is_list()) snafu_die("rev() requires a list");
    Value r = Value::List(v.list_len());
    for (int i = v.list_len() - 1; i >= 0; i--)
        r.list_push((*v.list)[i]);
    return r;
}

/* ---- join(sep, list) ---- */
static Value bi_join(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("join() takes exactly 2 arguments");
    if (!args[0].is_str()) snafu_die("join(): first arg must be string");
    if (!args[1].is_list()) snafu_die("join(): second arg must be list");
    const std::string &sep = *args[0].sval;
    std::string out;
    for (size_t i = 0; i < args[1].list->size(); i++) {
        if (i > 0) out += sep;
        out += (*args[1].list)[i].to_string();
    }
    return Value::Str(out);
}

/* ---- min / max ---- */
static Value bi_min(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs == 1 && args[0].is_list()) {
        auto &lst = *args[0].list;
        if (lst.empty()) snafu_die("min() of empty list");
        Value best = lst[0];
        for (size_t i = 1; i < lst.size(); i++) {
            if (lst[i].to_num() < best.to_num()) best = lst[i];
        }
        return best;
    }
    if (nargs >= 2) {
        Value best = args[0];
        for (int i = 1; i < nargs; i++) {
            if (args[i].to_num() < best.to_num()) best = args[i];
        }
        return best;
    }
    snafu_die("min() requires at least 1 argument");
    return Value::Und();
}

static Value bi_max(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs == 1 && args[0].is_list()) {
        auto &lst = *args[0].list;
        if (lst.empty()) snafu_die("max() of empty list");
        Value best = lst[0];
        for (size_t i = 1; i < lst.size(); i++) {
            if (lst[i].to_num() > best.to_num()) best = lst[i];
        }
        return best;
    }
    if (nargs >= 2) {
        Value best = args[0];
        for (int i = 1; i < nargs; i++) {
            if (args[i].to_num() > best.to_num()) best = args[i];
        }
        return best;
    }
    snafu_die("max() requires at least 1 argument");
    return Value::Und();
}

/* ---- push(list, val) ---- */
static Value bi_push(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("push() takes exactly 2 arguments");
    if (!args[0].is_list()) snafu_die("push(): first arg must be list");
    args[0].list->push_back(args[1]);
    return args[0];
}

/* ---- pop(list) ---- */
static Value bi_pop(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("pop() takes exactly 1 argument");
    if (!args[0].is_list()) snafu_die("pop(): arg must be list");
    if (args[0].list->empty()) snafu_die("pop(): empty list");
    Value v = args[0].list->back();
    args[0].list->pop_back();
    return v;
}

/* ---- head(list) ---- */
static Value bi_head(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("head() takes exactly 1 argument");
    if (!args[0].is_list()) snafu_die("head(): arg must be list");
    if (args[0].list->empty()) snafu_die("head(): empty list");
    return (*args[0].list)[0];
}

/* ---- tail(list) ---- */
static Value bi_tail(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("tail() takes exactly 1 argument");
    if (!args[0].is_list()) snafu_die("tail(): arg must be list");
    if (args[0].list->empty()) return Value::List(0);
    Value r = Value::List(static_cast<int>(args[0].list->size()) - 1);
    for (size_t i = 1; i < args[0].list->size(); i++)
        r.list_push((*args[0].list)[i]);
    return r;
}

/* ---- keys(dict) ---- */
static Value bi_keys(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("keys() takes exactly 1 argument");
    if (!args[0].is_dict()) snafu_die("keys(): arg must be dict");
    Value r = Value::List(static_cast<int>(args[0].dict->size()));
    for (auto &kv : *args[0].dict)
        r.list_push(Value::Str(kv.first));
    return r;
}

/* ---- vals(dict) ---- */
static Value bi_vals(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("vals() takes exactly 1 argument");
    if (!args[0].is_dict()) snafu_die("vals(): arg must be dict");
    Value r = Value::List(static_cast<int>(args[0].dict->size()));
    for (auto &kv : *args[0].dict)
        r.list_push(kv.second);
    return r;
}

/* ---- throw(msg) ---- */
static Value bi_throw(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("throw() takes exactly 1 argument");
    throw SnafuError(args[0].to_string());
}

/* ---- rdc(list, fn, init) — reduce ---- */
static Value bi_rdc(Value *args, int nargs, Scope *scope) {
    if (nargs < 2) snafu_die("rdc() takes 2-3 arguments");
    Value &lst = args[0];
    Value &fn  = args[1];
    if (!lst.is_list()) snafu_die("rdc(): first arg must be list");
    Value acc;
    size_t start = 0;
    if (nargs >= 3) {
        acc = args[2];
        start = 0;
    } else {
        if (lst.list->empty()) snafu_die("rdc() on empty list without init");
        acc = (*lst.list)[0];
        start = 1;
    }
    for (size_t i = start; i < lst.list->size(); i++) {
        Value call_args[2] = {acc, (*lst.list)[i]};
        if (fn.is_builtin()) {
            acc = (*fn.builtin_fn)(call_args, 2, scope);
        } else if (fn.is_fn()) {
            auto cs = make_scope(fn.fn->closure);
            if (fn.fn->params.size() >= 1)
                cs->set_local(fn.fn->params[0], call_args[0]);
            if (fn.fn->params.size() >= 2)
                cs->set_local(fn.fn->params[1], call_args[1]);
            cs->set_local(fn.fn->name, fn);
            try {
                acc = eval(fn.fn->body, cs);
            } catch (ReturnSignal &rs) {
                acc = rs.value;
            }
        } else {
            snafu_die("rdc(): second arg must be a function");
        }
    }
    return acc;
}

/* ---- srt(list) or srt(list, key_fn) — sort ---- */
static Value bi_srt(Value *args, int nargs, Scope *scope) {
    if (nargs < 1) snafu_die("srt() takes 1-2 arguments");
    Value &lst = args[0];
    if (!lst.is_list()) snafu_die("srt(): first arg must be list");
    Value r = Value::List(lst.list_len());
    *r.list = *lst.list;
    if (nargs >= 2) {
        Value key_fn = args[1];
        auto scp = make_scope(nullptr);
        std::sort(r.list->begin(), r.list->end(),
            [&key_fn, &scp, scope](Value &a, Value &b) {
                Value ka, kb;
                if (key_fn.is_builtin()) {
                    ka = (*key_fn.builtin_fn)(&a, 1, scope);
                    kb = (*key_fn.builtin_fn)(&b, 1, scope);
                } else if (key_fn.is_fn()) {
                    {
                        auto cs = make_scope(key_fn.fn->closure);
                        if (!key_fn.fn->params.empty())
                            cs->set_local(key_fn.fn->params[0], a);
                        try { ka = eval(key_fn.fn->body, cs); }
                        catch (ReturnSignal &rs) { ka = rs.value; }
                    }
                    {
                        auto cs = make_scope(key_fn.fn->closure);
                        if (!key_fn.fn->params.empty())
                            cs->set_local(key_fn.fn->params[0], b);
                        try { kb = eval(key_fn.fn->body, cs); }
                        catch (ReturnSignal &rs) { kb = rs.value; }
                    }
                } else {
                    return false;
                }
                return ka.to_num() < kb.to_num();
            });
    } else {
        std::sort(r.list->begin(), r.list->end(),
            [](const Value &a, const Value &b) {
                if (a.is_str() && b.is_str()) return *a.sval < *b.sval;
                return a.to_num() < b.to_num();
            });
    }
    return r;
}

/* ---- take(list, n) ---- */
static Value bi_take(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("take() takes 2 arguments");
    if (!args[0].is_list()) snafu_die("take(): first arg must be list");
    if (!args[1].is_int()) snafu_die("take(): second arg must be int");
    int n = static_cast<int>(args[1].ival);
    if (n < 0) n = 0;
    if (n > args[0].list_len()) n = args[0].list_len();
    Value r = Value::List(n);
    for (int i = 0; i < n; i++)
        r.list_push((*args[0].list)[i]);
    return r;
}

/* ---- drop(list, n) ---- */
static Value bi_drop(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("drop() takes 2 arguments");
    if (!args[0].is_list()) snafu_die("drop(): first arg must be list");
    if (!args[1].is_int()) snafu_die("drop(): second arg must be int");
    int n = static_cast<int>(args[1].ival);
    if (n < 0) n = 0;
    int len = args[0].list_len();
    if (n > len) n = len;
    Value r = Value::List(len - n);
    for (int i = n; i < len; i++)
        r.list_push((*args[0].list)[i]);
    return r;
}

/* ---- flat(list) — flatten one level ---- */
static Value bi_flat(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("flat() takes 1 argument");
    if (!args[0].is_list()) snafu_die("flat(): arg must be list");
    Value r = Value::List(0);
    for (auto &item : *args[0].list) {
        if (item.is_list()) {
            for (auto &sub : *item.list)
                r.list_push(sub);
        } else {
            r.list_push(item);
        }
    }
    return r;
}

/* ---- zip(a, b) ---- */
static Value bi_zip(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2) snafu_die("zip() takes 2 arguments");
    if (!args[0].is_list() || !args[1].is_list())
        snafu_die("zip(): both args must be lists");
    size_t len = std::min(args[0].list->size(), args[1].list->size());
    Value r = Value::List(static_cast<int>(len));
    for (size_t i = 0; i < len; i++) {
        Value pair = Value::List(2);
        pair.list_push((*args[0].list)[i]);
        pair.list_push((*args[1].list)[i]);
        r.list_push(pair);
    }
    return r;
}

/* ---- en(list) — enumerate ---- */
static Value bi_en(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("en() takes 1 argument");
    if (!args[0].is_list()) snafu_die("en(): arg must be list");
    Value r = Value::List(args[0].list_len());
    for (int i = 0; i < args[0].list_len(); i++) {
        Value pair = Value::List(2);
        pair.list_push(Value::Int(i));
        pair.list_push((*args[0].list)[i]);
        r.list_push(pair);
    }
    return r;
}

/* ---- chr(n) — int to character ---- */
static Value bi_chr(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("chr() takes 1 argument");
    if (!args[0].is_int()) snafu_die("chr(): arg must be int");
    char c = static_cast<char>(args[0].ival);
    return Value::Str(std::string(1, c));
}

/* ---- ord(s) — character to int ---- */
static Value bi_ord(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("ord() takes 1 argument");
    if (!args[0].is_str() || args[0].sval->empty())
        snafu_die("ord(): arg must be non-empty string");
    return Value::Int(static_cast<unsigned char>((*args[0].sval)[0]));
}

/* ---- D(n) — digits of a number ---- */
static Value bi_D(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("D() takes 1 argument");
    std::string s;
    if (args[0].is_int()) {
        s = std::to_string(args[0].ival < 0 ? -args[0].ival : args[0].ival);
    } else if (args[0].is_str()) {
        s = *args[0].sval;
    } else {
        snafu_die("D(): arg must be int or string");
    }
    Value r = Value::List(static_cast<int>(s.size()));
    for (char c : s) {
        if (isdigit(static_cast<unsigned char>(c)))
            r.list_push(Value::Int(c - '0'));
    }
    return r;
}

/* ---- R(list) — reverse ---- */
static Value bi_R(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("R() takes 1 argument");
    if (args[0].is_list()) {
        Value r = Value::List(args[0].list_len());
        for (int i = args[0].list_len() - 1; i >= 0; i--)
            r.list_push((*args[0].list)[i]);
        return r;
    }
    if (args[0].is_str()) {
        std::string s = *args[0].sval;
        std::reverse(s.begin(), s.end());
        return Value::Str(s);
    }
    snafu_die("R(): arg must be list or string");
    return Value::Und();
}

/* ---- T(matrix) — transpose ---- */
static Value bi_T(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("T() takes 1 argument");
    if (!args[0].is_list()) snafu_die("T(): arg must be list of lists");
    auto &mat = *args[0].list;
    if (mat.empty()) return Value::List(0);
    if (!mat[0].is_list()) snafu_die("T(): arg must be list of lists");
    int rows = static_cast<int>(mat.size());
    int cols = mat[0].list_len();
    Value result = Value::List(cols);
    for (int c = 0; c < cols; c++) {
        Value row = Value::List(rows);
        for (int r = 0; r < rows; r++) {
            if (r < static_cast<int>(mat.size()) && mat[r].is_list() && c < mat[r].list_len())
                row.list_push((*mat[r].list)[c]);
            else
                row.list_push(Value::Und());
        }
        result.list_push(row);
    }
    return result;
}

/* ---- to_json(v) — basic JSON serialization ---- */
static std::string value_to_json(const Value &v) {
    if (v.is_und()) return "null";
    if (v.is_bool()) return v.bval ? "true" : "false";
    if (v.is_int()) return std::to_string(v.ival);
    if (v.is_float()) {
        char buf[64];
        snprintf(buf, sizeof(buf), "%g", v.fval);
        return std::string(buf);
    }
    if (v.is_str()) {
        std::string out = "\"";
        for (char c : *v.sval) {
            if (c == '"') out += "\\\"";
            else if (c == '\\') out += "\\\\";
            else if (c == '\n') out += "\\n";
            else if (c == '\t') out += "\\t";
            else out += c;
        }
        out += "\"";
        return out;
    }
    if (v.is_list()) {
        std::string out = "[";
        for (size_t i = 0; i < v.list->size(); i++) {
            if (i > 0) out += ",";
            out += value_to_json((*v.list)[i]);
        }
        out += "]";
        return out;
    }
    if (v.is_dict()) {
        std::string out = "{";
        bool first = true;
        for (auto &kv : *v.dict) {
            if (!first) out += ",";
            first = false;
            out += "\"" + kv.first + "\":" + value_to_json(kv.second);
        }
        out += "}";
        return out;
    }
    return "null";
}

static Value bi_to_json(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("to_json() takes 1 argument");
    return Value::Str(value_to_json(args[0]));
}

/* ---- from_json(s) — basic JSON parsing ---- */
static Value parse_json_value(const std::string &s, size_t &pos);

static void skip_ws(const std::string &s, size_t &pos) {
    while (pos < s.size() && (s[pos] == ' ' || s[pos] == '\t' || s[pos] == '\n' || s[pos] == '\r'))
        pos++;
}

static std::string parse_json_string(const std::string &s, size_t &pos) {
    if (pos >= s.size() || s[pos] != '"') snafu_die("from_json: expected '\"'");
    pos++; // skip "
    std::string out;
    while (pos < s.size() && s[pos] != '"') {
        if (s[pos] == '\\' && pos + 1 < s.size()) {
            pos++;
            if (s[pos] == 'n') out += '\n';
            else if (s[pos] == 't') out += '\t';
            else if (s[pos] == '\\') out += '\\';
            else if (s[pos] == '"') out += '"';
            else out += s[pos];
            pos++;
        } else {
            out += s[pos++];
        }
    }
    if (pos < s.size()) pos++; // skip closing "
    return out;
}

static Value parse_json_value(const std::string &s, size_t &pos) {
    skip_ws(s, pos);
    if (pos >= s.size()) return Value::Und();
    char c = s[pos];
    if (c == '"') {
        return Value::Str(parse_json_string(s, pos));
    }
    if (c == '[') {
        pos++; // skip [
        Value r = Value::List(0);
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ']') { pos++; return r; }
        r.list_push(parse_json_value(s, pos));
        skip_ws(s, pos);
        while (pos < s.size() && s[pos] == ',') {
            pos++;
            r.list_push(parse_json_value(s, pos));
            skip_ws(s, pos);
        }
        if (pos < s.size() && s[pos] == ']') pos++;
        return r;
    }
    if (c == '{') {
        pos++; // skip {
        Value r = Value::Dict();
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == '}') { pos++; return r; }
        while (true) {
            skip_ws(s, pos);
            std::string key = parse_json_string(s, pos);
            skip_ws(s, pos);
            if (pos < s.size() && s[pos] == ':') pos++;
            Value val = parse_json_value(s, pos);
            (*r.dict)[key] = val;
            skip_ws(s, pos);
            if (pos >= s.size() || s[pos] != ',') break;
            pos++;
        }
        if (pos < s.size() && s[pos] == '}') pos++;
        return r;
    }
    if (c == 't' && pos + 3 < s.size() && s.substr(pos, 4) == "true") {
        pos += 4; return Value::Bool(true);
    }
    if (c == 'f' && pos + 4 < s.size() && s.substr(pos, 5) == "false") {
        pos += 5; return Value::Bool(false);
    }
    if (c == 'n' && pos + 3 < s.size() && s.substr(pos, 4) == "null") {
        pos += 4; return Value::Und();
    }
    if (c == '-' || isdigit(static_cast<unsigned char>(c))) {
        size_t start = pos;
        if (c == '-') pos++;
        while (pos < s.size() && isdigit(static_cast<unsigned char>(s[pos]))) pos++;
        bool is_float = false;
        if (pos < s.size() && s[pos] == '.') { is_float = true; pos++; }
        while (pos < s.size() && isdigit(static_cast<unsigned char>(s[pos]))) pos++;
        if (pos < s.size() && (s[pos] == 'e' || s[pos] == 'E')) {
            is_float = true; pos++;
            if (pos < s.size() && (s[pos] == '+' || s[pos] == '-')) pos++;
            while (pos < s.size() && isdigit(static_cast<unsigned char>(s[pos]))) pos++;
        }
        std::string num_str = s.substr(start, pos - start);
        if (is_float) return Value::Float(atof(num_str.c_str()));
        return Value::Int(atoll(num_str.c_str()));
    }
    snafu_die("from_json: unexpected character '%c'", c);
    return Value::Und();
}

static Value bi_from_json(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1) snafu_die("from_json() takes 1 argument");
    if (!args[0].is_str()) snafu_die("from_json(): arg must be string");
    size_t pos = 0;
    return parse_json_value(*args[0].sval, pos);
}

/* ---- __channel__(n) — create a channel ---- */
static Value bi_channel(Value *args, int nargs, Scope *scope) {
    (void)scope;
    int cap = 0;
    if (nargs >= 1 && args[0].is_int()) cap = static_cast<int>(args[0].ival);
    if (cap <= 0) cap = 1024; // unbounded-ish default
    auto cd = std::make_shared<ChannelData>(cap);
    return Value::Channel(cd);
}

/* ---- ps() — push state snapshot ---- */
static Value bi_ps(Value *args, int nargs, Scope *scope) {
    (void)args; (void)nargs;
    Scope *r = scope->root();
    r->snapshots.push_back(scope->all_bindings());
    return Value::Int(static_cast<long long>(r->snapshots.size()) - 1);
}

/* ---- sa(n) — get snapshot n (negative = from end) ---- */
static Value bi_sa(Value *args, int nargs, Scope *scope) {
    if (nargs != 1 || !args[0].is_int())
        snafu_die("sa() takes 1 integer argument");
    Scope *r = scope->root();
    long long idx = args[0].ival;
    if (idx < 0) idx += static_cast<long long>(r->snapshots.size());
    if (idx < 0 || idx >= static_cast<long long>(r->snapshots.size()))
        snafu_die("sa(): snapshot index %lld out of range (have %d)",
                  args[0].ival, static_cast<int>(r->snapshots.size()));
    auto &snap = r->snapshots[static_cast<size_t>(idx)];
    Value d = Value::Dict();
    for (auto &kv : snap)
        (*d.dict)[kv.first] = kv.second;
    return d;
}

/* ---- restore(snapshot_dict) — restore bindings from a snapshot ---- */
static Value bi_restore(Value *args, int nargs, Scope *scope) {
    if (nargs != 1 || !args[0].is_dict())
        snafu_die("restore() takes 1 dict argument (from sa())");
    for (auto &kv : *args[0].dict) {
        // Skip internal names
        if (kv.first[0] == '_' && kv.first.size() > 1 && kv.first[1] == '_')
            continue;
        scope->set(kv.first, kv.second);
    }
    return Value::Und();
}

/* ---- actor(fn) — create an actor with a message-processing function ---- */
static Value bi_actor(Value *args, int nargs, Scope *scope) {
    if (nargs != 1) snafu_die("actor() takes 1 argument (a function)");
    Value fn = args[0];
    if (!fn.is_fn() && !fn.is_builtin())
        snafu_die("actor() requires a function argument");
    auto ad = std::make_shared<ActorData>();
    auto scp = make_scope(fn.is_fn() ? fn.fn->closure : nullptr);
    ad->thread = std::make_shared<std::thread>([ad, fn, scp]() {
        while (true) {
            Value msg;
            {
                std::unique_lock<std::mutex> lock(ad->mtx);
                ad->cv_inbox.wait(lock, [&ad]() {
                    return !ad->inbox.empty() || ad->stopped;
                });
                if (ad->stopped) break;
                msg = ad->inbox.front();
                ad->inbox.pop();
            }
            // Process message
            Value result;
            Value call_fn = fn;
            if (call_fn.is_builtin()) {
                result = (*call_fn.builtin_fn)(&msg, 1, scp.get());
            } else if (call_fn.is_fn()) {
                auto cs = make_scope(call_fn.fn->closure);
                if (!call_fn.fn->params.empty())
                    cs->set_local(call_fn.fn->params[0], msg);
                cs->set_local(call_fn.fn->name, call_fn);
                try {
                    result = eval(call_fn.fn->body, cs);
                } catch (ReturnSignal &rs) {
                    result = rs.value;
                } catch (...) {
                    result = Value::Und();
                }
            }
            // Send response
            {
                std::lock_guard<std::mutex> lock(ad->mtx);
                ad->outbox.push(result);
            }
            ad->cv_outbox.notify_one();
        }
    });
    ad->thread->detach();
    return Value::Actor(ad);
}

/* ---- rand() or rand(n) — random number ---- */
static Value bi_rand(Value *args, int nargs, Scope *scope) {
    (void)scope;
    static thread_local std::mt19937 rng(
        static_cast<unsigned>(std::chrono::steady_clock::now().time_since_epoch().count()));
    if (nargs == 0) {
        std::uniform_real_distribution<double> dist(0.0, 1.0);
        return Value::Float(dist(rng));
    }
    if (nargs == 1 && args[0].is_int()) {
        if (args[0].ival <= 0) return Value::Int(0);
        std::uniform_int_distribution<long long> dist(0, args[0].ival - 1);
        return Value::Int(dist(rng));
    }
    snafu_die("rand() takes 0 or 1 integer argument");
    return Value::Und();
}

/* ---- sleep(ms) — sleep for milliseconds ---- */
static Value bi_sleep(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1 || !args[0].is_int())
        snafu_die("sleep() takes 1 integer argument (milliseconds)");
    std::this_thread::sleep_for(std::chrono::milliseconds(args[0].ival));
    return Value::Und();
}

/* ---- now() — current time in milliseconds since epoch ---- */
static Value bi_now(Value *args, int nargs, Scope *scope) {
    (void)args; (void)nargs; (void)scope;
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    return Value::Int(static_cast<long long>(ms));
}

/* ---- gcd(a, b) ---- */
static Value bi_gcd(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2 || !args[0].is_int() || !args[1].is_int())
        snafu_die("gcd() takes 2 integer arguments");
    long long a = args[0].ival < 0 ? -args[0].ival : args[0].ival;
    long long b = args[1].ival < 0 ? -args[1].ival : args[1].ival;
    while (b) { long long t = b; b = a % b; a = t; }
    return Value::Int(a);
}

/* ---- lcm(a, b) ---- */
static Value bi_lcm(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2 || !args[0].is_int() || !args[1].is_int())
        snafu_die("lcm() takes 2 integer arguments");
    long long a = args[0].ival < 0 ? -args[0].ival : args[0].ival;
    long long b = args[1].ival < 0 ? -args[1].ival : args[1].ival;
    if (a == 0 || b == 0) return Value::Int(0);
    long long g = a;
    long long bb = b;
    while (bb) { long long t = bb; bb = g % bb; g = t; }
    return Value::Int(a / g * b);
}

/* ---- fact(n) — factorial ---- */
static Value bi_fact(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1 || !args[0].is_int())
        snafu_die("fact() takes 1 integer argument");
    long long n = args[0].ival;
    if (n < 0) snafu_die("fact(): negative argument");
    long long result = 1;
    for (long long i = 2; i <= n; i++) result *= i;
    return Value::Int(result);
}

/* ---- uniq(list) — remove consecutive duplicates ---- */
static Value bi_uniq(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 1 || !args[0].is_list())
        snafu_die("uniq() takes 1 list argument");
    Value r = Value::List(args[0].list_len());
    for (size_t i = 0; i < args[0].list->size(); i++) {
        bool dup = false;
        // Check against all previously added elements
        for (size_t j = 0; j < r.list->size(); j++) {
            if ((*r.list)[j].to_string() == (*args[0].list)[i].to_string()) {
                dup = true;
                break;
            }
        }
        if (!dup) r.list_push((*args[0].list)[i]);
    }
    return r;
}

/* ---- window(list, n) — sliding window ---- */
static Value bi_window(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2 || !args[0].is_list() || !args[1].is_int())
        snafu_die("window() takes (list, int)");
    int n = static_cast<int>(args[1].ival);
    auto &lst = *args[0].list;
    if (n <= 0 || n > static_cast<int>(lst.size()))
        return Value::List(0);
    int out_len = static_cast<int>(lst.size()) - n + 1;
    Value r = Value::List(out_len);
    for (int i = 0; i < out_len; i++) {
        Value w = Value::List(n);
        for (int j = 0; j < n; j++)
            w.list_push(lst[i + j]);
        r.list_push(w);
    }
    return r;
}

/* ---- rotate(list, n) — rotate list by n positions ---- */
static Value bi_rotate(Value *args, int nargs, Scope *scope) {
    (void)scope;
    if (nargs != 2 || !args[0].is_list() || !args[1].is_int())
        snafu_die("rotate() takes (list, int)");
    auto &lst = *args[0].list;
    int len = static_cast<int>(lst.size());
    if (len == 0) return Value::List(0);
    int n = static_cast<int>(args[1].ival) % len;
    if (n < 0) n += len;
    Value r = Value::List(len);
    for (int i = 0; i < len; i++)
        r.list_push(lst[(i + n) % len]);
    return r;
}

/* ---- min_by(list, fn) / max_by(list, fn) ---- */
static Value bi_min_by(Value *args, int nargs, Scope *scope) {
    if (nargs != 2) snafu_die("min_by() takes 2 arguments");
    Value &lst = args[0];
    Value &fn  = args[1];
    if (!lst.is_list() || lst.list->empty())
        snafu_die("min_by(): first arg must be non-empty list");
    Value best = (*lst.list)[0];
    Value call_arg = best;
    Value best_key;
    if (fn.is_builtin())
        best_key = (*fn.builtin_fn)(&call_arg, 1, scope);
    else if (fn.is_fn()) {
        auto cs = make_scope(fn.fn->closure);
        if (!fn.fn->params.empty()) cs->set_local(fn.fn->params[0], call_arg);
        try { best_key = eval(fn.fn->body, cs); } catch (ReturnSignal &rs) { best_key = rs.value; }
    }
    for (size_t i = 1; i < lst.list->size(); i++) {
        call_arg = (*lst.list)[i];
        Value key;
        if (fn.is_builtin())
            key = (*fn.builtin_fn)(&call_arg, 1, scope);
        else if (fn.is_fn()) {
            auto cs = make_scope(fn.fn->closure);
            if (!fn.fn->params.empty()) cs->set_local(fn.fn->params[0], call_arg);
            try { key = eval(fn.fn->body, cs); } catch (ReturnSignal &rs) { key = rs.value; }
        }
        if (key.to_num() < best_key.to_num()) {
            best = (*lst.list)[i];
            best_key = key;
        }
    }
    return best;
}

static Value bi_max_by(Value *args, int nargs, Scope *scope) {
    if (nargs != 2) snafu_die("max_by() takes 2 arguments");
    Value &lst = args[0];
    Value &fn  = args[1];
    if (!lst.is_list() || lst.list->empty())
        snafu_die("max_by(): first arg must be non-empty list");
    Value best = (*lst.list)[0];
    Value call_arg = best;
    Value best_key;
    if (fn.is_builtin())
        best_key = (*fn.builtin_fn)(&call_arg, 1, scope);
    else if (fn.is_fn()) {
        auto cs = make_scope(fn.fn->closure);
        if (!fn.fn->params.empty()) cs->set_local(fn.fn->params[0], call_arg);
        try { best_key = eval(fn.fn->body, cs); } catch (ReturnSignal &rs) { best_key = rs.value; }
    }
    for (size_t i = 1; i < lst.list->size(); i++) {
        call_arg = (*lst.list)[i];
        Value key;
        if (fn.is_builtin())
            key = (*fn.builtin_fn)(&call_arg, 1, scope);
        else if (fn.is_fn()) {
            auto cs = make_scope(fn.fn->closure);
            if (!fn.fn->params.empty()) cs->set_local(fn.fn->params[0], call_arg);
            try { key = eval(fn.fn->body, cs); } catch (ReturnSignal &rs) { key = rs.value; }
        }
        if (key.to_num() > best_key.to_num()) {
            best = (*lst.list)[i];
            best_key = key;
        }
    }
    return best;
}

/* ================================================================== */
/*  install_prelude -- populate the global scope                       */
/* ================================================================== */

void install_prelude(std::shared_ptr<Scope> g) {
    /* constants */
    g->set_local("und",   Value::Und());
    g->set_local("true",  Value::Bool(true));
    g->set_local("false", Value::Bool(false));

    /* built-in functions */
    g->set_local("p",     Value::Builtin(bi_p));
    g->set_local("len",   Value::Builtin(bi_len));
    g->set_local("sum",   Value::Builtin(bi_sum));
    g->set_local("range", Value::Builtin(bi_range));
    g->set_local("type",  Value::Builtin(bi_type));
    g->set_local("str",   Value::Builtin(bi_str));
    g->set_local("int",   Value::Builtin(bi_int));
    g->set_local("abs",   Value::Builtin(bi_abs));
    g->set_local("sqrt",  Value::Builtin(bi_sqrt));
    g->set_local("m",     Value::Builtin(bi_m));
    g->set_local("fl",    Value::Builtin(bi_fl));
    g->set_local("flt",   Value::Builtin(bi_flt));
    g->set_local("rev",   Value::Builtin(bi_rev));
    g->set_local("join",  Value::Builtin(bi_join));
    g->set_local("min",   Value::Builtin(bi_min));
    g->set_local("max",   Value::Builtin(bi_max));
    g->set_local("push",  Value::Builtin(bi_push));
    g->set_local("pop",   Value::Builtin(bi_pop));
    g->set_local("head",  Value::Builtin(bi_head));
    g->set_local("tail",  Value::Builtin(bi_tail));
    g->set_local("keys",  Value::Builtin(bi_keys));
    g->set_local("vals",  Value::Builtin(bi_vals));
    g->set_local("throw", Value::Builtin(bi_throw));

    /* Phase 2 prelude */
    g->set_local("rdc",  Value::Builtin(bi_rdc));
    g->set_local("srt",  Value::Builtin(bi_srt));
    g->set_local("take", Value::Builtin(bi_take));
    g->set_local("drop", Value::Builtin(bi_drop));
    g->set_local("flat", Value::Builtin(bi_flat));
    g->set_local("zip",  Value::Builtin(bi_zip));
    g->set_local("en",   Value::Builtin(bi_en));
    g->set_local("chr",  Value::Builtin(bi_chr));
    g->set_local("ord",  Value::Builtin(bi_ord));
    g->set_local("D",    Value::Builtin(bi_D));
    g->set_local("R",    Value::Builtin(bi_R));
    g->set_local("T",    Value::Builtin(bi_T));
    g->set_local("to_json",   Value::Builtin(bi_to_json));
    g->set_local("from_json", Value::Builtin(bi_from_json));
    g->set_local("__channel__", Value::Builtin(bi_channel));

    /* Phase 3 prelude */
    g->set_local("ps",      Value::Builtin(bi_ps));
    g->set_local("sa",      Value::Builtin(bi_sa));
    g->set_local("restore", Value::Builtin(bi_restore));
    g->set_local("actor",   Value::Builtin(bi_actor));
    g->set_local("rand",    Value::Builtin(bi_rand));
    g->set_local("sleep",   Value::Builtin(bi_sleep));
    g->set_local("now",     Value::Builtin(bi_now));
    g->set_local("gcd",     Value::Builtin(bi_gcd));
    g->set_local("lcm",     Value::Builtin(bi_lcm));
    g->set_local("fact",    Value::Builtin(bi_fact));
    g->set_local("uniq",    Value::Builtin(bi_uniq));
    g->set_local("window",  Value::Builtin(bi_window));
    g->set_local("rotate",  Value::Builtin(bi_rotate));
    g->set_local("min_by",  Value::Builtin(bi_min_by));
    g->set_local("max_by",  Value::Builtin(bi_max_by));

    /* math constants */
    g->set_local("pi", Value::Float(3.14159265358979323846));
    g->set_local("e",  Value::Float(2.71828182845904523536));

    /* Python bridge: py.import("module") */
    {
        Value py_ns = Value::Dict();
        (*py_ns.dict)["import"] = Value::Builtin(
            [](Value *args, int nargs, Scope *) -> Value {
                if (nargs < 1 || !args[0].is_str()) {
                    snafu_die("py.import() requires a string argument");
                }
                return python_import(*args[0].sval);
            }
        );
        g->set_local("py", py_ns);
    }
}
