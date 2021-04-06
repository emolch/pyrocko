#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include "numpy/arrayobject.h"

#ifdef _WIN32
    #define timegm _mkgmtime

    char * strsep(char **sp, char *sep)
    {
        char *p, *s;
        if (sp == NULL || *sp == NULL || **sp == '\0') return(NULL);
        s = *sp;
        p = s + strcspn(s, sep);
        if (*p != '\0') *p++ = '\0';
        *sp = p;
        return(s);
    }
#endif

static const size_t BUFMAX = 10000000;
static const size_t READ_BUFFER_SIZE = 4096;
static const size_t BOOKMARK_INTERVAL = 1024*1024;
static const size_t N_GPS_TAGS_WANTED = 200;

/* convert char to positive int [0 - 255] regardless of char signedness
 * and without relying on undefined behaviour */
#define posint(x) ((((int)(x) % 256) + 256) % 256)
#define isnull(x) ((x) == NULL)

struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
#define GETSTATE(m) (&_state); (void) m;
static struct module_state _state;
#endif

int good_array(PyObject* o, int typenum) {
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

typedef enum {
    SUCCESS = 0,
    ALLOC_FAILED,
    BUFFER_LIMIT_EXCEEDED,
    READ_FAILED,
    KEY_NOT_FOUND,
    CONVERSION_ERROR,
    BAD_HEADER,
    HEADER_BLOCK_NOT_FOUND,
    BAD_NCHANNELS,
    UNKNOWN_BLOCK_TYPE,
    BAD_GPS_BLOCK,
    JUMP_FAILED,
} datacube_error_t;

const char* datacube_error_names[] = {
    "SUCCESS",
    "ALLOC_FAILED",
    "BUFFER_LIMIT_EXCEEDED",
    "READ_FAILED",
    "KEY_NOT_FOUND",
    "CONVERSION_ERROR",
    "BAD_HEADER",
    "HEADER_BLOCK_NOT_FOUND",
    "BAD_NCHANNELS",
    "UNKNOWN_BLOCK_TYPE",
    "BAD_GPS_BLOCK",
    "JUMP_FAILED",
};

typedef struct header_item {
    char *key;
    char *value;
    struct header_item *next;
} header_item_t;

typedef struct {
    int32_t *elements;
    size_t size;
    size_t fill;
} int32_array_t;

static int32_array_t ZERO_INT32_ARRAY = {NULL, 0, 0};

typedef struct {
    size_t ipos;
    double t;
    int fix;
    int nsvs;
} gps_tag_t;

typedef struct {
    gps_tag_t *elements;
    size_t size;
    size_t fill;
} gps_tag_array_t;

/*static gps_tag_array_t ZERO_GPS_TAG_ARRAY = {NULL, 0, 0}; */

typedef struct {
    off_t fpos;
    size_t ipos;
    size_t ipos_gps;
    size_t gps_tags_fill;
} backjump_t;

static backjump_t ZERO_BACKJUMP = {0, (size_t)(-1), 0, 0};

typedef struct {
    size_t ipos;
    off_t fpos;
} bookmark_t;

typedef struct {
    bookmark_t *elements;
    size_t size;
    size_t fill;
} bookmark_array_t;

typedef struct {
    int f;
    char *buf_1;
    size_t rpos;
    size_t wpos;

    char *buf;
    size_t buf_size;
    size_t buf_fill;

    int nchannels;
    size_t ipos;
    size_t ipos_gps;
    int load_data;
    ssize_t offset_want;
    ssize_t nsamples_want;
    double deltat;
    double tdelay;
    char *recording_unit;
    header_item_t *header;
    int32_array_t *arrays;
    gps_tag_array_t gps_tags;
    bookmark_array_t bookmarks;
} reader_t;

static reader_t ZERO_READER = {
    0, NULL, 1, 1, NULL, 0, 0, 0, 0, (size_t)(-1), 0, 0, -1, 0.0, 0.0, NULL,
    NULL, NULL, {NULL, 0, 0}, {NULL, 0, 0}};

size_t next_pow2(size_t x) {
    size_t y = 1;
    if (y == 0) return 0;
    while (y <= x) y += y;
    return y;
}

size_t smax(size_t a, size_t b) {
    return a > b ? a : b;
}

size_t smin(size_t a, size_t b) {
    return a < b ? a : b;
}

datacube_error_t int32_array_append(int32_array_t *arr, int32_t x) {
    int32_t *p;
    size_t n;
    if (arr->fill == arr->size) {
        n = smax(1024, arr->size*2);
        p = (int32_t*)realloc(arr->elements, n*sizeof(int32_t));
        if (isnull(p)) {
            return ALLOC_FAILED;
        }
        arr->elements = p;
        arr->size = n;
    }
    arr->elements[arr->fill] = x;
    arr->fill++;

    return SUCCESS;
}

datacube_error_t gps_tag_array_append(gps_tag_array_t *arr, size_t ipos,
                              double t, int fix, int nsvs) {
    gps_tag_t *p, *el;
    size_t n;
    if (arr->fill == arr->size) {
        n = smax(1024, arr->size*2);
        p = (gps_tag_t*)realloc(arr->elements, n*sizeof(gps_tag_t));
        if (isnull(p)) {
            return ALLOC_FAILED;
        }
        arr->elements = p;
        arr->size = n;
    }

    el = &arr->elements[arr->fill];
    el->ipos = ipos;
    el->t = t;
    el->fix = fix;
    el->nsvs = nsvs;

    arr->fill++;

    return SUCCESS;
}

datacube_error_t bookmark_array_append(bookmark_array_t *arr,
                                       size_t ipos, off_t fpos) {
    bookmark_t *p, *el;
    size_t n;
    if (arr->fill == arr->size) {
        n = smax(1024, arr->size*2);
        p = (bookmark_t*)realloc(arr->elements, n*sizeof(bookmark_t));
        if (isnull(p)) {
            return ALLOC_FAILED;
        }
        arr->elements = p;
        arr->size = n;
    }

    el = &arr->elements[arr->fill];
    el->ipos = ipos;
    el->fpos = fpos;

    arr->fill++;

    return SUCCESS;
}

datacube_error_t datacube_adjust_buffer(reader_t *reader, size_t n) {
    char *p;
    if (n > reader->buf_size) {
        n = smax(1024, next_pow2(n) * 2);
        if (n > BUFMAX) {
            return BUFFER_LIMIT_EXCEEDED;
        }
        p = (char*)realloc(reader->buf, n);
        if (isnull(p)) {
            return ALLOC_FAILED;
        }
        reader->buf = p;
        reader->buf_size = n;
    }
    return SUCCESS;
}

datacube_error_t datacube_read(reader_t *reader, size_t n) {
    ssize_t nread;
    size_t n1;
    datacube_error_t err;

    /* + 1 so that caller can safely null-terminate the buffer */
    err = datacube_adjust_buffer(reader, reader->buf_fill + n + 1);
    if (err != SUCCESS) {
        return err;
    }

    while (n > 0) {
        n1 = smin(reader->wpos - reader->rpos, n);
        memcpy(reader->buf + reader->buf_fill,
               reader->buf_1 + reader->rpos, n1);

        reader->rpos += n1;
        reader->buf_fill += n1;
        n -= n1;
        if (reader->wpos == reader->rpos) {
            nread = read(reader->f, reader->buf_1+1, READ_BUFFER_SIZE);
            if (nread <= 0) {
                return READ_FAILED;
            }
            reader->wpos = nread+1;
            reader->rpos = 1;
        }
    }
    return SUCCESS;
}

datacube_error_t datacube_read_to(reader_t *reader, char sepmin, char *sepfound) {
    datacube_error_t err;
    while (1) {
        err = datacube_read(reader, 1);
        if (err != SUCCESS) {
            return err;
        }
        if ((unsigned int)reader->buf[reader->buf_fill - 1] >= (unsigned int)sepmin) {
            *sepfound = reader->buf[reader->buf_fill - 1];
            break;
        }
    }
    reader->buf[reader->buf_fill] = '\0';
    reader->buf_fill += 1;
    return SUCCESS;
}

void datacube_push_back(reader_t *reader, char c) {
    reader->rpos--;
    reader->buf_1[reader->rpos] = c;
}

datacube_error_t datacube_read_blocktype(reader_t *reader, int *blocktype) {
    datacube_error_t err;
    err = datacube_read(reader, 1);
    if (err != SUCCESS) {
        return err;
    }

    *blocktype = posint(reader->buf[0]) >> 4;

    reader->buf_fill = 0;
    return SUCCESS;
}

datacube_error_t get_str_header(reader_t *reader, char *key, char **value) {
    header_item_t *item;
    item = reader->header;
    while (!isnull(item)) {
        if (0 == strcmp(item->key, key)) {
            *value = item->value;
            return SUCCESS;
        }
        item = item->next;
    }
    return KEY_NOT_FOUND;
}

datacube_error_t get_int_header(reader_t *reader, char *key, int *value) {
    char *svalue;
    datacube_error_t err;
    int n;
    err = get_str_header(reader, key, &svalue);
    if (err != SUCCESS) {
        return err;
    }
    n = sscanf(svalue, "%i", value);
    if (n != 1) {
        return CONVERSION_ERROR;
    }
    return SUCCESS;
}

datacube_error_t datacube_read_header_block(reader_t *reader) {
    datacube_error_t err;
    header_item_t *item, *prev;
    char *k, *scopy, *p, *s;
    char sepfound;
    int i, srate, dfilt;

    err = datacube_read_to(reader, '\x80', &sepfound);
    if (err != SUCCESS) {
        return err;
    }
    reader->buf[reader->buf_fill-2] = '\0';

    i = 0;
    p = reader->buf;
    k = NULL;
    scopy = NULL;
    prev = NULL;
    while (1) {
        s = strsep(&p, ";=");
        if (isnull(s)) {
            break;
        }
        scopy = malloc(strlen(s)+1);
        if (isnull(scopy)) {
            return ALLOC_FAILED;
        }
        strcpy(scopy, s);

        if (i == 0) {
            k = scopy;
            i = 1;
        } else {
            item = calloc(1, sizeof(header_item_t));
            if (isnull(item)) {
                free(k);
                free(scopy);
                return ALLOC_FAILED;
            }
            item->key = k;
            k = NULL;
            item->value = scopy;
            scopy = NULL;
            item->next = NULL;

            if (isnull(prev)) {
                reader->header = item;
            } else {
                prev->next = item;
            }
            prev = item;
            i = 0;
        }
    }

    if (!isnull(k)) {  /* odd number of elements */
        free(k);
        return BAD_HEADER;
    }

    err = get_int_header(reader, "CH_NUM", &reader->nchannels);
    if (err != SUCCESS) {
        return err;
    }
    if (reader->nchannels < 0 || reader->nchannels > 1024) {
        return BAD_NCHANNELS;
    }

    err = get_int_header(reader, "S_RATE", &srate);
    if (err != SUCCESS) {
        return err;
    }
    reader->deltat = 1.0 / srate;

    err = get_int_header(reader, "D_FILT", &dfilt);
    if (err != SUCCESS) {
        return err;
    }
    reader->tdelay = reader->deltat * dfilt;

    err = get_str_header(reader, "DEV_NO", &reader->recording_unit);
    if (err != SUCCESS) {
        return err;
    }

    if (reader->load_data == 2) {
        reader->arrays = calloc(reader->nchannels, sizeof(int32_array_t));
        if (isnull(reader->arrays)) {
            return ALLOC_FAILED;
        }

        for (i=0; i<reader->nchannels; i++) {
            reader->arrays[i] = ZERO_INT32_ARRAY;
        }
    }

    datacube_push_back(reader, sepfound);

    reader->buf_fill = 0;
    return SUCCESS;
}

int datacube_in_wanted_region(reader_t *reader) {
    return reader->offset_want <= (ssize_t)reader->ipos && (
        reader->nsamples_want == -1 ||
        (ssize_t)reader->ipos < reader->offset_want + reader->nsamples_want);
}

datacube_error_t datacube_read_data_block(reader_t *reader) {
    datacube_error_t err;
    size_t n;
    int i;
    char *b;
    int32_t v;

    n = 4 * reader->nchannels;
    err = datacube_read(reader, n);
    if (err != SUCCESS) {
        return err;
    }

    if (reader->load_data == 2 && datacube_in_wanted_region(reader)) {
        b = reader->buf;
        for (i=0; i<reader->nchannels; i++) {
            v = posint(b[i*4 + 0]) << 17;
            v += posint(b[i*4 + 1]) << 10;
            v += posint(b[i*4 + 2]) << 3;
            v += posint(b[i*4 + 3]);
            v -= (v & 0x800000) << 1;
            err = int32_array_append(&reader->arrays[i], v);
            if (err != SUCCESS) {
                return err;
            }
        }
    }

    reader->ipos++;

    reader->buf_fill = 0;
    return SUCCESS;
}

datacube_error_t datacube_read_pps_data_block(reader_t *reader) {
    reader->ipos_gps = reader->ipos;
    return datacube_read_data_block(reader);
}

datacube_error_t datacube_read_gps_block(reader_t *reader) {
    datacube_error_t err;
    char *b;
    struct tm tm;
    time_t t;
    double tgps, tshift;
    int msecs;
    int gps_utc_time_offset;
    int current_fix_source;
    int number_usable_svs;
    int gps_utc_offset_flag;

    err = datacube_read(reader, 79);

    reader->buf_fill = 0;
    if (reader->ipos_gps == (size_t)(-1)) {
        return SUCCESS;
    }
    if (err != SUCCESS) {
        return err;
    }

    if (!datacube_in_wanted_region(reader)) {
        return SUCCESS;
    }

    b = strstr(reader->buf, ">RTM");
    if (b == NULL) {
        return BAD_GPS_BLOCK;
    }
    b += 4;

    if (7 != sscanf(b, "%2d%2d%2d%3d%2d%2d%4d",
            &tm.tm_hour, &tm.tm_min, &tm.tm_sec, &msecs,
            &tm.tm_mday, &tm.tm_mon, &tm.tm_year)) {
        return BAD_GPS_BLOCK;
    }

    tm.tm_mon -= 1;
    tm.tm_year -= 1900;

    t = timegm(&tm);
    b += 17;
    b[6] = '\0';
    if (4 != sscanf(b, "%2i%1i%2i%1i", &gps_utc_time_offset,
                    &current_fix_source, &number_usable_svs,
                    &gps_utc_offset_flag)) {
        return BAD_GPS_BLOCK;
    }

    b = reader->buf + 76;
    if (posint(b[0]) >> 4 != 11) {
        return BAD_GPS_BLOCK;
    }
    tshift = (posint(b[1])*128 + posint(b[2])) * 2.44140625;

    tgps = t + tshift / 1000000.0 - reader->tdelay +
        ((gps_utc_offset_flag == 0) ? 0 : gps_utc_time_offset);

    if (current_fix_source != 0 || number_usable_svs >= 1) {
        err = gps_tag_array_append(&reader->gps_tags, reader->ipos_gps, tgps,
                current_fix_source, number_usable_svs);

        if (err != SUCCESS) {
            return err;
        }
    }

    return SUCCESS;
}

datacube_error_t datacube_read_diagnostics_block(reader_t *reader) {
    char sepfound;
    datacube_error_t err;

    err = datacube_read_to(reader, '\x80', &sepfound);
    if (err != SUCCESS) {
        return err;
    }

    reader->buf_fill = 0;
    datacube_push_back(reader, sepfound);

    return SUCCESS;
}

datacube_error_t datacube_read_unknown_block_3(reader_t *reader) {
    datacube_error_t err;

    err = datacube_read(reader, 2);
    if (err != SUCCESS) {
        return err;
    }

    reader->buf_fill = 0;

    return SUCCESS;
}

datacube_error_t datacube_init(reader_t *reader, int f) {
    *reader = ZERO_READER;
    reader->f = f;
    reader->buf_1 = malloc(READ_BUFFER_SIZE+1); /* +1 for push back support */
    if (isnull(reader->buf_1)) {
        return ALLOC_FAILED;
    }
    return SUCCESS;
}

void datacube_deinit(reader_t *reader) {
    header_item_t *item, *prev;
    int i;

    if (!isnull(reader->buf_1)) {
        free(reader->buf_1);
    }

    if (!isnull(reader->buf)) {
        free(reader->buf);
    }

    item = reader->header;
    while (!isnull(item)) {
        if (!isnull(item->key)) free(item->key);
        if (!isnull(item->value)) free(item->value);
        prev = item;
        item = item->next;
        free(prev);
    }
    if (!isnull(reader->arrays)) {
        for (i=0; i<reader->nchannels; i++) {
            if (!isnull(reader->arrays[i].elements)) {
                free(reader->arrays[i].elements);
            }
        }
        free(reader->arrays);
    }

    if (!isnull(reader->gps_tags.elements)) {
        free(reader->gps_tags.elements);
    }

    if (!isnull(reader->bookmarks.elements)) {
        free(reader->bookmarks.elements);
    }

    *reader = ZERO_READER;
}

off_t datacube_tell(reader_t *reader) {
    return lseek(reader->f, 0, SEEK_CUR) - (reader->wpos - reader->rpos);
}

void init_backjump(reader_t *reader, backjump_t *backjump) {
    backjump->fpos = datacube_tell(reader);
    backjump->ipos = reader->ipos;
    backjump->ipos_gps = reader->ipos_gps;
    backjump->gps_tags_fill = reader->gps_tags.fill;
}

void do_backjump(reader_t *reader, backjump_t *backjump) {
    lseek(reader->f, backjump->fpos, SEEK_SET);
    reader->wpos = 1;
    reader->rpos = 1;
    reader->buf_fill = 0;
    reader->ipos = backjump->ipos;
    reader->ipos_gps = backjump->ipos_gps;
    reader->gps_tags.fill = backjump->gps_tags_fill;
}

datacube_error_t datacube_jump(reader_t *reader, off_t offset, int whence,
                               backjump_t *backjump) {

    off_t proposed;
    datacube_error_t err;
    int iok, blocktype;

    init_backjump(reader, backjump);

    proposed = lseek(reader->f, offset, whence);
    reader->wpos = 1;
    reader->rpos = 1;

    if (proposed <= backjump->fpos) {
        lseek(reader->f, backjump->fpos, SEEK_SET);
        *backjump = ZERO_BACKJUMP;
        return JUMP_FAILED;
    } else {
        reader->ipos_gps = (size_t)(-1);
        iok = 0;
        while (iok < 20) {
            err = datacube_read_blocktype(reader, &blocktype);
            if (err != SUCCESS) break;

            if (blocktype == 8 || blocktype == 9) {
                err = datacube_read(reader, 4*reader->nchannels);
                reader->buf_fill = 0;
                iok += 1;
            } else if (blocktype == 10) {
                err = datacube_read(reader, 79);
                reader->buf_fill = 0;
                iok += 1;
            } else if (blocktype == 14) {
                break;
            } else {
                iok = 0;
            }
            if (err != SUCCESS) break;
        }

        if (iok < 20) {
            do_backjump(reader, backjump);
            *backjump = ZERO_BACKJUMP;
            return JUMP_FAILED;
        }
    }
    return SUCCESS;
}

datacube_error_t datacube_skip_to_offset(reader_t *reader, size_t ipos) {
    bookmark_t *bookmark;
    size_t i;

    bookmark = NULL;
    for (i=0; i+1 < reader->bookmarks.fill; i++) {
        if (ipos >= reader->bookmarks.elements[i].ipos) {
            bookmark = &reader->bookmarks.elements[i];
        }
    }

    if (bookmark != NULL) {
        lseek(reader->f, bookmark->fpos, SEEK_SET);
        reader->ipos = bookmark->ipos;
        reader->wpos = 1;
        reader->rpos = 1;
        reader->buf_fill = 0;
        reader->ipos_gps = 0;
        reader->gps_tags.fill = 0;
    }

    return SUCCESS;
}

datacube_error_t datacube_load(reader_t *reader) {
    int blocktype;
    datacube_error_t err;
    int jumpallowed, backjumpallowed;
    off_t roffset;
    int gps_ti, f_time, gps_on;
    backjump_t backjump;
    float toffset;
    int nblocks_needed;

    /* block types:
     *
     * 0x00          skip
     * 0x30   48   3:
     * 0x80  128   8: data block
     * 0x90  144   9: data block with pps
     * 0xa0  160  10: gps block
     * 0xb0       11: delay time block ???
     * 0xc0  192  12: Event block from 1 byte info, from version 5.0(1C) 2.0(3C) 2 bytes
     *                        if first byte is 1 should abort (buffer overrun in recorder)
     * 0xcf       12: diagnostics x byte ??? read while (byte >> 4) < 8
     * 0xd0  208  13: info block ascii ???
     * 0xd1       13:  aux channel
     *                     read 1 byte -> (byte & 0xf) - 2 is number of bytes to read additionally
     * 0xe0  224  14: end block
     * 0xef         : header block (at end???)
     * 0xf0  240  15: header block
     *
     */

    err = datacube_read_blocktype(reader, &blocktype);
    if (err != SUCCESS) {
        return err;
    }
    if (blocktype != 15) {
        return HEADER_BLOCK_NOT_FOUND;
    }
    err = datacube_read_header_block(reader);
    if (err != SUCCESS) {
        return err;
    }

    if (reader->load_data == 3) {
        return SUCCESS;
    }

    if (reader->load_data != 0 && reader->offset_want > 0) {
        err = datacube_skip_to_offset(reader, reader->offset_want);
        if (err != SUCCESS) {
            return err;
        }
    }

    jumpallowed = reader->load_data == 0;
    backjumpallowed = 0;

    while (1) {
        err = datacube_read_blocktype(reader, &blocktype);
        if (err == READ_FAILED) {
            if (backjumpallowed && reader->gps_tags.fill < N_GPS_TAGS_WANTED*2) {
                do_backjump(reader, &backjump);
                continue;
            } else {
                break;
            }
        } else if (err != SUCCESS) {
            return err;
        }

        if ((reader->ipos % BOOKMARK_INTERVAL == 0) &&
                (blocktype == 8 || blocktype == 9) &&
                (reader->load_data == 1 || reader->load_data == 2) &&
                (reader->offset_want == 0 && reader->nsamples_want == -1)) {
            bookmark_array_append(&reader->bookmarks,
                                  reader->ipos,
                                  datacube_tell(reader) - 1);
        }

        if (blocktype == 8) {
            err = datacube_read_data_block(reader);
        } else if (blocktype == 9) {
            err = datacube_read_pps_data_block(reader);
        } else if (blocktype == 10) {
            err = datacube_read_gps_block(reader);
            if (err == BAD_GPS_BLOCK) {
                fprintf(stderr, "ignoring a bad gps block\n");
                err = SUCCESS;
            }
        } else if (blocktype == 14) {
            /*datacube_read_end_block(reader);*/
            if (backjumpallowed && reader->gps_tags.fill < N_GPS_TAGS_WANTED*2) {
                do_backjump(reader, &backjump);
                continue;
            } else {
                break;
            }
        } else if (blocktype == 12) {
            err = datacube_read_diagnostics_block(reader);
        } else if (blocktype == 0) {
            fprintf(stderr, "skipping block type %i\n", blocktype);
        } else if (blocktype == 3) {
            fprintf(stderr, "skipping block type %i\n", blocktype);
            datacube_read_unknown_block_3(reader);
        } else {
            fprintf(stderr, "unknown block type %i\n", blocktype);
            return UNKNOWN_BLOCK_TYPE;
        }
        if (err == READ_FAILED) {
            if (backjumpallowed && reader->gps_tags.fill < N_GPS_TAGS_WANTED*2) {
                do_backjump(reader, &backjump);
                continue;
            } else {
                /* incomplete file? */
                break;
            }
        } else if (err != SUCCESS) {
            return err;
        }

        if (jumpallowed && reader->gps_tags.fill == N_GPS_TAGS_WANTED) {
            err = get_int_header(reader, "GPS_ON", &gps_on);
            if (err != SUCCESS) jumpallowed = 0;
            if (gps_on == 0) { /* cycled GPS */
                err = get_int_header(reader, "GPS_TI", &gps_ti);
                if (err != SUCCESS) jumpallowed = 0;
                err = get_int_header(reader, "F_TIME", &f_time);
                if (err != SUCCESS) jumpallowed = 0;

                nblocks_needed = (int)ceil(N_GPS_TAGS_WANTED / (gps_ti * 60.));
                toffset = (gps_ti + f_time) * 60.0 * nblocks_needed;
                roffset = toffset * 1.0/reader->deltat * (reader->nchannels * 4 + 1) + nblocks_needed * (gps_ti*60) * 80;

            } else if (gps_on == 1) { /* continuous GPS */
                roffset = datacube_tell(reader) * 2;
            } else {
                roffset = 0;
                jumpallowed = 0;
            }

            if (jumpallowed) {
                err = datacube_jump(reader, -roffset, SEEK_END, &backjump);
                if (err == SUCCESS) {
                    backjumpallowed = 1;
                }
                jumpallowed = 0;
            }
        }

        if (reader->nsamples_want != -1 &&
                (ssize_t)reader->ipos >= reader->offset_want + reader->nsamples_want) {
            break;
        }
    }
    return SUCCESS;
}

static PyObject* header_to_pylist(reader_t *reader) {
    PyObject *list, *element;
    header_item_t *item;

    list = PyList_New(0);
    if (isnull(list)) {
        return NULL;
    }

    item = reader->header;
    while (item != NULL) {
        element = Py_BuildValue("(s,s)", item->key, item->value);
        if (isnull(element)) {
            return NULL;
        }
        PyList_Append(list, element);
        Py_DECREF(element);
        item = item->next;
    }
    return list;
}

static PyObject* transfer_arrays(reader_t *reader) {
    PyObject *list;
    int i;
    npy_intp array_dims[1];
    PyObject *array;

    list = PyList_New(0);
    if (isnull(list)) {
        return NULL;
    }

    if (!isnull(reader->arrays)) {
        for (i=0; i<reader->nchannels; i++) {
            array_dims[0] = reader->arrays[i].fill;
            array = PyArray_SimpleNew(1, array_dims, NPY_INT32);
            if (array == NULL) {
                return NULL;
            }

            memcpy(PyArray_DATA((PyArrayObject*)array), reader->arrays[i].elements,
                   reader->arrays[i].fill*sizeof(int32_t));

            free(reader->arrays[i].elements);
            reader->arrays[i].elements = NULL;
            PyList_Append(list, array);
            Py_DECREF(array);
        }
    }
    return list;
}

static PyObject* gps_tags_to_pytup(reader_t *reader) {
    PyObject *out;
    PyObject *aipos, *at, *afix, *ansvs;
    size_t n;
    size_t i;
    npy_intp array_dims[1];

    n = reader->gps_tags.fill;
    array_dims[0] = n;

    aipos = PyArray_SimpleNew(1, array_dims, NPY_INT64);
    at = PyArray_SimpleNew(1, array_dims, NPY_FLOAT64);
    afix = PyArray_SimpleNew(1, array_dims, NPY_INT8);
    ansvs = PyArray_SimpleNew(1, array_dims, NPY_INT8);
    if (aipos == NULL || at == NULL || afix == NULL || ansvs == NULL) {
        return NULL;
    }

    for (i=0; i<n; i++) {
        ((int64_t*)PyArray_DATA((PyArrayObject*)aipos))[i] = reader->gps_tags.elements[i].ipos;
        ((double*)PyArray_DATA((PyArrayObject*)at))[i] = reader->gps_tags.elements[i].t;
        ((int8_t*)PyArray_DATA((PyArrayObject*)afix))[i] = reader->gps_tags.elements[i].fix;
        ((int8_t*)PyArray_DATA((PyArrayObject*)ansvs))[i] = reader->gps_tags.elements[i].nsvs;
    }
    out = Py_BuildValue("(NNNN)", aipos, at, afix, ansvs);
    return out;
}

static PyObject* bookmarks_to_pyarray(reader_t *reader) {
    PyObject *out;
    size_t n;
    size_t i;
    npy_intp array_dims[2];

    n = reader->bookmarks.fill;
    array_dims[0] = n;
    array_dims[1] = 2;

    out = PyArray_SimpleNew(2, array_dims, NPY_INT64);
    if (out == NULL) {
        return NULL;
    }
    for (i=0; i<n; i++) {
        ((int64_t*)PyArray_DATA((PyArrayObject*)out))[i*2] = reader->bookmarks.elements[i].ipos;
        ((int64_t*)PyArray_DATA((PyArrayObject*)out))[i*2+1] = reader->bookmarks.elements[i].fpos;
    }
    return out;
}

int pyarray_to_bookmarks(reader_t *reader, PyObject *barr) {
    int64_t *carr;
    size_t i, n;

    if (!good_array(barr, NPY_INT64)) {
        return 1;
    }
    if (PyArray_NDIM((PyArrayObject*)barr) != 2 ||
        PyArray_DIMS((PyArrayObject*)barr)[1] != 2) {
    }
    n = PyArray_DIMS((PyArrayObject*)barr)[0];

    carr = (int64_t*)PyArray_DATA((PyArrayObject*)barr);

    for (i=0; i<n; i++) {
        bookmark_array_append(&reader->bookmarks, carr[i*2], carr[i*2+1]);
    }
    return 0;
}

static PyObject* w_datacube_load(PyObject *m, PyObject *args) {
    /*
    load_data == 0: only load enough gps tags at beginning and end of file to
                    determine time range
    load_data == 1: load all gps tags but don't unpack data samples
    load_data == 2: load everything
    load_data == 3: load header only
    */

    int f;
    int load_data;
    datacube_error_t err;
    reader_t reader;
    PyObject *hlist, *alist, *gtup, *barr;
    size_t nsamples_total;
    ssize_t offset_want, nsamples_want;

    struct module_state *st = GETSTATE(m);

    if (!PyArg_ParseTuple(args, "iinnO", &f, &load_data,
                          &offset_want, &nsamples_want, &barr)) {
        PyErr_SetString(st->error,
            "usage load(f, load_data, offset_want, nsamples_want)");
        return NULL;
    }

    err = datacube_init(&reader, f);
    if (err != SUCCESS) {
        PyErr_SetString(st->error, datacube_error_names[err]);
        return NULL;
    }
    reader.load_data = load_data;
    reader.offset_want = offset_want;
    reader.nsamples_want = nsamples_want;

    if (barr != Py_None) {
        err = pyarray_to_bookmarks(&reader, barr);
        if (err != SUCCESS) {
            PyErr_SetString(st->error, "bookmarks corrupted");
            return NULL;
        }
    }

    err = datacube_load(&reader);
    if (err != SUCCESS) {
        PyErr_SetString(st->error, datacube_error_names[err]);
        return NULL;
    }

    hlist = header_to_pylist(&reader);
    alist = transfer_arrays(&reader);
    gtup = gps_tags_to_pytup(&reader);
    barr = bookmarks_to_pyarray(&reader);
    nsamples_total = reader.ipos;

    datacube_deinit(&reader);

    if (isnull(hlist) || isnull(alist) || isnull(gtup) || isnull(barr)) {
        PyErr_SetString(st->error, "could not build python objects");
        return NULL;
    }

    return Py_BuildValue("NNNKN", hlist, alist, gtup,
                         (unsigned long long)nsamples_total, barr);
}

static PyMethodDef datacube_ext_methods[] = {
    {"load",  w_datacube_load, METH_VARARGS,
        "load raw datacube file" },

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


#if PY_MAJOR_VERSION >= 3

static int datacube_ext_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int datacube_ext_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "datacube_ext",
        NULL,
        sizeof(struct module_state),
        datacube_ext_methods,
        NULL,
        datacube_ext_traverse,
        datacube_ext_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_datacube_ext(void)

#else
#define INITERROR return

void
initdatacube_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
    PyObject *module = PyModule_Create(&moduledef);
#else
    PyObject *module = Py_InitModule("datacube_ext", datacube_ext_methods);
#endif
    import_array();

    if (module == NULL)
        INITERROR;
    struct module_state *st = GETSTATE(module);

    st->error = PyErr_NewException("pyrocko.datacube_ext.DataCubeError", NULL, NULL);
    if (st->error == NULL) {
        Py_DECREF(module);
        INITERROR;
    }

    Py_INCREF(st->error);
    PyModule_AddObject(module, "DataCubeError", st->error);

#if PY_MAJOR_VERSION >= 3
    return module;
#endif
}
