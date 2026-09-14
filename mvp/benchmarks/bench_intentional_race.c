#include <pthread.h>

static int value;

static void *write_value(void *argument) {
  value = *(int *)argument;
  return 0;
}

int main(void) {
  int one = 1;
  int two = 2;
  pthread_t first;
  pthread_t second;
  pthread_create(&first, 0, write_value, &one);
  pthread_create(&second, 0, write_value, &two);
  pthread_join(first, 0);
  pthread_join(second, 0);
  return value == 0;
}
