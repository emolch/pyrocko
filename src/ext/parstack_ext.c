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

#define BAD_ARRAY 1
#define BAD_DTYPE 2
#define BAD_ALIGNMENT 3

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

int parstack_config(
        size_t narrays,
        int32_t *offsets,
        size_t *lengths,
        size_t nshifts,
        int32_t *shifts,
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

int parstackf(
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
        int nparallel);


static int32_t i32min(int32_t a, int32_t b) {
    return (a < b) ? a : b;
}

static size_t smin(size_t a, size_t b) {
    return (a < b) ? a : b;
}

static int32_t i32max(int32_t a, int32_t b) {
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
        size_t *lengthout,
        int32_t *offsetout) {

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

int parstackf(
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
        int nparallel) {

	(void) nparallel;
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
                weight = weights[ishift*narrays + iarray];
                if (weight == 0.0)
                    continue;
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                #if defined(_OPENMP)
                    #pragma omp simd
                #endif
                for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                    result[ishift*nsamp + istart-imin+i] += arrays[iarray][i] * weight;
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
                weight = weights[ishift*narrays + iarray];
                if (weight == 0.0)
                    continue;
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                #if defined(_OPENMP)
                    #pragma omp simd
                #endif
                for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                    temp[istart-imin+i] += arrays[iarray][i] * weight;
                }
            }
            m = 0.;
            for (i=0; i<nsamp; i++) {
                //m += temp[i]*temp[i];
                m = fmaxf(m, temp[i]);
            }
            result[ishift] = m;
        }
        free(temp);
        }
    }
    Py_END_ALLOW_THREADS
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
                weight = weights[ishift*narrays + iarray];
                if (weight == 0.0)
                    continue;
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                #if defined(_OPENMP)
                    #pragma omp simd
                #endif
                for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                    result[ishift*nsamp + istart-imin+i] += arrays[iarray][i] * weight;
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
                weight = weights[ishift*narrays + iarray];
                if (weight == 0.0)
                    continue;
                istart = offsets[iarray] + shifts[ishift*narrays + iarray];
                #if defined(_OPENMP)
                    #pragma omp simd
                #endif
                for (i=(size_t)i32max(0, imin - istart); i<(size_t)i32max(0, i32min(nsamp - istart + imin, lengths[iarray])); i++) {
                    temp[istart-imin+i] += arrays[iarray][i] * weight;
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
                if (arrayin[iy*nx + ix + ix_offset] > vmax[ix_offset]) {
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


int bad_array(PyObject* o, int type_num, char* name) {
    if (!PyArray_Check(o)) {
        PyErr_Format(PyExc_ValueError, "%s not a NumPy array", name);
        return BAD_ARRAY;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_Format(PyExc_ValueError, "%s array is not contiguous or not well behaved", name);
        return BAD_ALIGNMENT;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != type_num) {
        PyErr_Format(PyExc_ValueError, "%s array of unexpected dtype", name);
        return BAD_DTYPE;
    }

    return SUCCESS;
}

static PyObject* w_parstack(PyObject *module, PyObject *args, PyObject *kwds){

    PyObject *arrays, *offsets, *shifts, *weights, *arr;
    PyObject *result = Py_None;
    int method;
    int nparallel = 1;
    size_t narrays, nshifts, nweights;
    size_t *clengths;
    size_t lengthout;
    int32_t offsetout;
    int lengthout_arg;
    int32_t *coffsets, *cshifts;
    void **carrays;
    void *cresult;
    npy_intp array_dims[1];
    size_t i;
    int err = 0;

    carrays = NULL;
    clengths = NULL;
    struct module_state *st = GETSTATE(module);

    static char *kwlist[] = {"arrays", "offsets", "shifts", "weights", "method", "lengthout", "offsetout", "result", "nparallel", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "OOOOiii|Oi", kwlist, &arrays, &offsets, &shifts,
                                     &weights, &method, &lengthout_arg, &offsetout, &result, &nparallel))
        return NULL;
    if (!PyArray_Check(weights)) {
        PyErr_SetString(PyExc_ValueError, "weights is not a NumPy array");
        return NULL;
    }

    int dtype = PyArray_TYPE((PyArrayObject*)weights);
    if (dtype != NPY_FLOAT && dtype != NPY_DOUBLE) {
        PyErr_SetString(PyExc_ValueError, "Bad dtype, only float64 and float32 is supported.");
        return NULL;
    }
    if (bad_array(weights, dtype, "weights")) return NULL;

    if (bad_array(offsets, NPY_INT32, "offsets")) return NULL;
    if (bad_array(shifts, NPY_INT32, "shifts")) return NULL;

    if (result != Py_None && bad_array(result, dtype, "result")) return NULL;

    coffsets = PyArray_DATA((PyArrayObject*)offsets);
    narrays = PyArray_SIZE((PyArrayObject*)offsets);

    cshifts = PyArray_DATA((PyArrayObject*)shifts);
    nshifts = PyArray_SIZE((PyArrayObject*)shifts);

    nweights = PyArray_SIZE((PyArrayObject*)weights);

    nshifts /= narrays;
    nweights /= narrays;

    if (nshifts != nweights) {
        PyErr_SetString(st->error, "weights.size != shifts.size" );
        return NULL;
    }

    if (!PyList_Check(arrays)) {
        PyErr_SetString(st->error, "arrays must be a list of NumPy arrays.");
        return NULL;
    }

    if ((size_t)PyList_Size(arrays) != narrays) {
        PyErr_SetString(st->error, "len(offsets) != len(arrays)");
        return NULL;
    }

    carrays = (void**)calloc(narrays, sizeof(void *));
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
        if (bad_array(arr, dtype, "arrays")) {
            goto cleanup;
        }
        carrays[i] = PyArray_DATA((PyArrayObject*)arr);
        clengths[i] = PyArray_SIZE((PyArrayObject*)arr);
    }
    if (lengthout_arg < 0) {
        if (parstack_config(narrays, coffsets, clengths, nshifts, cshifts,
                            &lengthout, &offsetout)) {
            PyErr_SetString(st->error, "parstack_config() failed");
            goto cleanup;
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
            PyErr_SetString(st->error, "results is of unexpected size");
            goto cleanup;
        }
        Py_INCREF(result);
    } else {
        result = PyArray_ZEROS(1, array_dims, dtype, 0);
        if (result == NULL) {
            PyErr_SetString(st->error, "cannot allocate result");
            goto cleanup;
        }
    }
    cresult = PyArray_DATA((PyArrayObject*)result);

    if (dtype == NPY_FLOAT) {
        err = parstackf(narrays, (float **) carrays, coffsets, clengths, nshifts, cshifts,
                    PyArray_DATA((PyArrayObject*)weights), method, lengthout, offsetout, (float *) cresult, nparallel);
    } else if (dtype == NPY_DOUBLE) {
        err = parstack(narrays, (double**) carrays, coffsets, clengths, nshifts, cshifts,
                    PyArray_DATA((PyArrayObject*)weights), method, lengthout, offsetout, (double *) cresult, nparallel);
    }



    if (err != 0) {
        PyErr_SetString(st->error, "parstack() failed");
        Py_DECREF(result);
        goto cleanup;
    }

    free(carrays);
    free(clengths);
    return Py_BuildValue("Ni", (PyObject *)result, offsetout);

    cleanup:
        free(carrays);
        free(clengths);
        return NULL;

}

static PyObject* w_argmax(PyObject *module, PyObject *args, PyObject *kwds) {
    PyObject *arrayin;
    PyObject *result;
    double *carrayin;
    uint32_t *cresult;
    npy_intp *shape, shapeout[1];
    size_t i, ndim;
    int err;
    int nparallel = 1;
    struct module_state *st = GETSTATE(module);

    static char *kwlist[] = {"array", "nparallel", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|i", kwlist, &arrayin, &nparallel))
        return NULL;

    if (bad_array(arrayin, NPY_DOUBLE, "array")) return NULL;

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
    {"parstack", (PyCFunction)(void(*)(void))w_parstack, METH_VARARGS | METH_KEYWORDS,
        "Parallel weight-and-delay stacking" },

    {"argmax", (PyCFunction)(void(*)(void))w_argmax, METH_VARARGS | METH_KEYWORDS,
        "argmax of 2D numpy array along axis=0" },

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


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
        "C-extension supporting :py:mod:`pyrocko.parstack`.",
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


{
    PyObject *module = PyModule_Create(&moduledef);
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

    return module;
}
