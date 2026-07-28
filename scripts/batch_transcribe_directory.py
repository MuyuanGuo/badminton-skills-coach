#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

from bilibili_pipeline import acquire_bilibili_pipeline_lock
from douyin_pipeline import (
    compute_status_counts,
    normalize_transcribed_media_state,
    now_iso,
    validate_queue_statuses,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}
DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS = 3


def transcription_recipe(model_name):
    return {
        "schema_version": 1,
        "engine": "faster-whisper",
        "model": model_name,
        "language": "zh",
        "beam_size": 5,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "device": "cpu",
        "compute_type": "int8",
    }


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


def prepare_forced_transcription_retry(item):
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


def relative_source(media):
    try:
        return str(media.relative_to(ROOT))
    except ValueError:
        return str(media)


def validate_media_against_queue(media, item):
    if not item:
        return
    fingerprint = media_fingerprint(media)
    expected_bytes = item.get("media_bytes")
    expected_sha256 = item.get("media_sha256")
    if expected_bytes is not None and fingerprint["source_bytes"] != expected_bytes:
        raise ValueError(f"Queued media byte count changed for {media.stem}")
    if expected_sha256 and fingerprint["source_sha256"] != expected_sha256:
        raise ValueError(f"Queued media SHA-256 changed for {media.stem}")


def payload_from_model(media, model_name, model):
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
        "video_id": media.stem,
        "source_file": relative_source(media),
        **media_fingerprint(media),
        "model": model_name,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "transcription_recipe": transcription_recipe(model_name),
        "segments": segments,
        "segment_quality_metrics": segment_quality_metrics,
        "full_text": "".join(item["text"] for item in segments),
    }


def default_model_factory(model_name):
    from faster_whisper import WhisperModel

    available_cpus = os.cpu_count() or 1
    configured_threads = os.environ.get("BSC_WHISPER_CPU_THREADS")
    cpu_threads = (
        int(configured_threads)
        if configured_threads
        else min(available_cpus, 12)
    )
    if not 1 <= cpu_threads <= available_cpus:
        raise ValueError(
            "BSC_WHISPER_CPU_THREADS must be between 1 and the available CPU count"
        )
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
        num_workers=1,
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
):
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if force and not video_ids:
        raise ValueError("force requires explicit video_ids")
    media_dir = media_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = set(video_ids or [])
    discovered_files = sorted(
        file for file in media_dir.iterdir()
        if file.suffix.lower() in MEDIA_SUFFIXES
        and (not requested or file.stem in requested)
    )

    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path else None
    queue_items = {item["video_id"]: item for item in queue["items"]} if queue else {}
    files_by_id = {}
    for media in discovered_files:
        files_by_id.setdefault(media.stem, []).append(media)
    files = []
    for video_id, candidates in sorted(files_by_id.items()):
        if len(candidates) == 1:
            files.append(candidates[0])
            continue
        configured = (
            ROOT / queue_items.get(video_id, {}).get("media_path", "")
            if queue_items.get(video_id, {}).get("media_path")
            else None
        )
        matches = [
            candidate
            for candidate in candidates
            if configured is not None and candidate.resolve() == configured.resolve()
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Multiple media files exist for {video_id}; queue media_path "
                "must select exactly one"
            )
        files.append(matches[0])
    queue_changed = False
    isolated = []
    actionable_files = []
    for media in files:
        item = queue_items.get(media.stem)
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
        if item and item.get("status") == "transcription_quarantined":
            if force and media.stem in requested:
                prepare_forced_transcription_retry(item)
                queue_changed = True
            else:
                isolated.append(media.stem)
                continue
        actionable_files.append(media)
    files = actionable_files
    media_file_count = len(files) + len(isolated)
    completed = []
    pending = []
    invalid_outputs = []
    for media in files:
        output_path = output_dir / f"{media.stem}.json"
        if not output_path.exists():
            pending.append(media)
            continue
        try:
            payload = load_valid_transcript(output_path, media.stem, media)
            # Repair missing sidecars from the canonical JSON without rerunning Whisper.
            atomic_write_text(output_dir / f"{media.stem}.txt", transcript_text(payload))
            atomic_write_text(output_dir / f"{media.stem}.srt", transcript_srt(payload))
            if media.stem in queue_items:
                queue_changed = (
                    mark_transcribed(queue_items[media.stem], payload)
                    or queue_changed
                )
            completed.append(media.stem)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            remove_transcript_outputs(output_dir, media.stem)
            invalid_outputs.append(media.stem)
            pending.append(media)

    if queue is not None and queue_changed:
        save_queue(queue_path, queue)

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
        try:
            model = model_factory(model_name)
        except Exception as error:
            failed.extend(media.stem for media in pending)
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
    batch_started = time.monotonic()
    processed_audio_seconds = 0.0
    for index, media in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] transcribing {media.name}", flush=True)
        item_started = time.monotonic()
        try:
            validate_media_against_queue(media, queue_items.get(media.stem))
            payload = payload_from_model(media, model_name, model)
            validate_media_against_queue(media, queue_items.get(media.stem))
            write_transcript_outputs(output_dir, payload)
            if media.stem in queue_items:
                mark_transcribed(queue_items[media.stem], payload)
            transcribed.append(media.stem)
            elapsed = time.monotonic() - batch_started
            item_elapsed = time.monotonic() - item_started
            processed_audio_seconds += float(payload["duration"])
            remaining_audio_seconds = sum(
                float(
                    queue_items.get(item.stem, {}).get(
                        "media_duration_seconds",
                        0,
                    )
                    or 0
                )
                for item in pending[index:]
            )
            estimated_remaining_seconds = (
                elapsed
                / processed_audio_seconds
                * remaining_audio_seconds
                if processed_audio_seconds > 0 and remaining_audio_seconds > 0
                else (elapsed / index) * max(0, len(pending) - index)
            )
            print(
                json.dumps(
                    {
                        "video_id": media.stem,
                        "duration": round(payload["duration"], 1),
                        "segments": len(payload["segments"]),
                        "wall_seconds": round(item_elapsed, 1),
                        "real_time_factor": round(
                            item_elapsed / payload["duration"], 3
                        ),
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
            remove_transcript_outputs(output_dir, media.stem)
            if media.stem in queue_items:
                terminal = mark_transcription_failed(
                    queue_items[media.stem],
                    error,
                    max_attempts=max_attempts,
                )
            else:
                terminal = False
            failed.append(media.stem)
            if terminal:
                quarantined.append(media.stem)
            else:
                retryable_failed.append(media.stem)
            print(
                json.dumps({"video_id": media.stem, "error": str(error)}, ensure_ascii=False),
                flush=True,
            )
        if queue is not None:
            save_queue(queue_path, queue)

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
        help="Recover quarantined items; requires at least one --video-id",
    )
    args = parser.parse_args()
    if args.max_attempts <= 0:
        parser.error("--max-attempts must be positive")
    if args.force and not args.video_id:
        parser.error("--force requires at least one --video-id")
    pipeline_lock = (
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
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return (
        1
        if result.get("batch_error") or result["retryable_failed_video_ids"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
