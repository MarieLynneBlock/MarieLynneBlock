"""Public GitHub commit contributions, rendered as a seasonal L-system forest.

Refresh: python generators/garden/forest.py --refresh
Offline rebuilds use history.json.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nord import (  # noqa: E402
    ASSETS, AURORA, esc, svg_open, text, update_readme_asset_links, write_pair,
)

HERE = Path(__file__).resolve().parent
HISTORY_PATH = HERE / "history.json"
OUT_STEM = ASSETS / "garden" / "garden"
README_PATH = ASSETS.parent / "README.md"
GARDEN_LINK_RE = re.compile(
    r"assets/garden/garden-(?:dark|light)\.svg(?:[?#][^\"'<>\s]*)?(?=[\"'])"
)
OWNER = "MarieLynneBlock"
SEASONS = ("winter", "spring", "summer", "autumn")

QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!, $cursor:String) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      commitContributionsByRepository(maxRepositories:100) {
        repository { nameWithOwner isPrivate }
        contributions(first:100, after:$cursor) {
          pageInfo { hasNextPage endCursor }
          nodes { occurredAt commitCount }
        }
      }
    }
  }
}
"""


def graphql(query: str, **variables) -> dict:
    payload = json.dumps({"query": query, "variables": variables})
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"],
            input=payload, text=True, capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"GitHub query failed: {error.stderr.strip()}") from error
    response = json.loads(result.stdout)
    if response.get("errors"):
        raise RuntimeError(f"GitHub GraphQL errors: {response['errors']}")
    return response["data"]


def season_for_date(value: str) -> tuple[int, str]:
    date = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    if date.month == 12:
        return date.year + 1, "winter"
    if date.month <= 2:
        return date.year, "winter"
    return date.year, SEASONS[(date.month - 3) // 3 + 1]


def collect_history(login: str = OWNER, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    user = graphql(
        "query($login:String!) { user(login:$login) { createdAt } }", login=login,
    )["user"]
    if user is None:
        raise ValueError(f"GitHub user not found: {login}")
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    buckets: dict[tuple[int, str], dict[str, int]] = {}
    for year in range(created.year, now.year + 1):
        variables = {
            "login": login,
            "from": datetime(year, 1, 1, tzinfo=timezone.utc).isoformat(),
            "to": min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now).isoformat(),
        }

        def fetch(cursor=None):
            groups = graphql(QUERY, **variables, cursor=cursor)["user"][
                "contributionsCollection"
            ]["commitContributionsByRepository"]
            if len(groups) >= 100:
                raise RuntimeError(
                    f"{year}: GitHub's 100-repository limit was reached; "
                    "refusing to publish potentially incomplete history."
                )
            return groups

        for group in fetch():
            if group["repository"]["isPrivate"]:
                continue
            repository = group["repository"]["nameWithOwner"]
            connection = group["contributions"]
            seen_cursors = set()
            while True:
                for day in connection["nodes"]:
                    key = season_for_date(day["occurredAt"])
                    repos = buckets.setdefault(key, {})
                    repos[repository] = repos.get(repository, 0) + day["commitCount"]
                page = connection["pageInfo"]
                if not page["hasNextPage"]:
                    break
                cursor = page["endCursor"]
                if not cursor or cursor in seen_cursors:
                    raise RuntimeError(f"Invalid contribution cursor for {repository} in {year}")
                seen_cursors.add(cursor)
                matches = [
                    item for item in fetch(cursor)
                    if item["repository"]["nameWithOwner"] == repository
                    and not item["repository"]["isPrivate"]
                ]
                if len(matches) != 1:
                    raise RuntimeError(f"Repository disappeared while paginating: {repository}")
                connection = matches[0]["contributions"]

    last_year = max([now.year] + [year for year, _ in buckets])
    return {
        "login": login,
        "through": now.date().isoformat(),
        "source": "GitHub public commit contributions",
        "years": [
            {
                "year": year,
                "seasons": {
                    season: {
                        "commits": sum(buckets.get((year, season), {}).values()),
                        "repositories": dict(sorted(buckets.get((year, season), {}).items())),
                    }
                    for season in SEASONS
                },
            }
            for year in range(created.year, last_year + 1)
        ],
    }


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        raise FileNotFoundError(
            "No commit history cached. Run python generators/garden/forest.py --refresh "
            "with gh authenticated (or GH_TOKEN set)."
        )
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def refresh_history() -> dict:
    history = collect_history()
    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return history


def summary(history: dict) -> str:
    years = history["years"]
    total = sum(s["commits"] for y in years for s in y["seasons"].values())
    return f"{total:,} public commit contributions | {years[0]['year']}-{years[-1]['year']}"


def render(history: dict, theme) -> str:
    from generators.garden import lsystem

    width, height = 900, 560
    season_palettes = (
        lsystem.LIGHT_SEASON_PALETTES
        if theme.name == "light" else lsystem.SEASON_PALETTES
    )
    trees = [
        (year["year"], season, year["seasons"][season])
        for year in history["years"] for season in SEASONS
        if year["seasons"][season]["commits"]
    ]
    max_commits = max((bucket["commits"] for _, _, bucket in trees), default=0)
    parts = [svg_open(width, height, theme, f"Commit forest for {history['login']}: {summary(history)}")]
    parts.append(
        "<defs>"
        '<linearGradient id="aurora" x1="0" y1="0" x2="1" y2="0">'
        + "".join(
            f'<stop offset="{i / (len(AURORA) - 1):.2f}" stop-color="{c}"/>'
            for i, c in enumerate(AURORA)
        )
        + "</linearGradient>"
        '<filter id="glow"><feGaussianBlur stdDeviation=".8" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
        "<style>"
        "@keyframes sway{0%,100%{transform:rotate(-1.4deg)}50%{transform:rotate(1.4deg)}}"
        "@keyframes grow{to{stroke-dashoffset:0}}"
        "@keyframes bloom{to{opacity:1}}"
        ".tree{animation:sway 7s ease-in-out infinite}"
        ".tree path.b{stroke-dasharray:1;stroke-dashoffset:1;animation:grow 2.4s ease-out forwards}"
        ".tree .l{opacity:0;animation:bloom 1.2s ease-out forwards}"
        "@media(prefers-reduced-motion:reduce){.tree{animation:none}"
        ".tree path.b{stroke-dashoffset:0;animation:none}.tree .l{opacity:1;animation:none}}"
        "</style>"
    )
    parts.append(text(28, 36, "A FOREST OF COMMITS", theme.text, 19, weight="bold"))
    parts.append(text(28, 60, summary(history), theme.muted, 12))
    parts.append(text(28, 81, "Years of making, rooted in real history.", theme.muted, 11))
    parts.append(
        f'<path d="M0 375Q160 330 325 374T650 368T900 367V480H0Z" fill="{theme.panel}" opacity=".5"/>'
        f'<path d="M0 410Q190 370 400 414T900 403V480H0Z" fill="{theme.panel}" opacity=".65"/>'
    )

    grown = []
    for index, (year, season, bucket) in enumerate(trees):
        count = bucket["commits"]
        ratio = math.log1p(count) / math.log1p(max_commits)
        # Neighbouring seasons get different species, so the forest reads as mixed woodland.
        _, axiom, rules, angle, max_iterations = lsystem.SPECIES[
            (year * 4 + SEASONS.index(season) * 3) % len(lsystem.SPECIES)
        ]
        budget = 120 + 900 * ratio
        iterations = 2
        while (
            iterations < max_iterations
            and lsystem.expand(axiom, rules, iterations + 1).count("F") <= budget
        ):
            iterations += 1
        rng = random.Random(year * 4 + SEASONS.index(season))
        segments, leaves = lsystem.turtle(
            lsystem.expand(axiom, rules, iterations),
            angle, rng,
        )
        xs = [x for s in segments for x in (s[0], s[2])]
        ys = [y for s in segments for y in (s[1], s[3])]
        tree_height = 55 + 185 * ratio
        # One scale for both axes keeps the species' natural shape; the width cap keeps bushes tidy.
        scale = min(
            tree_height / max(-min(ys), 1),
            (40 + 140 * ratio) / max(max(xs) - min(xs), 1),
        )
        grown.append((index, year, season, bucket, ratio, rng, segments, leaves, scale, min(xs), max(xs)))

    # Space trees chronologically by crown width, letting neighbours overlap a little.
    spans = [(tree[10] - tree[9]) * tree[8] for tree in grown]
    gaps = [(a + b) / 2 * .6 for a, b in zip(spans, spans[1:])]
    squeeze = min(1, (width - 60 - (spans[0] + spans[-1]) / 2 if spans else 0) / max(sum(gaps), 1))
    placed = []
    cx = 30 + (spans[0] / 2 if spans else 0)
    for position, tree in enumerate(grown):
        year, season = tree[1], tree[2]
        if position:
            cx += gaps[position - 1] * squeeze
        baseline = 384 + random.Random(year * 10 + SEASONS.index(season)).uniform(-16, 44)
        placed.append((baseline, cx, tree))

    # Paint the far trees first, so overlapping crowns form one continuous forest.
    for baseline, cx, tree in sorted(placed, key=lambda item: item[0]):
        index, year, season, bucket, ratio, rng, segments, leaves, scale, left, right = tree
        count = bucket["commits"]
        repositories = bucket["repositories"]
        branches, leaves_palette = season_palettes.get(season, lsystem.SEASON_PALETTES[season])
        title = f"{season} {year}: {count} commits in {len(repositories)} public repositories"
        title += "; " + ", ".join(f"{repo}: {n}" for repo, n in repositories.items())
        cx = max(16 - left * scale, min(cx, width - 16 - right * scale))
        # The forest grows in chronologically, then each tree sways on its own rhythm.
        start = index * .12
        sway = 6 + rng.uniform(0, 3)
        parts.append(
            f'<ellipse cx="{cx:.1f}" cy="{baseline + 2:.1f}" rx="{10 + 16 * ratio:.0f}" ry="3" '
            f'fill="{theme.grid}" opacity=".35"/>'
            f'<g class="tree" style="transform-origin:{cx:.1f}px {baseline:.1f}px;'
            f'animation-duration:{sway:.1f}s;animation-delay:-{rng.uniform(0, sway):.1f}s" '
            f'data-year="{year}" data-season="{season}" data-commits="{count}">'
            f"<title>{esc(title)}</title>"
        )
        max_depth = max(s[4] for s in segments) or 1
        by_depth: dict[int, list[str]] = {}
        ends: dict[int, tuple[float, float]] = {}
        for x1, y1, x2, y2, depth in segments:
            a = (round(x1 * scale + cx, 1), round(y1 * scale + baseline, 1))
            b = (round(x2 * scale + cx, 1), round(y2 * scale + baseline, 1))
            # Continue the current stroke when segments join, keeping the SVG compact.
            move = "" if ends.get(depth) == a else f"M{a[0]} {a[1]}"
            by_depth.setdefault(depth, []).append(f"{move}L{b[0]} {b[1]}")
            ends[depth] = b
        for depth, paths in sorted(by_depth.items()):
            colour = branches[min(depth * len(branches) // (max_depth + 1), len(branches) - 1)]
            stroke = max(.5, (1.4 + 2.6 * ratio) * (1 - depth / (max_depth + 1)))
            parts.append(
                f'<path class="b" pathLength="1" d="{"".join(paths)}" fill="none" stroke="{colour}" '
                f'stroke-width="{stroke:.1f}" stroke-linecap="round" opacity=".92" '
                f'style="animation-delay:{start + 2.4 * depth / (max_depth + 1):.2f}s"/>'
            )
        cap = int(25 + 175 * ratio)
        tips = rng.sample(leaves, min(len(leaves), cap))
        # Leaves are zero-length round-capped strokes: one path per colour and size.
        dots: dict[tuple[str, float], list[str]] = {}
        for x, y, _ in tips:
            key = (rng.choice(leaves_palette), rng.choice((1.0, 1.4, 1.8)))
            dots.setdefault(key, []).append(f"M{x * scale + cx:.1f} {y * scale + baseline:.1f}h0")
        parts.append(f'<g class="l" filter="url(#glow)" style="animation-delay:{start + 2:.2f}s">')
        for (colour, size), points in sorted(dots.items()):
            parts.append(
                f'<path d="{"".join(points)}" stroke="{colour}" '
                f'stroke-width="{(1.8 + 1.8 * ratio) * size:.1f}" stroke-linecap="round" opacity=".9"/>'
            )
        parts.append("</g></g>")
    parts.append(f'<rect x="0" y="456" width="{width}" height="3" fill="url(#aurora)" opacity=".8"/>')
    if not trees:
        parts.append(text(width / 2, 290, "No public commit contributions recorded yet.", theme.muted, 13, anchor="middle"))

    for index, season in enumerate(SEASONS):
        x = 28 + index * 110
        _, leaves = season_palettes.get(season, lsystem.SEASON_PALETTES[season])
        for marker, colour in enumerate(leaves):
            parts.append(
                f'<circle cx="{x + (marker - 1) * 5}" cy="476" r="2.7" fill="{colour}" '
                f'stroke="{theme.bg}" stroke-width=".7"/>'
            )
        parts.append(text(x + 11, 480, season, theme.text, 11, weight="bold"))
    parts.append(text(28, 510, f"Public commit contributions through {history['through']} (UTC). Empty seasons leave no tree.", theme.muted, 10))
    parts.append(text(28, 536, "Winter = Dec-Feb. Seasonal history grows left to right; trees reflect public commit history.", theme.muted, 10))
    parts.append("</svg>")
    return "".join(parts)


def render_all() -> list[Path]:
    history = load_history()
    paths = write_pair(OUT_STEM, lambda theme: render(history, theme))
    update_readme_asset_links(paths, README_PATH, GARDEN_LINK_RE, "garden")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Fetch all years of public commit history from GitHub")
    args = parser.parse_args()
    if args.refresh:
        refresh_history()
    for path in render_all():
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
