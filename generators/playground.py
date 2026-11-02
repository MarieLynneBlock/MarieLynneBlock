"""Entry point for the playground workflow.

Reads a sequencer issue request, re-renders the dependent assets, updates the
README credit markers and writes the comment the workflow posts back on the issue.

Usage:
    python generators/playground.py --event "$GITHUB_EVENT_PATH"
    python generators/playground.py --title "sequencer: G4" --actor someone --number 12
    python generators/playground.py --render-only      # rebuild assets from cached state
    python generators/playground.py --refresh-history --render-only  # nightly history sync
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "garden"))
sys.path.insert(0, str(HERE / "sequencer"))
sys.path.insert(0, str(HERE / "waveform"))

import sequencer  # noqa: E402
import waveform  # noqa: E402
from generators.garden import forest  # noqa: E402
from nord import REPO_ROOT  # noqa: E402

README = REPO_ROOT / "README.md"
OWNER = "MarieLynneBlock"
RATE_LIMIT = 10           # actions per user per 24 h
RATE_WINDOW = 24 * 3600
RATE_FILE = HERE / "ratelimit.json"

TITLE_RE = re.compile(r"^\s*sequencer\s*:\s*(.+?)\s*$", re.IGNORECASE)


class Refusal(Exception):
    """Raised when the request is valid syntax but not allowed."""


def parse_title(title: str) -> tuple[str, str]:
    m = TITLE_RE.match(title or "")
    if not m:
        raise ValueError(
            "I could not read that title. Use a sequencer button in the README — "
            "titles look like `sequencer: G4`."
        )
    return "sequencer", m.group(1)


def check_rate_limit(actor: str, now: float) -> None:
    data = json.loads(RATE_FILE.read_text()) if RATE_FILE.exists() else {}
    recent = [t for t in data.get(actor, []) if now - t < RATE_WINDOW]
    if len(recent) >= RATE_LIMIT and actor != OWNER:
        raise Refusal(
            f"@{actor} has already made {RATE_LIMIT} changes in the last 24 hours — "
            "thank you for the enthusiasm! Come back tomorrow and add another note. 🌙"
        )
    recent.append(now)
    data[actor] = recent
    # Drop stale users so the file never grows unbounded.
    data = {k: [t for t in v if now - t < RATE_WINDOW] for k, v in data.items()}
    data = {k: v for k, v in data.items() if v}
    RATE_FILE.write_text(json.dumps(data, indent=0, sort_keys=True) + "\n")


def update_readme_marker(marker: str, content: str) -> None:
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(rf"(<!-- {marker}:START -->)(.*?)(<!-- {marker}:END -->)", re.DOTALL)
    if not pattern.search(text):
        return
    README.write_text(pattern.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text), encoding="utf-8")


def handles(names: list[str]) -> str:
    return " · ".join(f'<a href="https://github.com/{n}">@{n}</a>' for n in names) if names else "<em>nobody yet — be the first!</em>"


def refresh_readme(seq_state: dict) -> None:
    g_credit = (
        f"<strong>{forest.summary(forest.load_history())}</strong><br>"
        "<sub>Grown from public commit history · refreshed nightly</sub>"
    )
    update_readme_marker("GARDEN:CREDITS", g_credit)
    s_last = seq_state.get("last_action", {})
    filled = sum(1 for s in seq_state["steps"] if s["pitch"])
    s_credit = (
        f"<strong>{filled}/{sequencer.STEPS} steps filled</strong> · next free step: {seq_state['cursor'] % sequencer.STEPS + 1} · "
        f"{seq_state.get('notes_added', 0)} notes placed by visitors<br><sub>recent composers: {handles(seq_state.get('composers', []))}</sub>"
    )
    if s_last.get("actor"):
        if s_last.get("verb") == "clear":
            s_credit += f"<br><sub>latest: @{s_last['actor']} cleared the sequence — a blank canvas!</sub>"
        else:
            s_credit += f"<br><sub>latest: @{s_last['actor']} placed {s_last['verb']} on step {s_last.get('step', 0) + 1}</sub>"
    update_readme_marker("SEQUENCER:CREDITS", s_credit)


def render_everything(seq_state: dict) -> None:
    forest.render_all()
    sequencer.render_all(seq_state)
    sequencer.save_state(seq_state)
    waveform.render_all()
    refresh_readme(seq_state)


def run(title: str, actor: str, number: int | None, now: float) -> str:
    seq_state = sequencer.load_state()
    _, verb = parse_title(title)
    verb_l = verb.lower()

    if verb_l == "clear":
        if actor != OWNER:
            raise Refusal("Only the owner can clear the sequence — but you can overwrite steps one note at a time. 🎹")
    elif verb_l != sequencer.REST and sequencer.normalise_pitch(verb) is None:
        raise ValueError(f"`{verb}` is not in the scale. Pick one of {', '.join(sequencer.PITCHES)} or `rest`.")
    check_rate_limit(actor, now)
    message = sequencer.apply_verb(seq_state, verb if verb_l != "clear" else "clear", actor)
    render_everything(seq_state)
    stamp = number or int(now)
    return (
        f"🎛️ Thank you, @{actor}! You {message}.\n\n"
        f"![sequencer](https://raw.githubusercontent.com/{OWNER}/{OWNER}/master/assets/sequencer/sequencer-dark.svg?v={stamp})\n\n"
        f"▶ [Listen to the new loop](https://github.com/{OWNER}/{OWNER}/blob/master/assets/sequencer/sequence.wav) · "
        f"⬇ [MIDI](https://github.com/{OWNER}/{OWNER}/raw/master/assets/sequencer/sequence.mid)\n\n"
        "_The header waveform at the top of the README is rendered from this very audio, so you just changed that too. "
        "Closing this issue — it did its job._"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event")
    ap.add_argument("--title")
    ap.add_argument("--actor", default="local")
    ap.add_argument("--number", type=int)
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--refresh-history", action="store_true")
    ap.add_argument("--out", default=os.environ.get("PLAYGROUND_COMMENT_FILE", "comment.md"))
    args = ap.parse_args()

    now = time.time()
    if args.refresh_history:
        forest.refresh_history()
    if args.render_only:
        render_everything(sequencer.load_state())
        gh_out = os.environ.get("GITHUB_OUTPUT")
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as f:
                f.write("status=ok\n")
        print("rendered everything from state")
        return 0
    if args.event:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        issue = event["issue"]
        title, actor, number = issue["title"], issue["user"]["login"], issue["number"]
    else:
        title, actor, number = args.title or "", args.actor, args.number

    status = "ok"
    try:
        comment = run(title, actor, number, now)
    except Refusal as e:
        status, comment = "refused", f"🙈 {e}\n\n_Closing this issue without changes._"
    except ValueError as e:
        status, comment = "invalid", f"🤔 {e}\n\n_Closing this issue without changes._"

    Path(args.out).write_text(comment, encoding="utf-8")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
    print(f"[{status}] {title!r} by {actor}")
    print(comment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
