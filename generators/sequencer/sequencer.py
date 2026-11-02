"""Visitor step-sequencer.

16 steps, C-minor pentatonic across two octaves, one note per step, 120 BPM.
Visitors append a note (or a rest) via the playground workflow; this module
renders an animated piano-roll SVG plus a WAV and a MIDI file.
"""

from __future__ import annotations

import json
import struct
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nord import (  # noqa: E402
    ASSETS, AURORA, NORD3, NORD4, NORD7, NORD8, NORD9, NORD10, NORD11, NORD12, NORD13, NORD14,
    NORD15, Theme, svg_open, text, write_pair,
)

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE / "state.json"
OUT_DIR = ASSETS / "sequencer"
OUT_STEM = OUT_DIR / "sequencer"
WAV_PATH = OUT_DIR / "sequence.wav"
MID_PATH = OUT_DIR / "sequence.mid"

STEPS = 16
BPM = 120
SAMPLE_RATE = 22_050
LOOPS = 2  # WAV repeats the 16-step pattern this many times

# C minor pentatonic: C Eb F G Bb — two octaves, low to high.
PITCHES = ["C4", "Eb4", "F4", "G4", "Bb4", "C5", "Eb5", "F5", "G5", "Bb5"]
MIDI_NOTES = {"C4": 60, "Eb4": 63, "F4": 65, "G4": 67, "Bb4": 70,
              "C5": 72, "Eb5": 75, "F5": 77, "G5": 79, "Bb5": 82}
PITCH_COLOURS = [NORD14, NORD7, NORD8, NORD9, NORD10, NORD15, NORD11, NORD12, NORD13, NORD14]
REST = "rest"

WIDTH, HEIGHT = 900, 420
GRID_X, GRID_Y = 70, 52
CELL_W, CELL_H = 46, 26
GAP = 4


# ----------------------------------------------------------------------------- state

def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_state() -> dict:
    # A gentle starter phrase so the page is never silent.
    starter = ["C4", "Eb4", "G4", None, "Bb4", "G4", "F4", None,
               "C5", None, "G4", "Eb4", "F4", None, "Eb4", "C4"]
    return {
        "bpm": BPM,
        "steps": [{"pitch": p, "author": "MarieLynneBlock"} if p else {"pitch": None, "author": None} for p in starter],
        "cursor": 0,
        "composers": ["MarieLynneBlock"],
        "notes_added": 0,
        "actions": {},
    }


def apply_verb(state: dict, verb: str, actor: str) -> str:
    verb = verb.strip()
    if verb == "clear":
        state["steps"] = [{"pitch": None, "author": None} for _ in range(STEPS)]
        state["cursor"] = 0
        state["last_action"] = {"verb": "clear", "actor": actor}
        return "cleared the sequence"
    if verb == REST:
        pitch = None
    else:
        pitch = normalise_pitch(verb)
        if pitch is None:
            raise ValueError(f"unknown pitch: {verb}")
    i = state["cursor"] % STEPS
    state["steps"][i] = {"pitch": pitch, "author": actor}
    state["cursor"] = (i + 1) % STEPS
    state["notes_added"] = state.get("notes_added", 0) + 1
    if actor:
        composers = [c for c in state.get("composers", []) if c != actor]
        state["composers"] = ([actor] + composers)[:8]
    state.setdefault("actions", {})
    state["actions"][pitch or REST] = state["actions"].get(pitch or REST, 0) + 1
    state["last_action"] = {"verb": pitch or REST, "actor": actor, "step": i}
    return f"placed {'a rest' if pitch is None else pitch} on step {i + 1}"


def normalise_pitch(raw: str) -> str | None:
    raw = raw.strip().replace("♭", "b").replace("#", "s")
    lookup = {p.lower(): p for p in PITCHES}
    aliases = {"ds4": "Eb4", "ds5": "Eb5", "as4": "Bb4", "as5": "Bb5"}
    return lookup.get(raw.lower()) or aliases.get(raw.lower())


# ----------------------------------------------------------------------------- audio

def midi_to_hz(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def synth_note(freq: float, duration: float) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.arange(n) / SAMPLE_RATE
    tone = (np.sin(2 * np.pi * freq * t)
            + 0.35 * np.sin(2 * np.pi * 2 * freq * t)
            + 0.15 * np.sin(2 * np.pi * 3 * freq * t))
    attack, release = int(0.008 * SAMPLE_RATE), int(0.18 * SAMPLE_RATE)
    env = np.ones(n)
    env[:attack] = np.linspace(0, 1, attack)
    decay = np.exp(-np.linspace(0, 3.2, n))
    env *= decay
    env[-release:] *= np.linspace(1, 0, release)
    return tone * env * 0.55


def render_wav(state: dict) -> None:
    step_dur = 60.0 / state["bpm"] / 2  # eighth notes
    pattern_len = int(SAMPLE_RATE * step_dur * STEPS)
    out = np.zeros(pattern_len * LOOPS + SAMPLE_RATE, dtype=np.float64)
    for loop in range(LOOPS):
        for i, step in enumerate(state["steps"]):
            if not step["pitch"]:
                continue
            start = int((loop * STEPS + i) * step_dur * SAMPLE_RATE)
            note = synth_note(midi_to_hz(MIDI_NOTES[step["pitch"]]), step_dur * 1.6)
            end = min(start + len(note), len(out))
            out[start:end] += note[: end - start]
    # Tiny dotted-eighth delay for air.
    delay = int(step_dur * 1.5 * SAMPLE_RATE)
    echo = np.zeros_like(out)
    echo[delay:] = out[:-delay] * 0.28
    out = out + echo
    peak = np.max(np.abs(out)) or 1.0
    pcm = (out / peak * 0.85 * 32767).astype(np.int16)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(WAV_PATH), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def _vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def render_midi(state: dict) -> None:
    ticks_per_beat = 480
    eighth = ticks_per_beat // 2
    tempo = int(60_000_000 / state["bpm"])
    track = bytearray()
    track += _vlq(0) + b"\xff\x51\x03" + tempo.to_bytes(3, "big")
    track += _vlq(0) + b"\xff\x03" + _vlq(len(b"visitor sequence")) + b"visitor sequence"
    track += _vlq(0) + b"\xc0\x0b"  # programme 11: vibraphone
    pending = 0
    for step in state["steps"]:
        if step["pitch"]:
            note = MIDI_NOTES[step["pitch"]]
            track += _vlq(pending) + bytes([0x90, note, 96])
            track += _vlq(eighth) + bytes([0x80, note, 0])
            pending = 0
        else:
            pending += eighth
    track += _vlq(pending) + b"\xff\x2f\x00"
    data = b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks_per_beat) + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    MID_PATH.write_bytes(data)


# ----------------------------------------------------------------------------- svg

def render(state: dict, theme: Theme) -> str:
    rows = list(reversed(PITCHES))  # high pitches on top
    loop_s = 60.0 / state["bpm"] / 2 * STEPS
    composers = state.get("composers", [])
    last = state.get("last_action", {})
    title = f"Visitor step-sequencer — {STEPS} steps, C minor pentatonic, {state['bpm']} BPM"
    parts = [svg_open(WIDTH, HEIGHT, theme, title)]
    parts.append(
        "<defs>"
        '<linearGradient id="aurora" x1="0" y1="0" x2="1" y2="0">'
        + "".join(f'<stop offset="{i / (len(AURORA) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(AURORA))
        + "</linearGradient>"
        '<filter id="glow"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
    )
    grid_w = STEPS * (CELL_W + GAP) - GAP
    grid_h = len(rows) * (CELL_H + GAP) - GAP
    pulse_css = "".join(
        f".s{i}{{animation:pulse {loop_s:.2f}s linear infinite;animation-delay:{i * loop_s / STEPS:.3f}s}}"
        for i in range(STEPS)
    )
    parts.append(
        "<style>"
        f"@keyframes head{{from{{transform:translateX(0)}}to{{transform:translateX({grid_w}px)}}}}"
        f".head{{animation:head {loop_s:.2f}s steps({STEPS},end) infinite}}"
        "@keyframes pulse{0%{opacity:.78;transform:scale(1)}3%{opacity:1;transform:scale(1.12)}12%{opacity:.78;transform:scale(1)}100%{opacity:.78;transform:scale(1)}}"
        + pulse_css
        + "</style>"
    )
    # header
    parts.append(text(GRID_X, 32, "visitor sequencer", theme.text, 15, weight="bold"))
    parts.append(text(GRID_X + grid_w, 32, f"{STEPS} steps · C minor pentatonic · {state['bpm']} bpm", theme.muted, 12, anchor="end"))
    # grid
    for r, pitch in enumerate(rows):
        y = GRID_Y + r * (CELL_H + GAP)
        parts.append(text(GRID_X - 10, y + CELL_H * 0.72, pitch, theme.muted, 11, anchor="end"))
        for c in range(STEPS):
            x = GRID_X + c * (CELL_W + GAP)
            beat = c % 4 == 0
            parts.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" rx="5" fill="{theme.panel}" opacity="{0.95 if beat else 0.6}"/>')
    # notes
    for c, step in enumerate(state["steps"]):
        if not step["pitch"]:
            continue
        r = rows.index(step["pitch"])
        x = GRID_X + c * (CELL_W + GAP)
        y = GRID_Y + r * (CELL_H + GAP)
        colour = PITCH_COLOURS[PITCHES.index(step["pitch"])]
        parts.append(
            f'<rect class="s{c}" x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" rx="5" fill="{colour}" '
            f'style="transform-origin:{x + CELL_W / 2}px {y + CELL_H / 2}px" filter="url(#glow)"/>'
        )
    # playhead
    parts.append(
        f'<rect class="head" x="{GRID_X - 2}" y="{GRID_Y - 6}" width="{CELL_W + 4}" height="{grid_h + 12}" rx="7" '
        f'fill="none" stroke="url(#aurora)" stroke-width="2" opacity="0.9"/>'
    )
    # step numbers + authors
    for c, step in enumerate(state["steps"]):
        x = GRID_X + c * (CELL_W + GAP) + CELL_W / 2
        parts.append(text(x, GRID_Y + grid_h + 18, str(c + 1), theme.muted, 10, anchor="center"))
    # footer
    fy = HEIGHT - 26
    filled = sum(1 for s in state["steps"] if s["pitch"])
    parts.append(text(GRID_X, fy, f"{filled}/{STEPS} steps filled · next step {state['cursor'] % STEPS + 1} · {state.get('notes_added', 0)} notes placed so far", theme.muted, 11))
    if last.get("actor"):
        parts.append(text(GRID_X + grid_w, fy, f"last composer @{last['actor']}", theme.muted, 12, anchor="end"))
    parts.append(f'<rect x="{GRID_X}" y="{fy + 10}" width="{grid_w}" height="3" rx="1.5" fill="url(#aurora)" opacity="0.7"/>')
    parts.append("</svg>")
    return "".join(parts).replace('text-anchor="center"', 'text-anchor="middle"')


def render_all(state: dict) -> list[Path]:
    render_wav(state)
    render_midi(state)
    return write_pair(OUT_STEM, lambda t: render(state, t)) + [WAV_PATH, MID_PATH]


def main(argv: list[str]) -> None:
    if not STATE_PATH.exists():
        save_state(default_state())
    state = load_state()
    if len(argv) >= 2:
        actor = argv[2] if len(argv) > 2 else "local"
        print(apply_verb(state, argv[1], actor))
    paths = render_all(state)
    save_state(state)
    for p in paths:
        print(f"wrote {p.relative_to(ASSETS.parent)} ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv)
