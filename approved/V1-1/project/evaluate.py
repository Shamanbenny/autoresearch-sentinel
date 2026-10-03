"""Deterministic CPU-only maze evaluator for Autoresearch Sentinel."""

import json
from collections import deque
from pathlib import Path

from solver import solve


ROOT = Path(__file__).resolve().parent
RESULT_PATH = ROOT / "evaluation-result.json"
CASE_PATH = ROOT / "mazes.json"
ARTIFACT_PATH = ROOT / "logs" / "maze-runs.json"
DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


def make_grid(case):
    width, height = case["width"], case["height"]
    grid = [["." for _ in range(width)] for _ in range(height)]
    for row in range(height):
        for column in range(width):
            if row in (0, height - 1) or column in (0, width - 1):
                grid[row][column] = "#"
    for column, row in case["walls"]:
        grid[row][column] = "#"
    start = tuple(case["start"])
    goal = tuple(case["goal"])
    grid[start[0]][start[1]] = "."
    grid[goal[0]][goal[1]] = "."
    return ["".join(row) for row in grid], start, goal


def oracle_distance(grid, start, goal):
    """Independent BFS oracle used only to check shortest-path correctness."""
    frontier = deque([(start, 0)])
    visited = {start}
    while frontier:
        current, distance = frontier.popleft()
        if current == goal:
            return distance
        for row_delta, column_delta in DIRECTIONS:
            neighbor = (current[0] + row_delta, current[1] + column_delta)
            row, column = neighbor
            if not (0 <= row < len(grid) and 0 <= column < len(grid[row])):
                continue
            if grid[row][column] == "#" or neighbor in visited:
                continue
            visited.add(neighbor)
            frontier.append((neighbor, distance + 1))
    return None


def validate_path(path, grid, start, goal, expected_distance):
    if not isinstance(path, list) or not path:
        return "solver returned no path"
    try:
        points = [tuple(point) for point in path]
    except (TypeError, ValueError):
        return "path must be a list of [row, column] coordinates"
    if any(len(point) != 2 or any(type(value) is not int for value in point) for point in points):
        return "path coordinates must be integer [row, column] pairs"
    if points[0] != start or points[-1] != goal:
        return "path does not begin at start and end at goal"
    for row, column in points:
        if not (0 <= row < len(grid) and 0 <= column < len(grid[row])):
            return f"path leaves the grid at {(row, column)}"
        if grid[row][column] == "#":
            return f"path crosses a wall at {(row, column)}"
    for first, second in zip(points, points[1:]):
        if abs(first[0] - second[0]) + abs(first[1] - second[1]) != 1:
            return f"path contains a non-adjacent move from {first} to {second}"
    if len(points) - 1 != expected_distance:
        return f"path length {len(points) - 1} is not shortest distance {expected_distance}"
    return None


def main():
    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    failures = []
    records = []
    total_nodes_explored = 0

    for case in cases:
        grid, start, goal = make_grid(case)
        expected_distance = oracle_distance(grid, start, goal)
        if expected_distance is None:
            failures.append({"case": case["name"], "error": "test case has no oracle path"})
            continue
        try:
            path, nodes_explored = solve(grid, start, goal)
            if isinstance(nodes_explored, bool) or not isinstance(nodes_explored, int) or nodes_explored < 0:
                raise ValueError("nodes_explored must be a non-negative integer")
            total_nodes_explored += nodes_explored
            error = validate_path(path, grid, start, goal, expected_distance)
            if error:
                failures.append({"case": case["name"], "error": error})
            records.append({
                "case": case["name"],
                "shortest_path_length": expected_distance,
                "candidate_path_length": len(path) - 1 if isinstance(path, list) and path else None,
                "nodes_explored": nodes_explored,
            })
        except Exception as exc:  # Report a candidate failure as structured evaluator output.
            failures.append({"case": case["name"], "error": f"solver raised {type(exc).__name__}: {exc}"})

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema_version": 1,
        "status": "completed",
        "metrics": {"total_nodes_explored": total_nodes_explored},
        "failures": failures,
        "artifacts": [ARTIFACT_PATH.relative_to(ROOT).as_posix()],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
