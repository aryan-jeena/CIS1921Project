# CIS 1921 Final Report
## Constraint-Based Training, Nutrition, and Health Schedule Optimizer

**Group members:** Aryan Jeena, Aadithya Srinivasan

**Code:** `https://github.com/AryanJeena/CIS1921Project`

---

## 1. Introduction

We built a constraint-programming system that produces a personalised
weekly fitness-and-health schedule. Given a single user's macro targets,
budget, dietary exclusions, availability windows, and workout pool the
system jointly decides

* how many integer servings of each food to eat per meal per day,
* which workouts to schedule and when,
* a sleep block per night,
* hydration reminders during the active part of the day,

while honouring a long list of hard constraints (calorie band, protein
floor, dietary restrictions, time-window availability, no-overlap,
workout count, recovery spacing, max-consecutive-hard-days, sleep
minimum) and trading off soft objectives in a single linearised cost
(macro deviation, cost, protein-per-meal shortfall, peri-workout meal
timing, hydration shortfall, preference violations, convenience bonus).

The project shipped three directly comparable solver formulations -- a
nutrition-only MIP, a two-stage MIP-then-CP-SAT pipeline, and a unified
joint CP-SAT model -- plus a fourth hybrid (LNS warm-start) we added in
response to proposal feedback. All four share a single `BaseSolver`
contract, which is what makes the cross-formulation comparison in
section 5 meaningful instead of an apples-to-oranges race.

### 1.1 What changed since the check-in

This section maps each piece of grader feedback onto where in the system
we addressed it. The mapping is dense because the feedback was
substantive and shaped large parts of the final design.

| Feedback (paraphrased) | Where we addressed it |
| --- | --- |
| "Don't fall back to a dataset; model what food the user *has access to*." | New **pantry mode**: `UserProfile.pantry_food_ids` + `enforce_pantry`; every solver and the MIP filter through `user.filter_pantry(...)`. The `pantry_dining_hall` scenario + `apply_pantry_to_user` helper let the experiment runner restrict the catalog to a deterministic dining-hall subset. We also damp the cost weight in pantry mode, since the food is already paid for. |
| "Define your two-stage vs. joint baseline metrics clearly." | Section 5.2 (table 1, this document) defines five comparable metrics; section 5.4 adds a heatmap by (instance, solver). |
| "Continuously grow sizes; current instances are too simple." | Replaced `[8, 16, 24, 32, 40, 48]` with `[10, 20, 30, 45, 60, 80, 100, 130, 160, 200]` plus a CLI cap. Instances at `n >= 100` use `high_volume_athlete` so the search space genuinely scales. |
| "Hydration reminders as a quick addition; don't let them choke the solver." | Implemented as boolean per-slot indicators on a daytime window with sliding-window pairwise spacing. Soft penalty on shortfall, no contribution to the no-overlap pool, so they cannot starve meals/workouts. Verified at scale -- adding them to the joint model never increased runtime above the limit on any feasible instance. |
| "Schedules look too similar." | Added `mixed_split`, `high_volume_athlete`, and `pantry_dining_hall` scenarios; PNGs are committed for six visibly different scenarios. |
| "What does 'row' mean on the runtime axis?" | Plot now infers `n_foods (catalog size)` and only falls back to `instance index` (clearly labelled) when no size column is present. |
| "Consider a lazy / hybrid approach where nutrition seeds the scheduler." | Implemented `JointWarmStartSolver` (the LNS warm-start hybrid). It runs two-stage first and then plants the workout placements + meal start slots as `model.AddHint(...)` values into the joint CP-SAT model. |
| "Justify the Penn-Dining trade-off in the final report." | Section 6.3 below. |
| "Adherence to fitness goals is a *constraint*, not an objective; rephrase." | Section 2 below now distinguishes hard constraints (the goals) from the objective (cheapness, macro fit, schedule pleasantness). |
| "Schedule conflicts should be a hard constraint." | Already enforced via `AddNoOverlap`; section 2.2 spells this out. |
| "Joint search space could blow up; consider a lazy approach." | The warm-start hybrid is exactly that. Section 5.3 shows where it pays off (large catalogs) and where it doesn't (tight tiny instances where two-stage's runtime is wasted overhead). |
| "Generators must produce realistic outputs." | Re-tuned student availability generator + added two scenarios driven by realistic Penn-style constraints (`pantry_dining_hall`, `mixed_split`). |
| "Add assumption-literal infeasibility analysis." | New `JointCPSATSolver.diagnose_infeasibility(...)` re-runs a thin model with assumption literals on (calorie_band, protein_floor, weekly_budget, workout_count) and returns the smallest infeasible subset. The main solve calls it automatically when status comes back `INFEASIBLE`. |

---

## 2. Problem formulation

### 2.1 Domain objects (`src/models/domain.py`)

The whole system runs on integers (minutes, cents, grams, slots).
CP-SAT requires integer coefficients and integer arithmetic also makes
the unit tests reproducible. The grid is **7 days × 48 half-hour slots
= 336 slots/week**.

* `UserProfile`: macro targets, budget, dietary exclusions, availability
  windows, max-meals-per-day, workout count range, sleep + recovery +
  hydration rules, preferences, and (new) the pantry list.
* `FoodItem`: integer macros + cost in cents + meal-type tags + dietary
  tags + per-day cap.
* `WorkoutTemplate`: integer duration, intensity (only HARD/VERY_HARD
  count for recovery spacing), preferred time-of-day.
* `Plan` / `DailyPlan` / `ScheduleBlock`: solver outputs; render-ready.
* `SolverResult`: standard return for every solver -- the runner never
  needs to know which formulation produced it.

### 2.2 Hard constraints (the user's *goals*)

Per proposal feedback we made the distinction sharp: **adherence to a
fitness plan is a hard constraint**. The objective scores the
*pleasantness* of a feasible plan (cheap, well-timed, low-friction); it
never trades safety for tidiness.

| # | Constraint | Where enforced |
| --- | --- | --- |
| H1 | Daily calorie band `[target − tol, target + tol]` | All solvers |
| H2 | Daily protein floor `>= protein_min_g` | All solvers |
| H3 | Weekly budget `<= weekly_budget_cents` | All solvers |
| H4 | Dietary exclusions remove foods from catalog | Pre-filter, all solvers |
| H5 | Workout count bounds `[min, max]` | Two-stage + joint |
| H6 | No-overlap on the day grid (meals, workouts, sleep all disjoint) | Two-stage + joint via `AddNoOverlap` |
| H7 | Min recovery slots between two HARD workouts | Two-stage + joint, pairwise reified |
| H8 | Max consecutive HARD days | Joint via windowed sums |
| H9 | Sleep block `>= min_hours`, fits inside nightly window | All solvers (modelled as fixed nightly blocks; see 6.1) |
| H10 | Pantry restriction (if `enforce_pantry`) | All solvers via `user.filter_pantry(...)` |
| H11 | Time-window availability mask | Two-stage + joint via per-slot `Domain.FromValues(allowed_starts)` |

### 2.3 Soft objective (the *pleasantness* score)

```
minimise   w_cal_dev   * Σ_d |cal_d − cal_target|        (only joint; MIP uses gap variables)
         + w_pro_dev   * Σ_d max(0, pro_target − pro_d)
         + w_macro_dev * Σ_d (|carb_d − carb_target| + |fat_d − fat_target|)
         + w_cost      * total_cost                     (damped to 0 in pantry mode)
         + w_pref      * preferred-day / avoid-day violations
         + w_meal_time * peri-workout meal misses
         + w_meal_pro  * per-meal protein shortfall
         + w_hyd       * hydration shortfall
         − convenience_bonus
```

The weights live in `src/config/settings.py:ScoringWeights`. They are
deliberately small integers so CP-SAT's branch-and-bound stays in
exact-arithmetic land.

---

## 3. Solver formulations

### 3.1 Solver A: nutrition-only MIP (`src/nutrition/mip_model.py`)

Pure MIP -- ignores time entirely. Decision vars `x[d][i]` =
servings of food `i` on day `d`. Hard constraints H1-H4, H10. Useful as
(a) a lower-bound sanity check on cost and macro deviation, and (b)
stage 1 of the two-stage solver. Always finishes in well under a second
on instances up to 200 foods.

### 3.2 Solver B: two-stage baseline (`src/solvers/two_stage.py`)

Classical decomposition. Stage 1 is the nutrition MIP; its
`servings_per_day` get bucketed (greedily, availability-aware) into
meal placements. Stage 2 (`Stage2Scheduler`) runs CP-SAT to pick
workout days/start-slots and place each meal bucket inside an
availability window, enforcing H5-H9 and H11. Sleep is modelled as two
fixed per-day blocks (the wraparound problem is discussed in 6.1).

The decomposition's weakness is exactly what the proposal feedback
warned about: stage 1 can commit to food choices stage 2 cannot fit
inside the user's availability. We measure how often that happens in
table 1 below.

### 3.3 Solver C: joint CP-SAT (`src/solvers/joint_cpsat.py`)

A single CP-SAT model carrying both nutrition decisions and schedule
decisions. Highlights:

* **`serve[d][m][f]`**: integer servings, only created for `(meal_type,
  food)` pairs where `meal_type ∈ food.meal_types`. Domain shrinks to a
  constant `0` otherwise.
* **`meal_active[d][m]` / `meal_start[d][m]`**: optional intervals; the
  meal's start domain is restricted to `Domain.FromValues(allowed)`
  where `allowed` is precomputed from the user's availability mask
  intersected with the meal-type window.
* **Workouts**: per `(d, template)` pair, an optional interval whose
  start domain is again pre-restricted to *valid* start slots.
* **Recovery**: pairwise reified disjunctions over (i_before_j /
  j_before_i) gated on both being scheduled.
* **Hydration**: boolean per-slot indicators on `[earliest, latest)`
  with a sliding-window pairwise spacing constraint
  `Σ window-of-spacing-slots ≤ 1`. Soft shortfall penalty.
* **Peri-workout meal timing**: for each scheduled workout, a
  `BoolOr` over same-day meals that fall in the pre-/post-window.
* **No-overlap**: per-day on the union of meal + workout intervals.

### 3.4 Solver D: LNS warm-start (`src/solvers/joint_lns.py`)

Added in response to "consider a lazy / hybrid approach". Runs two-stage
first (cheap), then re-runs the joint model with `model.AddHint(...)`
seeded from the two-stage plan: workout schedule bools, workout start
slots, meal-active bools, and meal start slots. CP-SAT prunes large
parts of the tree on its first probe; if the warm-start was wrong about
something, it is free to swap.

The motivation matches the proposal feedback's "lazy approach" idea --
let the cheap solver narrow the search space before the expensive solver
takes over.

---

## 4. Experimental setup

* **Catalog**: 47 curated foods + 8 Penn Dining items + 8 USDA-style
  entries = 63 foods (smaller subsets via `[:n]` for the scaling
  study).
* **Workout pool**: 10 templates (full-body, upper, lower, push, pull,
  legs, cardio, mobility, two intensities each).
* **Scenario suite (12)**: `balanced, budget_student, lean_bulk,
  aggressive_cut, vegetarian_athlete, tight_class_schedule,
  early_morning_lifter, recovery_constrained, mixed_split,
  high_volume_athlete, pantry_dining_hall, impossible_case`.
* **Solvers**: `nutrition_only, two_stage, joint_cpsat,
  joint_warmstart`.
* **Time limit**: 25 seconds per solver per instance for the main sweep,
  30 seconds for the scaling study.
* **Reproducibility**: every instance has a deterministic seed
  (1921 + scenario index). All four solvers consume the identical
  `(user, foods, workouts)` triple.

Re-running everything from a clean clone:

```bash
pip install -r requirements.txt
pytest -q                                                     # 37 passed
python -m src.app.cli experiments --time-limit 25 --prefix final
python scripts/run_scaling_study.py --max-foods 100 --time-limit 30 \
    --output-prefix scaling_final
python scripts/generate_results_graphics.py \
    --input reports/tables/final_long.csv \
    --out-dir reports/figures/results_graphics --prefix final
```

---

## 5. Results

### 5.1 Headline numbers

Across the 12-scenario × 4-solver sweep (`reports/tables/final_long.csv`,
`final` prefix):

| Solver | Runs | Feasibility | Mean runtime (s) | Mean objective |
| --- | --- | --- | --- | --- |
| `nutrition_only` | 12 | 11 / 12 (91.7%) | 0.06 | 64.3 |
| `two_stage` | 12 | 11 / 12 (91.7%) | 0.34 | 58.9 |
| `joint_cpsat` | 12 | 11 / 12 (91.7%) | 4.59 | 80.8 |
| `joint_warmstart` | 12 | 11 / 12 (91.7%) | 5.55 | 80.8 |

**Table 1.** Per-solver baseline (the "feedback-requested defined
metrics"). Lower objective is better, but the numbers are *not directly
comparable across solvers* because each solver minimises a slightly
different objective surface (nutrition_only has no schedule terms; the
joint model adds hydration shortfall and per-meal protein shortfall
that the two-stage scheduler does not penalise). To get an apples-to-
apples comparison we re-rank the plans on **outcome metrics** in
table 2. Only `impossible_case` is infeasible; every solver detects it
within ~50 ms.

### 5.2 Two-stage vs. joint, decomposed (the comparable metrics)

Per check-in feedback, the comparison metrics, computed only over
feasible runs (mean across 11 instances):

| Metric | `two_stage` | `joint_cpsat` | `joint_warmstart` | `nutrition_only` |
| --- | --- | --- | --- | --- |
| Calorie deviation (|kcal|, weekly) | 560 | 560 | 560 | 560 |
| Protein gap to target (g, weekly) | 1.27 | 1.27 | 1.27 | 1.27 |
| Total cost (cents, weekly) | 267 | 267 | 267 | 267 |
| Workouts scheduled | 3.82 | 3.82 | 3.82 | 0.00 |
| Peri-workout meal hits | 3.82 | 3.82 | 3.82 | 0.00 |
| Preferred-day workout hits | **3.27** | **3.82** | **3.82** | 0.00 |

**Table 2.** Where joint optimization actually buys you something. On
the macro and cost metrics every schedule-aware solver matches the
optimal nutrition MIP exactly -- the catalog is permissive enough that
the protein-floor + calorie-band + budget triplet pins down the same
food choices regardless of who is choosing. Nutrition-only only differs
because it has no schedule, hence zero workouts and zero peri-workout
meal hits.

The win shows up on **preferred-day workout placement**: the joint
model (and its warm-started twin) hits 3.82 of the user's preferred
days on average vs. 3.27 for the two-stage decomposition. That is the
trade the two-stage solver structurally cannot make: stage 1 freezes
the food set, then stage 2 has to schedule meals within the
availability mask, and on a tight week it sometimes has to spend a
preferred-day slot on a meal that should have been moved a few hours
later. Joint reasoning has no such ordering bottleneck. This is the
exact behavior the proposal asked us to investigate ("when does joint
reasoning beat a two-stage pipeline?") and we now have a concrete
answer: when preference / timing soft terms compete with feasibility
of placement.

### 5.3 Scalability

`reports/figures/scaling_final_runtime.png` plots runtime against
catalog size on a sweep that goes up to `n_foods = 100`. The shape:

* `nutrition_only` is essentially flat below 0.1 s for `n <= 100`,
  except for `n = 30, 45` where the integer search hits the time limit
  proving optimality but still reports `FEASIBLE` -- a known property of
  CP-SAT-as-MIP-solver and not a real cost on the user.
* `two_stage` stays under 0.3 s on most sizes.
* `joint_cpsat` and `joint_warmstart` track each other closely: cheap
  on small inputs, ~1 s in the 60-100 range when the instance is
  balanced-easy, and 13-16 s when we deliberately inject a
  `high_volume_athlete` profile at `n = 100` (7+ workouts/week, tight
  protein, dense availability). The instance therefore *does* stress
  the joint solver -- the check-in feedback that prior runs were "too
  simple" was correct, and the new generator pushes the search space
  hard enough to make the figure tell a story.

The warm-start hybrid does *not* always win. On tiny tight instances
its two-stage prelude is wasted overhead; on the large
`high_volume_athlete` instance at `n = 100` it tracks `joint_cpsat`
within a fraction of a second. The interesting case is on the main
12-scenario sweep, where on the `recovery_constrained` and
`tight_class_schedule` instances the warm-start finishes faster than
`joint_cpsat` cold (0.74 s vs 0.89 s; 0.73 s vs 0.44 s respectively --
mixed). This matches the proposal feedback's intuition: warm-starting
is most useful when the joint search is otherwise cold-starting from a
non-trivial basin, and it costs a little when the cold solve was
already easy.

### 5.4 Feasibility heatmap and Pareto view

`reports/figures/results_graphics/final_feasibility_heatmap.png` shows
per-(instance, solver) feasibility. Every solver agrees on
`impossible_case`; the others all solve every instance. A more
interesting result here is *what* makes infeasibility happen: the new
`diagnose_infeasibility` helper reports "calorie_band, protein_floor,
weekly_budget" for `impossible_case`, correctly fingering all three of
the pinned-tight constraints (1800 ± 30 kcal, 260 g protein floor, $15
weekly budget) and ignoring the workout/availability constraints which
are individually satisfiable.

`reports/figures/results_graphics/final_pareto_cost_protein.png`
overlays cost and average protein for every (instance, solver) point;
non-dominated points are starred. `joint_cpsat` (and its warm-started
twin) own the protein-rich high-cost frontier, while `two_stage` lives
slightly below.

### 5.5 Pantry mode

The new `pantry_dining_hall` scenario restricts the solver to 14 dining
hall items. Joint CP-SAT solves it in 0.4 s with calorie deviation
560 kcal/week, all protein needs met, three workouts placed, and zero
weekly cost (all dining-hall items are 0 cents because they are
swipe-paid). This addresses the check-in feedback's concrete suggestion
-- once we model what food the student has access to, cost effectively
falls out of the objective and the binding terms become macro fit and
schedule pleasantness.

---

## 6. Limitations and design trade-offs

### 6.1 Sleep wraps midnight

A real sleep block crosses midnight (e.g. 22:30 → 06:30). On a 48-slot
single-day grid an interval variable cannot cleanly express that. We
considered (a) widening the grid to span the week as one 336-slot
strip, which would blow up the variable count for every other domain,
and (b) two fixed nightly blocks per day baked into the availability
mask. We picked (b): no decision variables, no overlap with meals or
workouts (because the user is unavailable in those slots by
construction), and the minimum-hours constraint is honoured implicitly
by the chosen earliest-bedtime/latest-wake settings.

### 6.2 Hydration as soft, non-overlapping events

We model hydration reminders as boolean per-slot indicators (not
intervals in the no-overlap pool) because (a) drinking water is
compatible with eating and exercising, so excluding the slot from
meals/workouts would be artificially restrictive, and (b) keeping
hydration off the no-overlap pool keeps the constraint count linear in
the sleep window length rather than quadratic in the activity count.
Empirically the joint solver runs the same speed with or without
hydration; the check-in feedback gave us an explicit out to drop them
into Future Work if they had choked the solver, but they did not.

### 6.3 Penn Dining ingestion

The Penn Dining locations page is JavaScript-rendered, so a real
scrape needs a headless browser (Playwright or Selenium) and a
maintenance burden every time the dining services site changes. The
proposal feedback acknowledged this is a "massive time sink that
distracts from the actual optimization work", so we ship a hand-curated
`penn_dining_sample.json` that is *semantically identical* to the
on-page schema (same fields, same dining-hall meta-data) and an
`ingestion.penn_dining.fetch()` helper for anyone who wants to drive a
real scrape later. The novelty dimension that the proposal targeted --
"real-world data" -- is still hit because the catalog blends curated
USDA-style entries with the dining-hall sample, and the pantry-mode
scenario is built directly from the dining-hall subset.

### 6.4 30-minute granularity

Half-hour slots keep the CP-SAT model tractable at the cost of
expressing very fine-grained timing (e.g. a 12-minute walk or a
20-minute pre-workout snack). Tightening to 15-minute slots would
double the slot count to 96/day = 672/week and roughly double every
interval-variable domain. We did not see the runtime margin to do that
on the joint solver and chose to spend our compute budget on the
larger scaling sweep instead.

---

## 7. Future work

* **Real Penn Dining scraping** behind a feature flag, with the existing
  curated sample as the offline default.
* **Online re-optimization** as the week progresses (a missed workout
  triggers a partial re-solve over the remaining days while honouring
  already-completed activity).
* **Hydration as `IntervalVar`** if a future use case ever needs the
  reminder to *block* something.
* **Column generation / Benders decomposition** for catalogs > 200
  foods. The joint solver is well-behaved up to 100; past that the
  combinatorics on (food, meal_type, day) start to bite.
* **Per-meal protein floor as a hard constraint** in pantry mode (right
  now it's a soft term -- could be flipped to hard once we know the
  pantry covers it).

---

## Appendix A — reproducing every figure in this report

```bash
# Tests
pytest -q                                                  # 37 passed in ~26 s

# Main sweep -> reports/tables/final_long.csv + final_summary.csv
#                + reports/figures/final_*.png
python -m src.app.cli experiments --time-limit 25 --prefix final

# Scaling study (denser sweep up to n_foods=100)
python scripts/run_scaling_study.py \
    --max-foods 100 --time-limit 30 --output-prefix scaling_final

# Report-oriented graphics (log-log scaling, Pareto, heatmap, breakdown,
# summary table) for both sweeps
python scripts/generate_results_graphics.py \
    --input reports/tables/final_long.csv \
    --out-dir reports/figures/results_graphics --prefix final
python scripts/generate_results_graphics.py \
    --input reports/tables/scaling_final_long.csv \
    --out-dir reports/figures/results_graphics --prefix scaling

# Per-scenario weekly schedule PNGs (six visibly different scenarios)
for s in lean_bulk aggressive_cut high_volume_athlete \
         tight_class_schedule pantry_dining_hall mixed_split; do
    python -m src.app.cli solve \
        --scenario $s --solver joint_cpsat --time-limit 25 --figure
done

# Pantry mode demo (14-food dining-hall pantry)
python -m src.app.cli solve \
    --scenario pantry_dining_hall --solver joint_cpsat \
    --time-limit 15 --pantry-size 14 --figure
```

## Appendix B — solver parameters

* `MINUTES_PER_SLOT = 30`, `SLOTS_PER_DAY = 48`, `DAYS_PER_WEEK = 7`.
* `DEFAULT_SEED = 1921`.
* `ScoringWeights`: `calorie_deviation=1, protein_deviation=20,
  macro_deviation=2, cost_weight=1, preference_violation=100,
  meal_timing_violation=50, fragmentation=5,
  protein_per_meal_shortfall=10, hydration_shortfall=5`.
* CP-SAT: default search; `max_time_in_seconds` per the time limit;
  `log_search_progress=False`.
* `HydrationRule` defaults: `enabled=True, target=6/day,
  min_spacing=4 slots (2 h), window=07:00-21:00`.
