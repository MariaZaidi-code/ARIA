"""Reingest scheduler regression tests.

Locks the interval validation: NaN/Infinity/non-positive values must be
rejected (previously ``timedelta`` raised and a non-positive interval caused
the job to re-run on every 60s scheduler tick).
"""

import math
import unittest

from services import reingest_scheduler as rs


class ReingestSchedulerTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from pathlib import Path

        self._orig_jobs_path = rs.JOBS_PATH
        rs.JOBS_PATH = Path(self._tmp.name) / "reingest_jobs.json"
        self.addCleanup(setattr, rs, "JOBS_PATH", self._orig_jobs_path)

    def test_rejects_non_positive_and_non_finite_intervals(self):
        for bad in (0, -1, float("nan"), float("inf"), float("-inf"), "abc", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    rs.add_job("user_1", bad)

    def test_adds_and_lists_valid_job(self):
        job = rs.add_job("user_1", 2.5, ["doc_a"])
        self.assertEqual(job["interval_hours"], 2.5)
        self.assertTrue(math.isfinite(job["interval_hours"]))
        jobs = rs.list_jobs("user_1")
        self.assertEqual([j["id"] for j in jobs], [job["id"]])
        self.assertEqual(jobs[0]["document_ids"], ["doc_a"])


if __name__ == "__main__":
    unittest.main()
