#include <thrust/device_vector.h>
#include <thrust/functional.h>
#include <thrust/iterator/counting_iterator.h>
#include <thrust/iterator/discard_iterator.h>
#include <thrust/iterator/permutation_iterator.h>
#include <thrust/iterator/transform_iterator.h>
#include <thrust/reduce.h>
#include <thrust/sequence.h>
#include <thrust/transform.h>

#include <cfloat>
#include <iostream>
#include <memory>

#include "minmax.cuh"
#include "utils.cuh"
using namespace thrust::placeholders;

template <typename V, typename I>
using MinMaxFunctor =
    thrust::binary_function<thrust::tuple<V, I>, thrust::tuple<V, I>,
                            thrust::tuple<V, I>>;

template <typename V, typename I, minmax_type_t type>
struct stable_minmax : public MinMaxFunctor<V, I> {
    __host__ __device__ thrust::tuple<V, I> operator()(thrust::tuple<V, I> x,
                                                       thrust::tuple<V, I> y) {
        bool is_max = (type == ARGMAX || type == MAX);
        if (thrust::get<0>(x) > thrust::get<0>(y))
            return is_max ? x : y;
        else if (thrust::get<0>(y) > thrust::get<0>(x))
            return is_max ? y : x;
        // for equal values, choose the smaller index
        if (thrust::get<1>(x) < thrust::get<1>(y)) return x;
        return y;
    }
};

template <typename I, typename V>
class ThrustMinMaxCUDAKernel : public MinMaxCUDAKernel<I, V> {
    using MinMaxCUDAKernel<I, V>::MinMaxCUDAKernel;

   private:
    template <minmax_type_t type, uint8_t axis>
    int __host__ thrust_2d_minmax() {
        thrust::device_vector<V> darray(
            this->array, this->array + (this->rows * this->cols));
        size_t out_size = (axis == 0) ? this->cols : this->rows;
        size_t rdc_dim = (axis == 0) ? this->rows : this->cols;

        thrust::device_vector<I> dmaxi(out_size);
        thrust::device_vector<V> dmaxv(out_size);

#if defined(CUDA_DEBUG)
        printf("cuda_thrust_minmax[host]: type=%d axis=%d\n", type, axis);
#endif

        auto col_idx_iterator = thrust::make_transform_iterator(
            thrust::make_counting_iterator((I)0), _1 / rdc_dim);
        if (axis == 0) {
            thrust::reduce_by_key(
                /* input keys: elements in the same column get the same key */
                col_idx_iterator, col_idx_iterator + (this->rows * this->cols),
                /* input values: tuples of column element and its column index
                 */
                thrust::make_zip_iterator(thrust::make_tuple(
                    thrust::make_permutation_iterator(
                        darray.begin(),
                        thrust::make_transform_iterator(
                            thrust::make_counting_iterator((I)0),
                            (_1 % this->rows) * this->cols + _1 / this->rows)),
                    thrust::make_transform_iterator(
                        thrust::make_counting_iterator((I)0), _1 % rdc_dim))),
                /* output keys: are discarded */
                thrust::make_discard_iterator(),
                /* output values: unzips the (val, idx) tupes from the input */
                thrust::make_zip_iterator(
                    thrust::make_tuple(dmaxv.begin(), dmaxi.begin())),
                /* apply binary reduction on all elements with equal keys */
                thrust::equal_to<I>(), stable_minmax<V, I, type>());
        } else {
            thrust::reduce_by_key(
                col_idx_iterator, col_idx_iterator + (this->rows * this->cols),
                thrust::make_zip_iterator(thrust::make_tuple(
                    darray.begin(),
                    thrust::make_transform_iterator(
                        thrust::make_counting_iterator((I)0), _1 % rdc_dim))),
                thrust::make_discard_iterator(),
                thrust::make_zip_iterator(
                    thrust::make_tuple(dmaxv.begin(), dmaxi.begin())),
                thrust::equal_to<I>(), stable_minmax<V, I, type>());
        }

        if (type == ARGMAX || type == ARGMIN)
            thrust::copy(dmaxi.begin(), dmaxi.end(), this->iarrayout);
        else
            thrust::copy(dmaxv.begin(), dmaxv.end(), this->varrayout);
        return SUCCESS;
    }

   public:
    __host__ static std::unique_ptr<MinMaxCUDAKernel<I, V>> make(
        minmax_kernel_arguments_t<I, V> args, char **err) {
        return std::make_unique<ThrustMinMaxCUDAKernel<I, V>>(args, err);
    }

    __host__ void launch_kernel(dim3 _grid, dim3 _blocks, size_t _shared_memory,
                                unsigned int _block_size,
                                minmax_kernel_arguments_t<I, V> _args) {}

    __host__ bool is_compatible() { return true; }

    __host__ void calculate_kernel_parameters() {}

    __host__ int launch() {
        switch (this->axis) {
            case 0:
                switch (this->type) {
                    case ARGMIN:
                        return thrust_2d_minmax<ARGMIN, 0>();
                    case ARGMAX:
                        return thrust_2d_minmax<ARGMAX, 0>();
                    case MIN:
                        return thrust_2d_minmax<MIN, 0>();
                    default:
                        return thrust_2d_minmax<MAX, 0>();
                }
            default:
                switch (this->type) {
                    case ARGMIN:
                        return thrust_2d_minmax<ARGMIN, 1>();
                    case ARGMAX:
                        return thrust_2d_minmax<ARGMAX, 1>();
                    case MIN:
                        return thrust_2d_minmax<MIN, 1>();
                    default:
                        return thrust_2d_minmax<MAX, 1>();
                }
        }
    }
};

template <typename I, typename V>
using MinMaxKernelFactory = std::unique_ptr<MinMaxCUDAKernel<I, V>> (*)(
    minmax_kernel_arguments_t<I, V>, char **);

template <typename I, typename V>
MinMaxKernelFactory<I, V> select_minmax_kernel_implementation(impl_t impl) {
    MinMaxKernelFactory<I, V> kernel_impl = NULL;
    switch (impl) {
        case IMPL_CUDA_THRUST:
            kernel_impl = ThrustMinMaxCUDAKernel<I, V>::make;
            break;
        default:
            kernel_impl = ReductionMinMaxCUDAKernel<I, V>::make;
            break;
    }
    return kernel_impl;
}

int check_cuda_minmax_implementation_compatibility(impl_t impl, int *compatible,
                                                   char **err) {
    MinMaxKernelFactory<uint32_t, double> factory =
        select_minmax_kernel_implementation<uint32_t, double>(impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", err);
    auto kernel = factory(minmax_kernel_arguments_t<uint32_t, double>{}, err);
    *compatible = kernel->is_compatible();
    return SUCCESS;
}

int calculate_cuda_minmax_kernel_parameters(
    size_t rows, size_t cols, uint8_t axis, impl_t impl,
    size_t target_block_threads, size_t work_per_thread,
    size_t shared_memory_per_thread, unsigned int grid[3],
    unsigned int blocks[3], size_t *shared_memory, char **err) {
    minmax_kernel_arguments_t<uint32_t, double> args = {
        axis : axis,
        type : ARGMAX,
        rows : rows,
        cols : cols,
        work_per_thread : work_per_thread,
    };
    MinMaxKernelFactory<uint32_t, double> factory =
        select_minmax_kernel_implementation<uint32_t, double>(impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", err);
    auto kernel = factory(args, err);
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

int cuda_minmax(double *array, double *varrayout, uint32_t *iarrayout,
                uint8_t axis, minmax_type_t type, size_t cols, size_t rows,
                impl_t impl, size_t target_block_threads, char **err) {
    minmax_kernel_arguments_t<uint32_t, double> args = {
        axis : axis,
        type : type,
        rows : rows,
        cols : cols,
        work_per_thread : 32,
        array : array,
        iarrayout : iarrayout,
        varrayout : varrayout,
    };
    MinMaxKernelFactory<uint32_t, double> factory =
        select_minmax_kernel_implementation<uint32_t, double>(impl);
    if (factory == NULL) EXIT_DEBUG("kernel not implemented", err);
    auto kernel = factory(args, err);
    if (!kernel->is_compatible())
        EXIT_DEBUG("CUDA implementation incompatible with available hardware",
                   err);
    return kernel->launch();
}
