"""Public/private boundary and shadow-artifact audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from v3.build import validate_manifest
from v3.canonical import read_json
from v3.inventory import validate_source_inventory
from v3.publication import assert_no_private_leaks, validate_publication
from v3.runtime import runtime_metadata


def audit_shadow_artifacts(
    publication_path: Path,
    manifest_path: Path,
    runtime_path: Path | None = None,
) -> dict[str, Any]:
    publication = read_json(publication_path)
    counts = validate_publication(publication)
    source_inventory = read_json(publication_path.parent / "source-inventory.json")
    inventory_counts = validate_source_inventory(source_inventory)
    manifest = read_json(manifest_path)
    validate_manifest(manifest, publication, source_inventory)
    assert_no_private_leaks(manifest)
    result: dict[str, Any] = {
        "publication": "valid",
        "manifest": "valid",
        "row_counts": counts,
        "source_inventory": inventory_counts,
        "private_leaks": 0,
    }
    if runtime_path is not None:
        metadata = runtime_metadata(runtime_path)
        if metadata.get("publication_fingerprint") != publication.get(
            "publication_fingerprint"
        ):
            raise ValueError("runtime was built from another publication")
        if metadata.get("runtime_fingerprint") != manifest.get("runtime_fingerprint"):
            raise ValueError("runtime fingerprint differs from build manifest")
        result["runtime"] = "valid"
    return result


def audit_public_v3_tree(root: Path) -> dict[str, int]:
    """Reject obvious private artifacts accidentally placed in public v3 paths."""

    allowed_suffixes = {".json", ".sql"}
    scanned = 0
    for relative in ("schemas/v3", "config/v3", "data/v3"):
        directory = root / relative
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            if path.suffix.casefold() not in allowed_suffixes:
                raise ValueError(f"unexpected public v3 artifact type: {path}")
            if path.suffix.casefold() == ".json" and relative != "schemas/v3":
                assert_no_private_leaks(read_json(path))
            scanned += 1
    return {"files_scanned": scanned, "private_leaks": 0}
