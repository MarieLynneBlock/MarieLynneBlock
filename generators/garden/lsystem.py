"""Community L-system garden.

State lives in ``state.json`` next to this file. Visitors mutate it through the
playground workflow (grow / mutate / season / drift); this module turns the state
into an animated SVG that "grows in" on page load.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nord import (  # noqa: E402
    ASSETS, AURORA, DARK, LIGHT, NORD4, NORD7, NORD8, NORD9, NORD10, NORD11, NORD12,
    NORD13, NORD14, NORD15, Theme, svg_open, text, write_pair,
)

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE / "state.json"
OUT_STEM = ASSETS / "garden" / "garden"

WIDTH, HEIGHT = 900, 520
MAX_ITERATIONS = 6
MAX_SEGMENTS = 22_000
MAX_BYTES = 420_000

SEASONS = ["spring", "summer", "autumn", "winter"]
# (branch palette, leaf palette) per season — all Nord
SEASON_PALETTES = {
    "spring": ([NORD14, NORD7, NORD8], [NORD14, NORD13, NORD15]),
    "summer": ([NORD14, NORD10, NORD9], [NORD14, NORD8, NORD7]),
    "autumn": ([NORD12, NORD11, NORD13], [NORD12, NORD13, NORD11]),
    "winter": ([NORD9, NORD10, NORD4], [NORD8, NORD4, NORD7]),
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

ALPHABET = "F+-[]X"


# ----------------------------------------------------------------------------- state

def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def seed_species(index: int, generation: int, season: str, rng: random.Random) -> dict:
    name, axiom, rules, angle, iterations = SPECIES[index % len(SPECIES)]
    return {
        "species": name,
        "axiom": axiom,
        "rules": dict(rules),
        "angle": angle,
        "iterations": iterations,
        "generation": generation,
        "season": season,
        "seed": rng.randrange(1, 10**9),
        "lineage": [],
    }


def default_state() -> dict:
    rng = random.Random(42)
    s = seed_species(0, 1, "spring", rng)
    s.update({"gardeners": [], "actions": {}, "species_index": 0})
    return s


# ----------------------------------------------------------------------------- verbs

def grow(state: dict, rng: random.Random) -> str:
    if state["iterations"] < MAX_ITERATIONS:
        state["iterations"] += 1
        return f"grew to iteration {state['iterations']}"
    idx = (state.get("species_index", 0) + 1) % len(SPECIES)
    fresh = seed_species(idx, state["generation"] + 1, state["season"], rng)
    fresh["lineage"] = (state.get("lineage", []) + [state["species"]])[-6:]
    for key in ("species", "axiom", "rules", "angle", "iterations", "generation", "seed", "lineage"):
        state[key] = fresh[key]
    state["species_index"] = idx
    return f"reached full size and re-seeded as generation {state['generation']}: {state['species']}"


def mutate(state: dict, rng: random.Random, gentle: bool = False) -> str:
    choice = rng.random()
    if gentle or choice < 0.45:
        delta = rng.uniform(1.0, 3.0) if gentle else rng.uniform(2.0, 8.0)
        delta *= rng.choice((-1, 1))
        state["angle"] = round(min(60.0, max(10.0, state["angle"] + delta)), 2)
        return f"bent the branching angle to {state['angle']}°"
    if choice < 0.75:
        state["seed"] = rng.randrange(1, 10**9)
        return "reshuffled the stochastic seed"
    # Substitute or insert one symbol in a rule while keeping brackets balanced.
    key = rng.choice([k for k in state["rules"] if k != "F"] or list(state["rules"]))
    rule = list(state["rules"][key])
    safe_positions = [i for i, c in enumerate(rule) if c in "F+-X"]
    if safe_positions and rng.random() < 0.5:
        i = rng.choice(safe_positions)
        rule[i] = rng.choice("F+-X".replace(rule[i], "") or "F")
        verb = "rewrote"
    else:
        i = rng.randrange(len(rule) + 1)
        rule.insert(i, rng.choice("F+-"))
        verb = "extended"
    state["rules"][key] = "".join(rule)
    return f"{verb} rule {key} → {state['rules'][key]}"


def season(state: dict) -> str:
    state["season"] = SEASONS[(SEASONS.index(state["season"]) + 1) % len(SEASONS)]
    return f"turned the season to {state['season']}"


def apply_verb(state: dict, verb: str, actor: str, seed: int) -> str:
    rng = random.Random(seed)
    if verb == "grow":
        message = grow(state, rng)
    elif verb == "mutate":
        message = mutate(state, rng)
    elif verb == "drift":
        message = mutate(state, rng, gentle=True)
    elif verb == "season":
        message = season(state)
    else:
        raise ValueError(f"unknown garden verb: {verb}")
    if actor and actor != "nightly-drift":
        gardeners = [g for g in state.get("gardeners", []) if g != actor]
        state["gardeners"] = ([actor] + gardeners)[:8]
    state.setdefault("actions", {})
    state["actions"][verb] = state["actions"].get(verb, 0) + 1
    state["last_action"] = {"verb": verb, "actor": actor, "message": message}
    return message


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


def fit(segments, leaves, pad: float = 36.0):
    xs = [v for s in segments for v in (s[0], s[2])] or [0.0]
    ys = [v for s in segments for v in (s[1], s[3])] or [0.0]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(max_x - min_x, 1e-6), max(max_y - min_y, 1e-6)
    scale = min((WIDTH - 2 * pad) / span_x, (HEIGHT - 2 * pad - 50) / span_y)
    off_x = (WIDTH - span_x * scale) / 2 - min_x * scale
    off_y = HEIGHT - pad - 40 - max_y * scale

    def tx(x): return x * scale + off_x
    def ty(y): return y * scale + off_y
    return tx, ty, scale


def render(state: dict, theme: Theme, iterations: int | None = None) -> str:
    iterations = state["iterations"] if iterations is None else iterations
    rng = random.Random(state["seed"])
    program = expand(state["axiom"], state["rules"], iterations)
    segments, leaves = turtle(program, state["angle"], rng)
    tx, ty, scale = fit(segments, leaves)
    branch_colours, leaf_colours = SEASON_PALETTES[state["season"]]
    max_depth = max((s[4] for s in segments), default=1) or 1

    # Group segments by depth so each depth level can have its own grow-in delay.
    by_depth: dict[int, list[str]] = {}
    length_by_depth: dict[int, float] = {}
    for x1, y1, x2, y2, d in segments:
        by_depth.setdefault(d, []).append(f"M{tx(x1):.1f} {ty(y1):.1f}L{tx(x2):.1f} {ty(y2):.1f}")
        length_by_depth[d] = length_by_depth.get(d, 0.0) + math.hypot(tx(x2) - tx(x1), ty(y2) - ty(y1))

    total_dur = 6.0
    parts = [svg_open(WIDTH, HEIGHT, theme, f"Community L-system garden — {state['species']}, generation {state['generation']}, {state['season']}")]
    parts.append(
        "<defs>"
        '<linearGradient id="aurora" x1="0" y1="0" x2="1" y2="0">'
        + "".join(f'<stop offset="{i / (len(AURORA) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(AURORA))
        + "</linearGradient>"
        '<filter id="glow"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
    )
    parts.append(
        "<style>"
        f"@keyframes sway{{0%,100%{{transform:rotate(-1.2deg)}}50%{{transform:rotate(1.2deg)}}}}"
        f".plant{{transform-origin:{WIDTH / 2:.0f}px {HEIGHT - 76}px;animation:sway 7s ease-in-out infinite}}"
        "@keyframes pop{from{opacity:0;r:0}to{opacity:.9}}"
        "</style>"
    )
    parts.append(f'<rect x="0" y="{HEIGHT - 76}" width="{WIDTH}" height="4" fill="url(#aurora)" opacity="0.8"/>')
    parts.append('<g class="plant">')
    for d in sorted(by_depth):
        colour = branch_colours[min(d * len(branch_colours) // (max_depth + 1), len(branch_colours) - 1)]
        width = max(0.6, 3.2 * (1 - d / (max_depth + 1)))
        delay = total_dur * d / (max_depth + 1)
        length = math.ceil(length_by_depth[d] * 1.02) + 2
        parts.append(
            f'<path d="{"".join(by_depth[d])}" fill="none" stroke="{colour}" stroke-width="{width:.2f}" '
            f'stroke-linecap="round" stroke-dasharray="{length}" stroke-dashoffset="{length}" opacity="0.92">'
            f'<animate attributeName="stroke-dashoffset" from="{length}" to="0" dur="{total_dur / (max_depth + 1) * 1.6:.2f}s" '
            f'begin="{delay:.2f}s" fill="freeze"/></path>'
        )
    # Leaves: cap so the SVG stays light.
    rng_leaf = random.Random(state["seed"] ^ 0xBEEF)
    if len(leaves) > 600:
        leaves = rng_leaf.sample(leaves, 600)
    for x, y, d in leaves:
        colour = leaf_colours[rng_leaf.randrange(len(leaf_colours))]
        r = max(1.2, min(4.0, 3.6 * scale / 10 + rng_leaf.uniform(0, 1.2)))
        delay = total_dur * d / (max_depth + 1) + rng_leaf.uniform(0.2, 1.4)
        parts.append(
            f'<circle cx="{tx(x):.1f}" cy="{ty(y):.1f}" r="{r:.1f}" fill="{colour}" opacity="0" filter="url(#glow)">'
            f'<animate attributeName="opacity" from="0" to="0.9" dur="0.6s" begin="{delay:.2f}s" fill="freeze"/>'
            f"</circle>"
        )
    parts.append("</g>")

    # Footer
    rules = "  ".join(f"{k}→{v}" for k, v in state["rules"].items())
    last = state.get("last_action", {})
    gardeners = state.get("gardeners", [])
    parts.append(text(24, HEIGHT - 44, f"{state['species'].lower()} · gen {state['generation']} · iter {iterations} · {state['angle']}° · {state['season']}",
                      theme.text, 13, weight="bold"))
    parts.append(text(24, HEIGHT - 24, f"{state['axiom']} ⟶ {rules}"[:110], theme.muted, 11))
    credit = f"last gardener @{last.get('actor')}" if last.get("actor") and last.get("actor") != "nightly-drift" else "tended by the nightly drift"
    parts.append(text(WIDTH - 24, HEIGHT - 44, credit, theme.muted, 12, anchor="end"))
    parts.append(text(WIDTH - 24, HEIGHT - 24, f"{len(gardeners)} gardener{'s' if len(gardeners) != 1 else ''} · {len(segments)} segments", theme.muted, 11, anchor="end"))
    parts.append("</svg>")
    return "".join(parts)


def render_all(state: dict) -> list[Path]:
    iterations = state["iterations"]
    while True:
        try:
            svgs = {t.name: render(state, t, iterations) for t in (DARK, LIGHT)}
        except OverflowError:
            iterations -= 1
            continue
        if max(len(s.encode()) for s in svgs.values()) > MAX_BYTES and iterations > 1:
            iterations -= 1
            continue
        break
    if iterations != state["iterations"]:
        state["iterations"] = iterations
    return write_pair(OUT_STEM, lambda t: svgs[t.name])


def main(argv: list[str]) -> None:
    if not STATE_PATH.exists():
        save_state(default_state())
    state = load_state()
    if len(argv) >= 2 and argv[1] in ("grow", "mutate", "season", "drift"):
        actor = argv[2] if len(argv) > 2 else "local"
        seed = int(argv[3]) if len(argv) > 3 else random.randrange(1, 10**9)
        print(apply_verb(state, argv[1], actor, seed))
    paths = render_all(state)
    save_state(state)
    for p in paths:
        print(f"wrote {p.relative_to(ASSETS.parent)} ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv)
