# Final report — draft outline

## 1. Introduction
- Motivation: student-life constraints + joint reasoning about nutrition + training
- Course alignment: LP, MIP, CP-SAT, hard vs soft constraints
- Contributions:
  - three solver formulations that share a common interface
  - parameterized instance generator + batch experiment harness
  - Penn Dining / USDA ingestion layer with graceful fallbacks

## 2. Problem formulation
### 2.1 Domain
- user profile (goals, macros, budget, dietary exclusions, sleep, recovery, preferences)
- food catalog schema + sources
- workout templates
- time grid (7 × 48 slots)

### 2.2 Hard constraints
- daily calorie band
- daily protein floor
- dietary exclusions
- weekly budget cap
- time-window availability
- no-overlap on the day grid
- workout count bounds
- sleep-block requirement
- min recovery gap between hard workouts
- max-consecutive-hard-days

### 2.3 Soft constraints / objective terms
- calorie deviation penalty
- protein target shortfall
- carb / fat absolute deviation
- cost penalty
- preferred / avoid workout-day penalty
- peri-workout meal timing penalty
- per-meal protein shortfall
- convenience bonus (negative term)

## 3. Solver formulations
### 3.1 Nutrition-only MIP (A)
- decision variables, constraints, objective
- what it intentionally ignores (schedule, recovery, timing)

### 3.2 Two-stage baseline (B)
- stage 1: nutrition MIP
- stage 2: CP-SAT scheduler (interval vars + `AddNoOverlap`)
- decomposition weakness: stage 1 can commit food choices stage 2 cannot fit

### 3.3 Joint CP-SAT (C)
- unified model with both nutrition and scheduling decisions
- peri-workout meal timing as reified disjunctions over same-day meals
- `max_consecutive_hard_days` via windowed sum constraints

### 3.4 Expected trade-offs
- A: fastest, least realistic
- B: realistic schedule but brittle on tight instances
- C: best plan quality when it finishes

## 4. Experimental setup
- bundled food catalog (sample CSV + Penn Dining)
- workout library (10 templates across hard/easy intensity and splits)
- scenario suite (9 named instances)
- scaling axis (foods = 8 → 48; workout templates scale similarly)

## 5. Results
### 5.1 Feasibility rate
- figure: `reports/figures/experiment_feasibility.png`
- takeaways (expected):
  - nutrition-only always feasible except `impossible_case`
  - two-stage can fail on very tight schedules it could have solved jointly
  - joint fills the gap on `tight_class_schedule` + `recovery_constrained`

### 5.2 Plan quality
- figure: `reports/figures/experiment_objective.png`
- figure: `reports/figures/experiment_macros.png`
- figure: `reports/figures/experiment_cost_vs_protein.png`
- discussion of macro deviation and peri-workout meal hits

### 5.3 Scalability
- figure: `reports/figures/scaling_runtime.png`
- discussion of runtime growth: joint CP-SAT scales linearly until the
  interval-var count hits roughly (n_foods × meal_types × days)

### 5.4 Infeasibility behavior
- how quickly each solver detects `impossible_case`
- role of `infeasibility_reason` in the UX

## 6. Limitations
- 30-minute granularity
- live Penn Dining scraping fragility (fallbacks are used)
- no column generation; scaling past ~80 foods needs decomposition

## 7. Future work
- assumption-based infeasibility explanations
- online re-optimization as the week progresses
- hydration reminders as scheduled blocks
- proper USDA ingestion end-to-end

## 8. Conclusion

## Appendix A — reproducing the figures
- exact CLI commands
- seed table

## Appendix B — solver parameters
- time limits, `ScoringWeights`, CP-SAT parameters
