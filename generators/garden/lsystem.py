"""L-system grammars and drawing helpers for the commit-history forest."""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nord import (  # noqa: E402
    NORD4, NORD7, NORD8, NORD9, NORD10, NORD11, NORD12,
    NORD13, NORD14, NORD15, Theme,
)

MAX_SEGMENTS = 22_000
MAX_BYTES = 420_000

SEASONS = ["spring", "summer", "autumn", "winter"]
# (branch palette, leaf palette) per season
SEASON_PALETTES = {
    "spring": ([NORD14, NORD15, "#D49AB3"], [NORD14, NORD15, "#D49AB3"]),
    "summer": (["#A3BE8C", "#8FBF78", "#6D9E65"], ["#A3BE8C", "#B8D884", "#8FBF78"]),
    "autumn": ([NORD12, NORD11, NORD13], [NORD12, NORD13, NORD11]),
    "winter": ([NORD9, NORD10, NORD4], [NORD8, NORD4, NORD7]),
}
LIGHT_SEASON_PALETTES = {
    "spring": (["#688252", "#80618D", "#B36B85"], ["#688252", "#80618D", "#B36B85"]),
    "summer": (["#567A48", "#729355", "#3F7047"], ["#567A48", "#729355", "#3F7047"]),
}

# Curated, well-behaved species. Each is (name, axiom, rules, angle, start_iterations).
SPECIES = [
    ("Fractal Plant", "X", {"X": "F+[[X]-X]-F[-FX]+X", "F": "FF"}, 25.0, 4),
    ("Stochastic Bush", "F", {"F": "FF-[-F+F+F]+[+F-F-F]"}, 22.5, 3),
    ("Fern", "X", {"X": "F[+X][-X]FX", "F": "FF"}, 25.7, 5),
    ("Twig", "F", {"F": "F[+F]F[-F]F"}, 25.7, 4),
    ("Seaweed", "F", {"F": "F[+F]F[-F][F]"}, 20.0, 4),
    ("Spiral Weed", "X", {"X": "F-[[X]+X]+F[+FX]-X", "F": "FF"}, 22.5, 4),
    ("Aurora Tree", "F", {"F": "F[-F][+F]FF"}, 28.0, 4),
    ("Sage", "X", {"X": "F[+X]F[-X]+X", "F": "FF"}, 20.0, 5),
]

# ----------------------------------------------------------------------------- rendering

def expand(axiom: str, rules: dict, iterations: int) -> str:
    s = axiom
    for _ in range(iterations):
        s = "".join(rules.get(c, c) for c in s)
    return s


def turtle(program: str, angle_deg: float, rng: random.Random):
    """Return (segments, leaves) in unit space. Segment: (x1,y1,x2,y2,depth)."""
    x, y, heading = 0.0, 0.0, -90.0
    stack = []
    depth = 0
    segments, leaves = [], []
    for c in program:
        if c == "F":
            jitter = 1.0 + rng.uniform(-0.08, 0.08)
            nx = x + math.cos(math.radians(heading)) * jitter
            ny = y + math.sin(math.radians(heading)) * jitter
            segments.append((x, y, nx, ny, depth))
            x, y = nx, ny
            if len(segments) > MAX_SEGMENTS:
                raise OverflowError
        elif c == "+":
            heading += angle_deg * (1.0 + rng.uniform(-0.15, 0.15))
        elif c == "-":
            heading -= angle_deg * (1.0 + rng.uniform(-0.15, 0.15))
        elif c == "[":
            stack.append((x, y, heading))
            depth += 1
        elif c == "]":
            leaves.append((x, y, depth))
            if stack:
                x, y, heading = stack.pop()
            depth = max(0, depth - 1)
    return segments, leaves


def render(theme: Theme) -> str:
    from generators.garden import forest

    return forest.render(forest.load_history(), theme)


def render_all():
    from generators.garden import forest

    return forest.render_all()


def main(argv: list[str]) -> None:
    import argparse
    from generators.garden import forest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Fetch all years of public commit history from GitHub")
    args = parser.parse_args(argv[1:])
    if args.refresh:
        forest.refresh_history()
    for path in forest.render_all():
        print(f"wrote {path}")


if __name__ == "__main__":
    main(sys.argv)
