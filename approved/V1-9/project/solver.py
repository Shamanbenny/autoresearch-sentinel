"""Deterministic grid maze solver using bidirectional breadth-first search."""


# Fixed movement order keeps tie-breaking deterministic.
DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


def solve(grid: list[str], start: tuple[int, int], goal: tuple[int, int]):
    """Return (shortest_path, nodes_explored) using bidirectional BFS.

    Coordinates use (row, column). A path includes both start and goal.
    Walls are represented by '#'; every other cell is traversable.
    """
    start_frontier = {start}
    goal_frontier = {goal}
    start_parent = {start: None}
    goal_parent = {goal: None}
    start_distance = {start: 0}
    goal_distance = {goal: 0}
    nodes_explored = 0
    meeting = None

    while start_frontier and goal_frontier and meeting is None:
        if len(start_frontier) <= len(goal_frontier):
            frontier = start_frontier
            own_parent = start_parent
            other_parent = goal_parent
            target = goal
            expand_start = True
        else:
            frontier = goal_frontier
            own_parent = goal_parent
            other_parent = start_parent
            target = start
            expand_start = False

        next_frontier = set()
        best_meeting = None
        best_distance = None
        for current in frontier:
            nodes_explored += 1
            if current in other_parent:
                distances = start_distance if expand_start else goal_distance
                candidate_distance = distances[current] + (goal_distance if expand_start else start_distance)[current]
                if best_distance is None or candidate_distance < best_distance:
                    best_meeting = current
                    best_distance = candidate_distance
            neighbors = []
            for row_delta, column_delta in DIRECTIONS:
                neighbor = (current[0] + row_delta, current[1] + column_delta)
                row, column = neighbor
                if not (0 <= row < len(grid) and 0 <= column < len(grid[row])):
                    continue
                if grid[row][column] == "#" or neighbor in own_parent:
                    continue
                neighbors.append(neighbor)

            neighbors.sort(key=lambda point: abs(point[0] - target[0]) + abs(point[1] - target[1]))
            for neighbor in neighbors:
                own_parent[neighbor] = current
                next_frontier.add(neighbor)
                own_distance = start_distance if expand_start else goal_distance
                other_distance = goal_distance if expand_start else start_distance
                own_distance[neighbor] = own_distance[current] + 1
                if neighbor in other_parent:
                    candidate_distance = own_distance[neighbor] + other_distance[neighbor]
                    if best_distance is None or candidate_distance < best_distance:
                        best_meeting = neighbor
                        best_distance = candidate_distance

        meeting = best_meeting

        if expand_start:
            start_frontier = next_frontier
        else:
            goal_frontier = next_frontier

    if meeting is None:
        return None, nodes_explored

    path = []
    current = meeting
    while current is not None:
        path.append(current)
        current = start_parent[current]
    path.reverse()

    current = goal_parent[meeting]
    while current is not None:
        path.append(current)
        current = goal_parent[current]

    return path, nodes_explored
