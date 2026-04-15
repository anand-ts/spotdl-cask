"""Regression tests for bundled ffmpeg discovery."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class RuntimeFFmpegTests(unittest.TestCase):
    """Cover bundled/runtime ffmpeg resolution without relying on shell PATH."""

    def _make_executable(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_resolve_binary_prefers_bundled_ffmpeg_when_frozen(self) -> None:
        """Bundled ffmpeg should be preferred over shell-discovered binaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_root = Path(tmpdir)
            ffmpeg_path = self._make_executable(bundle_root / "bin" / "ffmpeg")

            with (
                mock.patch.object(app.sys, "frozen", True, create=True),
                mock.patch.object(app.sys, "_MEIPASS", str(bundle_root), create=True),
                mock.patch.object(
                    app.sys,
                    "executable",
                    str(bundle_root / "MacOS" / "spotdl-web-downloader"),
                    create=True,
                ),
                mock.patch.object(app.shutil, "which", return_value="/usr/bin/ffmpeg"),
            ):
                resolved = app._resolve_binary_path("ffmpeg")

        self.assertEqual(resolved, ffmpeg_path.resolve())

    def test_configure_runtime_sets_path_and_ffmpeg_argument(self) -> None:
        """The helper should expose ffmpeg to spotdl and its child tools."""
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_dir = Path(tmpdir) / "bin"
            ffmpeg_path = self._make_executable(binary_dir / "ffmpeg")
            ffprobe_path = self._make_executable(binary_dir / "ffprobe")

            original_argv = list(app.sys.argv)
            original_path = os.environ.get("PATH")
            try:
                app.sys.argv = ["app.py", "--run-spotdl", "download", "example"]
                os.environ["PATH"] = "/usr/bin"

                with mock.patch.object(
                    app,
                    "_resolve_binary_path",
                    side_effect=[ffmpeg_path.resolve(), ffprobe_path.resolve()],
                ):
                    app._configure_bundled_spotdl_environment()

                self.assertEqual(
                    app.sys.argv[-2:], ["--ffmpeg", str(ffmpeg_path.resolve())]
                )
                self.assertTrue(
                    os.environ["PATH"].split(os.pathsep)[0].endswith(str(binary_dir))
                )
            finally:
                app.sys.argv = original_argv
                if original_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = original_path

    def test_configure_runtime_keeps_existing_ffmpeg_argument(self) -> None:
        """Do not append duplicate ffmpeg flags when one is already present."""
        existing_ffmpeg = "/custom/ffmpeg"
        original_argv = list(app.sys.argv)
        try:
            app.sys.argv = [
                "app.py",
                "--run-spotdl",
                "download",
                "example",
                "--ffmpeg",
                existing_ffmpeg,
            ]

            with mock.patch.object(
                app,
                "_resolve_binary_path",
                side_effect=[None, None],
            ):
                app._configure_bundled_spotdl_environment()

            self.assertEqual(app.sys.argv.count("--ffmpeg"), 1)
            self.assertEqual(app.sys.argv[-1], existing_ffmpeg)
        finally:
            app.sys.argv = original_argv


if __name__ == "__main__":
    unittest.main()
