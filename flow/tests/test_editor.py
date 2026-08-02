"""Tests for the editor's local API server, driven over real HTTP."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from flow.editor import make_handler
from flow.shortcuts import ShortcutStore

VALID = {
    "name": "sign off",
    "trigger": {"phrases": ["sign off"]},
    "blocks": [{"type": "text", "value": "Best,\nA"}],
}


class EditorApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ShortcutStore(Path(self._tmp.name))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def _req(self, path, payload=None, *, header=True):
        headers = {"Content-Type": "application/json"}
        if header:
            headers["X-Flow"] = "1"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_editor_page_serves(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
        self.assertIn("flow blocks", body)
        self.assertIn("api/shortcuts", body)

    def test_api_requires_header(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._req("/api/shortcuts", header=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_save_list_delete_roundtrip(self):
        status, res = self._req("/api/shortcuts", VALID)
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        status, res = self._req("/api/shortcuts")
        self.assertEqual([s["name"] for s in res["shortcuts"]], ["sign off"])
        status, res = self._req("/api/delete", {"name": "sign off"})
        self.assertTrue(res["ok"])
        _, res = self._req("/api/shortcuts")
        self.assertEqual(res["shortcuts"], [])

    def test_save_invalid_reports_problems(self):
        bad = {"name": "x", "trigger": {"phrases": []}, "blocks": []}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._req("/api/shortcuts", bad)
        self.assertEqual(ctx.exception.code, 400)
        problems = json.loads(ctx.exception.read())["problems"]
        self.assertTrue(problems)

    def test_try_with_unsaved_shortcut(self):
        payload = {
            "utterance": "email Sam about the launch",
            "shortcut": {
                "name": "email",
                "trigger": {"phrases": ["email <person> about <topic>"]},
                "blocks": [{"type": "slot", "name": "person"}],
            },
        }
        _, res = self._req("/api/try", payload)
        self.assertTrue(res["fires"])
        self.assertEqual(res["kind"], "command")
        self.assertEqual(res["slots"], {"person": "sam", "topic": "the launch"})
        self.assertEqual(res["text"], "sam")

    def test_try_no_fire(self):
        payload = {"utterance": "just some ordinary dictation", "shortcut": VALID}
        _, res = self._req("/api/try", payload)
        self.assertFalse(res["fires"])

    def test_try_against_saved(self):
        self._req("/api/shortcuts", VALID)
        _, res = self._req("/api/try", {"utterance": "sign off"})
        self.assertTrue(res["fires"])
        self.assertEqual(res["text"], "Best,\nA")


class ExampleShortcutsTest(unittest.TestCase):
    def test_shipped_examples_are_valid(self):
        from flow.shortcuts import Shortcut

        examples = Path(__file__).resolve().parent.parent / "examples" / "shortcuts"
        files = sorted(examples.glob("*.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            Shortcut.from_dict(json.loads(f.read_text(encoding="utf-8")))  # raises if invalid


if __name__ == "__main__":
    unittest.main()
