"""Render the curated toolbox (toolbox.yaml) into one Nord SVG per theme.

Icons are inlined from the simple-icons dataset (CC0) so the README makes a
single request instead of ~250 shields.io badge requests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from simpleicons.all import icons

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nord import ASSETS, Theme, esc, svg_open, text, write_pair  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "toolbox.yaml"
OUT_STEM = ASSETS / "toolbox" / "toolbox"

WIDTH = 900
PAD = 28
CHIP_H = 30
CHIP_GAP = 8
ICON = 16
CHAR_W = 7.6  # approximate monospace advance at 12px
CATEGORY_H = 24
ROW_GAP = 10


def chip_width(name: str, has_icon: bool) -> float:
    return 12 + (ICON + 8 if has_icon else 12) + len(name) * CHAR_W + 12


def layout(config: list[dict]) -> tuple[list[dict], int]:
    """Place chips in rows per category; return positioned items and total height."""
    y = PAD
    placed = []
    for cat in config:
        placed.append({"kind": "category", "label": cat["category"], "colour": cat["colour"], "x": PAD, "y": y + 16})
        y += CATEGORY_H + 6
        x = PAD
        for item in cat["items"]:
            icon = icons.get(item.get("icon", "")) if item.get("icon") else None
            w = chip_width(item["name"], icon is not None)
            if x + w > WIDTH - PAD:
                x = PAD
                y += CHIP_H + CHIP_GAP
            placed.append({"kind": "chip", "name": item["name"], "icon": icon, "colour": cat["colour"], "x": x, "y": y, "w": w})
            x += w + CHIP_GAP
        y += CHIP_H + ROW_GAP + 8
    return placed, int(y + PAD - 8)


def render(placed: list[dict], height: int, theme: Theme) -> str:
    parts = [svg_open(WIDTH, height, theme, "Toolbox — curated tools, languages and instruments")]
    parts.append(
        "<style>"
        "@keyframes rise{from{transform:translateY(8px)}to{transform:translateY(0)}}"
        ".c{animation:rise .5s ease-out both}"
        "</style>"
    )
    index = 0
    for p in placed:
        if p["kind"] == "category":
            parts.append(f'<rect x="{p["x"]}" y="{p["y"] - 12}" width="4" height="16" rx="2" fill="{p["colour"]}"/>')
            parts.append(text(p["x"] + 12, p["y"], p["label"], theme.text, 13, weight="bold"))
            continue
        index += 1
        delay = min(index * 0.02, 1.6)
        x, y, w = p["x"], p["y"], p["w"]
        parts.append(f'<g class="c" style="animation-delay:{delay:.2f}s">')
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{CHIP_H}" rx="7" fill="{theme.panel}" stroke="{p["colour"]}" stroke-opacity="0.35"/>')
        tx = x + 12
        if p["icon"] is not None:
            scale = ICON / 24
            parts.append(
                f'<path transform="translate({tx:.1f} {y + (CHIP_H - ICON) / 2:.1f}) scale({scale:.4f})" '
                f'd="{p["icon"].path}" fill="{p["colour"]}"/>'
            )
            tx += ICON + 8
        else:
            parts.append(f'<circle cx="{tx + 3:.1f}" cy="{y + CHIP_H / 2:.1f}" r="3" fill="{p["colour"]}"/>')
            tx += 0  # text chips keep the same left padding, dot is decorative
        parts.append(text(tx + (0 if p["icon"] is not None else 12), y + CHIP_H / 2 + 4.2, p["name"], theme.text, 12))
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def render_all() -> list[Path]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    placed, height = layout(config)
    return write_pair(OUT_STEM, lambda t: render(placed, height, t))


if __name__ == "__main__":
    for p in render_all():
        print(f"wrote {p.relative_to(ASSETS.parent)} ({p.stat().st_size // 1024} KB)")
