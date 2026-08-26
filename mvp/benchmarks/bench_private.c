// Repeated private accesses separated by synchronisation.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#define THREADS 4
#define ITERS 2000000

pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
long shared_tickets = 0;

void *worker(void *arg) {
    (void)arg;
    long *sum = malloc(64);
    *sum = 0;
    for (long i = 0; i < ITERS; i++) {
        pthread_mutex_lock(&m);
        long t = shared_tickets++;
        pthread_mutex_unlock(&m);
        *sum += t;
    }
    long r = *sum;
    free(sum);
    return (void *)r;
}

int main(void) {
    pthread_t th[THREADS];
    for (int i = 0; i < THREADS; i++) pthread_create(&th[i], 0, worker, 0);
    void *r;
    long total = 0;
    for (int i = 0; i < THREADS; i++) { pthread_join(th[i], &r); total += (long)r; }
    printf("total=%ld\n", total);
    return 0;
}
