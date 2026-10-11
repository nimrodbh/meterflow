CC ?= gcc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror

build/libaggregator.so: aggregator.c aggregator.h
	mkdir -p build
	$(CC) $(CFLAGS) -shared -fPIC -o $@ aggregator.c

build/test_aggregator: aggregator.c aggregator.h test_aggregator.c
	mkdir -p build
	$(CC) $(CFLAGS) -fsanitize=address,undefined -g -o $@ aggregator.c test_aggregator.c

.PHONY: test clean
test: build/test_aggregator
	./build/test_aggregator

clean:
	rm -rf build
