"""Public GitHub commit contributions, rendered as a seasonal commit tree.

Refresh: python generators/garden/forest.py --refresh
Offline rebuilds use history.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generators.garden import tree  # noqa: E402
from nord import ASSETS, update_readme_asset_links, write_pair  # noqa: E402

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
    total = sum(tree.validate_history(years, SEASONS))
    return f"{total:,} public commit contributions | {years[0]['year']}-{years[-1]['year']} season-years"


def render(history: dict, theme) -> str:
    return tree.render(history, theme, SEASONS, summary(history))


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
