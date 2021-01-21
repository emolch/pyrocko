#pragma once

#ifdef __cplusplus
#define EXTERNC extern "C"
#else
#define EXTERNC
#endif

namespace cuda {
struct __numeric_limits_base {};

template <typename _Tp>
struct numeric_limits : public __numeric_limits_base {
    __host__ __device__ static constexpr _Tp min() noexcept { return _Tp(); }
    __host__ __device__ static constexpr _Tp max() noexcept { return _Tp(); }
};
template <typename _Tp>
struct numeric_limits<const _Tp> : public numeric_limits<_Tp> {};

template <typename _Tp>
struct numeric_limits<volatile _Tp> : public numeric_limits<_Tp> {};

template <typename _Tp>
struct numeric_limits<const volatile _Tp> : public numeric_limits<_Tp> {};

/* float */
template <>
struct numeric_limits<float> {
    __host__ __device__ static constexpr float min() noexcept {
        return __FLT_MIN__;
    }
    __host__ __device__ static constexpr float max() noexcept {
        return __FLT_MAX__;
    }
};

/* double */
template <>
struct numeric_limits<double> {
    __host__ __device__ static constexpr double min() noexcept {
        return __DBL_MIN__;
    }
    __host__ __device__ static constexpr double max() noexcept {
        return __DBL_MAX__;
    }
};
}  // namespace cuda

#undef EXTERNC
