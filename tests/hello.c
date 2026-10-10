#include <pthread.h>
#include <stdio.h>

static volatile unsigned __int128 numerator = (unsigned __int128)1 << 100;
static volatile unsigned __int128 denominator = (unsigned __int128)1 << 40;

static void *
worker(void *argument)
{
	return argument;
}

int
main(void)
{
	pthread_t thread;
	void *result;
	int value;
	unsigned __int128 quotient;

	value = 42;
	quotient = numerator / denominator;
	if (quotient != (unsigned __int128)1 << 60)
		return 1;
	if (pthread_create(&thread, NULL, worker, &value) != 0)
		return 1;
	if (pthread_join(thread, &result) != 0 || result != &value)
		return 1;
	if (puts("musllvm C OK") < 0 || fflush(stdout) == EOF)
		return 1;
	return 0;
}
