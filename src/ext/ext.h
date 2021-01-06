#pragma once

#include "Python.h"
#define UNUSED(x) (void)x;

struct module_state {
  PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
#define GETSTATE(m) ((struct module_state *)PyModule_GetState(m))
#else
#define GETSTATE(m)                                                            \
  (&_state);                                                                   \
  (void)m;
static struct module_state _state;
#endif

int32_t min(int32_t a, int32_t b) { return (a < b) ? a : b; }

size_t smin(size_t a, size_t b) { return (a < b) ? a : b; }

int32_t max(int32_t a, int32_t b) { return (a > b) ? a : b; }

PyObject *handle_error(const char *call, struct module_state *st,
                       char *err_msg) {
  size_t len = snprintf(NULL, 0, "%s failed: %s", call, err_msg);
  char *full_err_msg = malloc(len + 1);
  snprintf(full_err_msg, len + 1, "%s failed: %s", call, err_msg);
  PyErr_SetString(st->error, full_err_msg);
  if (err_msg != NULL)
    free(err_msg);
  free(full_err_msg);
  return NULL;
}
