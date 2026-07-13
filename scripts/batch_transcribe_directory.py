#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]


def srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


parser = argparse.ArgumentParser()
parser.add_argument("media_dir", type=Path)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--queue", type=Path)
parser.add_argument("--model", default="small")
args = parser.parse_args()

media_dir = args.media_dir.resolve()
output_dir = args.output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=True)

files = sorted(
    file for file in media_dir.iterdir()
    if file.suffix.lower() in {".mp4", ".m4a", ".mp3", ".wav"}
)
already_done_files = [
    file for file in files
    if (output_dir / f"{file.stem}.json").exists()
]
pending = [file for file in files if file not in already_done_files]
print(json.dumps({
    "media_files": len(files),
    "already_done": len(files) - len(pending),
    "pending": len(pending),
}, ensure_ascii=False), flush=True)

queue = None
queue_items = {}
if args.queue:
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    queue_items = {item["video_id"]: item for item in queue["items"]}
    for media in already_done_files:
        if media.stem not in queue_items:
            continue
        transcript = json.loads((output_dir / f"{media.stem}.json").read_text(encoding="utf-8"))
        queue_items[media.stem]["status"] = "transcribed"
        queue_items[media.stem]["duration_seconds"] = round(transcript.get("duration", 0), 3)
        queue_items[media.stem]["error"] = None
    if already_done_files:
        counts = {}
        for item in queue["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        queue["counts"] = counts
        queue["updated_at"] = datetime.now(timezone.utc).isoformat()
        args.queue.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

model = WhisperModel(args.model, device="cpu", compute_type="int8")
for index, media in enumerate(pending, start=1):
    print(f"[{index}/{len(pending)}] transcribing {media.name}", flush=True)
    try:
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
        payload = {
            "video_id": media.stem,
            "source_file": str(media.relative_to(ROOT)),
            "model": args.model,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "segments": segments,
            "full_text": "".join(item["text"] for item in segments),
        }
        (output_dir / f"{media.stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{media.stem}.txt").write_text(
            "\n".join(
                f"[{item['start']:06.2f}-{item['end']:06.2f}] {item['text']}"
                for item in segments
            ) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{media.stem}.srt").write_text(
            "\n".join(
                f"{number}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}\n"
                for number, item in enumerate(segments, start=1)
            ),
            encoding="utf-8",
        )
        if media.stem in queue_items:
            queue_items[media.stem]["status"] = "transcribed"
            queue_items[media.stem]["duration_seconds"] = round(info.duration, 3)
            queue_items[media.stem]["error"] = None
        print(json.dumps({
            "video_id": media.stem,
            "duration": round(info.duration, 1),
            "segments": len(segments),
        }, ensure_ascii=False), flush=True)
    except Exception as error:
        if media.stem in queue_items:
            queue_items[media.stem]["status"] = "transcription_failed"
            queue_items[media.stem]["error"] = str(error)
        print(json.dumps({
            "video_id": media.stem,
            "error": str(error),
        }, ensure_ascii=False), flush=True)
    if queue is not None:
        counts = {}
        for item in queue["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        queue["counts"] = counts
        queue["updated_at"] = datetime.now(timezone.utc).isoformat()
        args.queue.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

print(json.dumps({"completed": len(pending)}, ensure_ascii=False), flush=True)
