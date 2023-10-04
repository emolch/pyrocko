#define NPY_NO_DEPRECATED_API 7

#define GF_STORE_HEADER_SIZE (8+4)

/* security limit for length of traces, shifts and offsets (samples) */
#define SLIMIT 1000000

#define SQR(a)  ( (a) * (a) )

#define EARTHRADIUS 6371000.0
#define EARTH_OBLATENESS 1./298.257223563
#define EARTHRADIUS_EQ 6378140.0
#define NPY_GFDTYPE NPY_FLOAT32

#define inlimits(i) (-SLIMIT <= (i) && (i) <= SLIMIT)
#define inposlimits(i) (0 <= (i) && (i) <= SLIMIT)

#include "Python.h"

#include "numpy/arrayobject.h"
#include <sys/types.h>
#include <sys/stat.h>
#ifndef _WIN32
    #include <sys/mman.h>
    #include <unistd.h>
#endif

#ifdef _WIN32
    #define _USE_MATH_DEFINES
    typedef SSIZE_T ssize_t;
#endif
#include <math.h>

#include <stdio.h>
#include <stdlib.h>
#if defined(_OPENMP)
    #include <omp.h>
#endif

#if defined(__GLIBC__)
  #include <endian.h>
  #ifndef be64toh
    /* Support older glibc (<2.9) which lack be64toh */
    #include <byteswap.h>
    #if __BYTE_ORDER == __BIG_ENDIAN
      #define be32toh(x) (x)
      #define le32toh(x) __bswap_32 (x)
      #define be64toh(x) (x)
      #define le64toh(x) __bswap_64 (x)
    #else
      #define be32toh(x) __bswap_32 (x)
      #define le32toh(x) (x)
      #define be64toh(x) __bswap_64 (x)
      #define le64toh(x) (x)
    #endif
  #endif
#elif defined (__APPLE__)
  #include <libkern/OSByteOrder.h>
  #define be32toh(x) OSSwapBigToHostInt32(x)
  #define le32toh(x) OSSwapLittleToHostInt32(x)
  #define be64toh(x) OSSwapBigToHostInt64(x)
  #define le64toh(x) OSSwapLittleToHostInt64(x)
#elif defined(_MSC_VER)
  #define be32toh(x) _byteswap_ulong(x)
  #define le32toh(x) (x)
  #define be64toh(x) _byteswap_uint64(x)
  #define le64toh(x) (x)
#endif


#ifdef LUT
  #include "lut.h"

  #define D2R (32768.0 / 360.0)
  #define R2D (1.0 / D2R)
  #define Q15 (1.0/(double)((1<<15)-1))

  double sin(double x) {
      return sin1(x) * Q15;
  }
  double cos(double x) {
      return cos1(x) * Q15;
  }
#else
  #define D2R (M_PI / 180.)
#endif
#define R2D (1.0 / D2R)


#ifdef _WIN32
ssize_t pread(int fd, void *buf, size_t count, off_t offset) {
    ssize_t ret;
    __int64 old_offset;

    if (count >= INT_MAX || offset >= INT64_MAX || offset < 0) {
        return -1;
    }

    old_offset = _lseeki64(fd, 0, SEEK_CUR);
    if (old_offset == -1) {
        return -1;
    }

    if (offset != _lseeki64(fd, (__int64)offset, SEEK_SET)) {
        return -1;
    }

    ret = _read(fd, buf, (unsigned int)count);
    if (old_offset != _lseeki64(fd, old_offset, SEEK_SET)) {
        return -1;
    }
    return ret;
}
#endif

struct module_state {
    PyObject *error;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

typedef npy_float32 gf_dtype;
typedef npy_float32 float32_t;
typedef npy_float64 float64_t;

#if (PY_VERSION_HEX >= 0x02070000)
  #define HAVE_CAPSULE
#endif

#define GF_STORE_IS_LITTLE_ENDIAN

#ifdef GF_STORE_IS_LITTLE_ENDIAN
  #define xe64toh le64toh
  #define xe32toh le32toh
#endif

#ifdef GF_STORE_IS_BIG_ENDIAN
  #define xe64toh be64toh
  #define xe32toh be32toh
#endif

/*#define fe32toh_void(x) \
   ({ int32_t _i; \
      _i = xe32toh(*((int32_t*)&(x))); \
      *((gf_dtype*)&_i); })*/

gf_dtype fe32toh(const gf_dtype x) {
    int32_t x1, x2;
    gf_dtype r;
    memcpy(&x1, &x, 4);
    x2 = xe32toh(x1);
    memcpy(&r, &x2, 4);
    return r;
}

#ifndef max
    #define max(a,b) \
       ({ __typeof__ (a) _a = (a); \
          __typeof__ (b) _b = (b); \
         _a > _b ? _a : _b; })
#endif

#ifndef min
    #define min(a,b) \
       ({ __typeof__ (a) _a = (a); \
          __typeof__ (b) _b = (b); \
         _a < _b ? _a : _b; })
#endif

typedef enum {
    SUCCESS = 0,
    INVALID_RECORD,
    EMPTY_RECORD,
    BAD_RECORD,
    ALLOC_FAILED,
    BAD_REQUEST,
    BAD_DATA_OFFSET,
    READ_DATA_FAILED,
    SEEK_INDEX_FAILED,
    READ_INDEX_FAILED,
    FSTAT_TRACES_FAILED,
    BAD_STORE,
    MMAP_INDEX_FAILED,
    MMAP_TRACES_FAILED,
    INDEX_OUT_OF_BOUNDS,
    NTARGETS_OUT_OF_BOUNDS,
} store_error_t;

const char* store_error_names[] = {
    "SUCCESS",
    "INVALID_RECORD",
    "EMPTY_RECORD",
    "BAD_RECORD",
    "ALLOC_FAILED",
    "BAD_REQUEST",
    "BAD_DATA_OFFSET",
    "READ_DATA_FAILED",
    "SEEK_INDEX_FAILED",
    "READ_INDEX_FAILED",
    "FSTAT_TRACES_FAILED",
    "BAD_STORE",
    "MMAP_INDEX_FAILED",
    "MMAP_TRACES_FAILED",
    "INDEX_OUT_OF_BOUNDS",
    "NTARGETS_OUT_OF_BOUNDS",
};

#define NDIMS_CONTINUOUS_MAX 4

typedef struct {
    float64_t mins[NDIMS_CONTINUOUS_MAX];
    float64_t maxs[NDIMS_CONTINUOUS_MAX];
    float64_t deltas[NDIMS_CONTINUOUS_MAX];
    uint64_t ns[NDIMS_CONTINUOUS_MAX];
    uint64_t ng;
} mapping_t;

/* mapping scheme defs */

#define VICINITY_NIP_MAX 8

typedef enum {
    NEAREST_NEIGHBOR = 0,
    MULTILINEAR,
    UNDEFINED_INTERPOLATION_SCHEME,
} interpolation_scheme_id;

const char* interpolation_scheme_names[] = {
    "nearest_neighbor",
    "multilinear",
    NULL,
};

typedef store_error_t (*irecord_function_t)(const mapping_t*, const float64_t*, const float64_t*, uint64_t*);
typedef store_error_t (*vicinity_function_t)(const mapping_t*, const float64_t*, const float64_t*, uint64_t*, float64_t*);

static store_error_t irecord_function_type_0(const mapping_t*, const float64_t*, const float64_t*, uint64_t*);
static store_error_t vicinity_function_type_0(const mapping_t*, const float64_t*, const float64_t*, uint64_t*, float64_t*);

static store_error_t irecord_function_type_a(const mapping_t*, const float64_t*, const float64_t*, uint64_t*);
static store_error_t vicinity_function_type_a(const mapping_t*, const float64_t*, const float64_t*, uint64_t*, float64_t*);

static store_error_t irecord_function_type_b(const mapping_t*, const float64_t*, const float64_t*, uint64_t*);
static store_error_t vicinity_function_type_b(const mapping_t*, const float64_t*, const float64_t*, uint64_t*, float64_t*);

static store_error_t irecord_function_type_c(const mapping_t*, const float64_t*, const float64_t*, uint64_t*);
static store_error_t vicinity_function_type_c(const mapping_t*, const float64_t*, const float64_t*, uint64_t*, float64_t*);

typedef struct {
    const char *name;
    const size_t vicinity_nip;
    const size_t ndims_continuous;
    const irecord_function_t irecord;
    const vicinity_function_t vicinity;
} mapping_scheme_t;

typedef enum {
    TYPE_0 = 0,
    TYPE_A,
    TYPE_B,
    TYPE_C,
} mapping_scheme_id;

const mapping_scheme_t mapping_schemes[] = {
    {"type_0", 2, 1, irecord_function_type_0, vicinity_function_type_0},
    {"type_a", 4, 2, irecord_function_type_a, vicinity_function_type_a},
    {"type_b", 8, 3, irecord_function_type_b, vicinity_function_type_b},
    {"type_c", 8, 3, irecord_function_type_c, vicinity_function_type_c},
    {NULL, 0, 0, NULL, NULL},
};

/* store record defs */

#define REC_EMPTY 0
#define REC_ZERO 1
#define REC_SHORT 2

typedef struct {
    uint64_t data_offset;
    int32_t itmin;
    int32_t nsamples;
    gf_dtype begin_value;
    gf_dtype end_value;
} record_t;

typedef struct {
    int f_index;
    int f_data;
    uint64_t nrecords;
    uint64_t data_size;
    float64_t deltat;
    record_t *records;
    gf_dtype *data;
    gf_dtype **memdata;
    const mapping_scheme_t *mapping_scheme;
    mapping_t *mapping;
} store_t;

typedef struct {
    int is_zero;
    int32_t itmin;
    int32_t nsamples;
    gf_dtype begin_value;
    gf_dtype end_value;
    gf_dtype *data;
} trace_t;

/* result trace sheme defs */

#define RESULT_INIT_CAPACITY 1024

typedef struct {
    int is_zero;
    int32_t icomponent;
    int32_t itmin;
    int32_t itmin_want;
    int32_t nsamples;
    int32_t nsamples_want;
    int32_t ncapacity;
    store_error_t err;
    gf_dtype begin_value;
    gf_dtype end_value;
    gf_dtype *data;
    gf_dtype *buffer;
} result_trace_t;

/* component scheme defs */

#define NCOMPONENTS_MAX 3
#define NSUMMANDS_MAX 6

typedef void (*make_weights_function_t)(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_dummy(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_elastic2(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_elastic5(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_elastic8(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_elastic10(const float64_t*, const float64_t*, const float64_t*, float64_t*);
static void make_weights_elastic18(const float64_t*, const float64_t*, const float64_t*, float64_t*);
/*static void make_weights_poroelastic10(const float64_t*, const float64_t*, const float64_t*, float64_t*);*/

typedef struct {
    const char *name;
    const size_t nsource_terms;
    const size_t ncomponents;
    const size_t nsummands_max;
    const size_t *nsummands;
    const uint64_t **igs;
    const make_weights_function_t make_weights;
} component_scheme_t;

const size_t nsummands_dummy[] = {1};
static const uint64_t igs_dummy_0[] = {0};
static const uint64_t *igs_dummy[] = {igs_dummy_0};

const size_t nsummands_elastic2[] = {1, 1, 1};
static const uint64_t igs_elastic2_0[] = {0};
static const uint64_t igs_elastic2_1[] = {0};
static const uint64_t igs_elastic2_2[] = {1};
static const uint64_t *igs_elastic2[] = {igs_elastic2_0, igs_elastic2_1, igs_elastic2_2};

const size_t nsummands_elastic5[] = {3, 3, 2};
static const uint64_t igs_elastic5_0[] = {0, 1, 2};
static const uint64_t igs_elastic5_1[] = {0, 1, 2};
static const uint64_t igs_elastic5_2[] = {3, 4};
static const uint64_t *igs_elastic5[] = {igs_elastic5_0, igs_elastic5_1, igs_elastic5_2};

const size_t nsummands_elastic8[] = {5, 5, 3};
static const uint64_t igs_elastic8_0[] = {0, 1, 2, 3, 4};
static const uint64_t igs_elastic8_1[] = {0, 1, 2, 3, 4};
static const uint64_t igs_elastic8_2[] = {5, 6, 7};
static const uint64_t *igs_elastic8[] = {igs_elastic8_0, igs_elastic8_1, igs_elastic8_2};

const size_t nsummands_elastic10[] = {6, 6, 4};
static const uint64_t igs_elastic10_0[] = {0, 1, 2, 8, 3, 4};
static const uint64_t igs_elastic10_1[] = {0, 1, 2, 8, 3, 4};
static const uint64_t igs_elastic10_2[] = {5, 6, 7, 9};
static const uint64_t *igs_elastic10[] = {igs_elastic10_0, igs_elastic10_1, igs_elastic10_2};

const size_t nsummands_elastic18[] = {6, 6, 6};
static const uint64_t igs_elastic18_0[] = {0, 1, 2, 3, 4, 5};
static const uint64_t igs_elastic18_1[] = {6, 7, 8, 9, 10, 11};
static const uint64_t igs_elastic18_2[] = {12, 13, 14, 15, 16, 17};
static const uint64_t *igs_elastic18[] = {igs_elastic18_0, igs_elastic18_1, igs_elastic18_2};

typedef enum {
    DUMMY = 0,
    ELASTIC2,
    ELASTIC5,
    ELASTIC8,
    ELASTIC10,
    ELASTIC18,
    /*POROELASTIC10,*/
} component_scheme_id;

const component_scheme_t component_schemes[] = {
    {"dummy", 1, 1, 1, nsummands_dummy, igs_dummy, make_weights_dummy},
    {"elastic2", 1, 3, 1, nsummands_elastic2, igs_elastic2, make_weights_elastic2},
    {"elastic5", 3, 3, 3, nsummands_elastic5, igs_elastic5, make_weights_elastic5},
    {"elastic8", 6, 3, 5, nsummands_elastic8, igs_elastic8, make_weights_elastic8},
    {"elastic10", 6, 3, 6, nsummands_elastic10, igs_elastic10, make_weights_elastic10},
    {"elastic18", 6, 3, 6, nsummands_elastic18, igs_elastic18, make_weights_elastic18},
    /* {"poroelastic10", 1, 9, nsummands_poroelastic10, igs_poroelastic10, make_weights_poroelastic10}, */
    {NULL, 0, 0, 0, NULL, NULL, NULL},
};

const component_scheme_t *get_component_scheme(char *name) {
    const component_scheme_t *s;
    s = component_schemes;
    while (s->name != NULL) {
        if (0 == strcmp(s->name, name)) {
            return s;
        }
        s++;
    }
    return NULL;
}

const mapping_scheme_t *get_mapping_scheme(char *name) {
    const mapping_scheme_t *s;
    s = mapping_schemes;
    while (s->name != NULL) {
        if (0 == strcmp(s->name, name)) {
            return s;
        }
        s++;
    }
    return NULL;
}

interpolation_scheme_id get_interpolation_scheme_id(char *name) {
    interpolation_scheme_id i;
    i = 0;
    while (interpolation_scheme_names[i] != NULL) {
        if (0 == strcmp(interpolation_scheme_names[i], name)) {
            return i;
        }
        i++;
    }
    return UNDEFINED_INTERPOLATION_SCHEME;
}

int good_array(PyObject* o, int typenum_want, npy_intp size_want, int ndim_want, npy_intp* shape_want) {
    int i;

    if (!PyArray_Check(o)) {
        PyErr_SetString(PyExc_AttributeError, "not a NumPy array" );
        return 0;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != typenum_want) {
        PyErr_SetString(PyExc_AttributeError, "array of unexpected type");
        return 0;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is not contiguous or not well behaved");
        return 0;
    }

    if (size_want != -1 && size_want != PyArray_SIZE((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is of unexpected size");
        return 0;
    }
    if (ndim_want != -1 && ndim_want != PyArray_NDIM((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is of unexpected ndim");
        return 0;
    }

    if (ndim_want != -1 && shape_want != NULL) {
        for (i=0; i<ndim_want; i++) {
            if (shape_want[i] != -1 && shape_want[i] != PyArray_DIMS((PyArrayObject*)o)[i]) {
                PyErr_SetString(PyExc_AttributeError, "array is of unexpected shape");
                return 0;
            }
        }
    }
    return 1;
}

static const trace_t ZERO_TRACE = { 1, 0, 0, 0.0, 0.0, NULL };
static const store_t ZERO_STORE = { 0, 0, 0, 0, 0.0, NULL, NULL, NULL, NULL, NULL };

static store_error_t store_get_span(const store_t *store, uint64_t irecord,
                                    int32_t *itmin, int32_t *nsamples, int *is_zero) {
    record_t *record;
    if (irecord >= store->nrecords) {
        return INVALID_RECORD;
    }

    record = &store->records[irecord];
    *itmin = xe32toh(record->itmin);
    *nsamples = xe32toh(record->nsamples);
    *is_zero = REC_ZERO == xe64toh(record->data_offset);

    if (!inlimits(*itmin) || !inposlimits(*nsamples)) {
        return BAD_RECORD;
    }

    return SUCCESS;
}

static store_error_t store_read(
        const store_t *store,
        uint64_t data_offset,
        size_t nbytes,
        void *data) {

    size_t nhave;
    ssize_t nread;

    nhave = 0;
    while (nhave < nbytes) {
        nread = pread(store->f_data, data, nbytes-nhave, data_offset+nhave);
        if (-1 == nread) {
            return READ_DATA_FAILED;
        }
        nhave += nread;
    }

    return SUCCESS;
}

static store_error_t store_get(
        const store_t *store,
        uint64_t irecord,
        trace_t *trace) {

    record_t *record;
    uint64_t data_offset;
    store_error_t err;
    size_t nbytes;

    if (irecord >= store->nrecords) {
        *trace = ZERO_TRACE;
        return INVALID_RECORD;
    }

    record = &store->records[irecord];
    data_offset = xe64toh(record->data_offset);
    trace->itmin = xe32toh(record->itmin);
    trace->nsamples = xe32toh(record->nsamples);
    trace->begin_value = fe32toh(record->begin_value);
    trace->end_value = fe32toh(record->end_value);

    if (!inlimits(trace->itmin) || !inposlimits(trace->nsamples) ||
            data_offset >= UINT64_MAX - SLIMIT * sizeof(gf_dtype)) {
        return BAD_RECORD;
    }

    if (REC_EMPTY == data_offset) {
        *trace = ZERO_TRACE;
        return EMPTY_RECORD;
    }

    if (REC_ZERO == data_offset) {
        *trace = ZERO_TRACE;
        trace->itmin = xe32toh(record->itmin);
        return SUCCESS;
    }

    trace->is_zero = 0;

    if (data_offset + trace->nsamples*sizeof(gf_dtype) > store->data_size) {
        *trace = ZERO_TRACE;
        return BAD_DATA_OFFSET;
    }

    if (REC_SHORT == data_offset) {
        trace->data = &record->begin_value;
    } else {
        if (NULL != store->data) {
            trace->data = &store->data[data_offset/sizeof(gf_dtype)];
        } else {
            if (NULL == store->memdata[irecord]) {
                nbytes = trace->nsamples * sizeof(gf_dtype);
                store->memdata[irecord] = (gf_dtype*)malloc(nbytes);
                if (NULL == store->memdata[irecord]) {
                    *trace = ZERO_TRACE;
                    return ALLOC_FAILED;
                }
                err = store_read(store, data_offset, nbytes, store->memdata[irecord]);
                if (SUCCESS != err) {
                    free(store->memdata[irecord]);
                    store->memdata[irecord] = NULL;
                    *trace = ZERO_TRACE;
                    return err;
                }
            }
            trace->data = store->memdata[irecord];
        }
    }

    return SUCCESS;
}

static int clipint32(int32_t lo, int32_t hi, int32_t n) {
    return n <= lo ? lo : n >= hi ? hi : n;
}

static void trace_trim(trace_t *trace, int32_t itmin, int32_t nsamples) {
    int32_t ilo, ihi;
    ilo = max(itmin, trace->itmin);
    ihi = min(itmin + nsamples, trace->itmin + trace->nsamples);
    trace->data = (trace->nsamples == 0) ? NULL : (trace->data + (ilo - trace->itmin));
    trace->itmin = ilo;
    trace->nsamples = max(0, ihi - ilo);
}

static void trace_trim_sticky(trace_t *trace, int32_t itmin, int32_t nsamples) {
    int32_t ilo, ihi;
    ilo = clipint32(0, trace->nsamples-1, itmin-trace->itmin);
    ihi = clipint32(1, trace->nsamples, itmin+nsamples-trace->itmin);
    trace->itmin = trace->itmin + ilo;
    trace->nsamples = max(0, (ihi - ilo));
    trace->data += ilo;
}

static store_error_t store_sum_extent(
            const store_t *store,
            const uint64_t *irecords,
            const float64_t *delays,
            int n,
            int32_t *nsamples_,
            int32_t *itmin_) {

    float64_t itmin_d, itmax_d, idelay_d;
    int32_t itmax, itmin, ns;
    int ihave, is_zero, j;
    store_error_t err;
    itmin_d = itmax_d = 0.0;
    itmin = 0;
    ihave = 0;

    if (n == 0) {
        *itmin_ = 0;
        *nsamples_ = 0;
        return SUCCESS;
    }

    for (j=0; j<n; j++) {
        err = store_get_span(store, irecords[j], &itmin, &ns, &is_zero);
        if (SUCCESS != err) {
            return err;
        }

        itmax = itmin + ns - 1;
        idelay_d = delays[j]/store->deltat;

        if (ihave) {
            itmin_d = min(itmin_d, itmin + idelay_d);
            itmax_d = max(itmax_d, itmax + idelay_d);
        } else {
            itmin_d = itmin + idelay_d;
            itmax_d = itmax + idelay_d;
            ihave = 1;
        }
    }


    *itmin_ = (int32_t) floor(itmin_d);
    *nsamples_ = (int32_t) ceil(itmax_d) - *itmin_ + 1;

    return SUCCESS;
}

static store_error_t store_sum(
        const store_t *store,
        const uint64_t *irecords,
        const float64_t *delays,
        const float32_t *weights,
        int n,
        trace_t *result) {

    float32_t weight;
    float64_t delay;
    trace_t trace;
    float64_t deltat = store->deltat;
    int ilo;
    int i, j;
    int idelay_floor, idelay_ceil;
    float w1, w2;
    store_error_t err;
    int32_t itmin;
    int32_t nsamples;
    gf_dtype *out;

    out = result->data;
    itmin = result->itmin;
    nsamples = result->nsamples;

    result->is_zero = 1;

    if (!inlimits(itmin) || !inposlimits(nsamples)) {
        return BAD_REQUEST;
    }

    if (0 == n) {
        return SUCCESS;
    }

    for (j=0; j<n; j++) {

        delay = delays[j];
        weight = weights[j];
        idelay_floor = (int)floor(delay/deltat);
        idelay_ceil = (int)ceil(delay/deltat);
        if (!inlimits(idelay_floor) || !inlimits(idelay_ceil))
            return BAD_REQUEST;

        if (0.0 == weight) {
            continue;
        }

        err = store_get(store, irecords[j], &trace);
        if (SUCCESS != err)
            return err;

        if (trace.is_zero)
            continue;

        trace_trim_sticky(&trace, itmin - idelay_ceil, nsamples + idelay_ceil - idelay_floor);

        if (idelay_floor == idelay_ceil) {
            ilo = itmin - idelay_floor - trace.itmin;
            /*for (i=0; i<nsamples; i++) {
                ifloor = i + ilo;
                ifloor = max(0, min(ifloor, trace.nsamples-1));
                out[i] += fe32toh(trace.data[ifloor]) * weight;
            } // version below is a bit faster */
            for (i=0; i<min(-ilo,nsamples); i++) {
                out[i] += fe32toh(trace.data[0]) * weight;
            }
            for (i=max(0,-ilo); i<min(nsamples, trace.nsamples-ilo); i++) {
                out[i] += fe32toh(trace.data[i+ilo]) * weight;
            }
            for (i=max(0,trace.nsamples-ilo); i<nsamples; i++) {
                out[i] += fe32toh(trace.data[trace.nsamples-1]) * weight;
            }
        } else {
            ilo = itmin - idelay_floor - trace.itmin;
            /*ihi = ilo - 1;*/
            w1 = (idelay_ceil - delay/deltat);
            w2 = 1.0 - w1;
            w1 *= weight;
            w2 *= weight;
            /* printf("- w1 %f, w2 %f\n", w1, w2); */
            /*for (i=0; i<nsamples; i++) {
                ifloor = i + ilo;
                iceil = i + ihi;
                ifloor = max(0, min(ifloor, trace.nsamples-1));
                iceil = max(0, min(iceil, trace.nsamples-1));
                out[i] += fe32toh(trace.data[ifloor]) * w1;
                out[i] += fe32toh(trace.data[iceil]) * w2;
            } // version below is a bit faster */
            for (i=0; i<min(-ilo,nsamples); i++) {
                out[i] += fe32toh(trace.data[0]) * weight;
            }
            for (i=max(0,-ilo); i<min(nsamples, -ilo+1); i++) {
                out[i] += fe32toh(trace.data[i+ilo])*w1
                          + fe32toh(trace.data[0])*w2;
            }
            for (i=max(0,-ilo+1); i<min(nsamples, trace.nsamples-ilo); i++) {
                out[i] += fe32toh(trace.data[i+ilo])*w1
                          + fe32toh(trace.data[i+ilo-1])*w2;
            }
            for (i=max(0,trace.nsamples-ilo);
                 i<min(nsamples, trace.nsamples-ilo+1); i++) {
                out[i] += fe32toh(trace.data[trace.nsamples-1]) * w1
                          + fe32toh(trace.data[i+ilo-1])*w2;
            }
            for (i=max(0,trace.nsamples-ilo+1); i<nsamples; i++) {
                out[i] += fe32toh(trace.data[trace.nsamples-1]) * weight;
            }
        }

        result->begin_value += trace.begin_value * weight;
        result->end_value += trace.end_value * weight;
    }

    result->is_zero = 0;

    return SUCCESS;
}

static store_error_t store_sum_static(
        const store_t *store,
        const uint64_t *irecords,
        const float64_t *delays,
        const float32_t *weights,
        int32_t it,
        int32_t ntargets,
        size_t nsummands,
        size_t nsources,
        int32_t nthreads,
        gf_dtype *result) {

    float32_t weight;
    float64_t delay;
    trace_t trace;
    float64_t deltat = store->deltat;
    int idelay_floor, idelay_ceil;
    int j, itarget, idx;
    uint64_t isummand, nsummands_src;
    float w1, w2;
    store_error_t err=SUCCESS;
    (void) nthreads;

    if (0 == nsummands || 0 == ntargets)
        return SUCCESS;

    if (!inlimits(it))
        return BAD_REQUEST;

    if (result == NULL)
        return ALLOC_FAILED;

    nsummands_src = nsummands / nsources;

    Py_BEGIN_ALLOW_THREADS
    #if defined(_OPENMP)
        if (nthreads == 0)
            nthreads = omp_get_num_procs();

        #pragma omp parallel \
            shared (store, irecords, delays, weights, ntargets, nsummands, \
                    result, it, deltat) \
            private (j, isummand, delay, weight, idelay_floor, idelay_ceil, idx, trace, w1, w2) \
            reduction (+: err) \
            num_threads (nthreads)
        {
        #pragma omp for schedule (static)
    #endif
        for (itarget=0; itarget<ntargets; itarget++) {
            for (isummand=0; isummand<nsummands; isummand++) {
                j = itarget*nsummands + isummand;

                delay = delays[isummand / nsummands_src];
                weight = weights[j];
                idelay_floor = (int) floor(delay/deltat);
                idelay_ceil = (int) ceil(delay/deltat);

                if (weight == 0.)
                    continue;

                if (!inlimits(idelay_floor) || !inlimits(idelay_ceil))
                    err += BAD_REQUEST;

                err += store_get(store, irecords[j], &trace);

                if (trace.is_zero)
                    continue;

                idx = it - idelay_floor - trace.itmin;

                if (idelay_floor == idelay_ceil) {
                    result[itarget] += fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * weight;
                } else {
                    w1 = (idelay_ceil - delay/deltat);
                    w2 = (1.0-w1);
                    result[itarget] += (
                        fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * w1
                        + fe32toh(trace.data[max(0, min(idx-1, trace.nsamples-1))]) * w2) * weight;
                }
            }
        }
    #if defined(_OPENMP)
        }
    #endif
    Py_END_ALLOW_THREADS
    if (err != SUCCESS)
        return BAD_REQUEST;
    return SUCCESS;
}


static store_error_t ensure_trace_capacity(result_trace_t *result, int itmin, int itmax) {
    int ncapacity, buf_pos, nsamples, i;
    int ncapacity_add;
    int ishift;
    int itmin_buffer, itmax_buffer;
    int result_itmax;
    gf_dtype *buffer, value;

    if (result->nsamples_want != -1) {  /* fixed length request, nothing to do */
        return SUCCESS;
    }

    if (result->buffer == NULL) {  /* initial allocation */
        itmin_buffer = itmin;
        itmax_buffer = itmax;
        nsamples = itmax - itmin + 1;
        ncapacity = max(nsamples * 3, RESULT_INIT_CAPACITY);
        buffer = (gf_dtype*) calloc(ncapacity, sizeof(gf_dtype));
        if (buffer == NULL)
            return ALLOC_FAILED;


        buf_pos = (ncapacity - nsamples) / 2;
        result->buffer = buffer;
        result->data = result->buffer + buf_pos;
        result->ncapacity = ncapacity;
        result->itmin = itmin;
        result->nsamples = nsamples;
    } else {
        itmin_buffer = result->itmin - (int)(result->data - result->buffer);
        itmax_buffer = itmin_buffer + result->ncapacity - 1;
        itmin = min(itmin, result->itmin);
        itmax = max(itmax, result->itmin + result->nsamples - 1);
    }

    if (itmin < itmin_buffer || itmax_buffer < itmax) {  /* resize */
        buf_pos = (int)(result->data - result->buffer);
        ncapacity = result->ncapacity;
        do {
            ncapacity_add = max(ncapacity, RESULT_INIT_CAPACITY);
            ncapacity += ncapacity_add;
            buf_pos += ncapacity_add / 2;
            itmin_buffer -= ncapacity_add / 2;
            itmax_buffer = itmin_buffer + ncapacity - 1;
        } while (itmin < itmin_buffer || itmax_buffer < itmax);

        buffer = (gf_dtype*) calloc(ncapacity, sizeof(gf_dtype));
        if (buffer == NULL)
            return ALLOC_FAILED;

        memcpy(buffer + buf_pos, result->data, sizeof(gf_dtype) * result->nsamples);
        free(result->buffer);

        result->buffer = buffer;
        result->data = result->buffer + buf_pos;
        result->ncapacity = ncapacity;
    }

    if (itmin < result->itmin) {  /* extend front */
        ishift = result->itmin - itmin;
        value = result->data[0];
        for (i=result->itmin-1; i>=itmin; i--)
            result->data[i-result->itmin] = value;

        result->data -= ishift;
        result->nsamples += ishift;
        result->itmin -= ishift;
    }

    result_itmax = result->itmin + result->nsamples - 1;

    if (result_itmax < itmax) {  /* extend back */
        ishift = itmax - result_itmax;
        value = result->data[result->nsamples-1];
        for (i=result_itmax+1; i<=itmax; i++)
            result->data[i-result->itmin] = value;

        result->nsamples += ishift;
    }

    return SUCCESS;
}


static store_error_t check_trace_extent(
        store_t *store,
        result_trace_t *result,
        float64_t delay,
        int irecord) {

    int itmin, itmax, ns, is_zero;
    float64_t idelay_d;
    store_error_t err = SUCCESS;
    ns = itmin = 0;

    if (result->nsamples_want == -1) {
        err = store_get_span(store, irecord, &itmin, &ns, &is_zero);
        idelay_d = delay/store->deltat;
        itmax = (int) ceil((itmin + ns - 1) + idelay_d);
        itmin = (int) floor(itmin + idelay_d);
    } else {
        itmin = result->itmin_want;
        itmax = result->itmin_want + result->nsamples_want - 1;
    }

    err += ensure_trace_capacity(result, itmin, itmax);

    return err;
}


static store_error_t stack_trace_timeseries(
        trace_t *trace,
        float32_t weight,
        int itmin,
        float64_t delay,
        int idelay_floor,
        int idelay_ceil,
        int nsamples,
        float64_t deltat,
        gf_dtype* out) {

    int ilo, i;
    float w1, w2;

    if (idelay_floor == idelay_ceil) {
        ilo = itmin - idelay_floor - trace->itmin;
        /*for (i=0; i<nsamples; i++) {
            ifloor = i + ilo;
            ifloor = max(0, min(ifloor, trace->nsamples-1));
            out[i] += fe32toh(trace->data[ifloor]) * weight;
        } // version below is a bit faster */
        for (i=0; i<min(-ilo,nsamples); i++) {
            out[i] += fe32toh(trace->data[0]) * weight;
        }
        for (i=max(0,-ilo); i<min(nsamples, trace->nsamples-ilo); i++) {
            out[i] += fe32toh(trace->data[i+ilo]) * weight;
        }
        for (i=max(0,trace->nsamples-ilo); i<nsamples; i++) {
            out[i] += fe32toh(trace->data[trace->nsamples-1]) * weight;
        }
    } else {
        ilo = itmin - idelay_floor - trace->itmin;
        /*ihi = ilo - 1;*/
        w1 = (idelay_ceil - delay/deltat);
        w2 = 1.0 - w1;
        w1 *= weight;
        w2 *= weight;
        /* printf("- w1 %f, w2 %f\n", w1, w2); */
        /*for (i=0; i<nsamples; i++) {
            ifloor = i + ilo;
            iceil = i + ihi;
            ifloor = max(0, min(ifloor, trace->nsamples-1));
            iceil = max(0, min(iceil, trace->nsamples-1));
            out[i] += fe32toh(trace->data[ifloor]) * w1;
            out[i] += fe32toh(trace->data[iceil]) * w2;
        } // version below is a bit faster */
        for (i=0; i<min(-ilo, nsamples); i++) {
            out[i] += fe32toh(trace->data[0]) * weight;
        }
        for (i=max(0, -ilo); i<min(nsamples, -ilo+1); i++) {
            out[i] += fe32toh(trace->data[i+ilo])*w1
                      + fe32toh(trace->data[0])*w2;
        }
        for (i=max(0, -ilo+1); i<min(nsamples, trace->nsamples-ilo); i++) {
            out[i] += fe32toh(trace->data[i+ilo])*w1
                      + fe32toh(trace->data[i+ilo-1])*w2;
        }
        for (i=max(0, trace->nsamples-ilo);
             i<min(nsamples, trace->nsamples-ilo+1); i++) {
            out[i] += fe32toh(trace->data[trace->nsamples-1]) * w1
                      + fe32toh(trace->data[i+ilo-1])*w2;
        }
        for (i=max(0, trace->nsamples-ilo+1); i<nsamples; i++) {
            out[i] += fe32toh(trace->data[trace->nsamples-1]) * weight;
        }
    }
    return SUCCESS;
}


static store_error_t store_calc_timeseries(
        store_t *store,
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *delays,
        const float64_t *receiver_coords,
        size_t nsources,
        size_t nreceivers,
        const component_scheme_t *cscheme,
        const mapping_scheme_t *mscheme,
        const mapping_t *mapping,
        interpolation_scheme_id interpolation,
        int32_t nthreads,
        result_trace_t *results) {

    float32_t weight;
    float64_t delay;
    trace_t trace;
    result_trace_t *result;
    float64_t deltat = store->deltat;
    int idelay_floor, idelay_ceil;
    uint64_t irecord;
    store_error_t err = SUCCESS;

    size_t ireceiver, isource, iip, nip, icomponent, isummand, nsummands_max, nsummands;
    float64_t ws_this[NCOMPONENTS_MAX*NSUMMANDS_MAX];
    uint64_t irecord_bases[VICINITY_NIP_MAX];
    float64_t weights_ip[VICINITY_NIP_MAX];

    nsummands_max = cscheme->nsummands_max;
    nip = mscheme->vicinity_nip;

    Py_BEGIN_ALLOW_THREADS
    #if defined(_OPENMP)
        if (nthreads == 0)
            nthreads = omp_get_num_procs();
        else if (nthreads > omp_get_num_procs()) {
            nthreads = omp_get_num_procs();
            printf("store_calc_static - Warning: Desired nthreads exceeds number of physical processors, falling to %d threads\n", nthreads);
        }

        #pragma omp parallel \
            shared (store, source_coords, ms, delays, receiver_coords, \
                    cscheme, mscheme, mapping, interpolation, nip, results, nsources, nsummands_max) \
            private (isource, iip, icomponent, isummand, nsummands, irecord_bases, weights_ip, ws_this, \
                     delay, weight, idelay_floor, idelay_ceil, irecord, trace, result, err) \
            num_threads (nthreads)
        {
        #pragma omp for schedule (dynamic)
    #endif

    for (ireceiver=0; ireceiver<nreceivers; ireceiver++) {
        for (isource=0; isource<nsources; isource++) {

            cscheme->make_weights(
                &source_coords[isource*5],
                &ms[isource*cscheme->nsource_terms],
                &receiver_coords[ireceiver*5],
                ws_this);

            delay = delays[isource];
            idelay_floor = (int) floor(delay/deltat);
            idelay_ceil = (int) ceil(delay/deltat);

            if (!inlimits(idelay_floor) || !inlimits(idelay_ceil)) {
                for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                    result = &(results[icomponent+ireceiver*cscheme->ncomponents]);
                    result->err = BAD_REQUEST;
                }
                continue;
            }

            if (interpolation == MULTILINEAR) {
                err = mscheme->vicinity(
                    mapping,
                    &source_coords[isource*5],
                    &receiver_coords[ireceiver*5],
                    irecord_bases,
                    weights_ip);

                if (err != SUCCESS) {
                    for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                        result = &(results[icomponent+ireceiver*cscheme->ncomponents]);
                        result->err = err;
                    }
                    continue;
                }

                for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {

                    result = &(results[icomponent+ireceiver*cscheme->ncomponents]);

                    nsummands = cscheme->nsummands[icomponent];

                    for (iip=0; iip<nip; iip++) {
                        for (isummand=0; isummand<nsummands; isummand++) {
                            weight = weights_ip[iip] * ws_this[icomponent*nsummands_max + isummand];

                            irecord = irecord_bases[iip] + cscheme->igs[icomponent][isummand];
                            err = check_trace_extent(store, result, delay, irecord);
                            if (err != SUCCESS || weight == 0.) {
                                result->err = err;
                                continue;
                            }

                            err = store_get(store, irecord, &trace);
                            if (err != SUCCESS || trace.is_zero) {
                                result->err = err;
                                continue;
                            }

                            trace_trim_sticky(
                                &trace,
                                result->itmin - idelay_ceil,
                                result->nsamples + idelay_ceil - idelay_floor);

                            stack_trace_timeseries(
                                &trace,
                                weight,
                                result->itmin,
                                delay,
                                idelay_floor,
                                idelay_ceil,
                                result->nsamples,
                                deltat,
                                result->data);

                            result->begin_value += trace.begin_value * weight;
                            result->end_value += trace.end_value * weight;
                        }
                    }

                    result->is_zero = 0;
                }
            } else if (interpolation == NEAREST_NEIGHBOR) {
                err = mscheme->irecord(
                    mapping,
                    &source_coords[isource*5],
                    &receiver_coords[ireceiver*5],
                    irecord_bases);

                if (err != SUCCESS) {
                    for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                        result = &(results[icomponent+ireceiver*cscheme->ncomponents]);
                        result->err = err;
                    }
                    continue;
                }

                for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {

                    result = &(results[icomponent+ireceiver*cscheme->ncomponents]);

                    nsummands = cscheme->nsummands[icomponent];

                    for (isummand=0; isummand<nsummands; isummand++) {
                        weight = ws_this[icomponent*nsummands_max + isummand];

                        irecord = irecord_bases[0] + cscheme->igs[icomponent][isummand];
                        err = check_trace_extent(store, result, delay, irecord);
                        if (err != SUCCESS || weight == 0.) {
                            result->err = err;
                            continue;
                        }

                        err = store_get(store, irecord, &trace);
                        if (err != SUCCESS || trace.is_zero) {
                            result->err = err;
                            continue;
                        }

                        trace_trim_sticky(
                            &trace,
                            result->itmin - idelay_ceil,
                            result->nsamples + idelay_ceil - idelay_floor);

                        stack_trace_timeseries(
                            &trace,
                            weight,
                            result->itmin,
                            delay,
                            idelay_floor,
                            idelay_ceil,
                            result->nsamples,
                            deltat,
                            result->data);

                        result->begin_value += trace.begin_value * weight;
                        result->end_value += trace.end_value * weight;

                    }

                    result->is_zero = 0;
                }
            }
        }
    }
    #if defined(_OPENMP)
        }
    #endif
    Py_END_ALLOW_THREADS

    return SUCCESS;
}

static store_error_t store_calc_static(
        const store_t *store,
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *delays,
        const float64_t *receiver_coords,
        const size_t nsources,
        const size_t nreceivers,
        const component_scheme_t *cscheme,
        const mapping_scheme_t *mscheme,
        const mapping_t *mapping,
        interpolation_scheme_id interpolation,
        int32_t it,
        int32_t nthreads,
        gf_dtype **result) {

    float32_t weight;
    float64_t delay;
    trace_t trace;
    float64_t deltat = store->deltat;
    int idelay_floor, idelay_ceil;
    int idx;
    uint64_t irecord;
    float w1, w2;
    store_error_t err = SUCCESS;

    (void) nthreads;

    size_t ireceiver, isource, iip, nip, icomponent, isummand, nsummands_max, nsummands;
    float64_t ws_this[NCOMPONENTS_MAX*NSUMMANDS_MAX];
    uint64_t irecord_bases[VICINITY_NIP_MAX];
    float64_t weights_ip[VICINITY_NIP_MAX];
    float64_t weights_sum;

    if (!inlimits(it))
        return BAD_REQUEST;

    if (result == NULL)
        return ALLOC_FAILED;

    nsummands_max = cscheme->nsummands_max;
    nip = mscheme->vicinity_nip;

    if (0 == nsummands_max || 0 == nreceivers)
        return SUCCESS;

    Py_BEGIN_ALLOW_THREADS
    #if defined(_OPENMP)
        if (nthreads == 0)
            nthreads = omp_get_num_procs();
        else if (nthreads > omp_get_num_procs()) {
            nthreads = omp_get_num_procs();
            printf("store_calc_static - Warning: Desired nthreads exceeds number of physical processors, falling to %d threads\n", nthreads);
        }

        #pragma omp parallel \
            shared (store, source_coords, ms, delays, receiver_coords, \
                    cscheme, mscheme, mapping, interpolation, it, nip, result) \
            private (isource, iip, icomponent, isummand, nsummands, irecord_bases, weights_ip, ws_this, \
                     delay, weight, idelay_floor, idelay_ceil, idx, irecord, trace, w1, w2, weights_sum) \
            reduction (+: err) \
            num_threads (nthreads)
        {
        #pragma omp for schedule (guided)
    #endif

    for (ireceiver=0; ireceiver<nreceivers; ireceiver++) {
        for (isource=0; isource<nsources; isource++) {

            cscheme->make_weights(
                &source_coords[isource*5],
                &ms[isource*cscheme->nsource_terms],
                &receiver_coords[ireceiver*5],
                ws_this);

            weights_sum = 0.;
            for (iip=0; iip<cscheme->ncomponents*cscheme->nsummands_max; iip++)
                weights_sum += ws_this[iip];

            if (weights_sum == 0.)
                continue;

            delay = delays[isource];
            idelay_floor = (int) floor(delay/deltat);
            idelay_ceil = (int) ceil(delay/deltat);
            if (!inlimits(idelay_floor) || !inlimits(idelay_ceil))
                err |= BAD_REQUEST;

            if (interpolation == MULTILINEAR) {
                err |= mscheme->vicinity(
                    mapping,
                    &source_coords[isource*5],
                    &receiver_coords[ireceiver*5],
                    irecord_bases,
                    weights_ip);

                for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                    nsummands = cscheme->nsummands[icomponent];
                    for (iip=0; iip<nip; iip++) {
                        for (isummand=0; isummand<nsummands; isummand++) {
                            weight = weights_ip[iip] * ws_this[icomponent*nsummands_max + isummand];
                            if (weight == 0.)
                                continue;

                            irecord = irecord_bases[iip] + cscheme->igs[icomponent][isummand];
                            err |= store_get(store, irecord, &trace);
                            if (trace.is_zero)
                                continue;

                            idx = it - idelay_floor - trace.itmin;
                            if (idelay_floor == idelay_ceil) {
                                result[icomponent][ireceiver] += fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * weight;
                            } else {
                                w1 = (idelay_ceil - delay/deltat);
                                w2 = (1.0-w1);
                                result[icomponent][ireceiver] += (
                                    fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * w1
                                    + fe32toh(trace.data[max(0, min(idx-1, trace.nsamples-1))]) * w2) * weight;
                            }
                        }
                    }
                }
            } else if (interpolation == NEAREST_NEIGHBOR) {
                err |= mscheme->irecord(
                    mapping,
                    &source_coords[isource*5],
                    &receiver_coords[ireceiver*5],
                    irecord_bases);

                for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                    nsummands = cscheme->nsummands[icomponent];
                    for (isummand=0; isummand<nsummands; isummand++) {
                        weight = ws_this[icomponent*nsummands_max + isummand];
                        if (weight == 0.)
                            continue;

                        irecord = irecord_bases[0] + cscheme->igs[icomponent][isummand];
                        err |= store_get(store, irecord, &trace);
                        if (trace.is_zero)
                            continue;

                        idx = it - idelay_floor - trace.itmin;
                        if (idelay_floor == idelay_ceil) {
                            result[icomponent][ireceiver] += fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * weight;
                        } else {
                            w1 = (idelay_ceil - delay/deltat);
                            w2 = (1.0-w1);
                            result[icomponent][ireceiver] += (
                                fe32toh(trace.data[max(0, min(idx, trace.nsamples-1))]) * w1
                                + fe32toh(trace.data[max(0, min(idx-1, trace.nsamples-1))]) * w2) * weight;
                        }
                    }
                }
            }
        }
    }
    #if defined(_OPENMP)
        }
    #endif
    Py_END_ALLOW_THREADS

    if (err != SUCCESS)
        return err;
    return SUCCESS;
}

static store_error_t store_init(int f_index, int f_data, store_t *store, float64_t patch_deltat) {
    void *p;
    struct stat st;
    size_t index_size;
#ifdef _WIN32
    ssize_t nread, index_pos;
#endif
    int use_mmap;
    float32_t fdeltat;

    use_mmap = 0;

    *store = ZERO_STORE;

    store->f_index = f_index;
    store->f_data = f_data;
    store->mapping = NULL;
    store->mapping_scheme = NULL;

    if (8 != pread(store->f_index, &store->nrecords, 8, 0)) {
        return READ_INDEX_FAILED;
    }

    if (4 != pread(store->f_index, &fdeltat, 4, 8)) {
        return READ_INDEX_FAILED;
    }
    store->deltat = fdeltat;

    store->nrecords = xe64toh(store->nrecords);
    store->deltat = (float64_t)fe32toh(store->deltat);

    if (patch_deltat != 0.0) {
        store->deltat = patch_deltat;
    }

    if (-1 == fstat(store->f_data, &st)) {
        return FSTAT_TRACES_FAILED;
    }

    if (st.st_size < 0) {
        return FSTAT_TRACES_FAILED;
    }

    store->data_size = (uint64_t)st.st_size;
    if (store->nrecords >= (UINT64_MAX - GF_STORE_HEADER_SIZE) / sizeof(record_t)) {
        return BAD_STORE;
    }

    index_size = sizeof(record_t) * store->nrecords + GF_STORE_HEADER_SIZE;
    if (index_size >= SIZE_MAX) {
        return MMAP_INDEX_FAILED;
    }


#ifndef _WIN32
    p = mmap(NULL, index_size, PROT_READ, MAP_SHARED, store->f_index, 0);
    if (MAP_FAILED == p) {
        return MMAP_INDEX_FAILED;
    }
#else
    p = malloc(index_size);
    if (p == NULL) {
        return ALLOC_FAILED;
    }

    index_pos = 0;
    while (index_pos < index_size) {
        nread = pread(store->f_index, p, index_size-index_pos, index_pos);
        if (-1 == nread) {
            return READ_INDEX_FAILED;
        }
        index_pos += nread;
    }
#endif

    store->records = (record_t*)((char*)p+GF_STORE_HEADER_SIZE);

    /* on 32-bit systems, use mmap only if traces file is considerably smaller
     * than address space */

#ifndef _WIN32
    use_mmap = store->data_size < SIZE_MAX / 8;
#else
    use_mmap = 0;
#endif

    if (use_mmap) {
#ifndef _WIN32
        if (store->data_size >= SIZE_MAX) {
            return MMAP_TRACES_FAILED;
        }
        p = mmap(NULL, store->data_size, PROT_READ, MAP_SHARED, store->f_data, 0);
        if (MAP_FAILED == p) {
            return MMAP_TRACES_FAILED;
        }

        store->data = (gf_dtype*)p;
#endif
    } else {
        if (store->nrecords > SIZE_MAX) {
            return ALLOC_FAILED;
        }
        store->memdata = (gf_dtype**)calloc(store->nrecords, sizeof(gf_dtype*));
        if (NULL == store->memdata) {
            return ALLOC_FAILED;
        }
    }

    return SUCCESS;
}

static store_error_t store_mapping_init(
        const store_t *store,
        const mapping_scheme_t *mscheme,
        const float64_t *mins,
        const float64_t *maxs,
        const float64_t *deltas,
        const uint64_t *ns,
        uint64_t ng,
        mapping_t *mapping) {

    size_t i;
    uint64_t nrecords_check;

    nrecords_check = 1;
    for (i=0; i<mscheme->ndims_continuous; i++) {
        mapping->mins[i] = mins[i];
        mapping->maxs[i] = maxs[i];
        mapping->deltas[i] = deltas[i];
        mapping->ns[i] = ns[i];
        nrecords_check *= ns[i];
    }

    mapping->ng = ng;
    nrecords_check *= ng;

    if (nrecords_check != store->nrecords) {
        return BAD_REQUEST;
    }

    return SUCCESS;
}

static void store_mapping_deinit(mapping_t *mapping) {
    (void)mapping;
}

void store_deinit(store_t *store) {
    size_t index_size;
    uint64_t irecord;

    index_size = sizeof(record_t) * store->nrecords + GF_STORE_HEADER_SIZE;
    if (store->records != NULL) {
#ifndef _WIN32
        munmap(((char*)store->records)-GF_STORE_HEADER_SIZE, index_size);
#else
        free(((char*)store->records)-GF_STORE_HEADER_SIZE);
#endif
    }

    if (store->data != NULL) {
#ifndef _WIN32
        munmap(store->data, store->data_size);
#endif
    }

    if (store->memdata != NULL) {
        for (irecord=0; irecord<store->nrecords; irecord++) {
            if (NULL != store->memdata[irecord]) {
                free(store->memdata[irecord]);
                store->memdata[irecord] = NULL;
            }
        }
        free(store->memdata);
    }

    if (store->mapping != NULL) {
        free(store->mapping);
    }

    if (store->mapping_scheme != NULL) {
    }

    *store = ZERO_STORE;
}

#ifdef HAVE_CAPSULE
static void w_store_delete(PyObject *capsule) {
    store_t *store;
    store = (store_t*)PyCapsule_GetPointer(capsule, NULL);
    store_deinit(store);
    free(store);
}
#else
static void w_store_delete(void *store) {
    store_deinit((store_t*)store);
    free(store);
}
#endif

static PyObject* w_store_init(PyObject *m, PyObject *args) {
    int f_index, f_data;
    store_t *store;
    store_error_t err;
    float64_t patch_deltat;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "iid", &f_index, &f_data, &patch_deltat)) {
        PyErr_SetString(st->error, "usage store_init(f_index, f_data, patch_deltat)" );
        return NULL;
    }

    store = (store_t*) calloc(1, sizeof(store_t));
    if (store == NULL) {
        PyErr_SetString(st->error, "memory allocation failed.");
        return NULL;
    }

    err = store_init(f_index, f_data, store, patch_deltat);
    if (SUCCESS != err) {
        PyErr_SetString(st->error, store_error_names[err]);
        store_deinit(store);
        free(store);
        return NULL;
    }

#ifdef HAVE_CAPSULE
    return Py_BuildValue("N",
        PyCapsule_New((void*)store, NULL, w_store_delete));
#else
    return Py_BuildValue("N",
        PyCObject_FromVoidPtr((void*)store, w_store_delete));
#endif
}

static store_t* get_store_from_capsule(PyObject *capsule) {
    store_t *store;

#ifdef HAVE_CAPSULE
    if (!PyCapsule_IsValid(capsule, NULL)) {
#else
    if (!PyCObject_Check(capsule)) {
#endif
        PyErr_SetString(PyExc_ValueError, "store_init: invalid cstore argument");
        return NULL;
    }

#ifdef HAVE_CAPSULE
    store = (store_t*)PyCapsule_GetPointer(capsule, NULL);
#else
    store = (store_t*)PyCObject_AsVoidPtr(capsule);
#endif

    return store;
}


static PyObject* w_store_mapping_init(PyObject *m, PyObject *args) {
    PyObject *capsule;
    char *mapping_scheme_name;
    PyObject *mins_arr, *maxs_arr, *deltas_arr, *ns_arr;
    float64_t *mins, *maxs, *deltas;
    uint64_t *ns, ng;
    store_t *store;
    store_error_t err;
    mapping_t *mapping;
    const mapping_scheme_t *mscheme;
    npy_intp n;
    int ng_;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "OsOOOOi", &capsule, &mapping_scheme_name,
                          &mins_arr, &maxs_arr, &deltas_arr, &ns_arr,
                          &ng_)) {
        PyErr_SetString(
            st->error,
            "usage store_mapping_init(cstore, mapping_name, mins, maxs, deltas, ns, ng)");
        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL)
        return NULL;

    mscheme = get_mapping_scheme(mapping_scheme_name);
    if (mscheme == NULL) {
        PyErr_Format(st->error, "store_mapping_init: invalid mapping scheme name %s", mapping_scheme_name);
        return NULL;
    }
    n = mscheme->ndims_continuous;

    if (!good_array(mins_arr, NPY_FLOAT64, n, 1, NULL)) return NULL;
    if (!good_array(maxs_arr, NPY_FLOAT64, n, 1, NULL)) return NULL;
    if (!good_array(deltas_arr, NPY_FLOAT64, n, 1, NULL)) return NULL;
    if (!good_array(ns_arr, NPY_UINT64, n, 1, NULL)) return NULL;

    if (!inposlimits(ng_)) {
        PyErr_SetString(st->error, "store_mapping_init: invalid ng argument");
        return NULL;
    }
    ng = ng_;

    mapping = (mapping_t*)calloc(1, sizeof(mapping_t));
    if (store == NULL) {
        PyErr_SetString(st->error, "memory allocation failed.");
        return NULL;
    }

    mins = PyArray_DATA((PyArrayObject*)mins_arr);
    maxs = PyArray_DATA((PyArrayObject*)maxs_arr);
    deltas = PyArray_DATA((PyArrayObject*)deltas_arr);
    ns = PyArray_DATA((PyArrayObject*)ns_arr);

    err = store_mapping_init(store, mscheme, mins, maxs, deltas, ns, ng, mapping);
    if (SUCCESS != err) {
        PyErr_SetString(st->error, store_error_names[err]);
        store_mapping_deinit(mapping);
        free(mapping);
        return NULL;
    }
    if (store->mapping != NULL) {
        store_mapping_deinit(store->mapping);
        free(store->mapping);
    }
    store->mapping = mapping;
    store->mapping_scheme = mscheme;

    Py_INCREF(Py_None);
    return Py_None;
}


static PyObject* w_store_get(PyObject *m, PyObject *args) {
    PyObject *capsule;
    store_t *store;
    gf_dtype *adata;
    trace_t trace;
    PyArrayObject *array = NULL;
    npy_intp array_dims[1] = {0};
    unsigned long long int irecord_;
    int itmin_, nsamples_;
    uint64_t irecord;
    int32_t itmin, nsamples;
    int i;
    store_error_t err;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "OKii", &capsule, &irecord_, &itmin_, &nsamples_)) {
        PyErr_SetString(st->error, "usage: store_get(cstore, irecord, itmin, nsamples)");
        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL)
        return NULL;

    irecord = irecord_;

    if (!inlimits(itmin_)) {
        PyErr_SetString(st->error, "invalid itmin argument");
        return NULL;
    }
    itmin = itmin_;

    if (!(inposlimits(nsamples_) || -1 == nsamples_)) {
        PyErr_SetString(st->error, "invalid nsamples argument");
        return NULL;
    }
    nsamples = nsamples_;

    err = store_get(store, irecord, &trace);
    if (SUCCESS != err) {
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }

    if (-1 != nsamples) {
        trace_trim(&trace, itmin, nsamples);
    }

    array_dims[0] = trace.nsamples;
    array = (PyArrayObject*)PyArray_EMPTY(1, array_dims, NPY_FLOAT32, 0);
    adata = (gf_dtype*)PyArray_DATA(array);
    for (i=0; i<trace.nsamples; i++) {
        adata[i] = fe32toh(trace.data[i]);
    }

    return Py_BuildValue("Nidiff", array, trace.itmin, store->deltat,
                         trace.is_zero, trace.begin_value, trace.end_value);
}

static float64_t clip(float64_t x, float64_t mi, float64_t ma) {
    return x < mi ? mi : (x > ma ? ma : x);
}

static float64_t wrap(float64_t x, float64_t mi, float64_t ma) {
    return x - floor((x-mi)/(ma-mi)) * (ma-mi);
}


static float64_t cosdelta(float64_t alat, float64_t alon, float64_t blat, float64_t blon) {
    return min(1., sin(alat*D2R) * sin(blat*D2R) +
            cos(alat*D2R) * cos(blat*D2R) * cos(D2R* (blon - alon)));
}

static void azibazi(float64_t alat, float64_t alon, float64_t blat, float64_t blon, float64_t *azi, float64_t *bazi) {
    float64_t cd;
    cd = cosdelta(alat, alon, blat, blon);
    *azi = R2D * atan2(
        cos(D2R * alat) * cos(D2R * blat) * sin(D2R * (blon-alon)),
        sin(D2R * blat) - sin(D2R * alat) * cd);
    *bazi = R2D * atan2(
        cos(D2R * blat) * cos(D2R * alat) * sin(D2R * (alon-blon)),
        sin(D2R * alat) - sin(D2R * blat) * cd);
}

static void ne_to_latlon(float64_t lat, float64_t lon, float64_t north, float64_t east, float64_t *lat_new, float64_t *lon_new) {
    float64_t a, b, c, gamma, alphasign, alpha;

    if (north == 0.0 && east == 0.0) {
        *lat_new = lat;
        *lon_new = lon;
        return;
    }

    a = sqrt(SQR(north) + SQR(east)) / EARTHRADIUS;
    gamma = atan2(east, north);

    b = 0.5*M_PI - lat*D2R;

    alphasign = gamma < 0.0 ? -1.0 : 1.0;
    gamma = fabs(gamma);

    c = acos(clip(cos(a)*cos(b)+sin(a)*sin(b)*cos(gamma), -1., 1.));

    alpha = asin(clip(sin(a)*sin(gamma)/sin(c), -1., 1.));
    alpha = cos(a) - cos(b)*cos(c) < 0.0 ? (alpha > 0.0 ? M_PI-alpha : -M_PI-alpha) : alpha;


    *lat_new = R2D * (0.5*M_PI - c);
    *lon_new = wrap(lon + R2D*alpha*alphasign, -180., 180.);
}

static void azibazi4(const float64_t *a, const float64_t *b, float64_t *azi, float64_t *bazi) {
    /* azimuth and backazimuth for (lat,lon,north,east) coordinates */

    float64_t alat, alon, anorth, aeast;
    float64_t blat, blon, bnorth, beast;
    float64_t alat_eff, alon_eff;
    float64_t blat_eff, blon_eff;

    alat = a[0];
    alon = a[1];
    anorth = a[2];
    aeast = a[3];
    blat = b[0];
    blon = b[1];
    bnorth = b[2];
    beast = b[3];

    if (alat == blat && alon == blon) { /* carthesian */
        *azi = atan2(beast - aeast, bnorth - anorth) * R2D;
        *bazi = *azi + 180.0;
    } else { /* spherical */
        ne_to_latlon(alat, alon, anorth, aeast, &alat_eff, &alon_eff);
        ne_to_latlon(blat, blon, bnorth, beast, &blat_eff, &blon_eff);
        azibazi(alat_eff, alon_eff, blat_eff, blon_eff, azi, bazi);
    }
}


static void distance_accurate50m(float64_t alat, float64_t alon, float64_t blat, float64_t blon, float64_t *dist) {
    /* more accurate distance calculation based on a spheroid of rotation

    returns distance in [m] between points a and b
    coordinates must be given in degrees

    should be accurate to 50 m using WGS84

    from wikipedia :  http://de.wikipedia.org/wiki/Orthodrome
    based on: Meeus, J.: Astronomical Algorithms, S 85, Willmann-Bell,
              Richmond 2000 (2nd ed., 2nd printing), ISBN 0-943396-61-1 */
    float64_t f, g, l, s, c, w, r;
    // float64_t d, h1, h2;
    // check_latlon_ranges(alat, alon, blat, blon);
    f = (alat + blat) * D2R / 2.;
    g = (alat - blat) * D2R / 2.;
    l = (alon - blon) * D2R / 2.;

    s = SQR(sin(g)) * SQR(cos(l)) + SQR(cos(f)) * SQR(sin(l));
    c = SQR(cos(g)) * SQR(cos(l)) + SQR(sin(f)) * SQR(sin(l));

    w = atan(sqrt(s/c));

    if (w == 0.) {
        *dist = 0.;
        return;
    }

    r = sqrt(s*c)/w;
    // d = 2. * w * EARTHRADIUS_EQ;
    // h1 = (3.*r-1.) / (2.*c);
    // h2 = (3.*r-1.) / (2.*s);

    *dist = 2. * w * EARTHRADIUS_EQ *
        (1. +
         EARTH_OBLATENESS * ((3.*r-1.) / (2.*c)) * SQR(sin(f)) * SQR(cos(g)) -
         EARTH_OBLATENESS * ((3.*r+1.) / (2.*s)) * SQR(cos(f)) * SQR(sin(g)));
}


static void distance4(const float64_t *a, const float64_t *b, float64_t *distance) {
    /* Distance (lat,lon,north,east) coordinates */

    float64_t alat, alon, anorth, aeast;
    float64_t blat, blon, bnorth, beast;
    float64_t alat_eff, alon_eff;
    float64_t blat_eff, blon_eff;

    alat = a[0];
    alon = a[1];
    anorth = a[2];
    aeast = a[3];
    blat = b[0];
    blon = b[1];
    bnorth = b[2];
    beast = b[3];

    if (alat == blat && alon == blon) { /* cartesian */
        *distance = sqrt(SQR(bnorth - anorth) + SQR(beast - aeast));
    } else { /* spherical */
        ne_to_latlon(alat, alon, anorth, aeast, &alat_eff, &alon_eff);
        ne_to_latlon(blat, blon, bnorth, beast, &blat_eff, &blon_eff);
        distance_accurate50m(alat_eff, alon_eff, blat_eff, blon_eff, distance);
    }
}


static void make_weights_dummy(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    (void)source_coords;
    (void)receiver_coords;

    ws[0] = ms[0];
}


static void make_weights_elastic2(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    float64_t azi, bazi;
    float64_t sb, cb;
    size_t ioff;
    size_t nsummands_max = component_schemes[ELASTIC2].nsummands_max;

    azibazi4(source_coords, receiver_coords, &azi, &bazi);
    sb = sin(bazi*D2R-M_PI);
    cb = cos(bazi*D2R-M_PI);

    ioff = 0 * nsummands_max;
    ws[ioff + 0] = cb * ms[0];

    ioff = 1 * nsummands_max;
    ws[ioff + 0] = sb * ms[0];

    ioff = 2 * nsummands_max;
    ws[ioff + 0] = ms[0];
}


static void make_weights_elastic5(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    float64_t azi, bazi, f0, f1, f2;
    float64_t sa, ca, sb, cb;
    size_t ioff;
    size_t nsummands_max = component_schemes[ELASTIC5].nsummands_max;

    azibazi4(source_coords, receiver_coords, &azi, &bazi);
    sa = sin(azi*D2R);
    ca = cos(azi*D2R);
    sb = sin(bazi*D2R-M_PI);
    cb = cos(bazi*D2R-M_PI);

    f0 = ms[2];
    f1 = ms[0]*ca + ms[1]*sa;
    f2 = ms[1]*ca - ms[0]*sa;

    ioff = 0 * nsummands_max;
    ws[ioff + 0] = cb * f0;
    ws[ioff + 1] = cb * f1;
    ws[ioff + 2] = -sb * f2;

    ioff = 1 * nsummands_max;
    ws[ioff + 0] = sb * f0;
    ws[ioff + 1] = sb * f1;
    ws[ioff + 2] = cb * f2;

    ioff = 2 * nsummands_max;
    ws[ioff + 0] = f0;
    ws[ioff + 1] = f1;
}


static void make_weights_elastic8(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    float64_t azi, bazi, f0, f1, f2, f3, f4;
    float64_t sa, ca, s2a, c2a, sb, cb;
    size_t ioff;
    size_t nsummands_max = component_schemes[ELASTIC8].nsummands_max;

    azibazi4(source_coords, receiver_coords, &azi, &bazi);
    sa = sin(azi*D2R);
    ca = cos(azi*D2R);
    s2a = sin(2.0*azi*D2R);
    c2a = cos(2.0*azi*D2R);
    sb = sin(bazi*D2R-M_PI);
    cb = cos(bazi*D2R-M_PI);

    f0 = ms[0]*SQR(ca) + ms[1]*SQR(sa) + ms[3]*s2a;
    f1 = ms[4]*ca + ms[5]*sa;
    f2 = ms[2];
    f3 = 0.5*(ms[1]-ms[0])*s2a + ms[3]*c2a;
    f4 = ms[5]*ca - ms[4]*sa;

    ioff = 0 * nsummands_max;
    ws[ioff + 0] = cb * f0;
    ws[ioff + 1] = cb * f1;
    ws[ioff + 2] = cb * f2;
    ws[ioff + 3] = -sb * f3;
    ws[ioff + 4] = -sb * f4;

    ioff = 1 * nsummands_max;
    ws[ioff + 0] = sb * f0;
    ws[ioff + 1] = sb * f1;
    ws[ioff + 2] = sb * f2;
    ws[ioff + 3] = cb * f3;
    ws[ioff + 4] = cb * f4;

    ioff = 2 * nsummands_max;
    ws[ioff + 0] = f0;
    ws[ioff + 1] = f1;
    ws[ioff + 2] = f2;
}

static void make_weights_elastic10(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    float64_t azi, bazi, f0, f1, f2, f3, f4, f5;
    float64_t sa, ca, s2a, c2a, sb, cb;
    size_t ioff;
    size_t nsummands_max = component_schemes[ELASTIC10].nsummands_max;

    azibazi4(source_coords, receiver_coords, &azi, &bazi);
    sa = sin(azi*D2R);
    ca = cos(azi*D2R);
    s2a = sin(2.0*azi*D2R);
    c2a = cos(2.0*azi*D2R);
    sb = sin(bazi*D2R-M_PI);
    cb = cos(bazi*D2R-M_PI);

    f0 = ms[0]*SQR(ca) + ms[1]*SQR(sa) + ms[3]*s2a;
    f1 = ms[4]*ca + ms[5]*sa;
    f2 = ms[2];
    f3 = 0.5*(ms[1]-ms[0])*s2a + ms[3]*c2a;
    f4 = ms[5]*ca - ms[4]*sa;
    f5 = ms[0]*SQR(sa) + ms[1]*SQR(ca) - ms[3]*s2a;

    ioff = 0 * nsummands_max;
    ws[ioff + 0] = cb * f0;
    ws[ioff + 1] = cb * f1;
    ws[ioff + 2] = cb * f2;
    ws[ioff + 3] = cb * f5;
    ws[ioff + 4] = -sb * f3;
    ws[ioff + 5] = -sb * f4;

    ioff = 1 * nsummands_max;
    ws[ioff + 0] = sb * f0;
    ws[ioff + 1] = sb * f1;
    ws[ioff + 2] = sb * f2;
    ws[ioff + 3] = sb * f5;
    ws[ioff + 4] = cb * f3;
    ws[ioff + 5] = cb * f4;

    ioff = 2 * nsummands_max;
    ws[ioff + 0] = f0;
    ws[ioff + 1] = f1;
    ws[ioff + 2] = f2;
    ws[ioff + 3] = f5;
}

static void make_weights_elastic18(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        float64_t *ws) {

    size_t ioff;
    size_t nsummands_max = component_schemes[ELASTIC18].nsummands_max;

    (void) source_coords;
    (void) receiver_coords;

    ioff = 0 * nsummands_max;
    ws[ioff + 0] = ms[0];
    ws[ioff + 1] = ms[1];
    ws[ioff + 2] = ms[2];
    ws[ioff + 3] = ms[3];
    ws[ioff + 4] = ms[4];
    ws[ioff + 5] = ms[5];

    ioff = 1 * nsummands_max;
    ws[ioff + 0] = ms[0];
    ws[ioff + 1] = ms[1];
    ws[ioff + 2] = ms[2];
    ws[ioff + 3] = ms[3];
    ws[ioff + 4] = ms[4];
    ws[ioff + 5] = ms[5];

    ioff = 2 * nsummands_max;
    ws[ioff + 0] = ms[0];
    ws[ioff + 1] = ms[1];
    ws[ioff + 2] = ms[2];
    ws[ioff + 3] = ms[3];
    ws[ioff + 4] = ms[4];
    ws[ioff + 5] = ms[5];
}

static store_error_t irecord_function_type_0(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecord) {

    float64_t v[2];
    uint64_t i;
    float64_t d3d;

    v[0] = source_coords[4] - receiver_coords[4];
    distance4(source_coords, receiver_coords, &v[1]);
    d3d = sqrt(SQR(v[0]) + SQR(v[1]));

    i = (uint64_t)(round((d3d - mapping->mins[0]) / mapping->deltas[0]));
    if (i >= mapping->ns[0]) {
        return INDEX_OUT_OF_BOUNDS;
    }
    *irecord = i*mapping->ng;
    return SUCCESS;
}

static store_error_t vicinity_function_type_0(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecords,
        float64_t *weights) {

    float64_t v[2], w_fl, w_ce;
    float64_t d3d;
    float64_t x, x_fl, x_ce;
    uint64_t i_fl, i_ce;
    uint64_t ns;

    v[0] = source_coords[4] - receiver_coords[4];
    distance4(source_coords, receiver_coords, &v[1]);
    d3d = sqrt(SQR(v[0]) + SQR(v[1]));

    ns = mapping->ns[0];

    x = (d3d - mapping->mins[0]) / mapping->deltas[0];
    x_fl = floor(x);
    x_ce = ceil(x);

    w_fl = 1.0 - (x - x_fl);
    w_ce = (1.0 - (x_ce - x)) * (x_ce - x_fl);

    i_fl = (uint64_t)x_fl;
    i_ce = (uint64_t)x_ce;

    if (i_fl >= ns || i_ce >= ns) {
        return INDEX_OUT_OF_BOUNDS;
    }

    irecords[0] = mapping->ng * i_fl;
    irecords[1] = mapping->ng * i_ce;
    irecords[2] = mapping->ng * i_fl;
    irecords[3] = mapping->ng * i_ce;

    weights[0] = w_fl;
    weights[1] = w_ce;
    return SUCCESS;
}

static store_error_t irecord_function_type_a(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecord) {

    float64_t v[2];
    uint64_t i[2];
    v[0] = source_coords[4];
    distance4(source_coords, receiver_coords, &v[1]);
    i[0] = (uint64_t)(round((v[0] - mapping->mins[0]) / mapping->deltas[0]));
    i[1] = (uint64_t)(round((v[1] - mapping->mins[1]) / mapping->deltas[1]));
    if (i[0] >= mapping->ns[0] || i[1] >= mapping->ns[1]) {
        return INDEX_OUT_OF_BOUNDS;
    }
    *irecord = (i[0]*mapping->ns[1] + i[1])*mapping->ng;
    return SUCCESS;
}

static store_error_t vicinity_function_type_a(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecords,
        float64_t *weights) {

    float64_t v[2], w_fl[2], w_ce[2];
    float64_t x, x_fl, x_ce;
    uint64_t i_fl[2], i_ce[2];
    const uint64_t *ns;
    size_t k;

    v[0] = source_coords[4];
    distance4(source_coords, receiver_coords, &v[1]);

    ns = mapping->ns;

    for (k=0; k<2; k++) {
        x = (v[k] - mapping->mins[k]) / mapping->deltas[k];
        x_fl = floor(x);
        x_ce = ceil(x);

        w_fl[k] = 1.0 - (x - x_fl);
        w_ce[k] = (1.0 - (x_ce - x)) * (x_ce - x_fl);

        i_fl[k] = (uint64_t)x_fl;
        i_ce[k] = (uint64_t)x_ce;

        if (i_fl[k] >= ns[k] || i_ce[k] >= ns[k]) {
            return INDEX_OUT_OF_BOUNDS;
        }
    }

    irecords[0] = mapping->ng * (i_fl[0]*ns[1] + i_fl[1]);
    irecords[1] = mapping->ng * (i_ce[0]*ns[1] + i_fl[1]);
    irecords[2] = mapping->ng * (i_fl[0]*ns[1] + i_ce[1]);
    irecords[3] = mapping->ng * (i_ce[0]*ns[1] + i_ce[1]);

    weights[0] = w_fl[0] * w_fl[1];
    weights[1] = w_ce[0] * w_fl[1];
    weights[2] = w_fl[0] * w_ce[1];
    weights[3] = w_ce[0] * w_ce[1];
    return SUCCESS;
}

static store_error_t irecord_function_type_b(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecord) {

    float64_t v[3];
    uint64_t i[3];
    v[0] = receiver_coords[4];
    v[1] = source_coords[4];
    distance4(source_coords, receiver_coords, &v[2]);

    i[0] = (uint64_t)(round((v[0] - mapping->mins[0]) / mapping->deltas[0]));
    i[1] = (uint64_t)(round((v[1] - mapping->mins[1]) / mapping->deltas[1]));
    i[2] = (uint64_t)(round((v[2] - mapping->mins[2]) / mapping->deltas[2]));
    if (i[0] >= mapping->ns[0] || i[1] >= mapping->ns[1] || i[2] >= mapping->ns[2]) {
        return INDEX_OUT_OF_BOUNDS;
    }
    *irecord = (i[0]*mapping->ns[1]*mapping->ns[2] + i[1]*mapping->ns[2] + i[2]) * mapping->ng;
    return SUCCESS;
}

static store_error_t vicinity_function_type_b(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecords,
        float64_t *weights) {

    float64_t v[3], w_fl[3], w_ce[3];
    float64_t x, x_fl, x_ce;
    uint64_t i_fl[3], i_ce[3];
    const uint64_t *ns;
    size_t k;

    v[0] = receiver_coords[4];
    v[1] = source_coords[4];
    distance4(source_coords, receiver_coords, &v[2]);

    ns = mapping->ns;

    for (k=0; k<3; k++) {
        x = (v[k] - mapping->mins[k]) / mapping->deltas[k];
        x_fl = floor(x);
        x_ce = ceil(x);

        w_fl[k] = 1.0 - (x - x_fl);
        w_ce[k] = (1.0 - (x_ce - x)) * (x_ce - x_fl);

        i_fl[k] = (uint64_t)x_fl;
        i_ce[k] = (uint64_t)x_ce;

        if (i_fl[k] >= ns[k] || i_ce[k] >= ns[k]) {
            return INDEX_OUT_OF_BOUNDS;
        }
    }

    /* irecords[0::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig */
    irecords[0] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_fl[2]);
    irecords[1] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_fl[2]);
    irecords[2] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_fl[2]);
    irecords[3] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_fl[2]);
    irecords[4] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_ce[2]);
    irecords[5] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_ce[2]);
    irecords[6] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_ce[2]);
    irecords[7] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_ce[2]);

    weights[0] = w_fl[0] * w_fl[1] * w_fl[2];
    weights[1] = w_ce[0] * w_fl[1] * w_fl[2];
    weights[2] = w_fl[0] * w_ce[1] * w_fl[2];
    weights[3] = w_ce[0] * w_ce[1] * w_fl[2];
    weights[4] = w_fl[0] * w_fl[1] * w_ce[2];
    weights[5] = w_ce[0] * w_fl[1] * w_ce[2];
    weights[6] = w_fl[0] * w_ce[1] * w_ce[2];
    weights[7] = w_ce[0] * w_ce[1] * w_ce[2];
    return SUCCESS;
}

static store_error_t irecord_function_type_c(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecord) {

    float64_t v[3];
    uint64_t i[3];

    (void)receiver_coords;

    v[0] = source_coords[4];
    v[1] = source_coords[3];
    v[2] = source_coords[2];

    i[0] = (uint64_t)(round((v[0] - mapping->mins[0]) / mapping->deltas[0]));
    i[1] = (uint64_t)(round((v[1] - mapping->mins[1]) / mapping->deltas[1]));
    i[2] = (uint64_t)(round((v[2] - mapping->mins[2]) / mapping->deltas[2]));
    if (i[0] >= mapping->ns[0] || i[1] >= mapping->ns[1] || i[2] >= mapping->ns[2]) {
        return INDEX_OUT_OF_BOUNDS;
    }
    *irecord = (i[0]*mapping->ns[1]*mapping->ns[2] + i[1]*mapping->ns[2] + i[2]) * mapping->ng;
    return SUCCESS;
}

static store_error_t vicinity_function_type_c(
        const mapping_t *mapping,
        const float64_t *source_coords,
        const float64_t *receiver_coords,
        uint64_t *irecords,
        float64_t *weights) {

    float64_t v[3], w_fl[3], w_ce[3];
    float64_t x, x_fl, x_ce;
    uint64_t i_fl[3], i_ce[3];
    const uint64_t *ns;
    size_t k;

    (void)receiver_coords;

    v[0] = source_coords[4];
    v[1] = source_coords[3];
    v[2] = source_coords[2];

    ns = mapping->ns;

    for (k=0; k<3; k++) {
        x = (v[k] - mapping->mins[k]) / mapping->deltas[k];
        x_fl = floor(x);
        x_ce = ceil(x);

        w_fl[k] = 1.0 - (x - x_fl);
        w_ce[k] = (1.0 - (x_ce - x)) * (x_ce - x_fl);

        i_fl[k] = (uint64_t)x_fl;
        i_ce[k] = (uint64_t)x_ce;

        if (i_fl[k] >= ns[k] || i_ce[k] >= ns[k]) {
            return INDEX_OUT_OF_BOUNDS;
        }
    }

    /* irecords[0::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig */
    irecords[0] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_fl[2]);
    irecords[1] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_fl[2]);
    irecords[2] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_fl[2]);
    irecords[3] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_fl[2]);
    irecords[4] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_ce[2]);
    irecords[5] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_fl[1]*ns[2] + i_ce[2]);
    irecords[6] = mapping->ng * (i_fl[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_ce[2]);
    irecords[7] = mapping->ng * (i_ce[0]*ns[1]*ns[2] + i_ce[1]*ns[2] + i_ce[2]);

    weights[0] = w_fl[0] * w_fl[1] * w_fl[2];
    weights[1] = w_ce[0] * w_fl[1] * w_fl[2];
    weights[2] = w_fl[0] * w_ce[1] * w_fl[2];
    weights[3] = w_ce[0] * w_ce[1] * w_fl[2];
    weights[4] = w_fl[0] * w_fl[1] * w_ce[2];
    weights[5] = w_ce[0] * w_fl[1] * w_ce[2];
    weights[6] = w_fl[0] * w_ce[1] * w_ce[2];
    weights[7] = w_ce[0] * w_ce[1] * w_ce[2];
    return SUCCESS;
}

static store_error_t make_sum_params(
        const float64_t *source_coords,
        const float64_t *ms,
        const float64_t *receiver_coords,
        size_t nsources,
        size_t nreceivers,
        const component_scheme_t *cscheme,
        const mapping_scheme_t *mscheme,
        const mapping_t *mapping,
        interpolation_scheme_id interpolation,
        int32_t nthreads,
        float32_t **ws,
        uint64_t **irecords) {

    size_t ireceiver, isource, iip, nip, icomponent, isummand, nsummands, nsummands_max, iout;
    float64_t ws_this[NCOMPONENTS_MAX*NSUMMANDS_MAX];
    uint64_t irecord_bases[VICINITY_NIP_MAX];
    float64_t weights_ip[VICINITY_NIP_MAX];
    store_error_t err = SUCCESS;
    (void) nthreads;

    nsummands_max = cscheme->nsummands_max;

    Py_BEGIN_ALLOW_THREADS
    nip = mscheme->vicinity_nip;
    #if defined(_OPENMP)
        if (nthreads == 0)
            nthreads = omp_get_num_procs();
        else if (nthreads > omp_get_num_procs()) {
            nthreads = omp_get_num_procs();
            printf("make_sum_params - Warning: Desired nthreads exceeds number of physical processors, falling to %d threads\n", nthreads);
        }

        #pragma omp parallel \
            shared (source_coords, ms, receiver_coords, nsources, nreceivers, \
                    cscheme, mscheme, mapping, interpolation, ws, irecords, nip) \
            private (ws_this, iout, nsummands, isource, icomponent, isummand, irecord_bases, weights_ip, iip) \
            reduction (+: err) \
            num_threads (nthreads)
        {
            #pragma omp for schedule (dynamic)
    #endif
        for (ireceiver=0; ireceiver<nreceivers; ireceiver++) {
            for (isource=0; isource<nsources; isource++) {
                cscheme->make_weights(
                    &source_coords[isource*5],
                    &ms[isource*cscheme->nsource_terms],
                    &receiver_coords[ireceiver*5],
                    ws_this);

                if (interpolation == MULTILINEAR)  {
                    err += mscheme->vicinity(
                        mapping,
                        &source_coords[isource*5],
                        &receiver_coords[ireceiver*5],
                        irecord_bases,
                        weights_ip);

                    for (iip=0; iip<nip; iip++) {
                        for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                            iout = (ireceiver*nsources + isource)*cscheme->nsummands[icomponent]*nip;
                            nsummands = cscheme->nsummands[icomponent];
                            for (isummand=0; isummand<nsummands; isummand++) {
                                ws[icomponent][iout+iip*nsummands+isummand] = weights_ip[iip] * ws_this[icomponent*nsummands_max + isummand];
                                irecords[icomponent][iout+iip*nsummands+isummand] = irecord_bases[iip] + cscheme->igs[icomponent][isummand];
                                /*printf("%d\n", iout+iip*nsummands+isummand);*/
                            }
                        }
                    }
                } else if (interpolation == NEAREST_NEIGHBOR) {
                    err += mscheme->irecord(
                        mapping,
                        &source_coords[isource*5],
                        &receiver_coords[ireceiver*5],
                        irecord_bases);

                    for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
                        iout = (ireceiver*nsources + isource)*cscheme->nsummands[icomponent];
                        nsummands = cscheme->nsummands[icomponent];
                        for (isummand=0; isummand<nsummands; isummand++) {
                            ws[icomponent][iout+isummand] = ws_this[icomponent*nsummands_max + isummand];
                            irecords[icomponent][iout+isummand] = irecord_bases[0] + cscheme->igs[icomponent][isummand];
                        }
                    }
                }
            }
        }
    #if defined(_OPENMP)
        }
    #endif
    Py_END_ALLOW_THREADS
    if (err != SUCCESS)
        return INDEX_OUT_OF_BOUNDS;
    return SUCCESS;
}

static PyObject* w_store_sum(PyObject *m, PyObject *args) {
    PyObject *capsule, *irecords_arr, *delays_arr, *weights_arr;
    store_t *store;
    trace_t result;
    PyArrayObject *array = NULL;
    npy_intp array_dims[1] = {0};
    uint64_t *irecords;
    float32_t *weights;
    float64_t *delays;
    npy_intp n_;
    int n;
    int itmin_, nsamples_;
    int32_t itmin, nsamples;
    store_error_t err;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "OOOOii", &capsule, &irecords_arr, &delays_arr,
                          &weights_arr, &itmin_, &nsamples_)) {
        PyErr_SetString(st->error,
            "usage: store_sum(cstore, irecords, delays, weights, itmin, nsamples)");

        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL) return NULL;

    if (!good_array(irecords_arr, NPY_UINT64, -1, 1, NULL)) return NULL;
    n_ = PyArray_SIZE((PyArrayObject*)irecords_arr);
    if (!inposlimits(n_)) {
        PyErr_SetString(st->error,
            "store_sum: invalid number of entries in arrays");
        return NULL;
    }

    if (!good_array(delays_arr, NPY_FLOAT64, n_, 1, NULL)) return NULL;
    if (!good_array(weights_arr, NPY_FLOAT32, n_, 1, NULL)) return NULL;

    n = n_;

    if (!inlimits(itmin_)) {
        PyErr_SetString(st->error, "store_sum: invalid itmin argument");
        return NULL;
    }
    itmin = itmin_;

    if (!(inposlimits(nsamples_) || -1 == nsamples_)) {
        PyErr_SetString(st->error, "store_sum: invalid nsamples argument");
        return NULL;
    }
    nsamples = nsamples_;

    irecords = PyArray_DATA((PyArrayObject*)irecords_arr);
    delays = PyArray_DATA((PyArrayObject*)delays_arr);
    weights = PyArray_DATA((PyArrayObject*)weights_arr);

    if (nsamples == -1) {
        err = store_sum_extent(store, irecords, delays, n, &nsamples, &itmin);
        if (SUCCESS != err) {
            PyErr_SetString(st->error, store_error_names[err]);
            return NULL;
        }
    }

    array_dims[0] = nsamples;
    array = (PyArrayObject*)PyArray_ZEROS(1, array_dims, NPY_GFDTYPE, 0);

    result.nsamples = nsamples;
    result.itmin = itmin;
    result.data = (gf_dtype*)PyArray_DATA(array);
    result.begin_value = 0.0;
    result.end_value = 0.0;

    err = store_sum(store, irecords, delays, weights, n, &result);
    if (SUCCESS != err) {
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }

    return Py_BuildValue("Nidiff", array, result.itmin, store->deltat,
                         result.is_zero, result.begin_value, result.end_value);
}

static PyObject* w_store_sum_static(PyObject *m, PyObject *args) {
    PyObject *capsule;
    PyArrayObject *irecords_arr, *delays_arr, *weights_arr, *result_arr;
    store_t *store;
    gf_dtype *result;
    uint64_t *irecords;
    float32_t *weights;
    float64_t *delays;
    npy_intp shape[1];
    int32_t it, ntargets, nthreads;
    size_t nsummands, nsources;
    store_error_t err;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "OOOOiii", &capsule, &irecords_arr, &delays_arr,
                                     &weights_arr, &it, &ntargets, &nthreads)) {
        PyErr_SetString(st->error,
            "usage: store_sum_static(cstore, irecords, delays, weights, it, ntargets, nthreads)");

        return NULL;
    }

    store = get_store_from_capsule(capsule);

    nsummands = PyArray_SIZE((PyArrayObject*)irecords_arr) / ntargets;
    nsources = PyArray_SIZE((PyArrayObject*)delays_arr);

    if (store == NULL) {
        PyErr_SetString(st->error, "store_sum_static: invalid store");
        return NULL;
    }
    if (!good_array((PyObject*)irecords_arr, NPY_UINT64, nsummands * ntargets, 1, NULL)) {
            PyErr_SetString(st->error, "store_sum_static: unhealthy irecords array");
            return NULL;
    }
    if (!good_array((PyObject*)delays_arr, NPY_FLOAT64, -1, 1, NULL) ||
        nsummands % nsources != 0) {
        PyErr_SetString(st->error, "store_sum_static: unhealthy delays array");
        return NULL;
    }
    if (!good_array((PyObject*)weights_arr, NPY_FLOAT32, nsummands * ntargets, 1, NULL)) {
        PyErr_SetString(st->error, "store_sum_static: unhealthy weights array");
        return NULL;
    }
    if (!inlimits(it)) {
        PyErr_SetString(st->error, "store_sum_static: invalid it argument");
        return NULL;
    }

    irecords = PyArray_DATA((PyArrayObject*)irecords_arr);
    delays = PyArray_DATA((PyArrayObject*)delays_arr);
    weights = PyArray_DATA((PyArrayObject*)weights_arr);

    shape[0] = (npy_intp) ntargets;
    result_arr = (PyArrayObject*) PyArray_ZEROS(1, shape, NPY_GFDTYPE, 0);
    result = PyArray_DATA(result_arr);

    err = store_sum_static(store, irecords, delays, weights, it, ntargets, nsummands, nsources, nthreads, result);
    if (SUCCESS != err) {
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }
    return (PyObject*) result_arr;
}


static PyObject* w_make_sum_params(PyObject *m, PyObject *args) {
    PyObject *capsule, *source_coords_arr, *receiver_coords_arr, *ms_arr;
    float64_t *source_coords, *receiver_coords, *ms;
    npy_intp shape_want_coords[2] = {-1, 5};
    npy_intp shape_want_ms[2] = {-1, 6};
    float32_t *weights[NCOMPONENTS_MAX];
    uint64_t *irecords[NCOMPONENTS_MAX];
    int32_t nthreads;
    size_t icomponent, vicinities_nip;
    size_t nsources, nreceivers;
    PyArrayObject *weights_arr, *irecords_arr;
    PyObject *out_list, *out_tuple;
    npy_intp array_dims[1];
    char *component_scheme_name, *interpolation_scheme_name;
    const component_scheme_t *cscheme;
    const mapping_scheme_t *mscheme;
    interpolation_scheme_id interpolation;
    store_error_t err;
    store_t *store;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(
            args, "OOOOssI", &capsule, &source_coords_arr, &ms_arr,
            &receiver_coords_arr, &component_scheme_name,
            &interpolation_scheme_name, &nthreads)) {
        PyErr_SetString(st->error,
            "usage: make_sum_params(cstore, source_coords, moment_tensors, receiver_coords, component_scheme, interpolation_name, nthreads)");
        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL) return NULL;

    mscheme = store->mapping_scheme;
    if (mscheme == NULL) {
        PyErr_SetString(st->error, "w_make_sum_params: no mapping scheme set on store");
        return NULL;
    }

    cscheme = get_component_scheme(component_scheme_name);
    if (cscheme == NULL) {
        PyErr_SetString(st->error, "w_make_sum_params: invalid component scheme name");
        return NULL;
    }

    interpolation = get_interpolation_scheme_id(interpolation_scheme_name);
    if (interpolation == UNDEFINED_INTERPOLATION_SCHEME) {
        PyErr_SetString(st->error, "w_make_sum_params: invalid interpolation scheme name");
        return NULL;
    }

    if (!good_array(source_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        return NULL;
    }

    shape_want_ms[1] = cscheme->nsource_terms;

    if (!good_array(ms_arr, NPY_FLOAT64, -1, 2, shape_want_ms)) {
        return NULL;
    }

    if (!good_array(receiver_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        return NULL;
    }

    source_coords = PyArray_DATA((PyArrayObject*)source_coords_arr);
    nsources = PyArray_DIMS((PyArrayObject*)source_coords_arr)[0];
    ms = PyArray_DATA((PyArrayObject*)ms_arr);
    receiver_coords = PyArray_DATA((PyArrayObject*)receiver_coords_arr);
    nreceivers = PyArray_DIMS((PyArrayObject*)receiver_coords_arr)[0];

    if (interpolation == NEAREST_NEIGHBOR) {
        vicinities_nip = 1;
    } else {
        vicinities_nip = mscheme->vicinity_nip;
    }

    out_list = Py_BuildValue("[]");
    for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
        array_dims[0] = nsources * nreceivers * cscheme->nsummands[icomponent] * vicinities_nip;
        /* printf("nsources: %ld\n", nsources);
        printf("nreceiver: %ld\n", nreceivers);
        printf("nsummands: %ld\n", cscheme->nsummands[icomponent]);
        printf("vicinities_nip: %ld\n", vicinities_nip);
        printf("array_size: %ld bytes\n", array_dims[0]*4 + array_dims[0]*8); */
        weights_arr = (PyArrayObject*)PyArray_SimpleNew(1, array_dims, NPY_FLOAT32);
        irecords_arr = (PyArrayObject*)PyArray_SimpleNew(1, array_dims, NPY_UINT64);

        weights[icomponent] = PyArray_DATA(weights_arr);
        irecords[icomponent] = PyArray_DATA(irecords_arr);

        out_tuple = Py_BuildValue("(N,N)", (PyObject*)weights_arr, (PyObject*)irecords_arr);

        PyList_Append(out_list, out_tuple);
        Py_DECREF(out_tuple);
    }

    err = make_sum_params(
        source_coords,
        ms,
        receiver_coords,
        nsources,
        nreceivers,
        cscheme,
        mscheme,
        store->mapping,
        interpolation,
        nthreads,
        weights,
        irecords);

    if (SUCCESS != err) {
        Py_DECREF(out_list);
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }

    return out_list;
}


static void free_results(result_trace_t *results, size_t nresults) {
    size_t iresult;
    for (iresult=0; iresult<nresults; iresult++) {
        if (results[iresult].buffer != NULL) {
            free(results[iresult].buffer);
        }
    }
    free(results);
}


static PyObject* w_store_calc_timeseries(PyObject *m, PyObject *args) {
    PyObject *capsule, *source_coords_arr, *ms_arr, *delays_arr, *receiver_coords_arr, *itmin_arr, *nsamples_arr, *out_list, *out_tuple;
    PyObject *array = NULL;
    store_t *store;
    npy_intp array_dims[1] = {0};

    char *component_scheme_name, *interpolation_scheme_name;
    const component_scheme_t *cscheme;
    const mapping_scheme_t *mscheme;
    interpolation_scheme_id interpolation;
    gf_dtype *data;

    float64_t *source_coords, *receiver_coords, *ms, *delays;
    int32_t *itmin, *nsamples, nsamples_want, itmin_want;
    int nsources, nreceivers;
    int32_t nthreads;
    store_error_t err;

    npy_intp shape_want_coords[2] = {-1, 5};
    npy_intp shape_want_ms[2] = {-1, 6};

    size_t ires, nresults;
    result_trace_t *results;
    result_trace_t *result;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(
            args, "OOOOOssOOI", &capsule, &source_coords_arr, &ms_arr, &delays_arr,
            &receiver_coords_arr, &component_scheme_name,
            &interpolation_scheme_name, &itmin_arr, &nsamples_arr, &nthreads)) {
        PyErr_SetString(st->error,
            "usage: store_calc_timeseries(cstore, source_coords, moment_tensors, delays, receiver_coords, component_scheme, interpolation_name, itmin_arr, nsamples_arr, nthreads)");
        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: bad store given");
        return NULL;
    }

    mscheme = store->mapping_scheme;
    if (mscheme == NULL) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: no mapping scheme set on store");
        return NULL;
    }

    cscheme = get_component_scheme(component_scheme_name);
    if (cscheme == NULL) {
        PyErr_Format(st->error, "w_store_calc_timeseries: invalid component scheme name %s", component_scheme_name);
        return NULL;
    }

    interpolation = get_interpolation_scheme_id(interpolation_scheme_name);
    if (interpolation == UNDEFINED_INTERPOLATION_SCHEME) {
        PyErr_Format(st->error, "w_store_calc_timeseries: invalid interpolation scheme name %s", interpolation_scheme_name);
        return NULL;
    }
    if (!good_array(source_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy source_coords array");
        return NULL;
    }

    shape_want_ms[1] = cscheme->nsource_terms;
    if (!good_array(ms_arr, NPY_FLOAT64, -1, 2, shape_want_ms)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy moment_tensors array");
        return NULL;
    }

    if (!good_array(receiver_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy reveiver_coords array");
        return NULL;
    }

    nsources = PyArray_DIMS((PyArrayObject*) source_coords_arr)[0];
    nreceivers = PyArray_DIMS((PyArrayObject*) receiver_coords_arr)[0];

    if (!good_array((PyObject*)delays_arr, NPY_FLOAT64, nsources, 1, NULL)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy delays array");
        return NULL;
    }

    if (!good_array((PyObject*)itmin_arr, NPY_INT32, nreceivers, 1, NULL)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy itmin array");
        return NULL;
    }

    if (!good_array((PyObject*)nsamples_arr, NPY_INT32, nreceivers, 1, NULL)) {
        PyErr_SetString(st->error, "w_store_calc_timeseries: unhealthy nsamples array");
        return NULL;
    }

    source_coords = PyArray_DATA((PyArrayObject*) source_coords_arr);
    ms = PyArray_DATA((PyArrayObject*) ms_arr);
    delays = PyArray_DATA((PyArrayObject*) delays_arr);
    receiver_coords = PyArray_DATA((PyArrayObject*) receiver_coords_arr);

    itmin = PyArray_DATA((PyArrayObject*) itmin_arr);
    nsamples = PyArray_DATA((PyArrayObject*) nsamples_arr);

    nresults = nreceivers*cscheme->ncomponents;
    // Initialize empty traces
    results = (result_trace_t*)calloc(nresults, sizeof(result_trace_t));
    if (results == NULL) {
        PyErr_SetString(st->error, "Could not allocate result struct");
        return NULL;
    }

    for (ires=0; ires<nresults; ires++) {
        nsamples_want = nsamples[ires / cscheme->ncomponents];
        itmin_want = itmin[ires / cscheme->ncomponents];

        result = &(results[ires]);

        result->icomponent = ires % cscheme->ncomponents;

        result->nsamples = 0;
        result->nsamples_want = nsamples_want;

        result->itmin = itmin_want;
        result->itmin_want = itmin_want;
        result->err = SUCCESS;

        result->begin_value = 0.0;
        result->end_value = 0.0;

        if (nsamples_want == -1) {
            result->buffer = NULL;
            result->data = NULL;
        } else {
            result->itmin = itmin_want;
            result->nsamples = nsamples_want;
            result->ncapacity = nsamples_want;
            result->buffer = (gf_dtype*) calloc(result->ncapacity, sizeof(gf_dtype));
            if (result->buffer == NULL) {
                free_results(results, nresults);
                PyErr_SetString(st->error, "Could not allocate result data array");
                return NULL;
            }
            result->data = result->buffer;
        }
    }

    err = store_calc_timeseries(
        store,
        source_coords,
        ms,
        delays,
        receiver_coords,
        nsources,
        nreceivers,
        cscheme,
        mscheme,
        store->mapping,
        interpolation,
        nthreads,
        results);

    if (SUCCESS != err) {
        free_results(results, nresults);
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }

    out_list = Py_BuildValue("[]");
    for (ires=0; ires < nreceivers*cscheme->ncomponents; ires++) {
        result = &(results[ires]);

        data = malloc(result->nsamples * sizeof(gf_dtype));
        memcpy(data, result->data, result->nsamples * sizeof(gf_dtype));

        array_dims[0] = result->nsamples;
        array = (PyObject*) PyArray_SimpleNewFromData(1, array_dims, NPY_GFDTYPE, data);
        PyArray_ENABLEFLAGS((PyArrayObject*) array, NPY_ARRAY_OWNDATA);

        out_tuple = Py_BuildValue("Nidiffii",
                array, result->itmin, store->deltat,
                result->is_zero, result->begin_value, result->end_value, result->icomponent, result->err);
        PyList_Append(out_list, out_tuple);


        Py_DECREF(out_tuple);
        /*printf("comp: %d, nsamples: %d, itmin: %d\n", result->icomponent, result->nsamples, result->itmin);*/
    }

    free_results(results, nresults);

    return out_list;
}


static PyObject* w_store_calc_static(PyObject *m, PyObject *args) {
    PyObject *capsule, *source_coords_arr, *receiver_coords_arr, *ms_arr, *delays_arr;
    PyArrayObject *results_arr;
    float64_t *source_coords, *receiver_coords, *ms, *delays;
    gf_dtype *results[NCOMPONENTS_MAX];
    int32_t it, nthreads;
    size_t icomponent, nsources, nreceivers;

    char *component_scheme_name, *interpolation_scheme_name;
    const component_scheme_t *cscheme;
    const mapping_scheme_t *mscheme;
    interpolation_scheme_id interpolation;
    store_error_t err;
    store_t *store;
    PyObject *out_list;

    npy_intp array_dims[1];
    npy_intp shape_want_coords[2] = {-1, 5};
    npy_intp shape_want_ms[2] = {-1, 6};

    struct module_state *st = GETSTATE(m);


    if (!PyArg_ParseTuple(
            args, "OOOOOssII", &capsule, &source_coords_arr, &ms_arr, &delays_arr, &receiver_coords_arr,
            &component_scheme_name, &interpolation_scheme_name,
            &it, &nthreads)) {
        PyErr_SetString(st->error,
            "usage: calc_static(cstore, source_coords, moment_tensors, delays, receiver_coords, component_scheme, interpolation_name, it, nthreads)");
        return NULL;
    }

    store = get_store_from_capsule(capsule);
    if (store == NULL) {
        PyErr_SetString(st->error, "w_store_calc_static: bad store given");
        return NULL;
    }

    mscheme = store->mapping_scheme;
    if (mscheme == NULL) {
        PyErr_SetString(st->error, "w_store_calc_static: no mapping scheme set on store");
        return NULL;
    }

    cscheme = get_component_scheme(component_scheme_name);
    if (cscheme == NULL) {
        PyErr_Format(st->error, "w_store_calc_static: invalid component scheme name %s", component_scheme_name);
        return NULL;
    }

    interpolation = get_interpolation_scheme_id(interpolation_scheme_name);
    if (interpolation == UNDEFINED_INTERPOLATION_SCHEME) {
        PyErr_Format(st->error, "w_store_calc_static: invalid interpolation scheme name %s", interpolation_scheme_name);
        return NULL;
    }

    if (!good_array(source_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        PyErr_SetString(st->error, "w_store_calc_static: unhealthy source_coords array");
        return NULL;
    }

    shape_want_ms[1] = cscheme->nsource_terms;
    if (!good_array(ms_arr, NPY_FLOAT64, -1, 2, shape_want_ms)) {
        PyErr_SetString(st->error, "w_store_calc_static: unhealthy moment_tensors array");
        return NULL;
    }

    if (!good_array(receiver_coords_arr, NPY_FLOAT64, -1, 2, shape_want_coords)) {
        PyErr_SetString(st->error, "w_store_calc_static: unhealthy reveiver_coords array");
        return NULL;
    }

    if (!good_array((PyObject*)delays_arr, NPY_FLOAT64, -1, 1, NULL)) {
        PyErr_SetString(st->error, "w_store_calc_static: unhealthy delays array");
        return NULL;
    }

    if (!inlimits(it)) {
        PyErr_SetString(st->error, "w_store_calc_static: invalid it argument");
        return NULL;
    }

    source_coords = PyArray_DATA((PyArrayObject*)source_coords_arr);
    ms = PyArray_DATA((PyArrayObject*)ms_arr);
    delays = PyArray_DATA((PyArrayObject*)delays_arr);
    receiver_coords = PyArray_DATA((PyArrayObject*)receiver_coords_arr);

    nsources = PyArray_DIMS((PyArrayObject*)source_coords_arr)[0];
    nreceivers = PyArray_DIMS((PyArrayObject*)receiver_coords_arr)[0];

    out_list = Py_BuildValue("[]");
    array_dims[0] = (npy_intp) nreceivers;

    for (icomponent=0; icomponent<cscheme->ncomponents; icomponent++) {
        results_arr = (PyArrayObject*) PyArray_ZEROS(1, array_dims, NPY_GFDTYPE, 0);
        results[icomponent] = PyArray_DATA(results_arr);

        PyList_Append(out_list, (PyObject*)results_arr);
        Py_DECREF(results_arr);
    }

    err = store_calc_static(
        store,
        source_coords,
        ms,
        delays,
        receiver_coords,
        nsources,
        nreceivers,
        cscheme,
        mscheme,
        store->mapping,
        interpolation,
        it,
        nthreads,
        results);

    if (SUCCESS != err) {
        Py_DECREF(out_list);
        PyErr_SetString(st->error, store_error_names[err]);
        return NULL;
    }

    return out_list;
}


static PyMethodDef store_ext_methods[] = {
    {"store_init",  w_store_init, METH_VARARGS,
        "Initialize store struct." },

    {"store_mapping_init", w_store_mapping_init, METH_VARARGS,
        "Initialize store index mapping." },

    {"store_get", w_store_get, METH_VARARGS,
        "Get a GF trace." },

    {"store_sum", w_store_sum, METH_VARARGS,
        "Get weight-and-delay-sum of GF traces." },

    {"store_sum_static", w_store_sum_static, METH_VARARGS,
        "Get weight-and-delay-sum of GF samples for static displacement." },

    {"store_calc_static", w_store_calc_static, METH_VARARGS,
        "Calculate static displacements (make make_sum_params obsolete)" },

    {"store_calc_timeseries", w_store_calc_timeseries, METH_VARARGS,
        "Calculate timeseries (make make_sum_params obsolete)" },

    {"make_sum_params", w_make_sum_params, METH_VARARGS,
        "Prepare parameters for weight-and-delay-sum." },

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int store_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int store_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "store_ext",
        "C-extension supporting :py:mod:`pyrocko.gf`.",
        sizeof(struct module_state),
        store_ext_methods,
        NULL,
        store_ext_traverse,
        store_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_store_ext(void)

{
    PyObject *module = PyModule_Create(&moduledef);
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.gf.store_ext.StoreExtError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "StoreExtError", st->error);

    return module;
}
