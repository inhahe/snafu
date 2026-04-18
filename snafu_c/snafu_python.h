#pragma once
#include "snafu.h"

// Initialize embedded Python (call once at startup)
void python_init();

// Finalize embedded Python (call at shutdown)
void python_fini();

// Import a Python module, return as a Snafu Value (VAL_PYOBJ wrapper)
Value python_import(const std::string &module_name);

// Call a Python callable with Snafu values, return result as Snafu Value
Value python_call(Value callable, const std::vector<Value> &args);

// Convert Snafu Value -> Python object (returns PyObject* as void*)
void *snafu_to_python(const Value &v);

// Convert Python object -> Snafu Value (takes PyObject* as void*)
Value python_to_snafu(void *pyobj);
