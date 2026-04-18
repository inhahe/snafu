#include "snafu.h"
#include <cstdarg>

/* ------------------------------------------------------------------ */
/*  Error helper                                                       */
/* ------------------------------------------------------------------ */

[[noreturn]] void snafu_die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "snafu error: ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    throw SnafuError("runtime error");
}

/* ------------------------------------------------------------------ */
/*  Value constructors                                                 */
/* ------------------------------------------------------------------ */

Value Value::Int(long long v) {
    Value r;
    r.type = VAL_INT;
    r.ival = v;
    return r;
}

Value Value::Float(double v) {
    Value r;
    r.type = VAL_FLOAT;
    r.fval = v;
    return r;
}

Value Value::Str(const std::string &s) {
    Value r;
    r.type = VAL_STR;
    r.sval = std::make_shared<std::string>(s);
    return r;
}

Value Value::Bool(bool b) {
    Value r;
    r.type = VAL_BOOL;
    r.bval = b;
    return r;
}

Value Value::Und() {
    Value r;
    r.type = VAL_UND;
    return r;
}

Value Value::List(int cap) {
    Value r;
    r.type = VAL_LIST;
    r.list = std::make_shared<std::vector<Value>>();
    if (cap > 0) r.list->reserve(cap);
    return r;
}

Value Value::Dict() {
    Value r;
    r.type = VAL_DICT;
    r.dict = std::make_shared<std::unordered_map<std::string, Value>>();
    return r;
}

Value Value::Fn(std::shared_ptr<FnData> fd) {
    Value r;
    r.type = VAL_FN;
    r.fn = std::move(fd);
    return r;
}

Value Value::Builtin(BuiltinFn f) {
    Value r;
    r.type = VAL_BUILTIN;
    r.builtin_fn = std::make_shared<BuiltinFn>(std::move(f));
    return r;
}

Value Value::Variant(const std::string &tag, Value payload) {
    Value r;
    r.type = VAL_VARIANT;
    r.variant = std::make_shared<VariantData>();
    r.variant->tag = tag;
    r.variant->payload = std::make_shared<Value>(std::move(payload));
    return r;
}

Value Value::Generator(std::shared_ptr<GeneratorData> gd) {
    Value r;
    r.type = VAL_GENERATOR;
    r.generator = std::move(gd);
    return r;
}

Value Value::Future(std::shared_ptr<FutureData> fd) {
    Value r;
    r.type = VAL_FUTURE;
    r.future = std::move(fd);
    return r;
}

Value Value::Channel(std::shared_ptr<ChannelData> cd) {
    Value r;
    r.type = VAL_CHANNEL;
    r.channel = std::move(cd);
    return r;
}

Value Value::Actor(std::shared_ptr<ActorData> ad) {
    Value r;
    r.type = VAL_ACTOR;
    r.actor = std::move(ad);
    return r;
}

/* ------------------------------------------------------------------ */
/*  Truthiness                                                         */
/* ------------------------------------------------------------------ */

bool Value::truthy() const {
    switch (type) {
    case VAL_UND:     return false;
    case VAL_BOOL:    return bval;
    case VAL_INT:     return ival != 0;
    case VAL_FLOAT:   return fval != 0.0;
    case VAL_STR:     return sval && !sval->empty();
    case VAL_LIST:    return list && !list->empty();
    case VAL_DICT:    return dict && !dict->empty();
    case VAL_FN:      return true;
    case VAL_BUILTIN: return true;
    case VAL_VARIANT:  return true;
    case VAL_GENERATOR: return true;
    case VAL_FUTURE:   return true;
    case VAL_CHANNEL:  return true;
    case VAL_ACTOR:    return true;
    case VAL_PYOBJ:    return pyobj != nullptr;
    }
    return false;
}

/* ------------------------------------------------------------------ */
/*  Numeric coercion                                                   */
/* ------------------------------------------------------------------ */

double Value::to_num() const {
    if (type == VAL_INT)   return static_cast<double>(ival);
    if (type == VAL_FLOAT) return fval;
    if (type == VAL_BOOL)  return bval ? 1.0 : 0.0;
    return 0.0;
}

/* ------------------------------------------------------------------ */
/*  to_string — human-readable string                                  */
/* ------------------------------------------------------------------ */

std::string Value::to_string() const {
    switch (type) {
    case VAL_INT:
        return std::to_string(ival);
    case VAL_FLOAT: {
        // Use %g style formatting
        char buf[64];
        snprintf(buf, sizeof(buf), "%g", fval);
        return std::string(buf);
    }
    case VAL_STR:
        return sval ? *sval : "";
    case VAL_BOOL:
        return bval ? "true" : "false";
    case VAL_UND:
        return "und";
    case VAL_LIST: {
        std::string out = "[";
        if (list) {
            for (size_t i = 0; i < list->size(); i++) {
                if (i > 0) out += ", ";
                out += (*list)[i].repr();
            }
        }
        out += "]";
        return out;
    }
    case VAL_DICT: {
        std::string out = "[";
        if (dict) {
            bool first = true;
            for (auto &kv : *dict) {
                if (!first) out += ", ";
                first = false;
                out += kv.first + ": " + kv.second.repr();
            }
        }
        out += "]";
        return out;
    }
    case VAL_FN:
        return "<fn " + (fn ? fn->name : "?") + ">";
    case VAL_BUILTIN:
        return "<builtin>";
    case VAL_VARIANT:
        if (variant) {
            if (variant->payload && variant->payload->type != VAL_UND)
                return variant->tag + "(" + variant->payload->repr() + ")";
            return variant->tag;
        }
        return "<variant>";
    case VAL_GENERATOR:
        return "<generator>";
    case VAL_FUTURE:
        return "<future>";
    case VAL_CHANNEL:
        return "<channel>";
    case VAL_ACTOR:
        return "<actor>";
    case VAL_PYOBJ:
        return "<pyobj>";
    }
    return "?";
}

/* ------------------------------------------------------------------ */
/*  repr — representation with quoting for strings                     */
/* ------------------------------------------------------------------ */

std::string Value::repr() const {
    if (type == VAL_STR) {
        return "\"" + (sval ? *sval : "") + "\"";
    }
    return to_string();
}

/* ------------------------------------------------------------------ */
/*  print — print without newline                                      */
/* ------------------------------------------------------------------ */

void Value::print() const {
    std::cout << to_string();
}

/* ------------------------------------------------------------------ */
/*  List helpers                                                       */
/* ------------------------------------------------------------------ */

void Value::list_push(const Value &v) {
    if (type != VAL_LIST || !list) {
        snafu_die("list_push on non-list");
    }
    list->push_back(v);
}

int Value::list_len() const {
    if (type != VAL_LIST || !list) return 0;
    return static_cast<int>(list->size());
}

/* ------------------------------------------------------------------ */
/*  AST node constructor                                               */
/* ------------------------------------------------------------------ */

std::unique_ptr<ASTNode> make_node(ASTType type, int line) {
    auto n = std::make_unique<ASTNode>(type, line);
    return n;
}
