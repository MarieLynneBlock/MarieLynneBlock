"""Nord palette, theme pairs and tiny SVG helpers shared by every generator."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Polar Night
NORD0, NORD1, NORD2, NORD3 = "#2E3440", "#3B4252", "#434C5E", "#4C566A"
# Snow Storm
NORD4, NORD5, NORD6 = "#D8DEE9", "#E5E9F0", "#ECEFF4"
# Frost
NORD7, NORD8, NORD9, NORD10 = "#8FBCBB", "#88C0D0", "#81A1C1", "#5E81AC"
# Aurora
NORD11, NORD12, NORD13, NORD14, NORD15 = "#BF616A", "#D08770", "#EBCB8B", "#A3BE8C", "#B48EAD"

FROST = [NORD7, NORD8, NORD9, NORD10]
AURORA = [NORD14, NORD8, NORD9, NORD15, NORD11]

FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    grid: str
    text: str
    muted: str


DARK = Theme("dark", bg=NORD0, panel=NORD1, grid=NORD2, text=NORD6, muted=NORD4)
LIGHT = Theme("light", bg=NORD6, panel=NORD5, grid=NORD4, text=NORD0, muted=NORD3)
THEMES = (DARK, LIGHT)


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def svg_open(width: int, height: int, theme: Theme, title: str, extra_attrs: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" {extra_attrs}>'
        f"<title>{esc(title)}</title>"
        f'<rect width="{width}" height="{height}" rx="12" fill="{theme.bg}"/>'
    )


def text(x: float, y: float, content: str, fill: str, size: int = 12, anchor: str = "start",
         weight: str = "normal", opacity: float = 1.0, extra: str = "",
         font_family: str = FONT) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{font_family}" font-size="{size}" '
        f'text-anchor="{anchor}" font-weight="{weight}" opacity="{opacity}" {extra}>{esc(content)}</text>'
    )


def write_pair(stem: Path, render) -> list[Path]:
    """Render `render(theme)` for both themes and write `<stem>-dark.svg` / `<stem>-light.svg`."""
    written = []
    stem.parent.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        path = stem.with_name(f"{stem.name}-{theme.name}.svg")
        path.write_text(render(theme), encoding="utf-8")
        written.append(path)
    return written


def update_readme_asset_links(
    paths: list[Path], readme_path: Path, link_pattern: re.Pattern[str], asset_name: str,
) -> None:
    versions = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:16] for path in paths}
    original = readme_path.read_text(encoding="utf-8")
    seen: set[str] = set()

    def version_link(match: re.Match[str]) -> str:
        parts = urlsplit(html.unescape(match.group()))
        name = Path(parts.path).name
        if name not in versions:
            raise RuntimeError(f"No rendered {asset_name} found for {name}")
        seen.add(name)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "v"]
        query.append(("v", versions[name]))
        return esc(urlunsplit(("", "", parts.path, urlencode(query), parts.fragment)))

    updated = link_pattern.sub(version_link, original)
    missing = set(versions) - seen
    if missing:
        raise RuntimeError(f"{readme_path} is missing {asset_name} links: {', '.join(sorted(missing))}")
    if updated != original:
        readme_path.write_text(updated, encoding="utf-8")
