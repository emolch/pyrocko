#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

static char translate[128] = {
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1, 0,-1, 1,-1,-1, 2,
     3, 4, 5, 6, 7, 8, 9,10,11,-1,-1,-1,-1,-1,-1,-1,
    12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,
    28,29,30,31,32,33,34,35,36,37,-1,-1,-1,-1,-1,-1,
    38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,
    54,55,56,57,58,59,60,61,62,63,-1,-1,-1,-1,-1
};

static int MODULUS = 100000000;

PyArrayObject *get_good_array(PyObject *array) {

    if (!PyArray_Check(array)) {
        PyErr_SetString(PyExc_AttributeError, "Data must be given as NumPy array." );
        return NULL;
    }
    if (PyArray_ISBYTESWAPPED((PyArrayObject*)array)) {
        PyErr_SetString(PyExc_AttributeError, "Data must be given in machine byte-order.");
        return NULL;
    }
    if (PyArray_TYPE((PyArrayObject*)array) != NPY_INT32) {
        PyErr_SetString(PyExc_AttributeError, "Data must be 32-bit integers.");
        return NULL;
    }
    return PyArray_GETCONTIGUOUS((PyArrayObject*)array);
}

static PyObject* ims_checksum(PyObject *m, PyObject *args) {
    npy_intp length, i;
    PyObject *array = NULL;
    PyArrayObject *carray = NULL;
    int *data;
    int checksum;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "O", &array )) {
        PyErr_SetString(st->error, "usage checksum(array)" );
        return NULL;
    }

    carray = get_good_array(array);
    if (carray == NULL) {
        return NULL;
    }

    length = PyArray_SIZE(carray);
    data = (int*)PyArray_DATA(carray);

    checksum = 0;
    for (i=0; i<length; i++) {
        checksum += data[i] % MODULUS;
        checksum %= MODULUS;
    }
    Py_DECREF(carray);

    return Py_BuildValue("i", abs(checksum));
}

static PyObject* ims_checksum_ref(PyObject *m, PyObject *args) {
    npy_intp length, i;
    PyObject *array = NULL;
    PyArrayObject *carray = NULL;
    int *data;
    int checksum, v;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "O", &array )) {
        PyErr_SetString(st->error, "usage checksum2(array)" );
        return NULL;
    }

    carray = get_good_array(array);
    if (carray == NULL) {
        return NULL;
    }

    length = PyArray_SIZE(carray);
    data = (int*)PyArray_DATA(carray);

    checksum = 0;
    for (i=0; i<length; i++) {
        v = data[i];
        if (abs(v) >= MODULUS) {
            v = v - (v/MODULUS)*MODULUS;
        }
        checksum += v;
        if (abs(checksum) >= MODULUS) {
            checksum = checksum - (checksum/MODULUS) * MODULUS;
        }
    }
    Py_DECREF(carray);

    return Py_BuildValue("i", abs(checksum));
}

static PyObject* ims_decode_cm6(PyObject *m, PyObject *args) {
    char *in_data;
    int *out_data = NULL;
    int *out_data_new = NULL;
    char *pos;
    char v;
    int sample, ibyte, sign;
    int previous1, previous2;
    Py_ssize_t sbufsize;
    size_t bufsize;
    char imore = 32, isign = 16;
    PyObject *array = NULL;
    size_t isample;
    npy_intp array_dims[1] = {0};

    struct module_state *st = GETSTATE(m);
    if (!PyArg_ParseTuple(args, "yn", &in_data, &sbufsize)) {
        PyErr_SetString(st->error, "invalid arguments in decode_cm6(data, sizehint)" );
        return NULL;
    }

    if (sbufsize > 0) {
        bufsize = (size_t)sbufsize;
    } else {
        bufsize = 64;
    }

    if (bufsize > SIZE_MAX / sizeof(int)) {
        PyErr_SetString(st->error, "cannot allocate memory");
        return NULL;
    }

    out_data = (int*)malloc(bufsize*sizeof(int));
    if (out_data == NULL) {
        PyErr_SetString(st->error, "cannot allocate memory" );
        return NULL;
    }

    pos = in_data;
    sample = 0;
    isample = 0;
    ibyte = 0;
    sign = 1;
    previous1 = 0;
    previous2 = 0;
    while (*pos != '\0') {
        v = translate[*pos & 0x7F];
        if (v != -1) {
            if (ibyte == 0) sign = (v & isign) ? -1 : 1;
            sample += v & ((ibyte == 0) ? 0xf : 0x1f);
            if ((v & imore) == 0) {
                if (isample >= bufsize) {
                    if (isample > SIZE_MAX / (2 * sizeof(int))) {
                        free(out_data);
                        PyErr_SetString(st->error, "cannot allocate memory");
                    }
                    bufsize = isample*2;
                    out_data_new = (int*)realloc(out_data, sizeof(int) * bufsize);
                    if (out_data_new == NULL) {
                        free(out_data);
                        PyErr_SetString(st->error, "cannot allocate memory" );
                        return NULL;
                    }
                    out_data = out_data_new;
                }
                previous1 = previous1 + sign * sample;
                out_data[isample] = previous2 = previous2 + previous1;
                isample++;
                sample = 0;
                ibyte = 0;
            } else {
                sample *= 32;
                ibyte++;
            }
        }
        pos++;
    }
    if (isample > NPY_MAX_INTP) {
        free(out_data);
        PyErr_SetString(st->error, "too many samples" );
        return NULL;
    }
    array_dims[0] = (npy_intp)isample;
    array = PyArray_SimpleNew(1, array_dims, NPY_INT32);
    memcpy(PyArray_DATA((PyArrayObject*)array), out_data, isample*sizeof(int32_t));
    free(out_data);
    return Py_BuildValue("N", array);
}

static PyObject* ims_encode_cm6(PyObject *m, PyObject *args) {
    PyObject *array = NULL;
    PyObject *string = NULL;
    PyArrayObject *contiguous_array = NULL;
    int *in_data;
    char *out_data = NULL;
    long long int sample;
    int v;
    int isign, imore;
    size_t bufsize, ipos, iout, i;
    npy_intp nsamples, isample;
    char temp;
    char rtranslate[64];

    struct module_state *st = GETSTATE(m);

    for (i=0; i<128; i++) {
        if (translate[i] != -1) {
            rtranslate[(int)translate[i]] = i;
        }
    }

    if (!PyArg_ParseTuple(args, "O", &array)) {
        PyErr_SetString(st->error, "invalid arguments in encode_cm6(data)");
        return NULL;
    }

    contiguous_array = get_good_array(array);
    if (contiguous_array == NULL) {
        return NULL;
    }

    nsamples  = PyArray_SIZE(contiguous_array);
    in_data = PyArray_DATA(contiguous_array);

    if (nsamples >= NPY_MAX_INTP / 7) {
        PyErr_SetString(st->error, "too many samples.");
        Py_DECREF(contiguous_array);
        return NULL;
    }
    bufsize = (size_t)nsamples * 7;
    out_data = (char*)malloc(bufsize);
    if (out_data == NULL) {
        PyErr_SetString(st->error, "cannot allocate memory");
        Py_DECREF(contiguous_array);
        return NULL;
    }

    iout = 0;
    for (isample=0; isample<nsamples; isample++) {
        sample = in_data[isample];
        if (isample >= 1) sample -= 2 * in_data[isample-1];
        if (isample >= 2) sample += in_data[isample-2];
        isign = sample < 0 ? 16 : 32;
        sample = llabs(sample);
        imore = 0;
        ipos = iout;
        while (isign != 0) {
            v = sample & 31;
            sample /= 32;
            if (sample == 0 && v < 16) {
                v += isign & 16;
                isign = 0;
            }
            v += imore;
            imore = 32;

            if (iout >= bufsize) {
                free(out_data);
                PyErr_SetString(st->error,
                    "some assumption of the programmer was wrong...");
                Py_DECREF(contiguous_array);
                return NULL;
            }

            out_data[iout] = rtranslate[v];
            iout++;
        }
        for (i=0; i<(iout-ipos)/2; i++) {
            temp = out_data[ipos+i];
            out_data[ipos+i] = out_data[iout-1-i];
            out_data[iout-1-i] = temp;
        }
    }

    string = PyBytes_FromStringAndSize(out_data, iout);
    free(out_data);

    if (string == NULL) {
        PyErr_SetString(st->error, "cannot create output string");
        Py_DECREF(contiguous_array);
        return NULL;
    }

    Py_DECREF(contiguous_array);
    return Py_BuildValue("N", string);
}

static PyMethodDef ims_ext_methods[] = {
    {"decode_cm6",  ims_decode_cm6, METH_VARARGS,
        "Decode CM6 encoded IMS/GSE data." },

    {"encode_cm6",  ims_encode_cm6, METH_VARARGS,
        "Encode integers to CM6." },

    {"checksum", ims_checksum, METH_VARARGS,
        "Calculate IMS/GSE checksum."},

    {"checksum_ref", ims_checksum_ref, METH_VARARGS,
        "Calculate IMS/GSE checksum."},

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int ims_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int ims_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "ims_ext",
        "C-extension supporting :py:mod:`pyrocko.io.ims`.",
        sizeof(struct module_state),
        ims_ext_methods,
        NULL,
        ims_ext_traverse,
        ims_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_ims_ext(void)


{
    PyObject *module = PyModule_Create(&moduledef);
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.ims_ext.IMSError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "IMSError", st->error);

    return module;
}
