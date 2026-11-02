import copy
import hashlib
import json
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from generators.garden import forest, lsystem
from generators import playground
from nord import THEMES


SVG = {"svg": "http://www.w3.org/2000/svg"}
GARDEN_README = (
    '<p>Keep this content.</p>\n<picture>\n'
    '<source srcset="https://example.test/assets/garden/garden-dark.svg?source=profile&amp;v=old#top">\n'
    '<source srcset="https://example.test/assets/garden/garden-light.svg?v=old">\n'
    '<img src="https://example.test/assets/garden/garden-dark.svg">\n'
    '</picture>\n<img src="https://example.test/assets/social/website.svg?v=old">'
)


class GardenLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"source", "img"}:
            return
        attrs = dict(attrs)
        url = attrs.get("srcset" if tag == "source" else "src", "")
        if "/assets/garden/garden-" in url:
            self.links.append(url)


def group(repository, days, more=False, cursor=None, private=False):
    return {
        "repository": {"nameWithOwner": repository, "isPrivate": private},
        "contributions": {
            "nodes": [{"occurredAt": date, "commitCount": count} for date, count in days],
            "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        },
    }


def response(groups):
    return {"user": {"contributionsCollection": {"commitContributionsByRepository": groups}}}


def representative_history():
    counts = {
        2016: (0, 0, 0, 0),
        2017: (0, 91, 181, 440),
        2018: (274, 196, 30, 4),
        2019: (0, 0, 3, 0),
        2020: (0, 0, 67, 13),
        2021: (0, 15, 1, 2),
        2022: (0, 0, 0, 0),
        2023: (0, 0, 113, 4),
        2024: (8, 55, 209, 15),
        2025: (0, 0, 0, 2),
        2026: (95, 62, 19, 49),
    }
    return {
        "login": "owner",
        "through": "2026-11-02",
        "years": [
            {
                "year": year,
                "seasons": {
                    season: {
                        "commits": count,
                        "repositories": {"owner/repo": count} if count else {},
                    }
                    for season, count in zip(forest.SEASONS, values)
                },
            }
            for year, values in counts.items()
        ],
    }


def contrast(foreground, background):
    def luminance(colour):
        rgb = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        r, g, b = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        return .2126 * r + .7152 * g + .0722 * b

    low, high = sorted((luminance(foreground), luminance(background)))
    return (high + .05) / (low + .05)


class ForestTests(unittest.TestCase):
    def assert_garden_versions(self, readme, stem):
        parser = GardenLinkParser()
        parser.feed(readme)
        self.assertEqual(
            [Path(urlsplit(link).path).name for link in parser.links],
            ["garden-dark.svg", "garden-light.svg", "garden-dark.svg"],
        )
        versions = {}
        for link in parser.links:
            parts = urlsplit(link)
            name = Path(parts.path).name
            expected = hashlib.sha256(stem.with_name(name).read_bytes()).hexdigest()[:16]
            self.assertEqual(parse_qs(parts.query).get("v"), [expected])
            versions[name] = expected
        return versions, parser.links

    def test_continuous_winter_and_season_boundaries_in_utc(self):
        cases = {
            "2018-12-01T00:00:00Z": (2019, "winter"),
            "2019-01-01T00:00:00Z": (2019, "winter"),
            "2020-02-29T23:59:59Z": (2020, "winter"),
            "2019-03-01T00:00:00Z": (2019, "spring"),
            "2019-05-31T23:59:59Z": (2019, "spring"),
            "2019-06-01T00:00:00Z": (2019, "summer"),
            "2019-08-31T23:59:59Z": (2019, "summer"),
            "2019-09-01T00:00:00Z": (2019, "autumn"),
            "2019-11-30T23:59:59Z": (2019, "autumn"),
            "2019-03-01T00:30:00+01:00": (2019, "winter"),
        }
        for date, expected in cases.items():
            with self.subTest(date=date):
                self.assertEqual(forest.season_for_date(date), expected)

    def collect_fixture(self):
        pages = [
            {"user": {"createdAt": "2018-02-01T00:00:00Z"}},
            response([
                group("owner/repo", [("2018-12-20T00:00:00Z", 5)], True, "page2"),
                group("private/hidden", [("2018-12-20T00:00:00Z", 100)], private=True),
                group("other/project", [("2018-04-01T00:00:00Z", 3)]),
            ]),
            response([
                group("owner/repo", [("2018-06-01T00:00:00Z", 2)]),
                # Other repositories' pages must not be added a second time.
                group("other/project", [("2018-04-01T00:00:00Z", 3)]),
            ]),
            response([group("owner/repo", [("2019-02-01T00:00:00Z", 7)])]),
        ]
        with patch.object(forest, "graphql", side_effect=pages) as api:
            history = forest.collect_history("owner", datetime(2019, 6, 1, tzinfo=timezone.utc))
        return history, api

    def test_collects_public_commits_across_repos_and_pages_without_duplicates(self):
        history, api = self.collect_fixture()
        self.assertEqual([y["year"] for y in history["years"]], [2018, 2019])
        first, second = history["years"]
        self.assertEqual(first["seasons"]["spring"]["commits"], 3)
        self.assertEqual(first["seasons"]["summer"]["commits"], 2)
        self.assertEqual(first["seasons"]["winter"]["commits"], 0)
        self.assertEqual(second["seasons"]["winter"], {
            "commits": 12, "repositories": {"owner/repo": 12},
        })
        self.assertNotIn("hidden", json.dumps(history))
        self.assertEqual(api.call_args_list[2].kwargs["cursor"], "page2")
        self.assertEqual(api.call_args_list[-1].kwargs["to"], "2019-06-01T00:00:00+00:00")
        self.assertIn("17 public commit contributions", forest.summary(history))

    def test_december_creates_next_year_winter_and_preserves_empty_years(self):
        pages = [
            {"user": {"createdAt": "2018-02-01T00:00:00Z"}},
            response([]),
            response([group("owner/repo", [("2019-12-20T00:00:00Z", 1)])]),
        ]
        with patch.object(forest, "graphql", side_effect=pages):
            history = forest.collect_history("owner", datetime(2019, 12, 31, tzinfo=timezone.utc))
        self.assertEqual([y["year"] for y in history["years"]], [2018, 2019, 2020])
        self.assertEqual(history["years"][-1]["seasons"]["winter"]["commits"], 1)
        self.assertEqual(sum(s["commits"] for s in history["years"][0]["seasons"].values()), 0)

    def test_refuses_repository_limit_and_keeps_previous_cache_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "history.json"
            cache.write_text('{"previous": true}\n')
            pages = [
                {"user": {"createdAt": f"{datetime.now(timezone.utc).year}-01-01T00:00:00Z"}},
                response([group(f"owner/repo{i}", []) for i in range(100)]),
            ]
            with patch.object(forest, "HISTORY_PATH", cache), patch.object(forest, "graphql", side_effect=pages):
                with self.assertRaisesRegex(RuntimeError, "100-repository limit"):
                    forest.refresh_history()
            self.assertEqual(json.loads(cache.read_text()), {"previous": True})

    def test_graphql_errors_are_not_success_shaped(self):
        with patch.object(forest.subprocess, "run") as run:
            run.return_value.stdout = '{"errors":[{"message":"rate limited"}]}'
            with self.assertRaisesRegex(RuntimeError, "rate limited"):
                forest.graphql("query { viewer { login } }")
        with patch.object(forest.subprocess, "run", side_effect=subprocess.CalledProcessError(
            1, ["gh"], stderr="authentication required",
        )):
            with self.assertRaisesRegex(RuntimeError, "authentication required"):
                forest.graphql("query { viewer { login } }")

    def test_repeated_pagination_cursor_is_rejected(self):
        repeating = response([group("owner/repo", [], True, "same")])
        pages = [{"user": {"createdAt": "2018-01-01T00:00:00Z"}}, repeating, repeating]
        with patch.object(forest, "graphql", side_effect=pages):
            with self.assertRaisesRegex(RuntimeError, "Invalid contribution cursor"):
                forest.collect_history("owner", datetime(2018, 6, 1, tzinfo=timezone.utc))

    def test_missing_cache_is_actionable(self):
        with patch.object(forest, "HISTORY_PATH", Path("/nonexistent/forest/history.json")):
            with self.assertRaisesRegex(FileNotFoundError, "--refresh"):
                forest.load_history()

    def test_season_legend_is_distinct_and_readable_in_both_themes(self):
        history, _ = self.collect_fixture()
        for theme in THEMES:
            root = ET.fromstring(forest.render(history, theme))
            palettes = (
                lsystem.LIGHT_SEASON_PALETTES
                if theme.name == "light" else lsystem.SEASON_PALETTES
            )
            groups = root.findall(".//svg:g[@class='legend-marker']", SVG)
            self.assertEqual([group.attrib["data-legend-season"] for group in groups], list(forest.SEASONS))
            self.assertGreaterEqual(contrast(theme.text, theme.bg), 4.5)
            self.assertGreaterEqual(contrast(theme.muted, theme.bg), 4.5)
            shapes = []
            for group, season in zip(groups, forest.SEASONS):
                markers = list(group)
                self.assertEqual(len(markers), 3)
                shapes.append(markers[0].tag)
                expected = palettes[season][1]
                actual = [marker.attrib["stroke" if season == "winter" else "fill"] for marker in markers]
                self.assertEqual(actual, expected)
                self.assertTrue(all(contrast(colour, theme.bg) >= 3 for colour in actual))
            self.assertEqual(shapes, [f"{{{SVG['svg']}}}{tag}" for tag in ("path", "circle", "ellipse", "path")])
            self.assertIn("h4M", groups[0][0].attrib["d"])
            self.assertTrue(groups[3][0].attrib["d"].endswith("Z"))
            self.assertNotEqual(set(palettes["spring"][1]), set(palettes["summer"][1]))

    def test_tree_is_history_driven_and_render_is_deterministic(self):
        history, _ = self.collect_fixture()
        snapshot = copy.deepcopy(history)
        expected = {
            (str(year["year"]), season): year["seasons"][season]["commits"]
            for year in history["years"] for season in forest.SEASONS
            if year["seasons"][season]["commits"]
        }
        for theme in THEMES:
            rendered = forest.render(history, theme)
            self.assertEqual(rendered, forest.render(history, theme))
            root = ET.fromstring(rendered)
            self.assertEqual(len(root.findall(".//svg:g[@class='trunk']", SVG)), 1)
            limbs = root.findall(".//svg:g[@class='limb']", SVG)
            self.assertEqual({group.attrib["data-year"] for group in limbs}, {"2018", "2019"})
            self.assertEqual(sum(int(group.attrib["data-commits"]) for group in limbs), 17)
            seasons = {}
            for limb in limbs:
                for group in limb.findall("./svg:g[@class='season']", SVG):
                    key = (limb.attrib["data-year"], group.attrib["data-season"])
                    self.assertNotIn(key, seasons)
                    seasons[key] = int(group.attrib["data-commits"])
            self.assertEqual(seasons, expected)
            anchors = {group.attrib["data-year"]: float(group.attrib["data-anchor-y"]) for group in limbs}
            self.assertGreater(anchors["2018"], anchors["2019"])
            self.assertIn("Winter starts in the previous December", root.find("svg:desc", SVG).text)
            self.assertIn("prefers-reduced-motion:reduce", rendered)
            self.assertIn(".limb{animation:none}", rendered)
            self.assertFalse(root.findall(".//svg:a", SVG))
            self.assertFalse(any(
                re.fullmatch(r"\d{4}", "".join(node.itertext()).strip())
                for node in root.findall(".//svg:text", SVG)
            ))
            self.assertNotIn("visitor", rendered.lower())
            self.assertNotIn("decoration", rendered.lower())
        self.assertEqual(history, snapshot)

    def test_many_empty_years_render_knots_without_inventing_growth(self):
        history, _ = self.collect_fixture()
        history["years"] = [
            {"year": year, "seasons": {
                season: {"commits": 0, "repositories": {}} for season in forest.SEASONS
            }}
            for year in range(2000, 2027)
        ]
        root = ET.fromstring(forest.render(history, THEMES[0]))
        self.assertFalse(root.findall(".//svg:g[@class='limb']", SVG))
        self.assertFalse(root.findall(".//svg:g[@class='season']", SVG))
        knots = root.findall(".//svg:g[@class='quiet-year']", SVG)
        self.assertEqual(len(knots), 27)
        self.assertEqual([int(group.attrib["data-year"]) for group in knots], list(range(2000, 2027)))
        anchors = [float(group.attrib["data-anchor-y"]) for group in knots]
        self.assertTrue(all(a - b >= 17.9 for a, b in zip(anchors, anchors[1:])))
        self.assertGreater(int(root.attrib["height"]), 570)
        self.assertIn("No public commit contributions recorded yet.", "".join(root.itertext()))

    def test_foliage_is_open_and_attached_to_the_correct_limb(self):
        history = representative_history()
        expected_totals = {
            str(year["year"]): sum(year["seasons"][season]["commits"] for season in forest.SEASONS)
            for year in history["years"]
        }
        for theme in THEMES:
            root = ET.fromstring(forest.render(history, theme))
            points = []
            limbs = root.findall(".//svg:g[@class='limb']", SVG)
            knots = root.findall(".//svg:g[@class='quiet-year']", SVG)
            self.assertEqual(
                {group.attrib["data-year"]: int(group.attrib["data-commits"]) for group in limbs},
                {year: count for year, count in expected_totals.items() if count},
            )
            self.assertEqual({group.attrib["data-year"] for group in knots}, {"2016", "2022"})
            for limb in limbs:
                outline = limb.find("./svg:path", SVG).attrib["d"]
                vertices = [
                    (float(x), float(y))
                    for x, y in re.findall(r"[ML](-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", outline)
                ]
                self.assertEqual(len(vertices), 34)
                centres = [
                    ((vertices[i][0] + vertices[-i - 1][0]) / 2, (vertices[i][1] + vertices[-i - 1][1]) / 2)
                    for i in range(17)
                ]
                for group in limb.findall("./svg:g[@class='season']", SVG):
                    branch = group.find("./svg:path", SVG).attrib["d"]
                    match = re.match(r"M(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", branch)
                    self.assertIsNotNone(match)
                    x, y = map(float, match.groups())
                    self.assertLess(min((x - cx) ** 2 + (y - cy) ** 2 for cx, cy in centres), .03)
                    key = (limb.attrib["data-year"], group.attrib["data-season"])
                    leaves = group.findall(".//svg:g[@class='leaves']/svg:path", SVG)
                    self.assertTrue(leaves)
                    for path in leaves:
                        for lx, ly in re.findall(r"M(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)h0", path.attrib["d"]):
                            points.append((float(lx), float(ly), key))
            self.assertEqual(len(root.findall(".//svg:g[@class='season']", SVG)), 24)
            self.assertGreater(len(points), 500)
            close = sum(
                any(other != key and (x - xx) ** 2 + (y - yy) ** 2 < 64 for xx, yy, other in points)
                for x, y, key in points
            )
            self.assertLess(close / len(points), .25)

    def test_long_active_history_keeps_every_season_within_image_budget(self):
        history = representative_history()
        history["years"] = [
            {
                "year": year,
                "seasons": {
                    season: {"commits": 100, "repositories": {"owner/repo": 100}}
                    for season in forest.SEASONS
                },
            }
            for year in range(2000, 2027)
        ]
        for theme in THEMES:
            with self.subTest(theme=theme.name):
                rendered = forest.render(history, theme)
                self.assertLess(len(rendered.encode("utf-8")), lsystem.MAX_BYTES)
                root = ET.fromstring(rendered)
                self.assertGreater(int(root.attrib["height"]), 570)
                limbs = root.findall(".//svg:g[@class='limb']", SVG)
                self.assertEqual(len(limbs), 27)
                for limb in limbs:
                    seasons = limb.findall("./svg:g[@class='season']", SVG)
                    self.assertEqual([group.attrib["data-season"] for group in seasons], list(forest.SEASONS))
                    self.assertTrue(all(group.attrib["data-commits"] == "100" for group in seasons))
                    self.assertTrue(all(group.findall(".//svg:g[@class='leaves']/svg:path", SVG) for group in seasons))

    def test_image_budget_failure_is_explicit(self):
        history, _ = self.collect_fixture()
        with patch.object(lsystem, "MAX_BYTES", 100):
            with self.assertRaisesRegex(OverflowError, "image limit even at minimum detail"):
                forest.render(history, THEMES[0])

    def test_single_season_stays_inside_artwork(self):
        for theme in THEMES:
            for season in forest.SEASONS:
                history = representative_history()
                history["years"] = [history["years"][-1]]
                for name in forest.SEASONS:
                    history["years"][0]["seasons"][name] = {
                        "commits": 100 if name == season else 0,
                        "repositories": {"owner/repo": 100} if name == season else {},
                    }
                with self.subTest(theme=theme.name, season=season):
                    root = ET.fromstring(forest.render(history, theme))
                    groups = root.findall(".//svg:g[@class='season']", SVG)
                    self.assertEqual(len(groups), 1)
                    coordinates = [
                        (float(x), float(y))
                        for path in groups[0].iter(f"{{{SVG['svg']}}}path")
                        for x, y in re.findall(
                            r"[ML](-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path.attrib["d"]
                        )
                    ]
                    self.assertTrue(coordinates)
                    self.assertTrue(all(19.9 <= x <= 880.1 and 83.9 <= y <= 460.1 for x, y in coordinates))

    def test_invalid_or_unordered_history_is_rejected(self):
        history, _ = self.collect_fixture()
        history["years"] = []
        with self.assertRaisesRegex(ValueError, "no season-years"):
            forest.render(history, THEMES[0])

        history, _ = self.collect_fixture()
        history["years"].reverse()
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            forest.render(history, THEMES[0])

        for invalid in (-1, True, 1.5, "3"):
            history, _ = self.collect_fixture()
            history["years"][0]["seasons"]["spring"]["commits"] = invalid
            with self.subTest(count=invalid), self.assertRaisesRegex(ValueError, "Invalid commit count"):
                forest.render(history, THEMES[0])

        history, _ = self.collect_fixture()
        history["years"][0]["year"] = 2018.5
        with self.assertRaisesRegex(ValueError, "season-years must be integers"):
            forest.render(history, THEMES[0])

        history, _ = self.collect_fixture()
        history["years"][0]["seasons"].pop("winter")
        with self.assertRaisesRegex(ValueError, "Invalid seasons"):
            forest.render(history, THEMES[0])

    def test_existing_render_entry_point_and_readme_credit_use_history(self):
        history, _ = self.collect_fixture()
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "garden"
            readme = Path(directory) / "README.md"
            readme.write_text(GARDEN_README, encoding="utf-8")
            with (
                patch.object(forest, "load_history", return_value=history),
                patch.object(forest, "OUT_STEM", stem),
                patch.object(forest, "README_PATH", readme),
            ):
                paths = lsystem.render_all()
                self.assertEqual(len(paths), 2)
                self.assertTrue(all(path.exists() for path in paths))
                self.assertEqual(lsystem.render(THEMES[0]), paths[0].read_text())
                with patch.object(playground, "update_readme_marker") as marker:
                    playground.refresh_readme(playground.sequencer.load_state())
                credit = marker.call_args_list[0].args[1]
                self.assertIn("17 public commit contributions", credit)
                self.assertIn("refreshed nightly", credit)
                self.assertIn("season-years", credit)
                self.assertNotIn("gardener", credit)

    def test_garden_action_titles_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "sequencer button"):
            playground.parse_title("garden: grow")
        self.assertEqual(playground.parse_title("sequencer: G4"), ("sequencer", "G4"))

    def test_render_only_reports_success_for_nightly_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output"
            with (
                patch("sys.argv", ["playground.py", "--render-only"]),
                patch.dict("os.environ", {"GITHUB_OUTPUT": str(output)}),
                patch.object(playground, "render_everything"),
            ):
                self.assertEqual(playground.main(), 0)
            self.assertEqual(output.read_text(), "status=ok\n")

    def test_nightly_refresh_rebuilds_tree_and_readme_from_history(self):
        history, _ = self.collect_fixture()
        state = {"steps": [{"pitch": None} for _ in range(playground.sequencer.STEPS)], "cursor": 0}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme, cache, output = root / "README.md", root / "history.json", root / "github-output"
            readme.write_text(
                GARDEN_README
                + "\n<!-- GARDEN:CREDITS:START -->old<!-- GARDEN:CREDITS:END -->"
                + "\n<!-- SEQUENCER:CREDITS:START -->old<!-- SEQUENCER:CREDITS:END -->",
                encoding="utf-8",
            )
            stem = root / "garden"
            with (
                patch("sys.argv", ["playground.py", "--refresh-history", "--render-only"]),
                patch.dict("os.environ", {"GITHUB_OUTPUT": str(output)}),
                patch.object(forest, "collect_history", return_value=history) as collect,
                patch.object(forest, "HISTORY_PATH", cache),
                patch.object(forest, "OUT_STEM", stem),
                patch.object(forest, "README_PATH", readme),
                patch.object(playground, "README", readme),
                patch.object(playground.sequencer, "load_state", return_value=state),
                patch.object(playground.sequencer, "render_all"),
                patch.object(playground.sequencer, "save_state"),
                patch.object(playground.waveform, "render_all"),
            ):
                self.assertEqual(playground.main(), 0)
                collect.assert_called_once_with()
                self.assertEqual(json.loads(cache.read_text()), history)
                self.assertEqual(stem.with_name("garden-dark.svg").read_text(), forest.render(history, THEMES[0]))
                updated = readme.read_text(encoding="utf-8")
                self.assertIn(f"<strong>{forest.summary(history)}</strong>", updated)
                self.assert_garden_versions(updated, stem)
                self.assertEqual(output.read_text(), "status=ok\n")

    def test_sequencer_issue_does_not_change_tree_history_or_rendering(self):
        history, _ = self.collect_fixture()
        snapshot = copy.deepcopy(history)
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(GARDEN_README, encoding="utf-8")
            with (
                patch.object(forest, "load_history", return_value=history),
                patch.object(forest, "refresh_history") as refresh,
                patch.object(forest, "OUT_STEM", Path(directory) / "garden"),
                patch.object(forest, "README_PATH", readme),
                patch.object(playground, "check_rate_limit"),
                patch.object(playground.sequencer, "render_all"),
                patch.object(playground.sequencer, "save_state"),
                patch.object(playground.waveform, "render_all"),
                patch.object(playground, "update_readme_marker"),
            ):
                comment = playground.run("sequencer: G4", "visitor", 7, 1000)
                self.assertIn("sequencer", comment)
                self.assertTrue((Path(directory) / "garden-dark.svg").exists())
                refresh.assert_not_called()
                self.assertEqual(
                    (Path(directory) / "garden-dark.svg").read_text(),
                    forest.render(history, THEMES[0]),
                )
        self.assertEqual(history, snapshot)

    def test_readme_uses_current_version_for_both_themes_and_fallback(self):
        readme = forest.README_PATH.read_text(encoding="utf-8")
        self.assert_garden_versions(readme, forest.OUT_STEM)
        self.assertIn(f"<strong>{forest.summary(forest.load_history())}</strong>", readme)

    def test_rendering_refreshes_garden_versions_when_history_changes(self):
        history, _ = self.collect_fixture()
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(GARDEN_README, encoding="utf-8")
            stem = Path(directory) / "garden"
            with (
                patch.object(forest, "README_PATH", readme),
                patch.object(forest, "OUT_STEM", stem),
                patch.object(forest, "load_history", return_value=history) as load_history,
            ):
                forest.render_all()
                first = readme.read_text(encoding="utf-8")
                first_versions, links = self.assert_garden_versions(first, stem)
                self.assertEqual(parse_qs(urlsplit(links[0]).query)["source"], ["profile"])
                self.assertEqual(urlsplit(links[0]).fragment, "top")
                self.assertIn("<p>Keep this content.</p>", first)
                self.assertIn("assets/social/website.svg?v=old", first)

                changed = copy.deepcopy(history)
                spring = changed["years"][0]["seasons"]["spring"]
                spring["commits"] += 1
                spring["repositories"]["other/project"] += 1
                load_history.return_value = changed
                forest.render_all()
                second = readme.read_text(encoding="utf-8")
                second_versions, _ = self.assert_garden_versions(second, stem)
                for name in first_versions:
                    self.assertNotEqual(first_versions[name], second_versions[name])

                forest.render_all()
                self.assertEqual(readme.read_text(encoding="utf-8"), second)

    def test_missing_garden_theme_link_fails_without_changing_readme(self):
        history, _ = self.collect_fixture()
        original = '<img src="https://example.test/assets/garden/garden-dark.svg">'
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(original, encoding="utf-8")
            with (
                patch.object(forest, "README_PATH", readme),
                patch.object(forest, "OUT_STEM", Path(directory) / "garden"),
                patch.object(forest, "load_history", return_value=history),
            ):
                with self.assertRaisesRegex(RuntimeError, "garden-light.svg"):
                    forest.render_all()
            self.assertEqual(readme.read_text(encoding="utf-8"), original)

    def test_published_assets_match_cached_history(self):
        history = forest.load_history()
        for theme in THEMES:
            expected = forest.render(history, theme)
            path = forest.OUT_STEM.with_name(f"garden-{theme.name}.svg")
            self.assertEqual(path.read_text(encoding="utf-8"), expected)
            self.assertLess(len(expected.encode()), lsystem.MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
