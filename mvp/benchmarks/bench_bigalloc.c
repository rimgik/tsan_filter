// Large, disjoint allocations owned by separate worker threads.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#define MB (1024 * 1024)
#define THREADS 4
#define TOTAL_MB 256
#define SLICE ((size_t)(TOTAL_MB / THREADS) * MB)

static char *slices[THREADS];
static long results[THREADS];

static void *worker(void *arg) {
    long id = (long)arg;
    char *buf = malloc(SLICE);
    slices[id] = buf;

    for (size_t i = 0; i < SLICE; i++)
        buf[i] = (char)(i + id);
    long sum = 0;
    for (size_t i = 0; i < SLICE; i += 64)
        sum += buf[i];

    results[id] = sum;
    return 0;
}

int main(void) {
    pthread_t th[THREADS];
    for (long i = 0; i < THREADS; i++)
        pthread_create(&th[i], 0, worker, (void *)i);
    long total = 0;
    for (int i = 0; i < THREADS; i++) {
        pthread_join(th[i], 0);
        total += results[i];
    }
    printf("sum=%ld over %d threads x %zu MB\n", total, THREADS,
           SLICE / MB);
    for (int i = 0; i < THREADS; i++)
        free(slices[i]);
    return 0;
}
