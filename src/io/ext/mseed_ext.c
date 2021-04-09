
/* Copyright (c) 2009, Sebastian Heimann <sebastian.heimann@zmaw.de>

  This file is part of pyrocko. For licensing information please see the file
  COPYING which is included with pyrocko. */

#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"

#include <libmseed.h>
#include <assert.h>

struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
#define GETSTATE(m) (&_state); (void) m;
static struct module_state _state;
#endif

#define BUFSIZE 1024


static PyObject*
mseed_get_traces (PyObject *m, PyObject *args)
{
    char          *filename;
    MSTraceGroup  *mstg = NULL;
    MSTrace       *mst = NULL;
    int           retcode;
    npy_intp      array_dims[1] = {0};
    PyObject      *array = NULL;
    PyObject      *out_traces = NULL;
    PyObject      *out_trace = NULL;
    int           numpytype;
    char          strbuf[BUFSIZE];
    PyObject      *unpackdata = NULL;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "sO", &filename, &unpackdata)) {
        PyErr_SetString(st->error, "usage get_traces(filename, dataflag)" );
        return NULL;
    }

    if (!PyBool_Check(unpackdata)) {
        PyErr_SetString(st->error, "Second argument must be a boolean" );
        return NULL;
    }
  
    /* get data from mseed file */
    retcode = ms_readtraces (&mstg, filename, 0, -1.0, -1.0, 0, 1, (unpackdata == Py_True), 0);
    if ( retcode < 0 ) {
        snprintf (strbuf, BUFSIZE, "Cannot read file '%s': %s", filename, ms_errorstr(retcode));
        PyErr_SetString(st->error, strbuf);
        return NULL;
    }

    if ( ! mstg ) {
        snprintf (strbuf, BUFSIZE, "Error reading file");
        PyErr_SetString(st->error, strbuf);
        return NULL;
    }

    /* check that there is data in the traces */
    if (unpackdata == Py_True) {
        mst = mstg->traces;
        while (mst) {
            if (mst->datasamples == NULL) {
                snprintf (strbuf, BUFSIZE, "Error reading file - datasamples is NULL");
                PyErr_SetString(st->error, strbuf);
                return NULL;
            }
            mst = mst->next;
        }
    }

    out_traces = Py_BuildValue("[]");

    mst = mstg->traces;

    /* convert data to python tuple */

    while (mst) {
        
        if (unpackdata == Py_True) {
            array_dims[0] = mst->numsamples;
            switch (mst->sampletype) {
                case 'i':
                    assert( ms_samplesize('i') == 4 );
                    numpytype = NPY_INT32;
                    break;
                case 'a':
                    assert( ms_samplesize('a') == 1 );
                    numpytype = NPY_INT8;
                    break;
                case 'f':
                    assert( ms_samplesize('f') == 4 );
                    numpytype = NPY_FLOAT32;
                    break;
                case 'd':
                    assert( ms_samplesize('d') == 8 );
                    numpytype = NPY_FLOAT64;
                    break;
                default:
                    snprintf (strbuf, BUFSIZE, "Unknown sampletype %c\n", mst->sampletype);
                    PyErr_SetString(st->error, strbuf);
                    Py_XDECREF(out_traces);
                    return NULL;
            }
            array = PyArray_SimpleNew(1, array_dims, numpytype);
            memcpy( PyArray_DATA((PyArrayObject*)array), mst->datasamples, mst->numsamples*ms_samplesize(mst->sampletype) );
        } else {
            Py_INCREF(Py_None);
            array = Py_None;
        }

        out_trace = Py_BuildValue( "(c,s,s,s,s,L,L,d,N)",
                                    mst->dataquality,
                                    mst->network,
                                    mst->station,
                                    mst->location,
                                    mst->channel,
                                    mst->starttime,
                                    mst->endtime,
                                    mst->samprate,
                                    array );

        
        PyList_Append(out_traces, out_trace);
        Py_DECREF(out_trace);
        mst = mst->next;
    }

    mst_freegroup (&mstg);

    return out_traces;
}

static void record_handler (char *record, int reclen, void *outfile) {    
    if ( fwrite(record, reclen, 1, outfile) != 1 ) {
      fprintf(stderr, "Error writing mseed record to output file\n");
    }
}

static PyObject*
mseed_store_traces (PyObject *m, PyObject *args, PyObject *kwds)
{
    char          *filename;
    MSTrace       *mst = NULL;
    PyObject      *array = NULL;
    PyObject      *in_traces = NULL;
    PyObject      *in_trace = NULL;
    PyArrayObject *contiguous_array = NULL;
    int           i;
    char          *network, *station, *location, *channel;
    char          mstype;
    int           msdetype;
    int64_t       psamples;
    int           numpytype;
    int           length;
    size_t        record_length = 4096;
    int           steim = 1;
    FILE          *outfile;

    struct module_state *st = GETSTATE(m);

    static char *kwlist[] = {"traces", "filename", "record_length", "steim", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "Os|ni", kwlist, &in_traces, &filename, &record_length, &steim))
        return NULL;

    if (steim != 1 && steim != 2) {
        PyErr_SetString(st->error, "Invalid STEIM compression, use 1 or 2.");
        return NULL;
    }

    if (!PySequence_Check( in_traces )) {
        PyErr_SetString(st->error, "Traces is not of sequence type." );
        return NULL;
    }

    outfile = fopen(filename, "wb" );
    if (outfile == NULL) {
        PyErr_SetString(st->error, "Error opening file.");
        return NULL;
    }

    for (i=0; i<PySequence_Length(in_traces); i++) {
        
        in_trace = PySequence_GetItem(in_traces, i);
        if (!PyTuple_Check(in_trace)) {
            PyErr_SetString(st->error, "Trace record must be a tuple of (network, station, location, channel, starttime, endtime, samprate, data)." );
            Py_DECREF(in_trace);
            return NULL;
        }
        mst = mst_init (NULL);
        
        if (!PyArg_ParseTuple(in_trace, "ssssLLdO",
                                    &network,
                                    &station,
                                    &location,
                                    &channel,
                                    &(mst->starttime),
                                    &(mst->endtime),
                                    &(mst->samprate),
                                    &array )) {
            PyErr_SetString(st->error, "Trace record must be a tuple of (network, station, location, channel, starttime, endtime, samprate, data)." );
            mst_free( &mst );  
            Py_DECREF(in_trace);
            return NULL;
        }

        strncpy( mst->network, network, 10);
        strncpy( mst->station, station, 10);
        strncpy( mst->location, location, 10);
        strncpy( mst->channel, channel, 10);
        mst->network[10] = '\0';
        mst->station[10] = '\0';
        mst->location[10] ='\0';
        mst->channel[10] = '\0';

        if (!PyArray_Check(array)) {
            PyErr_SetString(st->error, "Data must be given as NumPy array." );
            mst_free( &mst );
            Py_DECREF(in_trace);
            return NULL;
        }
        if (PyArray_ISBYTESWAPPED((PyArrayObject*)array)) {
            PyErr_SetString(st->error, "Data must be given in machine byte-order" );
            mst_free( &mst );
            Py_DECREF(in_trace);
            return NULL;
        }

        numpytype = PyArray_TYPE((PyArrayObject*)array);
        switch (numpytype) {
                case NPY_INT32:
                    assert( ms_samplesize('i') == 4 );
                    mstype = 'i';
                    msdetype = steim == 1 ? DE_STEIM1 : DE_STEIM2 ;
                    break;
                case NPY_INT8:
                    assert( ms_samplesize('a') == 1 );
                    mstype = 'a';
                    msdetype = DE_ASCII;
                    break;
                case NPY_FLOAT32:
                    assert( ms_samplesize('f') == 4 );
                    mstype = 'f';
                    msdetype = DE_FLOAT32;
                    break;
                case NPY_FLOAT64:
                    assert( ms_samplesize('d') == 8 );
                    mstype = 'd';
                    msdetype = DE_FLOAT64;
                    break;
                default:
                    PyErr_SetString(st->error, "Data must be of type float64, float32, int32 or int8.");
                    mst_free( &mst );  
                    Py_DECREF(in_trace);
                    return NULL;
            }
        mst->sampletype = mstype;

        contiguous_array = PyArray_GETCONTIGUOUS((PyArrayObject*)array);

        length = PyArray_SIZE(contiguous_array);
        mst->numsamples = length;
        mst->samplecnt = length;

        mst->datasamples = calloc(length,ms_samplesize(mstype));
        memcpy(mst->datasamples, PyArray_DATA(contiguous_array), length*ms_samplesize(mstype));
        Py_DECREF(contiguous_array);

        Py_BEGIN_ALLOW_THREADS
        mst_pack(mst, &record_handler, outfile, record_length, msdetype, 1, &psamples, 1, 0, NULL);
        mst_free( &mst );
        Py_END_ALLOW_THREADS

        Py_DECREF(in_trace);
    }
    fclose( outfile );

    Py_RETURN_NONE;
}


static PyMethodDef mseed_ext_methods[] = {
    {"get_traces",  mseed_get_traces, METH_VARARGS, 
    "get_traces(filename, dataflag)\n"
    "Get all traces stored in an mseed file.\n\n"
    "Returns a list of tuples, one tuple for each trace in the file. Each tuple\n"
    "has 9 elements:\n\n"
    "  (dataquality, network, station, location, channel,\n"
    "    startime, endtime, samprate, data)\n\n"
    "These come straight from the MSTrace data structure, defined and described\n"
    "in libmseed. If dataflag is True, `data` is a numpy array containing the\n"
    "data. If dataflag is False, the data is not unpacked and `data` is None.\n" },

    {"store_traces",  mseed_store_traces, METH_VARARGS | METH_KEYWORDS, 
    "store_traces(traces, filename)\n" },

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

#if PY_MAJOR_VERSION >= 3

static int mseed_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int mseed_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "mseed_ext",
        NULL,
        sizeof(struct module_state),
        mseed_ext_methods,
        NULL,
        mseed_ext_traverse,
        mseed_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_mseed_ext(void)

#else
#define INITERROR return

void
initmseed_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("mseed_ext", mseed_ext_methods);
#endif
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.mseed_ext.MSeedError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "MSeedError", st->error);
    PyModule_AddObject(module, "HPTMODULUS", PyLong_FromLong(HPTMODULUS));

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
