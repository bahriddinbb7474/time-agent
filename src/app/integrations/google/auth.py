from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


GCAL_SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"
GCAL_SCOPE_READONLY = "https://www.googleapis.com/auth/calendar.readonly"


def _parse_scopes(raw: str) -> list[str]:
    # поддержка "scope1,scope2" и "scope1, scope2"
    scopes = [s.strip() for s in (raw or "").split(",")]
    return [s for s in scopes if s]


def get_scopes() -> list[str]:
    raw_scopes = _parse_scopes(os.getenv("GCAL_SCOPES", GCAL_SCOPE_EVENTS))

    # Если запрошен write-scope calendar.events,
    # добавляем readonly тоже, потому что Google может вернуть оба,
    # и oauthlib иначе валится на "scope has changed".
    scopes = list(raw_scopes)

    if GCAL_SCOPE_EVENTS in scopes and GCAL_SCOPE_READONLY not in scopes:
        scopes.append(GCAL_SCOPE_READONLY)

    return scopes


def get_credentials_path() -> str:
    p = os.getenv("GCAL_CREDENTIALS_PATH", "")
    if not p:
        raise RuntimeError("GCAL_CREDENTIALS_PATH is not set")
    return p


def get_token_path() -> str:
    p = os.getenv("GCAL_TOKEN_PATH", "")
    if not p:
        raise RuntimeError("GCAL_TOKEN_PATH is not set")
    return p


def get_redirect_uri() -> str:
    uri = os.getenv("GCAL_OAUTH_REDIRECT_URI", "")
    if not uri:
        raise RuntimeError("GCAL_OAUTH_REDIRECT_URI is not set")
    return uri


def load_credentials() -> Optional[Credentials]:
    token_path = Path(get_token_path())
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), get_scopes())


def save_credentials(creds: Credentials) -> None:
    token_path = Path(get_token_path())
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def refresh_if_needed(creds: Credentials) -> Credentials:
    # НЕЛЬЗЯ логировать токены
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)
    return creds


def build_flow(state: str) -> Flow:
    """
    Flow c явным state (state храним в SQLite и валидируем в callback).
    """
    flow = Flow.from_client_secrets_file(
        get_credentials_path(),
        scopes=get_scopes(),
        redirect_uri=get_redirect_uri(),
        state=state,
    )
    return flow
