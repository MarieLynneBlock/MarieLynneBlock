import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import numpy as np

from generators.waveform import waveform
from nord import THEMES


SVG = {"svg": "http://www.w3.org/2000/svg"}


class WaveformTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
