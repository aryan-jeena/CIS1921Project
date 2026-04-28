# CIS 1921 Project Check-In

**Group Members:** Aryan Jeena, Aadithya Srinivasan
**Project Title:** Constraint-Based Training, Nutrition, and Health Schedule Optimizer

## Progress

The project runs end to end and is roughly eighty percent done. We have a typed domain model, three solver formulations behind a shared interface, a food catalog with a Penn Dining fallback and USDA support, a parameterized instance generator, a passing test suite, a batch experiment runner, and a Streamlit UI. Most of what is left is analysis and write-up rather than new modeling work. Every quantity the solvers see is an integer (minutes, cents, grams, and 30-minute slots), both because CP-SAT requires integer coefficients and because it makes our tests much easier to reason about. The calendar is a 7 by 48 grid, so one week of planning is 336 slots.

The three solvers are the heart of the project. The first, `nutrition_only`, is a pure MIP that decides only how many integer servings of each food to eat on each day. The second, `two_stage`, runs that same MIP and then hands its serving decisions to a CP-SAT scheduler that places meals, workouts, and sleep into the user's available time windows. The third, `joint_cpsat`, is a single CP-SAT model that decides servings, placements, and recovery spacing all at once. Keeping all three compatible lets us directly answer one of the questions from the proposal, namely when joint reasoning beats a two-stage pipeline. Hard and soft constraints stay clearly separated in the code. The hard side covers the calorie band, the daily protein floor, the weekly budget, dietary exclusions, availability windows, non-overlap, the workout count range, a minimum sleep block, and recovery gaps between hard workouts. The soft side lives in the objective and covers protein shortfall, absolute deviation of carbs and fat from target, total cost, avoid-day violations, preferred-day bonuses, peri-workout meal timing, and a small convenience term.

On data, we ship a 47-item curated catalog along with an 8-item Penn Dining sample so the project runs out of the box, with USDA FoodData Central wired in as a third source. The instance generator produces nine synthetic users by default, and the last of them, `impossible_case`, has deliberately contradictory constraints so we can confirm that every solver detects infeasibility rather than silently returning a broken plan. Six JSON presets in `configs/presets/` plus the Streamlit sidebar form both let users edit constraints without touching code.

All 32 of our unit tests pass in under 8 seconds. The suite covers config and domain validation, food-catalog filtering, feasibility and infeasibility detection for every solver, non-overlap on the scheduled week, budget enforcement, recovery spacing, and a roundtrip of the slot grid.

> **PLACE IMAGE 1 HERE:** Terminal screenshot of `pytest -v` showing "32 passed in 7.08s".

To show that the three formulations are directly comparable, we ran `python -m src.app.cli demo --time-limit 15` on an auto-generated balanced user carrying 56 foods and 10 workouts. All three solvers returned `OPTIMAL`. Nutrition-only finished in 0.08 seconds, two-stage in 0.19, and joint CP-SAT in 0.69. The joint solver is slowest because it reasons over meal intervals across 56 foods plus optional workout intervals plus sleep blocks in one model, and that ordering is exactly what we expected. Nutrition-only reports zero workouts scheduled, which is not a bug but the point of the comparison: that model simply does not place workouts, and that is part of why the more expensive joint model is worth its cost.

> **PLACE IMAGE 2 HERE:** Terminal screenshot of the three-solver demo output.

Running `python -m src.app.cli solve --preset lean_bulk --solver joint_cpsat --time-limit 20 --figure` returned `OPTIMAL` in 1.14 seconds with an objective of -203. The resulting plan has four workouts, two of them hard and separated by the required recovery gap, and averages 3120 kcal, 202 g protein, 368 g carbs, and 92 g fat per day. Weekly cost came out to zero cents because the solver stacked Penn Dining swipe items, which our catalog prices at zero since they are already covered by the meal plan. The `--figure` flag wrote the schedule to `reports/figures/schedule_lean_bulk_joint_cpsat.png`.

> **PLACE IMAGE 3 HERE:** Terminal screenshot of the `lean_bulk` solve showing Status, Metrics, the full Weekly plan, and Daily totals.
>
> **PLACE IMAGE 4 HERE:** The matplotlib PNG at `reports/figures/schedule_lean_bulk_joint_cpsat.png`.

To check that the system fails gracefully, we ran the joint solver on the `infeasible_demo` preset. It returned `INFEASIBLE` in 0.01 seconds with the message "No workout template has a valid start slot inside the user's availability." That is the behavior we promised in the proposal: either a valid plan or a reason why none exists.

> **PLACE IMAGE 5 HERE:** Terminal screenshot of the `infeasible_demo` run.

The full experiment sweep, run with `python -m src.app.cli experiments --time-limit 15 --prefix checkin`, evaluates all nine scenarios against all three solvers for a total of 27 runs. Twenty-four came back `OPTIMAL`, and the other three are all `INFEASIBLE` on `impossible_case` across every solver, which is the expected behavior since that scenario was designed to be unsolvable. The sweep writes two CSVs and five figures to `reports/`. Two observations from the results are worth carrying into the final report. First, joint CP-SAT runs between two and one hundred times slower than nutrition-only but never exceeds five seconds on any feasible instance. Second, `aggressive_cut` produces the largest weekly calorie deviation at 2506, because its calorie band is tight relative to the granularity of the catalog, which makes it a nice example of a constraint that makes instances harder without making them infeasible.

> **PLACE IMAGE 6 HERE:** Terminal screenshot of the `experiments` run with the full results table.
>
> **PLACE IMAGE 7 HERE:** `reports/figures/checkin_runtime.png`.
>
> **PLACE IMAGE 8 HERE:** `reports/figures/checkin_feasibility.png`.

The Streamlit UI launches with `python scripts/launch_ui.py` and is intentionally minimal, since the course document says the frontend can be scrappy and effort should go into the optimization work. The sidebar lets the user pick a scenario or a preset, override every nutrition target, change workout count bounds, toggle dietary exclusions, choose the solver, and set a time limit. After clicking Solve, the main panel shows status, runtime, objective, and a feasibility badge, followed by a matplotlib weekly-schedule grid and a per-day breakdown table with calories, macros, cost, workout count, and meal count.

> **PLACE IMAGE 9 HERE:** Full Streamlit screenshot with the sidebar visible on the left and Status plus the Weekly schedule on the right.
>
> **PLACE IMAGE 10 HERE:** Streamlit zoomed view showing the weekly schedule grid with the legend on the right and the Daily breakdown table underneath.

## Changes to scope

We have stayed faithful to the proposal's overall goals, but three things changed during implementation and each one reflected a real trade-off rather than a feature being dropped. The first is sleep modeling. The proposal treated sleep as a scheduling variable, but sleep almost always crosses midnight (for example 22:30 to 06:30), and a single-day interval variable on a 48-slot grid cannot cleanly express a wraparound interval. Rather than widen the grid and blow up the variable count, we model sleep as two fixed per-day blocks that are baked into the user's availability mask, so non-overlap with meals and workouts is enforced implicitly and the minimum-hours constraint is still honored. The second change is Penn Dining ingestion. The real pages are JavaScript-rendered, so scraping them properly would need a headless browser, which is a lot of infrastructure for modest gain. We ship a bundled `penn_dining_sample.json` that is semantically identical to what we would scrape, the parser's `fetch()` method is still in place for anyone who extends the pipeline later, and the catalog still includes USDA-style entries and curated sample data, so the real-world-data novelty dimension is still covered. The third change is that hydration reminders are not yet placed as scheduled events. The `HydrationRule` model is in place and used as a soft target count, but placing reminders in the CP-SAT schedule is still to do, and we are tracking it as a pending item on the remaining-tasks list rather than pretending it is done. None of these changes weakens our novelty claim. We still cover real-world data, three comparable solver implementations, a parameterized instance generator, and user-configurable constraints, which is four of the Option 2 bullets instead of the required three.

## Remaining tasks

Six items are left. The scaling study comes first: `scripts/run_scaling_study.py` is ready to run, and we will sweep the food catalog over roughly 20, 40, 60, and 80 items and workouts over 5, 10, and 15, then plot runtime against problem size for each solver. This directly answers a proposal question about solver behavior as instances grow, and we expect it to produce some of the best material for the final report. We plan to have this done in the next two days. Next is adding hydration reminders as single-slot events in the joint CP-SAT model with minimum-spacing constraints and a missed-reminder penalty in the objective, which should be on the order of fifty lines of code. After that comes better infeasibility analysis using CP-SAT assumption literals, so that when a model is infeasible we can return a minimal unsatisfiable subset of constraints as a human-readable message instead of a generic status. The largest remaining time cost is the final report itself; a draft outline lives at `reports/draft_outline.md`, and we plan to flesh it into a full write-up covering modeling choices, solver trade-offs, runtime scaling, the feasibility story, and where joint optimization beats two-stage and where they tie. The one-to-two-minute demo video is scheduled for the week of April 21 and will show the CLI demo, a Streamlit session, and the experiment sweep without voiceover. If time allows, we also want to try an LNS warm-start that seeds the joint solver with the two-stage solution as a hint, and add a couple more stress-test presets. We are confident we can finish through the report and video before April 28 without needing any late days.

Everything in this document can be reproduced from the repository with `pip install -r requirements.txt`, followed by `pytest`, `python -m src.app.cli demo`, `python -m src.app.cli experiments --time-limit 15`, and `python scripts/launch_ui.py`.
