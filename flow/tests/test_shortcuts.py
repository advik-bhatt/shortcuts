"""Unit tests for the shortcuts block engine — matching, execution, storage."""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path

from flow.shortcuts import (
    MatchResult,
    Plan,
    RunContext,
    Shortcut,
    ShortcutStore,
    Trigger,
    command_shaped,
    execute,
    expand_inline,
    find_command_match,
    find_inline_matches,
    normalize_words,
    validate,
)

WED_9AM = datetime.datetime(2026, 8, 5, 9, 30)  # a Wednesday morning


def make(name, phrases, blocks, **kw):
    return Shortcut.from_dict(
        {"name": name, "trigger": {"phrases": phrases}, "blocks": blocks, **kw}
    )


class TestNormalize(unittest.TestCase):
    def test_fillers_and_punctuation_drop(self):
        self.assertEqual(
            normalize_words("Um, please Email Sam — about the launch!"),
            ["email", "sam", "about", "the", "launch"],
        )

    def test_apostrophes_survive(self):
        self.assertEqual(normalize_words("don't stop"), ["don't", "stop"])


class TestTriggerMatching(unittest.TestCase):
    def test_exact_command_match(self):
        t = Trigger.compile("insert my address")
        self.assertEqual(t.match_command("insert my address"), {})
        self.assertEqual(t.match_command("Um, insert my address please"), {})

    def test_whole_utterance_only(self):
        t = Trigger.compile("insert my address")
        self.assertIsNone(t.match_command("I should insert my address here"))
        self.assertIsNone(t.match_command("insert my address and then some"))

    def test_slots_split_on_literals(self):
        t = Trigger.compile("email <person> about <topic>")
        hit = t.match_command("email Sam about the launch timeline")
        self.assertEqual(hit, {"person": "sam", "topic": "the launch timeline"})

    def test_multiword_early_slot(self):
        t = Trigger.compile("email <person> about <topic>")
        hit = t.match_command("email Priya Sharma about the offsite")
        self.assertEqual(hit["person"], "priya sharma")
        self.assertEqual(hit["topic"], "the offsite")

    def test_optional_words(self):
        t = Trigger.compile("open (the) calendar")
        self.assertEqual(t.match_command("open the calendar"), {})
        self.assertEqual(t.match_command("open calendar"), {})
        self.assertIsNone(t.match_command("open the calendar app"))

    def test_optional_at_end(self):
        t = Trigger.compile("start focus mode (now)")
        self.assertEqual(t.match_command("start focus mode"), {})
        self.assertEqual(t.match_command("start focus mode now"), {})

    def test_slot_only_trigger_rejected(self):
        problems = validate(
            {"name": "bad", "trigger": {"phrases": ["<anything>"]}, "blocks": [{"type": "text", "value": "x"}]}
        )
        self.assertTrue(any("literal word" in p for p in problems))

    def test_duplicate_slot_rejected(self):
        problems = validate(
            {"name": "bad", "trigger": {"phrases": ["send <x> to <x>"]}, "blocks": [{"type": "text", "value": "x"}]}
        )
        self.assertTrue(problems)

    def test_inline_matches_inside_sentence_with_span(self):
        t = Trigger.compile("insert my address")
        got = t.match_inline("Ship it to insert my address, thanks")
        self.assertIsNotNone(got)
        slots, span = got
        self.assertEqual(slots, {})
        self.assertEqual("Ship it to insert my address, thanks"[span[0]:span[1]], "insert my address")

    def test_inline_never_matches_inside_words(self):
        t = Trigger.compile("cc <person>")
        self.assertIsNone(t.match_inline("the accident occurred"))

    def test_inline_slot_is_lazy(self):
        t = Trigger.compile("cc <person>")
        slots, span = t.match_inline("also cc Rohan and then deploy")
        self.assertEqual(slots["person"], "Rohan")

    def test_inline_case_and_punctuation_tolerant(self):
        t = Trigger.compile("my signature")
        self.assertIsNotNone(t.match_inline("...and add My Signature."))


class TestCommandRouting(unittest.TestCase):
    def setUp(self):
        self.shortcuts = [
            make("email", ["email <person>"], [{"type": "text", "value": "hi"}]),
            make(
                "email-topic",
                ["email <person> about <topic>"],
                [{"type": "text", "value": "hi topic"}],
            ),
            make("addr", ["insert my address"], [{"type": "text", "value": "12 Elm St"}], inline=True),
        ]

    def test_most_specific_wins(self):
        m = find_command_match("email Sam about the launch", self.shortcuts)
        self.assertEqual(m.shortcut.name, "email-topic")

    def test_less_specific_still_fires(self):
        m = find_command_match("email Sam", self.shortcuts)
        self.assertEqual(m.shortcut.name, "email")

    def test_dictation_does_not_fire(self):
        self.assertIsNone(
            find_command_match("I need to email Sam about the launch tomorrow morning", self.shortcuts)
        )

    def test_inline_shortcut_excluded_from_commands(self):
        # "insert my address" is inline-only; as a whole utterance it must
        # still expand via the inline path, not the command path
        self.assertIsNone(find_command_match("insert my address", self.shortcuts))

    def test_disabled_never_fires(self):
        off = [make("email", ["email <person>"], [{"type": "text", "value": "x"}], enabled=False)]
        self.assertIsNone(find_command_match("email Sam", off))


class TestInlineExpansion(unittest.TestCase):
    def test_expand_in_place(self):
        scs = [make("addr", ["insert my address"], [{"type": "text", "value": "12 Elm St, Jersey City"}], inline=True)]
        out, actions, _ = expand_inline(
            "Ship it to insert my address, thanks", scs, RunContext()
        )
        self.assertEqual(out, "Ship it to 12 Elm St, Jersey City, thanks")
        self.assertEqual(actions, [])

    def test_no_match_returns_input(self):
        scs = [make("addr", ["insert my address"], [{"type": "text", "value": "x"}], inline=True)]
        raw = "nothing to expand here"
        self.assertEqual(expand_inline(raw, scs, RunContext()), (raw, [], []))

    def test_slotted_inline(self):
        scs = [
            make(
                "cal",
                ["my calendar link for <person>"],
                [{"type": "text", "value": "cal.com/advik?for="}, {"type": "slot", "name": "person"}],
                inline=True,
            )
        ]
        out, _, _ = expand_inline("send my calendar link for Rohan today", scs, RunContext())
        self.assertEqual(out, "send cal.com/advik?for=Rohan today")

    def test_multiple_non_overlapping(self):
        scs = [
            make("a", ["insert my address"], [{"type": "text", "value": "ADDR"}], inline=True),
            make("s", ["my signature"], [{"type": "text", "value": "SIG"}], inline=True),
        ]
        out, _, _ = expand_inline("insert my address and my signature", scs, RunContext())
        self.assertEqual(out, "ADDR and SIG")


class TestExecution(unittest.TestCase):
    def test_text_slot_date_compose(self):
        sc = make(
            "standup",
            ["standup note"],
            [
                {"type": "text", "value": "Standup "},
                {"type": "date", "format": "iso"},
                {"type": "text", "value": ": "},
                {"type": "slot", "name": "note", "fallback": "(nothing)"},
            ],
        )
        plan = execute(sc, RunContext(now=WED_9AM, slots={"note": "shipped blocks"}))
        self.assertEqual(plan.text, "Standup 2026-08-05: shipped blocks")

    def test_slot_fallback(self):
        sc = make("x", ["x marker"], [{"type": "slot", "name": "missing", "fallback": "?"}])
        self.assertEqual(execute(sc, RunContext()).text, "?")

    def test_condition_app_branches(self):
        sc = make(
            "signoff",
            ["sign off"],
            [
                {
                    "type": "if",
                    "cond": {"kind": "app", "value": "slack"},
                    "then": [{"type": "text", "value": "cheers"}],
                    "else": [{"type": "text", "value": "Best regards,\nAdvik"}],
                }
            ],
        )
        self.assertEqual(execute(sc, RunContext(app="Slack")).text, "cheers")
        self.assertEqual(execute(sc, RunContext(app="Mail")).text, "Best regards,\nAdvik")

    def test_condition_hours_and_weekday(self):
        sc = make(
            "greet",
            ["greeting line"],
            [
                {
                    "type": "if",
                    "cond": {"kind": "hour_before", "value": "12"},
                    "then": [{"type": "text", "value": "Good morning"}],
                    "else": [{"type": "text", "value": "Good evening"}],
                },
                {
                    "type": "if",
                    "cond": {"kind": "weekday", "value": "wed"},
                    "then": [{"type": "text", "value": " (midweek)"}],
                },
            ],
        )
        self.assertEqual(execute(sc, RunContext(now=WED_9AM)).text, "Good morning (midweek)")

    def test_transform_nests(self):
        sc = make(
            "shout",
            ["shout <thing>"],
            [{"type": "transform", "op": "upper", "children": [{"type": "slot", "name": "thing"}]}],
        )
        self.assertEqual(execute(sc, RunContext(slots={"thing": "ship it"})).text, "SHIP IT")

    def test_actions_collect_with_template_fill(self):
        sc = make(
            "meet",
            ["meeting with <person>"],
            [
                {"type": "open_url", "url": "https://cal.com/advik?invite={person}"},
                {"type": "pause", "seconds": 0.5},
                {"type": "keys", "combo": "cmd+enter"},
            ],
        )
        plan = execute(sc, RunContext(slots={"person": "rohan"}))
        self.assertEqual(plan.text, "")
        self.assertEqual(plan.actions[0], {"type": "open_url", "url": "https://cal.com/advik?invite=rohan"})
        self.assertEqual(plan.actions[1], {"type": "pause", "seconds": 0.5})
        self.assertEqual(plan.actions[2], {"type": "keys", "combo": "cmd+enter"})

    def test_clipboard_and_last_dictation(self):
        sc = make(
            "wrap",
            ["quote clipboard"],
            [{"type": "text", "value": "> "}, {"type": "clipboard"}],
        )
        plan = execute(sc, RunContext(clipboard="pasted words"))
        self.assertEqual(plan.text, "> pasted words")

    def test_describe_is_readable(self):
        sc = make("m", ["m marker"], [{"type": "text", "value": "hello"}, {"type": "open_app", "app": "Obsidian"}])
        d = execute(sc, RunContext()).describe()
        self.assertIn("type 'hello'", d)
        self.assertIn("launch Obsidian", d)


class TestValidation(unittest.TestCase):
    def test_valid_passes(self):
        self.assertEqual(
            validate(
                {
                    "name": "ok",
                    "trigger": {"phrases": ["do the thing"]},
                    "blocks": [{"type": "text", "value": "x"}],
                }
            ),
            [],
        )

    def test_problems_reported(self):
        problems = validate(
            {
                "name": "",
                "trigger": {"phrases": []},
                "blocks": [{"type": "nope"}],
            }
        )
        self.assertEqual(len(problems), 3)

    def test_nested_validation(self):
        problems = validate(
            {
                "name": "x",
                "trigger": {"phrases": ["x marker"]},
                "blocks": [
                    {
                        "type": "if",
                        "cond": {"kind": "app", "value": "Slack"},
                        "then": [{"type": "shell"}],  # missing cmd
                    }
                ],
            }
        )
        self.assertTrue(any("shell" in p for p in problems))


class TestStore(unittest.TestCase):
    def test_save_load_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = ShortcutStore(Path(d))
            path = store.save(
                {
                    "name": "Sign off",
                    "trigger": {"phrases": ["sign off"]},
                    "blocks": [{"type": "text", "value": "Best,\nAdvik"}],
                }
            )
            self.assertEqual(path.name, "sign-off.json")
            loaded, problems = store.load_all()
            self.assertEqual(problems, [])
            self.assertEqual(loaded[0].name, "Sign off")
            self.assertEqual(loaded[0].to_dict()["trigger"]["phrases"], ["sign off"])
            self.assertTrue(store.delete("Sign off"))
            self.assertEqual(store.load_all()[0], [])

    def test_broken_file_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bad.json").write_text("{not json", encoding="utf-8")
            store = ShortcutStore(Path(d))
            loaded, problems = store.load_all()
            self.assertEqual(loaded, [])
            self.assertEqual(len(problems), 1)

    def test_save_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ShortcutStore(Path(d)).save({"name": "x", "trigger": {"phrases": []}, "blocks": []})


class TestCommandShaped(unittest.TestCase):
    def test_short_is_command_shaped(self):
        self.assertTrue(command_shaped("email Sam about the launch"))

    def test_long_dictation_is_not(self):
        long = "so I was thinking about the launch and honestly we should move it to " \
               "Thursday because the deck is not ready and Sam is out on Wednesday"
        self.assertFalse(command_shaped(long))

    def test_empty_is_not(self):
        self.assertFalse(command_shaped("   "))


if __name__ == "__main__":
    unittest.main()
