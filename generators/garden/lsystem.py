"""L-system grammars and drawing helpers for the commit-history tree."""

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
    "autumn": (["#A8563E", "#A04E59", "#916B24"], ["#A8563E", "#916B24", "#A04E59"]),
    "winter": (["#426E91", "#53677F", "#527965"], ["#426E91", "#53677F", "#527965"]),
}

# One species for the whole tree: a binary L-system whose older internodes keep
# lengthening while every tip forks, after Alex Bespoyasov's canvas trees
# (https://bespoyasov.me/blog/generating-trees-on-canvas-using-typescript-and-oop/).
# "1" and "2" are wood, "0" is a leaf, "[" and "]" open and close a fork.
AXIOM = "220"
RULES = {"1": "21", "0": "1[20]20"}
JOINT_ANGLE = 27.0       # each fork spreads this far to either side
ANGLE_DEVIATION = 11.0   # random wobble added to every fork
GROW_CHANCE = .6         # share of wood symbols that actually grow
WIDTH_DECAY = .75        # every fork thins the wood
TROPISM = .05            # how strongly each segment bends back towards the light

# ----------------------------------------------------------------------------- rendering

def expand(iterations: int) -> str:
    program = AXIOM
    for _ in range(iterations):
        program = "".join(RULES.get(symbol, symbol) for symbol in program)
    return program


def turtle(program: str, heading: float, rng: random.Random):
    """Grow a program from the origin, in unit steps, starting along heading (degrees).

    Returns (segments, leaves): segments are (x1, y1, x2, y2, forks) and leaves
    are (x, y, heading), where forks counts the forks between origin and segment.
    """
    x, y = 0.0, 0.0
    stack = []
    forks = 0
    segments, leaves = [], []
    for symbol in program:
        if symbol in "12":
            # Skipping wood at random is what gives every bough its own proportions.
            if segments and rng.random() > GROW_CHANCE:
                continue
            # Bend towards straight up (-90 degrees), the short way round.
            heading += ((-90 - heading + 180) % 360 - 180) * TROPISM
            nx = x + math.cos(math.radians(heading))
            ny = y + math.sin(math.radians(heading))
            segments.append((x, y, nx, ny, forks))
            x, y = nx, ny
            if len(segments) > MAX_SEGMENTS:
                raise OverflowError
        elif symbol == "0":
            leaves.append((x, y, heading))
        elif symbol == "[":
            forks += 1
            heading -= JOINT_ANGLE + rng.uniform(-ANGLE_DEVIATION, ANGLE_DEVIATION)
            stack.append((x, y, heading, forks))
        elif symbol == "]":
            x, y, heading, forks = stack.pop()
            heading += 2 * JOINT_ANGLE + rng.uniform(-ANGLE_DEVIATION, ANGLE_DEVIATION)
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
