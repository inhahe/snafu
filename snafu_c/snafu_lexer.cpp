#include "snafu.h"

/* ------------------------------------------------------------------ */
/*  Keywords                                                           */
/* ------------------------------------------------------------------ */

static const char *KEYWORDS[] = {
    "if", "el", "eli", "for", "in", "wh", "un", "lp",
    "df", "r", "true", "false", "und", "br", "cn",
    "f", "new", "is", "not", "mt", "ty", "try", "exc",
    "ct", "y", "ef", "pf", "hd", "wi", "as",
    "gt", "aw", "ch", "lbl", "goto", "cf",
    "mc", "whr", "defer", "some", "every",
    "on", "of", "fk",
    nullptr
};

static bool is_keyword(const std::string &s) {
    for (int i = 0; KEYWORDS[i]; i++)
        if (s == KEYWORDS[i])
            return true;
    return false;
}

/* ------------------------------------------------------------------ */
/*  Operators — longest-first table                                    */
/* ------------------------------------------------------------------ */

static const char *OPS[] = {
    "|>",   // pipeline
    "+.",   // APL element-wise
    "+/",   // APL reduce
    "+\\",  // APL scan
    "-.",  "-/",  "-\\",
    "*.",  "*/",  "*\\",
    "->",
    "??",   // null coalesce
    "?.",   // safe navigation
    "~=",   // tracking bind
    ":=",   // alias bind
    "**", "==", "<>", "<=", ">=",
    "&&", "||", "..",
    "+", "-", "*", "/", "%",
    "=", "<", ">", "!",
    "&", "|",   // bitwise AND, OR
    "(", ")", "[", "]", "{", "}", ",", ";", ".", ":",
    "?", "@", "_",
    nullptr
};

/* ------------------------------------------------------------------ */
/*  Lexer state                                                        */
/* ------------------------------------------------------------------ */

struct LexState {
    const std::string &src;
    int pos;
    int len;
    int line;
    TokenList &tl;

    LexState(const std::string &s, TokenList &t)
        : src(s), pos(0), len(static_cast<int>(s.size())), line(1), tl(t) {}

    char peek(int off = 0) const {
        int p = pos + off;
        return (p < len) ? src[p] : '\0';
    }

    char cur() const { return peek(0); }

    void advance(int n = 1) {
        for (int i = 0; i < n && pos < len; i++) {
            if (src[pos] == '\n') line++;
            pos++;
        }
    }
};

/* Does the previous token imply continuation? */
static bool last_implies_continuation(const TokenList &tl) {
    if (tl.empty()) return true;
    const Token &last = tl.back();
    if (last.type == TOK_OP) {
        const std::string &v = last.value;
        if (v == "+" || v == "-" || v == "*" || v == "/" || v == "%" ||
            v == "**" || v == "==" || v == "<>" ||
            v == "<" || v == ">" || v == "<=" || v == ">=" ||
            v == "&&" || v == "||" || v == "=" || v == "," ||
            v == "(" || v == "[" || v == "{" || v == ".." ||
            v == "." || v == "|>" || v == "->" || v == ":" ||
            v == "??" || v == "~=" || v == ":=" || v == "&" || v == "|")
            return true;
    }
    return false;
}

static void push_token(TokenList &tl, TokType type, const std::string &value, int line) {
    tl.push_back({type, value, line});
}

/* ------------------------------------------------------------------ */
/*  Main lex()                                                         */
/* ------------------------------------------------------------------ */

TokenList lex(const std::string &src) {
    TokenList tl;
    LexState ls(src, tl);

    while (ls.pos < ls.len) {
        char c = ls.cur();

        /* ---- whitespace (not newline) ---- */
        if (c == ' ' || c == '\t' || c == '\r') {
            ls.advance();
            continue;
        }

        /* ---- newline ---- */
        if (c == '\n') {
            if (!tl.empty()
                && tl.back().type != TOK_NEWLINE
                && !last_implies_continuation(tl)) {
                push_token(tl, TOK_NEWLINE, "\n", ls.line);
            }
            ls.advance();
            continue;
        }

        /* ---- line comment ---- */
        if (c == '#') {
            while (ls.pos < ls.len && ls.cur() != '\n')
                ls.advance();
            continue;
        }

        /* ---- semicolon (statement separator) ---- */
        if (c == ';') {
            if (!tl.empty() && tl.back().type != TOK_NEWLINE)
                push_token(tl, TOK_NEWLINE, ";", ls.line);
            ls.advance();
            continue;
        }

        /* ---- regex literal r/pattern/flags ---- */
        if (c == 'r' && ls.peek(1) == '/') {
            // Check if this is really a regex (not identifier 'r' followed by division)
            // Heuristic: if previous token is a value-producing token, then it's division
            bool is_regex = true;
            if (!tl.empty()) {
                TokType pt = tl.back().type;
                if (pt == TOK_INT || pt == TOK_FLOAT || pt == TOK_STR ||
                    pt == TOK_IDENT ||
                    (pt == TOK_OP && (tl.back().value == ")" || tl.back().value == "]"))) {
                    is_regex = false;
                }
            }
            if (is_regex) {
                ls.advance(2); // skip r/
                std::string pattern;
                while (ls.pos < ls.len && ls.cur() != '/') {
                    if (ls.cur() == '\\' && ls.pos + 1 < ls.len) {
                        pattern += ls.cur();
                        ls.advance();
                        pattern += ls.cur();
                        ls.advance();
                    } else {
                        pattern += ls.cur();
                        ls.advance();
                    }
                }
                if (ls.pos >= ls.len)
                    snafu_die("unterminated regex at line %d", ls.line);
                ls.advance(); // skip closing /
                // Read flags
                std::string flags;
                while (ls.pos < ls.len && isalpha(static_cast<unsigned char>(ls.cur()))) {
                    flags += ls.cur();
                    ls.advance();
                }
                // Store as a special token: "REGEX:pattern:flags"
                push_token(tl, TOK_STR, "\x01REGEX:" + pattern + ":" + flags, ls.line);
                continue;
            }
        }

        /* ---- double-quoted string (with interpolation support) ---- */
        if (c == '"') {
            ls.advance(); // skip opening "
            std::string buf;
            bool has_interp = false;
            // First pass: check for interpolation
            int save_pos = ls.pos;
            int save_line = ls.line;
            while (ls.pos < ls.len && ls.cur() != '"') {
                if (ls.cur() == '\\' && ls.pos + 1 < ls.len) {
                    ls.advance(2);
                } else if (ls.cur() == '$' && ls.peek(1) == '{') {
                    has_interp = true;
                    break;
                } else {
                    ls.advance();
                }
            }
            ls.pos = save_pos;
            ls.line = save_line;

            if (has_interp) {
                // Emit interpolated string as a special string starting with \x02
                // We'll parse "${expr}" by emitting the raw content and letting
                // the parser handle it
                std::string raw;
                while (ls.pos < ls.len && ls.cur() != '"') {
                    if (ls.cur() == '\\' && ls.pos + 1 < ls.len) {
                        ls.advance();
                        char e = ls.cur();
                        if (e == 'n')      raw += '\n';
                        else if (e == 't')  raw += '\t';
                        else if (e == 'r')  raw += '\r';
                        else if (e == '\\') raw += '\\';
                        else if (e == '"')  raw += '"';
                        else if (e == '$')  raw += '$';
                        else if (e == '0')  raw += '\0';
                        else                raw += e;
                        ls.advance();
                    } else {
                        raw += ls.cur();
                        ls.advance();
                    }
                }
                if (ls.pos >= ls.len)
                    snafu_die("unterminated string at line %d", ls.line);
                ls.advance(); // skip closing "
                push_token(tl, TOK_STR, "\x02" + raw, ls.line);
            } else {
                while (ls.pos < ls.len && ls.cur() != '"') {
                    if (ls.cur() == '\\' && ls.pos + 1 < ls.len) {
                        ls.advance();
                        char e = ls.cur();
                        if (e == 'n')       buf += '\n';
                        else if (e == 't')  buf += '\t';
                        else if (e == 'r')  buf += '\r';
                        else if (e == '\\') buf += '\\';
                        else if (e == '"')  buf += '"';
                        else if (e == '0')  buf += '\0';
                        else                buf += e;
                        ls.advance();
                    } else {
                        buf += ls.cur();
                        ls.advance();
                    }
                }
                if (ls.pos >= ls.len)
                    snafu_die("unterminated string at line %d", ls.line);
                ls.advance(); // skip closing "
                push_token(tl, TOK_STR, buf, ls.line);
            }
            continue;
        }

        /* ---- single-quoted string ---- */
        if (c == '\'') {
            ls.advance();
            std::string buf;
            while (ls.pos < ls.len && ls.cur() != '\'') {
                if (ls.cur() == '\\' && ls.pos + 1 < ls.len &&
                    (ls.peek(1) == '\'' || ls.peek(1) == '\\')) {
                    ls.advance();
                    buf += ls.cur();
                    ls.advance();
                } else {
                    buf += ls.cur();
                    ls.advance();
                }
            }
            if (ls.pos >= ls.len)
                snafu_die("unterminated string at line %d", ls.line);
            ls.advance();
            push_token(tl, TOK_STR, buf, ls.line);
            continue;
        }

        /* ---- number ---- */
        if (isdigit(static_cast<unsigned char>(c))) {
            int start = ls.pos;
            while (ls.pos < ls.len &&
                   (isdigit(static_cast<unsigned char>(ls.cur())) || ls.cur() == '_'))
                ls.advance();
            bool is_float = false;
            if (ls.cur() == '.' && isdigit(static_cast<unsigned char>(ls.peek(1)))) {
                is_float = true;
                ls.advance(); // skip .
                while (ls.pos < ls.len &&
                       (isdigit(static_cast<unsigned char>(ls.cur())) || ls.cur() == '_'))
                    ls.advance();
            }
            if (ls.cur() == 'e' || ls.cur() == 'E') {
                is_float = true;
                ls.advance();
                if (ls.cur() == '+' || ls.cur() == '-')
                    ls.advance();
                while (ls.pos < ls.len && isdigit(static_cast<unsigned char>(ls.cur())))
                    ls.advance();
            }
            std::string buf;
            for (int i = start; i < ls.pos; i++) {
                if (src[i] != '_') buf += src[i];
            }
            push_token(tl, is_float ? TOK_FLOAT : TOK_INT, buf, ls.line);
            continue;
        }

        /* ---- identifier / keyword ---- */
        if (isalpha(static_cast<unsigned char>(c)) || c == '_') {
            int start = ls.pos;
            while (ls.pos < ls.len &&
                   (isalnum(static_cast<unsigned char>(ls.cur())) || ls.cur() == '_'))
                ls.advance();
            std::string word = src.substr(start, ls.pos - start);
            TokType tt = is_keyword(word) ? TOK_KW : TOK_IDENT;
            push_token(tl, tt, word, ls.line);
            continue;
        }

        /* ---- operators (longest match) ---- */
        {
            bool matched = false;
            for (int i = 0; OPS[i]; i++) {
                int olen = static_cast<int>(strlen(OPS[i]));
                if (ls.pos + olen <= ls.len &&
                    src.compare(ls.pos, olen, OPS[i]) == 0) {
                    push_token(tl, TOK_OP, OPS[i], ls.line);
                    ls.advance(olen);
                    matched = true;
                    break;
                }
            }
            if (matched) continue;
        }

        snafu_die("unexpected character '%c' at line %d", c, ls.line);
    }

    /* strip trailing newlines */
    while (!tl.empty() && tl.back().type == TOK_NEWLINE)
        tl.pop_back();

    push_token(tl, TOK_EOF, "", ls.line);
    return tl;
}
