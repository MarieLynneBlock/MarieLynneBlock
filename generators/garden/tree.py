"""Render a commit-history tree with one limb per active season-year."""

from __future__ import annotations

import math
import random
from datetime import date

from generators.garden import lsystem
from nord import AURORA, NORD8, Theme, esc, svg_open, text

Point = tuple[float, float]
Palette = tuple[list[str], list[str]]

BARK = {
    "dark": ("#566079", "#8C9BB5", "#6F7B96"),
    "light": ("#4C566A", "#71829D", "#5E718E"),
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _ratio(value: int, maximum: int) -> float:
    return math.log1p(value) / math.log1p(maximum)


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _ribbon(points: list[Point], widths: list[float], fill: str) -> str:
    left, right = [], []
    for index, (x, y) in enumerate(points):
        a = points[max(index - 1, 0)]
        b = points[min(index + 1, len(points) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy) or 1
        nx, ny = -dy / norm * widths[index] / 2, dx / norm * widths[index] / 2
        left.append(f"{x + nx:.1f} {y + ny:.1f}")
        right.append(f"{x - nx:.1f} {y - ny:.1f}")
    return f'<path d="M{"L".join(left)}L{"L".join(reversed(right))}Z" fill="{fill}"/>'


def _season_growth(
    year: int, season: str, count: int, maximum: int, season_index: int,
    origin: Point, heading: float, palette: Palette, bounds: tuple[float, float, float, float],
    detail: float,
) -> str:
    ratio = _ratio(count, maximum)
    species_index = (year * 4 + season_index * 3) % len(lsystem.SPECIES)
    _, axiom, rules, turn_angle, max_iterations = lsystem.SPECIES[species_index]
    budget = (120 + 650 * ratio) * detail
    iterations = 1 if detail < .25 else 2
    while (
        iterations < max_iterations
        and lsystem.expand(axiom, rules, iterations + 1).count("F") <= budget
    ):
        iterations += 1

    rng = random.Random(year * 4 + season_index)
    segments, leaves = lsystem.turtle(lsystem.expand(axiom, rules, iterations), turn_angle, rng)
    if not segments or not leaves:
        raise RuntimeError(f"No drawable seasonal growth for {season} {year}")
    coordinates = [
        (x, y)
        for segment in segments
        for x, y in ((segment[0], segment[1]), (segment[2], segment[3]))
    ]
    reach = max(math.hypot(x, y) for x, y in coordinates)
    if not reach:
        raise RuntimeError(f"Zero-length seasonal growth for {season} {year}")
    scale = (30 + 46 * ratio) / reach
    rotation = math.radians(heading + 90)
    cosine, sine = math.cos(rotation), math.sin(rotation)
    rotated = [(x * cosine - y * sine, x * sine + y * cosine) for x, y in coordinates]
    left, top, right, bottom = bounds
    if not (left < origin[0] < right and top < origin[1] < bottom):
        raise RuntimeError(f"Seasonal growth origin is outside the canvas for {season} {year}")
    min_x, max_x = min(x for x, _ in rotated), max(x for x, _ in rotated)
    min_y, max_y = min(y for _, y in rotated), max(y for _, y in rotated)
    # Keep unusually tall or wide growth inside the artwork, away from its header and legend.
    for distance, extent in (
        (origin[0] - left, -min_x), (right - origin[0], max_x),
        (origin[1] - top, -min_y), (bottom - origin[1], max_y),
    ):
        if extent > 0:
            scale = min(scale, distance / extent)

    def transform(x: float, y: float) -> Point:
        return (
            round(origin[0] + scale * (x * cosine - y * sine), 1),
            round(origin[1] + scale * (x * sine + y * cosine), 1),
        )

    branches, colours = palette
    max_depth = max(segment[4] for segment in segments) or 1
    paths: dict[int, list[str]] = {}
    ends: dict[int, Point] = {}
    for x1, y1, x2, y2, depth in segments:
        start, end = transform(x1, y1), transform(x2, y2)
        move = "" if ends.get(depth) == start else f"M{start[0]} {start[1]}"
        paths.setdefault(depth, []).append(f"{move}L{end[0]} {end[1]}")
        ends[depth] = end

    title = f"{season} {year}: {count} public commit contributions"
    parts = [f'<g class="season" data-season="{season}" data-commits="{count}"><title>{esc(title)}</title>']
    for depth, commands in sorted(paths.items()):
        colour = branches[min(depth * len(branches) // (max_depth + 1), len(branches) - 1)]
        stroke = max(.5, (1.4 + 2.6 * ratio) * (1 - depth / (max_depth + 1)))
        parts.append(
            f'<path d="{"".join(commands)}" fill="none" stroke="{colour}" '
            f'stroke-width="{stroke:.1f}" stroke-linecap="round" opacity=".92"/>'
        )

    tips = rng.sample(leaves, min(len(leaves), max(1, int((12 + 72 * ratio) * detail))))
    dots: dict[tuple[str, float], list[str]] = {}
    for x, y, _ in tips:
        tx, ty = transform(x, y)
        key = (rng.choice(colours), rng.choice((1.0, 1.25, 1.55)))
        dots.setdefault(key, []).append(f"M{tx:.1f} {ty:.1f}h0")
    parts.append('<g class="leaves" filter="url(#glow)">')
    for (colour, size), points in sorted(dots.items()):
        parts.append(
            f'<path d="{"".join(points)}" stroke="{colour}" stroke-width="{(1.7 + 1.6 * ratio) * size:.1f}" '
            f'stroke-linecap="round" opacity=".9"/>'
        )
    parts.append("</g></g>")
    return "".join(parts)


def _legend(seasons: tuple[str, ...], palettes: dict[str, Palette], theme: Theme, y: float) -> str:
    parts = []
    for index, season in enumerate(seasons):
        x = 28 + index * 110
        parts.append(f'<g class="legend-marker" data-legend-season="{season}">')
        for marker, colour in enumerate(palettes[season][1]):
            cx = x + (marker - 1) * 5
            if season == "winter":
                parts.append(
                    f'<path d="M{cx - 2} {y}h4M{cx} {y - 2}v4" fill="none" '
                    f'stroke="{colour}" stroke-width="1.5" stroke-linecap="round"/>'
                )
            elif season == "summer":
                parts.append(
                    f'<ellipse cx="{cx}" cy="{y}" rx="3" ry="2" fill="{colour}" '
                    f'transform="rotate(-35 {cx} {y})"/>'
                )
            elif season == "autumn":
                parts.append(
                    f'<path d="M{cx} {y - 3}l3 3l-3 3l-3 -3Z" fill="{colour}"/>'
                )
            else:
                parts.append(f'<circle cx="{cx}" cy="{y}" r="2.7" fill="{colour}"/>')
        parts.append("</g>")
        parts.append(text(x + 12, y + 4, season, theme.text, 11, weight="bold"))
    return "".join(parts)


def validate_history(years: list[dict], seasons: tuple[str, ...]) -> list[int]:
    if not years:
        raise ValueError("Commit history has no season-years")
    if any(isinstance(year["year"], bool) or not isinstance(year["year"], int) for year in years):
        raise ValueError("Commit history season-years must be integers")
    if any(a["year"] >= b["year"] for a, b in zip(years, years[1:])):
        raise ValueError("Commit history season-years must be strictly increasing")

    totals = []
    for year in years:
        if set(year["seasons"]) != set(seasons):
            raise ValueError(f"Invalid seasons in season-year {year['year']}")
        counts = [year["seasons"][season]["commits"] for season in seasons]
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counts):
            raise ValueError(f"Invalid commit count in season-year {year['year']}")
        totals.append(sum(counts))
    return totals


def render(history: dict, theme: Theme, seasons: tuple[str, ...], summary: str) -> str:
    for detail in (1.0, .75, .5, .25, .1, .05):
        image = _render(history, theme, seasons, summary, detail)
        if len(image.encode("utf-8")) < lsystem.MAX_BYTES:
            return image
    raise OverflowError(
        f"Commit tree exceeds the {lsystem.MAX_BYTES:,}-byte image limit even at minimum detail"
    )


def _render(history: dict, theme: Theme, seasons: tuple[str, ...], summary: str, detail: float) -> str:
    years = history["years"]
    totals = validate_history(years, seasons)
    maximum_year = max(totals)
    maximum_season = max(
        year["seasons"][season]["commits"] for year in years for season in seasons
    )
    palettes = lsystem.LIGHT_SEASON_PALETTES if theme.name == "light" else lsystem.SEASON_PALETTES
    bark_dark, bark_light, limb_colour = BARK[theme.name]

    width = 900
    height = 570 + max(0, 18 * (len(years) - 1) - 196)
    centre, base, top = width / 2, height - 98, 214
    rng = random.Random(years[0]["year"])
    title = f"Commit tree for {history['login']}: {summary}"
    description = (
        "Each active season-year is a limb with seasonal foliage. "
        "The oldest year is at the roots, the newest at the crown, and empty years are knots. "
        "Winter starts in the previous December."
    )
    parts = [svg_open(width, height, theme, title), f"<desc>{esc(description)}</desc>"]
    parts.append(
        "<defs>"
        f'<linearGradient id="bark" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{bark_dark}"/>'
        f'<stop offset=".55" stop-color="{bark_light}"/><stop offset="1" stop-color="{bark_dark}"/></linearGradient>'
        f'<linearGradient id="limb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{bark_light}"/>'
        f'<stop offset="1" stop-color="{limb_colour}"/></linearGradient>'
        '<linearGradient id="aurora" x1="0" y1="0" x2="1" y2="0">'
        + "".join(
            f'<stop offset="{index / (len(AURORA) - 1):.2f}" stop-color="{colour}"/>'
            for index, colour in enumerate(AURORA)
        )
        + "</linearGradient>"
        '<filter id="glow"><feGaussianBlur stdDeviation=".9" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
        "<style>"
        "@keyframes sway{0%,100%{transform:rotate(-.5deg)}50%{transform:rotate(.5deg)}}"
        ".limb{animation:sway 9s ease-in-out infinite}"
        "@media(prefers-reduced-motion:reduce){.limb{animation:none}}"
        "</style>"
    )
    parts.append(text(28, 33, "A TREE OF COMMITS", theme.text, 20, weight="bold"))
    parts.append(text(28, 58, "Every active season-year grows a limb, with foliage for its seasons.", theme.muted, 12))
    parts.append(
        f'<path d="M0 {base + 6}Q{width * .175:.1f} {base - 20} {width * .35:.1f} {base - 6}'
        f'T{width * .7:.1f} {base - 2}T{width} {base + 2}V{height}H0Z" '
        f'fill="{theme.panel}" opacity=".55"/>'
        f'<rect x="0" y="{base + 14}" width="{width}" height="2" fill="url(#aurora)" opacity=".7"/>'
    )

    trunk = [
        _bezier(
            (centre, base + 2), (centre - 16, base - 105),
            (centre + 18, top + 70), (centre + 4, top - 4), index / 200,
        )
        for index in range(201)
    ]

    def trunk_point(y: float) -> Point:
        return min(trunk, key=lambda point: abs(point[1] - y))

    spacing = (base - 62 - top) / max(len(years) - 1, 1)
    rows = []
    limbs = []
    for index, (year, total) in enumerate(zip(years, totals)):
        y = top if len(years) == 1 else base - 62 - index * spacing
        x = trunk_point(y)[0]
        rows.append((year, total, x, y))
        if total:
            limbs.append((index, year, total, x, y))

    branches = []
    for index, year, total, x, y in limbs:
        ratio = _ratio(total, maximum_year)
        side = -1 if index % 2 == 0 else 1
        height_fraction = .5 if len(years) == 1 else index / (len(years) - 1)
        lean = 70 - 12 * height_fraction + rng.uniform(-5, 5)
        length = (68 + 180 * ratio) * (1 - .34 * height_fraction)
        angle = -90 + side * lean
        end = (x + math.cos(math.radians(angle)) * length, y + math.sin(math.radians(angle)) * length)
        c1 = (x + side * length * .45, y - length * .05)
        c2 = (end[0] - side * length * .12, end[1] + length * .18)
        curve = [_bezier((x, y), c1, c2, end, step / 16) for step in range(17)]
        thickness = 2.4 + 4.6 * ratio
        widths = [thickness + (.8 - thickness) * step / 16 for step in range(17)]
        motion_rng = random.Random(year["year"] * 97)
        duration = 7 + motion_rng.uniform(0, 3)
        delay = motion_rng.uniform(0, duration)
        label = f"{year['year']} season-year: {total} public commit contributions"
        branch = [
            f'<g class="limb" data-year="{year["year"]}" data-commits="{total}" data-anchor-y="{y:.1f}" '
            f'style="transform-origin:{x:.1f}px {y:.1f}px;animation-duration:{duration:.1f}s;'
            f'animation-delay:-{delay:.1f}s"><title>{esc(label)}</title>',
            _ribbon(curve, widths, "url(#limb)"),
        ]
        active = [
            (season, year["seasons"][season]["commits"])
            for season in seasons if year["seasons"][season]["commits"]
        ]
        for slot, (season, count) in enumerate(active):
            fraction = .5 if len(active) == 1 else slot / (len(active) - 1)
            t = 1.0 if len(active) == 1 else .25 + .7 * fraction
            t = min(1.0, max(.2, t + rng.uniform(-.025, .025)))
            position = round(t * 16)
            origin = curve[position]
            a, b = curve[max(position - 1, 0)], curve[min(position + 1, 16)]
            heading = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            heading -= side * (50 - 55 * fraction + rng.uniform(-4, 4))
            branch.append(_season_growth(
                year["year"], season, count, maximum_season, seasons.index(season),
                origin, heading, palettes[season], (20, 84, width - 20, base - 12), detail,
            ))
        branch.append("</g>")
        branches.append("".join(branch))

    # The trunk's girth carries the combined width of all limbs above it.
    limb_widths = [(y, 2.4 + 4.6 * _ratio(total, maximum_year)) for _, _, total, _, y in limbs]
    widths = [
        math.sqrt(2.4**2 + sum(w**2 for limb_y, w in limb_widths if limb_y < y)) * 1.05
        + 22 * math.exp(-(base - y) / 16)
        for _, y in trunk
    ]
    for angle, length, root_width in ((188, 46, 9), (168, 30, 6), (-8, 50, 10), (12, 28, 6), (178, 20, 5), (2, 18, 5)):
        end = (centre + math.cos(math.radians(angle)) * length, base + 5 + abs(math.sin(math.radians(angle))) * 4)
        start = (centre + math.cos(math.radians(angle)) * 6, base - 10)
        bend = (centre + math.cos(math.radians(angle)) * length * .45, base + 1)
        line = [_bezier(start, bend, bend, end, step / 14) for step in range(15)]
        parts.append(_ribbon(line, [root_width * (1 - step / 15) + .6 for step in range(15)], "url(#bark)"))
    parts.extend(branches)
    parts.append(f'<g class="trunk">{_ribbon(trunk, widths, "url(#bark)")}</g>')

    for offset, colour, opacity in ((-.30, bark_dark, .55), (-.05, bark_dark, .35), (.18, bark_dark, .45), (-.38, NORD8, .18)):
        fibre_rng = random.Random(int(offset * 100))
        line = []
        for index in range(0, len(trunk) - 30, 3):
            (x, y), w = trunk[index], widths[index]
            a, b = trunk[max(index - 1, 0)], trunk[min(index + 1, len(trunk) - 1)]
            norm = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
            nx, ny = -(b[1] - a[1]) / norm, (b[0] - a[0]) / norm
            wobble = offset + fibre_rng.uniform(-.03, .03)
            line.append(f"{x + nx * w * wobble:.1f} {y + ny * w * wobble:.1f}")
        parts.append(
            f'<path d="M{"L".join(line)}" fill="none" stroke="{colour}" stroke-width=".7" '
            f'stroke-linecap="round" opacity="{opacity}"/>'
        )

    for year, total, x, y in rows:
        if not total:
            label = f"{year['year']} season-year: no public commit contributions"
            parts.append(
                f'<g class="quiet-year" data-year="{year["year"]}" data-commits="0" data-anchor-y="{y:.1f}">'
                f'<title>{esc(label)}</title><ellipse cx="{x:.1f}" cy="{y:.1f}" rx="2.4" ry="3.6" '
                f'fill="{bark_dark}" stroke="{bark_light}" stroke-width=".6" opacity=".9"/></g>'
            )
    if not maximum_year:
        parts.append(text(width / 2, 130, "No public commit contributions recorded yet.", theme.muted, 13, anchor="middle"))

    parts.append(_legend(seasons, palettes, theme, base + 34))
    parts.append(text(
        28, base + 68,
        "Oldest at the roots; newest in the crown. Size reflects activity on a logarithmic scale.",
        theme.muted, 10,
    ))
    through = date.fromisoformat(history["through"])
    through_text = f"{through.day} {MONTHS[through.month - 1]} {through.year}"
    parts.append(text(
        28, base + 86,
        f"Public commit contributions through {through_text} UTC. Winter begins in the previous December; empty years are knots.",
        theme.muted, 10,
    ))
    parts.append("</svg>")
    return "".join(parts)
