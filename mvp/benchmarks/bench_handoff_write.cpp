#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <pthread.h>

struct alignas(8) Cell {
  volatile std::uint64_t value;
};

struct Work {
  Cell *cell;
  std::uint64_t iterations;
  std::uint64_t result;
  double seconds;
};

__attribute__((noinline)) static std::uint64_t write_loop(
    Cell *cell, std::uint64_t iterations) {
  for (std::uint64_t i = 0; i < iterations; ++i)
    cell->value = i;
  return cell->value;
}

static void *worker(void *opaque) {
  auto *work = static_cast<Work *>(opaque);
  const auto start = std::chrono::steady_clock::now();
  work->result = write_loop(work->cell, work->iterations);
  const auto stop = std::chrono::steady_clock::now();
  work->seconds = std::chrono::duration<double>(stop - start).count();
  return nullptr;
}

int main(int argc, char **argv) {
  const std::uint64_t iterations =
      argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 300000000ULL;
  Cell *cell = static_cast<Cell *>(std::malloc(sizeof(Cell)));
  if (!cell)
    return 1;

  cell->value = 0;
  Work work{cell, iterations, 0, 0};
  pthread_t thread;
  if (pthread_create(&thread, nullptr, worker, &work) != 0)
    return 1;
  pthread_join(thread, nullptr);

  std::printf("iterations=%llu value=%llu seconds=%.6f\n",
              static_cast<unsigned long long>(iterations),
              static_cast<unsigned long long>(work.result), work.seconds);
  std::free(cell);
  return 0;
}
