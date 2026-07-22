"""Streamlit-agnostic HTTP client for the FastAPI backend.

Every method raises APIError on a non-2xx response instead of returning
partial data, so callers only ever need one except clause. Nothing in this
module touches st.session_state — that lives in services/auth.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import httpx

from config.settings import api_settings


class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


@dataclass
class SSEEvent:
    event: str
    data: dict[str, Any]


def _extract_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail")
        if detail:
            return detail if isinstance(detail, str) else json.dumps(detail)
    except ValueError:
        pass
    return response.text or f"HTTP {response.status_code}"


class ProposalAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self._base_url = (base_url or api_settings.base_url).rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=api_settings.timeout_seconds)

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _auth_headers(access_token: Optional[str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"} if access_token else {}

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIError(504, "The backend took too long to respond. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise APIError(503, f"Cannot reach the backend at {self._base_url}.") from exc
        if response.status_code >= 400:
            raise APIError(response.status_code, _extract_detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ---------------- Health ----------------

    def health_check(self) -> dict:
        return self._request("GET", "/")

    # ---------------- Auth ----------------

    def login(self, email: str, password: str) -> dict:
        return self._request("POST", "/auth/login", json={"email": email, "password": password})

    def refresh_access_token(self, refresh_token: str) -> dict:
        return self._request("POST", "/auth/refresh", json={"refresh_token": refresh_token})

    # ---------------- Requirement documents (Step 1) ----------------

    def upload_requirement_document(
        self,
        *,
        access_token: str,
        file_bytes: bytes,
        file_name: str,
        proposal_name: str,
        client_name: str,
        additional_context: Optional[str] = None,
    ) -> dict:
        files = {"file": (file_name, file_bytes)}
        data = {"proposal_name": proposal_name, "client_name": client_name}
        if additional_context:
            data["additional_context"] = additional_context
        return self._request(
            "POST",
            "/proposals/requirement-documents",
            files=files,
            data=data,
            headers=self._auth_headers(access_token),
            timeout=api_settings.timeout_seconds * 4,
        )

    def get_requirement_document(self, document_id: int) -> dict:
        return self._request("GET", f"/proposals/requirement-documents/{document_id}")

    # ---------------- Proposal generation (Step 2, SSE) ----------------

    def generate_proposal(
        self,
        *,
        access_token: str,
        requirement_document_id: int,
        category_ids: Optional[list[int]] = None,
    ) -> Iterator[SSEEvent]:
        payload: dict[str, Any] = {"requirement_document_id": requirement_document_id}
        if category_ids:
            payload["category_ids"] = category_ids

        try:
            with self._client.stream(
                "POST",
                "/proposals/generate",
                json=payload,
                headers=self._auth_headers(access_token),
                timeout=api_settings.stream_timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise APIError(response.status_code, _extract_detail(response))

                event_name: Optional[str] = None
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if line == "":
                        if event_name is not None:
                            yield self._parse_sse(event_name, data_lines)
                        event_name, data_lines = None, []
                        continue
                    if line.startswith("event:"):
                        event_name = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[len("data:"):].strip())
                if event_name is not None:
                    yield self._parse_sse(event_name, data_lines)
        except httpx.TimeoutException as exc:
            raise APIError(504, "The backend took too long to respond. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise APIError(503, f"Cannot reach the backend at {self._base_url}.") from exc

    @staticmethod
    def _parse_sse(event_name: str, data_lines: list[str]) -> SSEEvent:
        raw = "\n".join(data_lines)
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        return SSEEvent(event=event_name, data=data)

    # ---------------- Proposals (Step 3 + Dashboard) ----------------

    def get_proposal(self, proposal_id: int) -> dict:
        return self._request("GET", f"/proposals/{proposal_id}")

    def list_proposals(
        self,
        *,
        client_name: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
    ) -> dict:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if client_name:
            params["client_name"] = client_name
        if status:
            params["status"] = status
        return self._request("GET", "/proposals/", params=params)

    # ---------------- Sections (Step 3 review/refine) ----------------

    def edit_section(self, *, access_token: str, section_id: int, content: str) -> dict:
        return self._request(
            "PATCH",
            f"/proposals/sections/{section_id}",
            json={"content": content},
            headers=self._auth_headers(access_token),
        )

    def regenerate_section(self, *, access_token: str, section_id: int) -> dict:
        return self._request(
            "POST",
            f"/proposals/sections/{section_id}/regenerate",
            headers=self._auth_headers(access_token),
            timeout=api_settings.timeout_seconds * 3,
        )

    def approve_section(self, *, access_token: str, section_id: int) -> dict:
        return self._request(
            "POST",
            f"/proposals/sections/{section_id}/approve",
            headers=self._auth_headers(access_token),
        )

    # ---------------- Categories ----------------

    def list_categories(self) -> dict:
        return self._request("GET", "/category/list")
