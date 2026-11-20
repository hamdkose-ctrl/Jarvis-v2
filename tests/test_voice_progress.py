"""Progress narration: spoken while work runs, quiet enough to stay useful.

The user's requirement: Jarvis should keep talking while it works, and the voice
must not change when the model provider changes. Voice identity is chosen from the
profile's catalog entry (see voice_runtime), never from the provider; this module
only decides what may be said, so the two requirements cannot drift apart.
"""
import unittest
from types import SimpleNamespace

from modules import voice_progress


class NarrationTests(unittest.TestCase):
    def setUp(self):
        voice_progress._LINES.clear()

    def runtime(self, *, speak=True, sleep=False, paused=False):
        events = []
        return SimpleNamespace(
            flags={"speak": speak, "sleep": sleep},
            pause_listening=SimpleNamespace(is_set=lambda: paused),
            events=SimpleNamespace(put=events.append),
        ), events

    def job(self, ident="job-1", owner="hamdi"):
        return {"id": ident, "owner": owner, "steps": []}

    def test_one_line_reaches_the_single_voice_lane_with_progress_kind(self):
        runtime, events = self.runtime()
        self.assertTrue(voice_progress.narrate(runtime, self.job(), "Başlıyorum.", now=100.0))
        self.assertEqual(events, [("say", "Başlıyorum.", "hamdi",
                                   {"kind": "progress", "goal_id": "job-1"})])

    def test_a_slow_job_cannot_turn_into_a_monologue(self):
        runtime, events = self.runtime()
        job = self.job()
        # A line every second for two minutes must still produce at most the cap.
        said = sum(1 for second in range(120)
                   if voice_progress.narrate(runtime, job, "Çalışıyorum.", now=float(second)))
        self.assertEqual(said, voice_progress.MAX_LINES_PER_JOB)
        self.assertEqual(len(events), voice_progress.MAX_LINES_PER_JOB)

    def test_lines_respect_the_minimum_gap(self):
        runtime, _events = self.runtime()
        job = self.job()
        self.assertTrue(voice_progress.narrate(runtime, job, "Bir.", now=100.0))
        self.assertFalse(voice_progress.narrate(runtime, job, "İki.", now=101.0))
        self.assertTrue(voice_progress.narrate(
            runtime, job, "Üç.", now=100.0 + voice_progress.MIN_GAP_SECONDS))

    def test_a_muted_or_sleeping_profile_stays_silent(self):
        for flags in ({"speak": False}, {"sleep": True}):
            runtime, events = self.runtime(**flags)
            self.assertFalse(voice_progress.narrate(runtime, self.job(), "Başlıyorum.", now=100.0))
            self.assertEqual(events, [])

    def test_a_notice_that_owns_the_speaker_is_not_interrupted(self):
        runtime, events = self.runtime(paused=True)
        self.assertFalse(voice_progress.narrate(runtime, self.job(), "Başlıyorum.", now=100.0))
        self.assertEqual(events, [])

    def test_step_words_never_invent_unknown_work(self):
        self.assertEqual(voice_progress.step_words("research"), "Kaynakları tarıyorum.")
        self.assertEqual(voice_progress.step_words(" RESEARCH "), "Kaynakları tarıyorum.")
        self.assertEqual(voice_progress.step_words("bilinmeyen"), voice_progress._GENERIC_STEP)
        self.assertEqual(voice_progress.step_words(None), voice_progress._GENERIC_STEP)

    def test_forget_lets_a_new_job_speak_again(self):
        runtime, _events = self.runtime()
        job = self.job()
        for second in range(60):
            voice_progress.narrate(runtime, job, "Çalışıyorum.", now=float(second))
        self.assertFalse(voice_progress.may_speak("job-1", now=1000.0))
        voice_progress.forget("job-1")
        self.assertTrue(voice_progress.may_speak("job-1", now=1000.0))


if __name__ == "__main__":
    unittest.main()
