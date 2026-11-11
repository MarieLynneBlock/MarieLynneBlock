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


# Per season: share of tips in leaf, leaves per tip, leaf size.
FOLIAGE = {
    "winter": (.55, 1, .8),
    "spring": (1.0, 2, 1.0),
    "summer": (1.0, 3, 1.05),
    "autumn": (.85, 2, 1.1),
}


def _season_growth(
    year: int, season: str, count: int, maximum: int, season_index: int,
    origin: Point, heading: float, girth: float, palette: Palette, wood: str,
    bounds: tuple[float, float, float, float], detail: float,
) -> str:
    ratio = _ratio(count, maximum)
    iterations = max(1, round((3 + 3.6 * ratio) * detail**.4))
    rng = random.Random(year * 4 + season_index)
    segments, leaves = lsystem.turtle(lsystem.expand(iterations), heading, rng)
    if not segments or not leaves:
        raise RuntimeError(f"No drawable seasonal growth for {season} {year}")
    coordinates = [
        (x, y)
        for segment in segments
        for x, y in ((segment[0], segment[1]), (segment[2], segment[3]))
    ]
    reach = max(math.hypot(x, y) for x, y in coordinates)
    scale = (34 + 62 * ratio) / reach
    left, top, right, bottom = bounds
    if not (left < origin[0] < right and top < origin[1] < bottom):
        raise RuntimeError(f"Seasonal growth origin is outside the canvas for {season} {year}")
    min_x, max_x = min(x for x, _ in coordinates), max(x for x, _ in coordinates)
    min_y, max_y = min(y for _, y in coordinates), max(y for _, y in coordinates)
    # Keep unusually tall or wide growth inside the artwork, away from its header and legend.
    margin = 4
    for distance, extent in (
        (origin[0] - left - margin, -min_x), (right - origin[0] - margin, max_x),
        (origin[1] - top - margin, -min_y), (bottom - origin[1] - margin, max_y),
    ):
        if extent > 0:
            scale = min(scale, max(distance, 0) / extent)

    def transform(x: float, y: float) -> Point:
        return (round(origin[0] + scale * x, 1), round(origin[1] + scale * y, 1))

    paths: dict[int, list[str]] = {}
    ends: dict[int, Point] = {}
    for x1, y1, x2, y2, forks in segments:
        start, end = transform(x1, y1), transform(x2, y2)
        move = "" if ends.get(forks) == start else f"M{start[0]} {start[1]}"
        paths.setdefault(forks, []).append(f"{move}L{end[0]} {end[1]}")
        ends[forks] = end

    title = f"{season} {year}: {count} public commit contributions"
    parts = [f'<g class="season" data-season="{season}" data-commits="{count}"><title>{esc(title)}</title>']
    thickness = min(girth * .85, 1.3 + 2.4 * ratio)
    for forks, commands in sorted(paths.items()):
        stroke = max(.45, thickness * lsystem.WIDTH_DECAY**forks)
        parts.append(
            f'<path d="{"".join(commands)}" fill="none" stroke="{wood}" '
            f'stroke-width="{stroke:.2f}" stroke-linecap="round" stroke-linejoin="round"/>'
        )

    share, cluster, size = FOLIAGE[season]
    if detail < .5:
        cluster = 1
    tips = rng.sample(leaves, max(1, round(len(leaves) * share)))
    colours = palette[1]
    spread = 1.6 + 2.2 * ratio
    dots: dict[tuple[str, float], list[str]] = {}
    for x, y, _ in tips:
        tx, ty = transform(x, y)
        for leaf in range(cluster):
            if leaf:
                lx = min(max(tx + rng.gauss(0, spread), left), right)
                ly = min(max(ty + rng.gauss(0, spread), top), bottom)
            else:
                lx, ly = tx, ty
            key = (rng.choice(colours), rng.choice((.8, 1.0, 1.3)))
            dots.setdefault(key, []).append(f"M{lx:.1f} {ly:.1f}h0")
    parts.append('<g class="leaves" filter="url(#glow)">')
    for (colour, weight), points in sorted(dots.items()):
        parts.append(
            f'<path d="{"".join(points)}" stroke="{colour}" stroke-width="{(1.9 + 1.3 * ratio) * size * weight:.1f}" '
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

    spacing = (base - 62 - top) / max(len(years) - 1, 1)
    anchors = [top if len(years) == 1 else base - 62 - index * spacing for index in range(len(years))]

    # Each limb grows on the lighter side of the tree, and the trunk leans away from it.
    sides: dict[int, int] = {}
    weight = 0.0
    for index, total in enumerate(totals):
        if total:
            side = -1 if weight >= 0 else 1
            if sides and abs(weight) < .35:
                side = -list(sides.values())[-1]
            sides[index] = side
            weight += side * _ratio(total, maximum_year)
    knots = [(centre, base + 2.0), (centre - 3.0, base - 30.0)]
    drift, slope = -3.0, 0.0
    for index, y in enumerate(anchors):
        drift += slope * (knots[-1][1] - y)
        drift = max(-26.0, min(26.0, drift))
        knots.append((centre + drift, y))
        if index in sides:
            slope = slope * .4 - sides[index] * (.08 + .2 * _ratio(totals[index], maximum_year)) + rng.uniform(-.03, .03)

    def spline(y: float) -> float:
        for (x1, y1), (x2, y2) in zip(knots, knots[1:]):
            if y >= y2:
                return x1 + (x2 - x1) * (y1 - y) / (y1 - y2)
        return knots[-1][0]

    crown = knots[-1][1]
    trunk = [(spline(y), y) for y in (base + 2 + (crown - base - 2) * step / 200 for step in range(201))]
    for _ in range(3):  # round the corners off the leaning trunk
        trunk = [
            (sum(x for x, _ in trunk[max(i - 6, 0):i + 7]) / len(trunk[max(i - 6, 0):i + 7]), y)
            for i, (_, y) in enumerate(trunk)
        ]

    def trunk_x(y: float) -> float:
        return min(trunk, key=lambda point: abs(point[1] - y))[0]

    rows = []
    limbs = []
    for index, (year, total, y) in enumerate(zip(years, totals, anchors)):
        x = trunk_x(y)
        rows.append((year, total, x, y))
        if total:
            limbs.append((index, year, total, x, y))

    branches = []
    for order, (index, year, total, x, y) in enumerate(limbs):
        ratio = _ratio(total, maximum_year)
        side = sides[index]
        height_fraction = .5 if len(years) == 1 else index / (len(years) - 1)
        leader = order == len(limbs) - 1 and len(limbs) > 1
        lean = (12 if leader else 60 - 30 * height_fraction) + rng.uniform(-5, 5)
        length = (56 + 122 * ratio) * (1 - .25 * height_fraction)

        def direction(degrees: float) -> Point:
            return (side * math.sin(math.radians(degrees)), -math.cos(math.radians(degrees)))

        # Limbs leave the trunk reaching outwards, then turn up towards the light.
        out, aim, up = direction(lean + 16), direction(lean), direction(max(lean - 26, 0))
        # Leave room inside the artwork for the foliage at the limb's tip.
        length = min(length, (y - 84 - 34) / -aim[1], (width / 2 - 54) / abs(aim[0] or 1))
        end = (x + aim[0] * length, y + aim[1] * length)
        c1 = (x + out[0] * length * .4, y + out[1] * length * .4)
        c2 = (end[0] - up[0] * length * .32, end[1] - up[1] * length * .32)
        curve = [_bezier((x, y), c1, c2, end, step / 16) for step in range(17)]
        thickness = 2.6 + 5 * ratio
        widths = [.9 + (thickness - .9) * (1 - step / 16) ** 1.3 for step in range(17)]
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
        # The year's last season carries the limb on; earlier ones fork off on alternating sides.
        for slot, (season, count) in enumerate(active):
            last = slot == len(active) - 1
            t = 1.0 if last else .34 + .5 * slot / max(len(active) - 2, 1) + rng.uniform(-.03, .03)
            if len(active) == 2 and not last:
                t = .55 + rng.uniform(-.03, .03)
            position = round(min(t, 1.0) * 16)
            origin = curve[position]
            a, b = curve[max(position - 1, 0)], curve[min(position + 1, 16)]
            heading = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            if not last:
                fork = -side if slot % 2 == 0 else side
                heading += fork * (42 + rng.uniform(-6, 6))
            branch.append(_season_growth(
                year["year"], season, count, maximum_season, seasons.index(season),
                origin, heading, widths[position], palettes[season], limb_colour,
                (20, 84, width - 20, base - 12), detail,
            ))
        branch.append("</g>")
        branches.append("".join(branch))

    # The trunk's girth carries the combined width of all limbs above it.
    limb_widths = [(y, 2.6 + 5 * _ratio(total, maximum_year)) for _, _, total, _, y in limbs]
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
    tip_x, tip_y = trunk[-1]
    parts.append(
        f'<g class="trunk">{_ribbon(trunk, widths, "url(#bark)")}'
        f'<circle cx="{tip_x:.1f}" cy="{tip_y:.1f}" r="{widths[-1] / 2:.1f}" fill="{bark_light}"/></g>'
    )

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
