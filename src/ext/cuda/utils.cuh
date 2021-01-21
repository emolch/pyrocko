#pragma once

#define SUCCESS 0
#define NODATA 1
#define INVALID 2
#define ERROR 3

#define CUDA_COMPILED_FLAG "CUDA_COMPILED"

#ifdef __cplusplus
#include <assert.h>
#include <stdio.h>
#define UNUSED(x) [&x] {}()
#define EXTERNC extern "C"

#define EXIT_DEBUG(msg, err) \
    return handle_error(ERROR, msg, err, __FILE__, __LINE__);
#define cudaCheck(code, msg, err)                                         \
    do {                                                                  \
        if (code != cudaSuccess) {                                        \
            return handle_cuda_error(code, msg, err, __FILE__, __LINE__); \
        }                                                                 \
    } while (0)
#define cudaCheckLastError(msg, err) \
    { cudaCheck(cudaGetLastError(), msg, err); }

inline int handle_error(int code, const char *msg, char **err,
                        const char *fname, const size_t line) {
#if defined(CUDA_DEBUG)
    const char *format = "%s at %s:%d\n";
    const size_t len = snprintf(NULL, 0, format, msg, fname, line);
    char *err_msg = (char *)malloc(sizeof(char) * (len + 1));
    snprintf(err_msg, len + 1, format, msg, fname, line);
#else
    char *err_msg = (char *)malloc(sizeof(char) * (strlen(msg) + 1));
    strcpy(err_msg, msg);
#endif
    fprintf(stderr, "Fatal error: %s\n", err_msg);
    *err = err_msg;
    return code;
}

inline int handle_cuda_error(cudaError_t code, const char *msg, char **err,
                             const char *fname, const size_t line) {
    const char *format = "%s (%s)\n";
    const size_t len = snprintf(NULL, 0, format, msg, cudaGetErrorString(code));
    char *err_msg = (char *)malloc(sizeof(char) * (len + 1));
    snprintf(err_msg, len + 1, format, msg, cudaGetErrorString(code));
    return handle_error(ERROR, err_msg, err, fname, line);
}

#define ASSERT(expr, msg) assert(((void)(msg), (expr)))

inline void debugAssert(int result, const char *msg) {
#if defined(CUDA_DEBUG)
    ASSERT(msg, result);
#endif
}

inline void debugAssert(int result) {
#if defined(CUDA_DEBUG)
    ASSERT("assertion failed", result);
#endif
}

class CUDADevice {
   public:
    static cudaDeviceProp *properties();

   private:
    static cudaDeviceProp *_properties;
    CUDADevice(){};
    ~CUDADevice() {
        if (_properties != NULL) free(_properties);
    }

   public:
    CUDADevice(CUDADevice const &) = delete;
    void operator=(CUDADevice const &) = delete;
};

class CUDAKernel {
   protected:
    dim3 _grid, _blocks;
    size_t _shared_memory;
    unsigned int _block_size;

   public:
    size_t target_block_threads, work_per_thread, shared_memory_per_thread;
    char **err;

    CUDAKernel(size_t _work_per_thread, size_t _target_block_threads,
               char **_err)
        : work_per_thread(_work_per_thread),
          target_block_threads(_target_block_threads),
          err(_err) {}

    CUDAKernel(char **err) : CUDAKernel(32, 256, err) {}

    __host__ virtual void calculate_kernel_parameters() = 0;

    __host__ virtual bool is_compatible() = 0;

    __host__ virtual int launch() = 0;

    __host__ dim3 grid() { return _grid; }
    __host__ dim3 blocks() { return _blocks; }
    __host__ size_t shared_memory() { return _shared_memory; }

    __host__ void print_device_properties(cudaDeviceProp *props);
};

#else
#define EXTERNC
#endif

typedef enum {
    IMPL_NP = 0,
    IMPL_OMP = 1,
    IMPL_CUDA = 2,
    IMPL_CUDA_THRUST = 3,
    IMPL_CUDA_ATOMIC = 4,
} impl_t;

EXTERNC size_t next_pow2(size_t x);

EXTERNC int is_pow2(size_t x);

EXTERNC size_t gcd(size_t a, size_t b);

EXTERNC int check_cuda_supported();
#undef EXTERNC
