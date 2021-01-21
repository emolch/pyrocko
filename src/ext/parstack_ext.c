#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"
#include "ext.h"
#include "cuda/parstack.cuh"
#include "cuda/utils.cuh"
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <float.h>
#if defined(_OPENMP)
    # include <omp.h>
#endif

#define CHUNKSIZE 10

int parstack_config(size_t narrays, int32_t *offsets, size_t *lengths,
                    size_t nshifts, int32_t *shifts, size_t *lengthout,
                    int32_t *offsetout) {
    if (narrays < 1) {
        return NODATA;
    }

    int32_t imin, imax, istart, iend;
    size_t iarray, ishift;

    imin = offsets[0] + shifts[0];
    imax = imin + lengths[0];
    for (iarray = 0; iarray < narrays; iarray++) {
        for (ishift = 0; ishift < nshifts; ishift++) {
            istart = offsets[iarray] + shifts[ishift * narrays + iarray];
            iend = istart + lengths[iarray];
            imin = min(imin, istart);
            imax = max(imax, iend);
        }
    }

    *lengthout = imax - imin;
    *offsetout = imin;

    return SUCCESS;
}

#define STRINGIFY(a) #a
#if defined(_OPENMP)
#define OMP(block...) block
#else
#define OMP(block...)
#endif

#define __cpu_parstack_method_0(type) \
int cpu_parstack_method_0_##type(type **arrays, type *weights, type *result, parstack_arguments_t args) { \
  int32_t istart, ishift; \
  size_t iarray, i; \
  int chunk = CHUNKSIZE; \
  type weight; \
  \
  OMP( _Pragma( STRINGIFY(omp parallel private(ishift, iarray, i, istart, weight) num_threads(args.nparallel)))) \
  { \
    OMP(_Pragma( STRINGIFY(omp for schedule(dynamic, chunk) nowait ))) \
    for (ishift = 0; ishift < (int32_t)args.nshifts; ishift++) { \
      for (iarray = 0; iarray < args.narrays; iarray++) { \
        istart = args.offsets[iarray] + args.shifts[ishift * args.narrays + iarray]; \
        weight = weights[ishift * args.narrays + iarray]; \
        for (i = (size_t)max(0, args.offsetout - istart); \
             i < (size_t)max(0, min(args.lengthout - istart + args.offsetout, args.lengths[iarray])); i++) { \
          result[ishift * args.lengthout + istart - args.offsetout + i] += arrays[iarray][i] * weight; \
        } \
      } \
    } \
  } \
  return SUCCESS; \
}

__cpu_parstack_method_0(float);
__cpu_parstack_method_0(double);

#define __cpu_parstack_method_1(type) \
int cpu_parstack_method_1_##type(type **arrays, type *weights, type *result, parstack_arguments_t args) { \
  int32_t istart, ishift; \
  size_t iarray, i; \
  int chunk = CHUNKSIZE; \
  type *temp, m, weight; \
  \
  OMP( _Pragma( STRINGIFY(omp parallel private(ishift, iarray, i, istart, weight, temp, m) ))) \
  { \
    temp = (type*)calloc(args.lengthout, sizeof(type)); \
    OMP(_Pragma( STRINGIFY(omp for schedule(dynamic, chunk) nowait ))) \
    for (ishift = 0; ishift < (int32_t)args.nshifts; ishift++) { \
      memset(temp, 0, args.lengthout * sizeof(type)); \
      for (iarray = 0; iarray < args.narrays; iarray++) { \
        istart = args.offsets[iarray] + args.shifts[ishift * args.narrays + iarray]; \
        weight = weights[ishift * args.narrays + iarray]; \
        for (i = (size_t)max(0, args.offsetout - istart); \
             i < (size_t)max(0, min(args.lengthout - istart + args.offsetout, args.lengths[iarray])); i++) { \
          temp[istart - args.offsetout + i] += arrays[iarray][i] * weight; \
        } \
      } \
      m = 0.; \
      for (i=0; i<args.lengthout; i++) { \
        m = fmax(m, temp[i]); \
      } \
      result[ishift] = m; \
    } \
    free(temp); \
  } \
  return SUCCESS; \
}

__cpu_parstack_method_1(float);
__cpu_parstack_method_1(double);

int parstack(size_t narrays, void **arrays, int32_t *offsets, size_t *lengths,
             size_t nshifts, int32_t *shifts, void *weights, int method,
             size_t lengthout, int32_t offsetout, void *result, impl_t impl,
             int nparallel, size_t target_block_threads, int precision,
             char **err) {
    if (narrays < 1) {
        return NODATA;
    }

    if (nshifts > INT_MAX) {
        return INVALID;
    }

    int RET_CODE = SUCCESS;

    parstack_arguments_t args = {
        .narrays = narrays,
        .offsets = offsets,
        .lengths = lengths,
        .nshifts = nshifts,
        .shifts = shifts,
        .method = (uint8_t)method,
        .lengthout = lengthout,
        .offsetout = offsetout,
        .impl = impl,
        .nparallel = (uint8_t)nparallel,
        .target_block_threads = target_block_threads,
        .err = err,
    };

    Py_BEGIN_ALLOW_THREADS;
    if (impl == IMPL_CUDA || impl == IMPL_CUDA_THRUST ||
        impl == IMPL_CUDA_ATOMIC) {
#if defined(_CUDA)
        if (!check_cuda_supported()) {
            fprintf(stderr, "no CUDA capable GPU device available");
            RET_CODE = ERROR;
        } else {
            if (precision == NPY_FLOAT32) {
                RET_CODE = cuda_parstack_float(
                    (float **)arrays, (float *)weights, (float *)result, args);
            } else {
                RET_CODE =
                    cuda_parstack_double((double **)arrays, (double *)weights,
                                         (double *)result, args);
            }
        }
#else
        fprintf(stderr,
                "pyrocko was compiled without CUDA support, please "
                "recompile with CUDA");
        RET_CODE = ERROR;
#endif
    } else {
        if (precision == NPY_FLOAT32) {
            if (method == 0) {
                RET_CODE = cpu_parstack_method_0_float(
                    (float **)arrays, (float *)weights, (float *)result, args);
            } else {
                RET_CODE = cpu_parstack_method_1_float(
                    (float **)arrays, (float *)weights, (float *)result, args);
            }
        } else {
            if (method == 0) {
                RET_CODE = cpu_parstack_method_0_double((double **)arrays,
                                                        (double *)weights,
                                                        (double *)result, args);
            } else {
                RET_CODE = cpu_parstack_method_1_double((double **)arrays,
                                                        (double *)weights,
                                                        (double *)result, args);
            }
        }
    }
    Py_END_ALLOW_THREADS;
    return RET_CODE;
}

int good_array(char *name, PyObject *o, int typenum, char **err_msg) {
    int good = false;
    char *error = NULL;
    if (!PyArray_Check(o)) {
        error = "not a NumPy array";
    } else if (PyArray_TYPE((PyArrayObject *)o) != typenum) {
        error = "array of unexpected type";
    } else if (!PyArray_ISCARRAY((PyArrayObject *)o)) {
        error = "array is not contiguous or not well behaved";
    } else {
        good = true;
    }

    if (!good && error != NULL && *err_msg == NULL) {
        format(err_msg, "%s: %s", name, error);
    }
    return good;
}

static PyObject *w_check_parstack_implementation_compatibility(
    PyObject *module, PyObject *args, PyObject *kwargs) {
    struct module_state *st = GETSTATE(module);
    int impl = IMPL_NP;
    static char *kwlist[] = {"impl"};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|i", kwlist, &impl)) {
        PyErr_SetString(
            st->error,
            "usage check_parstack_implementation_compatibility(impl)");
        return NULL;
    }
    int compatible = 1;
    if (impl == IMPL_CUDA || impl == IMPL_CUDA_THRUST ||
        impl == IMPL_CUDA_ATOMIC) {
#if defined(_CUDA)
        char *err_msg = NULL;
        int err = check_cuda_parstack_implementation_compatibility(
            impl, &compatible, &err_msg);
        if (err != 0) {
            return handle_error("check_parstack_implementation_compatibility()",
                                st->error, err_msg);
        }
#else
        compatible = 0;  // omp and numpy are always compatible
#endif
    }
    return Py_BuildValue("N", PyBool_FromLong(compatible));
}

static PyObject *w_calculate_parstack_kernel_parameters(PyObject *module,
                                                        PyObject *args,
                                                        PyObject *kwargs) {
    struct module_state *st = GETSTATE(module);
    size_t narrays, nshifts, nsamples, lengthout;
    int32_t offsetout;
    int impl = IMPL_CUDA;
    size_t target_block_threads = 256;
    size_t work_per_thread = 16;
    size_t shared_memory_per_thread = sizeof(float);

    static char *kwlist[] = {"narrays",
                             "nshifts",
                             "nsamples",
                             "lengthout",
                             "offsetout",
                             "impl",
                             "target_block_threads",
                             "work_per_thread",
                             "shared_memory_per_thread",
                             NULL};
    if (!PyArg_ParseTupleAndKeywords(
            args, kwargs, "nnnni|innn", kwlist, &narrays, &nshifts, &nsamples,
            &lengthout, &offsetout, &impl, &target_block_threads,
            &work_per_thread, &shared_memory_per_thread)) {
        PyErr_SetString(
            st->error,
            "usage calculate_parstack_kernel_parameters(narrays, nshifts, "
            "nsamples, lengthout, offsetout, impl, target_block_threads, "
            "work_per_thread, shared_memory_per_thread)");
        return NULL;
    }
#if defined(_CUDA)
    unsigned int grid[3] = {0, 0, 0};
    unsigned int blocks[3] = {0, 0, 0};
    size_t shared_memory;
    char *err_msg = NULL;
    int err = calculate_cuda_parstack_kernel_parameters(
        impl, narrays, nshifts, nsamples, lengthout, offsetout,
        target_block_threads, work_per_thread, shared_memory_per_thread, grid,
        blocks, &shared_memory, &err_msg);
    if (err != 0) {
        return handle_error("calculate_parstack_kernel_parameters()", st->error,
                            err_msg);
    }
    return Py_BuildValue("(III)(III)n", grid[0], grid[1], grid[2], blocks[0],
                         blocks[1], blocks[2], shared_memory);
#else
    PyErr_SetString(st->error, "pyrocko was not compiled with CUDA support");
    return NULL;
#endif
}

static PyObject *w_parstack(PyObject *module, PyObject *args,
                            PyObject *kwargs) {
    PyObject *arrays, *offsets, *shifts, *weights, *arr;
    PyObject *result;
    int method, nparallel, impl;
    size_t narrays, nshifts, nweights, target_block_threads;
    size_t *clengths;
    size_t lengthout;
    int32_t offsetout;
    int lengthout_arg;
    int32_t *coffsets, *cshifts;

    void *cweights = NULL;
    void *cresult = NULL;
    void **carrays = NULL;

    npy_intp array_dims[1];
    size_t i;
    int err;

    struct module_state *st = GETSTATE(module);

    static char *kwlist[] = {"arrays",
                             "offsets",
                             "shifts",
                             "weights",
                             "method",
                             "lengthout",
                             "offsetout",
                             "result",
                             "impl",
                             "nparallel",
                             "target_block_threads",
                             NULL};
    if (!PyArg_ParseTupleAndKeywords(
            args, kwargs, "OOOO|iiiOiin", kwlist, &arrays, &offsets, &shifts,
            &weights, &method, &lengthout_arg, &offsetout, &result, &impl,
            &nparallel, &target_block_threads)) {
        PyErr_SetString(
            st->error,
            "usage parstack(arrays, offsets, shifts, weights, method, "
            "lengthout, "
            "offsetout, result, impl, nparallel, target_block_threads)");

        return NULL;
    }

    char *err_msg = NULL;
    if (!good_array("offsets", offsets, NPY_INT32, &err_msg))
        return handle_error("parstack", PyExc_ValueError, err_msg);
    if (!good_array("shifts", shifts, NPY_INT32, &err_msg))
        return handle_error("parstack", PyExc_ValueError, err_msg);
    if (!good_array("weights", weights, NPY_FLOAT32, &err_msg) &&
        !good_array("weights", weights, NPY_FLOAT64, &err_msg))
        return handle_error("parstack", PyExc_ValueError, err_msg);

    int precision = PyArray_TYPE((PyArrayObject *)weights);
    int data_size = precision == NPY_FLOAT32 ? sizeof(float) : sizeof(double);

    coffsets = PyArray_DATA((PyArrayObject *)offsets);
    narrays = PyArray_SIZE((PyArrayObject *)offsets);

    cshifts = PyArray_DATA((PyArrayObject *)shifts);
    nshifts = PyArray_SIZE((PyArrayObject *)shifts);

    cweights = PyArray_DATA((PyArrayObject *)weights);
    nweights = PyArray_SIZE((PyArrayObject *)weights);

    nshifts /= narrays;
    nweights /= narrays;

    if (impl != IMPL_CUDA && impl != IMPL_OMP && impl != IMPL_CUDA_THRUST &&
        impl != IMPL_CUDA_ATOMIC) {
        PyErr_SetString(st->error, "unknown implementation");
        return NULL;
    }

    if (nshifts != nweights) {
        PyErr_SetString(st->error, "weights.size != shifts.size");
        return NULL;
    }

    if (!PyList_Check(arrays)) {
        PyErr_SetString(st->error, "arg #1 must be a list of NumPy arrays.");
        return NULL;
    }

    if ((size_t)PyList_Size(arrays) != narrays) {
        PyErr_SetString(st->error, "len(offsets) != len(arrays)");
        return NULL;
    }

    carrays = (void **)calloc(narrays, sizeof(void *));
    clengths = (size_t *)calloc(narrays, sizeof(size_t));
    if (clengths == NULL) {
        free(carrays);
        PyErr_SetString(st->error, "alloc failed");
        return NULL;
    }

    for (i = 0; i < narrays; i++) {
        arr = PyList_GetItem(arrays, i);
        if (!good_array("array", arr, precision, &err_msg)) {
            free(clengths);
            return handle_error("parstack", PyExc_ValueError, err_msg);
        }
        carrays[i] = PyArray_DATA((PyArrayObject *)arr);
        clengths[i] = PyArray_SIZE((PyArrayObject *)arr);
    }
    if (lengthout_arg < 0) {
        err = parstack_config(narrays, coffsets, clengths, nshifts, cshifts,
                              &lengthout, &offsetout);

        if (err != 0) {
            PyErr_SetString(st->error, "parstack_config() failed");
            free(carrays);
            free(clengths);
            return NULL;
        }
    } else {
        lengthout = (size_t)lengthout_arg;
    }

    if (method == 0) {
        array_dims[0] = nshifts * lengthout;
    } else {
        array_dims[0] = nshifts;
    }

    if (result != Py_None) {
        if (!good_array("result", result, precision, &err_msg)) {
            free(carrays);
            free(clengths);
            return handle_error("parstack", PyExc_ValueError, err_msg);
        }
        if (PyArray_SIZE((PyArrayObject *)result) != array_dims[0]) {
            free(carrays);
            free(clengths);
            if (method == 0) {
                PyErr_SetString(
                    PyExc_ValueError,
                    "result array size must match (nshifts, lengthout)");
            } else {
                PyErr_SetString(PyExc_ValueError,
                                "result array size must match (nshifts)");
            }
            return NULL;
        }
        cresult = PyArray_DATA((PyArrayObject *)result);
        Py_INCREF(result);
    } else {
        result = PyArray_SimpleNew(1, array_dims, precision);
        cresult = PyArray_DATA((PyArrayObject *)result);
        memset(cresult, 0, (size_t)array_dims[0] * data_size);
        if (result == NULL) {
            free(carrays);
            free(clengths);
            return NULL;
        }
    }
    err =
        parstack(narrays, carrays, coffsets, clengths, nshifts, cshifts,
                 cweights, method, lengthout, offsetout, cresult, (impl_t)impl,
                 nparallel, target_block_threads, precision, &err_msg);
    free(carrays);
    free(clengths);

    if (err != 0) {
        Py_DECREF(result);
        return handle_error("parstack()", st->error, err_msg);
    }
    return Py_BuildValue("Ni", (PyObject *)result, offsetout);
}

static PyMethodDef ParstackMethods[] = {
    {"parstack", (PyCFunction)w_parstack, METH_VARARGS | METH_KEYWORDS,
     "Parallel weight-and-delay stacking"},

    {"check_parstack_implementation_compatibility",
     (PyCFunction)w_check_parstack_implementation_compatibility, METH_VARARGS | METH_KEYWORDS,
     "Checks parstack implementation compatibility"},

    {"parstack_kernel_parameters",
     (PyCFunctionWithKeywords)w_calculate_parstack_kernel_parameters,
     METH_VARARGS | METH_KEYWORDS,
     "Computes parstack kernel launch parameters"},

    {NULL, NULL, 0, NULL} /* Sentinel */
};

#if PY_MAJOR_VERSION >= 3

static int parstack_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int parstack_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "parstack_ext",
        NULL,
        sizeof(struct module_state),
        ParstackMethods,
        NULL,
        parstack_ext_traverse,
        parstack_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_parstack_ext(void)

#else
#define INITERROR return

void
initparstack_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("parstack_ext", ParstackMethods);
#endif
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.parstack_ext.ParstackExtError", NULL, NULL);
    if (st->error == NULL){
        Py_DECREF(module);
        INITERROR;
    }

    long cuda_compiled = 0;
    #if defined(_CUDA)
    cuda_compiled = 1;
    #endif
    if (PyModule_AddIntConstant(module, CUDA_COMPILED_FLAG, cuda_compiled) < 0) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    if (PyModule_AddObject(module, "ParstackExtError", st->error) < 0) {
        Py_DECREF(module);
        Py_DECREF(st->error);
        INITERROR;
    }

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
