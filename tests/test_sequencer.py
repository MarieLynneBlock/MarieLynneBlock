import unittest
from unittest.mock import patch

from generators import playground

sequencer = playground.sequencer


def blank_state() -> dict:
    return {
        "bpm": 120,
        "steps": [{"pitch": None, "author": None} for _ in range(sequencer.STEPS)],
        "cursor": 0,
        "composers": [],
        "notes_added": 0,
        "actions": {},
    }


class ParseRequestTests(unittest.TestCase):
    def test_single_note_goes_to_the_cursor(self):
        self.assertEqual(sequencer.parse_request("g4"), [(None, "G4")])

    def test_step_can_be_chosen(self):
        self.assertEqual(sequencer.parse_request("7=G4"), [(6, "G4")])
        self.assertEqual(sequencer.parse_request("16 = rest"), [(15, None)])

    def test_phrase_mixes_cursor_and_chosen_steps(self):
        self.assertEqual(
            sequencer.parse_request("C4, Eb4 rest 9=Bb5"),
            [(None, "C4"), (None, "Eb4"), (None, None), (8, "Bb5")],
        )

    def test_rejects_unknown_pitch_step_and_empty_request(self):
        for raw, message in (("H4", "not in the scale"), ("17=C4", "not a step"),
                             ("0=C4", "not a step"), ("x=C4", "not a step"), ("  ", "empty")):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, message):
                sequencer.parse_request(raw)


class ApplyVerbTests(unittest.TestCase):
    def test_single_note_advances_the_cursor(self):
        state = blank_state()
        self.assertEqual(sequencer.apply_verb(state, "G4", "visitor"), "placed G4 on step 1")
        self.assertEqual(state["steps"][0], {"pitch": "G4", "author": "visitor"})
        self.assertEqual(state["cursor"], 1)
        self.assertEqual(state["last_action"], {"verb": "G4", "actor": "visitor", "step": 0})

    def test_chosen_step_leaves_the_cursor_alone(self):
        state = blank_state()
        self.assertEqual(sequencer.apply_verb(state, "7=rest", "visitor"), "placed a rest on step 7")
        self.assertEqual(state["steps"][6]["author"], "visitor")
        self.assertEqual(state["cursor"], 0)

    def test_phrase_places_every_note(self):
        state = blank_state()
        state["cursor"] = 15
        message = sequencer.apply_verb(state, "C4 Eb4 5=G5", "visitor")
        self.assertEqual(message, "placed 3 notes on steps 1, 5, 16")
        self.assertEqual([state["steps"][i]["pitch"] for i in (15, 0, 4)], ["C4", "Eb4", "G5"])
        self.assertEqual(state["cursor"], 1)
        self.assertEqual(state["notes_added"], 3)
        self.assertEqual(state["actions"], {"C4": 1, "Eb4": 1, "G5": 1})
        self.assertEqual(state["last_action"]["count"], 3)
        self.assertEqual(state["composers"], ["visitor"])

    def test_invalid_phrase_changes_nothing(self):
        state = blank_state()
        with self.assertRaises(ValueError):
            sequencer.apply_verb(state, "C4 H4", "visitor")
        self.assertEqual(state, blank_state())


class PlaygroundRequestTests(unittest.TestCase):
    def run_request(self, title: str, actor: str) -> tuple[str, dict]:
        state = blank_state()
        with (
            patch.object(playground.sequencer, "load_state", return_value=state),
            patch.object(playground, "check_rate_limit"),
            patch.object(playground, "render_everything"),
        ):
            return playground.run(title, actor, 7, 1000), state

    def test_phrase_is_applied(self):
        comment, state = self.run_request("sequencer: 3=C4 9=rest", "visitor")
        self.assertIn("placed 2 notes on steps 3, 9", comment)
        self.assertEqual(state["steps"][2]["pitch"], "C4")

    def test_visitors_cannot_rewrite_the_whole_pattern(self):
        phrase = " ".join(["C4"] * (playground.MAX_PLACEMENTS + 1))
        with self.assertRaisesRegex(playground.Refusal, "more than"):
            self.run_request(f"sequencer: {phrase}", "visitor")
        _, state = self.run_request(f"sequencer: {phrase}", playground.OWNER)
        self.assertEqual(state["notes_added"], playground.MAX_PLACEMENTS + 1)

    def test_latest_line_describes_a_phrase(self):
        state = blank_state()
        sequencer.apply_verb(state, "3=C4 9=G4", "visitor")
        with (
            patch.object(playground.forest, "load_history", return_value={}),
            patch.object(playground.forest, "summary", return_value="tree"),
            patch.object(playground, "update_readme_marker") as marker,
        ):
            playground.refresh_readme(state)
        self.assertIn("@visitor placed 2 notes on steps 3, 9", marker.call_args_list[-1].args[1])


if __name__ == "__main__":
    unittest.main()
