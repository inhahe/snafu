#ifndef SNAFU_H
#define SNAFU_H

#include <string>
#include <vector>
#include <unordered_map>
#include <memory>
#include <functional>
#include <stdexcept>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cctype>
#include <iostream>
#include <sstream>
#include <regex>
#include <variant>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <atomic>
#include <algorithm>
#include <chrono>
#include <random>
#include <numeric>

/* ------------------------------------------------------------------ */
/*  Error / signal types — SnafuError, Break, Continue, Goto           */
/*  (ReturnSignal defined after Value)                                 */
/* ------------------------------------------------------------------ */

struct SnafuError : std::runtime_error {
    std::string msg;
    SnafuError(const std::string &m) : std::runtime_error(m), msg(m) {}
};

struct BreakSignal {
    int level;
    BreakSignal(int l = 1) : level(l) {}
};

struct ContinueSignal {
    int level;
    ContinueSignal(int l = 1) : level(l) {}
};

struct GotoSignal {
    std::string label;
    GotoSignal(const std::string &l) : label(l) {}
};


/* ------------------------------------------------------------------ */
/*  Value representation                                               */
/* ------------------------------------------------------------------ */

enum ValType {
    VAL_INT, VAL_FLOAT, VAL_STR, VAL_BOOL, VAL_UND,
    VAL_LIST, VAL_DICT, VAL_FN, VAL_BUILTIN, VAL_VARIANT,
    VAL_GENERATOR, VAL_FUTURE, VAL_CHANNEL, VAL_ACTOR,
    VAL_PYOBJ
};

struct Scope;
struct ASTNode;
struct Value;
struct ActorData;

using BuiltinFn = std::function<Value(Value *args, int nargs, Scope *scope)>;

struct FnData {
    std::vector<std::string> params;
    ASTNode *body = nullptr;
    std::shared_ptr<Scope> closure;
    std::string name;
    bool may_capture = false;
    bool is_coroutine = false;
    bool is_macro = false;
};

struct VariantData {
    std::string tag;
    std::shared_ptr<Value> payload;
};

/* Forward-declare: these structs use shared_ptr<Value> to break the cycle */
struct GeneratorData;
struct FutureData;
struct ChannelData;
/* ActorData already forward-declared above */

struct Value {
    ValType type = VAL_UND;
    union {
        long long ival;
        double    fval;
        bool      bval;
    };
    // Heap-allocated data for complex types
    std::shared_ptr<std::string> sval;
    std::shared_ptr<std::vector<Value>> list;
    std::shared_ptr<std::unordered_map<std::string, Value>> dict;
    std::shared_ptr<FnData> fn;
    std::shared_ptr<BuiltinFn> builtin_fn;
    std::shared_ptr<VariantData> variant;
    std::shared_ptr<GeneratorData> generator;
    std::shared_ptr<FutureData> future;
    std::shared_ptr<ChannelData> channel;
    std::shared_ptr<ActorData> actor;
    void *pyobj = nullptr; // Opaque PyObject* for Python bridge

    // Default constructor: und
    Value() : type(VAL_UND), ival(0) {}

    // Convenience constructors
    static Value Int(long long v);
    static Value Float(double v);
    static Value Str(const std::string &s);
    static Value Bool(bool b);
    static Value Und();
    static Value List(int cap = 0);
    static Value Dict();
    static Value Fn(std::shared_ptr<FnData> fd);
    static Value Builtin(BuiltinFn f);
    static Value Variant(const std::string &tag, Value payload);
    static Value Generator(std::shared_ptr<GeneratorData> gd);
    static Value Future(std::shared_ptr<FutureData> fd);
    static Value Channel(std::shared_ptr<ChannelData> cd);
    static Value Actor(std::shared_ptr<ActorData> ad);

    // Type checks
    bool is_int()       const { return type == VAL_INT; }
    bool is_float()     const { return type == VAL_FLOAT; }
    bool is_str()       const { return type == VAL_STR; }
    bool is_bool()      const { return type == VAL_BOOL; }
    bool is_und()       const { return type == VAL_UND; }
    bool is_list()      const { return type == VAL_LIST; }
    bool is_dict()      const { return type == VAL_DICT; }
    bool is_fn()        const { return type == VAL_FN; }
    bool is_builtin()   const { return type == VAL_BUILTIN; }
    bool is_variant()   const { return type == VAL_VARIANT; }
    bool is_generator() const { return type == VAL_GENERATOR; }
    bool is_future()    const { return type == VAL_FUTURE; }
    bool is_channel()   const { return type == VAL_CHANNEL; }
    bool is_actor()     const { return type == VAL_ACTOR; }
    bool is_pyobj()     const { return type == VAL_PYOBJ; }

    bool truthy() const;
    std::string to_string() const;
    std::string repr() const;
    void print() const;

    // List helpers
    void list_push(const Value &v);
    int  list_len() const;

    // Numeric coercion
    double to_num() const;
};

/* ------------------------------------------------------------------ */
/*  ReturnSignal — must come after Value is complete                    */
/* ------------------------------------------------------------------ */

struct ReturnSignal {
    Value value;
};

struct YieldSignal {
    Value value;
};

struct EffectSignal {
    Value value;
};

/* ------------------------------------------------------------------ */
/*  GeneratorData, FutureData, ChannelData — full definitions          */
/*  (after Value is complete so we can embed Value members)            */
/* ------------------------------------------------------------------ */

struct GeneratorData {
    std::shared_ptr<std::thread> thread;
    std::mutex mtx;
    std::condition_variable cv_producer;
    std::condition_variable cv_consumer;
    Value yielded_value;
    bool value_ready = false;
    bool next_requested = false;
    bool done = false;
    bool started = false;
};

struct FutureData {
    std::shared_ptr<std::thread> thread;
    Value result;
    bool done = false;
    std::mutex mtx;
    std::condition_variable cv;
};

struct ChannelData {
    std::queue<Value> buf;
    int capacity;
    std::mutex mtx;
    std::condition_variable cv_send;
    std::condition_variable cv_recv;
    bool closed = false;
    ChannelData(int cap = 0) : capacity(cap) {}
};

/* ------------------------------------------------------------------ */
/*  Scope (unordered_map + parent chain)                               */
/* ------------------------------------------------------------------ */

/* Reactive trigger: (var_name, field, body_ast) */
struct ReactiveTrigger {
    std::string var_name;
    std::string field;
    ASTNode *body;  // non-owning; owned by AST
};

/* Actor data: thread with a message queue */
struct ActorData {
    std::shared_ptr<std::thread> thread;
    std::queue<Value> inbox;
    std::queue<Value> outbox;
    std::mutex mtx;
    std::condition_variable cv_inbox;
    std::condition_variable cv_outbox;
    bool stopped = false;
};

struct Scope : std::enable_shared_from_this<Scope> {
    std::unordered_map<std::string, Value> bindings;
    std::shared_ptr<Scope> parent;

    /* Reactive triggers — stored at the root scope */
    std::vector<ReactiveTrigger> triggers;

    /* State snapshots for time-travel */
    std::vector<std::unordered_map<std::string, Value>> snapshots;

    /* Defer stack for current block */
    std::vector<ASTNode *> defer_stack;

    Scope() = default;
    explicit Scope(std::shared_ptr<Scope> p) : parent(std::move(p)) {}

    Value get(const std::string &name) const;
    bool  has(const std::string &name) const;
    void  set(const std::string &name, const Value &v);
    void  set_local(const std::string &name, const Value &v);

    /* Get root scope (for triggers/snapshots) */
    Scope *root();
    const Scope *root() const;

    /* Deep copy all bindings in scope chain */
    std::unordered_map<std::string, Value> all_bindings() const;

    /* Fire triggers matching a variable name */
    void fire_triggers(const std::string &name, std::shared_ptr<Scope> scope_ptr);
};

std::shared_ptr<Scope> make_scope(std::shared_ptr<Scope> parent = nullptr);

/* Global trigger count — avoids walking scope chain on every set() when no triggers exist */
extern std::atomic<int> g_trigger_count;

/* ------------------------------------------------------------------ */
/*  AST node types                                                     */
/* ------------------------------------------------------------------ */

enum ASTType {
    AST_NUM, AST_FLOAT, AST_STR, AST_BOOL, AST_UND,
    AST_IDENT, AST_BINOP, AST_UNARYOP, AST_CALL,
    AST_ASSIGN, AST_IF, AST_FOR, AST_WHILE, AST_BLOCK,
    AST_FNDECL, AST_RETURN, AST_EXPRSTMT,
    AST_LIST, AST_INDEX, AST_PRINT,
    AST_BREAK, AST_CONTINUE,
    /* New features */
    AST_MATCH, AST_SUMDECL, AST_PIPE,
    AST_APL_EACH, AST_APL_REDUCE, AST_APL_SCAN,
    AST_INTERP_STR, AST_REGEX, AST_TRY, AST_DICT_LIT,
    AST_DOT_ACCESS,
    /* Phase 2 features */
    AST_YIELD, AST_EFFECT_DECL, AST_PERFORM, AST_HANDLE,
    AST_GREEN_THREAD, AST_AWAIT, AST_LABEL, AST_GOTO, AST_COMEFROM,
    AST_TERNARY, AST_WITH, AST_DESTRUCT_ASSIGN, AST_DOT_CALL,
    /* Phase 3 features */
    AST_MACRO_DECL, AST_WHERE, AST_COMPREHENSION, AST_DEFER,
    AST_QUANTIFIER, AST_REACTIVE_ON, AST_REACTIVE_OFF,
    AST_FORK
};

struct MatchArm {
    std::unique_ptr<ASTNode> pattern;
    std::unique_ptr<ASTNode> body;
};

struct ASTNode {
    ASTType type;
    int     line = 0;

    // Payload — we use a simpler approach: optional fields per node type.
    // Only the relevant fields are populated for each type.

    long long    num_val = 0;
    double       float_val = 0.0;
    std::string  str_val;
    bool         bool_val = false;

    // AST_IDENT
    std::string ident_name;

    // AST_BINOP
    std::string binop_op;
    std::unique_ptr<ASTNode> lhs, rhs;

    // AST_UNARYOP
    std::string unary_op;
    std::unique_ptr<ASTNode> operand;

    // AST_CALL
    std::unique_ptr<ASTNode> call_fn;
    std::vector<std::unique_ptr<ASTNode>> call_args;

    // AST_ASSIGN
    std::string assign_name;
    std::unique_ptr<ASTNode> assign_value;

    // AST_IF
    std::unique_ptr<ASTNode> if_cond, if_then, if_else;
    std::vector<std::unique_ptr<ASTNode>> elif_conds;
    std::vector<std::unique_ptr<ASTNode>> elif_bodies;

    // AST_FOR
    std::string for_var;
    std::unique_ptr<ASTNode> for_iter, for_body;

    // AST_WHILE
    std::unique_ptr<ASTNode> while_cond, while_body;
    bool is_until = false;

    // AST_BLOCK
    std::vector<std::unique_ptr<ASTNode>> block_stmts;

    // AST_FNDECL
    std::string fndecl_name;
    std::vector<std::string> fndecl_params;
    std::unique_ptr<ASTNode> fndecl_body;

    // AST_RETURN
    std::unique_ptr<ASTNode> ret_value;

    // AST_EXPRSTMT
    std::unique_ptr<ASTNode> expr;

    // AST_LIST / AST_DICT_LIT
    std::vector<std::unique_ptr<ASTNode>> items;
    // For dict literals: keys
    std::vector<std::unique_ptr<ASTNode>> dict_keys;

    // AST_INDEX
    std::unique_ptr<ASTNode> index_target, index_key;

    // AST_BREAK / AST_CONTINUE
    int break_level = 1;

    // AST_MATCH
    std::unique_ptr<ASTNode> match_expr;
    std::vector<MatchArm> match_arms;

    // AST_SUMDECL
    std::string sumdecl_name;
    std::vector<std::string> sumdecl_constructors;

    // AST_PIPE
    std::unique_ptr<ASTNode> pipe_lhs, pipe_rhs;

    // AST_APL_EACH / AST_APL_REDUCE / AST_APL_SCAN
    std::string apl_op;
    std::unique_ptr<ASTNode> apl_operand;

    // AST_INTERP_STR
    std::vector<std::unique_ptr<ASTNode>> interp_parts; // mix of AST_STR and expr nodes

    // AST_REGEX
    std::string regex_pattern;
    std::string regex_flags;

    // AST_TRY
    std::unique_ptr<ASTNode> try_body;
    std::string try_var;
    std::unique_ptr<ASTNode> try_handler;

    // AST_DOT_ACCESS / AST_DOT_CALL
    std::unique_ptr<ASTNode> dot_target;
    std::string dot_field;
    std::vector<std::unique_ptr<ASTNode>> dot_call_args; // for AST_DOT_CALL
    bool dot_safe = false; // ?. safe navigation

    // AST_YIELD / AST_PERFORM / AST_AWAIT
    std::unique_ptr<ASTNode> yield_value;

    // AST_HANDLE: hd { body } with { match_arms }
    std::unique_ptr<ASTNode> handle_body;
    std::vector<MatchArm> handle_arms;

    // AST_GREEN_THREAD / AST_WITH
    std::unique_ptr<ASTNode> gt_body;

    // AST_WITH: wi expr as name { body }
    std::unique_ptr<ASTNode> with_expr;
    std::string with_var;
    std::unique_ptr<ASTNode> with_body;

    // AST_LABEL / AST_GOTO / AST_COMEFROM
    std::string label_name;

    // AST_TERNARY
    std::unique_ptr<ASTNode> tern_cond, tern_true, tern_false;

    // AST_DESTRUCT_ASSIGN
    std::vector<std::string> destruct_names;
    std::unique_ptr<ASTNode> destruct_value;

    // AST_FNDECL additions for decorators
    std::vector<std::unique_ptr<ASTNode>> decorators;
    bool is_coroutine = false;
    bool is_macro = false;

    // AST_EFFECT_DECL
    std::string effect_name;
    std::vector<std::string> effect_fields;

    // AST_WHERE: expr whr { bindings }
    std::unique_ptr<ASTNode> where_expr;
    std::unique_ptr<ASTNode> where_bindings;

    // AST_COMPREHENSION: [expr for var in iter if cond]
    std::unique_ptr<ASTNode> comp_expr;
    std::string comp_var;
    std::unique_ptr<ASTNode> comp_iter;
    std::unique_ptr<ASTNode> comp_cond; // may be null

    // AST_DEFER
    std::unique_ptr<ASTNode> defer_expr;

    // AST_QUANTIFIER: some/every x in list if pred
    bool quant_is_every = false;
    std::string quant_var;
    std::unique_ptr<ASTNode> quant_iter;
    std::unique_ptr<ASTNode> quant_pred;

    // AST_REACTIVE_ON: on x.ch { body }
    std::string reactive_var;
    std::string reactive_field;
    std::unique_ptr<ASTNode> reactive_body;

    // AST_FORK: fk { body }
    std::unique_ptr<ASTNode> fork_body;

    ASTNode() : type(AST_UND), line(0) {}
    explicit ASTNode(ASTType t, int ln = 0) : type(t), line(ln) {}
};

std::unique_ptr<ASTNode> make_node(ASTType type, int line);

/* ------------------------------------------------------------------ */
/*  Lexer                                                              */
/* ------------------------------------------------------------------ */

enum TokType {
    TOK_INT, TOK_FLOAT, TOK_STR, TOK_IDENT, TOK_KW, TOK_OP,
    TOK_NEWLINE, TOK_EOF
};

struct Token {
    TokType     type;
    std::string value;
    int         line = 0;
};

using TokenList = std::vector<Token>;

TokenList lex(const std::string &src);

/* ------------------------------------------------------------------ */
/*  Parser                                                             */
/* ------------------------------------------------------------------ */

std::unique_ptr<ASTNode> parse(TokenList &tokens);

/* ------------------------------------------------------------------ */
/*  Evaluator                                                          */
/* ------------------------------------------------------------------ */

Value eval(ASTNode *node, std::shared_ptr<Scope> scope);
void  install_prelude(std::shared_ptr<Scope> global);

/* ------------------------------------------------------------------ */
/*  Entry points                                                       */
/* ------------------------------------------------------------------ */

void run_source(const std::string &src);
void run_file(const std::string &path);
void repl();

/* ------------------------------------------------------------------ */
/*  Error helper                                                       */
/* ------------------------------------------------------------------ */

[[noreturn]] void snafu_die(const char *fmt, ...);

#endif /* SNAFU_H */
