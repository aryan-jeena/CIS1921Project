"""Helpers for converting between (day, slot) and linear week-slot indices,
and for building the per-day availability mask used by the schedulers."""
from __future__ import annotations

from typing import Iterable, Iterator

from src.config.settings import DAYS_PER_WEEK, SLOTS_PER_DAY
from src.models.domain import TimeWindow


def week_slot(day: int, slot: int) -> int:
    """Flatten ``(day, slot)`` into a single index 0..SLOTS_PER_WEEK."""
    return day * SLOTS_PER_DAY + slot


def split_week_slot(idx: int) -> tuple[int, int]:
    """Inverse of :func:`week_slot`."""
    return divmod(idx, SLOTS_PER_DAY)


def build_availability_mask(
    windows: Iterable[TimeWindow],
) -> list[list[bool]]:
    """Return a 7×48 boolean matrix marking slots where the user is free."""
    mask = [[False] * SLOTS_PER_DAY for _ in range(DAYS_PER_WEEK)]
    for w in windows:
        for s in range(w.start_slot, w.end_slot):
            mask[w.day][s] = True
    return mask


def iter_runs(mask_row: list[bool]) -> Iterator[tuple[int, int]]:
    """Yield ``(start, end)`` half-open ranges of ``True`` values in a row.

    Useful for turning the per-day availability mask into a list of
    contiguous windows, which CP-SAT can then place intervals inside.
    """
    start: int | None = None
    for i, v in enumerate(mask_row):
        if v and start is None:
            start = i
        elif not v and start is not None:
            yield start, i
            start = None
    if start is not None:
        yield start, len(mask_row)
