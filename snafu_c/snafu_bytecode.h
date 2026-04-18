#pragma once
#include "snafu.h"
#include <vector>
#include <string>
#include <cstdint>

/* ------------------------------------------------------------------ */
/*  Bytecode opcodes                                                   */
/* ------------------------------------------------------------------ */

enum Opcode : uint8_t {
    OP_LOAD_CONST,      // push constants[arg]
    OP_LOAD_NAME,       // push scope->get(names[arg])
    OP_STORE_NAME,      // pop, scope->set(names[arg], val)
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_POW,
    OP_EQ, OP_NE, OP_LT, OP_GT, OP_LE, OP_GE,
    OP_AND, OP_OR,
    OP_NEG, OP_NOT,
    OP_JUMP,            // ip = arg
    OP_JUMP_IF_FALSE,   // pop; if falsy, ip = arg
    OP_JUMP_IF_TRUE,    // pop; if truthy, ip = arg
    OP_CALL,            // pop nargs + fn, call, push result
    OP_RETURN,          // pop and return
    OP_POP,             // discard top
    OP_DUP,             // duplicate top
    OP_PRINT,           // pop and print
    OP_BUILD_LIST,      // pop n items, push list
    OP_INDEX,           // pop key, pop obj, push obj[key]
    OP_MAKE_FN,         // create a closure; arg = index into fn_protos
    OP_HALT,
};

/* ------------------------------------------------------------------ */
/*  Instruction                                                        */
/* ------------------------------------------------------------------ */

struct Instruction {
    Opcode op;
    int    arg;
};

/* ------------------------------------------------------------------ */
/*  Function prototype -- stored in the chunk for OP_MAKE_FN           */
/* ------------------------------------------------------------------ */

/* Maximum local slots per function frame */
static constexpr int BC_MAX_LOCALS = 32;

struct FnProto {
    std::string              name;
    std::vector<std::string> params;
    int                      body_start; // index into code where body begins
    int                      body_end;   // index past the body (for JUMP-over)

    /* Fast-locals: mapping from chunk name-index to a local slot.
       local_slot[name_idx] = slot in [0..n_locals), or -1 if global.
       Populated after compilation of the function body. */
    std::vector<int>         local_slot; // indexed by chunk name-index
    int                      n_locals;   // number of allocated local slots
};

/* ------------------------------------------------------------------ */
/*  BytecodeChunk                                                      */
/* ------------------------------------------------------------------ */

struct BytecodeChunk {
    std::vector<Instruction>  code;
    std::vector<Value>        constants;
    std::vector<std::string>  names;
    std::vector<FnProto>      fn_protos;
    std::string               name;

    int  add_const(const Value &v);
    int  add_name(const std::string &n);
    void emit(Opcode op, int arg = 0);
    int  current_offset() const;
};

/* ------------------------------------------------------------------ */
/*  Compiler: AST -> BytecodeChunk                                     */
/* ------------------------------------------------------------------ */

BytecodeChunk compile(ASTNode *node);

/* ------------------------------------------------------------------ */
/*  VM: execute BytecodeChunk                                          */
/* ------------------------------------------------------------------ */

Value vm_execute(BytecodeChunk &chunk, std::shared_ptr<Scope> scope);
