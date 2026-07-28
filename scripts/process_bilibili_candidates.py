#!/usr/bin/env python3
"""Verify and download audio for quarantined Bilibili Liu Hui candidates."""

import argparse
import copy
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bilibili_pipeline import acquire_bilibili_pipeline_lock, may_enter_knowledge_base
from douyin_pipeline import commit_json_transaction, now_iso


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
REVIEW_PATH = ROOT / "data" / "processing" / "bilibili_origin_review_queue.json"
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
RAW_ROOT = ROOT / "data" / "raw_videos" / "bilibili"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".bilibili-media-transaction.json"
EXPECTED_UPLOADER_ID = "1423436652"
ORIGIN_PATTERN = re.compile(r"刘辉(?:教练|羽毛球)?|辉哥")
TRUSTED_ORIGIN_TAGS = {"刘辉", "刘辉羽毛球"}
MEDIA_SUFFIXES = {".m4a", ".mp3", ".webm", ".wav", ".mp4"}
MEDIA_VALIDATION_VERSION = 2
RETRYABLE_ERROR_PATTERNS = {
    "rate_limited": re.compile(r"\b(?:412|429)\b|rate.?limit|too many requests", re.I),
    "temporary_network": re.compile(
        r"timed? ?out|temporar|connection|network|http error 5\d\d|"
        r"unable to download webpage|nodename|name resolution|"
        r"did not get any data blocks|expected \d+ bytes",
        re.I,
    ),
}
AUTH_ERROR_PATTERN = re.compile(r"\b403\b|login|cookie|captcha|sign in", re.I)
UNAVAILABLE_ERROR_PATTERN = re.compile(
    r"\b404\b|not available|deleted|removed|private video", re.I
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_metadata(info, expected_bvid):
    tags = {str(tag).strip() for tag in info.get("tags") or []}
    title = str(info.get("title") or "")
    description = str(info.get("description") or "")
    duration = info.get("duration")
    canonical_url = str(info.get("webpage_url") or "")
    signals = {
        "video_id_matches": info.get("id") == expected_bvid,
        "uploader_profile_matches": str(info.get("uploader_id") or "")
        == EXPECTED_UPLOADER_ID,
        "canonical_url_matches": f"/video/{expected_bvid}" in canonical_url,
        "publisher_text_names_liuhui": bool(
            ORIGIN_PATTERN.search(f"{title} {description}")
        ),
        "dedicated_origin_tag": bool(tags & TRUSTED_ORIGIN_TAGS),
        "duration_valid": (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and 0 < duration <= 7200
        ),
    }
    verified = all(signals.values())
    return {
        "status": "verified_liuhui_clip" if verified else "verification_failed",
        "verification_tier": "publisher_declared" if verified else "unverified",
        "methods": [
            "verified_uploader_profile",
            "publisher_origin_annotation",
        ] if verified else [],
        "verified_at": now_iso(),
        "signals": signals,
        "source_metadata": {
            "uploader": str(info.get("uploader") or ""),
            "uploader_id": str(info.get("uploader_id") or ""),
            "title": title,
            "description": description,
            "tags": sorted(tags),
            "duration_seconds": round(float(duration), 3) if signals["duration_valid"] else None,
            "upload_date": str(info.get("upload_date") or ""),
        },
    }


def preserve_verification_timestamp(previous, current):
    previous = previous or {}
    previous_stable = {key: value for key, value in previous.items() if key != "verified_at"}
    current_stable = {key: value for key, value in current.items() if key != "verified_at"}
    if previous_stable == current_stable and previous.get("verified_at"):
        current["verified_at"] = previous["verified_at"]
    return current


def ydl_options(output_dir=None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "sleep_interval_requests": 2.0,
        "sleep_interval": 2.0,
        "max_sleep_interval": 6.0,
        "concurrent_fragment_downloads": 1,
        "format": (
            "bestaudio[ext=m4a][abr>=80][abr<=128]/"
            "bestaudio[ext=m4a][abr<=160]/"
            "bestaudio[abr>=80][abr<=128]/bestaudio"
        ),
    }
    if output_dir is not None:
        options.update({
            "outtmpl": str(Path(output_dir) / "%(id)s.%(ext)s"),
            "overwrites": False,
        })
    return options


def extract_metadata(url):
    from yt_dlp import YoutubeDL

    with YoutubeDL(ydl_options()) as ydl:
        return ydl.extract_info(url, download=False)


def media_fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "media_bytes": Path(path).stat().st_size,
        "media_sha256": digest.hexdigest(),
    }


def probe_media(path):
    import av

    try:
        with av.open(str(path)) as container:
            audio = next(
                (stream for stream in container.streams if stream.type == "audio"),
                None,
            )
            if audio is None:
                raise RuntimeError(
                    f"Media has no readable audio stream: {Path(path).name}"
                )
            codec_name = str(audio.codec_context.name or "")
            sample_rate = int(audio.codec_context.sample_rate or 0) or None
            container_duration = (
                float(container.duration / av.time_base)
                if container.duration is not None
                else (
                    float(audio.duration * audio.time_base)
                    if audio.duration is not None and audio.time_base is not None
                    else 0
                )
            )

            packet_count = 0
            decoded_frame_count = 0
            decoded_samples = 0
            decoded_duration = 0.0
            for packet in container.demux(audio):
                if packet.size:
                    packet_count += 1
                # Demux may emit a zero-sized flush packet. Decode it too so
                # delayed codec frames are checked instead of silently lost.
                for frame in packet.decode():
                    frame_samples = int(frame.samples or 0)
                    frame_sample_rate = int(frame.sample_rate or sample_rate or 0)
                    decoded_frame_count += 1
                    decoded_samples += frame_samples
                    if frame_samples > 0 and frame_sample_rate > 0:
                        decoded_duration += frame_samples / frame_sample_rate
    except av.error.FFmpegError as error:
        raise RuntimeError(f"Media audio decode failed: {Path(path).name}") from error

    duration = decoded_duration if decoded_duration > 0 else container_duration
    if (
        duration <= 0
        or packet_count <= 0
        or decoded_frame_count <= 0
        or decoded_samples <= 0
    ):
        raise RuntimeError(f"Media has no readable decoded audio: {Path(path).name}")
    return {
        "media_validation_version": MEDIA_VALIDATION_VERSION,
        "media_duration_seconds": round(duration, 3),
        "media_codec": codec_name,
        "media_sample_rate": sample_rate,
        "media_packet_count": packet_count,
        "media_decoded_frame_count": decoded_frame_count,
        "media_decoded_samples": decoded_samples,
    }


def inspect_media_content(path, expected_duration=None):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 4096:
        raise RuntimeError(f"Audio is missing, incomplete, or too small: {path.name}")
    probe = probe_media(path)
    if expected_duration:
        drift = abs(probe["media_duration_seconds"] - float(expected_duration))
        allowed = max(3.0, float(expected_duration) * 0.05)
        if drift > allowed:
            raise RuntimeError(
                f"Media duration differs from metadata by {drift:.1f}s: {path.name}"
            )
    return {**probe, **media_fingerprint(path)}


def validate_media(path, expected_duration=None):
    path = Path(path)
    if (
        path.suffix.lower() not in MEDIA_SUFFIXES
        or path.name.endswith(".part")
    ):
        raise RuntimeError(f"Audio is missing, incomplete, or too small: {path.name}")
    return inspect_media_content(path, expected_duration)


def media_validation_is_current(item):
    if (
        item.get("media_validation_version") != MEDIA_VALIDATION_VERSION
        or int(item.get("media_decoded_frame_count") or 0) <= 0
        or int(item.get("media_decoded_samples") or 0) <= 0
        or not item.get("media_sha256")
        or not item.get("media_path")
    ):
        return False
    path = ROOT / item["media_path"]
    try:
        fingerprint = media_fingerprint(path)
    except OSError:
        return False
    return (
        fingerprint["media_bytes"] == item.get("media_bytes")
        and fingerprint["media_sha256"] == item.get("media_sha256")
    )


def recover_quarantined_media(bvid, expected_duration=None):
    quarantine = RAW_ROOT / "quarantine"
    if not quarantine.exists():
        return None, None
    pattern = re.compile(
        rf"^{re.escape(bvid)}(?P<suffix>\.(?:m4a|mp3|webm|wav|mp4))\."
    )
    for candidate in sorted(quarantine.glob(f"{bvid}.*.invalid"), reverse=True):
        match = pattern.match(candidate.name)
        if not match:
            continue
        try:
            validation = inspect_media_content(candidate, expected_duration)
        except (OSError, RuntimeError, ValueError):
            continue
        target = RAW_ROOT / f"{bvid}{match.group('suffix')}"
        if target.exists():
            return target, validate_media(target, expected_duration)
        candidate.replace(target)
        return target, validation
    return None, None


def completed_media(bvid, expected_duration=None):
    candidates = sorted(
        path
        for path in RAW_ROOT.glob(f"{bvid}.*")
        if path.suffix.lower() in MEDIA_SUFFIXES and not path.name.endswith(".part")
    )
    invalid = []
    for path in candidates:
        try:
            return path, validate_media(path, expected_duration)
        except (OSError, RuntimeError, ValueError) as error:
            invalid.append((path, error))
    if invalid:
        quarantine = RAW_ROOT / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for path, _ in invalid:
            target = quarantine / f"{path.name}.{stamp}.invalid"
            path.replace(target)
    recovered, recovered_validation = recover_quarantined_media(
        bvid,
        expected_duration,
    )
    if recovered is not None:
        return recovered, recovered_validation
    return None, None


def download_audio(url, bvid, expected_duration=None):
    from yt_dlp import YoutubeDL

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        media, validation = completed_media(bvid, expected_duration)
        if media is not None:
            return media, validation
        with YoutubeDL(ydl_options(RAW_ROOT)) as ydl:
            ydl.download([url])
    media, validation = completed_media(bvid, expected_duration)
    if media is not None:
        return media, validation
    raise RuntimeError(
        f"Downloaded audio failed complete decode validation for {bvid}"
    )


def queue_item(record, verification, media, media_validation):
    metadata = verification["source_metadata"]
    return {
        "platform": "bilibili",
        "video_id": record["bvid"],
        "evidence_id": record["video_id"],
        "url": record["url"],
        "title": metadata["title"] or record["title"],
        "description": metadata["description"],
        "category": "",
        "tags": "；".join(metadata["tags"]),
        "status": "downloaded",
        "classification_decision": "保留：教学",
        "classification_reason": "B站发布者元数据通过刘辉教学切片来源门禁",
        "classification_rules_version": record["classification_rules_version"],
        "classification_rules_hash": record["classification_rules_hash"],
        "origin_verification": verification,
        "media_path": str(media.relative_to(ROOT)),
        **media_validation,
        "duration_seconds": metadata["duration_seconds"],
        "attempts": 0,
        "error": None,
        "error_stage": None,
        "downloaded_at": now_iso()
    }


def persist(ledger, queue):
    ledger["updated_at"] = now_iso()
    ledger["counts"] = dict(Counter(item["decision"] for item in ledger["videos"]))
    queue["updated_at"] = now_iso()
    queue["counts"] = dict(Counter(item["status"] for item in queue["items"]))
    review_items = [
        item for item in ledger["videos"]
        if item["decision"] == "candidate_liuhui_teaching"
        and not item.get("knowledge_admission_eligible")
    ]
    review = {
        "version": 1,
        "platform": "bilibili",
        "updated_at": now_iso(),
        "counts": dict(Counter(item["decision"] for item in review_items)),
        "items": review_items,
    }
    commit_json_transaction(
        {LEDGER_PATH: ledger, QUEUE_PATH: queue, REVIEW_PATH: review},
        TRANSACTION_PATH,
    )


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def retry_due(record, current_time=None):
    next_retry = parse_time(
        (record.get("processing_state") or {}).get("next_retry_at")
    )
    return next_retry is None or next_retry <= (current_time or datetime.now(timezone.utc))


def classify_error(error):
    text = str(error)
    for error_class, pattern in RETRYABLE_ERROR_PATTERNS.items():
        if pattern.search(text):
            return error_class, True
    if AUTH_ERROR_PATTERN.search(text):
        return "blocked_auth", False
    if UNAVAILABLE_ERROR_PATTERN.search(text):
        return "unavailable", False
    return "unexpected", True


def update_processing_state(
    record,
    *,
    stage,
    attempt_stage=None,
    terminal=False,
    error_class=None,
    error_message=None,
    retry_after_minutes=None,
):
    state = dict(record.get("processing_state") or {})
    attempts = dict(state.get("attempts_by_stage") or {})
    if error_class:
        attempt_key = attempt_stage or stage
        attempts[attempt_key] = int(attempts.get(attempt_key) or 0) + 1
    state.update(
        {
            "stage": stage,
            "terminal": terminal,
            "attempts_by_stage": attempts,
            "last_error_class": error_class,
            "last_error_message": (
                str(error_message)[-1200:] if error_message else None
            ),
            "last_error_at": now_iso() if error_class else None,
            "next_retry_at": (
                (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=retry_after_minutes)
                ).isoformat()
                if retry_after_minutes
                else None
            ),
        }
    )
    record["processing_state"] = state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--cooldown-minutes", type=int, default=30)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore next_retry_at for explicitly requested BVIDs",
    )
    parser.add_argument(
        "--failure-circuit-threshold",
        type=int,
        default=3,
        help="Stop after this many consecutive retryable acquisition failures",
    )
    args = parser.parse_args()
    pipeline_lock = acquire_bilibili_pipeline_lock()
    if args.max_items is not None and args.max_items <= 0:
        parser.error("--max-items must be positive")
    if args.checkpoint_every <= 0:
        parser.error("--checkpoint-every must be positive")
    if args.failure_circuit_threshold <= 0:
        parser.error("--failure-circuit-threshold must be positive")
    requested = set(args.bvid)
    ledger = load_json(LEDGER_PATH)
    queue = load_json(QUEUE_PATH)
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    candidates = [
        item for item in ledger["videos"]
        if item["decision"] == "candidate_liuhui_teaching"
        and (not requested or item["bvid"] in requested)
        and not bool((item.get("processing_state") or {}).get("terminal"))
        and (retry_due(item) or (args.force and item["bvid"] in requested))
    ]
    if args.max_items is not None:
        candidates = candidates[:args.max_items]
    results = []
    pending_changes = 0
    consecutive_retryable_failures = 0
    for record in candidates:
        bvid = record["bvid"]
        record_before = copy.deepcopy(record)
        queue_item_before = copy.deepcopy(queue_by_id.get(bvid))
        try:
            existing = queue_by_id.get(bvid)
            verification = record.get("origin_verification") or {}
            if (
                verification.get("status") != "verified_liuhui_clip"
                or not may_enter_knowledge_base(record)
            ):
                info = extract_metadata(record["url"])
                verification = preserve_verification_timestamp(
                    record.get("origin_verification"),
                    verify_metadata(info, bvid),
                )
                record["origin_verification"] = verification
                record["knowledge_admission_eligible"] = may_enter_knowledge_base(
                    record
                )
            result = {
                "bvid": bvid,
                "origin_status": verification["status"],
                "eligible": record["knowledge_admission_eligible"],
            }
            if not record["knowledge_admission_eligible"]:
                update_processing_state(
                    record,
                    stage="quarantined_origin_unknown",
                    terminal=True,
                )
                result["status"] = "quarantined_origin_unknown"
            elif existing and existing.get("status") == "transcribed":
                expected_duration = verification["source_metadata"]["duration_seconds"]
                if not existing.get("media_path"):
                    # Finalized transcripts deliberately release temporary media.
                    # Their transcript/source integrity is enforced during build.
                    existing["origin_verification"] = verification
                    update_processing_state(record, stage="transcribed", terminal=False)
                    result["status"] = "already_transcribed"
                elif media_validation_is_current(existing):
                    existing["origin_verification"] = verification
                    update_processing_state(record, stage="transcribed", terminal=False)
                    result["status"] = "already_transcribed"
                else:
                    try:
                        validation = validate_media(
                            ROOT / existing.get("media_path", ""),
                            expected_duration,
                        )
                    except (OSError, RuntimeError, ValueError):
                        media, validation = download_audio(
                            record["url"],
                            bvid,
                            expected_duration,
                        )
                        queue_by_id[bvid] = queue_item(
                            record,
                            verification,
                            media,
                            validation,
                        )
                        update_processing_state(
                            record,
                            stage="downloaded",
                            terminal=False,
                        )
                        result["status"] = "downloaded"
                        result["media_recovered"] = True
                    else:
                        existing.update(validation)
                        existing["origin_verification"] = verification
                        update_processing_state(
                            record,
                            stage="transcribed",
                            terminal=False,
                        )
                        result["status"] = "already_transcribed"
                        result["media_validation_upgraded"] = True
            elif (
                existing
                and existing.get("status") == "downloaded"
                and media_validation_is_current(existing)
            ):
                existing["origin_verification"] = verification
                update_processing_state(record, stage="downloaded", terminal=False)
                result["status"] = "already_downloaded"
            elif (
                existing
                and existing.get("status")
                in {"transcription_failed", "transcription_quarantined"}
            ):
                existing_status = existing["status"]
                expected_duration = verification["source_metadata"]["duration_seconds"]
                try:
                    validation = (
                        None
                        if media_validation_is_current(existing)
                        else validate_media(
                            ROOT / existing.get("media_path", ""),
                            expected_duration,
                        )
                    )
                except (OSError, RuntimeError, ValueError):
                    media, validation = download_audio(
                        record["url"],
                        bvid,
                        expected_duration,
                    )
                    replacement = queue_item(
                        record,
                        verification,
                        media,
                        validation,
                    )
                    replacement["transcription_attempts"] = int(
                        existing.get("transcription_attempts") or 0
                    )
                    replacement["transcription_retry_attempts"] = 0
                    replacement["media_recoveries"] = (
                        int(existing.get("media_recoveries") or 0) + 1
                    )
                    queue_by_id[bvid] = replacement
                    update_processing_state(
                        record,
                        stage="downloaded",
                        terminal=False,
                    )
                    result["status"] = "downloaded"
                    result["media_recovered"] = True
                else:
                    if validation is not None:
                        existing.update(validation)
                    existing["origin_verification"] = verification
                    update_processing_state(
                        record,
                        stage=existing_status,
                        terminal=False,
                    )
                    result["status"] = f"already_{existing_status}"
            elif args.metadata_only:
                update_processing_state(record, stage="metadata_ready", terminal=False)
                result["status"] = "metadata_ready"
            else:
                media, media_validation = download_audio(
                    record["url"],
                    bvid,
                    verification["source_metadata"]["duration_seconds"],
                )
                if existing and existing.get("status") == "transcribed":
                    existing["origin_verification"] = verification
                    result["status"] = "already_transcribed"
                else:
                    queue_by_id[bvid] = queue_item(
                        record,
                        verification,
                        media,
                        media_validation,
                    )
                    result["status"] = "downloaded"
                    result["media_bytes"] = media_validation["media_bytes"]
                    result["media_sha256"] = media_validation["media_sha256"]
                    update_processing_state(
                        record,
                        stage="downloaded",
                        terminal=False,
                    )
            results.append(result)
            consecutive_retryable_failures = 0
        except Exception as error:
            error_class, retryable = classify_error(error)
            retry_minutes = (
                args.cooldown_minutes
                if error_class == "rate_limited"
                else 12 * 60
                if error_class == "blocked_auth"
                else min(
                    60,
                    2 ** min(
                        5,
                        int(
                            (record.get("processing_state") or {})
                            .get("attempts_by_stage", {})
                            .get("acquisition", 0)
                        ),
                    ),
                )
                if retryable
                else None
            )
            stage = "unavailable" if error_class == "unavailable" else (
                "blocked_auth" if error_class == "blocked_auth" else "acquisition_failed"
            )
            update_processing_state(
                record,
                stage=stage,
                attempt_stage="acquisition",
                terminal=error_class == "unavailable",
                error_class=error_class,
                error_message=error,
                retry_after_minutes=retry_minutes,
            )
            results.append({
                "bvid": bvid,
                "status": stage,
                "retryable": retryable,
                "error_class": error_class,
                "next_retry_at": record["processing_state"]["next_retry_at"],
                "error": str(error)[-500:],
            })
            consecutive_retryable_failures = (
                consecutive_retryable_failures + 1 if retryable else 0
            )
        queue["items"] = sorted(queue_by_id.values(), key=lambda item: item["video_id"])
        if (
            record != record_before
            or queue_by_id.get(bvid) != queue_item_before
        ):
            pending_changes += 1
        if pending_changes >= args.checkpoint_every:
            persist(ledger, queue)
            pending_changes = 0
        print(
            json.dumps(
                {
                    "progress": f"{len(results)}/{len(candidates)}",
                    "result": results[-1],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if (
            results[-1].get("error_class") == "rate_limited"
            or results[-1].get("error_class") == "blocked_auth"
            or consecutive_retryable_failures
            >= args.failure_circuit_threshold
        ):
            break
    if pending_changes:
        persist(ledger, queue)
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False, indent=2))
    return (
        1
        if any(
            item.get("retryable")
            or item.get("status") in {"blocked_auth", "acquisition_failed"}
            for item in results
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
