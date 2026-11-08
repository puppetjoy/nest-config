"""Isolated launcher contracts: never invoke a real browser or music player."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SpotifyLauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="spotify-launcher-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.log = self.base / "calls.jsonl"
        self.stub = self.base / "backend"
        self.stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['CALLS'], 'a') as f:\n"
            " f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1] == 'xdotool' and sys.argv[2] == 'search':\n"
            " print(os.environ.get('WINDOWS', ''), end='')\n"
            " sys.exit(0 if os.environ.get('WINDOWS') else 1)\n"
        )
        self.stub.chmod(0o700)
        self.env = dict(os.environ, CALLS=str(self.log), HOME=str(self.base),
                        DISPLAY=":99", XDG_RUNTIME_DIR=str(self.base),
                        XDG_CONFIG_HOME=str(self.base / "config with spaces"))

    def render(self, backend, hardware_video_decode=True):
        rendered = subprocess.check_output(
            ["ruby", "-rerb", "-e",
             "@backend=ARGV[1]; @hardware_video_decode=ARGV[2]=='true'; scope={'nest::gui_scaling_factor'=>2.0}; "
             "print ERB.new(File.read(ARGV[0]), trim_mode: '-').result(binding)",
             str(ROOT / "templates/spotify/launcher.erb"), backend, str(hardware_video_decode).lower()], text=True)
        subprocess.run(["bash", "-n"], input=rendered, text=True, check=True)
        for command in ("spotify", "google-chrome-stable", "xdotool"):
            rendered = rendered.replace("/usr/bin/" + command, str(self.stub) + " " + command)
        path = self.base / "launcher"
        path.write_text(rendered)
        return path

    def run_launcher(self, backend, *args):
        return subprocess.run(["bash", str(self.render(backend)), *args],
                              env=self.env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_native_launch_has_no_playback_arguments(self):
        self.assertEqual(self.run_launcher("native").returncode, 0)
        self.assertEqual(self.calls(), [["spotify"]])

    def test_native_software_video_decode_preserves_normal_session(self):
        result = subprocess.run(["bash", str(self.render("native", hardware_video_decode=False))],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [["spotify", "--disable-accelerated-video-decode"]])

    def test_web_isolated_profile_and_exact_identity(self):
        self.assertEqual(self.run_launcher("web").returncode, 0)
        browser = [call for call in self.calls() if call[0] == "google-chrome-stable"]
        self.assertEqual(browser, [["google-chrome-stable",
                                   "--user-data-dir=" + self.env["XDG_CONFIG_HOME"] + "/nest-spotify",
                                   "--ozone-platform=x11", "--force-device-scale-factor=2.0",
                                   "--class=nest-spotify",
                                   "--app=https://open.spotify.com/"]])

    def test_existing_window_is_reused(self):
        self.env["WINDOWS"] = "50\n20\n"
        self.assertEqual(self.run_launcher("web").returncode, 0)
        self.assertEqual(self.calls()[-1], ["xdotool", "windowactivate", "20"])
        self.assertFalse(any(call[0] == "google-chrome-stable" for call in self.calls()))

    def test_concurrent_start_does_not_launch_another_browser(self):
        with open(self.base / "nest-spotify.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_launcher("web").returncode, 0)
        self.assertFalse(any(call[0] == "google-chrome-stable" for call in self.calls()))

    def test_arguments_cannot_change_profile_or_start_playback(self):
        self.assertEqual(self.run_launcher("web", "spotify:track:example").returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_missing_session_fails_before_launch(self):
        self.env.pop("DISPLAY")
        self.assertNotEqual(self.run_launcher("web").returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
