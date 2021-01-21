#include <cuda_profiler_api.h>
#include <stdio.h>

#include <cfloat>

#include "../minmax.cuh"
#include "../utils.cuh"

template <class I, class V>
void initRange(size_t nx, size_t ny, V *array) {
    for (size_t ix = 0; ix < nx; ix++) {
        for (size_t iy = 0; iy < ny; iy++) {
            array[ix * ny + iy] = ix * ny + iy;
        }
    }
}

template <class I, class V>
int profile(size_t nx, size_t ny, size_t target_block_threads,
            minmax_type_t type, uint8_t axis, impl_t impl,
            void (*initf)(size_t nx, size_t ny, V *array)) {
    int nparallel = 1;
    V *array = (V *)calloc(nx * ny, sizeof(V));

    initRange<I, V>(nx, ny, array);
    (*initf)(nx, ny, array);

    V *vresult = (V *)malloc(nx * sizeof(V));
    I *iresult = (I *)malloc(nx * sizeof(I));

    cudaProfilerStart();

    char *err_msg = NULL;
    int err = cuda_minmax(array, vresult, iresult, axis, type, nx, ny, impl,
                          target_block_threads, &err_msg);

    cudaProfilerStop();
    if (err != SUCCESS) {
        if (err_msg != NULL) free(err_msg);
        return ERROR;
    }

    free(array);
    free(iresult);
    free(vresult);
    return SUCCESS;
}

template <class I, class V>
int profileRange(size_t nx, size_t ny, size_t target_block_threads,
                 minmax_type_t type, uint8_t axis, impl_t impl) {
    return profile<I, V>(nx, ny, target_block_threads, type, axis, impl,
                         initRange<I, V>);
}

int main() {
    return profileRange<uint32_t, double>(10000, 10000, 256, ARGMAX, 0,
                                          IMPL_CUDA);
}
