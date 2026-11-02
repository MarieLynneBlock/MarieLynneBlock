import copy
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from generators.garden import forest, lsystem
from generators import playground
from nord import THEMES


SVG = {"svg": "http://www.w3.org/2000/svg"}


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


class ForestTests(unittest.TestCase):
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

    def test_spring_and_summer_legend_markers_are_clear_in_both_themes(self):
        history, _ = self.collect_fixture()
        for theme in THEMES:
            root = ET.fromstring(forest.render(history, theme))
            markers = root.findall(".//svg:circle[@cy='476']", SVG)
            self.assertEqual(len(markers), 12)
            palettes = (
                lsystem.LIGHT_SEASON_PALETTES
                if theme.name == "light" else lsystem.SEASON_PALETTES
            )
            for index, season in enumerate(forest.SEASONS):
                expected = palettes.get(season, lsystem.SEASON_PALETTES[season])[1]
                actual = [marker.attrib["fill"] for marker in markers[index * 3:index * 3 + 3]]
                self.assertEqual(actual, expected)
                self.assertTrue(all(
                    marker.attrib["r"] == "2.7"
                    for marker in markers[index * 3:index * 3 + 3]
                ))
            self.assertNotEqual(
                {marker.attrib["fill"] for marker in markers[3:6]},
                {marker.attrib["fill"] for marker in markers[6:9]},
            )

    def test_forest_is_history_driven_and_render_is_deterministic(self):
        history, _ = self.collect_fixture()
        snapshot = copy.deepcopy(history)
        for theme in THEMES:
            rendered = forest.render(history, theme)
            self.assertEqual(rendered, forest.render(history, theme))
            root = ET.fromstring(rendered)
            trees = root.findall(".//svg:g[@data-year]", SVG)
            self.assertEqual(len(trees), 3)
            counts = [int(g.attrib["data-commits"]) for g in trees]
            self.assertEqual(sum(counts), 17)
            self.assertNotIn("visitor", rendered.lower())
            self.assertNotIn("decoration", rendered.lower())
        self.assertEqual(history, snapshot)

    def test_many_empty_years_render_without_inventing_trees(self):
        history, _ = self.collect_fixture()
        history["years"] = [
            {"year": year, "seasons": {
                season: {"commits": 0, "repositories": {}} for season in forest.SEASONS
            }}
            for year in range(2000, 2027)
        ]
        root = ET.fromstring(forest.render(history, THEMES[0]))
        self.assertEqual(len(root.findall(".//svg:g[@data-year]", SVG)), 0)
        self.assertEqual(root.attrib["height"], "560")
        self.assertIn("No public commit contributions recorded yet.", "".join(root.itertext()))

    def test_existing_render_entry_point_and_readme_credit_use_history(self):
        history, _ = self.collect_fixture()
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "garden"
            with patch.object(forest, "load_history", return_value=history), patch.object(forest, "OUT_STEM", stem):
                paths = lsystem.render_all()
                self.assertEqual(len(paths), 2)
                self.assertTrue(all(path.exists() for path in paths))
                self.assertEqual(lsystem.render(THEMES[0]), paths[0].read_text())
                with patch.object(playground, "update_readme_marker") as marker:
                    playground.refresh_readme(playground.sequencer.load_state())
                credit = marker.call_args_list[0].args[1]
                self.assertIn("17 public commit contributions", credit)
                self.assertIn("refreshed nightly", credit)
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

    def test_sequencer_issue_does_not_change_forest_history_or_rendering(self):
        history, _ = self.collect_fixture()
        snapshot = copy.deepcopy(history)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(forest, "load_history", return_value=history),
                patch.object(forest, "refresh_history") as refresh,
                patch.object(forest, "OUT_STEM", Path(directory) / "garden"),
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

    def test_published_assets_match_cached_history(self):
        history = forest.load_history()
        for theme in THEMES:
            expected = forest.render(history, theme)
            path = forest.OUT_STEM.with_name(f"garden-{theme.name}.svg")
            self.assertEqual(path.read_text(encoding="utf-8"), expected)
            self.assertLess(len(expected.encode()), lsystem.MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
