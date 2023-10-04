
/* Copyright (c) 2009, Sebastian Heimann <sebastian.heimann@zmaw.de>

  This file is part of pymseed. For licensing information please see the file
  COPYING which is included with pyevalresp. */

#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"

#include <evresp.h>
#include <assert.h>

#define BUFSIZE 1024

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

static PyObject*
evresp_wrapper (PyObject *m, PyObject *args)
{
    char *sta_list, *cha_list, *units, *file, *verbose;
    char *net_code, *locid, *rtype;
    int nfreqs;
    int start_stage = -1, stop_stage = 0, stdio_flag = 0;
    int listinterp_out_flag = 0, listinterp_in_flag = 0;
    double listinterp_tension = 1000.0;
    char *datime;
    struct response *first, *r;

    PyArrayObject *freqs_array = NULL, *freqs_array_cont = NULL;
    PyObject      *rvec_array = NULL;
    PyObject      *elem, *out_list;
    npy_intp      array_dims[1] = {0};

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "sssssssOssiiiiid",
                            &sta_list,
                            &cha_list,
                            &net_code,
                            &locid,
                            &datime,
                            &units,
                            &file,
                            &freqs_array,
                            &rtype,
                            &verbose,
                            &start_stage,
                            &stop_stage,
                            &stdio_flag,
                            &listinterp_out_flag,
                            &listinterp_in_flag,
                            &listinterp_tension)) {
        PyErr_SetString(st->error, "usage: evalresp(sta_list, cha_list, net_code, locid, datime, units, file, freqs_array, "
                                       "rtype, verbose, start_stage, stop_stage, stdio_flag, "
                                       "listinterp_out_flag, listinterp_in_flag, listinterp_tension)" );
        return NULL;
    }

    if (!PyArray_Check(freqs_array)) {
        PyErr_SetString(st->error, "Frequencies must be given as NumPy array." );
        return NULL;
    }

    assert( sizeof(double) == 8 );
    if (PyArray_TYPE(freqs_array) != NPY_FLOAT64) {
        PyErr_SetString(st->error, "Frequencies must be of type double.");
        return NULL;
    }

    if (start_stage==-1 && stop_stage) {
        PyErr_Warn(st->error, (char*)"Need to define start_stage, otherwise stop_stage is ignored.");
    }

    freqs_array_cont = PyArray_GETCONTIGUOUS((PyArrayObject*)freqs_array);
    nfreqs = PyArray_SIZE(freqs_array_cont);

    first = evresp_itp(sta_list, cha_list, net_code, locid, datime, units, file,
                      PyArray_DATA(freqs_array_cont), nfreqs, rtype, verbose, start_stage, stop_stage,
                      stdio_flag, listinterp_out_flag, listinterp_in_flag,
                      listinterp_tension);

    Py_DECREF(freqs_array_cont);

    if (!first) {
        PyErr_SetString(st->error, "Function evresp() failed" );
        return NULL;
    }

    out_list = Py_BuildValue("[]");


    r = first;
    while (r) {

        array_dims[0] = nfreqs;
        rvec_array = PyArray_SimpleNew(1, array_dims, NPY_COMPLEX128);
        memcpy( PyArray_DATA((PyArrayObject*)rvec_array), r->rvec, nfreqs*16 );

        elem = Py_BuildValue("(s,s,s,s,N)",
            r->station, r->network, r->locid, r->channel, rvec_array);

        PyList_Append(out_list, elem);
        Py_DECREF(elem);

        r = r->next;
    }
    free_response(first);

    return out_list;
}


static PyMethodDef evalresp_ext_methods[] = {
    {"evalresp",  evresp_wrapper, METH_VARARGS,
    "" },
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int evalresp_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int evalresp_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "evalresp_ext",
        "C-extension supporting :py:mod:`pyrocko.evalresp`.",
        sizeof(struct module_state),
        evalresp_ext_methods,
        NULL,
        evalresp_ext_traverse,
        evalresp_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_evalresp_ext(void)


{
    PyObject *module = PyModule_Create(&moduledef);
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.evalresp_ext.EvalrespExtError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "EvalrespExtError", st->error);

    return module;
}
