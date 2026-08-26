#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

struct alignas(8) Cell {
  volatile std::uint64_t value;
};

__attribute__((noinline)) static std::uint64_t write_loop(
    Cell *cell, std::uint64_t iterations) {
  for (std::uint64_t i = 0; i < iterations; ++i)
    cell->value = i;
  return cell->value;
}

int main(int argc, char **argv) {
  const std::uint64_t iterations =
      argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 300000000ULL;
  Cell *cell = static_cast<Cell *>(std::malloc(sizeof(Cell)));
  if (!cell)
    return 1;

  cell->value = 0;
  const auto start = std::chrono::steady_clock::now();
  const std::uint64_t result = write_loop(cell, iterations);
  const auto stop = std::chrono::steady_clock::now();
  const double seconds = std::chrono::duration<double>(stop - start).count();

  std::printf("iterations=%llu value=%llu seconds=%.6f\n",
              static_cast<unsigned long long>(iterations),
              static_cast<unsigned long long>(result), seconds);
  std::free(cell);
  return 0;
}
