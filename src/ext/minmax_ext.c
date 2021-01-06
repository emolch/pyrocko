#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "cuda/minmax.cuh"
#include "cuda/utils.cuh"
#include "ext.h"
#include "numpy/arrayobject.h"
#include <float.h>
#include <stdio.h>
#include <stdlib.h>
#if defined(_OPENMP)
#include <omp.h>
#endif

#define NBLOCK 64

int minmax(double *arrayin, uint32_t *iarrayout, double *varrayout,
           uint8_t axis, size_t nx, size_t ny, int nparallel,
           minmax_type_t type) {
  UNUSED(nparallel);
  size_t irdc, rdc_size, iout, iout_offset, iout_size, idx[NBLOCK];
  double vals[NBLOCK];

  if (axis == 0) {
    rdc_size = ny;
    iout_size = nx;
  } else {
    rdc_size = nx;
    iout_size = ny;
  }

#if defined(_OPENMP)
#pragma omp parallel private(irdc, iout_offset, idx, vals)                     \
    num_threads(nparallel)
#endif
  {
#if defined(_OPENMP)
#pragma omp for schedule(dynamic, 1) nowait
#endif
    for (iout = 0; iout < iout_size; iout += NBLOCK) {
      for (iout_offset = 0;
           iout_offset < (size_t)min((size_t)NBLOCK, iout_size - iout);
           iout_offset++) {
        idx[iout_offset] = 0;
        vals[iout_offset] = (type == ARGMAX || type == MAX) ? DBL_MIN : DBL_MAX;
      }
      for (irdc = 0; irdc < rdc_size; irdc++) {
        for (iout_offset = 0;
             iout_offset < (size_t)min((size_t)NBLOCK, iout_size - iout);
             iout_offset++) {
          double val;
          if (axis == 1)
            val = arrayin[(iout + iout_offset) * rdc_size + irdc];
          else
            val = arrayin[irdc * iout_size + (iout + iout_offset)];
          int equal = (val == vals[iout_offset]) && (irdc < idx[iout_offset]);
          if ((type == ARGMAX || type == MAX) &&
              ((val > vals[iout_offset]) || equal)) {
            vals[iout_offset] = val;
            idx[iout_offset] = irdc;
          } else if ((type == ARGMIN || type == MIN) &&
                     ((val < vals[iout_offset]) || equal)) {
            vals[iout_offset] = val;
            idx[iout_offset] = irdc;
          }
        }
      }
      for (iout_offset = 0;
           iout_offset < (size_t)min((size_t)NBLOCK, iout_size - iout);
           iout_offset++) {
        if (type == ARGMAX || type == ARGMIN)
          iarrayout[iout + iout_offset] = (uint32_t)idx[iout_offset];
        else
          varrayout[iout + iout_offset] = vals[iout_offset];
      }
    }
  }
  return SUCCESS;
}

int good_array(char *name, PyObject *o, int typenum) {
  int good = 0;
  char *error;
  if (!PyArray_Check(o)) {
    error = "not a NumPy array";
  } else if (PyArray_TYPE((PyArrayObject *)o) != typenum) {
    error = "array of unexpected type";
  } else if (!PyArray_ISCARRAY((PyArrayObject *)o)) {
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

static PyObject *w_minmax_kernel_parameters(PyObject *module, PyObject *args,
                                            PyObject *kwargs) {
  struct module_state *st = GETSTATE(module);
  size_t cols, rows;
  int axis = 0;
  int impl = 0;
  size_t target_block_threads = 256;
  size_t work_per_thread = 32;
  size_t shared_memory_per_thread = sizeof(double) + sizeof(uint32_t);

  static char *kwlist[] = {"cols",
                           "rows",
                           "axis",
                           "impl",
                           "target_block_threads",
                           "work_per_thread",
                           "shared_memory_per_thread",
                           NULL};
  if (!PyArg_ParseTupleAndKeywords(
          args, kwargs, "nn|iinnn", kwlist, &cols, &rows, &axis, &impl,
          &target_block_threads, &work_per_thread, &shared_memory_per_thread)) {
    PyErr_SetString(st->error,
                    "usage minmax_kernel_parameters(cols, rows, axis,"
                    "impl, target_block_threads, work_per_thread, "
                    "shared_memory_per_thread)");
    return NULL;
  }

  if (axis != 0 && axis != 1) {
    PyErr_SetString(st->error, "axis for 2D array must be either 0 or 1");
    return NULL;
  }
#if defined(_CUDA)
  unsigned int grid[3] = {0, 0, 0};
  unsigned int blocks[3] = {0, 0, 0};
  size_t shared_memory;
  char *err_msg = NULL;
  int err = calculate_cuda_minmax_kernel_parameters(
      rows, cols, (uint8_t)axis, impl, target_block_threads, work_per_thread,
      shared_memory_per_thread, grid, blocks, &shared_memory, &err_msg);
  if (err != SUCCESS) {
    return handle_error("minmax_kernel_parameters()", st, err_msg);
  }
  return Py_BuildValue("(III)(III)n", grid[0], grid[1], grid[2], blocks[0],
                       blocks[1], blocks[2], shared_memory);
#else
  PyErr_SetString(st->error, "pyrocko was not compiled with CUDA support");
  return NULL;
#endif
}

static PyObject *w_minmax(PyObject *module, PyObject *args, PyObject *kwargs) {
  struct module_state *st = GETSTATE(module);
  PyObject *arrayin;
  PyObject *result;

  double *carrayin;
  uint32_t *ciresult = NULL;
  double *cvresult = NULL;

  npy_intp *shape, shapeout[1];
  size_t ndim;

  int type = ARGMAX;
  int axis = 0;
  int nparallel = 1;
  int impl = IMPL_CUDA;
  size_t target_block_threads = 256;

  static char *kwlist[] = {"array",     "typ",  "axis",
                           "nparallel", "impl", "target_block_threads",
                           NULL};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|iiiin", kwlist, &arrayin,
                                   &type, &axis, &nparallel, &impl,
                                   &target_block_threads)) {
    PyErr_SetString(st->error, "usage minmax(array, typ, axis, nparallel, "
                               "impl, target_block_threads)");
    return NULL;
  }

  if (!good_array("array", arrayin, NPY_DOUBLE))
    return NULL;

  shape = PyArray_DIMS((PyArrayObject *)arrayin);
  ndim = PyArray_NDIM((PyArrayObject *)arrayin);

  if (ndim != 2) {
    PyErr_SetString(st->error, "array shape is not 2D");
    return NULL;
  }

  if (axis != 0 && axis != 1) {
    PyErr_SetString(st->error, "array axis for 2D array must be either 0 or 1");
    return NULL;
  }

  carrayin = PyArray_DATA((PyArrayObject *)arrayin);

  size_t rows, cols, max_idx;
  rows = (size_t)shape[0];
  cols = (size_t)shape[1];
  shapeout[0] = (axis == 0) ? cols : rows;
  max_idx = (axis == 0) ? rows : cols;

  if (max_idx >= (size_t)UINT32_MAX) {
    PyErr_SetString(
        st->error,
        "indices of the dimension to be aggregated must be smaller than 2^32");
    return NULL;
  }

  if (type == ARGMAX || type == ARGMIN) {
    result = PyArray_SimpleNew(1, shapeout, NPY_UINT32);
    ciresult = PyArray_DATA((PyArrayObject *)result);
    memset(ciresult, 0, shapeout[0] * sizeof(uint32_t));
  } else {
    result = PyArray_SimpleNew(1, shapeout, NPY_DOUBLE);
    cvresult = PyArray_DATA((PyArrayObject *)result);
    memset(cvresult, 0, shapeout[0] * sizeof(double));
  }

  int RET_CODE = SUCCESS;
  char *err_msg = NULL;

  Py_BEGIN_ALLOW_THREADS if (impl == IMPL_CUDA || impl == IMPL_CUDA_THRUST ||
                             impl == IMPL_CUDA_ATOMIC) {
#if defined(_CUDA)
    if (!check_cuda_supported()) {
      fprintf(stderr, "no CUDA capable GPU device available");
      RET_CODE = ERROR;
    } else {
      RET_CODE = cuda_minmax(carrayin, cvresult, ciresult, axis, type, cols,
                             rows, impl, target_block_threads, &err_msg);
    }
#else
    fprintf(stderr, "pyrocko was compiled without CUDA support, please "
                    "recompile with CUDA");
    RET_CODE = ERROR;
#endif
  }
  else {
    RET_CODE =
        minmax(carrayin, ciresult, cvresult, axis, cols, rows, nparallel, type);
  }
  Py_END_ALLOW_THREADS

      if (RET_CODE != SUCCESS) {
    Py_DECREF(result);
    return handle_error("minmax()", st, err_msg);
  }

  return Py_BuildValue("N", (PyObject *)result);
}

static PyMethodDef MinmaxMethods[] = {
    {"minmax", (PyCFunction)w_minmax, METH_VARARGS | METH_KEYWORDS,
     "(arg) min/max for 2D numpy arrays"},

    {"minmax_kernel_parameters",
     (PyCFunctionWithKeywords)w_minmax_kernel_parameters,
     METH_VARARGS | METH_KEYWORDS, "minmax cuda kernel launch paramters"},

    {NULL, NULL, 0, NULL} /* Sentinel */
};

#if PY_MAJOR_VERSION >= 3

static int minmax_ext_traverse(PyObject *m, visitproc visit, void *arg) {
  Py_VISIT(GETSTATE(m)->error);
  return 0;
}

static int minmax_ext_clear(PyObject *m) {
  Py_CLEAR(GETSTATE(m)->error);
  return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,       "minmax_ext",     NULL,
    sizeof(struct module_state), MinmaxMethods,    NULL,
    minmax_ext_traverse,         minmax_ext_clear, NULL};

#define INITERROR return NULL

PyMODINIT_FUNC PyInit_minmax_ext(void)

#else
#define INITERROR return

void initminmax_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
  PyObject *module = PyModule_Create(&moduledef);
#else
  PyObject *module = Py_InitModule("minmax_ext", MaxMethods);
#endif
  import_array();

  if (module == NULL)
    INITERROR;
  struct module_state *st = GETSTATE(module);

  st->error =
      PyErr_NewException("pyrocko.minmax_ext.MinmaxExtError", NULL, NULL);
  if (st->error == NULL) {
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

  PyModule_AddIntConstant(module, "MIN", MIN);
  PyModule_AddIntConstant(module, "MAX", MAX);
  PyModule_AddIntConstant(module, "ARGMIN", ARGMIN);
  PyModule_AddIntConstant(module, "ARGMAX", ARGMAX);

  Py_INCREF(st->error);
  if (PyModule_AddObject(module, "MinmaxExtError", st->error) < 0) {
    Py_DECREF(module);
    Py_DECREF(st->error);
    INITERROR;
  }

#if PY_MAJOR_VERSION >= 3
  return module;
#endif
}
