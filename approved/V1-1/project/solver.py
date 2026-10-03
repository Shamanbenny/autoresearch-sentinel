"""Baseline grid maze solver. Sentinel candidates may edit this file only."""

from collections import deque


# Fixed movement order keeps the baseline's tie-breaking deterministic.
DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


def solve(grid: list[str], start: tuple[int, int], goal: tuple[int, int]):
    """Return (shortest_path, nodes_explored) using breadth-first search.

    Coordinates use (row, column). A path includes both start and goal.
    Walls are represented by '#'; every other cell is traversable.
    """
    frontier = deque([start])
    parent = {start: None}
    nodes_explored = 0

    while frontier:
        current = frontier.popleft()
        nodes_explored += 1
        if current == goal:
            break

        neighbors = []
        for row_delta, column_delta in DIRECTIONS:
            neighbor = (current[0] + row_delta, current[1] + column_delta)
            row, column = neighbor
            if not (0 <= row < len(grid) and 0 <= column < len(grid[row])):
                continue
            if grid[row][column] == "#" or neighbor in parent:
                continue
            neighbors.append(neighbor)

        neighbors.sort(key=lambda point: abs(point[0] - goal[0]) + abs(point[1] - goal[1]))
        for neighbor in neighbors:
            parent[neighbor] = current
            frontier.append(neighbor)

    if goal not in parent:
        return None, nodes_explored

    path = []
    current = goal
    while current is not None:
        path.append(current)
        current = parent[current]
    path.reverse()
    return path, nodes_explored
