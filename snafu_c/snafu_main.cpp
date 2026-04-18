#include "snafu.h"
#include "snafu_python.h"

/* ------------------------------------------------------------------ */
/*  run_source -- lex + parse + eval a string                          */
/* ------------------------------------------------------------------ */

void run_source(const std::string &src) {
    TokenList tl = lex(src);
    auto prog = parse(tl);
    auto global = make_scope();
    install_prelude(global);
    try {
        Value result = eval(prog.get(), global);
        if (!result.is_und()) {
            std::cout << result.repr() << std::endl;
        }
    } catch (SnafuError &e) {
        std::cerr << "snafu error: " << e.msg << std::endl;
        exit(1);
    }
}

/* ------------------------------------------------------------------ */
/*  run_file -- read a file and run it                                 */
/* ------------------------------------------------------------------ */

void run_file(const std::string &path) {
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) {
        std::cerr << "snafu: cannot open '" << path << "'" << std::endl;
        exit(1);
    }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::string buf(sz, '\0');
    fread(&buf[0], 1, sz, f);
    fclose(f);
    run_source(buf);
}

/* ------------------------------------------------------------------ */
/*  repl -- simple read-eval-print loop                                */
/* ------------------------------------------------------------------ */

void repl() {
    std::cout << "snafu C++ v0.2 -- type expressions, Ctrl-D to exit" << std::endl;
    auto global = make_scope();
    install_prelude(global);
    char line[4096];
    while (true) {
        std::cout << "> " << std::flush;
        if (!fgets(line, sizeof(line), stdin))
            break;
        int len = static_cast<int>(strlen(line));
        if (len > 0 && line[len - 1] == '\n') line[--len] = '\0';
        if (len == 0) continue;
        try {
            TokenList tl = lex(line);
            auto prog = parse(tl);
            Value result = eval(prog.get(), global);
            if (!result.is_und()) {
                std::cout << result.repr() << std::endl;
            }
        } catch (SnafuError &e) {
            std::cerr << "snafu error: " << e.msg << std::endl;
        }
    }
    std::cout << std::endl;
}

/* ------------------------------------------------------------------ */
/*  main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv) {
    python_init();

    if (argc < 2) {
        repl();
        python_fini();
        return 0;
    }
    if (strcmp(argv[1], "-e") == 0) {
        if (argc < 3) {
            std::cerr << "usage: snafu -e <code>" << std::endl;
            python_fini();
            return 1;
        }
        run_source(argv[2]);
        python_fini();
        return 0;
    }
    run_file(argv[1]);
    python_fini();
    return 0;
}
