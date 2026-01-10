#!/usr/bin/env python3
"""Sync the latest shifts.csv from GitHub to the local data/ folder."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATHS = [REPO_ROOT / "bot" / ".env", REPO_ROOT / ".env"]


def load_env() -> None:
    if not load_dotenv:
        return
    for env_path in ENV_PATHS:
        if env_path.exists():
            load_dotenv(env_path)
            break


def main() -> None:
    load_env()
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    file_path = os.environ.get("GITHUB_FILE_PATH", "data/shifts.csv")
    branch = os.environ.get("GITHUB_BRANCH", "main")

    if not token or not repo:
        raise SystemExit("Missing GITHUB_TOKEN or GITHUB_REPO environment variables.")

    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    params = {"ref": branch}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    content = base64.b64decode(data["content"])

    destination = REPO_ROOT / file_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    print(f"Đã đồng bộ {file_path} từ GitHub → {destination}")


if __name__ == "__main__":
    main()
