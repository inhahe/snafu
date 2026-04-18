#include "snafu.h"

/* ------------------------------------------------------------------ */
/*  Create scope                                                       */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  Scope pool — reuse Scope objects to avoid heap churn               */
/* ------------------------------------------------------------------ */

static thread_local std::vector<Scope *> scope_pool;

static Scope *pool_alloc() {
    if (!scope_pool.empty()) {
        Scope *s = scope_pool.back();
        scope_pool.pop_back();
        return s;
    }
    return new Scope();
}

static void pool_return(Scope *s) {
    s->bindings.clear();
    s->parent.reset();
    s->triggers.clear();
    s->snapshots.clear();
    s->defer_stack.clear();
    if (scope_pool.size() < 256) {
        scope_pool.push_back(s);
    } else {
        delete s;
    }
}

std::shared_ptr<Scope> make_scope(std::shared_ptr<Scope> parent) {
    Scope *raw = pool_alloc();
    raw->parent = std::move(parent);
    return std::shared_ptr<Scope>(raw, pool_return);
}

/* ------------------------------------------------------------------ */
/*  scope_get — walk parent chain                                      */
/* ------------------------------------------------------------------ */

Value Scope::get(const std::string &name) const {
    auto it = bindings.find(name);
    if (it != bindings.end()) return it->second;
    if (parent) return parent->get(name);
    snafu_die("name '%s' not found", name.c_str());
    // unreachable
    return Value::Und();
}

/* ------------------------------------------------------------------ */
/*  scope_has — check existence                                        */
/* ------------------------------------------------------------------ */

bool Scope::has(const std::string &name) const {
    if (bindings.count(name)) return true;
    if (parent) return parent->has(name);
    return false;
}

/* ------------------------------------------------------------------ */
/*  scope_set — assign to existing binding if found, else create local */
/* ------------------------------------------------------------------ */

/* Global trigger count — defined here, declared extern in snafu.h */
std::atomic<int> g_trigger_count{0};

void Scope::set(const std::string &name, const Value &v) {
    // Walk chain looking for existing binding
    for (Scope *cur = this; cur; cur = cur->parent.get()) {
        auto it = cur->bindings.find(name);
        if (it != cur->bindings.end()) {
            it->second = v;
            if (g_trigger_count.load(std::memory_order_relaxed) > 0)
                fire_triggers(name, shared_from_this());
            return;
        }
    }
    // Not found: create local
    bindings[name] = v;
    if (g_trigger_count.load(std::memory_order_relaxed) > 0)
        fire_triggers(name, shared_from_this());
}

/* ------------------------------------------------------------------ */
/*  scope_set_local — always create / overwrite in THIS scope          */
/* ------------------------------------------------------------------ */

void Scope::set_local(const std::string &name, const Value &v) {
    bindings[name] = v;
}

/* ------------------------------------------------------------------ */
/*  root — walk up to the root scope                                   */
/* ------------------------------------------------------------------ */

Scope *Scope::root() {
    Scope *cur = this;
    while (cur->parent) cur = cur->parent.get();
    return cur;
}

const Scope *Scope::root() const {
    const Scope *cur = this;
    while (cur->parent) cur = cur->parent.get();
    return cur;
}

/* ------------------------------------------------------------------ */
/*  all_bindings — collect all bindings from this scope up             */
/* ------------------------------------------------------------------ */

std::unordered_map<std::string, Value> Scope::all_bindings() const {
    std::unordered_map<std::string, Value> result;
    // Start from root, then override with each child
    std::vector<const Scope *> chain;
    for (const Scope *cur = this; cur; cur = cur->parent.get())
        chain.push_back(cur);
    // Apply in reverse (root first)
    for (int i = static_cast<int>(chain.size()) - 1; i >= 0; i--) {
        for (auto &kv : chain[i]->bindings)
            result[kv.first] = kv.second;
    }
    return result;
}

/* ------------------------------------------------------------------ */
/*  fire_triggers — check and fire reactive triggers                   */
/* ------------------------------------------------------------------ */

void Scope::fire_triggers(const std::string &name, std::shared_ptr<Scope> scope_ptr) {
    Scope *r = root();
    if (r->triggers.empty()) return;  // fast path: no triggers registered
    for (auto &trigger : r->triggers) {
        if (trigger.var_name == name && trigger.body) {
            try {
                eval(trigger.body, scope_ptr);
            } catch (...) {
                // Silently ignore errors in triggers
            }
        }
    }
}
