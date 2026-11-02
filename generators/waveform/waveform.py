"""Audio-reactive header rendered from the community sequencer's own WAV.

Every time a visitor adds a note the sequencer rewrites ``sequence.wav`` and
this module turns it into a breathing bar-waveform with name and taglines.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nord import ASSETS, AURORA, Theme, esc, svg_open, text, write_pair  # noqa: E402

WAV_PATH = ASSETS / "sequencer" / "sequence.wav"
OUT_STEM = ASSETS / "header" / "waveform"

WIDTH, HEIGHT = 1200, 300
BARS = 160
BAR_W = 5.0
NAME = "Marie-Lynne Block"
TAGLINES = [
    "AI expert & data scientist",
    "creative coder · sound designer",
    "L-systems, live algorithms & latent spaces",
    "humanising the AI era, one commit at a time",
    "this header is drawn from the sequencer below ↓",
]


def load_envelope() -> np.ndarray:
    with wave.open(str(WAV_PATH), "rb") as w:
        frames = w.readframes(w.getnframes())
        width = w.getsampwidth()
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[width]
    samples = np.frombuffer(frames, dtype=dtype).astype(np.float64)
    samples /= float(np.iinfo(dtype).max)
    # Trim the silent tail so bars span the actual music.
    nonzero = np.flatnonzero(np.abs(samples) > 0.002)
    if nonzero.size:
        samples = samples[: nonzero[-1] + 1]
    chunks = np.array_split(samples, BARS)
    rms = np.array([np.sqrt(np.mean(c ** 2)) if c.size else 0.0 for c in chunks])
    peak = rms.max() or 1.0
    return np.clip(rms / peak, 0.03, 1.0)


def render(env: np.ndarray, theme: Theme) -> str:
    cy = HEIGHT / 2
    max_h = HEIGHT * 0.78
    span = WIDTH - 80
    step = span / BARS
    parts = [svg_open(WIDTH, HEIGHT, theme, f"{NAME} — audio-reactive header rendered from the visitor sequencer")]
    parts.append(
        "<defs>"
        '<linearGradient id="aurora" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{0}" y2="0">'.format(WIDTH)
        + "".join(f'<stop offset="{i / (len(AURORA) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(AURORA))
        + "</linearGradient>"
        f'<linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{theme.bg}" stop-opacity="0.7"/>'
        f'<stop offset="0.5" stop-color="{theme.bg}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{theme.bg}" stop-opacity="0.7"/></linearGradient>'
        f'<filter id="blur"><feGaussianBlur stdDeviation="18"/></filter>'
        "</defs>"
    )
    parts.append('<g fill="url(#aurora)" opacity="0.9">')
    for i, v in enumerate(env):
        x = 40 + i * step
        h = max(4.0, v * max_h)
        hi, lo = h * 1.18, max(4.0, h * 0.72)
        dur = 1.8 + (i % 7) * 0.23
        begin = -(i * 0.07)  # negative begin → bars are mid-animation at load, no visible "start"
        parts.append(
            f'<rect x="{x:.1f}" y="{cy - h / 2:.1f}" width="{BAR_W}" height="{h:.1f}" rx="2.5">'
            f'<animate attributeName="height" values="{h:.1f};{hi:.1f};{lo:.1f};{h:.1f}" dur="{dur:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"/>'
            f'<animate attributeName="y" values="{cy - h / 2:.1f};{cy - hi / 2:.1f};{cy - lo / 2:.1f};{cy - h / 2:.1f}" dur="{dur:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"/>'
            "</rect>"
        )
    parts.append("</g>")
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="url(#fade)"/>')
    # Soft backing so the name and taglines stay legible over the bars.
    parts.append(f'<rect x="{WIDTH / 2 - 330}" y="{cy - 64}" width="660" height="134" rx="40" fill="{theme.bg}" opacity="0.72" filter="url(#blur)"/>')
    # Name + rotating taglines
    parts.append(text(WIDTH / 2, cy - 6, NAME, theme.text, 54, anchor="middle", weight="bold",
                      extra='letter-spacing="2"'))
    per = 4.0
    total = per * len(TAGLINES)
    for i, line in enumerate(TAGLINES):
        a, b = i / len(TAGLINES), (i + 1) / len(TAGLINES)
        fade = 0.12 / len(TAGLINES)
        key_times = f"0;{a:.4f};{a + fade:.4f};{b - fade:.4f};{b:.4f};1"
        values = "0;0;1;1;0;0"
        parts.append(
            f'<text x="{WIDTH / 2}" y="{cy + 44}" fill="{theme.text}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" '
            f'font-size="20" text-anchor="middle" opacity="0">{esc(line)}'
            f'<animate attributeName="opacity" values="{values}" keyTimes="{key_times}" dur="{total:.1f}s" repeatCount="indefinite"/>'
            "</text>"
        )
    parts.append(text(WIDTH - 40, HEIGHT - 18, "themunchkinalgorithm.world", theme.muted, 13, anchor="end"))
    parts.append(text(40, HEIGHT - 18, "no static pixels · rendered by this repo's own actions", theme.muted, 13))
    parts.append("</svg>")
    return "".join(parts)


def render_all() -> list[Path]:
    env = load_envelope()
    return write_pair(OUT_STEM, lambda t: render(env, t))


if __name__ == "__main__":
    for p in render_all():
        print(f"wrote {p.relative_to(ASSETS.parent)} ({p.stat().st_size // 1024} KB)")
