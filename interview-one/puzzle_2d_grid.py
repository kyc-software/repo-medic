# Display one or more coordinate lines on a grid that is at least 5 by 5.
# Accept quoted multiline input, mark covered nodes with "1", and reject invalid input cleanly.
import re
import sys

MIN_GRID_SIZE = 5
LINE_PATTERN = re.compile(r"(\d+),(\d+)\s*->\s*(\d+),(\d+)")
USAGE = 'usage: python3 puzzle_2D-grid.py "0,0 -> 4,0" "0,0 -> 4,4"'


# Return validated coordinate pairs parsed from all command-line arguments.
def parse_lines(arguments):
    specifications = [
        line.strip()
        for argument in arguments
        for line in argument.splitlines()
        if line.strip()
    ]
    if not specifications:
        raise ValueError("provide at least one coordinate line")

    lines = []
    for number, specification in enumerate(specifications, start=1):
        match = LINE_PATTERN.fullmatch(specification)
        if not match:
            raise ValueError(
                f'invalid line {number}: "{specification}"; expected x1,y1 -> x2,y2'
            )

        x1, y1, x2, y2 = map(int, match.groups())
        if x1 != x2 and y1 != y2 and abs(x2 - x1) != abs(y2 - y1):
            raise ValueError(
                f"invalid line {number}: only horizontal, vertical, or 45-degree lines are supported"
            )
        lines.append(((x1, y1), (x2, y2)))

    return lines


# Return a grid string containing every supplied line marked with "1".
def render_lines(lines):
    largest_coordinate = max(
        value for line in lines for point in line for value in point
    )
    grid_size = max(MIN_GRID_SIZE, largest_coordinate + 1)
    grid = [["."] * grid_size for _ in range(grid_size)]

    for (x1, y1), (x2, y2) in lines:
        dx = (x2 > x1) - (x2 < x1)
        dy = (y2 > y1) - (y2 < y1)
        distance = max(abs(x2 - x1), abs(y2 - y1))
        for step in range(distance + 1):
            grid[y1 + step * dy][x1 + step * dx] = "1"

    return "\n".join("".join(row) for row in grid)


# Print the rendered grid and return a successful or invalid-input exit code.
def main(arguments):
    try:
        print(render_lines(parse_lines(arguments)))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
