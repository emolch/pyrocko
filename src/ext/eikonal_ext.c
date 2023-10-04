
#define NPY_NO_DEPRECATED_API 7

#define SQR(a)  ( (a) * (a) )

#include "Python.h"
#include "numpy/arrayobject.h"

#if defined(_OPENMP)
    #include <omp.h>
#endif

#include <limits.h>
#include <float.h>

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

int good_array(
        PyObject* o,
        int typenum_want,
        npy_intp size_want,
        int ndim_want,
        npy_intp* shape_want,
        char *name) {

    int i;

    if (!PyArray_Check(o)) {
        PyErr_Format(
            PyExc_AttributeError,
            "%s not a NumPy array", name);
        return 0;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != typenum_want) {
        PyErr_Format(
            PyExc_AttributeError,
            "array %s of unexpected type", name);
        return 0;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_Format(
            PyExc_AttributeError,
            "array %s is not contiguous or not well behaved", name);
        return 0;
    }

    if (size_want != -1 && size_want != PyArray_SIZE((PyArrayObject*)o)) {
        PyErr_Format(
            PyExc_AttributeError,
            "array %s is of unexpected size", name);
        return 0;
    }
    if (ndim_want != -1 && ndim_want != PyArray_NDIM((PyArrayObject*)o)) {
        PyErr_Format(
            PyExc_AttributeError,
            "array %s is of unexpected ndim", name);
        return 0;
    }

    if (ndim_want != -1 && shape_want != NULL) {
        for (i=0; i<ndim_want; i++) {
            if (shape_want[i] != -1
                    && shape_want[i] != PyArray_DIMS((PyArrayObject*)o)[i]) {

                PyErr_Format(
                    PyExc_AttributeError,
                    "array %s is of unexpected shape", name);

                return 0;
            }
        }
    }
    return 1;
}

typedef enum {
    SUCCESS = 0,
    MALLOC_FAILED = 1,
    HEAP_FULL = 2,
    HEAP_EMPTY = 3,
    NO_SEED_POINTS = 4,
    CHECK_RESULTS = 5,
} eikonal_error_t;

const char* eikonal_error_names[] = {
    "success",
    "memory allocation failed",
    "heap capacity exhausted",
    "heap drained prematurely",
    "no seeding points given",
    "unexpected/untested code executed, please check results",
};

#define NDIM_MAX 3

static const size_t FARAWAY = SIZE_MAX;
static const size_t ALIVE = SIZE_MAX - 1;
static const double THUGE = DBL_MAX;

typedef struct {
    size_t *indices;
    size_t n;
    size_t nmax;
} heap_t;

static void swap(size_t *a, size_t *b) {
    size_t t;
    t = *a;
    *a = *b;
    *b = t;
}

static double dmin(double a, double b) {
    return (a < b) ? a : b;
}

static heap_t *heap_new(size_t nmax) {
    heap_t *heap;

    heap = (heap_t*)malloc(sizeof(heap_t));
    if (heap == NULL) {
        return NULL;
    }

    heap->indices = (size_t*)calloc(nmax, sizeof(size_t));
    if (heap->indices == NULL) {
        free(heap);
        return NULL;
    }
    heap->nmax = nmax;
    heap->n = 0;
    return heap;
}

static void heap_delete(heap_t *heap) {
    if (heap == NULL) return;
    if (heap->indices != NULL) free(heap->indices);
    free(heap);
}

static void heap_down(
        heap_t *heap,
        size_t index,
        double *keys,
        size_t *backpointers) {

    size_t v, w;
    v = index;
    w = 2*v + 1;  /* first dscendant of v */
    while (w < heap->n) {
        /* if w has second descendant and it is greater take that one */
        if (w+1 < heap->n && keys[heap->indices[w+1]] < keys[heap->indices[w]])
            w = w + 1;

        /* w points to largest descendant */
        if (keys[heap->indices[v]] < keys[heap->indices[w]])
            return; /* v has heap property */

        swap(
            &(heap->indices[v]),
            &(heap->indices[w]));

        swap(
            &(backpointers[heap->indices[v]]),
            &(backpointers[heap->indices[w]]));

        v = w;
        w = 2*v + 1;
    }
}

static void heap_up(
        heap_t *heap,
        size_t index,
        double *keys,
        size_t *backpointers) {

    size_t v, u;
    v = index;
    while (v > 0) {
        u = (v-1)/2;  /* parent */
        if (keys[heap->indices[u]] < keys[heap->indices[v]])
            return; /* u has heap property */

        swap(
            &(heap->indices[v]),
            &(heap->indices[u]));
        swap(
            &(backpointers[heap->indices[v]]),
            &(backpointers[heap->indices[u]]));

        v = u;
    }
}

static eikonal_error_t heap_push(
        heap_t *heap,
        size_t index,
        double *keys,
        size_t *backpointers) {

    if (heap->n + 1 > heap->nmax)
        return HEAP_FULL;

    heap->n += 1;
    heap->indices[heap->n - 1] = index;
    backpointers[index] = heap->n - 1;
    heap_up(heap, heap->n - 1, keys, backpointers);
    return SUCCESS;
}

static size_t heap_pop(
        heap_t *heap,
        double *keys,
        size_t *backpointers) {

    size_t index;
    if (heap->n == 0)
        return SIZE_MAX;

    swap(&(heap->indices[0]), &(heap->indices[heap->n - 1]));
    swap(&(backpointers[heap->indices[0]]),
         &(backpointers[heap->indices[heap->n - 1]]));
    index = heap->indices[heap->n - 1];
    heap->n -= 1;
    heap_down(heap, 0, keys, backpointers);
    return index;
}

static void heap_update(
        heap_t *heap,
        size_t index,
        double newkey,
        double *keys,
        size_t *backpointers) {

    double oldkey;

    oldkey = keys[index];
    keys[index] = newkey;

    if (newkey < oldkey)
        heap_up(heap, backpointers[index], keys, backpointers);

    if (newkey > oldkey)
        heap_down(heap, backpointers[index], keys, backpointers);
}

static eikonal_error_t update_neighbor(
        size_t index,
        double *speeds,
        size_t ndim,
        size_t *shape,
        double delta,
        double *times,
        size_t *backpointers,
        heap_t *heap,
        double tref) {

    double s1, s2, tnew, d;
    double tmins[NDIM_MAX];
    size_t idim, ndim_eff, ix, stride;
    eikonal_error_t retval;

    if (backpointers[index] == ALIVE) return SUCCESS;
    if (backpointers[index] == FARAWAY) {
        heap_push(heap, index, times, backpointers);
    }

    stride = 1;
    for (idim=ndim; idim-- > 0;) {
        ix = (index / stride) % shape[idim];
        tmins[idim] = THUGE;

        if (1 <= ix)
            tmins[idim] = (backpointers[index-stride] == ALIVE)
                ? times[index-stride] : THUGE;

        if (ix+1 < shape[idim])
            tmins[idim] = dmin(
                tmins[idim],
                (backpointers[index+stride] == ALIVE)
                    ? times[index+stride] : THUGE);

        stride *= shape[idim];
    }

    s1 = 0.0;
    s2 = 0.0;
    ndim_eff = 0;
    for (idim=0; idim<ndim; idim++) {
        if (tmins[idim] <= tref + delta/speeds[index]) {
            s1 += tmins[idim];
            s2 += tmins[idim]*tmins[idim];
            ndim_eff += 1;
        }
    }

    retval = SUCCESS;
    d = s1*s1 - ndim_eff*(s2-delta*delta/(speeds[index]*speeds[index]));
    if (d >= 0) {
        tnew = 1.0/ndim_eff * (s1+sqrt(d));
    } else {
        // Should rarely get here if problem is well behaved. It might not be 
        // neccessary to return an error. Needs testing.
        retval = CHECK_RESULTS;
        tnew = tref + delta/speeds[index];
    }
    heap_update(heap, index, tnew, times, backpointers);

    return retval;
}

static eikonal_error_t update_neighbors(
        size_t index,
        double *speeds,
        size_t ndim,
        size_t *shape,
        double delta,
        double *times,
        size_t *backpointers,
        heap_t *heap) {

    size_t idim;
    size_t stride;
    size_t ix;
    eikonal_error_t retval, retval_temp;

    retval = SUCCESS;
    stride = 1;
    for (idim=ndim; idim-- > 0;) {
        ix = (index / stride) % shape[idim];

        if (1 <= ix) {
            retval_temp = update_neighbor(
                index-stride, speeds, ndim, shape, delta, times, 
                backpointers, heap, times[index]);

            retval = retval != SUCCESS ? retval : retval_temp;
        }
        if (ix+1 < shape[idim]) { 
            retval_temp = update_neighbor(
                index+stride, speeds, ndim, shape, delta, times,
                backpointers, heap, times[index]);

            retval = retval != SUCCESS ? retval : retval_temp;
        }

        stride *= shape[idim];
    }

    return retval;
}

static eikonal_error_t eikonal_solver_fmm_cartesian(
        double *speeds,
        size_t ndim,
        size_t *shape,
        double delta,
        double *times) {

    heap_t *heap;
    size_t idim;
    size_t n, i;
    size_t *backpointers;
    size_t nalive;
    size_t index;
    eikonal_error_t retval, retval_temp;

    retval = SUCCESS;

    n = 1;
    for (idim=0; idim<ndim; idim++) {
        n *= shape[idim];
    }

    heap = heap_new(n);
    if (heap == NULL) {
        return MALLOC_FAILED;
    }

    backpointers = (size_t*)calloc(n, sizeof(size_t));
    if (backpointers == NULL) {
        heap_delete(heap);
        return MALLOC_FAILED;
    }

    nalive = 0;
    for (i=0; i<n; i++) {
        if (times[i] < 0.0) {
            backpointers[i] = FARAWAY;
        } else {
            backpointers[i] = ALIVE;
            nalive += 1;
        }
    }
    if (nalive == 0) return NO_SEED_POINTS;

    // initialize narrowband
    for (index=0; index<n; index++) {
        if (backpointers[index] == ALIVE) {
            retval_temp = update_neighbors(
                index, speeds, ndim, shape, delta, times, 
                backpointers, heap);

            retval = retval != SUCCESS ? retval : retval_temp;
        }
    }

    // fast marching
    while (nalive < n) {
        index = heap_pop(heap, times, backpointers);
        if (index == SIZE_MAX) return HEAP_EMPTY;
        if (backpointers[index] != ALIVE) nalive += 1;

        backpointers[index] = ALIVE;

        retval_temp = update_neighbors(
            index, speeds, ndim, shape, delta, times, 
            backpointers, heap);

        retval = retval != SUCCESS ? retval : retval_temp;
    }

    free(backpointers);
    heap_delete(heap);

    return retval;
}

static PyObject* w_eikonal_solver_fmm_cartesian(
        PyObject *m,
        PyObject *args,
        PyObject *kwds) {

    eikonal_error_t err;
    PyObject *speeds_arr, *times_arr;
    int ndim, i;
    npy_intp shape[3], size;
    size_t size_t_shape[3];
    double *speeds, *times, delta;

    struct module_state *st = GETSTATE(m);

    static char *kwlist[] = {
        "speeds", "times", "delta", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "OOd", kwlist, &speeds_arr, &times_arr, &delta)) {
        PyErr_SetString(
            st->error,
            "usage: eikonal_solver_fmm_cartesian(speeds, times, delta)");
        return NULL;
    }

    if (!good_array(speeds_arr, NPY_FLOAT64, -1, -1, NULL, "speeds"))
        return NULL;
    ndim = PyArray_NDIM((PyArrayObject*)speeds_arr);
    if (!(1 <= ndim && ndim <= NDIM_MAX)) {
        PyErr_Format(
            st->error,
            "Only 1 to %i dimensional inputs have been tested. Set NDIM_MAX "
            "in eikonal_ext.c and recompile to try higher dimensions.",
            NDIM_MAX);
        return NULL;
    }

    size = 1;
    for (i=0; i<ndim; i++) {
        shape[i] = PyArray_DIMS((PyArrayObject*)speeds_arr)[i];
        size *= shape[i];
    }

    if (!good_array(times_arr, NPY_FLOAT64, size, ndim, shape, "times"))
        return NULL;

    speeds = (double*)PyArray_DATA((PyArrayObject*)speeds_arr);
    times = (double*)PyArray_DATA((PyArrayObject*)times_arr);

    for (i=0; i<ndim; i++) {
        size_t_shape[i] = shape[i];
    }

    err = eikonal_solver_fmm_cartesian(
        speeds, (size_t)ndim, size_t_shape, delta, times);

    if (SUCCESS != err) {
        PyErr_SetString(st->error, eikonal_error_names[err]);
        return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyMethodDef eikonal_ext_methods[] = {
    {
        "eikonal_solver_fmm_cartesian",
        (PyCFunction)(void(*)(void))w_eikonal_solver_fmm_cartesian,
        METH_VARARGS | METH_KEYWORDS,
        "Solve eikonal equation using the fast marching method."
    },
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int eikonal_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int eikonal_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "eikonal_ext",
        "C-extension supporting :py:mod:`pyrocko.modelling.eikonal`.",
        sizeof(struct module_state),
        eikonal_ext_methods,
        NULL,
        eikonal_ext_traverse,
        eikonal_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_eikonal_ext(void)


{
    PyObject *module = PyModule_Create(&moduledef);
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException(
        "pyrocko.eikonal_ext.EikonalExtError", NULL, NULL);

    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "EikonalExtError", st->error);

    return module;
}
