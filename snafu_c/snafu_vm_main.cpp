#include "snafu.h"
#include "snafu_bytecode.h"

/* ------------------------------------------------------------------ */
/*  snafu_vm — separate entry point for bytecode VM mode               */
/* ------------------------------------------------------------------ */

static void run_vm_source(const std::string &src) {
    TokenList tl = lex(src);
    auto prog = parse(tl);
    auto chunk = compile(prog.get());
    auto global = make_scope();
    install_prelude(global);
    try {
        Value result = vm_execute(chunk, global);
        if (!result.is_und())
            std::cout << result.repr() << std::endl;
    } catch (SnafuError &e) {
        std::cerr << "snafu vm error: " << e.msg << std::endl;
        exit(1);
    }
}

static void run_vm_file(const std::string &path) {
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) {
        std::cerr << "snafu_vm: cannot open '" << path << "'" << std::endl;
        exit(1);
    }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::string buf(sz, '\0');
    fread(&buf[0], 1, sz, f);
    fclose(f);
    run_vm_source(buf);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "Usage: snafu_vm -e \"<code>\"" << std::endl;
        std::cerr << "       snafu_vm <file.snf>" << std::endl;
        return 1;
    }
    if (strcmp(argv[1], "-e") == 0) {
        if (argc < 3) {
            std::cerr << "usage: snafu_vm -e <code>" << std::endl;
            return 1;
        }
        run_vm_source(argv[2]);
        return 0;
    }
    run_vm_file(argv[1]);
    return 0;
}
