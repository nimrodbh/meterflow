"""Aggregator: running totals per (customer, kind).

`CAggregator` calls the C implementation in core/aggregator.c through ctypes.
`PyAggregator` is a pure Python reference with the same interface. The test
suite checks the two against each other on random input, and the benchmark
reports how much faster the C core is.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from array import array
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

AGG_OK = 0
AGG_ERR_NOMEM = -1
AGG_ERR_OVERFLOW = -2
AGG_ERR_ARG = -3

INT64_MAX = 2**63 - 1


class AggregatorError(Exception):
    pass


class AggregatorOverflow(AggregatorError):
    pass


@dataclass(frozen=True)
class Row:
    customer: int
    kind: int
    events: int
    units: int
    amount_micro: int


class Aggregator(Protocol):
    def add(self, customer: int, kind: int, units: int, price_micro: int) -> None: ...
    def add_many(self, items: Iterable[tuple[int, int, int, int]]) -> None: ...
    def rows(self) -> list[Row]: ...
    def clear(self) -> None: ...
    def __len__(self) -> int: ...


class PyAggregator:
    def __init__(self) -> None:
        self._data: dict[tuple[int, int], list[int]] = {}

    def add(self, customer: int, kind: int, units: int, price_micro: int) -> None:
        if units < 0 or price_micro < 0:
            raise AggregatorError("units and price must be non-negative")
        cost = units * price_micro
        key = (customer, kind)
        cur = self._data.get(key)
        new_units = (cur[1] if cur else 0) + units
        new_amount = (cur[2] if cur else 0) + cost
        if cost > INT64_MAX or new_units > INT64_MAX or new_amount > INT64_MAX:
            raise AggregatorOverflow("int64 overflow")
        if cur is None:
            self._data[key] = [1, units, cost]
        else:
            cur[0] += 1
            cur[1] = new_units
            cur[2] = new_amount

    def add_many(self, items: Iterable[tuple[int, int, int, int]]) -> None:
        for customer, kind, units, price in items:
            self.add(customer, kind, units, price)

    def rows(self) -> list[Row]:
        return [Row(c, k, v[0], v[1], v[2]) for (c, k), v in self._data.items()]

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class _CRow(ctypes.Structure):
    _fields_ = [
        ("customer", ctypes.c_uint64),
        ("kind", ctypes.c_uint32),
        ("_pad", ctypes.c_uint32),
        ("events", ctypes.c_int64),
        ("units", ctypes.c_int64),
        ("amount_micro", ctypes.c_int64),
    ]


def _lib_candidates() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "core" / "build"
    env = os.environ.get("METERFLOW_LIB")
    names = ["libaggregator.so", "libaggregator.dylib", "aggregator.dll"]
    found = [root / n for n in names]
    return ([Path(env)] if env else []) + found


def _load_lib() -> ctypes.CDLL | None:
    for path in _lib_candidates():
        if path.exists():
            lib = ctypes.CDLL(str(path))
            lib.agg_new.restype = ctypes.c_void_p
            lib.agg_new.argtypes = [ctypes.c_size_t]
            lib.agg_free.argtypes = [ctypes.c_void_p]
            lib.agg_clear.argtypes = [ctypes.c_void_p]
            lib.agg_add.restype = ctypes.c_int
            lib.agg_add.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint64,
                ctypes.c_uint32,
                ctypes.c_int64,
                ctypes.c_int64,
            ]
            lib.agg_add_batch.restype = ctypes.c_int
            lib.agg_add_batch.argtypes = [
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_uint64),
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_int64),
                ctypes.POINTER(ctypes.c_int64),
            ]
            lib.agg_len.restype = ctypes.c_size_t
            lib.agg_len.argtypes = [ctypes.c_void_p]
            lib.agg_dump.restype = ctypes.c_size_t
            lib.agg_dump.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CRow), ctypes.c_size_t]
            return lib
    return None


_LIB = _load_lib()


def c_available() -> bool:
    return _LIB is not None


def _check(rc: int) -> None:
    if rc == AGG_OK:
        return
    if rc == AGG_ERR_OVERFLOW:
        raise AggregatorOverflow("int64 overflow")
    if rc == AGG_ERR_NOMEM:
        raise MemoryError("aggregator out of memory")
    raise AggregatorError(f"aggregator error {rc}")


class CAggregator:
    def __init__(self, initial_capacity: int = 1024) -> None:
        if _LIB is None:
            raise RuntimeError("C aggregator not built; run `make -C core build/libaggregator.so`")
        self._lib = _LIB
        self._h = self._lib.agg_new(initial_capacity)
        if not self._h:
            raise MemoryError("agg_new failed")

    def add(self, customer: int, kind: int, units: int, price_micro: int) -> None:
        _check(self._lib.agg_add(self._h, customer, kind, units, price_micro))

    def add_many(self, items: Iterable[tuple[int, int, int, int]]) -> None:
        batch = list(items)
        n = len(batch)
        if n == 0:
            return
        self.add_columns(
            array("Q", (b[0] for b in batch)),
            array("I", (b[1] for b in batch)),
            array("q", (b[2] for b in batch)),
            array("q", (b[3] for b in batch)),
        )

    def add_columns(self, customers: array, kinds: array, units: array, prices: array) -> None:
        """Columnar fast path: four equal-length arrays ('Q', 'I', 'q', 'q'), handed to C without copying."""
        n = len(customers)
        if not (len(kinds) == len(units) == len(prices) == n):
            raise AggregatorError("column lengths differ")
        if n == 0:
            return
        _check(
            self._lib.agg_add_batch(
                self._h,
                n,
                (ctypes.c_uint64 * n).from_buffer(customers),
                (ctypes.c_uint32 * n).from_buffer(kinds),
                (ctypes.c_int64 * n).from_buffer(units),
                (ctypes.c_int64 * n).from_buffer(prices),
            )
        )

    def rows(self) -> list[Row]:
        n = len(self)
        buf = (_CRow * max(n, 1))()
        got = self._lib.agg_dump(self._h, buf, n)
        return [Row(r.customer, r.kind, r.events, r.units, r.amount_micro) for r in buf[:got]]

    def clear(self) -> None:
        self._lib.agg_clear(self._h)

    def __len__(self) -> int:
        return int(self._lib.agg_len(self._h))

    def close(self) -> None:
        if self._h:
            self._lib.agg_free(self._h)
            self._h = None

    def __del__(self) -> None:
        # At interpreter shutdown the library handle may already be gone.
        with contextlib.suppress(Exception):
            self.close()


def make_aggregator(prefer_c: bool = True) -> Aggregator:
    if prefer_c and c_available():
        return CAggregator()
    if prefer_c:
        print("meterflow: C core not built, using the Python aggregator", file=sys.stderr)
    return PyAggregator()
