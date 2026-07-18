#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
from pathlib import Path

from douyin_pipeline import compute_status_counts, now_iso, validate_queue_statuses, write_json


ROOT = Path(__file__).resolve().parents[1]
MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".wav"}


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


def validate_transcript_payload(payload, expected_video_id):
    if str(payload.get("video_id") or "") != expected_video_id:
        raise ValueError("transcript video_id does not match the media filename")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("transcript segments must be a list")
    for segment in segments:
        if set(segment) != {"start", "end", "text"}:
            raise ValueError("transcript segment has unexpected fields")
        if not isinstance(segment["text"], str):
            raise ValueError("transcript segment text must be a string")
        if segment["start"] < 0 or segment["end"] < segment["start"]:
            raise ValueError("transcript segment timestamps are invalid")
    expected_text = "".join(segment["text"] for segment in segments)
    if payload.get("full_text") != expected_text:
        raise ValueError("transcript full_text does not match its segments")
    if not isinstance(payload.get("duration"), (int, float)) or payload["duration"] < 0:
        raise ValueError("transcript duration is invalid")
    for key in ["model", "language", "language_probability", "source_file"]:
        if key not in payload:
            raise ValueError(f"transcript is missing {key}")
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


def load_valid_transcript(path, expected_video_id):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_transcript_payload(payload, expected_video_id)


def remove_transcript_outputs(output_dir, video_id):
    for suffix in [".json", ".txt", ".srt"]:
        (output_dir / f"{video_id}{suffix}").unlink(missing_ok=True)


def save_queue(queue_path, queue):
    validate_queue_statuses(queue["items"])
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = now_iso()
    write_json(queue_path, queue)


def mark_transcribed(item, payload):
    item["status"] = "transcribed"
    item["duration_seconds"] = round(payload.get("duration", 0), 3)
    item["error"] = None
    item["error_stage"] = None
    item["last_attempt_at"] = now_iso()


def mark_transcription_failed(item, error):
    item["status"] = "transcription_failed"
    item["attempts"] = int(item.get("attempts") or 0) + 1
    item["transcription_attempts"] = int(item.get("transcription_attempts") or 0) + 1
    item["error"] = str(error)[-1200:]
    item["error_stage"] = "transcription"
    item["last_attempt_at"] = now_iso()


def relative_source(media):
    try:
        return str(media.relative_to(ROOT))
    except ValueError:
        return str(media)


def payload_from_model(media, model_name, model):
    segments_iter, info = model.transcribe(
        str(media),
        language="zh",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    segments = [
        {
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
        }
        for segment in segments_iter
        if segment.text.strip()
    ]
    return {
        "video_id": media.stem,
        "source_file": relative_source(media),
        "model": model_name,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": segments,
        "full_text": "".join(item["text"] for item in segments),
    }


def default_model_factory(model_name):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_directory(
    media_dir,
    output_dir,
    *,
    queue_path=None,
    model_name="small",
    model_factory=default_model_factory,
):
    media_dir = media_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(file for file in media_dir.iterdir() if file.suffix.lower() in MEDIA_SUFFIXES)

    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path else None
    queue_items = {item["video_id"]: item for item in queue["items"]} if queue else {}
    completed = []
    pending = []
    invalid_outputs = []
    for media in files:
        output_path = output_dir / f"{media.stem}.json"
        if not output_path.exists():
            pending.append(media)
            continue
        try:
            payload = load_valid_transcript(output_path, media.stem)
            # Repair missing sidecars from the canonical JSON without rerunning Whisper.
            atomic_write_text(output_dir / f"{media.stem}.txt", transcript_text(payload))
            atomic_write_text(output_dir / f"{media.stem}.srt", transcript_srt(payload))
            if media.stem in queue_items:
                mark_transcribed(queue_items[media.stem], payload)
            completed.append(media.stem)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            remove_transcript_outputs(output_dir, media.stem)
            invalid_outputs.append(media.stem)
            pending.append(media)

    if queue is not None and completed:
        save_queue(queue_path, queue)

    print(
        json.dumps(
            {
                "media_files": len(files),
                "already_done": len(completed),
                "invalid_outputs_removed": invalid_outputs,
                "pending": len(pending),
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
            for media in pending:
                if media.stem in queue_items:
                    mark_transcription_failed(queue_items[media.stem], error)
                failed.append(media.stem)
            if queue is not None:
                save_queue(queue_path, queue)
            return {
                "media_files": len(files),
                "already_done": len(completed),
                "attempted": 0,
                "transcribed": 0,
                "failed_video_ids": failed,
            }

    transcribed = []
    for index, media in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] transcribing {media.name}", flush=True)
        try:
            payload = payload_from_model(media, model_name, model)
            write_transcript_outputs(output_dir, payload)
            if media.stem in queue_items:
                mark_transcribed(queue_items[media.stem], payload)
            transcribed.append(media.stem)
            print(
                json.dumps(
                    {
                        "video_id": media.stem,
                        "duration": round(payload["duration"], 1),
                        "segments": len(payload["segments"]),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as error:
            remove_transcript_outputs(output_dir, media.stem)
            if media.stem in queue_items:
                mark_transcription_failed(queue_items[media.stem], error)
            failed.append(media.stem)
            print(
                json.dumps({"video_id": media.stem, "error": str(error)}, ensure_ascii=False),
                flush=True,
            )
        if queue is not None:
            save_queue(queue_path, queue)

    return {
        "media_files": len(files),
        "already_done": len(completed),
        "attempted": len(pending),
        "transcribed": len(transcribed),
        "failed_video_ids": failed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("media_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--model", default="small")
    args = parser.parse_args()

    result = transcribe_directory(
        args.media_dir,
        args.output_dir,
        queue_path=args.queue,
        model_name=args.model,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if result["failed_video_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
