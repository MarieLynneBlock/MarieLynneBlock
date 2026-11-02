"""Audio-reactive header rendered from the community sequencer's own WAV.

Every time a visitor adds a note the sequencer rewrites ``sequence.wav`` and
this module turns it into a bar-waveform that pulses on the sequencer's notes,
with peak-hold dots, name and taglines.
"""

from __future__ import annotations

import base64
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sequencer"))

import sequencer  # noqa: E402
from nord import ASSETS, AURORA, Theme, esc, svg_open, text, write_pair  # noqa: E402

WAV_PATH = ASSETS / "sequencer" / "sequence.wav"
OUT_STEM = ASSETS / "header" / "waveform"
# Quicksand Medium (SIL OFL, see fonts/OFL.txt), subset to the glyphs of NAME and
# embedded so the name looks the same everywhere; re-subset it if NAME changes.
NAME_FONT = Path(__file__).resolve().parent / "fonts" / "name-rounded.woff2"

WIDTH, HEIGHT = 1200, 300
BARS = 120
BAR_W = 5.0
PEAK_R = BAR_W / 2
PEAK_GAP = 4.0 + PEAK_R  # distance from bar end to dot centre
DOT_EVERY = 8
MAX_H = HEIGHT * 0.78
H_CAP = HEIGHT - 2 * (PEAK_GAP + PEAK_R) - 8  # keep bars plus dots inside the frame
# Meter ballistics, synced to the sequencer's notes.
ATTACK = 0.07  # s for a bar to respond to a hit
RELEASE = 0.34  # s exponential decay time constant
RELEASE_SPLINE = "0 .6 .4 1"  # ease-out approximating that decay between keyframes
FLOOR = 0.82  # resting bar height as a fraction of the song envelope
PEAK_HOLD = 0.24  # s a peak dot sticks before sinking
PEAK_FALL = 100.0  # bar-height px/s the peak sinks (each dot moves half of that)
PEAK_FADE = 0.75  # s an un-refreshed dot takes to fade out
PEAK_OPACITY = 0.48
SIM_DT = 0.002
SEED = 7  # fixed so regenerating without new notes yields the same SVG
NAME = "Marie-Lynne Block"
TAGLINES = [
    "AI Expert · Technology Coach",
    "Creative Coder · Mathemagician · Binary Bard",
    "Sound Designer · Producer · Mastering Engineer",
    "Humanising the AI era, one commit at a time",
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


def load_hits() -> tuple[float, list[tuple[float, int]]]:
    """Loop length and (time, pitch index) of every note the sequencer plays."""
    state = sequencer.load_state()
    step_dur = 60.0 / state["bpm"] / 2  # eighth notes, as in sequencer.render_wav
    hits = [(i * step_dur, sequencer.PITCHES.index(s["pitch"]))
            for i, s in enumerate(state["steps"]) if s["pitch"]]
    return step_dur * len(state["steps"]), hits


def simulate(env: np.ndarray, loop: float, hits: list[tuple[float, int]]) -> tuple[np.ndarray, ...]:
    """Bar heights, peak-dot heights and dot opacities sampled every SIM_DT over one loop.

    Bars jump to each hit in ATTACK and decay exponentially; the peak dot follows
    meter ballistics (hold, then slow fall). One warm-up loop makes the result seamless.
    """
    rng = np.random.default_rng(SEED)
    base = np.maximum(4.0, env * MAX_H)
    floor = base * FLOOR
    pos = (np.arange(BARS) + 0.5) / BARS
    peaks = []
    for _, pitch in hits:
        # Higher notes push bars further right a bit, so the melody shows as a sweep.
        centre = (pitch + 0.5) / len(sequencer.PITCHES)
        gain = 0.5 * rng.random(BARS) + 0.5 * np.exp(-(((pos - centre) / 0.35) ** 2))
        peaks.append(np.minimum(base * (0.95 + 0.12 * gain), H_CAP))
    hit_at = {round(t / SIM_DT): k for k, (t, _) in enumerate(hits)}
    n = round(loop / SIM_DT)

    h, d, held = floor.copy(), floor.copy(), np.full(BARS, -1e9)
    src, target, start = floor.copy(), floor.copy(), -1e9
    bars, dots, glow = (np.empty((n + 1, BARS)) for _ in range(3))
    for lap in range(2):
        for j in range(n):
            t = lap * loop + j * SIM_DT
            if j in hit_at:
                src, target, start = h.copy(), np.maximum(peaks[hit_at[j]], h), t
            u = t - start
            if u < ATTACK:
                h = src + (target - src) * u / ATTACK
            else:
                h = floor + (target - floor) * np.exp(-(u - ATTACK) / RELEASE)
            rising = h > d
            held = np.where(rising, t, held)
            sinking = np.maximum(h, d - PEAK_FALL * SIM_DT)
            d = np.where(rising, h, np.where(t - held < PEAK_HOLD, d, sinking))
            if lap:
                bars[j], dots[j] = h, d
                glow[j] = PEAK_OPACITY * np.clip(1 - (t - held) / PEAK_FADE, 0, 1)
    bars[n], dots[n], glow[n] = bars[0], dots[0], glow[0]
    return bars, dots, glow


def _keyframes(loop: float, hit_times: list[float], offsets: list[float]) -> list[float]:
    times = {0.0, loop}
    for t in hit_times:
        times.add(t)
        times.update((t + o) % loop for o in offsets)
    return sorted({round(t / SIM_DT) * SIM_DT for t in times})


def _on_hit(t: float, hit_times: list[float]) -> bool:
    return any(abs(t - h) < SIM_DT / 2 for h in hit_times)


def _num(v: float, digits: int) -> str:
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def render(env: np.ndarray, theme: Theme) -> str:
    cy = HEIGHT / 2
    span = WIDTH - 80
    step = span / BARS
    parts = [svg_open(WIDTH, HEIGHT, theme, f"{NAME} — audio-reactive header rendered from the visitor sequencer")]
    font_data = base64.b64encode(NAME_FONT.read_bytes()).decode("ascii")
    parts.append(
        "<defs><style>@font-face{font-family:'Name Rounded';font-weight:500;"
        f"src:url(data:font/woff2;base64,{font_data}) format('woff2');}}</style></defs>"
    )
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
    loop, hits = load_hits()
    bars, dots, glow = simulate(env, loop, hits)
    hit_times = [t for t, _ in hits]
    bar_keys = _keyframes(loop, hit_times, [ATTACK])
    dot_keys = _keyframes(loop, hit_times, [ATTACK, ATTACK + PEAK_HOLD])
    bar_kt = ";".join(_num(t / loop, 3) for t in bar_keys)
    dot_kt = ";".join(_num(t / loop, 3) for t in dot_keys)
    # Attack segments are linear; release segments ease out like an exponential decay.
    bar_splines = ";".join("0 0 1 1" if _on_hit(t, hit_times) else RELEASE_SPLINE for t in bar_keys[:-1])
    bar_idx = [round(t / SIM_DT) for t in bar_keys]
    dot_idx = [round(t / SIM_DT) for t in dot_keys]
    anim = f'dur="{_num(loop, 3)}s" repeatCount="indefinite"'

    # Mirror only the bars; a sparse row of top-side dots keeps the meter legible.
    cap = BAR_W / 2
    parts.append(f'<g fill="url(#aurora)" stroke="url(#aurora)" stroke-width="{BAR_W}" stroke-linecap="round" opacity="0.9">')
    for i in range(BARS):
        cx = 40 + i * step + cap
        tips = [_num(cy - h / 2 + cap, 0) for h in bars[bar_idx, i]]
        parts.append(
            f'<g id="b{i}"><line x1="{cx:.1f}" y1="{cy:g}" x2="{cx:.1f}" y2="{tips[0]}">'
            f'<animate attributeName="y2" values="{";".join(tips)}" keyTimes="{bar_kt}" calcMode="spline" keySplines="{bar_splines}" {anim}/>'
            "</line></g>"
            f'<use href="#b{i}" transform="matrix(1 0 0 -1 0 {HEIGHT})"/>'
        )
        if i % DOT_EVERY == 0:
            tops = [_num(cy - d / 2 - PEAK_GAP, 0) for d in dots[dot_idx, i]]
            alphas = [_num(a, 1) for a in glow[dot_idx, i]]
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{tops[0]}" r="{PEAK_R}" fill="url(#aurora)" opacity="{alphas[0]}">'
                f'<animate attributeName="cy" values="{";".join(tops)}" keyTimes="{dot_kt}" {anim}/>'
                f'<animate attributeName="opacity" values="{";".join(alphas)}" keyTimes="{dot_kt}" {anim}/>'
                "</circle>"
            )
    parts.append("</g>")
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="url(#fade)"/>')
    # Soft backing so the name and taglines stay legible over the bars.
    parts.append(f'<rect x="{WIDTH / 2 - 330}" y="{cy - 64}" width="660" height="134" rx="40" fill="{theme.bg}" opacity="0.72" filter="url(#blur)"/>')
    # Name + rotating taglines
    parts.append(text(WIDTH / 2, cy - 6, NAME, theme.text, 48, anchor="middle", weight="500",
                      extra='letter-spacing="3"',
                      font_family="'Name Rounded', ui-rounded, 'SF Pro Rounded', 'Avenir Next', sans-serif"))
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
    parts.append("</svg>")
    return "".join(parts)


def render_all() -> list[Path]:
    env = load_envelope()
    return write_pair(OUT_STEM, lambda t: render(env, t))


if __name__ == "__main__":
    for p in render_all():
        print(f"wrote {p.relative_to(ASSETS.parent)} ({p.stat().st_size // 1024} KB)")
