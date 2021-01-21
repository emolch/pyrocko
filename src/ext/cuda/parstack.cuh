#pragma once
#include "utils.cuh"

#ifdef __cplusplus
#include <cstdint>
#define EXTERNC extern "C"
#else
#define EXTERNC
#endif

EXTERNC typedef struct {
  size_t narrays;
  int32_t *offsets;
  size_t *lengths;
  size_t nshifts;
  int32_t *shifts;
  uint8_t method;
  size_t lengthout;
  int32_t offsetout;
  impl_t impl;
  uint8_t nparallel;
  size_t target_block_threads;
  char **err;
} parstack_arguments_t;


EXTERNC int cuda_parstack_float(float **arrays, float *weights, float *result, parstack_arguments_t args);

EXTERNC int cuda_parstack_double(double **arrays, double *weights, double *result, parstack_arguments_t args);

EXTERNC int check_cuda_parstack_implementation_compatibility(impl_t impl,
                                                             int *compatible,
                                                             char **err);

EXTERNC int calculate_cuda_parstack_kernel_parameters(
    impl_t impl, size_t narrays, size_t nshifts, size_t nsamples,
    size_t lengthout, int32_t offsetout, size_t target_block_threads,
    size_t work_per_thread, size_t shared_memory_per_thread,
    unsigned int grid[3], unsigned int blocks[3], size_t *shared_memory,
    char **err);

#undef EXTERNC
