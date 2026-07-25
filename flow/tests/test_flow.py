"""Unit tests for everything deterministic: run with `python -m unittest discover -s tests`."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from flow.audio import wav_bytes
from flow.context import HistoryStore, PrefStore, contact_from_window
from flow.language import (
    DEVANAGARI_SCRIPT,
    ENGLISH,
    HINDI,
    HINGLISH,
    LATIN_SCRIPT,
    decide,
    script_mix,
)
from flow.polish import build_user_message, fallback_cleanup
from flow.transcribe import build_asr_prompt


class TestLanguageDecision(unittest.TestCase):
    def test_plain_english(self):
        t = decide("send the report by Friday and cc the design team")
        self.assertEqual(t.language, ENGLISH)
        self.assertIsNone(t.hindi_script)

    def test_english_with_indian_name_stays_english(self):
        t = decide("ask Priya to review the pull request")
        self.assertEqual(t.language, ENGLISH)

    def test_single_hindi_like_token_stays_english(self):
        # one dictionary hit must not flip the sentence
        t = decide("the acha demo went well")
        self.assertEqual(t.language, ENGLISH)

    def test_devanagari_is_hindi(self):
        t = decide("कल मिलते हैं शाम को")
        self.assertEqual(t.language, HINDI)
        self.assertEqual(t.hindi_script, DEVANAGARI_SCRIPT)

    def test_devanagari_with_english_is_hinglish(self):
        t = decide("मैं office से late निकलूँगा so start the meeting without me")
        self.assertEqual(t.language, HINGLISH)
        self.assertEqual(t.hindi_script, DEVANAGARI_SCRIPT)

    def test_romanized_hindi_detected(self):
        t = decide("haan theek hai kal milte hain")
        self.assertIn(t.language, (HINDI, HINGLISH))
        self.assertEqual(t.hindi_script, LATIN_SCRIPT)

    def test_romanized_hinglish_mix(self):
        t = decide("bhai deploy karo aur phir mujhe batao")
        self.assertEqual(t.language, HINGLISH)
        self.assertEqual(t.hindi_script, LATIN_SCRIPT)

    def test_preference_overrides_mirror(self):
        t = decide("कल मिलते हैं", preferred_script=LATIN_SCRIPT)
        self.assertEqual(t.hindi_script, LATIN_SCRIPT)
        self.assertEqual(t.source, "contact preference")

    def test_policy_used_when_no_preference(self):
        t = decide("haan theek hai kal milte hain", policy=DEVANAGARI_SCRIPT)
        self.assertEqual(t.hindi_script, DEVANAGARI_SCRIPT)

    def test_script_mix_counts(self):
        mix = script_mix("कल milte hain")
        self.assertGreater(mix.devanagari_chars, 0)
        self.assertEqual(mix.latin_words, 2)
        self.assertEqual(mix.roman_hindi_hits, 2)


class TestContact(unittest.TestCase):
    def test_whatsapp_title_is_contact(self):
        self.assertEqual(contact_from_window("WhatsApp", "Mummy"), "Mummy")

    def test_whatsapp_bare_title_is_none(self):
        self.assertIsNone(contact_from_window("WhatsApp", "WhatsApp"))

    def test_slack_dm(self):
        self.assertEqual(
            contact_from_window("Slack", "Priya Sharma (DM) - rolemate - Slack"),
            "Priya Sharma",
        )

    def test_slack_channel(self):
        self.assertEqual(
            contact_from_window("Slack", "#launch - rolemate - Slack"), "#launch"
        )

    def test_non_messaging_app_is_none(self):
        self.assertIsNone(contact_from_window("Code", "polish.py — shortcuts"))


class TestStores(unittest.TestCase):
    def test_pref_learning_and_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = PrefStore(Path(d) / "prefs.json")
            self.assertIsNone(prefs.resolve("WhatsApp", "Mummy"))
            prefs.record("WhatsApp", "Mummy", "devanagari")
            # one sample is not a preference
            self.assertIsNone(prefs.resolve("WhatsApp", "Mummy"))
            prefs.record("WhatsApp", "Mummy", "devanagari")
            self.assertEqual(prefs.resolve("WhatsApp", "Mummy"), "devanagari")
            # app-level fallback kicks in for an unknown contact in the same app
            self.assertEqual(prefs.resolve("WhatsApp", "Someone New"), "devanagari")
            # reload from disk survives
            again = PrefStore(Path(d) / "prefs.json")
            self.assertEqual(again.resolve("WhatsApp", "Mummy"), "devanagari")

    def test_pref_majority_wins(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = PrefStore(Path(d) / "prefs.json")
            for _ in range(3):
                prefs.record("WhatsApp", "Rohan", "latin")
            prefs.record("WhatsApp", "Rohan", "devanagari")
            self.assertEqual(prefs.resolve("WhatsApp", "Rohan"), "latin")

    def test_history_scoped_recency(self):
        with tempfile.TemporaryDirectory() as d:
            hist = HistoryStore(Path(d) / "h.jsonl")
            hist.append({"app": "WhatsApp", "contact": "Mummy", "text": "namaste"})
            hist.append({"app": "Code", "contact": None, "text": "def foo"})
            hist.append({"app": "WhatsApp", "contact": "Mummy", "text": "kal aaungi"})
            scoped = hist.recent("WhatsApp", "Mummy", n=5)
            self.assertEqual([e["text"] for e in scoped], ["namaste", "kal aaungi"])
            # unknown scope falls back to global recency
            self.assertEqual(len(hist.recent("Mail", None, n=2)), 2)


class TestPolishHelpers(unittest.TestCase):
    def test_fallback_cleanup(self):
        self.assertEqual(
            fallback_cleanup("um  so i think we should ship it tomorrow"),
            "So I think we should ship it tomorrow.",
        )
        self.assertEqual(fallback_cleanup("   "), "")
        self.assertEqual(fallback_cleanup("ok"), "Ok")

    def test_user_message_contains_all_parts(self):
        target = decide("haan theek hai kal milte hain")
        msg = build_user_message(
            "haan theek hai kal milte hain",
            target,
            app="WhatsApp",
            contact="Rohan",
            recent=["kal call karte hain"],
            dictionary=["Rolemate"],
        )
        for needle in [
            "WhatsApp",
            "Rohan",
            "kal call karte hain",
            "Rolemate",
            "hindi_script: latin",
            "<transcript>",
            "haan theek hai kal milte hain",
        ]:
            self.assertIn(needle, msg)

    def test_english_target_has_no_script_line(self):
        msg = build_user_message("ship it", decide("ship the release today please"))
        self.assertNotIn("hindi_script", msg)


class TestAsrPrompt(unittest.TestCase):
    def test_primer_matches_preference(self):
        self.assertIn("theek", build_asr_prompt(None, "latin"))
        self.assertIn("ठीक", build_asr_prompt(None, "devanagari"))
        self.assertEqual(build_asr_prompt(None, None), "")

    def test_dictionary_included_and_capped(self):
        p = build_asr_prompt(["Rolemate", "Trackathon"], None)
        self.assertIn("Rolemate", p)
        self.assertLessEqual(len(build_asr_prompt(["x" * 50] * 100, None)), 800)


class TestAudio(unittest.TestCase):
    def test_wav_container(self):
        pcm = b"\x00\x01" * 1600  # 0.1s of 16kHz mono int16
        data = wav_bytes(pcm, 16_000)
        with wave.open(io.BytesIO(data)) as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getframerate(), 16_000)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getnframes(), 1600)


class TestPipelineOffline(unittest.TestCase):
    def test_run_pipeline_without_keys_uses_fallback(self):
        import os

        from flow.config import Config
        from flow.daemon import Snapshot, run_pipeline

        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ["FLOW_DIR"] = d
                from flow.daemon import Stores

                cfg = Config()
                stores = Stores(cfg)
                snap = Snapshot(focus=None, preferred_script=None)
                final, target = run_pipeline(
                    "um so let's ship the build tonight", snap, cfg, stores
                )
                self.assertEqual(final, "So let's ship the build tonight.")
                self.assertEqual(target.language, ENGLISH)
                # history got written
                self.assertEqual(len(stores.history.entries()), 1)
        finally:
            os.environ.pop("FLOW_DIR", None)
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
