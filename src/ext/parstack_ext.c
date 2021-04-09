#define NPY_NO_DEPRECATED_API 7


#include "Python.h"
#include "numpy/arrayobject.h"

#include <stdlib.h>
#if defined(_OPENMP)
    # include <omp.h>
#endif
#include <stdio.h>
#include <float.h>

#define CHUNKSIZE 10
#define NBLOCK 64

struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
#define GETSTATE(m) (&_state); (void) m;
static struct module_state _state;
#endif

int parstack_config(
        size_t narrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        double *weights,
        int method,
        size_t *lengthout,
        int32_t *offsetout);

int parstack(
        size_t narrays,
        double **arrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        double *weights,
        int method,
        size_t lengthout,
        int32_t offsetout,
        double *result,
        int nparallel);


int32_t i32min(int32_t a, int32_t b) {
    return (a < b) ? a : b;
}

size_t smin(size_t a, size_t b) {
    return (a < b) ? a : b;
}

int32_t i32max(int32_t a, int32_t b) {
    return (a > b) ? a : b;
}

double dmax(double a, double b) {
    return (a > b) ? a : b;
}

#define SUCCESS 0
#define NODATA 1
#define INVALID 2

int parstack_config(
        size_t narrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        double *weights,
        int method,
        size_t *lengthout,
        int32_t *offsetout) {

    (void)weights;  /* silence warnings */
    (void)method;

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
            imin = i32min(imin, istart);
            imax = i32max(imax, iend);
        }
    }

    *lengthout = imax - imin;
    *offsetout = imin;

    return SUCCESS;
}

int parstack(
        size_t narrays,
        double **arrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
        double *weights,
        int method,
        size_t lengthout,
        int32_t offsetout,
        double *result,
        int nparallel) {

	(void) nparallel;
    int32_t imin, istart, ishift;
    size_t iarray, nsamp, i;
    double weight;
    int chunk;
    double *temp;
    double m;

    if (narrays < 1) {
        return NODATA;
    }

    if (nshifts > INT_MAX) {
        return INVALID;
    }

    imin = offsetout;
    nsamp = lengthout;

    chunk = CHUNKSIZE;

    Py_BEGIN_ALLOW_THREADS
    if (method == 0) {
	#if defined(_OPENMP)
        #pragma omp parallel private(ishift, iarray, i, istart, weight) num_threads(nparallel)
	#endif
        {

	#if defined(_OPENMP)
        #pragma omp for schedule(dynamic, chunk) nowait
	#endif
        for (ishift=0; ishift<(int32_t)nshifts; ishift++) {
            for (iarray=0; iarray<narrays; iarray++) {
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                weight = weights[ishift*narrays + iarray];
                if (weight != 0.0) {
                    for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                        result[ishift*nsamp + istart-imin+i] += arrays[iarray][i] * weight;
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
        temp = (double*)calloc(nsamp, sizeof(double));
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
                    for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                        temp[istart-imin+i] += arrays[iarray][i] * weight;
                    }
                }
            }
            m = 0.;
            for (i=0; i<nsamp; i++) {
                //m += temp[i]*temp[i];
                m = dmax(m, temp[i]);
            }
            result[ishift] = m;
        }
        free(temp);
        }
    }
    Py_END_ALLOW_THREADS
    return SUCCESS;
}


int argmax(double *arrayin, uint32_t *arrayout, size_t nx, size_t ny, int nparallel){

    size_t ix, iy, ix_offset, imax[NBLOCK];
    double vmax[NBLOCK];
	(void) nparallel;

    Py_BEGIN_ALLOW_THREADS

    #if defined(_OPENMP)
        #pragma omp parallel private(iy, ix_offset, imax, vmax) num_threads(nparallel)
    #endif
        {

    #if defined(_OPENMP)
        #pragma omp for schedule(dynamic, 1) nowait
    #endif
    for (ix=0; ix<nx; ix+=NBLOCK){
        for (ix_offset=0; ix_offset<smin(NBLOCK, nx-ix); ix_offset++) {
            imax[ix_offset] = 0;
            vmax[ix_offset] = DBL_MIN;
        }
        for (iy=0; iy<ny; iy++){
            for (ix_offset=0; ix_offset<smin(NBLOCK, nx-ix); ix_offset++) {
                if (arrayin[iy*nx + ix + ix_offset] > vmax[ix_offset]){
                    vmax[ix_offset] = arrayin[iy*nx + ix + ix_offset];
                    imax[ix_offset] = iy;
                }
            }
        }
        for (ix_offset=0; ix_offset<smin(NBLOCK, nx-ix); ix_offset++) {
            arrayout[ix+ix_offset] = (uint32_t)imax[ix_offset];
        }
    }
    }

    Py_END_ALLOW_THREADS

    return SUCCESS;
}


int good_array(PyObject* o, int typenum) {
    if (!PyArray_Check(o)) {
        PyErr_SetString(PyExc_ValueError, "not a NumPy array" );
        return 0;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != typenum) {
        PyErr_SetString(PyExc_ValueError, "array of unexpected type");
        return 0;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_ValueError, "array is not contiguous or not well behaved");
        return 0;
    }

    return 1;
}

static PyObject* w_parstack(PyObject *module, PyObject *args) {

    PyObject *arrays, *offsets, *shifts, *weights, *arr;
    PyObject *result;
    int method, nparallel;
    size_t narrays, nshifts, nweights;
    size_t *clengths;
    size_t lengthout;
    int32_t offsetout;
    int lengthout_arg;
    int32_t *coffsets, *cshifts;
    double *cweights, *cresult;
    double **carrays;
    npy_intp array_dims[1];
    size_t i;
    int err;

    carrays = NULL;
    clengths = NULL;
    struct module_state *st = GETSTATE(module);

    if (!PyArg_ParseTuple(args, "OOOOiiiOi", &arrays, &offsets, &shifts,
                          &weights, &method, &lengthout_arg, &offsetout, &result, &nparallel)) {

        PyErr_SetString(
            st->error,
            "usage parstack(arrays, offsets, shifts, weights, method, lengthout, offsetout, result, nparallel)" );

        return NULL;
    }
    if (!good_array(offsets, NPY_INT32)) return NULL;
    if (!good_array(shifts, NPY_INT32)) return NULL;
    if (!good_array(weights, NPY_DOUBLE)) return NULL;
    if (result != Py_None && !good_array(result, NPY_DOUBLE)) return NULL;

    coffsets = PyArray_DATA((PyArrayObject*)offsets);
    narrays = PyArray_SIZE((PyArrayObject*)offsets);

    cshifts = PyArray_DATA((PyArrayObject*)shifts);
    nshifts = PyArray_SIZE((PyArrayObject*)shifts);

    cweights = PyArray_DATA((PyArrayObject*)weights);
    nweights = PyArray_SIZE((PyArrayObject*)weights);

    nshifts /= narrays;
    nweights /= narrays;

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

    carrays = (double**)calloc(narrays, sizeof(double*));
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
        if (!good_array(arr, NPY_DOUBLE)) {
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
        result = PyArray_SimpleNew(1, array_dims, NPY_FLOAT64);
        cresult = PyArray_DATA((PyArrayObject*)result);

        for (i=0; i<(size_t)array_dims[0]; i++) {
            cresult[i] = 0.0;
        }

        if (result == NULL) {
            free(carrays);
            free(clengths);
            return NULL;
        }
    }
    cresult = PyArray_DATA((PyArrayObject*)result);

    err = parstack(narrays, carrays, coffsets, clengths, nshifts, cshifts,
                   cweights, method, lengthout, offsetout, cresult, nparallel);

    if (err != 0) {
        PyErr_SetString(st->error, "parstack() failed");
        free(carrays);
        free(clengths);
        Py_DECREF(result);
        return NULL;
    }

    free(carrays);
    free(clengths);
    return Py_BuildValue("Ni", (PyObject *)result, offsetout);
}

static PyObject* w_argmax(PyObject *module, PyObject *args) {
    PyObject *arrayin;
    PyObject *result;
    double *carrayin;
    uint32_t *cresult;
    npy_intp *shape, shapeout[1];
    size_t i, ndim;
    int err, nparallel;
    struct module_state *st = GETSTATE(module);

    if (!PyArg_ParseTuple(args, "Oi", &arrayin, &nparallel)) {
        PyErr_SetString(st->error, "usage argmax(array)");
        return NULL;
    }

    if (!good_array(arrayin, NPY_DOUBLE)) return NULL;

    shape = PyArray_DIMS((PyArrayObject*)arrayin);
    ndim = PyArray_NDIM((PyArrayObject*)arrayin);

    if (ndim != 2){
        PyErr_SetString(st->error, "array shape is not 2D");
        return NULL;
    }

    carrayin = PyArray_DATA((PyArrayObject*)arrayin);

    if ((size_t)shape[0] >= (size_t)UINT32_MAX) {
        PyErr_SetString(st->error, "shape[0] must be smaller than 2^32");
        return NULL;
    }

    shapeout[0] = shape[1];

    result = PyArray_SimpleNew(1, shapeout, NPY_UINT32);
    cresult = PyArray_DATA((PyArrayObject*)result);

    for (i=0; i<(size_t)shapeout[0]; i++){
        cresult[i] = 0;
    }

    err = argmax(carrayin, cresult, (size_t)shape[1], (size_t)shape[0], nparallel);

    if(err != 0){
        Py_DECREF(result);
        return NULL;
    }

    return Py_BuildValue("N", (PyObject *)result);
}


static PyMethodDef ParstackMethods[] = {
    {"parstack",  (PyCFunction) w_parstack, METH_VARARGS,
        "Parallel weight-and-delay stacking" },

    {"argmax", (PyCFunction) w_argmax, METH_VARARGS,
        "argmax of 2D numpy array along axis=0" },

    {NULL, NULL, 0, NULL}        /* Sentinel */
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

    Py_INCREF(st->error);
    PyModule_AddObject(module, "ParstackExtError", st->error);

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
