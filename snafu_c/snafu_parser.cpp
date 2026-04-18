#include "snafu.h"

/* ------------------------------------------------------------------ */
/*  Parser state                                                       */
/* ------------------------------------------------------------------ */

struct Parser {
    TokenList &tl;
    int pos;

    Parser(TokenList &t) : tl(t), pos(0) {}

    Token &peek(int off = 0) {
        int idx = pos + off;
        if (idx >= static_cast<int>(tl.size())) idx = static_cast<int>(tl.size()) - 1;
        return tl[idx];
    }

    Token &cur() { return peek(0); }

    Token &advance() {
        Token &t = cur();
        if (t.type != TOK_EOF) pos++;
        return t;
    }

    bool check(TokType type, const char *val = nullptr) {
        Token &t = cur();
        if (t.type != type) return false;
        if (val && t.value != val) return false;
        return true;
    }

    bool match(TokType type, const char *val = nullptr) {
        if (check(type, val)) { advance(); return true; }
        return false;
    }

    Token &expect(TokType type, const char *val = nullptr) {
        if (!check(type, val)) {
            Token &t = cur();
            snafu_die("line %d: expected %s '%s', got '%s'",
                      t.line,
                      type == TOK_OP ? "op" : type == TOK_KW ? "keyword" : "token",
                      val ? val : "?",
                      t.value.c_str());
        }
        return advance();
    }

    void skip_newlines() {
        while (check(TOK_NEWLINE)) advance();
    }
};

/* ------------------------------------------------------------------ */
/*  Forward declarations                                               */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_stmt(Parser &p);
static std::unique_ptr<ASTNode> parse_expr(Parser &p, int min_prec);
static std::unique_ptr<ASTNode> parse_block(Parser &p);
static std::unique_ptr<ASTNode> parse_primary(Parser &p);
static std::unique_ptr<ASTNode> parse_unary(Parser &p);
static std::unique_ptr<ASTNode> parse_postfix(Parser &p);

/* ------------------------------------------------------------------ */
/*  Operator precedence                                                */
/* ------------------------------------------------------------------ */

static int op_prec(const std::string &op) {
    if (op == "|>")  return 10;
    if (op == "??")  return 12;
    if (op == "||")  return 20;
    if (op == "&&")  return 30;
    if (op == "|")   return 32;  // bitwise OR
    if (op == "&")   return 34;  // bitwise AND
    if (op == "==" || op == "<>")  return 40;
    if (op == "<" || op == ">" || op == "<=" || op == ">=")  return 40;
    if (op == "..")  return 50;
    if (op == "+" || op == "-")   return 60;
    if (op == "*" || op == "/" || op == "%")  return 70;
    if (op == "**")  return 80;
    return -1;
}

static bool is_right_assoc(const std::string &op) {
    return op == "**";
}

/* ------------------------------------------------------------------ */
/*  parse_params — "(name, name, ...)"                                 */
/* ------------------------------------------------------------------ */

static std::vector<std::string> parse_params(Parser &p) {
    p.expect(TOK_OP, "(");
    std::vector<std::string> params;
    if (!p.check(TOK_OP, ")")) {
        Token &t = p.cur();
        if (t.type != TOK_IDENT && t.type != TOK_KW)
            snafu_die("line %d: expected parameter name", t.line);
        params.push_back(p.advance().value);
        while (p.match(TOK_OP, ",")) {
            Token &t2 = p.cur();
            if (t2.type != TOK_IDENT && t2.type != TOK_KW)
                snafu_die("line %d: expected parameter name", t2.line);
            params.push_back(p.advance().value);
        }
    }
    p.expect(TOK_OP, ")");
    return params;
}

/* ------------------------------------------------------------------ */
/*  parse_call_args — "(expr, expr, ...)"  (already consumed '(')      */
/* ------------------------------------------------------------------ */

static std::vector<std::unique_ptr<ASTNode>> parse_call_args(Parser &p) {
    std::vector<std::unique_ptr<ASTNode>> args;
    if (!p.check(TOK_OP, ")")) {
        args.push_back(parse_expr(p, 0));
        while (p.match(TOK_OP, ",")) {
            args.push_back(parse_expr(p, 0));
        }
    }
    p.expect(TOK_OP, ")");
    return args;
}

/* ------------------------------------------------------------------ */
/*  parse_block  —  "{ stmts }"                                        */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_block(Parser &p) {
    int line = p.cur().line;
    p.expect(TOK_OP, "{");
    auto nd = make_node(AST_BLOCK, line);
    p.skip_newlines();
    while (!p.check(TOK_OP, "}") && p.cur().type != TOK_EOF) {
        auto s = parse_stmt(p);
        if (s) nd->block_stmts.push_back(std::move(s));
        p.skip_newlines();
    }
    p.expect(TOK_OP, "}");
    return nd;
}

/* ------------------------------------------------------------------ */
/*  parse_interp_string — handle "${expr}" interpolation               */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_interp_string(const std::string &raw, int line) {
    // raw is the content after removing \x02 prefix
    auto nd = make_node(AST_INTERP_STR, line);
    std::string buf;
    size_t i = 0;
    while (i < raw.size()) {
        if (raw[i] == '$' && i + 1 < raw.size() && raw[i+1] == '{') {
            // Emit accumulated literal
            if (!buf.empty()) {
                auto lit = make_node(AST_STR, line);
                lit->str_val = buf;
                nd->interp_parts.push_back(std::move(lit));
                buf.clear();
            }
            // Find matching }
            i += 2; // skip ${
            int depth = 1;
            std::string expr_str;
            while (i < raw.size() && depth > 0) {
                if (raw[i] == '{') depth++;
                else if (raw[i] == '}') {
                    depth--;
                    if (depth == 0) { i++; break; }
                }
                expr_str += raw[i];
                i++;
            }
            // Lex and parse the expression
            TokenList etl = lex(expr_str);
            auto expr = parse(etl);
            // If it's a block with one statement, unwrap
            if (expr->type == AST_BLOCK && expr->block_stmts.size() == 1) {
                auto &stmt = expr->block_stmts[0];
                if (stmt->type == AST_EXPRSTMT) {
                    nd->interp_parts.push_back(std::move(stmt->expr));
                } else {
                    nd->interp_parts.push_back(std::move(stmt));
                }
            } else {
                nd->interp_parts.push_back(std::move(expr));
            }
        } else {
            buf += raw[i];
            i++;
        }
    }
    if (!buf.empty()) {
        auto lit = make_node(AST_STR, line);
        lit->str_val = buf;
        nd->interp_parts.push_back(std::move(lit));
    }
    return nd;
}

/* ------------------------------------------------------------------ */
/*  parse_primary                                                      */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_primary(Parser &p) {
    Token &t = p.cur();

    /* APL prefix operators: +/ +\ +. -/ -\ -. */ /* */ // fix broken highlighting
    if (t.type == TOK_OP) {
        std::string v = t.value;
        ASTType apl_type = AST_UND;
        std::string apl_base_op;
        if (v.size() == 2) {
            char base = v[0];
            char mod = v[1];
            if ((base == '+' || base == '-' || base == '*') &&
                (mod == '/' || mod == '\\' || mod == '.')) {
                apl_base_op = std::string(1, base);
                if (mod == '/') apl_type = AST_APL_REDUCE;
                else if (mod == '\\') apl_type = AST_APL_SCAN;
                else apl_type = AST_APL_EACH;
            }
        }
        if (apl_type != AST_UND) {
            p.advance();
            auto operand = parse_unary(p);
            auto nd = make_node(apl_type, t.line);
            nd->apl_op = apl_base_op;
            nd->apl_operand = std::move(operand);
            return nd;
        }
    }

    /* number */
    if (t.type == TOK_INT) {
        p.advance();
        auto n = make_node(AST_NUM, t.line);
        n->num_val = atoll(t.value.c_str());
        return n;
    }
    if (t.type == TOK_FLOAT) {
        p.advance();
        auto n = make_node(AST_FLOAT, t.line);
        n->float_val = atof(t.value.c_str());
        return n;
    }

    /* string (possibly interpolated or regex) */
    if (t.type == TOK_STR) {
        p.advance();
        // Check for regex marker
        if (t.value.size() > 1 && t.value[0] == '\x01' && t.value.substr(1, 6) == "REGEX:") {
            std::string rest = t.value.substr(7);
            size_t colon = rest.rfind(':');
            auto n = make_node(AST_REGEX, t.line);
            if (colon != std::string::npos) {
                n->regex_pattern = rest.substr(0, colon);
                n->regex_flags = rest.substr(colon + 1);
            } else {
                n->regex_pattern = rest;
            }
            return n;
        }
        // Check for interpolation marker
        if (!t.value.empty() && t.value[0] == '\x02') {
            return parse_interp_string(t.value.substr(1), t.line);
        }
        auto n = make_node(AST_STR, t.line);
        n->str_val = t.value;
        return n;
    }

    /* keyword literals */
    if (t.type == TOK_KW) {
        if (t.value == "true") {
            p.advance();
            auto n = make_node(AST_BOOL, t.line);
            n->bool_val = true;
            return n;
        }
        if (t.value == "false") {
            p.advance();
            auto n = make_node(AST_BOOL, t.line);
            n->bool_val = false;
            return n;
        }
        if (t.value == "und") {
            p.advance();
            return make_node(AST_UND, t.line);
        }

        /* if as expression */
        if (t.value == "if")
            return parse_stmt(p);

        /* mt (match) as expression */
        if (t.value == "mt")
            return parse_stmt(p);

        /* f (anonymous fn) */
        if (t.value == "f") {
            Token &nxt = p.peek(1);
            bool is_fn_lit = false;
            if (nxt.type == TOK_OP && (nxt.value == "{" || nxt.value == "("))
                is_fn_lit = true;
            if (is_fn_lit) {
                p.advance(); // consume 'f'
                int line = t.line;
                std::vector<std::string> params;
                if (p.check(TOK_OP, "("))
                    params = parse_params(p);
                auto body = parse_block(p);
                auto n = make_node(AST_FNDECL, line);
                n->fndecl_name = "<lambda>";
                n->fndecl_params = std::move(params);
                n->fndecl_body = std::move(body);
                return n;
            }
        }

        /* 'r' as return */
        if (t.value == "r") {
            Token &nxt = p.peek(1);
            if (nxt.type != TOK_OP || nxt.value != "=") {
                p.advance();
                auto n = make_node(AST_RETURN, t.line);
                if (p.cur().type != TOK_NEWLINE &&
                    p.cur().type != TOK_EOF &&
                    !(p.cur().type == TOK_OP && p.cur().value == "}")) {
                    n->ret_value = parse_expr(p, 0);
                }
                return n;
            }
        }

        /* gt { body } — green thread as expression */
        if (t.value == "gt") {
            Token &nxt = p.peek(1);
            if (nxt.type == TOK_OP && nxt.value == "{") {
                return parse_stmt(p);
            }
        }

        /* aw expr — await as expression */
        if (t.value == "aw") {
            Token &nxt = p.peek(1);
            // aw should be followed by an expression, not an assignment
            if (nxt.type != TOK_OP || nxt.value != "=") {
                return parse_stmt(p);
            }
        }

        /* hd { body } wi { arms } — handle as expression */
        if (t.value == "hd") {
            Token &nxt = p.peek(1);
            if (nxt.type == TOK_OP && nxt.value == "{") {
                return parse_stmt(p);
            }
        }

        /* ch(n) — channel creation as expression */
        if (t.value == "ch") {
            Token &nxt = p.peek(1);
            if (nxt.type == TOK_OP && nxt.value == "(") {
                p.advance(); // consume ch
                p.advance(); // consume (
                auto cap = parse_expr(p, 0);
                p.expect(TOK_OP, ")");
                // Return a call to the builtin ch function
                auto ident_node = make_node(AST_IDENT, t.line);
                ident_node->ident_name = "__channel__";
                auto c = make_node(AST_CALL, t.line);
                c->call_fn = std::move(ident_node);
                c->call_args.push_back(std::move(cap));
                return c;
            }
        }

        /* fk { body } — universe fork as expression */
        if (t.value == "fk") {
            Token &nxt = p.peek(1);
            if (nxt.type == TOK_OP && nxt.value == "{") {
                return parse_stmt(p);
            }
        }

        /* some / every as expression */
        if (t.value == "some" || t.value == "every") {
            return parse_stmt(p);
        }

        /* soft keywords as identifiers */
        if (t.value == "r" || t.value == "f" || t.value == "in" ||
            t.value == "not" || t.value == "is" ||
            t.value == "as" || t.value == "y" || t.value == "ef" ||
            t.value == "pf" || t.value == "hd" || t.value == "wi" ||
            t.value == "gt" || t.value == "aw" || t.value == "ch" ||
            t.value == "lbl" || t.value == "goto" || t.value == "cf" ||
            t.value == "ct" || t.value == "mc" || t.value == "whr" ||
            t.value == "defer" || t.value == "some" || t.value == "every" ||
            t.value == "on" || t.value == "of" || t.value == "fk") {
            p.advance();
            auto n = make_node(AST_IDENT, t.line);
            n->ident_name = t.value;
            return n;
        }
    }

    /* identifier */
    if (t.type == TOK_IDENT) {
        p.advance();
        auto n = make_node(AST_IDENT, t.line);
        n->ident_name = t.value;
        return n;
    }

    /* wildcard _ in pattern context (treated as ident) */
    if (t.type == TOK_OP && t.value == "_") {
        p.advance();
        auto n = make_node(AST_IDENT, t.line);
        n->ident_name = "_";
        return n;
    }

    /* parenthesized expression */
    if (t.type == TOK_OP && t.value == "(") {
        p.advance();
        auto e = parse_expr(p, 0);
        p.expect(TOK_OP, ")");
        return e;
    }

    /* list literal [a, b, c] or dict literal [k: v, ...] */
    if (t.type == TOK_OP && t.value == "[") {
        p.advance();
        p.skip_newlines();

        // Check for dict: peek ahead to see if second token is ':'
        bool is_dict = false;
        if (!p.check(TOK_OP, "]")) {
            // Save position
            int save = p.pos;
            // Try to parse one expression and see if ':' follows
            // Simple heuristic: if next non-newline is ident/str followed by ':'
            if ((p.cur().type == TOK_IDENT || p.cur().type == TOK_STR ||
                 p.cur().type == TOK_KW) &&
                p.peek(1).type == TOK_OP && p.peek(1).value == ":") {
                is_dict = true;
            }
            p.pos = save;
        }

        if (is_dict) {
            auto nd = make_node(AST_DICT_LIT, t.line);
            while (!p.check(TOK_OP, "]") && p.cur().type != TOK_EOF) {
                auto key = parse_expr(p, 0);
                p.expect(TOK_OP, ":");
                auto val = parse_expr(p, 0);
                nd->dict_keys.push_back(std::move(key));
                nd->items.push_back(std::move(val));
                p.skip_newlines();
                p.match(TOK_OP, ",");
                p.skip_newlines();
            }
            p.expect(TOK_OP, "]");
            return nd;
        }

        /* Empty list */
        if (p.check(TOK_OP, "]")) {
            p.advance();
            return make_node(AST_LIST, t.line);
        }

        /* Parse first expression, then check for comprehension */
        auto first_expr = parse_expr(p, 0);
        p.skip_newlines();

        /* Comprehension: [expr for x in iter if cond] */
        if (p.check(TOK_KW, "for")) {
            p.advance(); // consume 'for'
            Token &vt = p.cur();
            if (vt.type != TOK_IDENT && vt.type != TOK_KW)
                snafu_die("line %d: expected variable after 'for' in comprehension", vt.line);
            std::string comp_var = p.advance().value;
            p.expect(TOK_KW, "in");
            auto iter_expr = parse_expr(p, 0);
            std::unique_ptr<ASTNode> cond_expr;
            p.skip_newlines();
            if (p.check(TOK_KW, "if")) {
                p.advance(); // consume 'if'
                cond_expr = parse_expr(p, 0);
            }
            p.skip_newlines();
            p.expect(TOK_OP, "]");
            auto nd = make_node(AST_COMPREHENSION, t.line);
            nd->comp_expr = std::move(first_expr);
            nd->comp_var = comp_var;
            nd->comp_iter = std::move(iter_expr);
            nd->comp_cond = std::move(cond_expr);
            return nd;
        }

        auto nd = make_node(AST_LIST, t.line);
        nd->items.push_back(std::move(first_expr));
        p.match(TOK_OP, ",");
        p.skip_newlines();
        while (!p.check(TOK_OP, "]") && p.cur().type != TOK_EOF) {
            nd->items.push_back(parse_expr(p, 0));
            p.skip_newlines();
            p.match(TOK_OP, ",");
            p.skip_newlines();
        }
        p.expect(TOK_OP, "]");
        return nd;
    }

    /* block as expression { stmts } */
    if (t.type == TOK_OP && t.value == "{") {
        return parse_block(p);
    }

    snafu_die("line %d: unexpected token '%s' in expression",
              t.line, t.value.c_str());
    return nullptr; /* unreachable */
}

/* ------------------------------------------------------------------ */
/*  parse_postfix — calls, indexing, dot access                        */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_postfix(Parser &p) {
    auto expr = parse_primary(p);
    while (true) {
        Token &t = p.cur();
        if (t.type == TOK_OP && t.value == "(") {
            p.advance(); // consume (
            auto args = parse_call_args(p);
            auto c = make_node(AST_CALL, t.line);
            c->call_fn = std::move(expr);
            c->call_args = std::move(args);
            expr = std::move(c);
        } else if (t.type == TOK_OP && t.value == "[") {
            p.advance();
            auto key = parse_expr(p, 0);
            p.expect(TOK_OP, "]");
            auto idx = make_node(AST_INDEX, t.line);
            idx->index_target = std::move(expr);
            idx->index_key = std::move(key);
            expr = std::move(idx);
        } else if (t.type == TOK_OP && (t.value == "." || t.value == "?.")) {
            bool safe_nav = (t.value == "?.");
            p.advance();
            Token &field = p.cur();
            if (field.type != TOK_IDENT && field.type != TOK_KW)
                snafu_die("line %d: expected field name after '.'", field.line);
            std::string fname = p.advance().value;
            // Check if it's a method call: .field(args)
            if (p.check(TOK_OP, "(")) {
                p.advance(); // consume (
                auto dc = make_node(AST_DOT_CALL, t.line);
                dc->dot_target = std::move(expr);
                dc->dot_field = fname;
                dc->dot_safe = safe_nav;
                if (!p.check(TOK_OP, ")")) {
                    dc->dot_call_args.push_back(parse_expr(p, 0));
                    while (p.match(TOK_OP, ",")) {
                        dc->dot_call_args.push_back(parse_expr(p, 0));
                    }
                }
                p.expect(TOK_OP, ")");
                expr = std::move(dc);
            } else {
                auto dot = make_node(AST_DOT_ACCESS, t.line);
                dot->dot_target = std::move(expr);
                dot->dot_field = fname;
                dot->dot_safe = safe_nav;
                expr = std::move(dot);
            }
        } else {
            break;
        }
    }
    return expr;
}

/* ------------------------------------------------------------------ */
/*  parse_unary                                                        */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_unary(Parser &p) {
    Token &t = p.cur();
    if (t.type == TOK_OP &&
        (t.value == "-" || t.value == "!" || t.value == "+")) {
        p.advance();
        auto operand = parse_unary(p);
        auto n = make_node(AST_UNARYOP, t.line);
        n->unary_op = t.value;
        n->operand = std::move(operand);
        return n;
    }
    return parse_postfix(p);
}

/* ------------------------------------------------------------------ */
/*  parse_expr — Pratt precedence climbing                             */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_expr(Parser &p, int min_prec) {
    auto left = parse_unary(p);
    while (true) {
        Token &t = p.cur();
        if (t.type != TOK_OP) break;
        int prec = op_prec(t.value);
        if (prec < 0 || prec < min_prec) break;
        std::string op = t.value;
        p.advance();

        if (op == "|>") {
            // Pipeline: a |> f  =>  f(a)
            auto right = parse_expr(p, prec + 1);
            auto pipe = make_node(AST_PIPE, t.line);
            pipe->pipe_lhs = std::move(left);
            pipe->pipe_rhs = std::move(right);
            left = std::move(pipe);
        } else {
            int next_prec = is_right_assoc(op) ? prec : prec + 1;
            auto right = parse_expr(p, next_prec);
            auto bin = make_node(AST_BINOP, t.line);
            bin->binop_op = op;
            bin->lhs = std::move(left);
            bin->rhs = std::move(right);
            left = std::move(bin);
        }
    }
    /* Ternary: cond ? a : b */
    if (p.check(TOK_OP, "?") && min_prec <= 5) {
        int line = p.cur().line;
        p.advance(); // consume ?
        auto true_expr = parse_expr(p, 0);
        p.expect(TOK_OP, ":");
        auto false_expr = parse_expr(p, 5);
        auto n = make_node(AST_TERNARY, line);
        n->tern_cond = std::move(left);
        n->tern_true = std::move(true_expr);
        n->tern_false = std::move(false_expr);
        left = std::move(n);
    }
    /* Where clause: expr whr { bindings } */
    if (p.check(TOK_KW, "whr") && min_prec <= 5) {
        int line = p.cur().line;
        p.advance(); // consume 'whr'
        auto bindings = parse_block(p);
        auto n = make_node(AST_WHERE, line);
        n->where_expr = std::move(left);
        n->where_bindings = std::move(bindings);
        left = std::move(n);
    }
    return left;
}

/* ------------------------------------------------------------------ */
/*  parse_fn_body  —  { ... } or = expr                                */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_fn_body(Parser &p) {
    if (p.check(TOK_OP, "{"))
        return parse_block(p);
    if (p.match(TOK_OP, "=")) {
        auto e = parse_expr(p, 0);
        auto es = make_node(AST_EXPRSTMT, e->line);
        int line = e->line;
        es->expr = std::move(e);
        auto b = make_node(AST_BLOCK, line);
        b->block_stmts.push_back(std::move(es));
        return b;
    }
    snafu_die("line %d: expected fn body '{' or '='", p.cur().line);
    return nullptr;
}

/* ------------------------------------------------------------------ */
/*  parse_match_pattern                                                */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_match_pattern(Parser &p) {
    // Patterns: literal (int, float, str, bool), _, variable, list pattern, Variant(pat)
    Token &t = p.cur();

    if (t.type == TOK_OP && t.value == "_") {
        p.advance();
        auto n = make_node(AST_IDENT, t.line);
        n->ident_name = "_";
        return n;
    }

    if (t.type == TOK_INT) {
        p.advance();
        auto n = make_node(AST_NUM, t.line);
        n->num_val = atoll(t.value.c_str());
        return n;
    }

    if (t.type == TOK_FLOAT) {
        p.advance();
        auto n = make_node(AST_FLOAT, t.line);
        n->float_val = atof(t.value.c_str());
        return n;
    }

    if (t.type == TOK_STR) {
        p.advance();
        auto n = make_node(AST_STR, t.line);
        n->str_val = t.value;
        return n;
    }

    if (t.type == TOK_KW && (t.value == "true" || t.value == "false")) {
        p.advance();
        auto n = make_node(AST_BOOL, t.line);
        n->bool_val = (t.value == "true");
        return n;
    }

    if (t.type == TOK_OP && t.value == "[") {
        p.advance();
        auto lst = make_node(AST_LIST, t.line);
        p.skip_newlines();
        while (!p.check(TOK_OP, "]") && p.cur().type != TOK_EOF) {
            lst->items.push_back(parse_match_pattern(p));
            p.skip_newlines();
            p.match(TOK_OP, ",");
            p.skip_newlines();
        }
        p.expect(TOK_OP, "]");
        return lst;
    }

    // Identifier (variable binding) or variant constructor
    if (t.type == TOK_IDENT || t.type == TOK_KW) {
        p.advance();
        // Check if it's a variant constructor: Name(pattern)
        if (p.check(TOK_OP, "(")) {
            std::string tag = t.value;
            p.advance(); // consume (
            auto inner = parse_match_pattern(p);
            p.expect(TOK_OP, ")");
            // Encode as a CALL-like node with tag as ident
            auto n = make_node(AST_CALL, t.line);
            auto ident = make_node(AST_IDENT, t.line);
            ident->ident_name = tag;
            n->call_fn = std::move(ident);
            n->call_args.push_back(std::move(inner));
            return n;
        }
        auto n = make_node(AST_IDENT, t.line);
        n->ident_name = t.value;
        return n;
    }

    // Negative number pattern
    if (t.type == TOK_OP && t.value == "-") {
        p.advance();
        auto inner = parse_match_pattern(p);
        auto n = make_node(AST_UNARYOP, t.line);
        n->unary_op = "-";
        n->operand = std::move(inner);
        return n;
    }

    snafu_die("line %d: unexpected token '%s' in match pattern", t.line, t.value.c_str());
    return nullptr;
}

/* ------------------------------------------------------------------ */
/*  parse_stmt                                                         */
/* ------------------------------------------------------------------ */

static std::unique_ptr<ASTNode> parse_stmt(Parser &p) {
    Token &t = p.cur();

    /* @decorator df name(params) { body } */
    if (t.type == TOK_OP && t.value == "@") {
        int line = t.line;
        std::vector<std::unique_ptr<ASTNode>> decorators;
        while (p.check(TOK_OP, "@")) {
            p.advance(); // consume @
            decorators.push_back(parse_expr(p, 0));
            p.skip_newlines();
        }
        // Now expect df or ct
        auto fn_node = parse_stmt(p);
        if (fn_node->type != AST_FNDECL)
            snafu_die("line %d: decorator must precede df/ct", line);
        fn_node->decorators = std::move(decorators);
        return fn_node;
    }

    /* df name(params) { body } */
    if (t.type == TOK_KW && t.value == "df") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected function name", name_tok.line);
        std::string name = p.advance().value;
        auto params = parse_params(p);
        auto body = parse_fn_body(p);
        auto n = make_node(AST_FNDECL, line);
        n->fndecl_name = name;
        n->fndecl_params = std::move(params);
        n->fndecl_body = std::move(body);
        return n;
    }

    /* ct name(params) { body } — coroutine declaration */
    if (t.type == TOK_KW && t.value == "ct") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected coroutine name", name_tok.line);
        std::string name = p.advance().value;
        auto params = parse_params(p);
        auto body = parse_fn_body(p);
        auto n = make_node(AST_FNDECL, line);
        n->fndecl_name = name;
        n->fndecl_params = std::move(params);
        n->fndecl_body = std::move(body);
        n->is_coroutine = true;
        return n;
    }

    /* y expr — yield (but not if followed by =, ~=, :=) */
    if (t.type == TOK_KW && t.value == "y") {
        Token &nxt = p.peek(1);
        if (!(nxt.type == TOK_OP && (nxt.value == "=" || nxt.value == "~=" || nxt.value == ":="))) {
            p.advance();
            int line = t.line;
            auto n = make_node(AST_YIELD, line);
            if (p.cur().type != TOK_NEWLINE &&
                p.cur().type != TOK_EOF &&
                !(p.cur().type == TOK_OP && p.cur().value == "}")) {
                n->yield_value = parse_expr(p, 0);
            }
            return n;
        }
    }

    /* ef Name(fields) — effect declaration */
    if (t.type == TOK_KW && t.value == "ef") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT)
            snafu_die("line %d: expected effect name", name_tok.line);
        auto n = make_node(AST_EFFECT_DECL, line);
        n->effect_name = p.advance().value;
        if (p.check(TOK_OP, "(")) {
            p.advance();
            while (!p.check(TOK_OP, ")") && p.cur().type != TOK_EOF) {
                Token &ft = p.cur();
                if (ft.type != TOK_IDENT && ft.type != TOK_KW)
                    snafu_die("line %d: expected field name", ft.line);
                n->effect_fields.push_back(p.advance().value);
                p.match(TOK_OP, ",");
            }
            p.expect(TOK_OP, ")");
        }
        return n;
    }

    /* pf expr — perform effect */
    if (t.type == TOK_KW && t.value == "pf") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_PERFORM, line);
        n->yield_value = parse_expr(p, 0);
        return n;
    }

    /* hd { body } wi { match_arms } — handle */
    if (t.type == TOK_KW && t.value == "hd") {
        p.advance();
        int line = t.line;
        auto body = parse_block(p);
        p.skip_newlines();
        p.expect(TOK_KW, "wi");
        p.expect(TOK_OP, "{");
        auto n = make_node(AST_HANDLE, line);
        n->handle_body = std::move(body);
        p.skip_newlines();
        while (!p.check(TOK_OP, "}") && p.cur().type != TOK_EOF) {
            MatchArm arm;
            arm.pattern = parse_match_pattern(p);
            p.expect(TOK_OP, "->");
            if (p.check(TOK_OP, "{")) {
                arm.body = parse_block(p);
            } else {
                arm.body = parse_expr(p, 0);
            }
            n->handle_arms.push_back(std::move(arm));
            p.skip_newlines();
            p.match(TOK_OP, ",");
            p.skip_newlines();
        }
        p.expect(TOK_OP, "}");
        return n;
    }

    /* gt { body } — green thread */
    if (t.type == TOK_KW && t.value == "gt") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_GREEN_THREAD, line);
        n->gt_body = parse_block(p);
        return n;
    }

    /* aw expr — await */
    if (t.type == TOK_KW && t.value == "aw") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_AWAIT, line);
        n->yield_value = parse_expr(p, 0);
        return n;
    }

    /* lbl name — label */
    if (t.type == TOK_KW && t.value == "lbl") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected label name", name_tok.line);
        auto n = make_node(AST_LABEL, line);
        n->label_name = p.advance().value;
        return n;
    }

    /* goto name */
    if (t.type == TOK_KW && t.value == "goto") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected label name after goto", name_tok.line);
        auto n = make_node(AST_GOTO, line);
        n->label_name = p.advance().value;
        return n;
    }

    /* mc name(params) { body } — macro declaration */
    if (t.type == TOK_KW && t.value == "mc") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected macro name", name_tok.line);
        std::string name = p.advance().value;
        auto params = parse_params(p);
        auto body = parse_fn_body(p);
        auto n = make_node(AST_FNDECL, line);
        n->fndecl_name = name;
        n->fndecl_params = std::move(params);
        n->fndecl_body = std::move(body);
        n->is_macro = true;
        return n;
    }

    /* defer expr — defer execution to block exit */
    if (t.type == TOK_KW && t.value == "defer") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_DEFER, line);
        n->defer_expr = parse_expr(p, 0);
        return n;
    }

    /* some x in list if pred / every x in list if pred */
    if (t.type == TOK_KW && (t.value == "some" || t.value == "every")) {
        bool is_every = (t.value == "every");
        p.advance();
        int line = t.line;
        Token &vt = p.cur();
        if (vt.type != TOK_IDENT && vt.type != TOK_KW)
            snafu_die("line %d: expected variable after some/every", vt.line);
        std::string var = p.advance().value;
        p.expect(TOK_KW, "in");
        auto iter = parse_expr(p, 0);
        p.expect(TOK_KW, "if");
        auto pred = parse_expr(p, 0);
        auto n = make_node(AST_QUANTIFIER, line);
        n->quant_is_every = is_every;
        n->quant_var = var;
        n->quant_iter = std::move(iter);
        n->quant_pred = std::move(pred);
        return n;
    }

    /* on x.field { body } — reactive trigger */
    if (t.type == TOK_KW && t.value == "on") {
        Token &nxt = p.peek(1);
        // Must be: on ident.field { body }
        if (nxt.type == TOK_IDENT || nxt.type == TOK_KW) {
            int save = p.pos;
            p.advance(); // consume 'on'
            int line = t.line;
            Token &var_tok = p.cur();
            std::string var = p.advance().value;
            if (p.check(TOK_OP, ".")) {
                p.advance(); // consume '.'
                Token &field_tok = p.cur();
                if (field_tok.type != TOK_IDENT && field_tok.type != TOK_KW)
                    snafu_die("line %d: expected field name after '.'", field_tok.line);
                std::string field = p.advance().value;
                auto body = parse_block(p);
                auto n = make_node(AST_REACTIVE_ON, line);
                n->reactive_var = var;
                n->reactive_field = field;
                n->reactive_body = std::move(body);
                return n;
            }
            // Not a reactive trigger, rewind
            p.pos = save;
        }
    }

    /* of x.field — remove reactive trigger */
    if (t.type == TOK_KW && t.value == "of") {
        Token &nxt = p.peek(1);
        if (nxt.type == TOK_IDENT || nxt.type == TOK_KW) {
            int save = p.pos;
            p.advance(); // consume 'of'
            int line = t.line;
            std::string var = p.advance().value;
            if (p.check(TOK_OP, ".")) {
                p.advance(); // consume '.'
                Token &field_tok = p.cur();
                if (field_tok.type != TOK_IDENT && field_tok.type != TOK_KW)
                    snafu_die("line %d: expected field name after '.'", field_tok.line);
                std::string field = p.advance().value;
                auto n = make_node(AST_REACTIVE_OFF, line);
                n->reactive_var = var;
                n->reactive_field = field;
                return n;
            }
            p.pos = save;
        }
    }

    /* fk { body } — universe fork */
    if (t.type == TOK_KW && t.value == "fk") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_FORK, line);
        n->fork_body = parse_block(p);
        return n;
    }

    /* cf name — comefrom */
    if (t.type == TOK_KW && t.value == "cf") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT && name_tok.type != TOK_KW)
            snafu_die("line %d: expected label name after cf", name_tok.line);
        auto n = make_node(AST_COMEFROM, line);
        n->label_name = p.advance().value;
        return n;
    }

    /* wi expr as name { body } — with/context manager */
    if (t.type == TOK_KW && t.value == "wi") {
        p.advance();
        int line = t.line;
        auto n = make_node(AST_WITH, line);
        n->with_expr = parse_expr(p, 0);
        if (p.match(TOK_KW, "as")) {
            Token &vt = p.cur();
            if (vt.type != TOK_IDENT && vt.type != TOK_KW)
                snafu_die("line %d: expected variable after 'as'", vt.line);
            n->with_var = p.advance().value;
        }
        n->with_body = parse_block(p);
        return n;
    }

    /* ty Name = Con1 | Con2  (sum type declaration) */
    if (t.type == TOK_KW && t.value == "ty") {
        p.advance();
        int line = t.line;
        Token &name_tok = p.cur();
        if (name_tok.type != TOK_IDENT)
            snafu_die("line %d: expected type name after 'ty'", name_tok.line);
        std::string name = p.advance().value;
        p.expect(TOK_OP, "=");
        auto nd = make_node(AST_SUMDECL, line);
        nd->sumdecl_name = name;
        // Parse constructors separated by |
        Token &ct = p.cur();
        if (ct.type != TOK_IDENT)
            snafu_die("line %d: expected constructor name", ct.line);
        nd->sumdecl_constructors.push_back(p.advance().value);
        while (p.cur().type == TOK_OP && p.cur().value == "|") {
            // This is "||" tokenized — but we actually want single "|".
            // Since our lexer doesn't have a single "|", we use a workaround:
            // we won't use | as separator; instead we use comma
            break;
        }
        // Also accept comma-separated constructors
        while (p.match(TOK_OP, ",")) {
            Token &c2 = p.cur();
            if (c2.type != TOK_IDENT)
                snafu_die("line %d: expected constructor name", c2.line);
            nd->sumdecl_constructors.push_back(p.advance().value);
        }
        return nd;
    }

    /* if cond { then } eli cond { then } el { else } */
    if (t.type == TOK_KW && t.value == "if") {
        p.advance();
        int line = t.line;
        auto cond = parse_expr(p, 0);
        auto then_b = parse_block(p);

        auto nd = make_node(AST_IF, line);
        nd->if_cond = std::move(cond);
        nd->if_then = std::move(then_b);

        while (true) {
            int save = p.pos;
            p.skip_newlines();
            if (p.check(TOK_KW, "eli")) {
                p.advance();
                nd->elif_conds.push_back(parse_expr(p, 0));
                nd->elif_bodies.push_back(parse_block(p));
            } else {
                p.pos = save;
                break;
            }
        }

        int save = p.pos;
        p.skip_newlines();
        if (p.match(TOK_KW, "el")) {
            nd->if_else = parse_block(p);
        } else {
            p.pos = save;
        }

        return nd;
    }

    /* mt expr { pattern -> body, ... }  (match) */
    if (t.type == TOK_KW && t.value == "mt") {
        p.advance();
        int line = t.line;
        auto expr = parse_expr(p, 0);
        p.expect(TOK_OP, "{");
        auto nd = make_node(AST_MATCH, line);
        nd->match_expr = std::move(expr);
        p.skip_newlines();
        while (!p.check(TOK_OP, "}") && p.cur().type != TOK_EOF) {
            MatchArm arm;
            arm.pattern = parse_match_pattern(p);
            p.expect(TOK_OP, "->");
            // Body: can be a single expression or a block
            if (p.check(TOK_OP, "{")) {
                arm.body = parse_block(p);
            } else {
                arm.body = parse_expr(p, 0);
            }
            nd->match_arms.push_back(std::move(arm));
            p.skip_newlines();
            p.match(TOK_OP, ",");
            p.skip_newlines();
        }
        p.expect(TOK_OP, "}");
        return nd;
    }

    /* try { body } exc var { handler } */
    if (t.type == TOK_KW && t.value == "try") {
        p.advance();
        int line = t.line;
        auto body = parse_block(p);
        p.skip_newlines();
        p.expect(TOK_KW, "exc");
        std::string var_name;
        if (p.cur().type == TOK_IDENT) {
            var_name = p.advance().value;
        }
        auto handler = parse_block(p);
        auto nd = make_node(AST_TRY, line);
        nd->try_body = std::move(body);
        nd->try_var = var_name;
        nd->try_handler = std::move(handler);
        return nd;
    }

    /* for var in iter { body } */
    if (t.type == TOK_KW && t.value == "for") {
        p.advance();
        int line = t.line;
        Token &vt = p.cur();
        if (vt.type != TOK_IDENT && vt.type != TOK_KW)
            snafu_die("line %d: expected variable after 'for'", vt.line);
        std::string var = p.advance().value;
        p.expect(TOK_KW, "in");
        auto iter = parse_expr(p, 0);
        auto body = parse_block(p);
        auto nd = make_node(AST_FOR, line);
        nd->for_var = var;
        nd->for_iter = std::move(iter);
        nd->for_body = std::move(body);
        return nd;
    }

    /* wh cond { body }  or  un cond { body } */
    if (t.type == TOK_KW && (t.value == "wh" || t.value == "un")) {
        bool is_until = (t.value == "un");
        p.advance();
        int line = t.line;
        auto cond = parse_expr(p, 0);
        auto body = parse_block(p);
        auto nd = make_node(AST_WHILE, line);
        nd->while_cond = std::move(cond);
        nd->while_body = std::move(body);
        nd->is_until = is_until;
        return nd;
    }

    /* lp { body }   (infinite loop) */
    if (t.type == TOK_KW && t.value == "lp") {
        p.advance();
        int line = t.line;
        auto body = parse_block(p);
        auto nd = make_node(AST_WHILE, line);
        auto c = make_node(AST_BOOL, line);
        c->bool_val = true;
        nd->while_cond = std::move(c);
        nd->while_body = std::move(body);
        nd->is_until = false;
        return nd;
    }

    /* r expr   (return) */
    if (t.type == TOK_KW && t.value == "r") {
        Token &nxt = p.peek(1);
        if (nxt.type != TOK_OP || nxt.value != "=") {
            p.advance();
            int line = t.line;
            auto nd = make_node(AST_RETURN, line);
            if (p.cur().type != TOK_NEWLINE &&
                p.cur().type != TOK_EOF &&
                !(p.cur().type == TOK_OP && p.cur().value == "}")) {
                nd->ret_value = parse_expr(p, 0);
            }
            return nd;
        }
    }

    /* br (break) */
    if (t.type == TOK_KW && t.value == "br") {
        p.advance();
        auto nd = make_node(AST_BREAK, t.line);
        // Optional level: br 2
        if (p.cur().type == TOK_INT) {
            nd->break_level = atoi(p.advance().value.c_str());
        }
        return nd;
    }

    /* cn (continue) */
    if (t.type == TOK_KW && t.value == "cn") {
        p.advance();
        auto nd = make_node(AST_CONTINUE, t.line);
        if (p.cur().type == TOK_INT) {
            nd->break_level = atoi(p.advance().value.c_str());
        }
        return nd;
    }

    /* expression or assignment statement */
    {
        auto expr = parse_expr(p, 0);

        /* check for assignment: ident = expr  or  [a, b, c] = expr
           Also handles ~= (tracking bind) and := (alias bind) as plain assignment */
        if (p.check(TOK_OP, "=") || p.check(TOK_OP, "~=") || p.check(TOK_OP, ":=")) {
            p.advance();
            if (expr->type == AST_IDENT) {
                auto val = parse_expr(p, 0);
                auto a = make_node(AST_ASSIGN, expr->line);
                a->assign_name = expr->ident_name;
                a->assign_value = std::move(val);
                return a;
            }
            if (expr->type == AST_LIST) {
                // Destructuring assignment: [a, b, c] = expr
                auto n = make_node(AST_DESTRUCT_ASSIGN, expr->line);
                for (auto &item : expr->items) {
                    if (item->type != AST_IDENT)
                        snafu_die("line %d: destructuring requires identifiers", item->line);
                    n->destruct_names.push_back(item->ident_name);
                }
                n->destruct_value = parse_expr(p, 0);
                return n;
            }
            snafu_die("line %d: left side of '=' must be an identifier or destructuring pattern",
                      expr->line);
        }

        auto es = make_node(AST_EXPRSTMT, expr->line);
        es->expr = std::move(expr);
        return es;
    }
}

/* ------------------------------------------------------------------ */
/*  parse — entry point                                                */
/* ------------------------------------------------------------------ */

std::unique_ptr<ASTNode> parse(TokenList &tl) {
    Parser p(tl);
    p.skip_newlines();

    auto prog = make_node(AST_BLOCK, 1);

    while (p.cur().type != TOK_EOF) {
        auto s = parse_stmt(p);
        if (s) prog->block_stmts.push_back(std::move(s));
        p.skip_newlines();
    }

    return prog;
}
