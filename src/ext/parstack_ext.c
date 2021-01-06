#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"
#include "ext.h"
#include "cuda/parstack.cuh"
#include "cuda/utils.cuh"
#include <stdlib.h>
#include <stdio.h>
#include <float.h>
#if defined(_OPENMP)
    # include <omp.h>
#endif

#define CHUNKSIZE 10

int parstack_config(
        size_t narrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        float *weights,
        int method,
        size_t *lengthout,
        int32_t *offsetout) {

    UNUSED(weights);
    UNUSED(method);

    if (narrays < 1) {
        return NODATA;
    }

    int32_t imin, imax, istart, iend;
    size_t iarray, ishift;

    imin = offsets[0] + shifts[0];
    imax = imin + lengths[0];
    for (iarray=0; iarray<narrays; iarray++) {
        for (ishift=0; ishift<nshifts; ishift++) {
            istart = offsets[iarray] + shifts[ishift*narrays + iarray];
            iend = istart + lengths[iarray];
            imin = min(imin, istart);
            imax = max(imax, iend);
        }
    }

    *lengthout = imax - imin;
    *offsetout = imin;

    return SUCCESS;
}

int parstack(
        size_t narrays,
        float **arrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        float *weights,
        int method,
        size_t lengthout,
        int32_t offsetout,
        float *result,
        impl_t impl,
        int nparallel,
        size_t target_block_threads,
        char **err) {
    int32_t imin, istart, ishift;
    size_t iarray, nsamp, i;
    float weight;
    int chunk;
    float *temp;
    float m;

    if (narrays < 1) {
        return NODATA;
    }

    if (nshifts > INT_MAX) {
        return INVALID;
    }

    int RET_CODE = SUCCESS;

    imin = offsetout;
    nsamp = lengthout;

    chunk = CHUNKSIZE;

    Py_BEGIN_ALLOW_THREADS if (impl == IMPL_CUDA || impl == IMPL_CUDA_THRUST ||
                               impl == IMPL_CUDA_ATOMIC) {
#if defined(_CUDA)
      if (!check_cuda_supported()) {
        fprintf(stderr, "no CUDA capable GPU device available");
        RET_CODE = ERROR;
      } else {
        RET_CODE = cuda_parstack(narrays, arrays, offsets, lengths, nshifts,
                                 shifts, weights, (uint8_t)method, lengthout,
                                 offsetout, result, impl, (uint8_t)nparallel,
                                 target_block_threads, err);
      }
#else
      fprintf(stderr, "pyrocko was compiled without CUDA support, please "
                      "recompile with CUDA");
      RET_CODE = ERROR;
#endif
    }
    else {
      if (method == 0) {
#if defined(_OPENMP)
#pragma omp parallel private(ishift, iarray, i, istart, weight)                \
    num_threads(nparallel)
#endif
        {
#if defined(_OPENMP)
#pragma omp for schedule(dynamic, chunk) nowait
#endif
          for (ishift = 0; ishift < (int32_t)nshifts; ishift++) {
            for (iarray = 0; iarray < narrays; iarray++) {
              istart = offsets[iarray] + shifts[ishift * narrays + iarray];
              weight = weights[ishift * narrays + iarray];
              if (weight != 0.0) {
                for (i = (size_t)max(0, imin - istart);
                     i < (size_t)max(
                             0, min(nsamp - istart + imin, lengths[iarray]));
                     i++) {
                  result[ishift * nsamp + istart - imin + i] +=
                      arrays[iarray][i] * weight;
                }
              }
            }
          }
        }
      } else if (method == 1) {
#if defined(_OPENMP)
#pragma omp parallel private(ishift, iarray, i, istart, weight, temp, m)
#endif
          {
            temp = (float*)calloc(nsamp, sizeof(float));
#if defined(_OPENMP)
#pragma omp for schedule(dynamic,chunk) nowait
#endif
            for (ishift=0; ishift<(int32_t)nshifts; ishift++) {
              for (i=0; i<nsamp; i++) {
                temp[i] = 0.0;
              }
              for (iarray=0; iarray<narrays; iarray++) {
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                weight = weights[ishift*narrays + iarray];
                if (weight != 0.0) {
                  for (i=(size_t)max(0, imin - istart); i<(size_t)max(0, min(nsamp - istart + imin, lengths[iarray])); i++) {
                    temp[istart-imin+i] += arrays[iarray][i] * weight;
                  }
                }
              }
              m = 0.;
              for (i=0; i<nsamp; i++) {
                //m += temp[i]*temp[i];
                m = fmax(m, temp[i]);
              }
              result[ishift] = m;
            }
            free(temp);
          }
        }
    }
    Py_END_ALLOW_THREADS
    return RET_CODE;
}

int good_array(char *name, PyObject* o, int typenum) {
    int good = 0;
    char *error;
    if (!PyArray_Check(o)) {
        error = "not a NumPy array";
    }
    else if (PyArray_TYPE((PyArrayObject*)o) != typenum) {
        error = "array of unexpected type";
    }
    else if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        error = "array is not contiguous or not well behaved";
    } else {
        good = 1;
    }

    if (!good) {
        size_t len = snprintf(NULL, 0, "%s: %s", name, error);
        char *msg = malloc(len + 1);
        snprintf(msg, len + 1, "%s: %s", name, error);
        PyErr_SetString(PyExc_ValueError, msg);
        free(msg);
    }
    return good;
}

static PyObject *w_check_parstack_implementation_compatibility(PyObject *module,
                                                               PyObject *args,
                                                               PyObject *kwargs) {
  struct module_state *st = GETSTATE(module);
  int impl = IMPL_NP;
  static char *kwlist[] = {"impl"};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|i", kwlist, &impl)) {
    PyErr_SetString(st->error,
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
      return handle_error("check_parstack_implementation_compatibility()", st,
                          err_msg);
    }
#else
    compatible = 0; // omp and numpy are compatible
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
    return handle_error("calculate_parstack_kernel_parameters()", st, err_msg);
  }
  return Py_BuildValue("(III)(III)n", grid[0], grid[1], grid[2], blocks[0],
                       blocks[1], blocks[2], shared_memory);
#else
  PyErr_SetString(st->error, "pyrocko was not compiled with CUDA support");
  return NULL;
#endif
}

static PyObject* w_parstack(PyObject *module, PyObject *args, PyObject *kwargs) {

    PyObject *arrays, *offsets, *shifts, *weights, *arr;
    PyObject *result;
    int method, nparallel, impl;
    size_t narrays, nshifts, nweights, target_block_threads;
    size_t *clengths;
    size_t lengthout;
    int32_t offsetout;
    int lengthout_arg;
    int32_t *coffsets, *cshifts;
    float *cweights, *cresult;
    float **carrays;
    npy_intp array_dims[1];
    size_t i;
    int err;

    carrays = NULL;
    clengths = NULL;
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
          "usage parstack(arrays, offsets, shifts, weights, method, lengthout, "
          "offsetout, result, impl, nparallel, target_block_threads)");

      return NULL;
    }

    if (!good_array("offsets", offsets, NPY_INT32)) return NULL;
    if (!good_array("shifts", shifts, NPY_INT32)) return NULL;
    if (!good_array("weights", weights, NPY_FLOAT32)) return NULL;
    if (result != Py_None && !good_array("result", result, NPY_FLOAT32)) return NULL;

    coffsets = PyArray_DATA((PyArrayObject*)offsets);
    narrays = PyArray_SIZE((PyArrayObject*)offsets);

    cshifts = PyArray_DATA((PyArrayObject*)shifts);
    nshifts = PyArray_SIZE((PyArrayObject*)shifts);

    cweights = PyArray_DATA((PyArrayObject*)weights);
    nweights = PyArray_SIZE((PyArrayObject*)weights);

    nshifts /= narrays;
    nweights /= narrays;

    if (impl != IMPL_CUDA && impl != IMPL_OMP && impl != IMPL_CUDA_THRUST &&
        impl != IMPL_CUDA_ATOMIC) {
      PyErr_SetString(st->error, "unknown implementation");
      return NULL;
    }

    if (nshifts != nweights) {
        PyErr_SetString(st->error, "weights.size != shifts.size" );
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

    carrays = (float**)calloc(narrays, sizeof(float*));
    if (carrays == NULL) {
        PyErr_SetString(st->error, "alloc failed");
        return NULL;
    }

    clengths = (size_t*)calloc(narrays, sizeof(size_t));
    if (clengths == NULL) {
        PyErr_SetString(st->error, "alloc failed");
        free(carrays);
        return NULL;
    }

    for (i=0; i<narrays; i++) {
        arr = PyList_GetItem(arrays, i);
        if (!good_array("array", arr, NPY_FLOAT32)) {
            free(carrays);
            free(clengths);
            return NULL;
        }
        carrays[i] = PyArray_DATA((PyArrayObject*)arr);
        clengths[i] = PyArray_SIZE((PyArrayObject*)arr);
    }
    if (lengthout_arg < 0) {
        err = parstack_config(narrays, coffsets, clengths, nshifts, cshifts,
                              cweights, method, &lengthout, &offsetout);

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
        if (PyArray_SIZE((PyArrayObject*)result) != array_dims[0]) {
            free(carrays);
            free(clengths);
            return NULL;
        }
        Py_INCREF(result);
    } else {
        result = PyArray_SimpleNew(1, array_dims, NPY_FLOAT32);
        cresult = PyArray_DATA((PyArrayObject*)result);

        memset(cresult, 0, (size_t)array_dims[0] * sizeof(float));

        if (result == NULL) {
            free(carrays);
            free(clengths);
            return NULL;
        }
    }
    cresult = PyArray_DATA((PyArrayObject*)result);

    char *err_msg = NULL;
    err = parstack(narrays, carrays, coffsets, clengths, nshifts, cshifts,
                   cweights, method, lengthout, offsetout, cresult, (impl_t)impl, nparallel, target_block_threads, &err_msg);

    free(carrays);
    free(clengths);

    if (err != 0) {
        Py_DECREF(result);
        return handle_error("parstack()", st, err_msg);
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
