#ifndef METERFLOW_AGGREGATOR_H
#define METERFLOW_AGGREGATOR_H

#include <stddef.h>
#include <stdint.h>

/*
 * Usage aggregator: running totals per (customer, kind) pair.
 *
 * Open addressing hash table with linear probing, grown at 70% load.
 * Money is kept as integer micro-units (1 unit = 1,000,000 micro) so that
 * billing never touches floating point.
 */

typedef struct agg agg_t;

typedef struct {
    uint64_t customer;
    uint32_t kind;
    uint32_t _pad;
    int64_t events;
    int64_t units;
    int64_t amount_micro;
} agg_row_t;

#define AGG_OK 0
#define AGG_ERR_NOMEM (-1)
#define AGG_ERR_OVERFLOW (-2)
#define AGG_ERR_ARG (-3)

agg_t *agg_new(size_t initial_capacity);
void agg_free(agg_t *a);
void agg_clear(agg_t *a);

/* Add one event: units consumed at price_micro per unit. */
int agg_add(agg_t *a, uint64_t customer, uint32_t kind, int64_t units, int64_t price_micro);

/* Add many events at once; the three arrays have n entries each.
 * Stops at the first error and returns it; events before it are kept. */
int agg_add_batch(agg_t *a, size_t n, const uint64_t *customers, const uint32_t *kinds,
                  const int64_t *units, const int64_t *prices_micro);

size_t agg_len(const agg_t *a);

/* Copy up to max rows into out (unordered). Returns the number written. */
size_t agg_dump(const agg_t *a, agg_row_t *out, size_t max);

#endif
