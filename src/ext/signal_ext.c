#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

#ifdef _WIN32
  #define _USE_MATH_DEFINES
#endif
#include <math.h>

static const int64_t NENTRIES = 1001;
/*static const int64_t ORDER = 25;*/
static const int64_t NCOEFFS = 25*2+1;

typedef enum {
    SUCCESS = 0,
    INVALID_INPUT_EMPTY = 1,
    INVALID_INPUT_SLOPE = 2,
    INVALID_INPUT_NEED_MORE_CONTROL_POINTS = 3,
    INVALID_INPUT_FIRST_CONTROL_POINT = 4,
    INVALID_INPUT_LAST_CONTROL_POINT = 5,
} signal_error_t;

const char* signal_error_names[] = {
    "success",
    "antidrift: empty input array",
    "antidrift: time correction slope too extreme (must be in range [0.9, 1.1])",
    "antidrift: need at least 2 control points",
    "antidrift: first control point must be at or before first sample",
    "antidrift: last control point must be at after last sample",
};

#define INVALID_INPUT 1
#define SUCCESS 0

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

static int good_array(const PyObject* o, int typenum) {
    if (!PyArray_Check(o)) {
        PyErr_SetString(PyExc_AttributeError, "not a NumPy array" );
        return 0;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != typenum) {
        PyErr_SetString(PyExc_ValueError, "array of unexpected type");
        return 0;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_ValueError, "array is not contiguous or not behaved");
        return 0;
    }

    return 1;
}

static double blackman_nutall(int i, int n) {
    return 0.3635819 - 0.4891775*cos((2.*M_PI*i)/(n-1))
              + 0.1365995*cos((4.*M_PI*i)/(n-1))
              - 0.0106411*cos((6.*M_PI*i)/(n-1));
}

static double sinc(double x) {
    if (x == 0.0) {
        return 1.0;
    } else {
        return sin(M_PI*x)/(M_PI*x);
    }
}

static int64_t imin(int64_t i, int64_t j) {
    return i < j ? i : j;
}
static int64_t imax(int64_t i, int64_t j) {
    return i > j ? i : j;
}

static signal_error_t antidrift(
        int64_t n_control,
        const int64_t *indices_control,
        const double *t_control,
        int64_t n_in,
        const double *samples_in,
        int64_t n_out,
        double tmin_out,
        double deltat_out,
        double *samples_out) {

    double *coeffs = NULL;
    int64_t ic, ientry, nentries, i, icoeff_lo, icoeff_hi;
    int64_t icoeff, ncoeffs;
    int64_t i_in;
    double r_in, slope, gamma, t;
    double *slopes;
    double sum;


    /* check inputs */
    if (n_in < 1) {
        return INVALID_INPUT_EMPTY;
    }

    if (n_control < 2) {
        return INVALID_INPUT_NEED_MORE_CONTROL_POINTS;
    }

    if (indices_control[0] > 0) {
        return INVALID_INPUT_FIRST_CONTROL_POINT;
    }
    if (indices_control[n_control-1] < n_in-1) {
        return INVALID_INPUT_LAST_CONTROL_POINT;
    }

    slopes = calloc(n_control-1, sizeof(double));
    for (ic=0; ic<n_control-1; ic++) {
        slope = (indices_control[ic+1] - indices_control[ic]) /
                ((t_control[ic+1] - t_control[ic])/deltat_out);

        if (slope < 0.9 || 1.1 < slope) {
            return INVALID_INPUT_SLOPE;
        }
        slopes[ic] = slope;
    }

    nentries = NENTRIES;
    ncoeffs = NCOEFFS;

    /* tabulate coefficients */
    coeffs = calloc(nentries*ncoeffs, sizeof(double));
    for (ientry=0; ientry<nentries; ientry++) {
        gamma = (ientry/(nentries-1.0)) - 0.5;
        sum = 0.0;
        for (icoeff=0; icoeff<ncoeffs; icoeff++) {
            coeffs[ientry*ncoeffs + icoeff] = sinc(gamma-(icoeff-ncoeffs/2)) *
                                              blackman_nutall(icoeff, ncoeffs);

            sum += coeffs[ientry*ncoeffs + icoeff];
        }
        for (icoeff=0; icoeff<ncoeffs; icoeff++) {
            coeffs[ientry*ncoeffs + icoeff] /= sum;
        }
    }

    /* interpolate */
    ic = 0;
    for (i=0; i<n_out; i++) {
        t = tmin_out + i * deltat_out;

        while (ic < n_control-1 && t_control[ic+1] < t) {
            ic++;
        }

        r_in = indices_control[ic] + (t-t_control[ic]) * slopes[ic] / deltat_out;
        i_in = lround(r_in);
        gamma = r_in - i_in;
        ientry = lround((gamma - (-0.5)) * (nentries-1));

        samples_out[i] = 0.0;
        icoeff_lo = imax(-i_in + ncoeffs / 2, 0);
        icoeff_hi = imin(ncoeffs, n_in - i_in + ncoeffs / 2);

        for (icoeff=icoeff_lo; icoeff<icoeff_hi; icoeff++) {
            samples_out[i] += samples_in[i_in + icoeff - ncoeffs/2] *
                              coeffs[ientry*ncoeffs + icoeff];
        }

        /* repeating end points */
        for (icoeff=0; icoeff<icoeff_lo; icoeff++) {
            samples_out[i] += samples_in[0] *
                              coeffs[ientry*ncoeffs + icoeff];
        }

        for (icoeff=icoeff_hi; icoeff<ncoeffs; icoeff++) {
            samples_out[i] += samples_in[n_in-1] *
                              coeffs[ientry*ncoeffs + icoeff];
        }
    }

    free(slopes);
    free(coeffs);

    return SUCCESS;
}

static PyObject* w_antidrift(PyObject *m, PyObject *args) {
    int err;

    int64_t n_control;
    int64_t *indices_control;
    double *t_control;
    int64_t n_in;
    double *samples_in;
    int64_t n_out;
    double tmin_out;
    double deltat_out;
    double *samples_out;
    PyObject *arr_indices_control, *arr_t_control, *arr_samples_in;
    PyObject *arr_samples_out;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "OOOddO",
                &arr_indices_control,
                &arr_t_control,
                &arr_samples_in,
                &tmin_out,
                &deltat_out,
                &arr_samples_out)) {

        PyErr_SetString(st->error,
            "usage antidrift(indices_control, t_control, samples_in, "
            "tmin_out, deltat_out, samples_out)");
        return NULL;
    }

    if (!good_array(arr_indices_control, NPY_INT64) ||
        !good_array(arr_t_control, NPY_DOUBLE) ||
        !good_array(arr_samples_in, NPY_DOUBLE) ||
        !good_array(arr_samples_out, NPY_DOUBLE)) {
        return NULL;
    }

    n_control = PyArray_SIZE((PyArrayObject*)arr_indices_control);
    indices_control = (int64_t*)PyArray_DATA((PyArrayObject*)arr_indices_control);

    if (n_control != PyArray_SIZE((PyArrayObject*)arr_t_control)) {
        PyErr_SetString(st->error,
            "sizes of indices_control and t_control differ");
        return NULL;
    }

    t_control = (double*)PyArray_DATA((PyArrayObject*)arr_t_control);

    n_in = PyArray_SIZE((PyArrayObject*)arr_samples_in);
    samples_in = (double*)PyArray_DATA((PyArrayObject*)arr_samples_in);

    n_out = PyArray_SIZE((PyArrayObject*)arr_samples_out);
    samples_out = (double*)PyArray_DATA((PyArrayObject*)arr_samples_out);

    err = antidrift(n_control, indices_control, t_control, n_in, samples_in,
            n_out, tmin_out, deltat_out, samples_out);

    if (err != 0) {
        PyErr_SetString(st->error, signal_error_names[err]);
        return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}


static PyObject* w_apply_costaper(PyObject *m, PyObject *args) {
    double xa, xb, xc, xd, x0, dx;
    int64_t iy, ny, ia, ib, ic, id;
    double *y;
    PyObject *y_arr;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "ddddOdd",
                &xa, &xb, &xc, &xd, &y_arr, &x0, &dx)) {

        PyErr_SetString(st->error,
            "usage apply_costaper(xa, xb, xc, xd, y, x0, dx)");
        return NULL;
    }

    if (!good_array(y_arr, NPY_DOUBLE)) {
        return NULL;
    }
    ny = PyArray_SIZE((PyArrayObject*)y_arr);
    y = (double*)PyArray_DATA((PyArrayObject*)y_arr);

    ia = (int64_t)ceil((xa-x0)/dx);
    ib = (int64_t)ceil((xb-x0)/dx);
    ic = (int64_t)ceil((xc-x0)/dx);
    id = (int64_t)ceil((xd-x0)/dx);

    for (iy=0; iy<imin(ny, ia); iy++) {
        y[iy] = 0.0;
    }
    for (iy=imax(0, ia); iy<imin(ny, ib); iy++) {
        y[iy] *= 0.5 - 0.5*cos((x0+iy*dx-xa)/(xb-xa)*M_PI);
    }
    for (iy=imax(0, ic); iy<imin(ny, id); iy++) {
        y[iy] *= 0.5 + 0.5*cos((x0+iy*dx-xc)/(xd-xc)*M_PI);
    }
    for (iy=imax(0, id); iy<ny; iy++) {
        y[iy] = 0.0;
    }

    Py_INCREF(Py_None);
    return Py_None;
}


static PyMethodDef signal_ext_methods[] = {
    {"antidrift",  w_antidrift, METH_VARARGS,
        "correct time drift using sinc interpolation" },
    {"apply_costaper",  w_apply_costaper, METH_VARARGS,
        "apply cosine taper" },
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int signal_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int signal_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "signal_ext",
        "C-extension supporting :py:mod:`pyrocko.trace`.",
        sizeof(struct module_state),
        signal_ext_methods,
        NULL,
        signal_ext_traverse,
        signal_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_signal_ext(void)


{
    PyObject *module = PyModule_Create(&moduledef);
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.signal_ext.Error", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "Error", st->error);

    return module;
}
