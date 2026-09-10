#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>

extern "C" void __tsan_read8(void *);
extern "C" void __tsan_write1(void *);
extern "C" void __tsan_write8(void *);
extern "C" void __tsan_write16(void *);
extern "C" void __tsan_ownership_profile_set_range(void *, uintptr_t);

constexpr uintptr_t kAppBytesPerShadowPage = 2048;
constexpr int kPages = 60;
char *memory;

void *ChangeOwner(void *) {
  for (int page = 30; page < 40; ++page)
    __tsan_write8(memory + page * kAppBytesPerShadowPage);
  return nullptr;
}

int main() {
  memory = static_cast<char *>(
      mmap(nullptr, kPages * kAppBytesPerShadowPage, PROT_READ | PROT_WRITE,
           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
  __tsan_ownership_profile_set_range(memory, kPages * kAppBytesPerShadowPage);

  for (int page = 0; page < 10; ++page)
    for (int cell = 0; cell < 256; ++cell)
      __tsan_write8(memory + page * kAppBytesPerShadowPage + cell * 8);
  for (int page = 10; page < 15; ++page)
    for (int cell = 0; cell < 193; ++cell)
      __tsan_write8(memory + page * kAppBytesPerShadowPage + cell * 8);
  for (int page = 15; page < 20; ++page)
    for (int cell = 0; cell < 129; ++cell)
      __tsan_write8(memory + page * kAppBytesPerShadowPage + cell * 8);
  for (int page = 20; page < 25; ++page)
    for (int cell = 0; cell < 65; ++cell)
      __tsan_write8(memory + page * kAppBytesPerShadowPage + cell * 8);

  for (int page = 25; page < 30; ++page)
    if (page != 28)
      __tsan_write8(memory + page * kAppBytesPerShadowPage);
  __tsan_write8(memory + 26 * kAppBytesPerShadowPage);
  __tsan_read8(memory + 27 * kAppBytesPerShadowPage);
  __tsan_write1(memory + 28 * kAppBytesPerShadowPage);
  __tsan_write1(memory + 28 * kAppBytesPerShadowPage + 1);

  for (int page = 30; page < 40; ++page)
    __tsan_write8(memory + page * kAppBytesPerShadowPage);
  pthread_t thread;
  pthread_create(&thread, nullptr, ChangeOwner, nullptr);
  pthread_join(thread, nullptr);

  for (int page = 40; page < 50; ++page)
    __tsan_write1(memory + page * kAppBytesPerShadowPage);
  static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
  pthread_mutex_lock(&mutex);
  pthread_mutex_unlock(&mutex);
  for (int page = 40; page < 50; ++page) {
    __tsan_write1(memory + page * kAppBytesPerShadowPage + 1);
    __tsan_write1(memory + page * kAppBytesPerShadowPage + 1);
  }

  for (int page = 50; page < 60; ++page)
    __tsan_write16(memory + page * kAppBytesPerShadowPage);

  __tsan_ownership_profile_set_range(nullptr, 0);
  puts("expected: sparse=58.33% dense=25% avoidable=50% mixed=33.33% fallback-only=16.67%");
}
