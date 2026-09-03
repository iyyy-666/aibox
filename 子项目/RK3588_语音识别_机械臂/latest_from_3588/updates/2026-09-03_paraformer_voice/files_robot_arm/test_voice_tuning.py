from __future__ import annotations

import unittest

import numpy as np

from voice_engine import (
    adaptive_threshold,
    is_probably_incomplete_command_asr,
    put_latest,
    prefer_reviewed_asr,
    should_review_asr,
    trim_audio_edges,
    is_command_candidate,
    extract_command,
    should_auto_upright,
    idle_timeout_due,
)


class VoiceTuningTests(unittest.TestCase):
    def test_adaptive_threshold_stays_above_high_noise_floor(self) -> None:
        threshold = adaptive_threshold(0.14, 0.038, 1.25, 0.009, 0.22)

        self.assertGreater(threshold, 0.14)
        self.assertLess(threshold, 0.22)

    def test_put_latest_discards_all_older_commands(self) -> None:
        import queue

        commands: queue.Queue[str] = queue.Queue()
        commands.put("直立")
        commands.put("抓取")

        put_latest(commands, "停止")

        self.assertEqual(commands.get_nowait(), "停止")
        self.assertTrue(commands.empty())

    def test_trim_audio_edges_keeps_active_center(self) -> None:
        lead = np.zeros(1600, dtype=np.int16)
        body = np.array([0, 500, 1200, -1200, 700], dtype=np.int16)
        tail = np.zeros(1600, dtype=np.int16)
        audio = np.concatenate([lead, body, tail]).tobytes()

        trimmed = trim_audio_edges(audio, sample_rate=16000, edge_trim_sec=0.05)

        self.assertLess(len(trimmed), len(audio))
        samples = np.frombuffer(trimmed, dtype=np.int16)
        self.assertGreater(int(np.max(np.abs(samples))), 1000)

    def test_prefer_reviewed_asr_uses_reviewed_for_truncated_primary(self) -> None:
        self.assertEqual(
            prefer_reviewed_asr("打", "打开夹爪", audio_sec=0.4),
            "打开夹爪",
        )

    def test_prefer_reviewed_asr_keeps_complete_primary(self) -> None:
        self.assertEqual(
            prefer_reviewed_asr("打开夹爪", "打开夹爪一点", audio_sec=0.4),
            "打开夹爪",
        )

    def test_complete_long_primary_does_not_trigger_slow_review(self) -> None:
        self.assertFalse(should_review_asr("打开夹爪", audio_sec=4.2, command_matched=True))

    def test_empty_or_truncated_primary_triggers_review(self) -> None:
        self.assertTrue(should_review_asr("", audio_sec=0.7, command_matched=False))
        self.assertTrue(should_review_asr("我", audio_sec=0.7, command_matched=False))

    def test_unmatched_command_triggers_review(self) -> None:
        self.assertTrue(should_review_asr("打开夹爪", audio_sec=1.0, command_matched=False))

    def test_prefer_reviewed_asr_uses_reviewed_for_short_unmatched_command(self) -> None:
        self.assertEqual(
            prefer_reviewed_asr("打开", "打开夹爪", audio_sec=0.4, command_matched=False),
            "打开夹爪",
        )

    def test_incomplete_command_prefix_triggers_review_without_penalizing_exact_alias(self) -> None:
        commands = ("张开",)

        self.assertTrue(is_probably_incomplete_command_asr("打开夹", commands))
        self.assertFalse(is_probably_incomplete_command_asr("打开", commands))


    def test_command_candidate_requires_registered_command(self) -> None:
        self.assertTrue(is_command_candidate("\u6253\u5f00\u5939\u722a", ("\u6253\u5f00\u5939\u722a",)))
        self.assertFalse(is_command_candidate("\u6253\u5f00", ("\u6253\u5f00\u5939\u722a",)))
        self.assertFalse(is_command_candidate("\u4eca\u5929\u5929\u6c14\u4e0d\u9519", ("\u6253\u5f00\u5939\u722a",)))

    def test_paraformer_backend_name_is_supported(self) -> None:
        from voice_engine import normalize_backend_name

        self.assertEqual(normalize_backend_name("paraformer_onnx"), "paraformer")
        self.assertEqual(normalize_backend_name("paraformer"), "paraformer")

    def test_extract_command_accepts_sentence_and_single_character_errors(self) -> None:
        commands = ("直立", "放平", "抓取", "搬运", "张开", "闭合")
        self.assertEqual(extract_command("请帮我把机械臂站起来", commands), "直立")
        self.assertEqual(extract_command("实力", commands), "直立")
        self.assertEqual(extract_command("只", commands), "直立")
        self.assertEqual(extract_command("帮我抓一下", commands), "抓取")

    def test_extract_command_does_not_return_removed_commands(self) -> None:
        commands = ("直立", "放平", "抓取")
        self.assertIsNone(extract_command("停止", commands))
        self.assertIsNone(extract_command("复位", commands))

    def test_auto_upright_after_twenty_seconds_without_new_command(self) -> None:
        self.assertTrue(should_auto_upright(last_command_age=20.1, moving=False, already_upright=False))
        self.assertFalse(should_auto_upright(last_command_age=19.9, moving=False, already_upright=False))
        self.assertFalse(should_auto_upright(last_command_age=25.0, moving=True, already_upright=False))

    def test_idle_timeout_starts_when_motion_has_finished(self) -> None:
        self.assertTrue(idle_timeout_due(20.0, moving=False, already_upright=False))
        self.assertFalse(idle_timeout_due(20.0, moving=True, already_upright=False))


if __name__ == "__main__":
    unittest.main()
