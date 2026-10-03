# CPU Maze Pathfinder Demo

This is a small, deterministic Sentinel example that needs no GPU or third-party
packages. The baseline in `solver.py` uses breadth-first search (BFS). The
read-only evaluator checks path validity and shortest-path correctness across
17 fixed mazes, then minimizes total nodes explored. It writes structured
results to `evaluation-result.json` and per-maze records to `logs/maze-runs.json`.

Sentinel allows the agent to edit only `solver.py`; it may read the evaluator
and maze cases for context, but cannot change the test cases, correctness checks,
or score calculation.
