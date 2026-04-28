"""Render a weekly plan as matplotlib figure or plain text.

The schedule figure is a 7-day × 48-slot grid with colored boxes per
activity kind. It's used by both the CLI (saved to PNG) and the Streamlit
UI (embedded via st.pyplot). The renderer is tuned for legibility on a
projector: sleep is drawn as an ambient background band (it dominates
the day numerically but adds no information to look at), workouts and
meals are drawn as foreground blocks with labels positioned to avoid
collisions with neighbouring activities.
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


# Modern palette tuned for projection (slightly desaturated, high contrast).
_COLORS: dict[ActivityKind, str] = {
    ActivityKind.WORKOUT:   "#dc2626",   # red-600
    ActivityKind.MEAL:      "#16a34a",   # green-600
    ActivityKind.SLEEP:     "#7c3aed",   # violet-600 (drawn translucent)
    ActivityKind.HYDRATION: "#0284c7",   # sky-600
    ActivityKind.RECOVERY:  "#d97706",   # amber-600
    ActivityKind.IDLE:      "#e5e7eb",
}


def _short_label(label: str) -> str:
    """Trim labels for figure rendering.

    Drop meal-type prefix ("breakfast: ..." -> "breakfast") and the
    trailing "(intensity)" suffix from workout names since intensity is
    encoded by the bar colour.
    """
    if ":" in label:
        head, _, tail = label.partition(":")
        head = head.strip()
        if head in {"breakfast", "lunch", "dinner", "snack",
                    "pre_workout", "post_workout"}:
            return head
        return tail.strip()[:24]
    if "(" in label:
        return label.split("(")[0].strip()
    return label[:22]


def _fit_workout_label(label: str, width_slots: float) -> tuple[str, int]:
    """Pick a label string + fontsize that fits inside a workout bar.

    width_slots is in 30-min units. ~3 chars fit per slot at fontsize=8.
    """
    short = _short_label(label)
    capacity_8 = max(1, int(width_slots * 3.0))
    if len(short) <= capacity_8:
        return short, 8
    # Try a smaller font.
    capacity_7 = max(1, int(width_slots * 3.5))
    if len(short) <= capacity_7:
        return short, 7
    # Fall back to first word + ellipsis.
    first = short.split()[0]
    capacity_6 = max(1, int(width_slots * 4.0))
    if len(first) <= capacity_6:
        return first, 6
    return first[: max(2, capacity_6 - 1)] + "…", 6


def render_schedule_to_figure(plan: Plan, path: Path | None = None):
    """Draw the weekly grid. Returns (fig, saved_path|None)."""
    # Use a clean sans-serif system font instead of matplotlib's default
    # DejaVu Sans, which looks dated next to modern slide decks.
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [
            "Helvetica Neue", "Inter", "SF Pro Text", "Helvetica",
            "Arial", "DejaVu Sans",
        ],
    })
    # Wider canvas: 13" wide gives meal labels room without truncation.
    fig, ax = plt.subplots(figsize=(13, 6.2))

    ax.set_xlim(0, SLOTS_PER_DAY)
    ax.set_ylim(0, DAYS_PER_WEEK)
    ax.invert_yaxis()

    # ---- background grid: every 2 hours, very light ---------------------
    for s in range(0, SLOTS_PER_DAY + 1, 4):
        ax.axvline(s, color="#f1f5f9", linewidth=0.6, zorder=0)
    for d in range(DAYS_PER_WEEK + 1):
        ax.axhline(d, color="#e2e8f0", linewidth=0.7, zorder=0)

    # Sort blocks so sleep paints first (becomes background), then meals,
    # then workouts on top (which is the rare event we care about most).
    order = {
        ActivityKind.SLEEP: 0,
        ActivityKind.HYDRATION: 1,
        ActivityKind.RECOVERY: 2,
        ActivityKind.MEAL: 3,
        ActivityKind.WORKOUT: 4,
    }
    blocks = sorted(
        plan.schedule_blocks,
        key=lambda b: (order.get(b.kind, 0), b.day, b.start_slot),
    )

    # Stash workouts/meals per day for label-collision handling.
    fg_by_day: dict[int, list] = {d: [] for d in range(DAYS_PER_WEEK)}

    for b in blocks:
        color = _COLORS.get(b.kind, "#64748b")
        width = max(0.5, b.end_slot - b.start_slot)

        if b.kind == ActivityKind.SLEEP:
            # Draw sleep as a translucent ambient band (full row height).
            rect = mpatches.Rectangle(
                (b.start_slot, b.day),
                width, 1.0,
                facecolor=color, edgecolor="none",
                alpha=0.14, zorder=1,
            )
            ax.add_patch(rect)
            continue

        if b.kind == ActivityKind.MEAL:
            # Slim, centred bar for meals (their default duration is 1 slot,
            # which would otherwise be invisible). Label drawn beneath.
            rect = mpatches.Rectangle(
                (b.start_slot, b.day + 0.25),
                width, 0.50,
                facecolor=color, edgecolor=color,
                linewidth=0.6, alpha=0.85, zorder=3,
            )
            ax.add_patch(rect)
            fg_by_day[b.day].append(("meal", b, width))
            continue

        if b.kind == ActivityKind.WORKOUT:
            # Full-height bar so workouts read as the day's anchor event.
            rect = mpatches.Rectangle(
                (b.start_slot, b.day + 0.08),
                width, 0.84,
                facecolor=color, edgecolor="#7f1d1d",
                linewidth=0.8, alpha=0.92, zorder=4,
            )
            ax.add_patch(rect)
            fg_by_day[b.day].append(("workout", b, width))
            continue

        # Hydration / recovery: small markers along the top edge of the
        # row, so they read as a recurring "always-on" stripe that never
        # competes with meal or workout labels.
        rect = mpatches.Rectangle(
            (b.start_slot, b.day + 0.02),
            width, 0.075,
            facecolor=color, edgecolor=color,
            linewidth=0, alpha=0.95, zorder=2,
        )
        ax.add_patch(rect)

    # ---- labels with collision avoidance --------------------------------
    # Workout labels go INSIDE the bar (auto-shrunk + truncated to fit) so
    # adjacent workouts on the same day cannot collide horizontally. Meal
    # labels go BELOW the day row; adjacent meals stagger their offset so
    # short labels like "snack" + "lunch" don't sit on top of each other.
    for d in range(DAYS_PER_WEEK):
        events = sorted(fg_by_day[d], key=lambda e: e[1].start_slot)
        last_below_end = -10
        last_below_offset = 0.92
        for kind, b, width in events:
            cx = (b.start_slot + b.end_slot) / 2
            if kind == "workout":
                label, size = _fit_workout_label(b.label, width)
                ax.text(
                    cx, b.day + 0.50, label,
                    fontsize=size, color="white", fontweight="bold",
                    ha="center", va="center", zorder=6,
                )
            else:  # meal
                label = _short_label(b.label)
                # Stagger adjacent meal labels (within ~2 hours of each
                # other) onto two rows so short tags don't overlap.
                if b.start_slot < last_below_end + 5:
                    offset = 1.05 if last_below_offset < 1.0 else 0.92
                else:
                    offset = 0.92
                ax.text(
                    cx, b.day + offset, label,
                    fontsize=7, color="#166534",
                    ha="center", va="top", zorder=6,
                )
                last_below_end = b.end_slot
                last_below_offset = offset

    # ---- axes ------------------------------------------------------------
    tick_slots = list(range(0, SLOTS_PER_DAY + 1, 4))
    ax.set_xticks(tick_slots)
    ax.set_xticklabels(
        [slot_to_time(s % SLOTS_PER_DAY) for s in tick_slots],
        rotation=0, fontsize=8, color="#475569",
    )
    ax.set_yticks([d + 0.5 for d in range(DAYS_PER_WEEK)])
    ax.set_yticklabels(DAY_NAMES, fontsize=9, color="#334155")
    for spine in ax.spines.values():
        spine.set_edgecolor("#cbd5e1")
        spine.set_linewidth(0.7)
    ax.tick_params(length=0)

    ax.set_title(
        f"Weekly plan — {plan.user_name}",
        fontsize=13, fontweight="bold", color="#0f172a", pad=12,
    )

    # ---- legend ----------------------------------------------------------
    legend_handles = [
        mpatches.Patch(color=_COLORS[ActivityKind.WORKOUT], label="workout"),
        mpatches.Patch(color=_COLORS[ActivityKind.MEAL], label="meal"),
        mpatches.Patch(facecolor=_COLORS[ActivityKind.SLEEP], alpha=0.25,
                       label="sleep"),
        mpatches.Patch(color=_COLORS[ActivityKind.HYDRATION], label="hydration"),
    ]
    leg = ax.legend(
        handles=legend_handles,
        loc="upper right",
        bbox_to_anchor=(1.0, 1.10),
        ncol=4,
        frameon=False,
        fontsize=9,
    )
    for txt in leg.get_texts():
        txt.set_color("#334155")

    plt.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.10)
    saved = None
    if path is not None:
        saved = Path(path)
        fig.savefig(saved, dpi=160, bbox_inches="tight",
                    facecolor="white")
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
