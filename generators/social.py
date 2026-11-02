"""Render the README's Nord social buttons: python generators/social.py."""

from __future__ import annotations

from nord import ASSETS, NORD0, NORD8, NORD9, NORD13, NORD15, Theme, esc, text, write_pair

BUTTONS = (
    ("website", "themunchkinalgorithm.world", 280, NORD15),
    ("linkedin", "LinkedIn", 132, NORD9),
    ("huggingface", "Hugging Face", 164, NORD13),
    ("bandcamp", "Bandcamp", 140, NORD8),
)

ICONS = {
    "website": (
        '<path d="M4 11a8 8 0 0 1 16 0Z"/>'
        '<path d="M7 14c-3 3 3 3 0 6m5-6c-3 3 3 3 0 7m5-7c-3 3 3 3 0 6"/>'
    ),
    "linkedin": (
        '<circle cx="6" cy="5" r="1" fill="currentColor" stroke="none"/>'
        '<path d="M6 10v9m5 0v-9m0 4a4 4 0 0 1 8 0v5"/>'
    ),
    "huggingface": (
        '<circle cx="12" cy="10" r="7"/>'
        '<path d="M9 8h.01M15 8h.01M9 11q3 4 6 0M3 14l3 5 4 1m11-6-3 5-4 1"/>'
    ),
    "bandcamp": (
        '<path d="M4 13v-2a8 8 0 0 1 16 0v2"/>'
        '<rect x="3" y="12" width="4" height="8" rx="2"/>'
        '<rect x="17" y="12" width="4" height="8" rx="2"/>'
    ),
}


def render(key: str, label: str, width: int, accent: str, theme: Theme) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="44" '
        f'viewBox="0 0 {width} 44" role="img" aria-label="{esc(label)}">'
        f"<title>{esc(label)}</title>"
        f'<rect x="1" y="1" width="{width - 2}" height="42" rx="12" '
        f'fill="{theme.bg}" stroke="{accent}"/>'
        f'<rect x="9" y="9" width="26" height="26" rx="8" fill="{accent}"/>'
        f'<g transform="translate(12 12) scale(.833333)" fill="none" '
        f'color="{NORD0}" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[key]}</g>'
        + text(47, 27, label, theme.text, 13, weight="500")
        + "</svg>"
    )


def render_all() -> None:
    for key, label, width, accent in BUTTONS:
        for path in write_pair(
            ASSETS / "social" / key,
            lambda theme: render(key, label, width, accent, theme),
        ):
            print(f"wrote {path.relative_to(ASSETS.parent)}")


if __name__ == "__main__":
    render_all()
