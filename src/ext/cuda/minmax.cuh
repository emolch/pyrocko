#pragma once
#include "utils.cuh"

typedef enum {
    ARGMAX = 0,
    ARGMIN = 1,
    MAX = 2,
    MIN = 3,
} minmax_type_t;

#ifdef __cplusplus
#include <cstdint>
#include <memory>

#include "limits.cuh"
#define EXTERNC extern "C"

#define select_minmax_kernel_for_block_size(kernel, _block_size) \
    {                                                            \
        switch (_block_size) {                                   \
            case 1024:                                           \
                kernel<I, V, type, axis, 1024>                   \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 512:                                            \
                kernel<I, V, type, axis, 512>                    \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 256:                                            \
                kernel<I, V, type, axis, 256>                    \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 128:                                            \
                kernel<I, V, type, axis, 128>                    \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 64:                                             \
                kernel<I, V, type, axis, 64>                     \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 32:                                             \
                kernel<I, V, type, axis, 32>                     \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 16:                                             \
                kernel<I, V, type, axis, 16>                     \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 8:                                              \
                kernel<I, V, type, axis, 8>                      \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 4:                                              \
                kernel<I, V, type, axis, 4>                      \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 2:                                              \
                kernel<I, V, type, axis, 2>                      \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
            case 1:                                              \
                kernel<I, V, type, axis, 1>                      \
                    <<<_grid, _blocks, _shared_memory>>>(_args); \
                break;                                           \
        }                                                        \
    }

template <typename I, typename V>
struct minmax_kernel_arguments_t {
    uint8_t axis;
    minmax_type_t type;
    size_t rows;
    size_t cols;
    size_t work_per_thread;
    V *array;
    I *iarrayout;
    V *varrayout;
    size_t pitchin;
    size_t pitchout;
};

template <typename I, typename V>
class MinMaxCUDAKernel : public CUDAKernel {
    using CUDAKernel::CUDAKernel;

   protected:
    minmax_kernel_arguments_t<I, V> args{minmax_kernel_arguments_t<I, V>{}};

   public:
    V *array, *varrayout;
    I *iarrayout;
    uint8_t axis;
    minmax_type_t type;
    size_t rows, cols;

    MinMaxCUDAKernel(V *_array, I *_iarrayout, V *_varrayout,
                     const uint8_t _axis, const minmax_type_t _type,
                     const size_t _cols, const size_t _rows,
                     size_t _work_per_thread, size_t _target_block_threads,
                     char **_err)
        : array(_array),
          iarrayout(_iarrayout),
          varrayout(_varrayout),
          axis(_axis),
          type(_type),
          cols(_cols),
          rows(_rows),
          CUDAKernel(_work_per_thread, _target_block_threads, _err) {}

    MinMaxCUDAKernel(V *array, I *iarrayout, V *varrayout, const uint8_t axis,
                     const minmax_type_t type, const size_t cols,
                     const size_t rows, char **err)
        : MinMaxCUDAKernel(array, iarrayout, varrayout, axis, type, cols, rows,
                           32, 256, err) {}

    MinMaxCUDAKernel(minmax_kernel_arguments_t<I, V> args, char **err)
        : MinMaxCUDAKernel(args.array, args.iarrayout, args.varrayout,
                           args.axis, args.type, args.cols, args.rows,
                           args.work_per_thread, 256, err) {}

    __host__ void launch_kernel(minmax_kernel_arguments_t<I, V> args) {
#if defined(CUDA_DEBUG)
        printf(
            "cuda_minmax[host]: cols=%zu rows=%zu grid=(%u,%u) "
            "blocks=(%u,%u) (%zu threads) mem=%zu\n",
            args.cols, args.rows, _grid.x, _grid.y, _blocks.x, _blocks.y,
            (size_t)(_blocks.x * _blocks.y * _blocks.z), _shared_memory);
#endif
        debugAssert(
            0 < _block_size && _block_size <= 1024 && is_pow2(_block_size),
            "block_size must be power of two");
        launch_kernel(_grid, _blocks, _shared_memory, _block_size, args);
    };

    __host__ int launch() override {
        minmax_kernel_arguments_t<I, V> _args = {
            axis : axis,
            type : type,
            rows : rows,
            cols : cols,
            work_per_thread : work_per_thread
        };
        args = _args;
        debugAssert(sizeof(args) < 256);

        size_t out_size = (axis == 0) ? args.cols : args.rows;

#if defined(CUDA_DEBUG)
        cudaEvent_t start, stop;
        cudaEventCreate(&start);
        cudaEventCreate(&stop);

        clock_t r_start = clock();
        cudaEventRecord(start);
#endif

        if (type == ARGMAX || type == ARGMIN) {
            cudaCheck(
                cudaMalloc((void **)&(args.iarrayout), out_size * sizeof(I)),
                "iarrayout: allocation failed", err);
        } else {
            cudaCheck(
                cudaMalloc((void **)&(args.varrayout), out_size * sizeof(V)),
                "varrayout: allocation failed", err);
        };

        cudaCheck(cudaMallocPitch((void **)&(args.array), &(args.pitchin),
                                  args.cols * sizeof(V), args.rows),
                  "array: device allocation failed", err);

        /* this memcopy operation is the bottleneck of the system, e.g. a
         * 10000x10000 matrix of doubles (~800MB) */
        /* takes about 0.15 seconds to copy to the device and there is nothing
         * we can do to speed that up (pinning host memory increases transfer
         * speed but is not feasible) */
        cudaCheck(cudaMemcpy2D(args.array, args.pitchin, array,
                               args.cols * sizeof(V), args.cols * sizeof(V),
                               args.rows, cudaMemcpyHostToDevice),
                  "array: copy failed", err);

#if defined(CUDA_DEBUG)
        printf("cuda_minmax[host]: copy to GPU done: %f sec\n",
               ((double)(clock() - r_start)) / CLOCKS_PER_SEC);
#endif

        calculate_kernel_parameters();
        launch_kernel(args);
        if (type == ARGMAX || type == ARGMIN) {
            cudaCheck(cudaMemcpy(iarrayout, args.iarrayout,
                                 out_size * sizeof(I), cudaMemcpyDeviceToHost),
                      "iarrayout: copy back failed", err);
        } else {
            cudaCheck(
                cudaMemcpyAsync(varrayout, args.varrayout, out_size * sizeof(V),
                                cudaMemcpyDeviceToHost),
                "varrayout: copy back failed", err);
        }

#if defined(CUDA_DEBUG)
        cudaEventRecord(stop);
        cudaEventSynchronize(stop);
        float milliseconds;
        cudaEventElapsedTime(&milliseconds, start, stop);

        size_t transferred = args.cols * args.rows * sizeof(V);
        printf(
            "cuda_max[host]: compute and copy back done: %f sec (%f sec "
            "total, %f GB %f GB/s bandwidth)\n",
            ((double)(clock() - r_start)) / CLOCKS_PER_SEC, milliseconds / 1e3,
            transferred / 1e9, transferred / 1e9 / milliseconds / 1e3);

        cudaEventDestroy(start);
        cudaEventDestroy(stop);
#endif

        debugAssert(cudaFree(args.array) == cudaSuccess);
        if (type == ARGMAX || type == ARGMIN) {
            debugAssert(cudaFree(args.iarrayout) == cudaSuccess);
        } else {
            debugAssert(cudaFree(args.varrayout) == cudaSuccess);
        }
        return SUCCESS;
    }

    __host__ virtual void launch_kernel(
        dim3 _grid, dim3 _blocks, size_t _shared_memory,
        unsigned int _block_size, minmax_kernel_arguments_t<I, V> _args) = 0;

    __host__ virtual bool is_compatible() = 0;

    __host__ virtual void calculate_kernel_parameters() = 0;
};

template <typename I, typename V>
struct indexed_elem_t {
    I idx;
    V val;
};

template <typename I, typename V, minmax_type_t type>
__device__ __forceinline__ void minmax_idx(volatile indexed_elem_t<I, V> *sdata,
                                           unsigned int tid1,
                                           unsigned int tid2) {
    bool tid2_smaller = sdata[tid2].val < sdata[tid1].val;
    bool equal_but_tid2_smaller_idx =
        sdata[tid2].val == sdata[tid1].val && sdata[tid2].idx < sdata[tid1].idx;

    bool swap;
    if (type == MAX || type == ARGMAX) {
        swap =
            (sdata[tid2].val > sdata[tid1].val) || equal_but_tid2_smaller_idx;
    } else {
        swap =
            (sdata[tid2].val < sdata[tid1].val) || equal_but_tid2_smaller_idx;
    }
    if (swap) {
        sdata[tid1].idx = sdata[tid2].idx;
        sdata[tid1].val = sdata[tid2].val;
    }
}

template <typename I, typename V, minmax_type_t type, unsigned int block_size>
__device__ __forceinline__ void minmax_warp_reduce(
    volatile indexed_elem_t<I, V> *sdata, unsigned int tid) {
    if (block_size >= 64) minmax_idx<I, V, type>(sdata, tid, tid + 32);
    if (block_size >= 32) minmax_idx<I, V, type>(sdata, tid, tid + 16);
    if (block_size >= 16) minmax_idx<I, V, type>(sdata, tid, tid + 8);
    if (block_size >= 8) minmax_idx<I, V, type>(sdata, tid, tid + 4);
    if (block_size >= 4) minmax_idx<I, V, type>(sdata, tid, tid + 2);
    if (block_size >= 2) minmax_idx<I, V, type>(sdata, tid, tid + 1);
}

template <typename I, typename V, minmax_type_t type, uint8_t axis,
          unsigned int block_size>
__global__ void minmax_reduction_kernel(minmax_kernel_arguments_t<I, V> args) {
    // shared memory that is used for partial results during reduction
    // because the kernel is templated, the type of the shared memory is
    // dynamically casted
    extern __shared__ __align__(
        sizeof(indexed_elem_t<I, V>)) unsigned char _sdata[];
    indexed_elem_t<I, V> *sdata =
        reinterpret_cast<indexed_elem_t<I, V> *>(_sdata);

    const unsigned int xtid = threadIdx.x;
    const unsigned int ytid = threadIdx.y;
    const unsigned int y = blockIdx.y * blockDim.y + ytid;
    const unsigned int x = blockIdx.x * blockDim.x + xtid;
    const unsigned int out_idx = (axis == 0) ? x : y;

    unsigned int rdc_idx;
    unsigned int rdc_max, rdc_tid, offset, grid_size;
    if (axis == 0) {
        rdc_idx = blockIdx.y * (block_size * 2) + ytid;
        rdc_max = args.rows;
        rdc_tid = ytid;
        offset = xtid * block_size;
        grid_size = block_size * gridDim.y;
    } else {
        rdc_idx = blockIdx.x * (block_size * 2) + xtid;
        rdc_max = args.cols;
        rdc_tid = xtid;
        offset = ytid * block_size;
        grid_size = block_size * gridDim.x;
    }

#if defined(CUDA_DEBUG)
    if (x == 0 && y == 0 && rdc_tid == 0)
        printf("cuda_max[ dev]: x=%u y=%u type=%d axis=%d\n", x, y, type, axis);
#endif

    I starti = 0;
    V startv;
    if (type == ARGMAX || type == MAX)
        startv = cuda::numeric_limits<V>::min();
    else
        startv = cuda::numeric_limits<V>::max();

    while (x < args.cols && y < args.rows && rdc_idx < rdc_max) {
        V value;
        if (axis == 0) {
            V *array = (V *)((char *)args.array + rdc_idx * args.pitchin);
            value = array[x];
        } else {
            V *array = (V *)((char *)args.array + y * args.pitchin);
            value = array[rdc_idx];
        }

        bool update = (type == ARGMAX || type == MAX) ? (value > startv)
                                                      : (value < startv);
        if (update) {
            startv = value;
            starti = rdc_idx;
        };
        rdc_idx += grid_size;
    }

    sdata[offset + rdc_tid].idx = starti;
    sdata[offset + rdc_tid].val = startv;
    __syncthreads();

    if (block_size >= 1024) {
        if (rdc_tid < 512) {
            minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                   offset + rdc_tid + 512);
        }
        __syncthreads();
    }
    if (block_size >= 512) {
        if (rdc_tid < 256) {
            minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                   offset + rdc_tid + 256);
        }
        __syncthreads();
    }
    if (block_size >= 256) {
        if (rdc_tid < 128) {
            minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                   offset + rdc_tid + 128);
        }
        __syncthreads();
    }
    if (block_size >= 128) {
        if (rdc_tid < 64) {
            minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                   offset + rdc_tid + 64);
        }
        __syncthreads();
    }
    if (blockDim.x > 1) {
        if (block_size >= 64) {
            if (rdc_tid < 32) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 32);
            }
            __syncthreads();
        }
        if (block_size >= 32) {
            if (rdc_tid < 16) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 16);
            }
            __syncthreads();
        }
        if (block_size >= 16) {
            if (rdc_tid < 8) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 8);
            }
            __syncthreads();
        }
        if (block_size >= 8) {
            if (rdc_tid < 4) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 4);
            }
            __syncthreads();
        }
        if (block_size >= 4) {
            if (rdc_tid < 2) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 2);
            }
            __syncthreads();
        }
        if (block_size >= 2) {
            if (rdc_tid < 1) {
                minmax_idx<I, V, type>(sdata, offset + rdc_tid,
                                       offset + rdc_tid + 1);
            }
        }
    } else if (rdc_tid < 32) {
        minmax_warp_reduce<I, V, type, block_size>(sdata, offset + rdc_tid);
    }
    if (x < args.cols && y < args.rows && rdc_tid == 0) {
        if (type == ARGMAX || type == ARGMIN)
            args.iarrayout[out_idx] = sdata[offset].idx;
        else
            args.varrayout[out_idx] = sdata[offset].val;
    }
}

template <typename I, typename V>
class ReductionMinMaxCUDAKernel : public MinMaxCUDAKernel<I, V> {
    using MinMaxCUDAKernel<I, V>::MinMaxCUDAKernel;

   public:
    __host__ static std::unique_ptr<MinMaxCUDAKernel<I, V>> make(
        minmax_kernel_arguments_t<I, V> args, char **err) {
        return std::make_unique<ReductionMinMaxCUDAKernel<I, V>>(args, err);
    };

    template <minmax_type_t type, uint8_t axis>
    __host__ void launch_minmax_kernel(dim3 _grid, dim3 _blocks,
                                       size_t _shared_memory,
                                       unsigned int _block_size,
                                       minmax_kernel_arguments_t<I, V> _args) {
        select_minmax_kernel_for_block_size(minmax_reduction_kernel,
                                            _block_size);
    }

    __host__ virtual void launch_kernel(dim3 _grid, dim3 _blocks,
                                        size_t _shared_memory,
                                        unsigned int _block_size,
                                        minmax_kernel_arguments_t<I, V> _args) {
        switch (this->axis) {
            case 0:
                switch (this->type) {
                    case ARGMIN:
                        return launch_minmax_kernel<ARGMIN, 0>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    case ARGMAX:
                        return launch_minmax_kernel<ARGMAX, 0>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    case MIN:
                        return launch_minmax_kernel<MIN, 0>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    default:
                        return launch_minmax_kernel<MAX, 0>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                }
            default:
                switch (this->type) {
                    case ARGMIN:
                        return launch_minmax_kernel<ARGMIN, 1>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    case ARGMAX:
                        return launch_minmax_kernel<ARGMAX, 1>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    case MIN:
                        return launch_minmax_kernel<MIN, 1>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                    default:
                        return launch_minmax_kernel<MAX, 1>(
                            _grid, _blocks, _shared_memory, _block_size, _args);
                }
        }
    }

    __host__ bool is_compatible() { return true; }

    __host__ void calculate_kernel_parameters() {
        cudaDeviceProp *limits = CUDADevice::properties();
        this->shared_memory_per_thread = sizeof(indexed_elem_t<I, V>);

#if defined(CUDA_DEBUG)
        this->print_device_properties(limits);
#endif
        this->target_block_threads = next_pow2(this->target_block_threads);
        this->target_block_threads =
            min(this->target_block_threads, (size_t)limits->maxThreadsPerBlock);
        this->target_block_threads =
            min(this->target_block_threads,
                limits->sharedMemPerBlock / this->shared_memory_per_thread);
        const unsigned int threads_per_block =
            limits->warpSize *
            gcd(this->target_block_threads / limits->warpSize,
                limits->maxThreadsPerMultiProcessor / limits->warpSize);

        size_t n_rdc, n_other;
        if (this->axis == 0) {
            n_rdc = this->rows;
            n_other = this->cols;
        } else {
            n_rdc = this->cols;
            n_other = this->rows;
        }

        /* reduction dimension parameter */
        unsigned int b_rdc = next_pow2(n_rdc);
        b_rdc = min(b_rdc, threads_per_block);
        b_rdc = min(b_rdc, limits->maxThreadsDim[1]);

        /* other dimension parameter */
        unsigned int b_other = threads_per_block / b_rdc;
        b_other = min((size_t)b_other, next_pow2(n_other));
        b_other = min(b_other, limits->maxThreadsDim[0]);
        b_other = min((size_t)b_other,
                      limits->sharedMemPerBlock /
                          (max(32, b_rdc) * this->shared_memory_per_thread));

        size_t g_other = ceil((double)n_other / (double)b_other);
        if (this->axis == 0) {
            this->_blocks = dim3(b_other, b_rdc);
            this->_block_size = this->_blocks.y;
            this->_grid = dim3(g_other, 1);
        } else {
            this->_blocks = dim3(b_rdc, b_other);
            this->_block_size = this->_blocks.x;
            this->_grid = dim3(1, g_other);
        }
        this->_shared_memory =
            max(32, b_rdc) * b_other * this->shared_memory_per_thread;
    }
};

#else
#define EXTERNC
#endif

EXTERNC int check_cuda_minmax_implementation_compatibility(impl_t impl,
                                                           int *compatible,
                                                           char **err);

EXTERNC int calculate_cuda_minmax_kernel_parameters(
    size_t rows, size_t cols, uint8_t axis, impl_t impl,
    size_t target_block_threads, size_t work_per_thread,
    size_t shared_memory_per_thread, unsigned int grid[3],
    unsigned int blocks[3], size_t *shared_memory, char **err);

EXTERNC int cuda_minmax(double *array, double *varrayout, uint32_t *iarrayout,
                        uint8_t axis, minmax_type_t type, size_t cols,
                        size_t rows, impl_t impl, size_t target_block_threads,
                        char **err);

#undef EXTERNC
