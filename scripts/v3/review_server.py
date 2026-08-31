"""Loopback-only review application and hardened stdlib HTTP server."""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from v3.canonical import content_id, read_json, sha256_file
from v3.ledger import ReviewLedger, current_dependencies
from v3.publication import export_publication
from v3.transcript import (
    candidate_event_payload,
    compile_formal_transcript,
    evidence_window,
    validate_candidate,
    verification_payload,
)


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "review-ui" / "v3"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class ReviewApplication:
    def __init__(
        self,
        *,
        candidate_path: Path,
        ledger_path: Path,
        media_path: Path,
        media_root: Path | None = None,
    ):
        self.candidate_path = candidate_path.resolve()
        self.ledger_path = ledger_path.resolve()
        self.media_path = media_path.resolve()
        self.media_root = (media_root or media_path.parent).resolve()
        if not self.media_path.is_relative_to(self.media_root):
            raise ValueError("review media must stay inside the configured media root")
        if not self.media_path.is_file():
            raise ValueError(f"review media is missing: {self.media_path}")
        self.candidate = read_json(self.candidate_path)
        validate_candidate(self.candidate)
        if sha256_file(self.media_path) != self.candidate["media"]["sha256"]:
            raise ValueError("review media fingerprint differs from the candidate")
        self.transcript_id = self.candidate["candidate_id"]
        with ReviewLedger(self.ledger_path) as ledger:
            head = ledger.head("transcript", self.transcript_id)
            if head is None or head["state"] not in {
                "candidate",
                "in_review",
                "source_verified",
                "stale",
                "rejected",
            }:
                raise ValueError("candidate must be registered in the review ledger")
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)

    def summary(self) -> dict[str, Any]:
        with ReviewLedger(self.ledger_path) as ledger:
            heads = ledger.heads()
            events = ledger.events()
            draft = ledger.load_draft("transcript", self.transcript_id)
            ledger_report = ledger.verify_integrity()
        return {
            "candidate": self.candidate,
            "transcript_entity_id": self.transcript_id,
            "media_available": True,
            "csrf_token": self.csrf_token,
            "heads": heads,
            "events": events,
            "transcript_draft": draft,
            "ledger": ledger_report,
            "evidence_notice": (
                "候选和草稿不是回答证据；只有完整走过人工门禁的 published "
                "主张才会进入 shadow publication。"
            ),
        }

    def save_draft(self, body: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(body.get("entity_type") or "")
        entity_id = str(body.get("entity_id") or "")
        base_revision = body.get("base_revision")
        draft = body.get("draft")
        if not isinstance(base_revision, int) or not isinstance(draft, dict):
            raise ValueError("draft requires base_revision and a draft object")
        with ReviewLedger(self.ledger_path) as ledger:
            return ledger.save_draft(
                entity_type, entity_id, base_revision, draft
            )

    def begin_transcript_review(self, body: dict[str, Any]) -> dict[str, Any]:
        with ReviewLedger(self.ledger_path) as ledger:
            head = ledger.head("transcript", self.transcript_id)
            if head is None:
                raise ValueError("transcript candidate is missing")
            event = ledger.append_event(
                entity_type="transcript",
                entity_id=self.transcript_id,
                action="begin_review",
                reviewer_id=str(body.get("reviewer_id") or ""),
                human_confirmation=body.get("human_confirmation") is True,
                payload=candidate_event_payload(self.candidate),
                expected_revision=int(body.get("expected_revision", -1)),
                expected_base_fingerprint=str(
                    body.get("expected_base_fingerprint") or ""
                ),
                note=str(body.get("note") or ""),
            )
            return {"event": event, "head": ledger.head("transcript", self.transcript_id)}

    def preview_transcript(self, body: dict[str, Any]) -> dict[str, Any]:
        decisions = body.get("decisions")
        insertions = body.get("insertions", [])
        if not isinstance(decisions, list) or not isinstance(insertions, list):
            raise ValueError("transcript preview requires decisions and insertions")
        return compile_formal_transcript(self.candidate, decisions, insertions)

    def verify_transcript(self, body: dict[str, Any]) -> dict[str, Any]:
        compiled = self.preview_transcript(body)
        attestation = body.get("attestation")
        if not isinstance(attestation, dict):
            raise ValueError("transcript verification requires an attestation")
        payload = verification_payload(compiled, attestation)
        with ReviewLedger(self.ledger_path) as ledger:
            event = ledger.append_event(
                entity_type="transcript",
                entity_id=self.transcript_id,
                action="source_verify",
                reviewer_id=str(body.get("reviewer_id") or ""),
                human_confirmation=body.get("human_confirmation") is True,
                payload=payload,
                expected_revision=int(body.get("expected_revision", -1)),
                expected_base_fingerprint=str(
                    body.get("expected_base_fingerprint") or ""
                ),
                note=str(body.get("note") or ""),
            )
            return {
                "event": event,
                "head": ledger.head("transcript", self.transcript_id),
                "compiled": compiled,
            }

    def _transcript_head(self, ledger: ReviewLedger) -> dict[str, Any]:
        head = ledger.head("transcript", self.transcript_id)
        if head is None or head["state"] != "source_verified":
            raise ValueError("teaching events require a current source-verified transcript")
        return head

    def _teaching_event_payload(
        self, ledger: ReviewLedger, content_input: dict[str, Any]
    ) -> dict[str, Any]:
        transcript_head = self._transcript_head(ledger)
        formal = transcript_head["payload"]["content"]
        segment_ids = content_input.get("segment_ids", [])
        if not isinstance(segment_ids, list):
            raise ValueError("teaching event segment_ids must be a list")
        modality = content_input.get("modality")
        if modality in {"language", "multimodal"}:
            window = evidence_window(formal, segment_ids)
        else:
            window = {"segment_ids": [], "text": ""}
        window["visual_observation"] = str(
            content_input.get("visual_observation") or ""
        ).strip()
        content = {
            "source_id": self.candidate["source"]["source_id"],
            "source": self.candidate["source"],
            "start_ms": content_input.get("start_ms"),
            "end_ms": content_input.get("end_ms"),
            "modality": modality,
            "evidence_boundary": str(
                content_input.get("evidence_boundary") or ""
            ).strip(),
            "formal_projection_sha256": formal["formal_projection_sha256"],
            "evidence_window": window,
            "viewing_value": str(content_input.get("viewing_value") or "").strip(),
            "watch_focus": str(content_input.get("watch_focus") or "").strip(),
        }
        return {
            "content": content,
            "dependencies": current_dependencies(
                ledger, [("transcript", self.transcript_id)]
            ),
        }

    @staticmethod
    def _claim_payload(
        ledger: ReviewLedger, content_input: dict[str, Any]
    ) -> dict[str, Any]:
        support_ids = content_input.get("support_event_ids")
        if not isinstance(support_ids, list):
            raise ValueError("claim support_event_ids must be a list")
        content = {
            "topic": str(content_input.get("topic") or "").strip(),
            "symptoms": content_input.get("symptoms"),
            "applicability": content_input.get("applicability"),
            "mechanism": str(content_input.get("mechanism") or "").strip(),
            "correction_direction": str(
                content_input.get("correction_direction") or ""
            ).strip(),
            "exclusions": content_input.get("exclusions"),
            "confidence": content_input.get("confidence"),
            "training_method": str(
                content_input.get("training_method") or ""
            ).strip(),
            "support_event_ids": support_ids,
            "aliases": content_input.get("aliases", []),
        }
        return {
            "content": content,
            "dependencies": current_dependencies(
                ledger,
                [("teaching_event", event_id) for event_id in support_ids],
            ),
        }

    def transition_entity(self, body: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(body.get("entity_type") or "")
        action = str(body.get("action") or "")
        if entity_type not in {"teaching_event", "semantic_claim"}:
            raise ValueError("workbench transition supports events and claims only")
        content_input = body.get("content")
        if not isinstance(content_input, dict):
            raise ValueError("transition requires a content object")
        with ReviewLedger(self.ledger_path) as ledger:
            supplied_id = str(body.get("entity_id") or "").strip()
            if entity_type == "teaching_event":
                payload = self._teaching_event_payload(ledger, content_input)
                generated_id = content_id(
                    "event",
                    {
                        "source_id": payload["content"]["source_id"],
                        "start_ms": payload["content"]["start_ms"],
                        "end_ms": payload["content"]["end_ms"],
                        "formal_projection_sha256": payload["content"][
                            "formal_projection_sha256"
                        ],
                    },
                )
            else:
                generated_id = content_id(
                    "claim",
                    {
                        "topic": content_input.get("topic"),
                        "semantic_key": content_input.get("semantic_key"),
                    },
                )
                entity_id_for_head = supplied_id or generated_id
                current = ledger.head(entity_type, entity_id_for_head)
                if action in {"domain_approve", "publish", "withdraw", "reject"}:
                    if current is None:
                        raise ValueError("formal claim transition requires an existing claim")
                    payload = current["payload"]
                else:
                    payload = self._claim_payload(ledger, content_input)
            entity_id = supplied_id or generated_id
            current = ledger.head(entity_type, entity_id)
            machine_action = action == "create_draft"
            event = ledger.append_event(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                reviewer_id=(
                    "system:review-workbench"
                    if machine_action
                    else str(body.get("reviewer_id") or "")
                ),
                human_confirmation=(
                    False if machine_action else body.get("human_confirmation") is True
                ),
                payload=payload,
                expected_revision=int(body.get("expected_revision", -1)),
                expected_base_fingerprint=str(
                    body.get("expected_base_fingerprint") or ""
                ),
                note=str(body.get("note") or ""),
            )
            return {"event": event, "head": ledger.head(entity_type, entity_id)}

    def publication_preview(self) -> dict[str, Any]:
        with ReviewLedger(self.ledger_path) as ledger:
            return export_publication(ledger)


class ReviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def make_handler(application: ReviewApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "BadmintonEvidenceReview/3"

        def _allowed_hosts(self) -> set[str]:
            address = self.server.server_address
            if not isinstance(address, tuple) or len(address) < 2:
                return set()
            port = address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

        def _valid_host(self) -> bool:
            return self.headers.get("Host", "") in self._allowed_hosts()

        def _token(self) -> str:
            header = self.headers.get("X-Review-Token", "")
            if header:
                return header
            return parse_qs(urlparse(self.path).query).get("token", [""])[0]

        def _send_headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; "
                "font-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )

        def send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def send_asset(self, path: Path) -> None:
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self._send_headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

        def send_media(self) -> None:
            size = application.media_path.stat().st_size
            start = 0
            end = size - 1
            status = 200
            requested = self.headers.get("Range")
            if requested:
                match = _RANGE.fullmatch(requested.strip())
                if match is None:
                    raise ValueError("unsupported media range")
                start_text, end_text = match.groups()
                if not start_text and not end_text:
                    raise ValueError("empty media range")
                if not start_text:
                    suffix = int(end_text)
                    start = max(0, size - suffix)
                else:
                    start = int(start_text)
                    end = int(end_text) if end_text else end
                if start < 0 or end < start or start >= size:
                    raise ValueError("media range is outside the file")
                end = min(end, size - 1)
                status = 206
            length = end - start + 1
            self.send_response(status)
            content_type = mimetypes.guess_type(application.media_path.name)[0]
            self._send_headers(content_type or "application/octet-stream", length)
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with application.media_path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _require_api_access(self, post: bool = False) -> bool:
            if not self._valid_host():
                self.send_json(403, {"error": "invalid_host"})
                return False
            if not secrets.compare_digest(self._token(), application.session_token):
                self.send_json(403, {"error": "invalid_session_token"})
                return False
            if post:
                host = self.headers.get("Host", "")
                if self.headers.get("Origin") != f"http://{host}":
                    self.send_json(403, {"error": "invalid_origin"})
                    return False
                csrf = self.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(csrf, application.csrf_token):
                    self.send_json(403, {"error": "invalid_csrf_token"})
                    return False
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    self.send_json(415, {"error": "json_content_type_required"})
                    return False
            return True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/"):
                    if not self._require_api_access():
                        return
                    if parsed.path == "/api/session":
                        self.send_json(200, application.summary())
                    elif parsed.path == "/api/media":
                        self.send_media()
                    elif parsed.path == "/api/publication-preview":
                        self.send_json(200, application.publication_preview())
                    else:
                        self.send_json(404, {"error": "not_found"})
                    return
                name = "index.html" if parsed.path in {"", "/"} else parsed.path[1:]
                if name not in {"index.html", "styles.css", "app.js"}:
                    self.send_json(404, {"error": "not_found"})
                    return
                self.send_asset(ASSET_ROOT / name)
            except (BrokenPipeError, ConnectionResetError):
                return
            except (OSError, ValueError) as error:
                self.send_json(400, {"error": str(error)})

        def do_POST(self) -> None:
            if not self._require_api_access(post=True):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 2_000_000:
                    raise ValueError("review request size is invalid")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("review request must be an object")
                path = urlparse(self.path).path
                if path == "/api/drafts":
                    result = application.save_draft(body)
                elif path == "/api/transcript/begin":
                    result = application.begin_transcript_review(body)
                elif path == "/api/transcript/preview":
                    result = application.preview_transcript(body)
                elif path == "/api/transcript/verify":
                    result = application.verify_transcript(body)
                elif path == "/api/entities/transition":
                    result = application.transition_entity(body)
                else:
                    self.send_json(404, {"error": "not_found"})
                    return
                self.send_json(200, result)
            except (json.JSONDecodeError, OSError, ValueError) as error:
                self.send_json(400, {"error": str(error)})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def create_server(
    application: ReviewApplication, host: str = "127.0.0.1", port: int = 8765
) -> ReviewHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("review workbench may bind only to a loopback host")
    return ReviewHTTPServer((host, port), make_handler(application))


def token_from_url(url: str) -> str:
    values = parse_qs(urlparse(url).query)
    return values.get("token", [""])[0]
