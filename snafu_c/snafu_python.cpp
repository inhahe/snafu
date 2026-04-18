#include "snafu_python.h"

/* ------------------------------------------------------------------ */
/*  Python bridge — conditionally compiled                             */
/* ------------------------------------------------------------------ */

#ifdef SNAFU_HAS_PYTHON
#include <Python.h>

void python_init() {
    if (!Py_IsInitialized()) {
        Py_Initialize();
    }
}

void python_fini() {
    if (Py_IsInitialized()) {
        Py_FinalizeEx();
    }
}

/* ---- Snafu Value -> PyObject* ---- */

static PyObject *snafu_to_py(const Value &v) {
    switch (v.type) {
    case VAL_INT:
        return PyLong_FromLongLong(v.ival);
    case VAL_FLOAT:
        return PyFloat_FromDouble(v.fval);
    case VAL_STR:
        return PyUnicode_FromString(v.sval ? v.sval->c_str() : "");
    case VAL_BOOL:
        if (v.bval) { Py_RETURN_TRUE; }
        else        { Py_RETURN_FALSE; }
    case VAL_UND:
        Py_RETURN_NONE;
    case VAL_LIST: {
        Py_ssize_t n = v.list ? static_cast<Py_ssize_t>(v.list->size()) : 0;
        PyObject *list = PyList_New(n);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyList_SET_ITEM(list, i, snafu_to_py((*v.list)[static_cast<size_t>(i)]));
        }
        return list;
    }
    case VAL_DICT: {
        PyObject *dict = PyDict_New();
        if (v.dict) {
            for (auto &[k, val] : *v.dict) {
                PyObject *key = PyUnicode_FromString(k.c_str());
                PyObject *pval = snafu_to_py(val);
                PyDict_SetItem(dict, key, pval);
                Py_DECREF(key);
                Py_DECREF(pval);
            }
        }
        return dict;
    }
    case VAL_PYOBJ:
        if (v.pyobj) {
            Py_INCREF((PyObject *)v.pyobj);
            return (PyObject *)v.pyobj;
        }
        Py_RETURN_NONE;
    default:
        Py_RETURN_NONE;
    }
}

void *snafu_to_python(const Value &v) {
    return static_cast<void *>(snafu_to_py(v));
}

/* ---- PyObject* -> Snafu Value ---- */

static Value py_to_snafu(PyObject *obj) {
    if (!obj || obj == Py_None)
        return Value::Und();
    if (PyBool_Check(obj))
        return Value::Bool(obj == Py_True);
    if (PyLong_Check(obj))
        return Value::Int(PyLong_AsLongLong(obj));
    if (PyFloat_Check(obj))
        return Value::Float(PyFloat_AsDouble(obj));
    if (PyUnicode_Check(obj)) {
        const char *s = PyUnicode_AsUTF8(obj);
        return Value::Str(s ? s : "");
    }
    if (PyList_Check(obj)) {
        Py_ssize_t n = PyList_Size(obj);
        Value list = Value::List(static_cast<int>(n));
        for (Py_ssize_t i = 0; i < n; i++) {
            list.list_push(py_to_snafu(PyList_GetItem(obj, i)));
        }
        return list;
    }
    if (PyTuple_Check(obj)) {
        Py_ssize_t n = PyTuple_Size(obj);
        Value list = Value::List(static_cast<int>(n));
        for (Py_ssize_t i = 0; i < n; i++) {
            list.list_push(py_to_snafu(PyTuple_GetItem(obj, i)));
        }
        return list;
    }
    if (PyDict_Check(obj)) {
        Value d = Value::Dict();
        PyObject *key, *value;
        Py_ssize_t pos = 0;
        while (PyDict_Next(obj, &pos, &key, &value)) {
            const char *k = PyUnicode_AsUTF8(key);
            if (k) (*d.dict)[k] = py_to_snafu(value);
        }
        return d;
    }
    /* For callable Python objects, modules, etc. -- wrap as VAL_PYOBJ */
    Py_INCREF(obj);
    Value v;
    v.type = VAL_PYOBJ;
    v.pyobj = obj;
    return v;
}

Value python_to_snafu(void *pyobj) {
    return py_to_snafu(static_cast<PyObject *>(pyobj));
}

/* ---- Import a Python module ---- */

Value python_import(const std::string &module_name) {
    python_init();
    PyObject *mod = PyImport_ImportModule(module_name.c_str());
    if (!mod) {
        PyErr_Print();
        return Value::Und();
    }
    Value v;
    v.type = VAL_PYOBJ;
    v.pyobj = mod; /* owns a reference */
    return v;
}

/* ---- Call a Python callable ---- */

Value python_call(Value callable, const std::vector<Value> &args) {
    if (callable.type != VAL_PYOBJ || !callable.pyobj)
        return Value::Und();

    PyObject *pyargs = PyTuple_New(static_cast<Py_ssize_t>(args.size()));
    for (size_t i = 0; i < args.size(); i++) {
        /* PyTuple_SetItem steals the reference returned by snafu_to_py */
        PyTuple_SetItem(pyargs, static_cast<Py_ssize_t>(i), snafu_to_py(args[i]));
    }

    PyObject *result = PyObject_CallObject((PyObject *)callable.pyobj, pyargs);
    Py_DECREF(pyargs);

    if (!result) {
        PyErr_Print();
        return Value::Und();
    }

    Value rv = py_to_snafu(result);
    Py_DECREF(result);
    return rv;
}

#else
/* ------------------------------------------------------------------ */
/*  Stub implementations when Python is not available                  */
/* ------------------------------------------------------------------ */

void python_init() {}
void python_fini() {}

Value python_import(const std::string &) {
    fprintf(stderr, "Python bridge not available (compiled without SNAFU_HAS_PYTHON)\n");
    return Value::Und();
}

Value python_call(Value, const std::vector<Value> &) {
    return Value::Und();
}

void *snafu_to_python(const Value &) {
    return nullptr;
}

Value python_to_snafu(void *) {
    return Value::Und();
}

#endif
