#!/usr/bin/env python3
"""Wait for a successful main-branch validation of an exact release SHA."""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request


ACTIVE_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


def matching_runs(runs, repository, sha, branch):
    return [
        run
        for run in runs
        if run.get("head_sha") == sha
        and run.get("head_branch") == branch
        and run.get("event") == "push"
        and (run.get("head_repository") or {}).get("full_name") == repository
    ]


def validation_state(runs, repository, sha, branch="main"):
    matches = matching_runs(runs, repository, sha, branch)
    if any(
        run.get("status") == "completed" and run.get("conclusion") == "success"
        for run in matches
    ):
        return "success"
    if any(run.get("status") in ACTIVE_STATUSES for run in matches):
        return "pending"
    if matches:
        return "failed"
    return "missing"


def fetch_workflow_runs(repository, workflow, sha, branch, token):
    query = urllib.parse.urlencode(
        {
            "branch": branch,
            "event": "push",
            "head_sha": sha,
            "per_page": 20,
        }
    )
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/"
        f"{urllib.parse.quote(workflow, safe='')}/runs?{query}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "badminton-skills-coach-release-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response).get("workflow_runs", [])


def wait_for_successful_validation(
    repository,
    sha,
    workflow,
    branch,
    token,
    timeout_seconds,
    poll_seconds,
    *,
    fetcher=fetch_workflow_runs,
    sleep=time.sleep,
    monotonic=time.monotonic,
):
    deadline = monotonic() + timeout_seconds
    last_state = "missing"
    while True:
        runs = fetcher(repository, workflow, sha, branch, token)
        last_state = validation_state(runs, repository, sha, branch)
        if last_state == "success":
            return {
                "repository": repository,
                "sha": sha,
                "workflow": workflow,
                "branch": branch,
                "status": "success",
            }
        if last_state == "failed":
            raise RuntimeError(
                "The exact release commit has a completed, non-successful "
                "main-branch validation"
            )
        if monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for an exact successful main-branch "
                f"validation; last state was {last_state}"
            )
        sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--workflow", default="validate.yml")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("--repository must be an owner/name pair")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase commit SHA")
    if args.timeout_seconds < 0 or args.poll_seconds <= 0:
        parser.error("polling durations must be positive")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN is required")
    try:
        result = wait_for_successful_validation(
            args.repository,
            args.sha,
            args.workflow,
            args.branch,
            token,
            args.timeout_seconds,
            args.poll_seconds,
        )
    except (RuntimeError, TimeoutError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
