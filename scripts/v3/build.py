"""Build and audit deterministic v3 shadow artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import atomic_write_json, read_json, sha256_json
from v3.inventory import validate_source_inventory
from v3.publication import validate_publication
from v3.runtime import build_runtime, runtime_metadata


def build_manifest(
    publication: dict[str, Any],
    runtime_result: dict[str, Any],
    source_inventory: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "builder": "scripts/v3/build.py",
        "mode": "shadow",
        "publication_path": "data/v3/publication.json",
        "publication_id": publication["publication_id"],
        "publication_fingerprint": publication["publication_fingerprint"],
        "source_inventory_path": "data/v3/source-inventory.json",
        "source_inventory_fingerprint": source_inventory["inventory_fingerprint"],
        "source_inventory_sources": source_inventory["summary"][
            "answer_eligible_sources"
        ],
        "runtime_schema": "schemas/v3/runtime.sql",
        "runtime_fingerprint": runtime_result["runtime_fingerprint"],
        "row_counts": runtime_result["row_counts"],
        "stable_v2_behavior": "unchanged",
        "switch_eligible": False,
    }
    result = dict(body)
    result["manifest_fingerprint"] = sha256_json(body)
    return result


def validate_manifest(
    manifest: dict[str, Any],
    publication: dict[str, Any],
    source_inventory: dict[str, Any],
) -> None:
    fingerprint = manifest.get("manifest_fingerprint")
    body = {
        key: value for key, value in manifest.items() if key != "manifest_fingerprint"
    }
    if fingerprint != sha256_json(body):
        raise ValueError("v3 build manifest fingerprint mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("v3 build manifest schema mismatch")
    if manifest.get("publication_fingerprint") != publication.get(
        "publication_fingerprint"
    ):
        raise ValueError("v3 build manifest references another publication")
    if manifest.get("source_inventory_fingerprint") != source_inventory.get(
        "inventory_fingerprint"
    ):
        raise ValueError("v3 build manifest references another source inventory")
    if manifest.get("source_inventory_sources") != source_inventory.get(
        "summary", {}
    ).get("answer_eligible_sources"):
        raise ValueError("v3 build manifest source count mismatch")
    if manifest.get("stable_v2_behavior") != "unchanged":
        raise ValueError("M1/M2 shadow build must not change stable v2 behavior")
    if manifest.get("switch_eligible") is not False:
        raise ValueError("M1/M2 shadow build cannot be switch eligible")


def build_shadow_artifacts(
    publication_path: Path,
    runtime_path: Path,
    manifest_path: Path,
    source_inventory_path: Path | None = None,
) -> dict[str, Any]:
    publication = read_json(publication_path)
    validate_publication(publication)
    source_inventory = read_json(
        source_inventory_path or publication_path.parent / "source-inventory.json"
    )
    validate_source_inventory(source_inventory)
    runtime_result = build_runtime(publication, runtime_path)
    manifest = build_manifest(publication, runtime_result, source_inventory)
    validate_manifest(manifest, publication, source_inventory)
    atomic_write_json(manifest_path, manifest, indent=2)
    metadata = runtime_metadata(runtime_path)
    if metadata.get("runtime_fingerprint") != manifest["runtime_fingerprint"]:
        raise ValueError("built runtime does not match its public manifest")
    return manifest
