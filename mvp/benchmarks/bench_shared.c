// Contended writes to a mutex-protected shared object.
#include <pthread.h>
#include <stdio.h>

#define THREADS 8
#define ITERS 500000

pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
struct { long a, b, c, d; } S;

void *worker(void *arg) {
    (void)arg;
    for (long i = 0; i < ITERS; i++) {
        pthread_mutex_lock(&m);
        S.a++; S.b += 2; S.c ^= i; S.d = S.a + S.b;
        pthread_mutex_unlock(&m);
    }
    return 0;
}

int main(void) {
    pthread_t th[THREADS];
    for (int i = 0; i < THREADS; i++) pthread_create(&th[i], 0, worker, 0);
    for (int i = 0; i < THREADS; i++) pthread_join(th[i], 0);
    printf("S.a=%ld\n", S.a);
    return 0;
}
