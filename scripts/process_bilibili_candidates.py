#!/usr/bin/env python3
"""Verify and download audio for quarantined Bilibili Liu Hui candidates."""

import argparse
import copy
import hashlib
import json
import os
import re
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bilibili_pipeline import (
    acquire_bilibili_pipeline_lock,
    may_enter_knowledge_base,
    stabilize_updated_at,
)
from bilibili_storage import (
    BILIBILI_MEDIA_CACHE_ENV,
    bilibili_media_cache_root,
    lexical_absolute,
    media_storage_key,
    media_stem_matches_bvid,
    queue_media_locator,
    resolve_queue_media_path,
)
from douyin_pipeline import commit_json_transaction, now_iso


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
REVIEW_PATH = ROOT / "data" / "processing" / "bilibili_origin_review_queue.json"
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
RAW_ROOT = bilibili_media_cache_root(ROOT)
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


def verify_metadata(
    info,
    expected_bvid,
    decision="candidate_liuhui_teaching",
    policy_basis=None,
):
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
    required_policy = decision == "required_transcription_policy"
    policy_contract = {
        "collection": {
            "status": "verified_collection_policy",
            "tier": "user_confirmed_collection_policy",
            "method": "user_confirmed_collection_policy",
        },
        "video_override": {
            "status": "verified_video_policy",
            "tier": "user_confirmed_video_policy",
            "method": "user_confirmed_video_policy",
        },
    }.get(policy_basis)
    if required_policy and policy_contract is None:
        raise ValueError("Required transcription policy is missing its basis")
    required_signals = {
        "video_id_matches",
        "uploader_profile_matches",
        "canonical_url_matches",
        "duration_valid",
    }
    verified = all(
        value
        for name, value in signals.items()
            if not required_policy or name in required_signals
    )
    return {
        "status": (
            policy_contract["status"]
            if verified and required_policy
            else "verified_liuhui_clip"
            if verified
            else "verification_failed"
        ),
        "verification_tier": (
            policy_contract["tier"]
            if verified and required_policy
            else "publisher_declared"
            if verified
            else "unverified"
        ),
        "methods": (
            [
                "verified_uploader_profile",
                policy_contract["method"],
            ]
            if verified and required_policy
            else [
                "verified_uploader_profile",
                "publisher_origin_annotation",
            ]
            if verified
            else []
        ),
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


def promote_existing_collection_verification(record):
    verification = copy.deepcopy(record.get("origin_verification") or {})
    signals = verification.get("signals") or {}
    required = {
        "video_id_matches",
        "uploader_profile_matches",
        "canonical_url_matches",
        "duration_valid",
    }
    if (
        record.get("decision") != "required_transcription_policy"
        or (record.get("collection_policy") or {}).get("basis")
        != "collection"
        or not verification.get("source_metadata")
        or not all(signals.get(name) is True for name in required)
    ):
        return None
    verification.update({
        "status": "verified_collection_policy",
        "verification_tier": "user_confirmed_collection_policy",
        "methods": [
            "verified_uploader_profile",
            "user_confirmed_collection_policy",
        ],
        "verified_at": now_iso(),
    })
    return verification


def preserve_verification_timestamp(previous, current):
    previous = previous or {}
    previous_stable = {key: value for key, value in previous.items() if key != "verified_at"}
    current_stable = {key: value for key, value in current.items() if key != "verified_at"}
    if previous_stable == current_stable and previous.get("verified_at"):
        current["verified_at"] = previous["verified_at"]
    return current


def ydl_options(output_dir=None, *, output_stem=None):
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
        if not output_stem:
            raise ValueError("output_stem is required when downloading media")
        options.update({
            "outtmpl": str(Path(output_dir) / f"{output_stem}.%(ext)s"),
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


def queued_media_path(item, expected_bvid):
    return resolve_queue_media_path(
        item,
        expected_bvid,
        project_root=ROOT,
        cache_root=RAW_ROOT,
    )


def path_is_within(path, root):
    try:
        lexical_absolute(path).relative_to(lexical_absolute(root))
    except (TypeError, ValueError):
        return False
    return True


def recovered_queue_item(
    record,
    verification,
    media,
    validation,
    previous,
    *,
    reason,
    forced,
):
    """Replace media while retaining ASR failure history and recovery audit."""

    replacement = queue_item(
        record,
        verification,
        media,
        validation,
    )
    replacement["attempts"] = int(previous.get("attempts") or 0)
    replacement["transcription_attempts"] = int(
        previous.get("transcription_attempts") or 0
    )
    replacement["transcription_retry_attempts"] = 0
    replacement["transcription_retryable"] = True
    replacement["transcription_isolated_at"] = None
    replacement["media_recoveries"] = (
        int(previous.get("media_recoveries") or 0) + 1
    )
    if forced:
        replacement["transcription_force_recoveries"] = (
            int(previous.get("transcription_force_recoveries") or 0) + 1
        )
    audit = list(previous.get("media_recovery_audit") or [])
    audit.append({
        "recovered_at": now_iso(),
        "reason": reason,
        "forced": bool(forced),
        "previous_status": previous.get("status"),
        "previous_media_path": previous.get("media_path"),
        "previous_media_cache_key": previous.get("media_cache_key"),
        "previous_media_sha256": previous.get("media_sha256"),
        "transcription_attempts": int(
            previous.get("transcription_attempts") or 0
        ),
        "transcription_retry_attempts": int(
            previous.get("transcription_retry_attempts") or 0
        ),
    })
    replacement["media_recovery_audit"] = audit
    return replacement


def media_validation_is_current(item, expected_bvid=None):
    if (
        item.get("media_validation_version") != MEDIA_VALIDATION_VERSION
        or int(item.get("media_decoded_frame_count") or 0) <= 0
        or int(item.get("media_decoded_samples") or 0) <= 0
        or not item.get("media_sha256")
        or not (item.get("media_path") or item.get("media_cache_key"))
    ):
        return False
    try:
        path = (
            queued_media_path(item, expected_bvid)
            if expected_bvid is not None
            else resolve_queue_media_path(
                item,
                item.get("video_id"),
                project_root=ROOT,
                cache_root=RAW_ROOT,
            )
        )
    except ValueError:
        return False
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
    accepted_stems = [media_storage_key(bvid), str(bvid)]
    pattern = re.compile(
        rf"^(?P<stem>{'|'.join(re.escape(stem) for stem in accepted_stems)})"
        r"(?P<suffix>\.(?:m4a|mp3|webm|wav|mp4))\."
    )
    candidates = sorted(
        (
            path
            for path in quarantine.iterdir()
            if path.is_file() and path.name.endswith(".invalid")
        ),
        reverse=True,
    )
    for candidate in candidates:
        match = pattern.match(candidate.name)
        if not match:
            continue
        try:
            validation = inspect_media_content(candidate, expected_duration)
        except (OSError, RuntimeError, ValueError):
            continue
        target = RAW_ROOT / f"{media_storage_key(bvid)}{match.group('suffix')}"
        if target.exists():
            return target, validate_media(target, expected_duration)
        candidate.replace(target)
        return target, validation
    return None, None


def completed_media(bvid, expected_duration=None):
    preferred_stems = [media_storage_key(bvid), str(bvid)]
    preference = {stem: position for position, stem in enumerate(preferred_stems)}
    candidates = sorted(
        (
            path
            for path in RAW_ROOT.iterdir()
            if path.is_file()
            and path.suffix.lower() in MEDIA_SUFFIXES
            and not path.name.endswith(".part")
            and media_stem_matches_bvid(path.stem, bvid)
        ),
        key=lambda path: (preference[path.stem], path.name),
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


def download_audio(url, bvid, expected_duration=None, metadata_info=None):
    from yt_dlp import YoutubeDL

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    output_stem = media_storage_key(bvid)
    if metadata_info is not None:
        media, validation = completed_media(bvid, expected_duration)
        if media is not None:
            return media, validation
        try:
            with YoutubeDL(
                ydl_options(RAW_ROOT, output_stem=output_stem)
            ) as ydl:
                ydl.process_ie_result(
                    copy.deepcopy(metadata_info),
                    download=True,
                )
        except Exception:
            # The regular URL path below is the compatibility fallback for
            # extractor versions that cannot replay a processed info dict.
            pass
        media, validation = completed_media(bvid, expected_duration)
        if media is not None:
            return media, validation
    for _ in range(3):
        media, validation = completed_media(bvid, expected_duration)
        if media is not None:
            return media, validation
        with YoutubeDL(ydl_options(RAW_ROOT, output_stem=output_stem)) as ydl:
            ydl.download([url])
    media, validation = completed_media(bvid, expected_duration)
    if media is not None:
        return media, validation
    raise RuntimeError(
        f"Downloaded audio failed complete decode validation for {bvid}"
    )


def queue_item(record, verification, media, media_validation):
    metadata = verification["source_metadata"]
    policy_basis = (record.get("collection_policy") or {}).get("basis")
    required_policy = record["decision"] == "required_transcription_policy"
    policy_label = (
        "用户确认合集"
        if policy_basis == "collection"
        else "用户逐条确认"
    )
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
        "classification_decision": (
            f"保留：{policy_label}"
            if required_policy
            else "保留：教学"
        ),
        "classification_reason": (
            f"{policy_label}该B站视频必须转写并进入知识存储"
            if required_policy
            else "B站发布者元数据通过刘辉教学切片来源门禁"
        ),
        "classification_rules_version": record["classification_rules_version"],
        "classification_rules_hash": record["classification_rules_hash"],
        "origin_verification": verification,
        **queue_media_locator(
            media,
            record["bvid"],
            project_root=ROOT,
        ),
        **media_validation,
        "duration_seconds": metadata["duration_seconds"],
        "attempts": 0,
        "error": None,
        "error_stage": None,
        "downloaded_at": now_iso()
    }


def sync_queue_classification(item, record, verification):
    policy_basis = (record.get("collection_policy") or {}).get("basis")
    required_policy = record["decision"] == "required_transcription_policy"
    policy_label = (
        "用户确认合集"
        if policy_basis == "collection"
        else "用户逐条确认"
    )
    item.update({
        "classification_decision": (
            f"保留：{policy_label}"
            if required_policy
            else "保留：教学"
        ),
        "classification_reason": (
            f"{policy_label}该B站视频必须转写并进入知识存储"
            if required_policy
            else "B站发布者元数据通过刘辉教学切片来源门禁"
        ),
        "classification_rules_version": record.get(
            "classification_rules_version",
            item.get("classification_rules_version"),
        ),
        "classification_rules_hash": record.get(
            "classification_rules_hash",
            item.get("classification_rules_hash"),
        ),
        "origin_verification": verification,
    })


def persist(ledger, queue):
    current_ledger = load_json(LEDGER_PATH)
    current_queue = load_json(QUEUE_PATH)
    current_review = load_json(REVIEW_PATH) if REVIEW_PATH.exists() else {}
    changed_at = now_iso()
    ledger["counts"] = dict(Counter(item["decision"] for item in ledger["videos"]))
    queue["counts"] = dict(Counter(item["status"] for item in queue["items"]))
    review_items = [
        item for item in ledger["videos"]
        if item["decision"] in {
            "candidate_liuhui_teaching",
            "review_pending",
        }
        and not item.get("knowledge_admission_eligible")
    ]
    review = {
        "version": 1,
        "platform": "bilibili",
        "updated_at": changed_at,
        "counts": dict(Counter(item["decision"] for item in review_items)),
        "items": review_items,
    }
    ledger = stabilize_updated_at(current_ledger, ledger, changed_at)
    queue = stabilize_updated_at(current_queue, queue, changed_at)
    review = stabilize_updated_at(current_review, review, changed_at)
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


def process_candidate(
    record,
    existing,
    *,
    metadata_only,
    cooldown_minutes,
    force_reacquire=False,
):
    """Acquire one candidate without mutating the shared ledger or queue.

    ``record`` and ``existing`` must be worker-owned copies.  The caller is
    responsible for merging the returned values and persisting them from one
    thread only.
    """
    bvid = record["bvid"]
    try:
        verification = record.get("origin_verification") or {}
        metadata_info = None
        if not may_enter_knowledge_base(record):
            promoted = promote_existing_collection_verification(record)
            if promoted is not None:
                verification = promoted
                record["origin_verification"] = verification
                record["knowledge_admission_eligible"] = may_enter_knowledge_base(
                    record
                )
        if not may_enter_knowledge_base(record):
            info = extract_metadata(record["url"])
            metadata_info = info
            verification = preserve_verification_timestamp(
                record.get("origin_verification"),
                verify_metadata(
                    info,
                    bvid,
                    record["decision"],
                    (record.get("collection_policy") or {}).get("basis"),
                ),
            )
            record["origin_verification"] = verification
            record["knowledge_admission_eligible"] = may_enter_knowledge_base(record)
        result = {
            "bvid": bvid,
            "origin_status": verification["status"],
            "eligible": record["knowledge_admission_eligible"],
        }
        if not record["knowledge_admission_eligible"]:
            update_processing_state(
                record,
                stage=(
                    "metadata_verification_failed"
                    if record["decision"] == "required_transcription_policy"
                    else "quarantined_origin_unknown"
                ),
                terminal=record["decision"] != "required_transcription_policy",
            )
            result["status"] = record["processing_state"]["stage"]
        elif existing and existing.get("status") == "transcribed":
            expected_duration = verification["source_metadata"]["duration_seconds"]
            sync_queue_classification(existing, record, verification)
            if not existing.get("media_path"):
                # Finalized transcripts deliberately release temporary media.
                # Their transcript/source integrity is enforced during build.
                existing["origin_verification"] = verification
                update_processing_state(record, stage="transcribed", terminal=False)
                result["status"] = "already_transcribed"
            elif media_validation_is_current(existing, bvid):
                existing["origin_verification"] = verification
                update_processing_state(record, stage="transcribed", terminal=False)
                result["status"] = "already_transcribed"
            else:
                try:
                    validation = validate_media(
                        queued_media_path(existing, bvid),
                        expected_duration,
                    )
                except (OSError, RuntimeError, ValueError):
                    media, validation = download_audio(
                        record["url"],
                        bvid,
                        expected_duration,
                    )
                    existing = queue_item(
                        record,
                        verification,
                        media,
                        validation,
                    )
                    update_processing_state(record, stage="downloaded", terminal=False)
                    result["status"] = "downloaded"
                    result["media_recovered"] = True
                else:
                    existing.update(validation)
                    existing["origin_verification"] = verification
                    update_processing_state(record, stage="transcribed", terminal=False)
                    result["status"] = "already_transcribed"
                    result["media_validation_upgraded"] = True
        elif (
            existing
            and existing.get("status") == "downloaded"
            and media_validation_is_current(existing, bvid)
        ):
            sync_queue_classification(existing, record, verification)
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
                current_path = queued_media_path(existing, bvid)
            except ValueError:
                current_path = None
            relocation_required = (
                force_reacquire
                and (
                    current_path is None
                    or not path_is_within(current_path, RAW_ROOT)
                )
            )
            try:
                media_current = (
                    False
                    if relocation_required or current_path is None
                    else media_validation_is_current(existing, bvid)
                )
                if relocation_required:
                    raise RuntimeError(
                        "Explicit recovery requested relocation into the "
                        "configured external media cache"
                    )
                if current_path is None:
                    raise ValueError("Failed queue item has no usable media path")
                if force_reacquire and not media_current:
                    raise RuntimeError(
                        "Explicit recovery requested reacquisition after media "
                        "integrity validation failed"
                    )
                validation = (
                    None
                    if media_current
                    else validate_media(current_path, expected_duration)
                )
            except (OSError, RuntimeError, ValueError):
                media, validation = download_audio(
                    record["url"],
                    bvid,
                    expected_duration,
                )
                replacement = recovered_queue_item(
                    record,
                    verification,
                    media,
                    validation,
                    existing,
                    reason=(
                        "external_cache_relocation"
                        if relocation_required
                        else "forced_media_integrity_reacquisition"
                        if force_reacquire
                        else "media_missing_unreadable_or_hash_mismatch"
                    ),
                    forced=force_reacquire,
                )
                existing = replacement
                update_processing_state(record, stage="downloaded", terminal=False)
                result["status"] = "downloaded"
                result["media_recovered"] = True
            else:
                if validation is not None:
                    existing.update(validation)
                sync_queue_classification(existing, record, verification)
                update_processing_state(
                    record,
                    stage=existing_status,
                    terminal=False,
                )
                result["status"] = f"already_{existing_status}"
        elif metadata_only:
            update_processing_state(record, stage="metadata_ready", terminal=False)
            result["status"] = "metadata_ready"
        else:
            media, media_validation = download_audio(
                record["url"],
                bvid,
                verification["source_metadata"]["duration_seconds"],
                metadata_info=metadata_info,
            )
            if existing and existing.get("status") == "transcribed":
                sync_queue_classification(existing, record, verification)
                result["status"] = "already_transcribed"
            else:
                existing = queue_item(
                    record,
                    verification,
                    media,
                    media_validation,
                )
                result["status"] = "downloaded"
                result["media_bytes"] = media_validation["media_bytes"]
                result["media_sha256"] = media_validation["media_sha256"]
                update_processing_state(record, stage="downloaded", terminal=False)
        return {"record": record, "queue_item": existing, "result": result}
    except Exception as error:
        error_class, retryable = classify_error(error)
        retry_minutes = (
            cooldown_minutes
            if error_class == "rate_limited"
            else 12 * 60
            if error_class == "blocked_auth"
            else min(
                60,
                2
                ** min(
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
        stage = (
            "unavailable"
            if error_class == "unavailable"
            else "blocked_auth"
            if error_class == "blocked_auth"
            else "acquisition_failed"
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
        return {
            "record": record,
            "queue_item": existing,
            "result": {
                "bvid": bvid,
                "status": stage,
                "retryable": retryable,
                "error_class": error_class,
                "next_retry_at": record["processing_state"]["next_retry_at"],
                "error": str(error)[-500:],
            },
        }


def main():
    global RAW_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument(
        "--existing-queue-only",
        action="store_true",
        help="Reconcile policy metadata only for records already in the queue",
    )
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
    parser.add_argument(
        "--download-workers",
        type=int,
        choices=range(1, 5),
        default=int(os.environ.get("BSC_BILIBILI_DOWNLOAD_WORKERS", "2")),
        metavar="{1,2,3,4}",
        help=(
            "Bounded concurrent acquisition workers (default: "
            "BSC_BILIBILI_DOWNLOAD_WORKERS or 2; use 1 for diagnostics)"
        ),
    )
    parser.add_argument(
        "--media-cache-dir",
        type=Path,
        help=(
            "Local Bilibili media cache outside synchronized Documents storage "
            f"(default: {BILIBILI_MEDIA_CACHE_ENV} or data/raw_videos/bilibili)"
        ),
    )
    args = parser.parse_args()
    RAW_ROOT = bilibili_media_cache_root(
        ROOT,
        override=args.media_cache_dir,
    )
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
    excluded_ids = {
        item["bvid"]
        for item in ledger["videos"]
        if item["decision"] == "excluded_transcription_policy"
    }
    queue_by_id = {
        item["video_id"]: item
        for item in queue["items"]
        if item["video_id"] not in excluded_ids
    }
    queue_changed = len(queue_by_id) != len(queue["items"])
    queue["items"] = sorted(
        queue_by_id.values(),
        key=lambda item: item["video_id"],
    )
    candidates = [
        item for item in ledger["videos"]
        if item["decision"] in {
            "candidate_liuhui_teaching",
            "required_transcription_policy",
        }
        and (not requested or item["bvid"] in requested)
        and (
            not args.existing_queue_only
            or item["bvid"] in queue_by_id
        )
        and (
            args.existing_queue_only
            or (queue_by_id.get(item["bvid"]) or {}).get("status")
            != "transcribed"
        )
        and not bool((item.get("processing_state") or {}).get("terminal"))
        and (retry_due(item) or (args.force and item["bvid"] in requested))
    ]
    candidate_ids = [item["bvid"] for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RuntimeError(
            "Candidate ledger contains duplicate BVIDs; refusing concurrent acquisition"
        )
    if args.max_items is not None:
        candidates = candidates[:args.max_items]
    results = []
    pending_changes = int(queue_changed)
    consecutive_retryable_failures = 0
    candidate_iterator = iter(enumerate(candidates))
    in_flight = {}
    circuit_open = False

    def submit_next(executor):
        try:
            index, record = next(candidate_iterator)
        except StopIteration:
            return False
        bvid = record["bvid"]
        future = executor.submit(
            process_candidate,
            copy.deepcopy(record),
            copy.deepcopy(queue_by_id.get(bvid)),
            metadata_only=args.metadata_only,
            cooldown_minutes=args.cooldown_minutes,
            force_reacquire=args.force and bvid in requested,
        )
        in_flight[future] = {
            "index": index,
            "record": record,
            "record_before": copy.deepcopy(record),
            "queue_item_before": copy.deepcopy(queue_by_id.get(bvid)),
        }
        return True

    with ThreadPoolExecutor(
        max_workers=args.download_workers,
        thread_name_prefix="bilibili-acquire",
    ) as executor:
        while len(in_flight) < args.download_workers and submit_next(executor):
            pass
        while in_flight:
            completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in sorted(
                completed,
                key=lambda item: in_flight[item]["index"],
            ):
                context = in_flight.pop(future)
                outcome = future.result()
                record = context["record"]
                bvid = record["bvid"]
                record.clear()
                record.update(outcome["record"])
                if outcome["queue_item"] is not None:
                    queue_by_id[bvid] = outcome["queue_item"]
                result = outcome["result"]
                results.append(result)
                if result.get("retryable"):
                    consecutive_retryable_failures += 1
                else:
                    consecutive_retryable_failures = 0
                if (
                    result.get("error_class") in {"rate_limited", "blocked_auth"}
                    or consecutive_retryable_failures
                    >= args.failure_circuit_threshold
                ):
                    circuit_open = True

                queue["items"] = sorted(
                    queue_by_id.values(),
                    key=lambda item: item["video_id"],
                )
                if (
                    record != context["record_before"]
                    or queue_by_id.get(bvid) != context["queue_item_before"]
                ):
                    pending_changes += 1
                if pending_changes >= args.checkpoint_every:
                    persist(ledger, queue)
                    pending_changes = 0
                print(
                    json.dumps(
                        {
                            "progress": f"{len(results)}/{len(candidates)}",
                            "result": result,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if not circuit_open:
                while (
                    len(in_flight) < args.download_workers
                    and submit_next(executor)
                ):
                    pass
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
