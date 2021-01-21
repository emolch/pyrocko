#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "cuda/utils.cuh"
#include "ext.h"

static PyObject *w_check_cuda_supported(PyObject *module, PyObject *args) {
    UNUSED(module);
    UNUSED(args);
    long supported = 0;
#if defined(_CUDA)
    supported = check_cuda_supported();
#endif
    return Py_BuildValue("N", PyBool_FromLong(supported));
}

static PyMethodDef MaxMethods[] = {
    {"check_cuda_supported", (PyCFunction)w_check_cuda_supported, METH_NOARGS,
     "checks if a CUDA enabled GPU is available"},

    {NULL, NULL, 0, NULL} /* Sentinel */
};

#if PY_MAJOR_VERSION >= 3

static int cuda_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int cuda_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,       "cuda_ext",     NULL,
    sizeof(struct module_state), MaxMethods,     NULL,
    cuda_ext_traverse,           cuda_ext_clear, NULL};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit_cuda_ext(void)
#else
#define INITERROR return

void initcuda_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("cuda_ext", MaxMethods);
#endif
    if (module == NULL) INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.cuda_ext.CudaExtError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    long cuda_compiled = 0;
    long cuda_debug = 0;
#if defined(_CUDA)
    cuda_compiled = 1;
#endif
    if (PyModule_AddIntConstant(module, CUDA_COMPILED_FLAG, cuda_compiled) <
        0) {
        Py_DECREF(module);
        INITERROR;
    }

#if defined(CUDA_DEBUG)
    cuda_debug = 1;
#endif
    PyModule_AddIntConstant(module, "CUDA_DEBUG", cuda_debug);

    PyModule_AddIntConstant(module, "IMPL_NP", IMPL_NP);
    PyModule_AddIntConstant(module, "IMPL_OMP", IMPL_OMP);
    PyModule_AddIntConstant(module, "IMPL_CUDA", IMPL_CUDA);
    PyModule_AddIntConstant(module, "IMPL_CUDA_THRUST", IMPL_CUDA_THRUST);
    PyModule_AddIntConstant(module, "IMPL_CUDA_ATOMIC", IMPL_CUDA_ATOMIC);

    Py_INCREF(st->error);
    if (PyModule_AddObject(module, "CudaExtError", st->error) < 0) {
        Py_DECREF(module);
        Py_DECREF(st->error);
        INITERROR;
    }

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
