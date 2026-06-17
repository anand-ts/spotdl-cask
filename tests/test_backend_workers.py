from __future__ import annotations

import unittest

from app.backend.workers import WorkerProtocolError, parse_worker_event


class WorkerProtocolTests(unittest.TestCase):
    def test_parse_valid_worker_event(self) -> None:
        event = parse_worker_event('{"type":"phase","phase":"resolving","detail":"Searching youtube-music"}')
        self.assertEqual(event["type"], "phase")
        self.assertEqual(event["phase"], "resolving")

    def test_parse_rejects_malformed_json(self) -> None:
        with self.assertRaises(WorkerProtocolError):
            parse_worker_event("not-json")

    def test_parse_rejects_missing_type(self) -> None:
        with self.assertRaises(WorkerProtocolError):
            parse_worker_event('{"detail":"missing type"}')


if __name__ == "__main__":
    unittest.main()

