#!/usr/bin/env python3
import json
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
MEDIA_DIR = ROOT / "data" / "raw_videos" / "douyin" / "pilot"
OUTPUT_DIR = ROOT / "data" / "transcripts" / "douyin" / "pilot"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


files = sorted(
    file for file in MEDIA_DIR.iterdir()
    if file.suffix.lower() in {".mp4", ".m4a", ".mp3", ".wav"}
)
pending = [file for file in files if not (OUTPUT_DIR / f"{file.stem}.json").exists()]
print(json.dumps({
    "media_files": len(files),
    "already_done": len(files) - len(pending),
    "pending": len(pending),
}, ensure_ascii=False), flush=True)

model = WhisperModel("small", device="cpu", compute_type="int8")
for index, media in enumerate(pending, start=1):
    print(f"[{index}/{len(pending)}] transcribing {media.name}", flush=True)
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
        "source_file": str(media),
        "model": "small",
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": segments,
        "full_text": "".join(item["text"] for item in segments),
    }
    (OUTPUT_DIR / f"{media.stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / f"{media.stem}.txt").write_text(
        "\n".join(
            f"[{item['start']:06.2f}-{item['end']:06.2f}] {item['text']}"
            for item in segments
        ) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / f"{media.stem}.srt").write_text(
        "\n".join(
            f"{number}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}\n"
            for number, item in enumerate(segments, start=1)
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "video_id": media.stem,
        "duration": round(info.duration, 1),
        "segments": len(segments),
    }, ensure_ascii=False), flush=True)

print(json.dumps({"completed": len(pending)}, ensure_ascii=False), flush=True)
