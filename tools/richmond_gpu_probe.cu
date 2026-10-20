#include <cuda_runtime.h>
#include <cstdio>

int main() {
    int count = 0;
    cudaError_t status = cudaGetDeviceCount(&count);
    if (status != cudaSuccess) {
        std::fprintf(stderr, "CUDA device qualification failed: %s\n", cudaGetErrorString(status));
        return 1;
    }
    if (count != 1) {
        std::fprintf(stderr, "Expected one allocated CUDA device, observed %d\n", count);
        return 1;
    }
    cudaDeviceProp properties;
    status = cudaGetDeviceProperties(&properties, 0);
    if (status != cudaSuccess) {
        std::fprintf(stderr, "CUDA device properties failed: %s\n", cudaGetErrorString(status));
        return 1;
    }
    std::printf("{\"device_count\":%d,\"name\":\"%s\",\"compute_capability\":%d,\"memory_bytes\":%zu}\n",
                count, properties.name, properties.major * 10 + properties.minor, properties.totalGlobalMem);
    return 0;
}
