import hashlib
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np

from generators.waveform import waveform
from nord import THEMES


SVG = {"svg": "http://www.w3.org/2000/svg"}


class HeaderLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"source", "img"}:
            return
        attrs = dict(attrs)
        url = attrs.get("srcset" if tag == "source" else "src", "")
        if "/assets/header/waveform-" in url:
            self.links.append(url)


class WaveformTests(unittest.TestCase):
    def assert_header_versions(self, readme, stem):
        parser = HeaderLinkParser()
        parser.feed(readme)
        self.assertEqual(
            [Path(urlsplit(link).path).name for link in parser.links],
            ["waveform-dark.svg", "waveform-light.svg", "waveform-dark.svg"],
        )
        versions = {}
        for link in parser.links:
            parts = urlsplit(link)
            name = Path(parts.path).name
            path = stem.with_name(name)
            expected = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            self.assertEqual(parse_qs(parts.query).get("v"), [expected])
            versions[name] = expected
        return versions, parser.links

    def test_envelope_uses_audio_and_trims_silent_tail(self):
        samples = np.concatenate(
            [
                np.zeros(160, dtype="<i2"),
                np.full(240, 8192, dtype="<i2"),
                np.full(240, 16384, dtype="<i2"),
                np.zeros(160, dtype="<i2"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sequence.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(samples.tobytes())
            with patch.object(waveform, "WAV_PATH", path):
                envelope = waveform.load_envelope()

        self.assertEqual(len(envelope), waveform.BARS)
        np.testing.assert_allclose(envelope[:40], 0.03)
        np.testing.assert_allclose(envelope[40:100], 0.5)
        np.testing.assert_allclose(envelope[100:], 1.0)

    def test_bars_breathe_smoothly_without_peak_dots(self):
        envelope = np.linspace(0.03, 1.0, waveform.BARS)
        spline = "0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"
        for theme in THEMES:
            with self.subTest(theme=theme.name):
                root = ET.fromstring(waveform.render(envelope, theme))
                self.assertEqual(root.findall(".//svg:circle", SVG), [])
                group = root.find("svg:g", SVG)
                self.assertIsNotNone(group)
                bars = group.findall("svg:rect", SVG)
                self.assertEqual(len(bars), 160)

                durations = set()
                starts = set()
                for index, bar in enumerate(bars):
                    animations = {
                        animation.get("attributeName"): animation
                        for animation in bar.findall("svg:animate", SVG)
                    }
                    self.assertEqual(set(animations), {"height", "y"})
                    height = animations["height"]
                    y = animations["y"]
                    for animation in (height, y):
                        self.assertEqual(animation.get("calcMode"), "spline")
                        self.assertEqual(animation.get("keySplines"), spline)
                        self.assertEqual(animation.get("repeatCount"), "indefinite")
                        values = animation.get("values").split(";")
                        self.assertEqual(len(values), 4)
                        self.assertEqual(values[0], values[-1])

                    self.assertEqual(height.get("dur"), y.get("dur"))
                    self.assertEqual(height.get("begin"), y.get("begin"))
                    durations.add(height.get("dur"))
                    starts.add(height.get("begin"))
                    duration = float(height.get("dur").removesuffix("s"))
                    self.assertGreaterEqual(duration, 1.8)
                    self.assertLessEqual(duration, 3.18)
                    self.assertLessEqual(float(height.get("begin").removesuffix("s")), 0)

                    heights = [float(value) for value in height.get("values").split(";")]
                    positions = [float(value) for value in y.get("values").split(";")]
                    self.assertAlmostEqual(
                        heights[0], max(4.0, envelope[index] * waveform.HEIGHT * 0.78), delta=0.051
                    )
                    self.assertGreater(heights[1], heights[0])
                    self.assertLess(heights[2], heights[0])
                    for h, position in zip(heights, positions):
                        self.assertAlmostEqual(position + h / 2, waveform.HEIGHT / 2, delta=0.076)

                self.assertGreater(len(durations), 1)
                self.assertEqual(len(starts), len(bars))

    def test_both_published_assets_match_the_generator(self):
        envelope = waveform.load_envelope()
        for theme in THEMES:
            with self.subTest(theme=theme.name):
                path = waveform.OUT_STEM.with_name(f"{waveform.OUT_STEM.name}-{theme.name}.svg")
                actual = path.read_text(encoding="utf-8")
                expected = waveform.render(envelope, theme)
                self.assertTrue(
                    actual == expected,
                    f"{path.name} is stale; run python generators/waveform/waveform.py",
                )

    def test_readme_uses_current_version_for_both_themes_and_fallback(self):
        self.assert_header_versions(
            waveform.README_PATH.read_text(encoding="utf-8"), waveform.OUT_STEM
        )

    def test_rendering_refreshes_header_versions_when_audio_changes(self):
        original = (
            '<p>Keep this content.</p>\n<picture>\n'
            '<source srcset="https://example.test/assets/header/waveform-dark.svg?source=profile&amp;v=old#top">\n'
            '<source srcset="https://example.test/assets/header/waveform-light.svg?v=old">\n'
            '<img src="https://example.test/assets/header/waveform-dark.svg">\n'
            '</picture>\n<img src="https://example.test/assets/social/website.svg?v=old">'
        )
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(original, encoding="utf-8")
            stem = Path(directory) / "waveform"
            envelope = np.linspace(0.03, 1.0, waveform.BARS)
            with (
                patch.object(waveform, "README_PATH", readme),
                patch.object(waveform, "OUT_STEM", stem),
                patch.object(waveform, "load_envelope", return_value=envelope) as load_envelope,
            ):
                waveform.render_all()
                first = readme.read_text(encoding="utf-8")
                first_versions, links = self.assert_header_versions(first, stem)
                self.assertEqual(parse_qs(urlsplit(links[0]).query)["source"], ["profile"])
                self.assertEqual(urlsplit(links[0]).fragment, "top")
                self.assertIn('<p>Keep this content.</p>', first)
                self.assertIn('assets/social/website.svg?v=old', first)

                load_envelope.return_value = envelope[::-1]
                waveform.render_all()
                second = readme.read_text(encoding="utf-8")
                second_versions, _ = self.assert_header_versions(second, stem)
                for name in first_versions:
                    self.assertNotEqual(first_versions[name], second_versions[name])

                waveform.render_all()
                self.assertEqual(readme.read_text(encoding="utf-8"), second)

    def test_missing_theme_link_fails_without_changing_readme(self):
        original = '<img src="https://example.test/assets/header/waveform-dark.svg">'
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(original, encoding="utf-8")
            with (
                patch.object(waveform, "README_PATH", readme),
                patch.object(waveform, "OUT_STEM", Path(directory) / "waveform"),
            ):
                with self.assertRaisesRegex(RuntimeError, "waveform-light.svg"):
                    waveform.render_all()
            self.assertEqual(readme.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
