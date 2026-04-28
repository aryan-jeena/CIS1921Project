# CLAUDE.md

## Project identity

This repository is for a CIS 1921 final project:

**Constraint-Based Training, Nutrition, and Health Schedule Optimizer**

This is an application project centered on optimization and constraint programming. The core of the project must remain solver-heavy and closely tied to course concepts such as LP, MIP, CP, and CP-SAT.

The repo should feel like a strong course final project submission, not a startup MVP and not a frontend-heavy app.

---

## Primary goal

Build a system that generates a personalized weekly fitness and health plan by jointly reasoning about:

- workouts
- meals
- hydration
- sleep
- recovery

The system should accept user constraints and preferences, then generate valid or near-optimal weekly plans.

---

## Course alignment

This project must strongly demonstrate course-relevant modeling and solving, including:

- LP/MIP for nutrition or discrete meal selection
- CP-SAT or related scheduling formulation for weekly plan generation
- constraint modeling with hard and soft constraints
- experimental comparison between formulations
- solver performance analysis
- generated or real-world instances
- rigorous evaluation, not just “it works”

The majority of repository effort should go into optimization logic, model design, experiments, and analysis.

---

## Required solver variants

Claude should preserve and improve these solver variants:

1. **Nutrition-only baseline**
   - LP or MIP
   - optimize meals/foods for calories, macros, cost, and dietary restrictions

2. **Two-stage baseline**
   - first optimize meals
   - then schedule meals/workouts/recovery into time windows

3. **Joint weekly optimizer**
   - CP-SAT preferred
   - jointly reason about workouts, meals, recovery, sleep, hydration, and availability

When adding features, Claude should try to keep these formulations comparable so experiments remain meaningful.

---

## Novelty targets

The repo should clearly satisfy multiple novelty dimensions:

### 1. Real-world data
Preferred:
- Penn Dining ingestion or parsing
Fallback:
- USDA FoodData Central integration
- curated sample food catalog

### 2. Multiple formulations
Keep at least 3 formulations so comparison is possible.

### 3. Parameterized instance generator
Support synthetic users and scalable difficulty.

### 4. User-configurable constraints
Allow easy toggling/configuration via JSON, YAML, CLI args, or Streamlit inputs.

---

## Modeling expectations

### Hard constraints
Examples:
- calorie band
- protein minimum
- dietary restrictions
- budget cap
- time-window availability
- no overlap
- workout count
- sleep minimum
- recovery spacing
- maximum meals per day
- allowed meal windows

### Soft constraints
Examples:
- preferred workout days
- preferred split
- preferred meal timing around workouts
- target meal count
- minimize cost
- minimize macro deviation
- maximize adherence
- reduce fragmentation

Claude should keep the distinction between hard and soft constraints explicit in code and documentation.

---

## Design preferences

### Strongly preferred
- Python
- OR-Tools
- pandas
- numpy
- pydantic or dataclasses
- pytest
- matplotlib
- Streamlit optional but helpful

### Architecture preferences
- modular, typed code
- separate domain models from solver logic
- separate ingestion from optimization
- separate experiments from UI
- reusable configs and scenario files
- reproducible scripts

### Avoid
- bloated frontend code
- unnecessary auth/databases/cloud infra
- complex deployment setup
- over-engineering outside project scope
- replacing optimization with heuristics unless explicitly labeled as baseline/helper

---

## Code quality rules

- Write runnable code, not pseudocode
- Prefer complete implementations over stubs
- Add docstrings and section comments generously
- Keep functions small and composable
- Make assumptions explicit
- Handle infeasibility gracefully
- Provide deterministic behavior when reasonable through random seeds
- Keep experiment outputs machine-readable
- Make demo scenarios easy to run

---

## Repository structure goals

The repository should contain some version of:

- `README.md`
- `requirements.txt`
- `data/`
- `src/`
- `tests/`
- `scripts/`
- `reports/`
- `notebooks/`

Inside `src/`, prefer modules such as:
- `config`
- `data_ingestion`
- `models`
- `nutrition`
- `scheduling`
- `solvers`
- `evaluation`
- `experiments`
- `visualization`
- `app`
- `utils`

---

## Data strategy

Claude should design for graceful fallback:

1. If Penn Dining ingestion works, use it
2. If Penn Dining pages are unavailable or unstable, use USDA data or curated sample food data
3. Always include a small local sample dataset so the repo runs out of the box

All food records should ideally support:
- name
- calories
- protein
- carbs
- fat
- sodium
- cost
- dietary tags
- meal tags

---

## Evaluation strategy

Claude should preserve or improve scripts that measure:

- runtime
- feasibility rate
- objective value
- calorie deviation
- protein deviation
- cost
- workouts scheduled
- preference satisfaction
- scalability

Where possible, generate:
- CSV outputs
- plots
- summary tables

The repo should make it easy to compare formulations side by side.

---

## Demo strategy

The repo should always support an easy demo path:

- one example config for a feasible user
- one example config for a tight but feasible user
- one example config for an infeasible user
- one command to run a baseline solver
- one command to run the joint solver
- one command to run batch experiments
- one command to launch UI if present

---

## Documentation expectations

Claude should maintain:
- a strong `README.md`
- file-level comments
- docstrings
- experiment descriptions
- a report outline in `reports/`
- notes on limitations and future work

The final project report will likely discuss:
- modeling choices
- solver tradeoffs
- runtime scaling
- feasibility behavior
- why some constraints make instances harder
- where joint optimization helps vs two-stage methods

So code and experiment outputs should support those discussions directly.

---

## When extending the project

If asked to add features, prefer additions that strengthen the academic/project value, such as:
- better solver comparisons
- more realistic constraints
- improved infeasibility analysis
- better experiment coverage
- stronger visualizations
- cleaner report artifacts

Do not drift into unrelated product features.

---

## Behavior instructions for Claude

When asked to make changes:
1. preserve runnability
2. preserve solver comparability
3. preserve experiment reproducibility
4. keep optimization logic central
5. annotate non-obvious logic clearly

When unsure between a flashy UI improvement and a better modeling/evaluation improvement, choose the modeling/evaluation improvement.