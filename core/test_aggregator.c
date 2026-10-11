#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "aggregator.h"

static const agg_row_t *find(const agg_row_t *rows, size_t n, uint64_t customer, uint32_t kind) {
    for (size_t i = 0; i < n; i++) {
        if (rows[i].customer == customer && rows[i].kind == kind) {
            return &rows[i];
        }
    }
    return NULL;
}

static void test_basic(void) {
    agg_t *a = agg_new(4);
    assert(a != NULL);
    assert(agg_add(a, 1, 0, 10, 500) == AGG_OK);
    assert(agg_add(a, 1, 0, 5, 500) == AGG_OK);
    assert(agg_add(a, 1, 1, 2, 1000) == AGG_OK);
    assert(agg_add(a, 2, 0, 7, 500) == AGG_OK);
    assert(agg_len(a) == 3);

    agg_row_t rows[8];
    size_t n = agg_dump(a, rows, 8);
    assert(n == 3);
    const agg_row_t *r = find(rows, n, 1, 0);
    assert(r != NULL && r->events == 2 && r->units == 15 && r->amount_micro == 7500);
    r = find(rows, n, 1, 1);
    assert(r != NULL && r->events == 1 && r->units == 2 && r->amount_micro == 2000);
    agg_free(a);
}

static void test_growth(void) {
    agg_t *a = agg_new(16);
    for (uint64_t c = 0; c < 100000; c++) {
        assert(agg_add(a, c, (uint32_t)(c % 3), 1, 10) == AGG_OK);
    }
    assert(agg_len(a) == 100000);
    agg_row_t *rows = malloc(sizeof(agg_row_t) * 100000);
    assert(agg_dump(a, rows, 100000) == 100000);
    int64_t total_units = 0;
    for (size_t i = 0; i < 100000; i++) {
        total_units += rows[i].units;
    }
    assert(total_units == 100000);
    free(rows);
    agg_free(a);
}

static void test_errors(void) {
    agg_t *a = agg_new(16);
    assert(agg_add(a, 1, 0, -1, 10) == AGG_ERR_ARG);
    assert(agg_add(a, 1, 0, 1, -10) == AGG_ERR_ARG);
    assert(agg_add(a, 1, 0, INT64_MAX, 2) == AGG_ERR_OVERFLOW);
    assert(agg_add(a, 1, 0, INT64_MAX, 1) == AGG_OK);
    assert(agg_add(a, 1, 0, 1, 1) == AGG_ERR_OVERFLOW);
    assert(agg_len(a) == 1);
    agg_clear(a);
    assert(agg_len(a) == 0);
    agg_free(a);
}

static void test_batch(void) {
    agg_t *a = agg_new(16);
    uint64_t c[3] = {1, 1, 2};
    uint32_t k[3] = {0, 0, 0};
    int64_t u[3] = {1, 2, 3};
    int64_t p[3] = {100, 100, 100};
    assert(agg_add_batch(a, 3, c, k, u, p) == AGG_OK);
    assert(agg_len(a) == 2);
    agg_free(a);
}

int main(void) {
    test_basic();
    test_growth();
    test_errors();
    test_batch();
    puts("all C tests passed");
    return 0;
}
