"""MangaDex login via a *personal API client* (OAuth2 password grant).

Docs: https://api.mangadex.org/docs/02-authentication/personal-clients/

Your password is used once to get a token pair and is never written to disk. What we keep in
~/.config/mangadex-dl/auth.json (mode 600) is the client id/secret and the refresh token.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from . import api

TOKEN_URL = "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token"
CONFIG_PATH = os.path.expanduser("~/.config/mangadex-dl/auth.json")


class AuthError(Exception):
    pass


class Session:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.client_id = self.client_secret = self.refresh_token = ""
        self.access_token = ""
        self.expires_at = 0.0
        self.username = ""
        self._load()

    # ---------------------------------------------------------- persistence
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        self.client_id = d.get("client_id", "")
        self.client_secret = d.get("client_secret", "")
        self.refresh_token = d.get("refresh_token", "")
        self.username = d.get("username", "")

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"client_id": self.client_id, "client_secret": self.client_secret,
                       "refresh_token": self.refresh_token, "username": self.username}, f)
        os.chmod(self.path, 0o600)

    @property
    def logged_in(self) -> bool:
        return bool(self.refresh_token)

    # ---------------------------------------------------------- token flow
    def _post(self, form: Dict[str, str]) -> Dict[str, Any]:
        body = urllib.parse.urlencode(form).encode()
        try:
            raw = api.fetch(TOKEN_URL, data=body, retries=1, headers={
                "Content-Type": "application/x-www-form-urlencoded"})
        except api.ApiError as e:
            msg = str(e)
            if "HTTP 401" in msg or "HTTP 400" in msg:
                raise AuthError("MangaDex rejected those credentials. Check username/password, "
                                "and that your API client is approved (not 'pending').") from e
            raise AuthError(msg) from e
        return json.loads(raw.decode())

    def login(self, username: str, password: str, client_id: str, client_secret: str) -> None:
        tok = self._post({"grant_type": "password", "username": username, "password": password,
                          "client_id": client_id, "client_secret": client_secret})
        with self.lock:
            self.client_id, self.client_secret = client_id, client_secret
            self._take(tok)
            try:
                me = api.get_json("/user/me", token=self.access_token)["data"]
                self.username = me["attributes"].get("username") or username
            except api.ApiError:
                self.username = username
            self._save()

    def _take(self, tok: Dict[str, Any]) -> None:
        self.access_token = tok["access_token"]
        self.expires_at = time.time() + float(tok.get("expires_in", 900)) - 60
        if tok.get("refresh_token"):
            self.refresh_token = tok["refresh_token"]

    def token(self) -> str:
        """A valid access token, refreshing it if it's (nearly) expired."""
        with self.lock:
            if not self.refresh_token:
                raise AuthError("Not logged in.")
            if self.access_token and time.time() < self.expires_at:
                return self.access_token
            try:
                tok = self._post({"grant_type": "refresh_token", "refresh_token": self.refresh_token,
                                  "client_id": self.client_id, "client_secret": self.client_secret})
            except AuthError:
                # Refresh tokens eventually expire; make the user log in again.
                self.refresh_token = self.access_token = ""
                self._save()
                raise AuthError("Your MangaDex session expired. Please log in again.")
            self._take(tok)
            self._save()
            return self.access_token

    def logout(self) -> None:
        with self.lock:
            self.access_token = self.refresh_token = self.username = ""
            self.expires_at = 0
            self._save()

    # ---------------------------------------------------------- account data
    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return api.get_json(path, params, token=self.token())

    def follows(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            d = self.get("/user/follows/manga", {"limit": 100, "offset": offset,
                                                 "includes[]": ["cover_art", "author"]})
            out += d["data"]
            offset += 100
            if offset >= d.get("total", 0) or offset >= 1000:
                return out

    def reading_statuses(self) -> Dict[str, str]:
        return self.get("/manga/status").get("statuses") or {}

    def updates(self, langs: List[str], limit: int = 48) -> List[Dict[str, Any]]:
        return self.get("/user/follows/manga/feed", {
            "translatedLanguage[]": langs, "limit": limit, "order[readableAt]": "desc",
            "includes[]": ["manga", "scanlation_group"], "contentRating[]": api.ALL_RATINGS,
            "includeExternalUrl": 0, "includeEmptyPages": 0,
        })["data"]

    def lists(self) -> List[Dict[str, Any]]:
        return self.get("/user/list", {"limit": 100})["data"]
