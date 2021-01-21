#include <stdio.h>

#include "utils.cuh"

size_t next_pow2(size_t x) {
    --x;
    x |= x >> 1;
    x |= x >> 2;
    x |= x >> 4;
    x |= x >> 8;
    x |= x >> 16;
    return ++x;
}

int is_pow2(size_t v) { return v && ((v & (v - 1)) == 0); }

size_t gcd(size_t a, size_t b) {
    if (b == 0) return a;
    return gcd(b, a % b);
}

cudaDeviceProp query_cuda_device() {
    int dev;
    if (cudaGetDevice(&dev) == cudaSuccess) {
        struct cudaDeviceProp props;
        cudaGetDeviceProperties(&props, dev);
        return props;
    }
    return cudaDeviceProp{};
}

int check_cuda_supported() {
    int devc;
    if (cudaGetDeviceCount(&devc) == cudaSuccess) {
        return (bool)devc > 0;
    }
    return 0;
}

cudaDeviceProp *CUDADevice::_properties = NULL;

__host__ cudaDeviceProp *CUDADevice::properties() {
    if (_properties == NULL) {
        cudaDeviceProp props = query_cuda_device();
        _properties = (cudaDeviceProp *)malloc(sizeof(cudaDeviceProp));
        memcpy(_properties, &props, sizeof(cudaDeviceProp));
    }
    return _properties;
}

__host__ void CUDAKernel::print_device_properties(cudaDeviceProp *props) {
    printf(
        "cuda_parstack[host]: max_threads_per_block=%d max_threads_per_sm=%d "
        "shared_mem_per_block=%zu "
        "shared_mem_per_sm=%zu multiprocessor_count=%d warp_size=%d\n",
        props->maxThreadsPerBlock, props->maxThreadsPerMultiProcessor,
        props->sharedMemPerBlock, props->sharedMemPerMultiprocessor,
        props->multiProcessorCount, props->warpSize);
}
