// Data-parallel private work followed by shared merge and read phases.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define THREADS 4
#define ROUNDS 3
#define SLICE_MB 128
#define BINS 4096

static size_t slice_bytes = (size_t)SLICE_MB * 1024 * 1024;
static unsigned char *slices[THREADS];
static long shared_hist[BINS];
static long shared_checksum;
static pthread_mutex_t hist_lock = PTHREAD_MUTEX_INITIALIZER;
typedef struct {
    pthread_mutex_t m;
    pthread_cond_t cv;
    unsigned count, waiting, generation;
} barrier_t;
static barrier_t barrier;

static void barrier_init(barrier_t *b, unsigned count) {
    pthread_mutex_init(&b->m, 0);
    pthread_cond_init(&b->cv, 0);
    b->count = count;
    b->waiting = 0;
    b->generation = 0;
}

static void barrier_wait(barrier_t *b) {
    pthread_mutex_lock(&b->m);
    unsigned gen = b->generation;
    if (++b->waiting == b->count) {
        b->waiting = 0;
        b->generation++;
        pthread_cond_broadcast(&b->cv);
    } else {
        while (gen == b->generation)
            pthread_cond_wait(&b->cv, &b->m);
    }
    pthread_mutex_unlock(&b->m);
}

static void *worker(void *arg) {
    long id = (long)arg;
    unsigned char *mine = slices[id];
    long *hist = malloc(BINS * sizeof(long));

    for (int r = 0; r < ROUNDS; r++) {
        for (size_t i = 0; i < slice_bytes; i++)
            mine[i] = (unsigned char)(i + r + id);

        memset(hist, 0, BINS * sizeof(long));
        for (size_t i = 0; i < slice_bytes; i += 64)
            hist[mine[i] % BINS]++;

        barrier_wait(&barrier);

        pthread_mutex_lock(&hist_lock);
        for (int b = 0; b < BINS; b++)
            shared_hist[b] += hist[b];
        pthread_mutex_unlock(&hist_lock);

        barrier_wait(&barrier);

        unsigned char *other = slices[(id + 1) % THREADS];
        long sum = 0;
        for (size_t i = 0; i < slice_bytes; i += 4096)
            sum += other[i];
        pthread_mutex_lock(&hist_lock);
        shared_checksum += sum;
        pthread_mutex_unlock(&hist_lock);

        barrier_wait(&barrier);
    }
    free(hist);
    return 0;
}

int main(void) {
    pthread_t th[THREADS];
    barrier_init(&barrier, THREADS);
    for (long i = 0; i < THREADS; i++) {
        slices[i] = malloc(slice_bytes);
        if (!slices[i]) { perror("malloc"); return 1; }
    }
    for (long i = 0; i < THREADS; i++) pthread_create(&th[i], 0, worker, (void *)i);
    for (int i = 0; i < THREADS; i++) pthread_join(th[i], 0);

    long total = 0;
    for (int b = 0; b < BINS; b++) total += shared_hist[b];
    printf("hist total=%ld checksum=%ld\n", total, shared_checksum);
    for (int i = 0; i < THREADS; i++) free(slices[i]);
    return 0;
}
