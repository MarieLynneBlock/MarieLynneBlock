"""Render the README's Nord social buttons: python generators/social.py."""

from __future__ import annotations

from nord import ASSETS, NORD0, NORD7, NORD8, NORD9, NORD11, NORD12, NORD13, NORD14, NORD15, Theme, esc, text, write_pair

# Bump an asset key and its README paths when its artwork changes to avoid stale caches.
BUTTONS = (
    ("website-v2", "website", 116, NORD15),
    ("linkedin", "LinkedIn", 132, NORD9),
    ("huggingface", "Hugging Face", 164, NORD13),
    ("openprocessing-v2", "OpenProcessing", 180, NORD9),
    ("youtube", "YouTube", 124, NORD11),
    ("bandcamp", "Bandcamp", 140, NORD8),
    ("soundcloud", "SoundCloud", 148, NORD12),
    ("vibe-personal", "VI.BE / Personal", 180, NORD14),
    ("vibe-project", "VI.BE / The Munchkin Algorithm", 310, NORD15),
    ("instagram", "Instagram / Munchkin", 228, NORD15),
    ("instagram-photography-v2", "Instagram / Photography", 250, NORD7),
)

VIBE_ICON = '<path d="M14 4v11.2a3.2 3.2 0 1 1-2-3V7l8-2v8.2a3.2 3.2 0 1 1-2-3V4"/>'

INSTAGRAM_ICON = (
    '<rect x="4" y="4" width="16" height="16" rx="5"/>'
    '<circle cx="12" cy="12" r="3.5"/>'
    '<circle cx="17" cy="7" r="1" fill="currentColor" stroke="none"/>'
)

ICONS = {
    "website-v2": (
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
    "vibe-personal": VIBE_ICON,
    "vibe-project": VIBE_ICON,
    "soundcloud": (
        '<path d="M3 13v3m3-5v7m3-9v9m3-11v11"/>'
        '<path d="M12 9a4 4 0 0 1 7 3h.5a3 3 0 0 1 0 6H12"/>'
    ),
    "youtube": (
        '<rect x="3" y="6" width="18" height="12" rx="4"/>'
        '<path d="M10 9l5 3-5 3z"/>'
    ),
    "instagram": INSTAGRAM_ICON,
    "instagram-photography-v2": INSTAGRAM_ICON,
    "openprocessing-v2": '<path d="M9 7 4 12l5 5m6-10 5 5-5 5M13 5l-2 14"/>',
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
