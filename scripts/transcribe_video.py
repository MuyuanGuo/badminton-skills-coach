#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


parser = argparse.ArgumentParser()
parser.add_argument("video", type=Path)
parser.add_argument("--model", default="small")
parser.add_argument("--output-dir", type=Path, default=Path("data/transcripts/douyin/pilot"))
args = parser.parse_args()

args.output_dir.mkdir(parents=True, exist_ok=True)
model = WhisperModel(args.model, device="cpu", compute_type="int8")
segments_iter, info = model.transcribe(
    str(args.video),
    language="zh",
    beam_size=5,
    vad_filter=True,
    condition_on_previous_text=True,
    word_timestamps=False,
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

stem = args.video.stem
payload = {
    "video_id": stem,
    "source_file": str(args.video),
    "model": args.model,
    "language": info.language,
    "language_probability": info.language_probability,
    "duration": info.duration,
    "segments": segments,
    "full_text": "".join(item["text"] for item in segments),
}
(args.output_dir / f"{stem}.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
(args.output_dir / f"{stem}.txt").write_text(
    "\n".join(
        f"[{item['start']:06.2f}-{item['end']:06.2f}] {item['text']}"
        for item in segments
    ) + "\n",
    encoding="utf-8",
)
(args.output_dir / f"{stem}.srt").write_text(
    "\n".join(
        f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}\n"
        for index, item in enumerate(segments, start=1)
    ),
    encoding="utf-8",
)
print(json.dumps({
    "video_id": stem,
    "segments": len(segments),
    "duration": info.duration,
    "language_probability": info.language_probability,
    "output_dir": str(args.output_dir),
}, ensure_ascii=False))
