#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>

extern "C" void __tsan_write8(void *);
extern "C" void __tsan_ownership_profile_set_range(void *, uintptr_t);

constexpr int kCells = 100;
constexpr int kSharedCells = 40;
uint64_t *cells;

void *TouchFromSecondThread(void *) {
  for (int i = 0; i < kSharedCells; ++i)
    __tsan_write8(cells + i);
  return nullptr;
}

int main() {
  cells = static_cast<uint64_t *>(
      mmap(nullptr, kCells * sizeof(*cells), PROT_READ | PROT_WRITE,
           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
  if (cells == MAP_FAILED)
    return 1;

  __tsan_ownership_profile_set_range(cells, kCells * sizeof(*cells));
  for (int i = 0; i < kCells; ++i)
    __tsan_write8(cells + i);

  pthread_t thread;
  if (pthread_create(&thread, nullptr, TouchFromSecondThread, nullptr) != 0)
    return 1;
  pthread_join(thread, nullptr);
  __tsan_ownership_profile_set_range(nullptr, 0);

  puts("expected: first_touches=100 transitions=40 private_cells=60");
}
