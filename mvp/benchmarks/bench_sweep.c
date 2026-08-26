// Working-set sweep over disjoint per-thread slices.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

#define THREADS 4

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static const size_t max_slice = 1ull << 28;
static const size_t touches_per_pass = 1ull << 24;

static size_t cur_slice;
static double pass_ns[THREADS];
static long pass_sum[THREADS];

typedef struct {
    long id;
    long *buf;
} arg_t;

static void *worker(void *p) {
    arg_t *a = (arg_t *)p;
    long *buf = a->buf;
    size_t n = cur_slice / sizeof(long);

    for (size_t i = 0; i < n; i++) buf[i] = (long)i;

    long sum = 0;
    size_t idx = 0;
    const size_t stride = 9973;
    double t0 = now();
    for (size_t k = 0; k < touches_per_pass; k++) {
        idx += stride;
        if (idx >= n) idx -= n;
        sum += buf[idx];
        buf[idx] = sum;
    }
    pass_ns[a->id] = (now() - t0) * 1e9 / touches_per_pass;
    pass_sum[a->id] = sum;
    return 0;
}

int main(void) {
    arg_t args[THREADS];
    for (int i = 0; i < THREADS; i++) {
        args[i].id = i;
        args[i].buf = malloc(max_slice);
        if (!args[i].buf) { perror("malloc"); return 1; }
    }

    printf("%14s %14s %16s\n", "slice_per_thr", "total_MB", "ns_per_access");
    for (cur_slice = 1ull << 20; cur_slice <= max_slice; cur_slice <<= 1) {
        pthread_t th[THREADS];
        for (int i = 0; i < THREADS; i++)
            pthread_create(&th[i], 0, worker, &args[i]);
        double worst = 0;
        for (int i = 0; i < THREADS; i++) {
            pthread_join(th[i], 0);
            if (pass_ns[i] > worst) worst = pass_ns[i];
        }
        printf("%11zu MB %14zu %16.2f\n", cur_slice >> 20,
               (cur_slice * THREADS) >> 20, worst);
        fflush(stdout);
    }
    for (int i = 0; i < THREADS; i++) free(args[i].buf);
    return 0;
}
