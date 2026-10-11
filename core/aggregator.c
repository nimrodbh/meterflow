#include "aggregator.h"

#include <stdlib.h>
#include <string.h>

typedef struct {
    agg_row_t row;
    uint8_t used;
} slot_t;

struct agg {
    slot_t *slots;
    size_t cap; /* always a power of two */
    size_t len;
};

static size_t next_pow2(size_t n) {
    size_t p = 16;
    while (p < n) {
        p <<= 1;
    }
    return p;
}

/* 64-bit mix (splitmix64 finalizer) over the (customer, kind) pair. */
static uint64_t hash_key(uint64_t customer, uint32_t kind) {
    uint64_t x = customer ^ ((uint64_t)kind * 0x9E3779B97F4A7C15ULL);
    x ^= x >> 30;
    x *= 0xBF58476D1CE4E5B9ULL;
    x ^= x >> 27;
    x *= 0x94D049BB133111EBULL;
    x ^= x >> 31;
    return x;
}

static slot_t *find_slot(slot_t *slots, size_t cap, uint64_t customer, uint32_t kind) {
    size_t mask = cap - 1;
    size_t i = (size_t)hash_key(customer, kind) & mask;
    while (slots[i].used && !(slots[i].row.customer == customer && slots[i].row.kind == kind)) {
        i = (i + 1) & mask;
    }
    return &slots[i];
}

static int grow(agg_t *a) {
    size_t new_cap = a->cap * 2;
    slot_t *fresh = calloc(new_cap, sizeof(slot_t));
    if (fresh == NULL) {
        return AGG_ERR_NOMEM;
    }
    for (size_t i = 0; i < a->cap; i++) {
        if (a->slots[i].used) {
            slot_t *dst = find_slot(fresh, new_cap, a->slots[i].row.customer, a->slots[i].row.kind);
            *dst = a->slots[i];
        }
    }
    free(a->slots);
    a->slots = fresh;
    a->cap = new_cap;
    return AGG_OK;
}

agg_t *agg_new(size_t initial_capacity) {
    agg_t *a = malloc(sizeof(agg_t));
    if (a == NULL) {
        return NULL;
    }
    a->cap = next_pow2(initial_capacity);
    a->len = 0;
    a->slots = calloc(a->cap, sizeof(slot_t));
    if (a->slots == NULL) {
        free(a);
        return NULL;
    }
    return a;
}

void agg_free(agg_t *a) {
    if (a == NULL) {
        return;
    }
    free(a->slots);
    free(a);
}

void agg_clear(agg_t *a) {
    if (a == NULL) {
        return;
    }
    memset(a->slots, 0, a->cap * sizeof(slot_t));
    a->len = 0;
}

int agg_add(agg_t *a, uint64_t customer, uint32_t kind, int64_t units, int64_t price_micro) {
    if (a == NULL || units < 0 || price_micro < 0) {
        return AGG_ERR_ARG;
    }
    int64_t cost;
    if (__builtin_mul_overflow(units, price_micro, &cost)) {
        return AGG_ERR_OVERFLOW;
    }
    if ((a->len + 1) * 10 > a->cap * 7) {
        int rc = grow(a);
        if (rc != AGG_OK) {
            return rc;
        }
    }
    slot_t *s = find_slot(a->slots, a->cap, customer, kind);
    int64_t new_units, new_amount;
    if (s->used) {
        if (__builtin_add_overflow(s->row.units, units, &new_units) ||
            __builtin_add_overflow(s->row.amount_micro, cost, &new_amount)) {
            return AGG_ERR_OVERFLOW;
        }
        s->row.events += 1;
        s->row.units = new_units;
        s->row.amount_micro = new_amount;
    } else {
        s->used = 1;
        s->row.customer = customer;
        s->row.kind = kind;
        s->row._pad = 0;
        s->row.events = 1;
        s->row.units = units;
        s->row.amount_micro = cost;
        a->len += 1;
    }
    return AGG_OK;
}

int agg_add_batch(agg_t *a, size_t n, const uint64_t *customers, const uint32_t *kinds,
                  const int64_t *units, const int64_t *prices_micro) {
    for (size_t i = 0; i < n; i++) {
        int rc = agg_add(a, customers[i], kinds[i], units[i], prices_micro[i]);
        if (rc != AGG_OK) {
            return rc;
        }
    }
    return AGG_OK;
}

size_t agg_len(const agg_t *a) {
    return a == NULL ? 0 : a->len;
}

size_t agg_dump(const agg_t *a, agg_row_t *out, size_t max) {
    size_t n = 0;
    if (a == NULL) {
        return 0;
    }
    for (size_t i = 0; i < a->cap && n < max; i++) {
        if (a->slots[i].used) {
            out[n++] = a->slots[i].row;
        }
    }
    return n;
}
