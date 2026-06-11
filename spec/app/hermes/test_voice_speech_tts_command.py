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

    def test_operational_identifiers_are_suppressed_and_visible_source_is_not_mutated(self) -> None:
        source = "Request ar-20260611-193233-fca585 task t_6c5e456f: Status: healthy"
        normalized = self.normalize(source)
        self.assertEqual(normalized, "request recorded task recorded: Status: healthy")
        self.assertEqual(source, "Request ar-20260611-193233-fca585 task t_6c5e456f: Status: healthy")

    def test_review_acceptance_ids_hashes_and_commits_are_summarized(self) -> None:
        self.assertEqual(
            self.normalize(
                "Acceptance ID: rva-20260611-162641-d6b758; "
                "Commit f70994374; SHA256 "
                "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
            ),
            "review acceptance recorded; Commit recorded; checksum recorded",
        )

    def test_urls_paths_and_technical_terms_are_shortened_without_cadence_rewrites(self) -> None:
        self.assertEqual(
            self.normalize("Docs: https://talon.eyrie/status: check /home/joy/tts-cadence/output.wav"),
            "Docs: link: check path home joy tts-cadence and more",
        )
        self.assertEqual(
            self.normalize("KubeCM and kubectl manage Eyrie OpenVox ROCm."),
            "cube see em and cube control manage airy open vox rock em.",
        )


if __name__ == "__main__":
    unittest.main()
