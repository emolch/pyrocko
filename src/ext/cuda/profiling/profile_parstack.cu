#include "../parstack.cuh"
#include "../utils.cuh"
#include <cuda_profiler_api.h>
#include <stdio.h>

void initA(size_t narrays, size_t nshifts, size_t nsamples, size_t *lengths,
           int32_t *offsets, int32_t *shifts, float *weights, float **arrays) {
  for (int iarray = 0; iarray < narrays; iarray++) {
    lengths[iarray] = nsamples;
    offsets[iarray] = iarray;

    arrays[iarray] = (float *)calloc(nsamples, sizeof(float));

    for (int isample = 0; isample < nsamples; isample++) {
      arrays[iarray][isample] = isample;
    }

    for (int ishift = 0; ishift < nshifts; ishift++) {
      weights[ishift * narrays + iarray] = 1;
    }
  }
}

int profile(size_t narrays, size_t nshifts, size_t nsamples,
            size_t target_block_threads,
            void (*initf)(size_t narrays, size_t nshifts, size_t nsamples,
                          size_t *lengths, int32_t *offsets, int32_t *shifts,
                          float *weights, float **arrays)) {
  int method = 0;
  int nparallel = 1;
  int32_t *offsets = (int32_t *)calloc(narrays, sizeof(int32_t));
  size_t *lengths = (size_t *)calloc(narrays, sizeof(size_t));
  int32_t *shifts = (int32_t *)calloc(nshifts * narrays, sizeof(int32_t));
  float *weights = (float *)calloc(nshifts * narrays, sizeof(float));
  float **arrays = (float **)calloc(narrays * nsamples, sizeof(float));

  (*initf)(narrays, nshifts, nsamples, lengths, offsets, shifts, weights,
           arrays);

  int32_t imin, imax, istart, iend;
  size_t iarray, ishift;

  imin = offsets[0] + shifts[0];
  imax = imin + lengths[0];
  for (iarray = 0; iarray < narrays; iarray++) {
    for (ishift = 0; ishift < nshifts; ishift++) {
      istart = offsets[iarray] + shifts[ishift * narrays + iarray];
      iend = istart + lengths[iarray];
      imin = min(imin, istart);
      imax = max(imax, iend);
    }
  }

  size_t lengthout = imax - imin;
  size_t offsetout = imin;

  float *result = (float *)malloc(nshifts * lengthout * sizeof(float));

  cudaProfilerStart();

  char *err_msg = NULL;
  int err = cuda_parstack(narrays, arrays, offsets, lengths, nshifts, shifts,
                          weights, method, lengthout, offsetout, result,
                          IMPL_CUDA, nparallel, target_block_threads, &err_msg);

  cudaProfilerStop();

  if (err != SUCCESS) {
    if (err_msg != NULL)
      free(err_msg);
    return ERROR;
  }

  for (size_t i = 0; i < narrays; i++)
    free(arrays[i]);
  free(arrays);
  free(offsets);
  free(lengths);
  free(shifts);
  free(weights);
  free(result);
  return 0;
}

int profileA(size_t narrays, size_t nshifts, size_t nsamples,
             size_t target_block_threads) {
  return profile(narrays, nshifts, nsamples, target_block_threads, initA);
}

int main() { return profileA(5000, 5000, 100, 256); }
