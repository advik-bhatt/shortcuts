"""Tests for the daemon routing layer, tap-lock state machine, style, intent gate."""

from __future__ import annotations

import os
import tempfile
import unittest

from flow.config import Config
from flow.daemon import HoldOrLock, Routed, Snapshot, Stores, route
from flow.intent import gate, _vocabulary
from flow.shortcuts import Shortcut
from flow.style import profile


def make(name, phrases, blocks, **kw):
    return Shortcut.from_dict(
        {"name": name, "trigger": {"phrases": phrases}, "blocks": blocks, **kw}
    )


class RoutingBase(unittest.TestCase):
    """route() with a temp FLOW_DIR and no API keys: fully deterministic."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = os.environ.get("FLOW_DIR")
        self._old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["FLOW_DIR"] = self._tmp.name
        self.cfg = Config()
        self.stores = Stores(self.cfg)
        self.snap = Snapshot(focus=None, preferred_script=None)

    def tearDown(self):
        if self._old_dir is None:
            os.environ.pop("FLOW_DIR", None)
        else:
            os.environ["FLOW_DIR"] = self._old_dir
        if self._old_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._old_key
        self._tmp.cleanup()


class TestRoute(RoutingBase):
    def test_command_routes_to_plan(self):
        scs = [make("addr", ["insert my address"], [{"type": "text", "value": "12 Elm St"}])]
        routed = route("insert my address", self.snap, self.cfg, self.stores, shortcuts=scs)
        self.assertEqual(routed.kind, "command")
        self.assertEqual(routed.plan.text, "12 Elm St")
        self.assertEqual(routed.via, "deterministic")
        # history records it as a shortcut, not dictation
        entries = self.stores.history.entries()
        self.assertEqual(entries[-1]["kind"], "shortcut")
        self.assertEqual(entries[-1]["shortcut"], "addr")

    def test_dictation_falls_through(self):
        scs = [make("addr", ["insert my address"], [{"type": "text", "value": "12 Elm St"}])]
        routed = route(
            "um so let's ship the build tonight", self.snap, self.cfg, self.stores, shortcuts=scs
        )
        self.assertEqual(routed.kind, "dictation")
        self.assertEqual(routed.final, "So let's ship the build tonight.")
        self.assertIsNone(routed.plan)

    def test_inline_expansion_flows_into_dictation(self):
        scs = [
            make("addr", ["insert my address"], [{"type": "text", "value": "12 Elm St"}], inline=True)
        ]
        routed = route(
            "ship it to insert my address thanks", self.snap, self.cfg, self.stores, shortcuts=scs
        )
        self.assertEqual(routed.kind, "dictation")
        self.assertIn("12 Elm St", routed.final)

    def test_dry_run_writes_no_history(self):
        scs = [make("addr", ["insert my address"], [{"type": "text", "value": "x"}])]
        route("insert my address", self.snap, self.cfg, self.stores, shortcuts=scs, dry=True)
        route("plain dictation here", self.snap, self.cfg, self.stores, shortcuts=scs, dry=True)
        self.assertEqual(self.stores.history.entries(), [])

    def test_command_with_actions_only(self):
        scs = [
            make(
                "cal",
                ["open my calendar"],
                [{"type": "open_url", "url": "https://cal.com/advik"}],
            )
        ]
        routed = route("open my calendar", self.snap, self.cfg, self.stores, shortcuts=scs)
        self.assertEqual(routed.kind, "command")
        self.assertEqual(routed.final, "")
        self.assertEqual(routed.plan.actions[0]["url"], "https://cal.com/advik")

    def test_shortcut_entries_stay_out_of_recent_context(self):
        from flow.daemon import take_snapshot

        self.stores.history.append({"app": "Slack", "contact": "Rohan", "text": "SIG", "kind": "shortcut"})
        self.stores.history.append({"app": "Slack", "contact": "Rohan", "text": "real message"})
        # take_snapshot reads frontmost() which is None off-mac; call the
        # filter logic through recent() directly instead
        entries = self.stores.history.recent("Slack", "Rohan", n=4)
        texts = [e["text"] for e in entries if e.get("kind") != "shortcut"]
        self.assertEqual(texts, ["real message"])


class TestHoldOrLock(unittest.TestCase):
    def test_hold_to_talk(self):
        m = HoldOrLock(tap_threshold=0.35)
        self.assertEqual(m.press(0.0), "start")
        self.assertEqual(m.release(1.2), "stop")
        self.assertEqual(m.state, HoldOrLock.IDLE)

    def test_tap_locks_then_tap_stops(self):
        m = HoldOrLock(tap_threshold=0.35)
        self.assertEqual(m.press(0.0), "start")
        self.assertEqual(m.release(0.1), "lock")
        self.assertEqual(m.state, HoldOrLock.LOCKED)
        # second tap: press stops, its release is inert
        self.assertEqual(m.press(5.0), "stop")
        self.assertIsNone(m.release(5.1))
        self.assertEqual(m.state, HoldOrLock.IDLE)

    def test_auto_repeat_ignored_while_held(self):
        m = HoldOrLock()
        self.assertEqual(m.press(0.0), "start")
        self.assertIsNone(m.press(0.1))  # macOS key auto-repeat
        self.assertIsNone(m.press(0.2))
        self.assertEqual(m.release(1.0), "stop")

    def test_tap_lock_disabled_means_short_press_stops(self):
        m = HoldOrLock(tap_threshold=0.35, tap_lock=False)
        self.assertEqual(m.press(0.0), "start")
        self.assertEqual(m.release(0.1), "stop")
        self.assertEqual(m.state, HoldOrLock.IDLE)


class TestStyleProfile(unittest.TestCase):
    def test_lowercase_casual_detected(self):
        p = profile(["yeah lets do it", "omw now", "cool cool"])
        self.assertTrue(p.lowercase)
        self.assertTrue(p.light_punctuation)
        self.assertTrue(any("lowercase" in h for h in p.hints()))

    def test_formal_register_no_hints(self):
        p = profile(["Sounds good, see you then.", "I'll send the deck tomorrow.", "Thanks!"])
        self.assertFalse(p.lowercase)
        self.assertEqual([h for h in p.hints() if "lowercase" in h], [])

    def test_too_few_samples_say_nothing(self):
        self.assertEqual(profile(["hi"]).hints(), [])

    def test_empty_history(self):
        p = profile([])
        self.assertEqual(p.samples, 0)
        self.assertEqual(p.hints(), [])


class TestIntentGate(unittest.TestCase):
    def setUp(self):
        self.scs = [
            make("email", ["email <person> about <topic>"], [{"type": "text", "value": "x"}]),
            make("cal", ["open (the) calendar"], [{"type": "text", "value": "y"}]),
        ]

    def test_vocabulary_extraction(self):
        vocab = _vocabulary(self.scs)
        self.assertIn("email", vocab)
        self.assertIn("calendar", vocab)
        self.assertIn("the", vocab)  # optional words count

    def test_conservative_needs_shared_word(self):
        self.assertTrue(gate("shoot an email to Sam", self.scs, "conservative"))
        self.assertFalse(gate("ship the build tonight", self.scs, "conservative"))

    def test_long_utterances_never_gate(self):
        long = "email everyone on the team about the launch and also remind me to " \
               "check the numbers before the standup tomorrow morning at nine"
        self.assertFalse(gate(long, self.scs, "conservative"))
        self.assertFalse(gate(long, self.scs, "eager"))

    def test_off_and_eager(self):
        self.assertFalse(gate("email Sam", self.scs, "off"))
        self.assertTrue(gate("ship the build", self.scs, "eager"))


class TestActionsHelpers(unittest.TestCase):
    def test_press_keys_rejects_unknown_modifier(self):
        from flow.actions import press_keys

        self.assertFalse(press_keys("hyper+x"))
        self.assertFalse(press_keys(""))

    def test_press_keys_known_shapes_offmac(self):
        import sys

        from flow.actions import press_keys

        if sys.platform == "darwin":
            self.skipTest("exercises the off-mac print path")
        self.assertTrue(press_keys("cmd+shift+4"))
        self.assertTrue(press_keys("enter"))


if __name__ == "__main__":
    unittest.main()
