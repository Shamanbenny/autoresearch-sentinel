"""Deterministic grid maze solver using A* search."""

from heapq import heappop, heappush


# Fixed movement order keeps neighbor insertion deterministic.
DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


def solve(grid: list[str], start: tuple[int, int], goal: tuple[int, int]):
    """Return (shortest_path, nodes_explored) using Manhattan-distance A*.

    Coordinates use (row, column). A path includes both start and goal.
    Walls are represented by '#'; every other cell is traversable.
    """
    heuristic = lambda point: abs(point[0] - goal[0]) + abs(point[1] - goal[1])
    frontier = [(heuristic(start), heuristic(start), start)]
    parent = {start: None}
    distance = {start: 0}
    nodes_explored = 0

    while frontier:
        estimate_total, estimate, current = heappop(frontier)
        if estimate_total - estimate != distance[current]:
            continue
        nodes_explored += 1
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = parent[current]
            path.reverse()
            return path, nodes_explored

        for row_delta, column_delta in DIRECTIONS:
            neighbor = (current[0] + row_delta, current[1] + column_delta)
            row, column = neighbor
            if not (0 <= row < len(grid) and 0 <= column < len(grid[row])):
                continue
            if grid[row][column] == "#":
                continue
            candidate_distance = distance[current] + 1
            if candidate_distance >= distance.get(neighbor, float("inf")):
                continue
            distance[neighbor] = candidate_distance
            parent[neighbor] = current
            if neighbor == goal:
                path = []
                current = goal
                while current is not None:
                    path.append(current)
                    current = parent[current]
                path.reverse()
                return path, nodes_explored
            estimate = heuristic(neighbor)
            heappush(frontier, (candidate_distance + estimate, estimate, neighbor))

    return None, nodes_explored
