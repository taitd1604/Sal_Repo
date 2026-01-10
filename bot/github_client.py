import base64
import io
from datetime import datetime
from typing import Dict, Iterable, Optional

import requests


class GitHubCSVClient:
    """Lightweight helper that appends rows to a CSV file in a GitHub repo."""

    def __init__(
        self,
        token: str,
        repo: str,
        file_path: str,
        branch: str = "main",
    ) -> None:
        if "/" not in repo:
            raise ValueError("repo must be in the format 'owner/name'")
        self.repo = repo
        self.file_path = file_path.strip("/")
        self.branch = branch
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )

    # region public api
    def append_row(self, header: Iterable[str], row: Dict[str, str]) -> None:
        """Append a CSV row to the configured file (creating the file if needed)."""
        existing = self._fetch_file()
        csv_payload, sha = self._build_payload(existing, header, row)
        self._put_file(csv_payload, sha)

    # endregion

    def _fetch_file(self) -> Optional[str]:
        url = f"https://api.github.com/repos/{self.repo}/contents/{self.file_path}"
        params = {"ref": self.branch}
        response = self._session.get(url, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        self._sha = payload["sha"]
        return content

    def _build_payload(
        self,
        existing_content: Optional[str],
        header: Iterable[str],
        row: Dict[str, str],
    ) -> tuple[str, Optional[str]]:
        output = io.StringIO()
        writer = _DictWriter(output, header)
        if not existing_content:
            writer.writeheader()
        else:
            output.write(existing_content.rstrip("\n"))
            output.write("\n")
        writer.writerow(row)
        return output.getvalue(), getattr(self, "_sha", None)

    def _put_file(self, content: str, sha: Optional[str]) -> None:
        url = f"https://api.github.com/repos/{self.repo}/contents/{self.file_path}"
        data = {
            "message": f"chore: log shift via bot at {datetime.utcnow().isoformat()}",
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": self.branch,
        }
        if sha:
            data["sha"] = sha
        response = self._session.put(url, json=data)
        response.raise_for_status()


class _DictWriter:
    """Minimal CSV DictWriter to avoid bringing csv module state handling here."""

    def __init__(self, stream: io.StringIO, fieldnames: Iterable[str]) -> None:
        self.stream = stream
        self.fieldnames = list(fieldnames)

    def writeheader(self) -> None:
        self.stream.write(",".join(self.fieldnames))
        self.stream.write("\n")

    def writerow(self, row: Dict[str, str]) -> None:
        values = [self._escape(row.get(name, "")) for name in self.fieldnames]
        self.stream.write(",".join(values))
        self.stream.write("\n")

    def _escape(self, value: str) -> str:
        value = str(value)
        if any(ch in value for ch in [",", '"', "\n"]):
            escaped = value.replace('"', '""')
            return f'"{escaped}"'
        return value
