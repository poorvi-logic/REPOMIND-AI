from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings
from .errors import ExternalServiceError, InputError, NotFoundError

ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,15}-\d{1,9}$")
PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")


@dataclass(frozen=True)
class JiraCredentials:
    base_url: str
    email: str
    api_token: str = field(repr=False)


def normalize_site_url(raw_url: str, allow_any_host: bool) -> str:
    candidate = (raw_url or "").strip().rstrip("/")
    if not candidate or len(candidate) > 200:
        raise InputError("Enter your Jira site URL, for example https://your-team.atlassian.net.")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InputError("The Jira site URL must start with https://.")
    if parsed.username or parsed.password:
        raise InputError("Do not include credentials in the Jira site URL.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise InputError("Enter only the Jira site root URL, without a path or query string.")
    host = parsed.hostname.lower()
    if not allow_any_host and not host.endswith(".atlassian.net"):
        raise InputError("Only *.atlassian.net sites are accepted unless JIRA_ALLOW_ANY_HOST=true is set.")
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    return f"https://{host}{port}"


def credentials_from_settings(settings: Settings) -> JiraCredentials | None:
    if not (settings.jira_base_url and settings.jira_email and settings.jira_api_token):
        return None
    return JiraCredentials(
        base_url=normalize_site_url(settings.jira_base_url, settings.jira_allow_any_host),
        email=settings.jira_email,
        api_token=settings.jira_api_token,
    )


class JiraCredentialStore:
    def __init__(self, environment: JiraCredentials | None) -> None:
        self._environment = environment
        self._session: JiraCredentials | None = None
        self._lock = threading.Lock()

    def set_session(self, credentials: JiraCredentials) -> None:
        with self._lock:
            self._session = credentials

    def clear_session(self) -> None:
        with self._lock:
            self._session = None

    def current(self) -> tuple[JiraCredentials | None, str | None]:
        with self._lock:
            if self._session is not None:
                return self._session, "session"
        if self._environment is not None:
            return self._environment, "environment"
        return None, None

    def public_status(self) -> dict[str, Any]:
        credentials, source = self.current()
        return {
            "configured": credentials is not None,
            "source": source,
            "base_url": credentials.base_url if credentials else None,
            "email": credentials.email if credentials else None,
            "session_override_active": self._session is not None,
        }


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "no details returned"
    messages = list(payload.get("errorMessages") or [])
    messages.extend(f"{key}: {value}" for key, value in (payload.get("errors") or {}).items())
    return ("; ".join(messages) or "no details returned")[:300]


class JiraClient:
    def __init__(self, credentials: JiraCredentials, timeout_seconds: float = 20.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = credentials.base_url
        self._client = httpx.Client(
            base_url=credentials.base_url,
            auth=(credentials.email, credentials.api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Jira did not respond in time. Try again.") from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Could not reach Jira. Check the site URL and your network connection.") from exc
        if response.status_code == 401:
            raise InputError("Jira rejected the email or API token.", status_code=401)
        if response.status_code == 403:
            raise InputError("The Jira account does not have permission for this action.", status_code=403)
        if response.status_code == 404:
            raise NotFoundError("The requested Jira resource was not found.")
        if response.status_code >= 400:
            raise ExternalServiceError(f"Jira returned HTTP {response.status_code}: {_error_text(response)}")
        if not response.content:
            return {}
        return response.json()

    def myself(self) -> dict[str, Any]:
        payload = self._request("GET", "/rest/api/3/myself")
        return {"account_id": payload.get("accountId"), "display_name": payload.get("displayName"),
                "active": payload.get("active", True)}

    def projects(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request("GET", "/rest/api/3/project/search", params={"maxResults": limit, "orderBy": "key"})
        return [{"key": item["key"], "name": item["name"], "id": item.get("id")} for item in payload.get("values", [])]

    def issue_types(self, project_key: str) -> list[str]:
        payload = self._request("GET", f"/rest/api/3/project/{project_key}")
        return [item["name"] for item in payload.get("issueTypes", []) if not item.get("subtask")]

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        payload = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        key = payload["key"]
        return {"id": payload.get("id"), "key": key, "url": f"{self.base_url}/browse/{key}"}

    def issue_status(self, issue_key: str) -> dict[str, Any]:
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}",
                                params={"fields": "summary,status,priority,assignee,updated"})
        fields = payload.get("fields", {})
        status = fields.get("status") or {}
        return {
            "key": payload.get("key", issue_key),
            "summary": fields.get("summary"),
            "status": status.get("name"),
            "status_category": (status.get("statusCategory") or {}).get("name"),
            "priority": (fields.get("priority") or {}).get("name"),
            "assignee": (fields.get("assignee") or {}).get("displayName"),
            "updated": fields.get("updated"),
            "url": f"{self.base_url}/browse/{issue_key}",
        }
