#include <stdio.h>

#include <cfloat>
#include <cstdint>
#include <limits>

#include "minmax.cuh"
#include "parstack.cuh"
#include "utils.cuh"
#if defined(_OPENMP)
#include <omp.h>
#endif
#include <thrust/reduce.h>

#define select_parstack_kernel_for_block_size(kernel, _block_size)          \
    {                                                                       \
        switch (_block_size) {                                              \
            case 1024:                                                      \
                kernel<T, 1024><<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                                      \
            case 512:                                                       \
                kernel<T, 512><<<_grid, _blocks, _shared_memory>>>(_args);  \
                break;                                                      \
            case 256:                                                       \
                kernel<T, 256><<<_grid, _blocks, _shared_memory>>>(_args);  \
                break;                                                      \
            case 128:                                                       \
                kernel<T, 128><<<_grid, _blocks, _shared_memory>>>(_args);  \
                break;                                                      \
            case 64:                                                        \
                kernel<T, 64><<<_grid, _blocks, _shared_memory>>>(_args);   \
                break;                                                      \
            case 32:                                                        \
                kernel<T, 32><<<_grid, _blocks, _shared_memory>>>(_args);   \
                break;                                                      \
            case 16:                                                        \
                kernel<T, 16><<<_grid, _blocks, _shared_memory>>>(_args);   \
                break;                                                      \
            case 8:                                                         \
                kernel<T, 8><<<_grid, _blocks, _shared_memory>>>(_args);    \
                break;                                                      \
            case 4:                                                         \
                kernel<T, 4><<<_grid, _blocks, _shared_memory>>>(_args);    \
                break;                                                      \
            case 2:                                                         \
                kernel<T, 2><<<_grid, _blocks, _shared_memory>>>(_args);    \
                break;                                                      \
            case 1:                                                         \
                kernel<T, 1><<<_grid, _blocks, _shared_memory>>>(_args);    \
                break;                                                      \
        }                                                                   \
    }

template <typename T>
struct parstack_kernel_arguments_t {
    size_t narrays;
    size_t nshifts;
    size_t nsamples;
    size_t lengthout;
    int32_t offsetout;
    size_t work_per_thread;
    T *weights;
    T *result;
    size_t *lengths;
    int32_t *shifts;
    int32_t *offsets;
    size_t pitchin;
    size_t pitchout;
    T *arrays;
};

template <typename T>
class ParstackCUDAKernel : public CUDAKernel {
   public:
    ParstackCUDAKernel(size_t _narrays, size_t _nshifts, size_t _nsamples,
                       size_t _lengthout, int32_t _offsetout, T **_arrays,
                       T *_weights, T *_result, size_t *_lengths,
                       int32_t *_offsets, int32_t *_shifts, uint8_t _method,
                       uint8_t _nparallel, size_t _work_per_thread,
                       size_t _target_block_threads, char **_err)
        : narrays(_narrays),
          nshifts(_nshifts),
          nsamples(_nsamples),
          lengthout(_lengthout),
          offsetout(_offsetout),
          arrays(_arrays),
          weights(_weights),
          result(_result),
          lengths(_lengths),
          offsets(_offsets),
          shifts(_shifts),
          method(_method),
          nparallel(_nparallel),
          CUDAKernel(_work_per_thread, _target_block_threads, _err) {}

    ParstackCUDAKernel(size_t narrays, size_t nshifts, size_t nsamples,
                       size_t lengthout, int32_t offsetout, T **arrays,
                       T *weights, T *result, size_t *lengths, int32_t *offsets,
                       int32_t *shifts, char **err)
        : ParstackCUDAKernel(narrays, nshifts, nsamples, lengthout, offsetout,
                             arrays, weights, result, lengths, offsets, shifts,
                             0, 1, 32, 256, err) {}

    ParstackCUDAKernel(T **arrays, parstack_kernel_arguments_t<T> args,
                       uint8_t method, char **err)

        : ParstackCUDAKernel(args.narrays, args.nshifts, args.nsamples,
                             args.lengthout, args.offsetout, arrays,
                             args.weights, args.result, args.lengths,
                             args.offsets, args.shifts, method, 1,
                             args.work_per_thread, 256, err) {}

    __host__ void launch_kernel(parstack_kernel_arguments_t<T> args) {
        debugAssert(
            0 < _block_size && _block_size <= 1024 && is_pow2(_block_size),
            "block_size must be power of two");
        launch_kernel(_grid, _blocks, _shared_memory, _block_size, args);
    }

    __host__ virtual void launch_kernel(
        dim3 _grid, dim3 _blocks, size_t _shared_memory,
        unsigned int _block_size, parstack_kernel_arguments_t<T> _args) = 0;

    __host__ virtual int launch() override {
        parstack_kernel_arguments_t<T> _args = {
            narrays : narrays,
            nshifts : nshifts,
            nsamples : nsamples,
            lengthout : lengthout,
            offsetout : offsetout,
            work_per_thread : work_per_thread,
        };
        args = _args;
        debugAssert(sizeof(args) < 256);

        nsamples = *thrust::max_element(lengths, lengths + narrays);
        args.nsamples = nsamples;

        calculate_kernel_parameters();

        cudaStream_t stream = NULL;

#if defined(CUDA_DEBUG)
        cudaEvent_t start, stop;
        cudaEventCreate(&start);
        cudaEventCreate(&stop);

        clock_t r_start = clock();
        cudaEventRecord(start);

        printf(
            "cuda_parstack[host]: narrays=%zu nshifts=%zu lengthout=%zu "
            "grid=(%u,%u,%u) "
            "blocks=(%u,%u,%u) (%zu threads) mem=%zu output=(%zu,%zu)\n",
            narrays, nshifts, lengthout, _grid.x, _grid.y, _grid.z, _blocks.x,
            _blocks.y, _blocks.z, (size_t)(_blocks.x * _blocks.y * _blocks.z),
            _shared_memory, nshifts, lengthout);
#endif

        size_t i;
        T *padded = (T *)calloc(nsamples * narrays, sizeof(T));
#if defined(_OPENMP)
#pragma omp parallel for private(i) num_threads(nparallel)
#endif
        for (i = 0; i < narrays; i++) {
            memcpy(padded + i * nsamples, arrays[i], lengths[i] * sizeof(T));
        }

#if defined(CUDA_DEBUG)
        printf("cuda_parstack[host]: data preparation done: %f sec\n",
               ((double)(clock() - r_start)) / CLOCKS_PER_SEC);
#endif

        cudaCheck(cudaMallocPitch((void **)&(args.arrays), &(args.pitchin),
                                  nsamples * sizeof(T), narrays),
                  "arrays: allocation failed", err);

        cudaCheck(
            cudaMalloc((void **)&(args.weights), nshifts * narrays * sizeof(T)),
            "weights: allocation failed", err);

        cudaCheck(cudaMallocPitch((void **)&(args.result), &(args.pitchout),
                                  lengthout * sizeof(T), nshifts),
                  "result: allocation failed", err);

        cudaCheck(cudaMemset2D(args.result, args.pitchout, 0,
                               lengthout * sizeof(T), nshifts),
                  "result: memset failed", err);

        cudaCheck(
            cudaMalloc((void **)&(args.offsets), narrays * sizeof(int32_t)),
            "offsets: allocation failed", err);

        cudaCheck(
            cudaMalloc((void **)&(args.lengths), narrays * sizeof(size_t)),
            "lengths: allocation failed", err);

        cudaCheck(cudaMalloc((void **)&(args.shifts),
                             nshifts * narrays * sizeof(int32_t)),
                  "shifts: allocation failed", err);

        cudaCheck(cudaMemcpy2DAsync(args.arrays, args.pitchin, padded,
                                    nsamples * sizeof(T), nsamples * sizeof(T),
                                    narrays, cudaMemcpyHostToDevice, stream),
                  "arrays: copy failed", err);

        cudaCheck(cudaMemcpyAsync(args.weights, weights,
                                  nshifts * narrays * sizeof(T),
                                  cudaMemcpyHostToDevice, stream),
                  "weights: copy failed", err);

        cudaCheck(
            cudaMemcpyAsync(args.offsets, offsets, narrays * sizeof(int32_t),
                            cudaMemcpyHostToDevice, stream),
            "offsets: copy failed", err);

        cudaCheck(
            cudaMemcpyAsync(args.lengths, lengths, narrays * sizeof(size_t),
                            cudaMemcpyHostToDevice, stream),
            "lengths: copy failed", err);

        cudaCheck(cudaMemcpyAsync(args.shifts, shifts,
                                  nshifts * narrays * sizeof(int32_t),
                                  cudaMemcpyHostToDevice, stream),
                  "shifts: copy to GPU failed", err);

        if (method == 0) {
            cudaCheck(
                cudaMemcpy2DAsync(args.result, args.pitchout, result,
                                  lengthout * sizeof(T), lengthout * sizeof(T),
                                  nshifts, cudaMemcpyHostToDevice, stream),
                "result: copy to GPU failed", err);
        }

        free(padded);

#if defined(CUDA_DEBUG)
        printf("cuda_parstack[host]: copy to GPU done: %f sec\n",
               ((double)(clock() - r_start)) / CLOCKS_PER_SEC);
#endif

        launch_kernel(args);
        cudaCheckLastError("launching the parstack kernel failed", err);
#if defined(CUDA_DEBUG)
        printf("cuda_parstack[host]: kernel invocation done: %f sec\n",
               ((double)(clock() - r_start)) / CLOCKS_PER_SEC);
#endif

        if (method == 1) {
            // compute the maximum values in dimension 1
            // this could easily be swapped out with the CPU version
            // but since the data is already in GPU memory we avoid the copy
            const size_t rows = nshifts;
            const size_t cols = lengthout;
            minmax_kernel_arguments_t<size_t, T> max_args = {
                axis : 1,
                type : MAX,
                rows : rows,
                cols : cols,
                work_per_thread : 1,
                array : args.result,  // already in GPU memory
                iarrayout : NULL,
                varrayout : NULL,
                pitchin : args.pitchout,
            };

            cudaCheck(
                cudaMalloc((void **)&(max_args.varrayout), rows * sizeof(T)),
                "maxresult: allocation failed", err);

            auto max_kernel =
                ReductionMinMaxCUDAKernel<size_t, T>::make(max_args, err);
            max_kernel->calculate_kernel_parameters();
            max_kernel->launch_kernel(max_args);

            cudaCheck(cudaMemcpy(result, max_args.varrayout, rows * sizeof(T),
                                 cudaMemcpyDeviceToHost),
                      "maxresult: copy back failed", err);
            debugAssert(cudaFree(max_args.varrayout) == cudaSuccess);

        } else {
            cudaCheck(cudaMemcpy2D(result, lengthout * sizeof(T), args.result,
                                   args.pitchout, lengthout * sizeof(T),
                                   nshifts, cudaMemcpyDeviceToHost),
                      "result: copy back failed", err);
        }

#if defined(CUDA_DEBUG)
        cudaEventRecord(stop);
        cudaEventSynchronize(stop);
        float milliseconds;
        cudaEventElapsedTime(&milliseconds, start, stop);

        size_t transferred = narrays * lengthout * nshifts * sizeof(T);
        printf(
            "cuda_parstack[host]: compute and copy back done: %f sec (%f sec "
            "total, %f GB %f GB/s bandwidth)\n",
            ((double)(clock() - r_start)) / CLOCKS_PER_SEC, milliseconds / 1e3,
            transferred / 1e9, transferred / 1e9 / milliseconds / 1e3);

        cudaEventDestroy(start);
        cudaEventDestroy(stop);
#endif

        debugAssert(cudaFree(args.lengths) == cudaSuccess);
        debugAssert(cudaFree(args.arrays) == cudaSuccess);
        debugAssert(cudaFree(args.weights) == cudaSuccess);
        debugAssert(cudaFree(args.result) == cudaSuccess);
        debugAssert(cudaFree(args.offsets) == cudaSuccess);
        debugAssert(cudaFree(args.shifts) == cudaSuccess);

        return SUCCESS;
    };

   public:
    T **arrays, *weights, *result;
    size_t *lengths;
    int32_t *offsets, *shifts;

    size_t narrays, nshifts, nsamples, lengthout;
    int32_t offsetout;
    uint8_t method, nparallel;

   protected:
    parstack_kernel_arguments_t<T> args{parstack_kernel_arguments_t<T>{}};
};

template <typename T, unsigned int block_size>
__global__ void parstack_atomic_kernel(parstack_kernel_arguments_t<T> args) {
#ifdef __CUDA_ARCH__
#if (__CUDA_ARCH__ >= 600)
    unsigned int shift_idx = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned int arr_idx = blockIdx.y * blockDim.y + threadIdx.y;
    unsigned int sample_idx =
        args.work_per_thread * blockIdx.z * blockDim.z + threadIdx.z;

    if (shift_idx < args.nshifts && arr_idx < args.narrays &&
        sample_idx < args.nsamples) {
        const T weight = args.weights[shift_idx * args.narrays + arr_idx];
        int32_t istart = args.offsets[arr_idx] +
                         args.shifts[shift_idx * args.narrays + arr_idx];
        if (weight != 0.0) {
            T *result = (T *)((char *)args.result + shift_idx * args.pitchout);
            T *array = (T *)((char *)args.arrays + arr_idx * args.pitchin);
            size_t start = max((int32_t)0, args.offsetout - istart);
            size_t end =
                max((size_t)0, min(args.lengthout - istart + args.offsetout,
                                   args.lengths[arr_idx]));
            size_t i = start + sample_idx;
            for (; i < min(end, start + sample_idx + args.work_per_thread); i++)
                atomicAdd_system(&result[istart - args.offsetout + i],
                                 array[i] * weight);
        }
    }
#endif
#endif
}

template <class T>
class AtomicParstackCUDAKernel : public ParstackCUDAKernel<T> {
    using ParstackCUDAKernel<T>::ParstackCUDAKernel;

   public:
    size_t shared_memory_per_thread{0};

    __host__ static std::unique_ptr<ParstackCUDAKernel<T>> make(
        T **arrays, parstack_kernel_arguments_t<T> args, uint8_t method,
        char **err) {
        return std::make_unique<AtomicParstackCUDAKernel<T>>(arrays, args,
                                                             method, err);
    }

    __host__ void launch_kernel(dim3 _grid, dim3 _blocks, size_t _shared_memory,
                                unsigned int _block_size,
                                parstack_kernel_arguments_t<T> _args) {
        select_parstack_kernel_for_block_size(parstack_atomic_kernel,
                                              _block_size);
    }

    __host__ bool is_compatible() {
        return CUDADevice::properties()->major >= 6;
    }

    __host__ void calculate_kernel_parameters() {
        cudaDeviceProp *limits = CUDADevice::properties();
#if defined(CUDA_DEBUG)
        this->print_device_properties(limits);
#endif
        this->target_block_threads = next_pow2(this->target_block_threads);
        this->target_block_threads =
            min(this->target_block_threads, (size_t)limits->maxThreadsPerBlock);
        const unsigned int threads_per_block =
            limits->warpSize *
            gcd(this->target_block_threads / limits->warpSize,
                limits->maxThreadsPerMultiProcessor / limits->warpSize);

        unsigned int bshifts = next_pow2(this->args.nshifts);
        bshifts = min(bshifts, threads_per_block);
        bshifts = min(bshifts, limits->maxThreadsDim[0]);

        unsigned int barrays = threads_per_block / bshifts;
        barrays = min((size_t)barrays, next_pow2(this->args.narrays));
        barrays = min(barrays, limits->maxThreadsDim[1]);

        unsigned int bsamples = threads_per_block / (barrays * bshifts);
        bsamples = min((size_t)bsamples,
                       next_pow2(ceil((float)this->args.nsamples /
                                      (float)this->args.work_per_thread)));
        bsamples = min(bsamples, limits->maxThreadsDim[2]);

        this->_blocks = dim3(bshifts, barrays, bsamples);
        this->_block_size = this->_blocks.x;
        this->_grid = dim3(
            (unsigned int)ceil((float)this->args.nshifts / (float)bshifts),
            (unsigned int)ceil((float)this->args.narrays / (float)barrays),
            (unsigned int)ceil((float)this->args.nsamples /
                               (float)(bsamples * this->args.work_per_thread)));
        this->_shared_memory = 0;
    }
};

template <typename T, unsigned int block_size>
__global__ void parstack_reduction_kernel(parstack_kernel_arguments_t<T> args) {
    // shared memory that is used for partial results during reduction
    // because the kernel is templated, the type of the shared memory is
    // dynamically casted
    extern __shared__ __align__(sizeof(T)) unsigned char _partials[];
    T *partials = reinterpret_cast<T *>(_partials);

    const unsigned int arr_tid = threadIdx.x;
    const unsigned int shift_tid = threadIdx.y;
    const unsigned int lengthout_tid = threadIdx.z;

    unsigned int arr_idx = blockIdx.x * (block_size * 2) + arr_tid;
    const unsigned int shift_idx = blockIdx.y * blockDim.y + threadIdx.y;
    const unsigned int lengthout_idx = blockIdx.z * blockDim.z + threadIdx.z;

    const unsigned int offset =
        (lengthout_tid * blockDim.y * block_size) + shift_tid * block_size;
    const unsigned int grid_size = block_size * gridDim.x;

    T acc = 0;
    while (shift_idx < args.nshifts && lengthout_idx < args.lengthout &&
           arr_idx < args.narrays) {
        const int32_t offset = args.offsets[arr_idx];
        const int32_t shift = args.shifts[shift_idx * args.narrays + arr_idx];
        const T weight = args.weights[shift_idx * args.narrays + arr_idx];
        const int32_t istart = offset + shift;
        const int istart_r = istart - args.offsetout;
        const unsigned int idx = lengthout_idx - istart_r;
        if (weight != 0.0 && idx < args.nsamples) {
            T *array = (T *)((char *)args.arrays + arr_idx * args.pitchin);
            acc += array[idx] * weight;
        }
        arr_idx += grid_size;
    }

    partials[offset + arr_tid] = acc;
    __syncthreads();

    if (block_size >= 1024) {
        if (arr_tid < 512) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 512];
        }
        __syncthreads();
    }
    if (block_size >= 512) {
        if (arr_tid < 256) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 256];
        }
        __syncthreads();
    }
    if (block_size >= 256) {
        if (arr_tid < 128) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 128];
        }
        __syncthreads();
    }
    if (block_size >= 128) {
        if (arr_tid < 64) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 64];
        }
        __syncthreads();
    }
    if (block_size >= 64) {
        if (arr_tid < 32) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 32];
        }
        __syncthreads();
    }
    if (block_size >= 32) {
        if (arr_tid < 16) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 16];
        }
        __syncthreads();
    }
    if (block_size >= 16) {
        if (arr_tid < 8) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 8];
        }
        __syncthreads();
    }
    if (block_size >= 8) {
        if (arr_tid < 4) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 4];
        }
        __syncthreads();
    }
    if (block_size >= 4) {
        if (arr_tid < 2) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 2];
        }
        __syncthreads();
    }
    if (block_size >= 2) {
        if (arr_tid < 1) {
            partials[offset + arr_tid] += partials[offset + arr_tid + 1];
        }
        __syncthreads();
    }

    T *result = (T *)((char *)args.result + shift_idx * args.pitchout);
    if (shift_idx < args.nshifts && lengthout_idx < args.lengthout &&
        arr_tid == 0)
        result[lengthout_idx] += partials[offset];
}

template <class T>
class ReductionParstackCUDAKernel : public ParstackCUDAKernel<T> {
    using ParstackCUDAKernel<T>::ParstackCUDAKernel;

   public:
    __host__ static std::unique_ptr<ParstackCUDAKernel<T>> make(
        T **arrays, parstack_kernel_arguments_t<T> args, uint8_t method,
        char **err) {
        return std::make_unique<ReductionParstackCUDAKernel<T>>(arrays, args,
                                                                method, err);
    }

    __host__ void launch_kernel(dim3 _grid, dim3 _blocks, size_t _shared_memory,
                                unsigned int _block_size,
                                parstack_kernel_arguments_t<T> _args) {
        select_parstack_kernel_for_block_size(parstack_reduction_kernel,
                                              _block_size);
    }

    __host__ bool is_compatible() { return true; }

    __host__ void calculate_kernel_parameters() {
        cudaDeviceProp *limits = CUDADevice::properties();
        this->shared_memory_per_thread = sizeof(T);
#if defined(CUDA_DEBUG)
        this->print_device_properties(limits);
#endif

        this->target_block_threads = next_pow2(this->target_block_threads);
        this->target_block_threads =
            min(this->target_block_threads, (size_t)limits->maxThreadsPerBlock);
        this->target_block_threads =
            min(this->target_block_threads,
                next_pow2(limits->sharedMemPerBlock /
                          this->shared_memory_per_thread) /
                    2);
        this->target_block_threads =
            min(this->target_block_threads,
                next_pow2(limits->sharedMemPerMultiprocessor /
                          limits->multiProcessorCount) /
                    2);
        const unsigned int threads_per_block =
            limits->warpSize *
            gcd(this->target_block_threads / limits->warpSize,
                limits->maxThreadsPerMultiProcessor / limits->warpSize);

        unsigned int barrays = next_pow2(this->narrays);
        barrays = min(barrays, threads_per_block);
        barrays = min(barrays, limits->maxThreadsDim[0]);

        unsigned int bshifts = threads_per_block / barrays;
        bshifts = min((size_t)bshifts, next_pow2(this->nshifts));
        bshifts = min(bshifts, limits->maxThreadsDim[1]);
        bshifts =
            min((size_t)bshifts,
                next_pow2(limits->sharedMemPerBlock /
                          (max(32, barrays) * this->shared_memory_per_thread)) /
                    2);

        unsigned int blengthout = threads_per_block / (barrays * bshifts);
        blengthout = min((size_t)blengthout, next_pow2(this->lengthout));
        blengthout = min(blengthout, limits->maxThreadsDim[2]);
        blengthout = min((size_t)blengthout,
                         next_pow2(limits->sharedMemPerBlock /
                                   (max(32, barrays) * bshifts *
                                    this->shared_memory_per_thread)) /
                             2);

        this->_blocks = dim3(barrays, bshifts, blengthout);
        this->_block_size = this->_blocks.x;
        this->_grid =
            dim3(1, (size_t)ceil((float)this->nshifts / (float)bshifts),
                 (size_t)ceil((float)this->lengthout / (float)blengthout));
        this->_shared_memory = max(32, barrays) * bshifts * blengthout *
                               this->shared_memory_per_thread;
    }
};

template <typename T>
using ParstackKernelFactory = std::unique_ptr<ParstackCUDAKernel<T>> (*)(
    T **arrays, parstack_kernel_arguments_t<T>, uint8_t, char **);

template <typename T>
ParstackKernelFactory<T> select_parstack_kernel_implementation(impl_t impl) {
    ParstackKernelFactory<T> kernel_impl = NULL;
    switch (impl) {
        case IMPL_CUDA_ATOMIC:
            kernel_impl = AtomicParstackCUDAKernel<T>::make;
            break;
        default:
            kernel_impl = ReductionParstackCUDAKernel<T>::make;
            break;
    }
    return kernel_impl;
}

int check_cuda_parstack_implementation_compatibility(impl_t impl,
                                                     int *compatible,
                                                     char **err) {
    ParstackKernelFactory<float> factory =
        select_parstack_kernel_implementation<float>(impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", err);
    auto kernel = factory(NULL, parstack_kernel_arguments_t<float>{}, 0, err);
    *compatible = kernel->is_compatible();
    return SUCCESS;
}

int calculate_cuda_parstack_kernel_parameters(
    impl_t impl, size_t narrays, size_t nshifts, size_t nsamples,
    size_t lengthout, int32_t offsetout, size_t target_block_threads,
    size_t work_per_thread, size_t shared_memory_per_thread,
    unsigned int grid[3], unsigned int blocks[3], size_t *shared_memory,
    char **err) {
    parstack_kernel_arguments_t<float> args = {
        narrays : narrays,
        nshifts : nshifts,
        nsamples : nsamples,
        lengthout : lengthout,
        offsetout : offsetout,
        work_per_thread : work_per_thread,
    };
    ParstackKernelFactory<float> factory =
        select_parstack_kernel_implementation<float>(impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", err);
    auto kernel = factory(NULL, args, 0, err);
    kernel->target_block_threads = target_block_threads;
    kernel->shared_memory_per_thread = shared_memory_per_thread;
    kernel->calculate_kernel_parameters();
    *shared_memory = kernel->shared_memory();
    grid[0] = kernel->grid().x;
    grid[1] = kernel->grid().y;
    grid[2] = kernel->grid().z;
    blocks[0] = kernel->blocks().x;
    blocks[1] = kernel->blocks().y;
    blocks[2] = kernel->blocks().z;
    return SUCCESS;
}

template <typename T>
int cuda_parstack(T **arrays, T *weights, T *result,
                  parstack_arguments_t args) {
    parstack_kernel_arguments_t<T> kernel_args = {
        narrays : args.narrays,
        nshifts : args.nshifts,
        nsamples : 0,  // computed
        lengthout : args.lengthout,
        offsetout : args.offsetout,
        work_per_thread : 32,
        weights : weights,
        result : result,
        lengths : args.lengths,
        shifts : args.shifts,
        offsets : args.offsets
    };
    ParstackKernelFactory<T> factory =
        select_parstack_kernel_implementation<T>(args.impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", args.err);
    auto kernel = factory(arrays, kernel_args, args.method, args.err);
    if (!kernel->is_compatible())
        EXIT_DEBUG("CUDA implementation incompatible with available hardware",
                   args.err);
    return kernel->launch();
}

int cuda_parstack_float(float **arrays, float *weights, float *result,
                        parstack_arguments_t args) {
    return cuda_parstack<float>(arrays, weights, result, args);
}

int cuda_parstack_double(double **arrays, double *weights, double *result,
                         parstack_arguments_t args) {
    return cuda_parstack<double>(arrays, weights, result, args);
}
