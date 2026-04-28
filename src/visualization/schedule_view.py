"""Render a weekly plan as matplotlib figure or plain text.

The schedule figure is a 7-day × 48-slot grid with colored boxes per
activity kind. It's used by both the CLI (saved to PNG) and the Streamlit
UI (embedded via st.pyplot).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

from src.config.settings import (
    DAY_NAMES,
    DAYS_PER_WEEK,
    SLOTS_PER_DAY,
    slot_to_time,
)
from src.models.domain import Plan
from src.models.enums import ActivityKind


_COLORS: dict[ActivityKind, str] = {
    ActivityKind.WORKOUT: "#ef4444",
    ActivityKind.MEAL: "#22c55e",
    ActivityKind.SLEEP: "#8b5cf6",
    ActivityKind.HYDRATION: "#0ea5e9",
    ActivityKind.RECOVERY: "#f59e0b",
    ActivityKind.IDLE: "#e5e7eb",
}


def render_schedule_to_figure(plan: Plan, path: Path | None = None):
    """Draw the weekly grid. Returns (fig, saved_path|None)."""
    fig, ax = plt.subplots(figsize=(12, 5))

    ax.set_xlim(0, SLOTS_PER_DAY)
    ax.set_ylim(0, DAYS_PER_WEEK)
    ax.invert_yaxis()

    # grid
    for s in range(0, SLOTS_PER_DAY + 1, 4):   # every 2h
        ax.axvline(s, color="#e5e7eb", linewidth=0.5, zorder=0)
    for d in range(DAYS_PER_WEEK + 1):
        ax.axhline(d, color="#e5e7eb", linewidth=0.5, zorder=0)

    # blocks
    for b in plan.schedule_blocks:
        color = _COLORS.get(b.kind, "#64748b")
        rect = mpatches.Rectangle(
            (b.start_slot, b.day),
            b.end_slot - b.start_slot,
            1.0,
            facecolor=color,
            edgecolor="black",
            linewidth=0.5,
            alpha=0.75,
        )
        ax.add_patch(rect)
        # Label: only if block wide enough (>= 2 slots)
        if b.end_slot - b.start_slot >= 2:
            ax.text(
                b.start_slot + 0.2,
                b.day + 0.5,
                b.label[:28],
                fontsize=7,
                va="center",
            )

    # x-ticks every 2h
    tick_slots = list(range(0, SLOTS_PER_DAY + 1, 4))
    ax.set_xticks(tick_slots)
    ax.set_xticklabels([slot_to_time(s % SLOTS_PER_DAY) for s in tick_slots],
                       rotation=0, fontsize=8)
    ax.set_yticks([d + 0.5 for d in range(DAYS_PER_WEEK)])
    ax.set_yticklabels(DAY_NAMES)
    ax.set_title(f"Weekly plan — {plan.user_name}")

    # legend
    legend_handles = [
        mpatches.Patch(color=c, label=k.value)
        for k, c in _COLORS.items() if k != ActivityKind.IDLE
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              bbox_to_anchor=(1.18, 1.0), fontsize=8)

    plt.tight_layout()
    saved = None
    if path is not None:
        saved = Path(path)
        fig.savefig(saved, dpi=150, bbox_inches="tight")
    return fig, saved


def schedule_to_text(plan: Plan) -> str:
    """A compact textual weekly schedule for terminal output."""
    if not plan.schedule_blocks:
        return "(no scheduled blocks; nutrition-only plan)"
    lines = [f"Weekly plan for {plan.user_name}"]
    for d in range(DAYS_PER_WEEK):
        day_blocks = [b for b in plan.schedule_blocks if b.day == d]
        day_blocks.sort(key=lambda b: b.start_slot)
        lines.append(f"  {DAY_NAMES[d]}")
        if not day_blocks:
            lines.append("    (empty day)")
            continue
        for b in day_blocks:
            lines.append(
                f"    {slot_to_time(b.start_slot)}-{slot_to_time(b.end_slot % SLOTS_PER_DAY)} "
                f"[{b.kind.value}] {b.label}"
            )
    dp_totals = [f"  Day {dp.day}: {dp.calories_total} kcal, "
                 f"{dp.protein_total_g}g P, {dp.cost_cents}c"
                 for dp in plan.daily_plans if dp.calories_total > 0]
    if dp_totals:
        lines.append("")
        lines.append("Daily totals:")
        lines.extend(dp_totals)
    lines.append(f"Weekly cost: {plan.weekly_cost_cents}c "
                 f"(${plan.weekly_cost_cents / 100:.2f})")
    return "\n".join(lines)
