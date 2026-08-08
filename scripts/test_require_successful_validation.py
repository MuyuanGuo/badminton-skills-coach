#!/usr/bin/env python3
import unittest

from require_successful_validation import (
    validation_state,
    wait_for_successful_validation,
)


REPOSITORY = "MuyuanGuo/badminton-skills-coach"
SHA = "a" * 40


def run_payload(status, conclusion=None, *, sha=SHA, branch="main"):
    return {
        "head_sha": sha,
        "head_branch": branch,
        "event": "push",
        "status": status,
        "conclusion": conclusion,
        "head_repository": {"full_name": REPOSITORY},
    }


class SuccessfulValidationGateTests(unittest.TestCase):
    def test_exact_successful_main_push_is_reused(self):
        self.assertEqual(
            validation_state(
                [run_payload("completed", "success")],
                REPOSITORY,
                SHA,
            ),
            "success",
        )

    def test_pr_fork_or_different_sha_cannot_satisfy_release_gate(self):
        candidates = [
            {**run_payload("completed", "success"), "event": "pull_request"},
            run_payload("completed", "success", sha="b" * 40),
            {
                **run_payload("completed", "success"),
                "head_repository": {"full_name": "someone/fork"},
            },
        ]
        self.assertEqual(validation_state(candidates, REPOSITORY, SHA), "missing")

    def test_non_successful_completed_run_fails_closed(self):
        self.assertEqual(
            validation_state(
                [run_payload("completed", "failure")],
                REPOSITORY,
                SHA,
            ),
            "failed",
        )

    def test_waits_for_in_progress_run_then_reuses_success(self):
        responses = iter(
            [
                [run_payload("in_progress")],
                [run_payload("completed", "success")],
            ]
        )
        clock = iter([0, 0, 1])
        result = wait_for_successful_validation(
            REPOSITORY,
            SHA,
            "validate.yml",
            "main",
            "token",
            30,
            1,
            fetcher=lambda *_args: next(responses),
            sleep=lambda _seconds: None,
            monotonic=lambda: next(clock),
        )
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
