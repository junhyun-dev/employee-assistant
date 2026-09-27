"""Small loopback HTTP boundary for the local-first employee assistant."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .flow import (
    DEFAULT_INQUIRY_SCOPE,
    DEFAULT_LAPTOP_INQUIRY_GOAL,
    INQUIRY_SCOPES,
    LAPTOP_INQUIRY_GOALS,
    load_corpus,
    process_request,
)


HOST = "127.0.0.1"
MAX_BODY_BYTES = 32 * 1024
MAX_USER_TEXT = 2_000
MAX_FACT_TEXT = 240
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
SUPPORTED_TYPE = "monitor_and_laptop_replacement"
LAPTOP_EVIDENCE_ID = "laptops-insurance-repairs"


class RequestError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _expect_keys(value: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "unexpected_field",
            f"{where}에 지원하지 않는 필드가 있습니다: {', '.join(extra)}",
        )


def _clean_text(value: Any, field: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", f"{field}는 문자열이어야 합니다.")
    if required and not value.strip():
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", f"{field}를 입력해 주세요.")
    if len(value) > maximum:
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", f"{field}가 너무 깁니다.")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", f"{field}에 허용되지 않는 문자가 있습니다.")
    return value


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_json_shape", "JSON 객체를 보내 주세요.")
    _expect_keys(
        payload,
        {
            "client_request_id",
            "inquiry_type",
            "inquiry_scope",
            "laptop_inquiry_goal",
            "user_text",
            "employee_facts",
            "exclude_laptop_evidence",
        },
        "요청",
    )

    request_id = payload.get("client_request_id")
    if isinstance(request_id, bool) or not isinstance(request_id, int) or not 0 <= request_id <= 2**53 - 1:
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", "client_request_id가 올바르지 않습니다.")

    inquiry_type = payload.get("inquiry_type")
    if not isinstance(inquiry_type, str):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", "inquiry_type은 문자열이어야 합니다.")
    if inquiry_type != SUPPORTED_TYPE:
        raise RequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "unsupported_inquiry_type",
            "현재는 모니터 구입과 회사 노트북 문의만 지원합니다.",
        )

    inquiry_scope = payload.get("inquiry_scope", DEFAULT_INQUIRY_SCOPE)
    if not isinstance(inquiry_scope, str):
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_value",
            "inquiry_scope은 문자열이어야 합니다.",
        )
    if inquiry_scope not in INQUIRY_SCOPES:
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_value",
            "inquiry_scope 값이 올바르지 않습니다.",
        )

    laptop_inquiry_goal = payload.get(
        "laptop_inquiry_goal", DEFAULT_LAPTOP_INQUIRY_GOAL
    )
    if not isinstance(laptop_inquiry_goal, str):
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_value",
            "laptop_inquiry_goal은 문자열이어야 합니다.",
        )
    if laptop_inquiry_goal not in LAPTOP_INQUIRY_GOALS:
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_value",
            "laptop_inquiry_goal 값이 올바르지 않습니다.",
        )

    user_text = _clean_text(payload.get("user_text", ""), "user_text", maximum=MAX_USER_TEXT, required=True)
    facts = payload.get("employee_facts")
    if not isinstance(facts, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", "employee_facts는 JSON 객체여야 합니다.")
    _expect_keys(facts, {"tenure", "symptom", "purchase_status", "monitor_employee_detail"}, "employee_facts")

    cleaned_facts: dict[str, str] = {}
    for key in ("tenure", "symptom", "monitor_employee_detail"):
        if key in facts:
            cleaned_facts[key] = _clean_text(facts[key], key, maximum=MAX_FACT_TEXT)
    purchase_status = _clean_text(
        facts.get("purchase_status", ""),
        "purchase_status",
        maximum=MAX_FACT_TEXT,
    )
    if purchase_status.strip() and purchase_status not in {"not_purchased", "purchased", "unknown"}:
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", "purchase_status 값이 올바르지 않습니다.")
    if "purchase_status" in facts:
        cleaned_facts["purchase_status"] = purchase_status

    exclude_laptop = payload.get("exclude_laptop_evidence", False)
    if not isinstance(exclude_laptop, bool):
        raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_value", "exclude_laptop_evidence는 true 또는 false여야 합니다.")

    return {
        "client_request_id": request_id,
        "inquiry_type": inquiry_type,
        "inquiry_scope": inquiry_scope,
        "laptop_inquiry_goal": laptop_inquiry_goal,
        "user_text": user_text,
        "employee_facts": cleaned_facts,
        "exclude_laptop_evidence": exclude_laptop,
    }


def build_api_response(payload: dict[str, Any]) -> dict[str, Any]:
    request = {
        "inquiry_type": payload["inquiry_type"],
        "inquiry_scope": payload["inquiry_scope"],
        "laptop_inquiry_goal": payload["laptop_inquiry_goal"],
        "user_text": payload["user_text"],
        "employee_facts": payload["employee_facts"],
    }
    excluded = [LAPTOP_EVIDENCE_ID] if payload["exclude_laptop_evidence"] else []
    result = process_request(load_corpus(), request, excluded_evidence_ids=excluded)
    states = {branch["status"] for branch in result["branches"].values()}
    return {
        "client_request_id": payload["client_request_id"],
        "ui_state": "missing" if "withheld_missing_required_evidence" in states else "normal",
        "result": result,
    }


class EmployeeAssistantHandler(BaseHTTPRequestHandler):
    server_version = "EmployeeAssistant/0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )

    def _write(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: Any) -> None:
        self._write(status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _error(self, error: RequestError) -> None:
        self._json(error.status, {"error": {"code": error.code, "message": error.message}})

    def do_GET(self) -> None:  # noqa: N802
        raw_path = unquote(urlsplit(self.path).path)
        relative = "index.html" if raw_path == "/" else raw_path.lstrip("/")
        try:
            target = (WEB_ROOT / relative).resolve()
            target.relative_to(WEB_ROOT.resolve())
        except (OSError, ValueError):
            self._json(HTTPStatus.FORBIDDEN, {"error": {"code": "path_outside_web_root", "message": "허용되지 않는 경로입니다."}})
            return
        if not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "파일을 찾지 못했습니다."}})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._write(HTTPStatus.OK, content_type, target.read_bytes())

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/workspace":
            self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "API 경로를 찾지 못했습니다."}})
            return
        if self.headers.get_content_type() != "application/json":
            self._error(RequestError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "application/json으로 보내 주세요."))
            return
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "")
        except ValueError:
            length = -1
        if length < 0:
            self._error(RequestError(HTTPStatus.LENGTH_REQUIRED, "content_length_required", "Content-Length가 필요합니다."))
            return
        if length > MAX_BODY_BYTES:
            self._error(RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large", "요청 본문이 너무 큽니다."))
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            cleaned = validate_payload(payload)
            self._json(HTTPStatus.OK, build_api_response(cleaned))
        except UnicodeDecodeError:
            self._error(RequestError(HTTPStatus.BAD_REQUEST, "invalid_encoding", "요청은 UTF-8이어야 합니다."))
        except json.JSONDecodeError:
            self._error(RequestError(HTTPStatus.BAD_REQUEST, "invalid_json", "올바른 JSON을 보내 주세요."))
        except RequestError as error:
            self._error(error)


class EmployeeAssistantServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port: int = 8767) -> EmployeeAssistantServer:
    return EmployeeAssistantServer((HOST, port), EmployeeAssistantHandler)


def run(port: int = 8767) -> None:
    server = make_server(port)
    print(f"직원 업무 도우미: http://{HOST}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
