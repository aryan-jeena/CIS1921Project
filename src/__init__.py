"""Health Schedule Optimizer (CIS 1921 final project).

Top-level package. Sub-packages split along the dimensions of the project:

- ``config``        global configuration and scoring weights
- ``models``        typed domain objects (pydantic / dataclasses)
- ``data_ingestion`` food catalog + workout library loaders
- ``nutrition``     LP/MIP helpers for nutrition-only formulations
- ``scheduling``    time-grid utilities and the two-stage scheduler
- ``solvers``       three full solver formulations plus a common base class
- ``evaluation``    metrics and validators used by the experiment harness
- ``experiments``   instance generator + batch runner
- ``visualization`` plotting + schedule rendering
- ``utils``         small IO/logging helpers
- ``app``           CLI and Streamlit UI entry points
"""

__version__ = "0.1.0"
