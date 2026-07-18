#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = (3, 10)
REQUIRED_SKILL_FILES = [
    "SKILL.md",
    "scripts/prepare_answer_context.py",
    "scripts/search_knowledge.py",
    "scripts/navigate_topics.py",
    "scripts/feedback.py",
    "references/knowledge-base.json",
    "references/retrieval-index.json",
    "references/retrieval-rules.json",
    "references/answer-modality-rules.json",
    "references/answer-selection-rules.json",
    "references/answer-workflow.md",
    "references/build-manifest.json",
    "references/practice-plan-rules.json",
    "references/feedback-rules.json",
    "references/feedback-signals.json",
    "references/topic-map.json",
]
JSON_SKILL_FILES = [
    path for path in REQUIRED_SKILL_FILES if path.endswith(".json")
]


def check(name, ok, detail, remediation=None, required=True):
    return {
        "name": name,
        "status": "pass" if ok else "fail" if required else "warn",
        "required": required,
        "detail": detail,
        "remediation": None if ok else remediation,
    }


def nearest_existing_parent(path):
    candidate = Path(path).expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def skill_checks(skill_root=SKILL_ROOT, run_smoke=True):
    skill_root = Path(skill_root).resolve()
    checks = [
        check(
            "python_version",
            sys.version_info >= MINIMUM_PYTHON,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Install Python 3.10 or newer.",
        )
    ]
    missing = [path for path in REQUIRED_SKILL_FILES if not (skill_root / path).is_file()]
    checks.append(
        check(
            "skill_files",
            not missing,
            "all required files present" if not missing else "missing: " + ", ".join(missing),
            "Reinstall the Skill from a complete release archive.",
        )
    )

    payloads = {}
    json_errors = []
    for relative in JSON_SKILL_FILES:
        path = skill_root / relative
        if not path.is_file():
            continue
        try:
            payloads[relative] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            json_errors.append(f"{relative}: {error}")
    checks.append(
        check(
            "skill_json",
            not json_errors and len(payloads) == len(JSON_SKILL_FILES),
            "all bundled JSON parsed" if not json_errors else "; ".join(json_errors),
            "Reinstall the Skill; one or more bundled resources are corrupt.",
        )
    )

    knowledge = payloads.get("references/knowledge-base.json", {})
    retrieval = payloads.get("references/retrieval-index.json", {})
    try:
        ready_ids = {
            str(video["video_id"])
            for video in knowledge["videos"]
            if video["processing_status"] == "ready"
        }
        retrieval_ids = {str(video["video_id"]) for video in retrieval["videos"]}
        aligned = bool(ready_ids) and ready_ids == retrieval_ids
        detail = f"ready={len(ready_ids)}, retrieval={len(retrieval_ids)}"
    except (KeyError, TypeError):
        aligned = False
        detail = "knowledge or retrieval schema is invalid"
    checks.append(
        check(
            "knowledge_alignment",
            aligned,
            detail,
            "Reinstall a release whose knowledge base and retrieval index were packaged together.",
        )
    )

    manifest = payloads.get("references/build-manifest.json", {})
    artifact_errors = []
    for artifact in manifest.get("skill_artifacts", []):
        path = skill_root / artifact.get("path", "")
        if not path.is_file():
            artifact_errors.append(f"missing:{artifact.get('path')}")
            continue
        content = path.read_bytes()
        if len(content) != artifact.get("bytes"):
            artifact_errors.append(f"size:{artifact.get('path')}")
        if hashlib.sha256(content).hexdigest() != artifact.get("sha256"):
            artifact_errors.append(f"sha256:{artifact.get('path')}")
    manifest_without_id = dict(manifest)
    expected_build_id = manifest_without_id.pop("build_id", None)
    canonical_manifest = (
        json.dumps(
            manifest_without_id,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    actual_build_id = hashlib.sha256(canonical_manifest).hexdigest()
    manifest_ok = bool(manifest) and not artifact_errors and (
        expected_build_id == actual_build_id
    )
    checks.append(
        check(
            "build_manifest",
            manifest_ok,
            f"build_id={expected_build_id}, artifacts={len(manifest.get('skill_artifacts', []))}"
            if manifest_ok
            else "; ".join(artifact_errors)
            or "manifest build_id mismatch",
            "Reinstall a complete release or rebuild its deterministic manifest.",
        )
    )

    portable_knowledge = (
        knowledge.get("transcript_files_bundled") is False
        and not any("transcript_file" in video for video in knowledge.get("videos", []))
    )
    checks.append(
        check(
            "portable_knowledge_paths",
            portable_knowledge,
            "no unavailable maintainer transcript paths are bundled",
            "Reinstall the Skill from a package built by the current release pipeline.",
        )
    )
    transcript_backed_ready = [
        video
        for video in knowledge.get("videos", [])
        if video.get("processing_status") == "ready"
        and video.get("confidence") != "visual_reviewed"
    ]
    runtime_segments_complete = (
        knowledge.get("runtime_transcript_segments_bundled") is True
        and transcript_backed_ready
        and all(video.get("transcript_segments") for video in transcript_backed_ready)
    )
    checks.append(
        check(
            "runtime_transcript_evidence",
            bool(runtime_segments_complete),
            f"timestamped segments bundled for {len(transcript_backed_ready)} transcript-backed ready videos",
            "Rebuild and reinstall the Skill so query-time transcript evidence is available.",
        )
    )

    feedback_dir = Path(
        os.environ.get(
            "LIUHUI_FEEDBACK_DIR",
            Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            / "feedback"
            / "liuhui-badminton-coach",
        )
    ).expanduser()
    writable_parent = nearest_existing_parent(feedback_dir)
    checks.append(
        check(
            "feedback_directory",
            os.access(writable_parent, os.W_OK),
            f"future local feedback path: {feedback_dir}",
            "Set LIUHUI_FEEDBACK_DIR to a writable private directory.",
            required=False,
        )
    )

    if run_smoke and not missing and not json_errors:
        completed = subprocess.run(
            [
                sys.executable,
                str(skill_root / "scripts" / "search_knowledge.py"),
                "网前框架",
                "--plan-only",
                "--no-local-personalization",
            ],
            cwd=skill_root,
            text=True,
            capture_output=True,
            check=False,
        )
        smoke_ok = completed.returncode == 0
        if smoke_ok:
            try:
                smoke_ok = json.loads(completed.stdout).get("query") == "网前框架"
            except json.JSONDecodeError:
                smoke_ok = False
        checks.append(
            check(
                "search_smoke_test",
                smoke_ok,
                "plan-only retrieval succeeded" if smoke_ok else (completed.stderr or completed.stdout)[-600:],
                "Run search_knowledge.py directly to inspect the reported error.",
            )
        )
        context_completed = subprocess.run(
            [
                sys.executable,
                str(skill_root / "scripts" / "prepare_answer_context.py"),
                "网前框架怎么做才不会身体僵硬",
                "--max-videos",
                "2",
                "--no-local-personalization",
            ],
            cwd=skill_root,
            text=True,
            capture_output=True,
            check=False,
        )
        context_ok = context_completed.returncode == 0
        if context_ok:
            try:
                context_payload = json.loads(context_completed.stdout)
                context_ok = bool(context_payload.get("selected_videos")) and all(
                    item.get("label", "").startswith("V")
                    for item in context_payload["selected_videos"]
                )
            except json.JSONDecodeError:
                context_ok = False
        checks.append(
            check(
                "answer_context_smoke_test",
                context_ok,
                "answer context and evidence lookup succeeded"
                if context_ok
                else (context_completed.stderr or context_completed.stdout)[-600:],
                "Run prepare_answer_context.py directly to inspect the reported error.",
            )
        )
    return checks


def command_check(command, required=True):
    path = shutil.which(command)
    return check(
        f"command_{command}",
        bool(path),
        path or "not found",
        f"Install `{command}` and make it available on PATH.",
        required=required,
    )


def resolve_transcription_python(repo_root, override=None):
    if override:
        candidate = Path(override).expanduser()
        return candidate.absolute() if candidate.is_file() else None
    if os.environ.get("LIUHUI_TRANSCRIPTION_PYTHON"):
        candidate = Path(os.environ["LIUHUI_TRANSCRIPTION_PYTHON"]).expanduser()
        return candidate.absolute() if candidate.is_file() else None
    repo_root = Path(repo_root)
    candidates = [
        repo_root / ".venv" / "bin" / "python",
        repo_root / ".venv" / "Scripts" / "python.exe",
    ]
    candidates.append(Path(sys.executable))
    # Preserve a virtualenv launcher path; resolving its symlink bypasses venv site-packages.
    return next((path.absolute() for path in candidates if path.is_file()), None)


def transcription_checks(repo_root, override=None, include_curl=True):
    repo_root = Path(repo_root).resolve()
    python_path = resolve_transcription_python(repo_root, override)
    checks = [command_check("curl")] if include_curl else []
    checks.append(
        check(
            "transcription_python",
            python_path is not None,
            str(python_path) if python_path else "not found",
            "Create .venv and install requirements-transcription.txt, or set LIUHUI_TRANSCRIPTION_PYTHON.",
        )
    )
    faster_whisper_ok = False
    if python_path:
        completed = subprocess.run(
            [
                str(python_path),
                "-c",
                "import faster_whisper; print(getattr(faster_whisper, '__version__', 'installed'))",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        checks.append(
            check(
                "faster_whisper",
                completed.returncode == 0,
                completed.stdout.strip() or completed.stderr.strip()[-600:],
                f"{python_path} -m pip install -r {repo_root / 'requirements-transcription.txt'}",
            )
        )
        faster_whisper_ok = completed.returncode == 0
        browser_completed = subprocess.run(
            [
                str(python_path),
                "scripts/download_douyin_browser_batch.py",
                "batch-doctor",
                "--preflight-only",
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        checks.append(
            check(
                "douyin_browser_download",
                browser_completed.returncode == 0,
                browser_completed.stdout.strip()
                or browser_completed.stderr.strip()[-600:],
                (
                    "Install requirements-transcription.txt and Node.js 22+, "
                    "then install Chrome/Edge or set LIUHUI_CHROME."
                ),
            )
        )
    if python_path and faster_whisper_ok:
        model_completed = subprocess.run(
            [
                str(python_path),
                "-c",
                (
                    "import sys; from faster_whisper import WhisperModel; "
                    "WhisperModel(sys.argv[1], device='cpu', compute_type='int8', "
                    "local_files_only=True); print('model ready')"
                ),
                "small",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        checks.append(
            check(
                "faster_whisper_model",
                model_completed.returncode == 0,
                model_completed.stdout.strip()
                or model_completed.stderr.strip()[-600:],
                (
                    f"Warm the model cache with {python_path} -c "
                    '"from faster_whisper import WhisperModel; '
                    "WhisperModel('small', device='cpu', compute_type='int8')\""
                ),
            )
        )
    free_gb = shutil.disk_usage(repo_root).free / (1024**3)
    checks.append(
        check(
            "free_disk_space",
            free_gb >= 8,
            f"{free_gb:.1f} GiB available",
            "Free at least 8 GiB before downloading and transcribing a batch.",
        )
    )
    return checks


def maintainer_checks(repo_root, transcription=False, override=None):
    repo_root = Path(repo_root).resolve()
    required_paths = [
        "README.md",
        "config",
        "data/knowledge/douyin_knowledge_base.json",
        "scripts/validate_project.py",
        "requirements-transcription.txt",
    ]
    missing = [path for path in required_paths if not (repo_root / path).exists()]
    checks = [
        check(
            "repository_files",
            not missing,
            "repository layout present" if not missing else "missing: " + ", ".join(missing),
            "Run this command from a complete repository checkout or pass --repo-root.",
        ),
        command_check("git"),
        command_check("curl"),
        command_check("node"),
        command_check("unzip", required=False),
    ]
    if transcription:
        checks.extend(
            transcription_checks(repo_root, override, include_curl=False)
        )
    return checks


def summarize(profile, checks):
    failures = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "profile": profile,
        "ok": not failures,
        "api_key_required": False,
        "checks": checks,
        "summary": {
            "passed": sum(item["status"] == "pass" for item in checks),
            "warnings": len(warnings),
            "failed": len(failures),
        },
    }


def main(default_profile="skill"):
    parser = argparse.ArgumentParser(
        description="Diagnose the Liu Hui badminton Skill and maintainer runtime."
    )
    parser.add_argument(
        "--profile",
        choices=["skill", "maintainer", "transcription", "all"],
        default=default_profile,
    )
    parser.add_argument("--skill-root", type=Path, default=SKILL_ROOT)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--transcription-python", type=Path)
    parser.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()

    repo_root = (args.repo_root or args.skill_root.resolve().parents[1]).resolve()
    checks = (
        []
        if args.profile == "transcription"
        else skill_checks(args.skill_root, run_smoke=not args.no_smoke)
    )
    if args.profile in {"maintainer", "all"}:
        checks.extend(
            maintainer_checks(
                repo_root,
                transcription=args.profile == "all",
                override=args.transcription_python,
            )
        )
    elif args.profile == "transcription":
        checks.extend(transcription_checks(repo_root, args.transcription_python))
    result = summarize(args.profile, checks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
