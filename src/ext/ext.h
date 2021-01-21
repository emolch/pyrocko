#pragma once

#include "Python.h"
#include <stdarg.h>
#include <stdio.h>
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

int format(char **dest, const char *format, ...) {
  va_list args;
  int ret;

  va_start(args, format);
  size_t len = vsnprintf(NULL, 0, format, args);
  *dest = malloc(len + 1);
  ret = vsnprintf(*dest, len + 1, format, args);
  va_end(args);

  return ret;
}

PyObject *handle_error(const char *call, PyObject *error, char *err_msg) {
  char *full_err_msg;
  format(&full_err_msg, "%s: failed: %s", call, err_msg);
  PyErr_SetString(error, full_err_msg);
  if (err_msg != NULL)
    free(err_msg);
  free(full_err_msg);
  return NULL;
}
