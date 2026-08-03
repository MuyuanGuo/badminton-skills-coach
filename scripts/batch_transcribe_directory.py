#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bilibili_pipeline import acquire_bilibili_pipeline_lock
from bilibili_storage import (
    index_exact_transcript_candidates,
    lexical_absolute,
    media_storage_key,
    resolve_queue_media_path,
)
from douyin_pipeline import (
    compute_status_counts,
    normalize_transcribed_media_state,
    now_iso,
    validate_queue_statuses,
    write_json,
)
from queue_wal import QueueWAL

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None


ROOT = Path(__file__).resolve().parents[1]
MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}
DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS = 3
MODEL_CONFIG_PATH = ROOT / "config" / "transcription_models.json"


def transcription_model_spec(model_name):
    config = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
    try:
        spec = config["models"][model_name]
    except (KeyError, TypeError) as error:
        raise ValueError(f"Unpinned transcription model: {model_name}") from error
    repository = str(spec.get("repository") or "")
    revision = str(spec.get("revision") or "")
    if not repository or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Invalid pinned transcription model: {model_name}")
    return {"repository": repository, "revision": revision}


def peak_resident_memory_mb():
    if resource is None:
        return 0.0
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    bytes_per_unit = 1 if sys.platform == "darwin" else 1024
    return round(maximum_rss * bytes_per_unit / (1024 * 1024), 1)


def transcription_recipe(model_name):
    spec = transcription_model_spec(model_name)
    return {
        "schema_version": 2,
        "engine": "faster-whisper",
        "model": model_name,
        "model_repository": spec["repository"],
        "model_revision": spec["revision"],
        "language": "zh",
        "beam_size": 5,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "device": "cpu",
        "compute_type": "int8",
    }


def legacy_transcription_recipe(model_name):
    """Describe the old recipe without claiming an unobserved model revision."""

    recipe = transcription_recipe(model_name)
    recipe["schema_version"] = 1
    recipe.pop("model_repository")
    recipe.pop("model_revision")
    return recipe


def srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def atomic_write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(value)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def media_fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "source_bytes": Path(path).stat().st_size,
        "source_sha256": digest.hexdigest(),
    }


def validate_transcript_payload(payload, expected_video_id, source_media=None):
    if str(payload.get("video_id") or "") != expected_video_id:
        raise ValueError("transcript video_id does not match the media filename")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("transcript segments must be a list")
    duration = payload.get("duration")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("transcript duration is invalid")
    previous_start = -1.0
    for segment in segments:
        if set(segment) != {"start", "end", "text"}:
            raise ValueError("transcript segment has unexpected fields")
        if not isinstance(segment["text"], str):
            raise ValueError("transcript segment text must be a string")
        start = segment["start"]
        end = segment["end"]
        if (
            not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or start < previous_start
            or end > duration + max(1.0, duration * 0.02)
        ):
            raise ValueError("transcript segment timestamps are invalid")
        previous_start = start
    metrics = payload.get("segment_quality_metrics")
    if metrics is not None:
        if not isinstance(metrics, list) or len(metrics) != len(segments):
            raise ValueError(
                "transcript segment_quality_metrics must align with segments"
            )
        for metric in metrics:
            if set(metric) != {
                "avg_logprob",
                "no_speech_prob",
                "compression_ratio",
            }:
                raise ValueError(
                    "transcript segment quality metric has unexpected fields"
                )
            if any(
                not isinstance(metric[key], (int, float))
                or isinstance(metric[key], bool)
                or not math.isfinite(metric[key])
                for key in metric
            ):
                raise ValueError("transcript segment quality metric is invalid")
            if not 0 <= metric["no_speech_prob"] <= 1:
                raise ValueError("transcript no_speech_prob is invalid")
    expected_text = "".join(segment["text"] for segment in segments)
    if payload.get("full_text") != expected_text:
        raise ValueError("transcript full_text does not match its segments")
    for key in ["model", "language", "language_probability", "source_file"]:
        if key not in payload:
            raise ValueError(f"transcript is missing {key}")
    probability = payload.get("language_probability")
    if (
        not isinstance(probability, (int, float))
        or isinstance(probability, bool)
        or not math.isfinite(probability)
        or not 0 <= probability <= 1
    ):
        raise ValueError("transcript language_probability is invalid")
    if not all(
        isinstance(payload.get(key), str) and payload.get(key).strip()
        for key in ["model", "language", "source_file"]
    ):
        raise ValueError("transcript model, language, and source_file must be non-empty strings")
    if source_media is not None:
        fingerprint = media_fingerprint(source_media)
        if payload.get("source_bytes") != fingerprint["source_bytes"]:
            raise ValueError("transcript source_bytes does not match the current media")
        if payload.get("source_sha256") != fingerprint["source_sha256"]:
            raise ValueError("transcript source_sha256 does not match the current media")
    return payload


def transcript_text(payload):
    return "\n".join(
        f"[{item['start']:06.2f}-{item['end']:06.2f}] {item['text']}"
        for item in payload["segments"]
    ) + "\n"


def transcript_srt(payload):
    return "\n".join(
        f"{number}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}\n"
        for number, item in enumerate(payload["segments"], start=1)
    )


def write_transcript_outputs(output_dir, payload):
    video_id = str(payload["video_id"])
    validate_transcript_payload(payload, video_id)
    atomic_write_text(output_dir / f"{video_id}.txt", transcript_text(payload))
    atomic_write_text(output_dir / f"{video_id}.srt", transcript_srt(payload))
    # The JSON file is the completion marker and is committed last.
    write_json(output_dir / f"{video_id}.json", payload)


def load_valid_transcript(path, expected_video_id, source_media=None):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_transcript_payload(payload, expected_video_id, source_media)


def remove_transcript_outputs(output_dir, video_id):
    for suffix in [".json", ".txt", ".srt"]:
        (output_dir / f"{video_id}{suffix}").unlink(missing_ok=True)


def save_queue(queue_path, queue):
    validate_queue_statuses(queue["items"])
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = now_iso()
    write_json(queue_path, queue)


def mark_transcribed(item, payload):
    values = {
        "status": "transcribed",
        "duration_seconds": round(payload.get("duration", 0), 3),
        "error": None,
        "error_stage": None,
        "transcript_model": payload["model"],
        "transcript_language": payload["language"],
        "transcript_source_sha256": payload.get("source_sha256"),
        "transcript_source_bytes": payload.get("source_bytes"),
        "transcript_text_characters": len(payload.get("full_text") or ""),
        "transcription_retry_attempts": 0,
        "transcription_retryable": False,
        "transcription_isolated_at": None,
    }
    changed = any(item.get(key) != value for key, value in values.items())
    item.update(values)
    if "transcription_recovery_required_model" in item:
        item.pop("transcription_recovery_required_model")
        changed = True
    changed = normalize_transcribed_media_state(item) or changed
    if changed:
        item["last_attempt_at"] = now_iso()
    return changed


def mark_transcription_failed(
    item,
    error,
    max_attempts=DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS,
):
    recorded_retry_attempts = item.get("transcription_retry_attempts")
    retry_attempts = int(
        recorded_retry_attempts
        if recorded_retry_attempts is not None
        else item.get("transcription_attempts") or 0
    ) + 1
    terminal = retry_attempts >= max_attempts
    item["status"] = (
        "transcription_quarantined" if terminal else "transcription_failed"
    )
    item["attempts"] = int(item.get("attempts") or 0) + 1
    item["transcription_attempts"] = int(item.get("transcription_attempts") or 0) + 1
    item["transcription_retry_attempts"] = retry_attempts
    item["transcription_retryable"] = not terminal
    item["error"] = str(error)[-1200:]
    item["error_stage"] = "transcription"
    item["last_attempt_at"] = now_iso()
    item["transcription_isolated_at"] = now_iso() if terminal else None
    return terminal


def quarantine_exhausted_transcription(item):
    item["status"] = "transcription_quarantined"
    item["transcription_retryable"] = False
    item["transcription_retry_attempts"] = int(
        item.get("transcription_retry_attempts")
        if item.get("transcription_retry_attempts") is not None
        else item.get("transcription_attempts") or 0
    )
    if not item.get("transcription_isolated_at"):
        item["transcription_isolated_at"] = now_iso()


def prepare_forced_transcription_retry(item, model_name=None):
    item["status"] = "downloaded"
    item["transcription_retry_attempts"] = 0
    item["transcription_retryable"] = True
    item["transcription_isolated_at"] = None
    item["transcription_force_recoveries"] = (
        int(item.get("transcription_force_recoveries") or 0) + 1
    )
    item["last_force_recovery_at"] = now_iso()
    item["error"] = None
    item["error_stage"] = None
    if model_name:
        item["transcription_recovery_required_model"] = model_name


def relative_source(media, cache_root=None):
    try:
        return str(media.relative_to(ROOT))
    except ValueError:
        pass
    if cache_root is not None:
        try:
            return str(
                Path("bilibili-media-cache")
                / media.relative_to(cache_root)
            )
        except ValueError:
            pass
    return str(media)


def validate_media_against_queue(media, item, fingerprint=None):
    if not item:
        return
    fingerprint = fingerprint or media_fingerprint(media)
    expected_bytes = item.get("media_bytes")
    expected_sha256 = item.get("media_sha256")
    if expected_bytes is not None and fingerprint["source_bytes"] != expected_bytes:
        raise ValueError(f"Queued media byte count changed for {media.stem}")
    if expected_sha256 and fingerprint["source_sha256"] != expected_sha256:
        raise ValueError(f"Queued media SHA-256 changed for {media.stem}")


def payload_from_model(
    media,
    model_name,
    model,
    *,
    source_fingerprint=None,
    video_id=None,
    source_cache_root=None,
):
    segments_iter, info = model.transcribe(
        str(media),
        language="zh",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    segments = []
    segment_quality_metrics = []
    for segment in segments_iter:
        text = segment.text.strip()
        if not text:
            continue
        segments.append(
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": text,
            }
        )
        segment_quality_metrics.append(
            {
                "avg_logprob": round(float(getattr(segment, "avg_logprob", -1.0)), 5),
                "no_speech_prob": round(
                    float(getattr(segment, "no_speech_prob", 0.0)),
                    5,
                ),
                "compression_ratio": round(
                    float(getattr(segment, "compression_ratio", 1.0)),
                    5,
                ),
            }
        )
    return {
        "video_id": str(video_id or media.stem),
        "source_file": relative_source(media, source_cache_root),
        **(source_fingerprint or media_fingerprint(media)),
        "model": model_name,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "transcription_recipe": transcription_recipe(model_name),
        "segments": segments,
        "segment_quality_metrics": segment_quality_metrics,
        "full_text": "".join(item["text"] for item in segments),
    }


def schedule_pending_media(pending, queue_items, video_ids_by_media=None):
    """Start the longest known jobs first to minimize the parallel tail."""

    video_ids_by_media = video_ids_by_media or {}
    return sorted(
        pending,
        key=lambda media: (
            -float(
                queue_items.get(video_ids_by_media.get(media, media.stem), {}).get(
                    "media_duration_seconds",
                    0,
                )
                or 0
            ),
            media.name,
        ),
    )


def exact_path_match(first, second):
    first = lexical_absolute(first)
    second = lexical_absolute(second)
    if first == second:
        return True
    return (
        first.name == second.name
        and first.exists()
        and second.exists()
        and first.samefile(second)
    )


def resolve_media_files(
    discovered_files,
    queue_items,
    requested=None,
    *,
    cache_root=None,
):
    """Map media to exact video IDs, preferring queue.media_path over basenames."""

    requested = set(requested or [])
    configured_paths = {}
    configured_paths_by_name = {}
    aliases = {}
    for video_id, item in queue_items.items():
        media_path = item.get("media_path")
        if media_path or item.get("media_cache_key"):
            configured = resolve_queue_media_path(
                item,
                video_id,
                project_root=ROOT,
                cache_root=cache_root,
                require_legacy_identity=False,
            )
            configured_paths.setdefault(configured, []).append(video_id)
            configured_paths_by_name.setdefault(configured.name, []).append(
                (configured, video_id)
            )
        for alias in (str(video_id), media_storage_key(video_id)):
            aliases.setdefault(alias, []).append(video_id)

    candidates_by_id = {}
    for media in discovered_files:
        media_absolute = lexical_absolute(media)
        exact_matches = configured_paths.get(media_absolute, [])
        if not exact_matches:
            exact_matches = [
                video_id
                for configured, video_id in configured_paths_by_name.get(
                    media_absolute.name,
                    [],
                )
                if exact_path_match(configured, media_absolute)
            ]
        alias_matches = aliases.get(media.stem, [])
        matches = exact_matches or alias_matches
        if len(matches) > 1:
            raise ValueError(
                f"Media path {media} maps to multiple queue video IDs: "
                f"{', '.join(sorted(matches))}"
            )
        video_id = matches[0] if matches else media.stem
        if requested and video_id not in requested:
            continue
        candidates_by_id.setdefault(video_id, []).append(media)

    files = []
    video_ids_by_media = {}
    for video_id, candidates in sorted(candidates_by_id.items()):
        if len(candidates) == 1:
            selected = candidates[0]
        else:
            item = queue_items.get(video_id) or {}
            configured = (
                resolve_queue_media_path(
                    item,
                    video_id,
                    project_root=ROOT,
                    cache_root=cache_root,
                    require_legacy_identity=False,
                )
                if item.get("media_path") or item.get("media_cache_key")
                else None
            )
            matches = [
                candidate
                for candidate in candidates
                if configured is not None
                and exact_path_match(candidate, configured)
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Multiple media files exist for {video_id}; queue media_path "
                    "must select exactly one"
                )
            selected = matches[0]
        files.append(selected)
        video_ids_by_media[selected] = video_id
    return files, video_ids_by_media


def discover_media_files(media_dir, queue_items):
    """Discover the active cache plus existing legacy/absolute queue targets."""

    discovered = [
        file
        for file in media_dir.iterdir()
        if file.is_file() and file.suffix.lower() in MEDIA_SUFFIXES
    ]
    for video_id, item in queue_items.items():
        if not (item.get("media_path") or item.get("media_cache_key")):
            continue
        configured = resolve_queue_media_path(
            item,
            video_id,
            project_root=ROOT,
            cache_root=media_dir,
            require_legacy_identity=False,
        )
        if (
            configured.is_file()
            and configured.suffix.lower() in MEDIA_SUFFIXES
            and not any(
                exact_path_match(configured, existing)
                for existing in discovered
            )
        ):
            discovered.append(configured)
    return sorted(discovered)


def transcript_directories(output_dir, video_ids):
    """Keep legacy flat outputs, isolating only case-folding filename collisions."""

    output_dir = Path(output_dir)
    video_ids = set(video_ids)
    groups = {}
    for video_id in video_ids:
        groups.setdefault(video_id.casefold(), []).append(video_id)
    exact_flat_names = {
        path.name
        for path in output_dir.iterdir()
        if path.is_file()
    }
    directories = {}
    for group in groups.values():
        collision = len(group) > 1
        for video_id in group:
            has_exact_flat_completion = f"{video_id}.json" in exact_flat_names
            directories[video_id] = (
                output_dir
                if not collision or has_exact_flat_completion
                else output_dir / media_storage_key(video_id)
            )
    return directories


def default_model_factory(model_name):
    from faster_whisper import WhisperModel

    spec = transcription_model_spec(model_name)

    available_cpus = os.cpu_count() or 1
    configured_workers = os.environ.get("BSC_WHISPER_WORKERS")
    workers = int(configured_workers) if configured_workers else 1
    if not 1 <= workers <= min(4, available_cpus):
        raise ValueError(
            "BSC_WHISPER_WORKERS must be between 1 and 4 and no greater "
            "than the available CPU count"
        )
    configured_threads = os.environ.get("BSC_WHISPER_CPU_THREADS")
    cpu_threads = (
        int(configured_threads)
        if configured_threads
        else max(1, min(available_cpus, 12) // workers)
    )
    if not 1 <= cpu_threads or cpu_threads * workers > available_cpus:
        raise ValueError(
            "BSC_WHISPER_CPU_THREADS multiplied by BSC_WHISPER_WORKERS "
            "must not exceed the available CPU count"
        )
    return WhisperModel(
        spec["repository"],
        revision=spec["revision"],
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
        num_workers=workers,
    )


def transcribe_directory(
    media_dir,
    output_dir,
    *,
    queue_path=None,
    model_name="small",
    model_factory=default_model_factory,
    video_ids=None,
    max_attempts=DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS,
    force=False,
    fallback_output_dirs=None,
):
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if force and not video_ids:
        raise ValueError("force requires explicit video_ids")
    media_dir = media_dir.resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = set(video_ids or [])
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path else None
    queue_wal = QueueWAL(queue_path) if queue is not None else None
    if queue_wal is not None and queue_wal.replay(queue):
        save_queue(queue_path, queue)
        queue_wal.clear()
    queue_items = {item["video_id"]: item for item in queue["items"]} if queue else {}
    discovered_files = discover_media_files(media_dir, queue_items)
    files, video_ids_by_media = resolve_media_files(
        discovered_files,
        queue_items,
        requested,
        cache_root=media_dir,
    )
    output_dirs_by_video_id = transcript_directories(
        output_dir,
        set(queue_items) | set(video_ids_by_media.values()),
    )
    primary_transcripts = index_exact_transcript_candidates([output_dir])
    fallback_transcripts = index_exact_transcript_candidates(
        [
            path
            for path in (fallback_output_dirs or [])
            if lexical_absolute(path) != lexical_absolute(output_dir)
        ]
    )
    queue_changed = False
    isolated = []
    actionable_files = []
    for media in files:
        video_id = video_ids_by_media[media]
        item = queue_items.get(video_id)
        forced_recovery = force and video_id in requested
        if (
            item
            and item.get("status") == "transcription_failed"
            and int(
                item.get("transcription_retry_attempts")
                if item.get("transcription_retry_attempts") is not None
                else item.get("transcription_attempts") or 0
            )
            >= max_attempts
        ):
            quarantine_exhausted_transcription(item)
            queue_changed = True
        if item and forced_recovery:
            if item.get("status") != "downloaded":
                prepare_forced_transcription_retry(item, model_name=model_name)
            else:
                item["transcription_recovery_required_model"] = model_name
            queue_changed = True
        if item and item.get("status") == "transcription_quarantined":
            if not forced_recovery:
                isolated.append(video_id)
                continue
        actionable_files.append(media)
    files = actionable_files
    media_file_count = len(files) + len(isolated)
    completed = []
    pending = []
    invalid_outputs = []
    for media in files:
        video_id = video_ids_by_media[media]
        target_dir = output_dirs_by_video_id[video_id]
        if force and video_id in requested:
            pending.append(media)
            continue
        transcript_candidates = [
            *primary_transcripts.get(video_id, []),
            *fallback_transcripts.get(video_id, []),
        ]
        if not transcript_candidates:
            pending.append(media)
            continue
        payload = None
        source_path = None
        for candidate_index, candidate in enumerate(transcript_candidates):
            try:
                payload = load_valid_transcript(candidate, video_id, media)
            except OSError:
                # An evicted preferred-cache file may still look like a file
                # to the filesystem. Try the repository compatibility copy.
                continue
            except (ValueError, TypeError, json.JSONDecodeError):
                if candidate_index < len(
                    primary_transcripts.get(video_id, [])
                ):
                    remove_transcript_outputs(candidate.parent, video_id)
                invalid_outputs.append(video_id)
                payload = None
                break
            source_path = candidate
            break
        if payload is None:
            pending.append(media)
            continue
        required_model = (
            queue_items.get(video_id) or {}
        ).get("transcription_recovery_required_model")
        if required_model and payload.get("model") != required_model:
            pending.append(media)
            continue
        try:
            transcript_dir = source_path.parent
            if source_path not in primary_transcripts.get(video_id, []):
                # Migrate a readable repository completion marker into the
                # external cache without rerunning Whisper or touching source.
                write_transcript_outputs(target_dir, payload)
                transcript_dir = target_dir
            # Repair missing sidecars from the canonical JSON without rerunning Whisper.
            atomic_write_text(
                transcript_dir / f"{video_id}.txt",
                transcript_text(payload),
            )
            atomic_write_text(
                transcript_dir / f"{video_id}.srt",
                transcript_srt(payload),
            )
            if video_id in queue_items:
                queue_changed = (
                    mark_transcribed(queue_items[video_id], payload)
                    or queue_changed
                )
            completed.append(video_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            if source_path in primary_transcripts.get(video_id, []):
                remove_transcript_outputs(source_path.parent, video_id)
            invalid_outputs.append(video_id)
            pending.append(media)

    if queue is not None and queue_changed:
        save_queue(queue_path, queue)
        queue_wal.clear()

    print(
        json.dumps(
            {
                "media_files": media_file_count,
                "already_done": len(completed),
                "invalid_outputs_removed": invalid_outputs,
                "pending": len(pending),
                "isolated_video_ids": isolated,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    failed = []
    model = None
    if pending:
        conflicting_models = sorted(
            {
                str(queue_items.get(video_ids_by_media[media], {}).get(
                    "transcription_recovery_required_model"
                ))
                for media in pending
                if queue_items.get(video_ids_by_media[media], {}).get(
                    "transcription_recovery_required_model"
                )
                and queue_items.get(video_ids_by_media[media], {}).get(
                    "transcription_recovery_required_model"
                ) != model_name
            }
        )
        if conflicting_models:
            raise ValueError(
                "Pending recovery requires model(s) "
                + ", ".join(conflicting_models)
                + f"; current model is {model_name}"
            )
        try:
            model = model_factory(model_name)
        except Exception as error:
            failed.extend(video_ids_by_media[media] for media in pending)
            return {
                "media_files": media_file_count,
                "already_done": len(completed),
                "invalid_outputs_removed": invalid_outputs,
                "attempted": 0,
                "transcribed": 0,
                "failed_video_ids": failed,
                "retryable_failed_video_ids": failed,
                "quarantined_video_ids": isolated,
                "batch_error": str(error)[-1200:],
            }

    transcribed = []
    retryable_failed = []
    quarantined = list(isolated)
    pending = schedule_pending_media(pending, queue_items, video_ids_by_media)
    batch_started = time.monotonic()
    processed_audio_seconds = 0.0
    remaining_audio_seconds = sum(
        float(
            queue_items.get(video_ids_by_media[media], {}).get(
                "media_duration_seconds",
                0,
            )
            or 0
        )
        for media in pending
    )
    configured_workers = os.environ.get("BSC_WHISPER_WORKERS")
    workers = int(configured_workers) if configured_workers else 1

    def transcribe_one(media):
        video_id = video_ids_by_media[media]
        transcript_dir = output_dirs_by_video_id[video_id]
        item_started = time.monotonic()
        required_model = (
            queue_items.get(video_id) or {}
        ).get("transcription_recovery_required_model")
        if required_model and model_name != required_model:
            raise ValueError(
                f"Recovery for {video_id} requires model {required_model}"
            )
        source_fingerprint = media_fingerprint(media)
        validate_media_against_queue(
            media,
            queue_items.get(video_id),
            source_fingerprint,
        )
        payload = payload_from_model(
            media,
            model_name,
            model,
            source_fingerprint=source_fingerprint,
            video_id=video_id,
            source_cache_root=media_dir,
        )
        final_fingerprint = media_fingerprint(media)
        if final_fingerprint != source_fingerprint:
            raise ValueError(f"Media changed while transcribing {video_id}")
        validate_media_against_queue(
            media,
            queue_items.get(video_id),
            final_fingerprint,
        )
        # Persist each completed transcript in its worker. If the coordinator is
        # interrupted before updating the queue, the next run can reconcile the
        # atomic JSON completion marker without rerunning Whisper.
        write_transcript_outputs(transcript_dir, payload)
        return payload, time.monotonic() - item_started

    print(
        json.dumps(
            {
                "transcription_workers": workers,
                "cpu_threads_per_worker": (
                    int(os.environ["BSC_WHISPER_CPU_THREADS"])
                    if os.environ.get("BSC_WHISPER_CPU_THREADS")
                    else max(1, min(os.cpu_count() or 1, 12) // workers)
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {}
    pending_iterator = iter(enumerate(pending, start=1))

    def submit_next():
        try:
            index, media = next(pending_iterator)
        except StopIteration:
            return False
        print(
            f"[{index}/{len(pending)}] queued {media.name}",
            flush=True,
        )
        futures[executor.submit(transcribe_one, media)] = media
        return True

    try:
        for _ in range(min(workers, len(pending))):
            submit_next()
        completed_count = 0
        while futures:
            # Keep at most one in-flight item per CTranslate2 worker. Besides
            # bounding memory, this lets an interrupt cancel all work that has
            # not started and wait only for the currently decoding items.
            future = next(as_completed(tuple(futures)))
            media = futures.pop(future)
            video_id = video_ids_by_media[media]
            completed_count += 1
            expected_duration = float(
                queue_items.get(video_id, {}).get(
                    "media_duration_seconds",
                    0,
                )
                or 0
            )
            try:
                payload, item_elapsed = future.result()
                if video_id in queue_items:
                    mark_transcribed(queue_items[video_id], payload)
                    queue_wal.record(queue_items[video_id])
                transcribed.append(video_id)
                elapsed = time.monotonic() - batch_started
                processed_audio_seconds += float(payload["duration"])
                remaining_audio_seconds = max(
                    0.0,
                    remaining_audio_seconds
                    - (expected_duration or float(payload["duration"])),
                )
                estimated_remaining_seconds = (
                    elapsed
                    / processed_audio_seconds
                    * remaining_audio_seconds
                    if processed_audio_seconds > 0
                    and remaining_audio_seconds > 0
                    else (elapsed / completed_count)
                    * max(0, len(pending) - completed_count)
                )
                print(
                    json.dumps(
                        {
                            "video_id": video_id,
                            "duration": round(payload["duration"], 1),
                            "segments": len(payload["segments"]),
                            "wall_seconds": round(item_elapsed, 1),
                            "real_time_factor": round(
                                item_elapsed / payload["duration"], 3
                            ),
                            "aggregate_real_time_factor": round(
                                elapsed / processed_audio_seconds,
                                3,
                            ),
                            "peak_resident_memory_mb": peak_resident_memory_mb(),
                            "estimated_remaining_minutes": round(
                                estimated_remaining_seconds / 60,
                                1,
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as error:
                remaining_audio_seconds = max(
                    0.0,
                    remaining_audio_seconds - expected_duration,
                )
                remove_transcript_outputs(
                    output_dirs_by_video_id[video_id],
                    video_id,
                )
                if video_id in queue_items:
                    terminal = mark_transcription_failed(
                        queue_items[video_id],
                        error,
                        max_attempts=max_attempts,
                    )
                    queue_wal.record(queue_items[video_id])
                else:
                    terminal = False
                failed.append(video_id)
                if terminal:
                    quarantined.append(video_id)
                else:
                    retryable_failed.append(video_id)
                print(
                    json.dumps(
                        {"video_id": video_id, "error": str(error)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if queue is not None and queue_wal.should_checkpoint():
                save_queue(queue_path, queue)
                queue_wal.clear()
            submit_next()
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    if queue is not None and queue_wal.pending_events:
        save_queue(queue_path, queue)
        queue_wal.clear()

    return {
        "media_files": media_file_count,
        "already_done": len(completed),
        "invalid_outputs_removed": invalid_outputs,
        "attempted": len(pending),
        "transcribed": len(transcribed),
        "failed_video_ids": failed,
        "retryable_failed_video_ids": retryable_failed,
        "quarantined_video_ids": quarantined,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("media_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--fallback-output-dir",
        type=Path,
        action="append",
        default=[],
        help=(
            "Read-only compatibility transcript root used when the preferred "
            "output cache has no locally readable canonical JSON"
        ),
    )
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rerun ASR for explicit video IDs even when a valid transcript "
            "already exists"
        ),
    )
    args = parser.parse_args()
    if args.max_attempts <= 0:
        parser.error("--max-attempts must be positive")
    if args.force and not args.video_id:
        parser.error("--force requires at least one --video-id")
    _pipeline_lock = (
        acquire_bilibili_pipeline_lock()
        if args.queue
        and args.queue.resolve()
        == (ROOT / "data" / "processing" / "bilibili_queue.json").resolve()
        else None
    )

    result = transcribe_directory(
        args.media_dir,
        args.output_dir,
        queue_path=args.queue,
        model_name=args.model,
        video_ids=args.video_id,
        max_attempts=args.max_attempts,
        force=args.force,
        fallback_output_dirs=args.fallback_output_dir,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return (
        1
        if result.get("batch_error") or result["retryable_failed_video_ids"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
