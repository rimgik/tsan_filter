// Private byte-wise initialisation followed by cross-thread reads.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define THREADS 4
#define BUFS_PER_THREAD 500
#define BUFSZ 4096

static char *bufs[THREADS][BUFS_PER_THREAD];
static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
static int published;
static long checksums[THREADS];

static void *writer(void *arg) {
    long id = (long)arg;

    for (int i = 0; i < BUFS_PER_THREAD; i++) {
        char *b = malloc(BUFSZ);
        bufs[id][i] = b;
        for (int j = 0; j < BUFSZ; j++)
            b[j] = (char)(i + j + id);
    }

    pthread_mutex_lock(&m);
    published++;
    pthread_cond_broadcast(&cv);
    while (published < THREADS)
        pthread_cond_wait(&cv, &m);
    pthread_mutex_unlock(&m);

    long sum = 0;
    for (int t = 0; t < THREADS; t++)
        for (int i = 0; i < BUFS_PER_THREAD; i++)
            for (int j = 0; j < BUFSZ; j += 512)
                sum += bufs[t][i][j];
    checksums[id] = sum;
    return 0;
}

int main(void) {
    pthread_t th[THREADS];
    for (long i = 0; i < THREADS; i++)
        pthread_create(&th[i], 0, writer, (void *)i);
    long total = 0;
    for (int i = 0; i < THREADS; i++) {
        pthread_join(th[i], 0);
        total += checksums[i];
    }
    printf("checksum=%ld over %d threads\n", total, THREADS);
    for (int t = 0; t < THREADS; t++)
        for (int i = 0; i < BUFS_PER_THREAD; i++)
            free(bufs[t][i]);
    return 0;
}
