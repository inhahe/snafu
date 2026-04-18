#include "snafu_bytecode.h"

/* ================================================================== */
/*  BytecodeChunk helpers                                              */
/* ================================================================== */

int BytecodeChunk::add_const(const Value &v) {
    constants.push_back(v);
    return static_cast<int>(constants.size()) - 1;
}

int BytecodeChunk::add_name(const std::string &n) {
    // Reuse existing index if the name was already interned
    for (int i = 0; i < static_cast<int>(names.size()); i++) {
        if (names[i] == n) return i;
    }
    names.push_back(n);
    return static_cast<int>(names.size()) - 1;
}

void BytecodeChunk::emit(Opcode op, int arg) {
    code.push_back({op, arg});
}

int BytecodeChunk::current_offset() const {
    return static_cast<int>(code.size());
}

/* ================================================================== */
/*  Compiler: AST -> BytecodeChunk                                     */
/* ================================================================== */

static void compile_node(ASTNode *node, BytecodeChunk &chunk);

/* Compile a list of statements (block body).
   Each statement's result is popped except the last, whose value
   remains on the stack as the block's value. */
static void compile_block_stmts(std::vector<std::unique_ptr<ASTNode>> &stmts,
                                BytecodeChunk &chunk) {
    if (stmts.empty()) {
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        return;
    }
    for (size_t i = 0; i < stmts.size(); i++) {
        compile_node(stmts[i].get(), chunk);
        if (i < stmts.size() - 1)
            chunk.emit(OP_POP);
    }
}

static void compile_node(ASTNode *node, BytecodeChunk &chunk) {
    if (!node) {
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        return;
    }

    switch (node->type) {

    /* ---- literals ---- */
    case AST_NUM:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Int(node->num_val)));
        break;

    case AST_FLOAT:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Float(node->float_val)));
        break;

    case AST_STR:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Str(node->str_val)));
        break;

    case AST_BOOL:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Bool(node->bool_val)));
        break;

    case AST_UND:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        break;

    /* ---- identifier ---- */
    case AST_IDENT:
        chunk.emit(OP_LOAD_NAME, chunk.add_name(node->ident_name));
        break;

    /* ---- binary operators ---- */
    case AST_BINOP: {
        const std::string &op = node->binop_op;

        // Short-circuit: && and ||
        if (op == "&&") {
            compile_node(node->lhs.get(), chunk);
            chunk.emit(OP_DUP);
            int jump_false = chunk.current_offset();
            chunk.emit(OP_JUMP_IF_FALSE, 0);
            chunk.emit(OP_POP);
            compile_node(node->rhs.get(), chunk);
            chunk.code[jump_false].arg = chunk.current_offset();
            break;
        }
        if (op == "||") {
            compile_node(node->lhs.get(), chunk);
            chunk.emit(OP_DUP);
            int jump_true = chunk.current_offset();
            chunk.emit(OP_JUMP_IF_TRUE, 0);
            chunk.emit(OP_POP);
            compile_node(node->rhs.get(), chunk);
            chunk.code[jump_true].arg = chunk.current_offset();
            break;
        }

        compile_node(node->lhs.get(), chunk);
        compile_node(node->rhs.get(), chunk);

        if      (op == "+")  chunk.emit(OP_ADD);
        else if (op == "-")  chunk.emit(OP_SUB);
        else if (op == "*")  chunk.emit(OP_MUL);
        else if (op == "/")  chunk.emit(OP_DIV);
        else if (op == "%")  chunk.emit(OP_MOD);
        else if (op == "**") chunk.emit(OP_POW);
        else if (op == "==") chunk.emit(OP_EQ);
        else if (op == "<>") chunk.emit(OP_NE);
        else if (op == "<")  chunk.emit(OP_LT);
        else if (op == ">")  chunk.emit(OP_GT);
        else if (op == "<=") chunk.emit(OP_LE);
        else if (op == ">=") chunk.emit(OP_GE);
        else                 chunk.emit(OP_HALT);
        break;
    }

    /* ---- unary operators ---- */
    case AST_UNARYOP: {
        compile_node(node->operand.get(), chunk);
        if (node->unary_op == "-")       chunk.emit(OP_NEG);
        else if (node->unary_op == "!")   chunk.emit(OP_NOT);
        else if (node->unary_op == "+")   { /* no-op */ }
        else                              chunk.emit(OP_HALT);
        break;
    }

    /* ---- assignment ---- */
    case AST_ASSIGN:
        compile_node(node->assign_value.get(), chunk);
        chunk.emit(OP_DUP);
        chunk.emit(OP_STORE_NAME, chunk.add_name(node->assign_name));
        break;

    /* ---- if / elif / else ---- */
    case AST_IF: {
        compile_node(node->if_cond.get(), chunk);
        int jump_else = chunk.current_offset();
        chunk.emit(OP_JUMP_IF_FALSE, 0);

        compile_node(node->if_then.get(), chunk);

        if (node->elif_conds.empty() && !node->if_else) {
            int after_then = chunk.current_offset();
            chunk.emit(OP_JUMP, 0);
            chunk.code[jump_else].arg = chunk.current_offset();
            chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
            chunk.code[after_then].arg = chunk.current_offset();
        } else {
            int jump_end = chunk.current_offset();
            chunk.emit(OP_JUMP, 0);
            chunk.code[jump_else].arg = chunk.current_offset();

            std::vector<int> end_jumps;
            end_jumps.push_back(jump_end);

            for (size_t i = 0; i < node->elif_conds.size(); i++) {
                compile_node(node->elif_conds[i].get(), chunk);
                int elif_skip = chunk.current_offset();
                chunk.emit(OP_JUMP_IF_FALSE, 0);
                compile_node(node->elif_bodies[i].get(), chunk);
                end_jumps.push_back(chunk.current_offset());
                chunk.emit(OP_JUMP, 0);
                chunk.code[elif_skip].arg = chunk.current_offset();
            }

            if (node->if_else) {
                compile_node(node->if_else.get(), chunk);
            } else {
                chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
            }

            int end_pos = chunk.current_offset();
            for (int ej : end_jumps)
                chunk.code[ej].arg = end_pos;
        }
        break;
    }

    /* ---- while loop ---- */
    case AST_WHILE: {
        int loop_start = chunk.current_offset();
        compile_node(node->while_cond.get(), chunk);
        if (node->is_until)
            chunk.emit(OP_NOT);
        int jump_exit = chunk.current_offset();
        chunk.emit(OP_JUMP_IF_FALSE, 0);
        compile_node(node->while_body.get(), chunk);
        chunk.emit(OP_POP);
        chunk.emit(OP_JUMP, loop_start);
        chunk.code[jump_exit].arg = chunk.current_offset();
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        break;
    }

    /* ---- for loop ---- */
    case AST_FOR: {
        compile_node(node->for_iter.get(), chunk);
        std::string iter_name = "__for_iter_" + std::to_string(chunk.current_offset()) + "__";
        std::string idx_name  = "__for_idx_"  + std::to_string(chunk.current_offset()) + "__";
        int iter_ni = chunk.add_name(iter_name);
        int idx_ni  = chunk.add_name(idx_name);
        int var_ni  = chunk.add_name(node->for_var);

        chunk.emit(OP_STORE_NAME, iter_ni);
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Int(0)));
        chunk.emit(OP_STORE_NAME, idx_ni);

        int loop_top = chunk.current_offset();
        chunk.emit(OP_LOAD_NAME, idx_ni);
        int len_ni = chunk.add_name("len");
        chunk.emit(OP_LOAD_NAME, len_ni);
        chunk.emit(OP_LOAD_NAME, iter_ni);
        chunk.emit(OP_CALL, 1);
        chunk.emit(OP_GE);
        int jump_exit = chunk.current_offset();
        chunk.emit(OP_JUMP_IF_TRUE, 0);

        chunk.emit(OP_LOAD_NAME, iter_ni);
        chunk.emit(OP_LOAD_NAME, idx_ni);
        chunk.emit(OP_INDEX);
        chunk.emit(OP_STORE_NAME, var_ni);
        chunk.emit(OP_POP);

        compile_node(node->for_body.get(), chunk);
        chunk.emit(OP_POP);

        chunk.emit(OP_LOAD_NAME, idx_ni);
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Int(1)));
        chunk.emit(OP_ADD);
        chunk.emit(OP_STORE_NAME, idx_ni);
        chunk.emit(OP_POP);

        chunk.emit(OP_JUMP, loop_top);
        chunk.code[jump_exit].arg = chunk.current_offset();
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        break;
    }

    /* ---- block ---- */
    case AST_BLOCK:
        compile_block_stmts(node->block_stmts, chunk);
        break;

    /* ---- function declaration ---- */
    case AST_FNDECL: {
        FnProto proto;
        proto.name   = node->fndecl_name;
        proto.params = node->fndecl_params;

        int jump_over = chunk.current_offset();
        chunk.emit(OP_JUMP, 0);

        proto.body_start = chunk.current_offset();
        compile_node(node->fndecl_body.get(), chunk);
        chunk.emit(OP_RETURN);
        proto.body_end = chunk.current_offset();

        chunk.code[jump_over].arg = proto.body_end;

        /* Build fast-local slot map: params + fn name get local slots.
           Also scan the body for any STORE_NAME targets and give them slots.
           Names that are only loaded (not stored and not params) are global. */
        {
            int num_names = static_cast<int>(chunk.names.size());
            proto.local_slot.assign(num_names, -1);
            proto.n_locals = 0;

            // Params get the first slots
            for (auto &pname : proto.params) {
                int ni = chunk.add_name(pname);
                if (ni < static_cast<int>(proto.local_slot.size()) &&
                    proto.local_slot[ni] == -1 &&
                    proto.n_locals < BC_MAX_LOCALS) {
                    proto.local_slot[ni] = proto.n_locals++;
                }
            }
            // Self-reference slot
            {
                int ni = chunk.add_name(proto.name);
                // Might have grown names -- resize local_slot
                proto.local_slot.resize(chunk.names.size(), -1);
                if (ni < static_cast<int>(proto.local_slot.size()) &&
                    proto.local_slot[ni] == -1 &&
                    proto.n_locals < BC_MAX_LOCALS) {
                    proto.local_slot[ni] = proto.n_locals++;
                }
            }
            // Scan body for STORE_NAME instructions and assign them local slots too
            for (int ci = proto.body_start; ci < proto.body_end; ci++) {
                if (chunk.code[ci].op == OP_STORE_NAME) {
                    int ni = chunk.code[ci].arg;
                    if (ni < static_cast<int>(proto.local_slot.size()) &&
                        proto.local_slot[ni] == -1 &&
                        proto.n_locals < BC_MAX_LOCALS) {
                        proto.local_slot[ni] = proto.n_locals++;
                    }
                }
            }
            // Final resize to match current names count
            proto.local_slot.resize(chunk.names.size(), -1);
        }

        int proto_idx = static_cast<int>(chunk.fn_protos.size());
        chunk.fn_protos.push_back(proto);

        chunk.emit(OP_MAKE_FN, proto_idx);

        if (node->fndecl_name != "<lambda>") {
            chunk.emit(OP_DUP);
            chunk.emit(OP_STORE_NAME, chunk.add_name(node->fndecl_name));
            chunk.emit(OP_POP);
            chunk.emit(OP_POP);
            chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        }
        break;
    }

    /* ---- function call ---- */
    case AST_CALL: {
        compile_node(node->call_fn.get(), chunk);
        int nargs = static_cast<int>(node->call_args.size());
        for (int i = 0; i < nargs; i++)
            compile_node(node->call_args[i].get(), chunk);
        chunk.emit(OP_CALL, nargs);
        break;
    }

    /* ---- return ---- */
    case AST_RETURN:
        if (node->ret_value)
            compile_node(node->ret_value.get(), chunk);
        else
            chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        chunk.emit(OP_RETURN);
        break;

    /* ---- expression statement ---- */
    case AST_EXPRSTMT:
        compile_node(node->expr.get(), chunk);
        break;

    /* ---- list literal ---- */
    case AST_LIST: {
        int n = static_cast<int>(node->items.size());
        for (int i = 0; i < n; i++)
            compile_node(node->items[i].get(), chunk);
        chunk.emit(OP_BUILD_LIST, n);
        break;
    }

    /* ---- index ---- */
    case AST_INDEX:
        compile_node(node->index_target.get(), chunk);
        compile_node(node->index_key.get(), chunk);
        chunk.emit(OP_INDEX);
        break;

    /* ---- print ---- */
    case AST_PRINT:
        if (node->expr)
            compile_node(node->expr.get(), chunk);
        else
            chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        chunk.emit(OP_PRINT);
        break;

    /* ---- ternary ---- */
    case AST_TERNARY: {
        compile_node(node->tern_cond.get(), chunk);
        int jump_false = chunk.current_offset();
        chunk.emit(OP_JUMP_IF_FALSE, 0);
        compile_node(node->tern_true.get(), chunk);
        int jump_end = chunk.current_offset();
        chunk.emit(OP_JUMP, 0);
        chunk.code[jump_false].arg = chunk.current_offset();
        compile_node(node->tern_false.get(), chunk);
        chunk.code[jump_end].arg = chunk.current_offset();
        break;
    }

    /* ---- unsupported nodes: push und ---- */
    default:
        chunk.emit(OP_LOAD_CONST, chunk.add_const(Value::Und()));
        break;
    }
}

BytecodeChunk compile(ASTNode *node) {
    BytecodeChunk chunk;
    chunk.name = "<main>";
    compile_node(node, chunk);
    chunk.emit(OP_HALT);
    return chunk;
}

/* ================================================================== */
/*  VM: frame-based execution with inline call stack                   */
/* ================================================================== */

/* A CallFrame represents one function activation on the call stack.
   By keeping the call stack explicit (not via C++ recursion), we avoid
   the overhead of make_scope + shared_ptr refcount per call.  */

struct CallFrame {
    int                      ip;         // instruction pointer
    int                      bp;         // base pointer (stack offset)
    int                      end;        // one past last instruction (0 = use chunk end)
    std::shared_ptr<Scope>   scope;      // closure / global scope (for non-local lookups)
    /* Fast locals: params + fn self-reference stored in flat array,
       avoiding Scope hash-map and shared_ptr per call. */
    int                      proto_idx;  // -1 = top-level (no fast locals)
    Value                    locals[BC_MAX_LOCALS];
};

/* Maximum call depth before we bail. */
static constexpr int MAX_FRAMES = 4096;

Value vm_execute(BytecodeChunk &chunk, std::shared_ptr<Scope> scope) {
    std::vector<Value> stack;
    stack.reserve(256);

    /* Heap-allocate the frame stack since each frame contains a Value array
       (Value is large due to shared_ptrs) and MAX_FRAMES * sizeof(CallFrame)
       would overflow the C stack. */
    static thread_local std::vector<CallFrame> frames_storage(MAX_FRAMES);
    CallFrame *frames = frames_storage.data();
    int frame_count = 0;

    // Push the top-level frame (no fast locals -- uses scope for everything)
    frames[0].ip        = 0;
    frames[0].bp        = 0;
    frames[0].end       = static_cast<int>(chunk.code.size());
    frames[0].scope     = scope;
    frames[0].proto_idx = -1;  // no fast locals
    frame_count = 1;

    CallFrame *frame = &frames[0];
    Instruction *code = chunk.code.data();
    int code_size = static_cast<int>(chunk.code.size());

    // Pre-fetch pointers
    Value *consts   = chunk.constants.data();
    std::string *names_p = chunk.names.data();

    // Helper lambda: pop value from stack
    auto spop = [&stack]() -> Value {
        Value v = stack.back();
        stack.pop_back();
        return v;
    };

#define PUSH(v)   stack.push_back(v)
#define POP()     spop()
#define TOP()     stack.back()
#define SSIZE()   static_cast<int>(stack.size())

    for (;;) {
        if (frame->ip >= frame->end) {
            // Implicit return from frame
            Value result = stack.empty() ? Value::Und() : stack.back();
            if (frame_count <= 1) return result;
            // Pop frame: discard everything above bp, push result
            stack.resize(frame->bp);
            frame_count--;
            frame = &frames[frame_count - 1];
            PUSH(result);
            continue;
        }

        Instruction &inst = code[frame->ip++];

        switch (inst.op) {

        case OP_LOAD_CONST:
            PUSH(consts[inst.arg]);
            break;

        case OP_LOAD_NAME: {
            if (frame->proto_idx >= 0) {
                FnProto &fp = chunk.fn_protos[frame->proto_idx];
                int ni = inst.arg;
                if (ni < static_cast<int>(fp.local_slot.size())) {
                    int slot = fp.local_slot[ni];
                    if (slot >= 0) {
                        PUSH(frame->locals[slot]);
                        break;
                    }
                }
            }
            PUSH(frame->scope->get(names_p[inst.arg]));
            break;
        }

        case OP_STORE_NAME: {
            Value v = POP();
            if (frame->proto_idx >= 0) {
                FnProto &fp = chunk.fn_protos[frame->proto_idx];
                int ni = inst.arg;
                if (ni < static_cast<int>(fp.local_slot.size())) {
                    int slot = fp.local_slot[ni];
                    if (slot >= 0) {
                        frame->locals[slot] = v;
                        break;
                    }
                }
            }
            frame->scope->set(names_p[inst.arg], v);
            break;
        }

        case OP_ADD: {
            Value &r = stack[stack.size() - 1];
            Value &l = stack[stack.size() - 2];
            if (l.is_int() && r.is_int()) {
                l.ival += r.ival;
                stack.pop_back();
            } else if (l.is_str() || r.is_str()) {
                Value res = Value::Str(l.to_string() + r.to_string());
                stack.pop_back();
                stack.back() = res;
            } else {
                double d = l.to_num() + r.to_num();
                stack.pop_back();
                stack.back() = Value::Float(d);
            }
            break;
        }

        case OP_SUB: {
            Value &r = stack[stack.size() - 1];
            Value &l = stack[stack.size() - 2];
            if (l.is_int() && r.is_int()) {
                l.ival -= r.ival;
                stack.pop_back();
            } else {
                double d = l.to_num() - r.to_num();
                stack.pop_back();
                stack.back() = Value::Float(d);
            }
            break;
        }

        case OP_MUL: {
            Value &r = stack[stack.size() - 1];
            Value &l = stack[stack.size() - 2];
            if (l.is_int() && r.is_int()) {
                l.ival *= r.ival;
                stack.pop_back();
            } else {
                double d = l.to_num() * r.to_num();
                stack.pop_back();
                stack.back() = Value::Float(d);
            }
            break;
        }

        case OP_DIV: {
            Value r = POP();
            Value &l = TOP();
            if (r.is_int() && r.ival == 0)
                snafu_die("division by zero");
            if (l.is_int() && r.is_int()) {
                if (l.ival % r.ival == 0) {
                    l.ival /= r.ival;
                } else {
                    l = Value::Float(static_cast<double>(l.ival) /
                                     static_cast<double>(r.ival));
                }
            } else {
                double dr = r.to_num();
                if (dr == 0.0) snafu_die("division by zero");
                l = Value::Float(l.to_num() / dr);
            }
            break;
        }

        case OP_MOD: {
            Value r = POP();
            Value &l = TOP();
            if (l.is_int() && r.is_int()) {
                if (r.ival == 0) snafu_die("modulo by zero");
                l.ival %= r.ival;
            } else {
                double dr = r.to_num();
                if (dr == 0.0) snafu_die("modulo by zero");
                l = Value::Float(fmod(l.to_num(), dr));
            }
            break;
        }

        case OP_POW: {
            Value r = POP();
            Value &l = TOP();
            if (l.is_int() && r.is_int() && r.ival >= 0) {
                long long base = l.ival, exp = r.ival, result = 1;
                while (exp > 0) {
                    if (exp & 1) result *= base;
                    base *= base;
                    exp >>= 1;
                }
                l.ival = result;
            } else {
                l = Value::Float(pow(l.to_num(), r.to_num()));
            }
            break;
        }

        case OP_EQ: {
            Value r = POP();
            Value &l = TOP();
            if (l.is_int() && r.is_int())
                l = Value::Bool(l.ival == r.ival);
            else if ((l.is_int() || l.is_float()) && (r.is_int() || r.is_float()))
                l = Value::Bool(l.to_num() == r.to_num());
            else if (l.is_str() && r.is_str())
                l = Value::Bool(*l.sval == *r.sval);
            else if (l.is_bool() && r.is_bool())
                l = Value::Bool(l.bval == r.bval);
            else if (l.is_und() && r.is_und())
                l = Value::Bool(true);
            else
                l = Value::Bool(false);
            break;
        }

        case OP_NE: {
            Value r = POP();
            Value &l = TOP();
            if (l.is_int() && r.is_int())
                l = Value::Bool(l.ival != r.ival);
            else if ((l.is_int() || l.is_float()) && (r.is_int() || r.is_float()))
                l = Value::Bool(l.to_num() != r.to_num());
            else if (l.is_str() && r.is_str())
                l = Value::Bool(*l.sval != *r.sval);
            else
                l = Value::Bool(true);
            break;
        }

        case OP_LT: {
            Value &r = stack[stack.size() - 1];
            Value &l = stack[stack.size() - 2];
            bool res = (l.is_int() && r.is_int()) ? l.ival < r.ival
                                                   : l.to_num() < r.to_num();
            stack.pop_back();
            stack.back() = Value::Bool(res);
            break;
        }

        case OP_GT: {
            Value &r = stack[stack.size() - 1];
            Value &l = stack[stack.size() - 2];
            bool res = (l.is_int() && r.is_int()) ? l.ival > r.ival
                                                   : l.to_num() > r.to_num();
            stack.pop_back();
            stack.back() = Value::Bool(res);
            break;
        }

        case OP_LE: {
            Value r = POP();
            Value &l = TOP();
            l = Value::Bool((l.is_int() && r.is_int()) ? l.ival <= r.ival
                                                       : l.to_num() <= r.to_num());
            break;
        }

        case OP_GE: {
            Value r = POP();
            Value &l = TOP();
            l = Value::Bool((l.is_int() && r.is_int()) ? l.ival >= r.ival
                                                       : l.to_num() >= r.to_num());
            break;
        }

        case OP_AND: {
            Value r = POP();
            Value &l = TOP();
            l = Value::Bool(l.truthy() && r.truthy());
            break;
        }

        case OP_OR: {
            Value r = POP();
            Value &l = TOP();
            l = Value::Bool(l.truthy() || r.truthy());
            break;
        }

        case OP_NEG: {
            Value &v = TOP();
            if (v.is_int())        v.ival = -v.ival;
            else if (v.is_float()) v.fval = -v.fval;
            else snafu_die("cannot negate non-number");
            break;
        }

        case OP_NOT: {
            Value &v = TOP();
            v = Value::Bool(!v.truthy());
            break;
        }

        case OP_JUMP:
            frame->ip = inst.arg;
            break;

        case OP_JUMP_IF_FALSE: {
            bool t = TOP().truthy();
            stack.pop_back();
            if (!t) frame->ip = inst.arg;
            break;
        }

        case OP_JUMP_IF_TRUE: {
            bool t = TOP().truthy();
            stack.pop_back();
            if (t) frame->ip = inst.arg;
            break;
        }

        case OP_CALL: {
            int nargs = inst.arg;
            int fn_idx = SSIZE() - nargs - 1;
            Value &fn = stack[fn_idx];

            // Builtin fast path
            if (fn.is_builtin()) {
                Value *arg_ptr = stack.data() + fn_idx + 1;
                Value result = (*fn.builtin_fn)(arg_ptr, nargs, frame->scope.get());
                stack.resize(fn_idx);
                PUSH(result);
                break;
            }

            if (fn.is_fn()) {
                FnData *fd = fn.fn.get();

                if (nargs != static_cast<int>(fd->params.size()))
                    snafu_die("function '%s' expects %d args, got %d",
                              fd->name.c_str(),
                              static_cast<int>(fd->params.size()), nargs);

                // Bytecode-compiled function: body == nullptr, proto index in ival
                if (fd->body == nullptr) {
                    int proto_idx = static_cast<int>(fn.ival);
                    if (proto_idx >= 0 && proto_idx < static_cast<int>(chunk.fn_protos.size())) {
                        FnProto &proto = chunk.fn_protos[proto_idx];

                        if (frame_count >= MAX_FRAMES)
                            snafu_die("call stack overflow");

                        // Push a new call frame with fast locals
                        CallFrame &nf = frames[frame_count];
                        nf.ip        = proto.body_start;
                        nf.bp        = fn_idx;
                        nf.end       = proto.body_end;
                        nf.scope     = fd->closure;  // share closure scope, no new scope
                        nf.proto_idx = proto_idx;

                        // Copy params into fast local slots
                        for (int i = 0; i < nargs; i++) {
                            int ni = chunk.add_name(fd->params[i]);
                            // Update local_slot vector if names grew
                            if (ni >= static_cast<int>(proto.local_slot.size()))
                                proto.local_slot.resize(ni + 1, -1);
                            int slot = proto.local_slot[ni];
                            if (slot >= 0)
                                nf.locals[slot] = stack[fn_idx + 1 + i];
                        }
                        // Self-reference for recursion
                        {
                            int ni = chunk.add_name(fd->name);
                            if (ni >= static_cast<int>(proto.local_slot.size()))
                                proto.local_slot.resize(ni + 1, -1);
                            int slot = proto.local_slot[ni];
                            if (slot >= 0)
                                nf.locals[slot] = fn;
                        }

                        // Remove fn + args from value stack
                        stack.resize(fn_idx);
                        frame_count++;
                        frame = &frames[frame_count - 1];
                        // Refresh names_p since add_name may have reallocated
                        names_p = chunk.names.data();
                        break;
                    }
                }

                // Tree-walk fallback for AST-backed functions
                Value *arg_ptr = stack.data() + fn_idx + 1;
                auto call_scope = make_scope(fd->closure);
                for (int i = 0; i < nargs; i++)
                    call_scope->set_local(fd->params[i], arg_ptr[i]);
                call_scope->set_local(fd->name, fn);
                Value result;
                try {
                    result = eval(fd->body, call_scope);
                } catch (ReturnSignal &rs) {
                    result = rs.value;
                }
                stack.resize(fn_idx);
                PUSH(result);
                break;
            }

            snafu_die("not callable (type %d)", fn.type);
            break;
        }

        case OP_RETURN: {
            Value result = stack.empty() ? Value::Und() : POP();
            if (frame_count <= 1) return result;
            stack.resize(frame->bp);
            frame_count--;
            frame = &frames[frame_count - 1];
            PUSH(result);
            break;
        }

        case OP_POP:
            if (!stack.empty()) stack.pop_back();
            break;

        case OP_DUP:
            if (!stack.empty()) PUSH(TOP());
            break;

        case OP_PRINT: {
            Value v = POP();
            std::cout << v.to_string() << std::endl;
            PUSH(Value::Und());
            break;
        }

        case OP_BUILD_LIST: {
            int n = inst.arg;
            Value lst = Value::List(n);
            int start = SSIZE() - n;
            for (int i = 0; i < n; i++)
                lst.list_push(stack[start + i]);
            stack.resize(start);
            PUSH(lst);
            break;
        }

        case OP_INDEX: {
            Value key    = POP();
            Value target = POP();
            if (target.is_list()) {
                if (!key.is_int()) snafu_die("list index must be integer");
                long long idx = key.ival;
                int len = target.list_len();
                if (idx < 0) idx += len;
                if (idx < 0 || idx >= len)
                    snafu_die("index %lld out of range (len %d)", key.ival, len);
                PUSH((*target.list)[static_cast<size_t>(idx)]);
            } else if (target.is_str()) {
                if (!key.is_int()) snafu_die("string index must be integer");
                long long idx = key.ival;
                int slen = static_cast<int>(target.sval->size());
                if (idx < 0) idx += slen;
                if (idx < 0 || idx >= slen)
                    snafu_die("string index out of range");
                PUSH(Value::Str(std::string(1, (*target.sval)[static_cast<size_t>(idx)])));
            } else if (target.is_dict()) {
                if (!key.is_str()) snafu_die("dict key must be string");
                auto it = target.dict->find(*key.sval);
                PUSH(it != target.dict->end() ? it->second : Value::Und());
            } else {
                snafu_die("cannot index into this type");
            }
            break;
        }

        case OP_MAKE_FN: {
            FnProto &proto = chunk.fn_protos[inst.arg];
            // Ensure local_slot covers all current names
            proto.local_slot.resize(chunk.names.size(), -1);
            auto fd = std::make_shared<FnData>();
            fd->name   = proto.name;
            fd->params = proto.params;
            fd->closure = frame->scope;
            fd->body    = nullptr;
            fd->may_capture = false;
            fd->is_coroutine = false;
            fd->is_macro = false;
            Value fn_val = Value::Fn(fd);
            fn_val.ival = inst.arg;
            PUSH(fn_val);
            break;
        }

        case OP_HALT:
            return stack.empty() ? Value::Und() : stack.back();

        } // switch
    } // for

#undef PUSH
#undef POP
#undef TOP
#undef SSIZE

    return stack.empty() ? Value::Und() : stack.back();
}
