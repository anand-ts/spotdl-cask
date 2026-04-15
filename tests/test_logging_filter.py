"""Regression tests for noisy third-party log filtering."""

import logging
import unittest

from app import _SpotipyRateLimitFilter


class SpotipyRateLimitFilterTests(unittest.TestCase):
    """Ensure expected Spotify rate limits do not spam the terminal."""

    def setUp(self) -> None:
        self.filter = _SpotipyRateLimitFilter()

    def test_filters_handled_spotipy_429_logs(self) -> None:
        """Expected rate-limit messages should be hidden."""
        record = logging.LogRecord(
            "spotipy.client",
            logging.ERROR,
            __file__,
            1,
            "HTTP Error for GET to x returned 429 due to Too many requests",
            (),
            None,
        )

        self.assertFalse(self.filter.filter(record))

    def test_keeps_other_spotipy_errors_visible(self) -> None:
        """Non-rate-limit Spotify failures should still reach the terminal."""
        record = logging.LogRecord(
            "spotipy.client",
            logging.ERROR,
            __file__,
            1,
            "HTTP Error for GET to x returned 500 due to Internal Server Error",
            (),
            None,
        )

        self.assertTrue(self.filter.filter(record))


if __name__ == "__main__":
    unittest.main()
