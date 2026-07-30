"""Portable, collision-safe local storage helpers for Bilibili media."""

import hashlib
import os
from pathlib import Path


MEDIA_KEY_HASH_LENGTH = 64
BILIBILI_MEDIA_CACHE_ENV = "BSC_BILIBILI_MEDIA_CACHE_DIR"
BILIBILI_TRANSCRIPT_CACHE_ENV = "BSC_BILIBILI_TRANSCRIPT_CACHE_DIR"
DEFAULT_MEDIA_CACHE_RELATIVE = Path("data") / "raw_videos" / "bilibili"
DEFAULT_TRANSCRIPT_CACHE_RELATIVE = Path("data") / "transcripts" / "bilibili"


def exact_case_hash(value, length=MEDIA_KEY_HASH_LENGTH):
    """Hash UTF-8 bytes so identifiers that differ only by case stay distinct."""

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def media_storage_key(bvid):
    """Return a stable filename stem that cannot case-fold to another BVID."""

    bvid = str(bvid)
    return f"{bvid}--{exact_case_hash(bvid)}"


def media_stem_matches_bvid(stem, bvid):
    """Accept the collision-safe stem and the exact-case legacy BVID stem."""

    return str(stem) in {media_storage_key(bvid), str(bvid)}


def lexical_absolute(path, *, root=None):
    """Normalize dot segments without resolving symlinks or changing path case."""

    path = Path(path)
    if not path.is_absolute():
        if root is None:
            raise ValueError("root is required for a relative path")
        path = Path(root) / path
    return Path(os.path.abspath(os.fspath(path)))


def bilibili_media_cache_root(project_root, override=None, *, environ=None):
    """Return the configured media cache without resolving symlinks.

    Relative paths are anchored at the project root so CLI, subprocess and CI
    invocations agree even when their current working directories differ.
    """

    environ = os.environ if environ is None else environ
    configured = override or environ.get(BILIBILI_MEDIA_CACHE_ENV)
    if configured:
        return lexical_absolute(
            Path(configured).expanduser(),
            root=project_root,
        )
    return lexical_absolute(DEFAULT_MEDIA_CACHE_RELATIVE, root=project_root)


def bilibili_transcript_cache_root(
    project_root,
    override=None,
    *,
    environ=None,
):
    """Return the preferred writable Bilibili transcript cache."""

    environ = os.environ if environ is None else environ
    configured = override or environ.get(BILIBILI_TRANSCRIPT_CACHE_ENV)
    if configured:
        return lexical_absolute(
            Path(configured).expanduser(),
            root=project_root,
        )
    return lexical_absolute(
        DEFAULT_TRANSCRIPT_CACHE_RELATIVE,
        root=project_root,
    )


def bilibili_transcript_roots(
    project_root,
    override=None,
    *,
    environ=None,
):
    """Return preferred-first transcript roots with the repository fallback."""

    preferred = bilibili_transcript_cache_root(
        project_root,
        override,
        environ=environ,
    )
    legacy = lexical_absolute(
        DEFAULT_TRANSCRIPT_CACHE_RELATIVE,
        root=project_root,
    )
    return [preferred] if preferred == legacy else [preferred, legacy]


def queue_media_locator(media, bvid, *, project_root):
    """Serialize a media path plus a cache-root-independent exact-case key."""

    media = lexical_absolute(media)
    if not media_stem_matches_bvid(media.stem, bvid):
        raise ValueError(f"Media path does not belong to exact BVID {bvid}")
    project_root = lexical_absolute(project_root)
    try:
        media_path = str(media.relative_to(project_root))
    except ValueError:
        # Keep an absolute compatibility path for older consumers. New
        # consumers relocate it with media_cache_key when the cache root moves.
        media_path = str(media)
    locator = {
        "media_path": media_path,
    }
    # Only the hashed filename is safe to relocate through a case-folding
    # filesystem. Exact-case legacy paths remain readable through media_path.
    if media.stem == media_storage_key(bvid):
        locator["media_cache_key"] = media.name
    return locator


def resolve_queue_media_path(
    item,
    expected_bvid,
    *,
    project_root,
    cache_root=None,
    prefer_existing=True,
    require_legacy_identity=True,
):
    """Resolve new portable cache keys and legacy relative/absolute paths.

    A portable key is only a filename, never an arbitrary path. Both new and
    legacy paths must carry the exact BVID (or its collision-safe hash key).
    """

    candidates = []
    cache_key = item.get("media_cache_key")
    if cache_key:
        cache_key = str(cache_key)
        key_path = Path(cache_key)
        if (
            key_path.name != cache_key
            or cache_key in {"", ".", ".."}
            or "/" in cache_key
            or "\\" in cache_key
        ):
            raise ValueError("Queued media_cache_key must be a plain filename")
        if key_path.stem != media_storage_key(expected_bvid):
            raise ValueError(
                f"Queued media cache key does not belong to exact BVID "
                f"{expected_bvid}"
            )
        effective_cache_root = (
            lexical_absolute(cache_root)
            if cache_root is not None
            else bilibili_media_cache_root(project_root)
        )
        candidates.append(effective_cache_root / key_path.name)

    media_path = item.get("media_path")
    if media_path:
        raw_legacy_path = Path(media_path)
        legacy_path = lexical_absolute(raw_legacy_path, root=project_root)
        if not raw_legacy_path.is_absolute():
            normalized_project_root = lexical_absolute(project_root)
            try:
                legacy_path.relative_to(normalized_project_root)
            except ValueError as error:
                raise ValueError(
                    "Queued relative media_path escapes the project root"
                ) from error
        if (
            require_legacy_identity
            and not media_stem_matches_bvid(legacy_path.stem, expected_bvid)
        ):
            raise ValueError(
                f"Queued media path does not belong to exact BVID "
                f"{expected_bvid}"
            )
        if legacy_path not in candidates:
            candidates.append(legacy_path)

    if not candidates:
        raise ValueError(f"Queue item for {expected_bvid} has no media locator")
    if prefer_existing:
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return candidates[0]


def find_exact_stem_files(root, stem, suffixes, *, recursive=False):
    """Find files by exact-case stem instead of filesystem case-folded lookup."""

    root = Path(root)
    if not root.exists():
        return []
    suffixes = {str(suffix).lower() for suffix in suffixes}
    paths = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        path
        for path in paths
        if path.is_file()
        and path.stem == str(stem)
        and path.suffix.lower() in suffixes
    )


def find_exact_transcript(root, video_id):
    matches = find_exact_stem_files(
        root,
        video_id,
        {".json"},
        recursive=True,
    )
    if len(matches) > 1:
        raise ValueError(
            f"Multiple transcript completion markers exist for {video_id}"
        )
    return matches[0] if matches else None


def index_exact_transcript_candidates(roots):
    """Index exact-case canonical JSON candidates in root priority order."""

    indexed = {}
    for root in roots:
        root = lexical_absolute(root)
        if not root.exists():
            continue
        current_root = {}
        for path in sorted(root.rglob("*.json")):
            if not path.is_file():
                continue
            video_id = path.stem
            if video_id in current_root:
                raise ValueError(
                    f"Multiple transcript completion markers exist for "
                    f"{video_id} under {root}"
                )
            current_root[video_id] = path
        for video_id, path in current_root.items():
            indexed.setdefault(video_id, []).append(path)
    return indexed


def first_readable_transcript(candidates):
    """Return the first canonical JSON whose bytes are locally readable."""

    for path in candidates or []:
        try:
            with Path(path).open("rb") as file:
                file.read(1)
        except OSError:
            continue
        return Path(path)
    return None


def portable_transcript_reference(path, *, project_root, cache_root=None):
    """Return a stable repository-shaped transcript reference."""

    path = lexical_absolute(path)
    project_root = lexical_absolute(project_root)
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        pass
    if cache_root is not None:
        cache_root = lexical_absolute(cache_root)
        try:
            relative = path.relative_to(cache_root)
        except ValueError:
            pass
        else:
            return str(DEFAULT_TRANSCRIPT_CACHE_RELATIVE / relative)
    return str(path)
