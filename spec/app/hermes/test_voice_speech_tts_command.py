#!/usr/bin/env python3
"""Regression tests for Hermes voice-speech TTS speech-only normalization."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[3] / "files" / "app" / "hermes" / "voice-speech-tts-command.py"


spec = importlib.util.spec_from_file_location("voice_speech_tts_command", MODULE_PATH)
assert spec is not None
voice_speech_tts_command = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(voice_speech_tts_command)


class NormalizeTtsTextTest(unittest.TestCase):
    def normalize(self, text: str) -> str:
        return voice_speech_tts_command.normalize_tts_text(text)

    def test_colon_labels_gain_speech_pause_periods(self) -> None:
        self.assertEqual(self.normalize("Status: healthy"), "Status. healthy")
        self.assertEqual(
            self.normalize("Results: API healthy; queue tail normal; limiter active."),
            "Results. API healthy. queue tail normal. limiter active.",
        )
        self.assertEqual(
            self.normalize("Status: healthy. Queue: normal. Limiter: active."),
            "Status. healthy. Queue. normal. Limiter. active.",
        )

    def test_operational_identifiers_are_spoken_and_visible_source_is_not_mutated(self) -> None:
        source = "Task t_6c5e456f: Status: healthy"
        normalized = self.normalize(source)
        self.assertEqual(normalized, "Task T, six C five E four five six F. Status. healthy")
        self.assertEqual(source, "Task t_6c5e456f: Status: healthy")

    def test_times_urls_and_ratios_do_not_get_label_pause_rewrites(self) -> None:
        self.assertEqual(self.normalize("Window 12:30 to 13:00"), "Window 12:30 to 13:00")
        self.assertEqual(self.normalize("Ratio 1:2 is expected"), "Ratio 1:2 is expected")
        self.assertEqual(
            self.normalize("Docs: https://talon.eyrie/status: check"),
            "Docs. H T T P S link talon dot eyrie slash status. check",
        )


if __name__ == "__main__":
    unittest.main()
