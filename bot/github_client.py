import base64
import csv
import io
from datetime import datetime
from typing import Dict, Iterable, Optional, Sequence, Tuple

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
        existing_content, sha = self._fetch_file()
        csv_payload = self._build_payload(existing_content, header, row)
        self._put_file(csv_payload, sha)

    # endregion

    def read_rows(self) -> Tuple[Sequence[str], Sequence[Dict[str, str]]]:
        """Read the remote CSV into (header, rows)."""
        content, _sha = self._fetch_file()
        if not content:
            return (), ()
        header, rows = self._parse_csv(content)
        return header, rows

    def delete_matching_row(
        self,
        row_fingerprint: Dict[str, str],
        *,
        preferred_index: Optional[int] = None,
        commit_message: Optional[str] = None,
    ) -> bool:
        """Delete the most recent row that matches the fingerprint.

        Returns True if a row was found & deleted.
        """
        content, sha = self._fetch_file()
        if not content or not sha:
            return False
        header, rows = self._parse_csv(content)
        index = self._locate_row(
            rows,
            row_fingerprint,
            header=header,
            preferred_index=preferred_index,
        )
        if index is None:
            return False
        del rows[index]
        updated = self._serialize_csv(header, rows)
        self._put_file(
            updated,
            sha,
            message=commit_message
            or f"chore: delete shift via bot at {datetime.utcnow().isoformat()}",
        )
        return True

    def update_matching_row(
        self,
        row_fingerprint: Dict[str, str],
        updated_row: Dict[str, str],
        *,
        preferred_index: Optional[int] = None,
        commit_message: Optional[str] = None,
    ) -> bool:
        """Update the most recent row that matches the fingerprint.

        Returns True if a row was found & updated.
        """
        content, sha = self._fetch_file()
        if not content or not sha:
            return False
        header, rows = self._parse_csv(content)
        index = self._locate_row(
            rows,
            row_fingerprint,
            header=header,
            preferred_index=preferred_index,
        )
        if index is None:
            return False
        rows[index] = {col: str(updated_row.get(col, "")) for col in header}
        updated = self._serialize_csv(header, rows)
        self._put_file(
            updated,
            sha,
            message=commit_message
            or f"chore: update shift via bot at {datetime.utcnow().isoformat()}",
        )
        return True

    def _fetch_file(self) -> tuple[Optional[str], Optional[str]]:
        url = f"https://api.github.com/repos/{self.repo}/contents/{self.file_path}"
        params = {"ref": self.branch}
        response = self._session.get(url, params=params)
        if response.status_code == 404:
            return None, None
        response.raise_for_status()
        payload = response.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        return content, payload["sha"]

    def _build_payload(
        self,
        existing_content: Optional[str],
        header: Iterable[str],
        row: Dict[str, str],
    ) -> str:
        output = io.StringIO()
        writer = _DictWriter(output, header)
        if not existing_content:
            writer.writeheader()
        else:
            output.write(existing_content.rstrip("\n"))
            output.write("\n")
        writer.writerow(row)
        return output.getvalue()

    @staticmethod
    def _parse_csv(content: str) -> Tuple[Sequence[str], list[Dict[str, str]]]:
        stream = io.StringIO(content)
        reader = csv.DictReader(stream)
        header = list(reader.fieldnames or [])
        rows: list[Dict[str, str]] = []
        for row in reader:
            if not row:
                continue
            normalized = {key: (value or "") for key, value in row.items()}
            if not any(normalized.values()):
                continue
            rows.append(normalized)
        return header, rows

    @staticmethod
    def _serialize_csv(header: Sequence[str], rows: Sequence[Dict[str, str]]) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in header})
        return output.getvalue()

    @staticmethod
    def _locate_row(
        rows: Sequence[Dict[str, str]],
        fingerprint: Dict[str, str],
        *,
        header: Sequence[str],
        preferred_index: Optional[int],
    ) -> Optional[int]:
        def matches(candidate: Dict[str, str]) -> bool:
            return all(
                (candidate.get(col, "") or "") == (fingerprint.get(col, "") or "")
                for col in header
            )

        if preferred_index is not None and 0 <= preferred_index < len(rows):
            if matches(rows[preferred_index]):
                return preferred_index

        for index in range(len(rows) - 1, -1, -1):
            if matches(rows[index]):
                return index
        return None

    def _put_file(self, content: str, sha: Optional[str], *, message: Optional[str] = None) -> None:
        url = f"https://api.github.com/repos/{self.repo}/contents/{self.file_path}"
        data = {
            "message": message or f"chore: log shift via bot at {datetime.utcnow().isoformat()}",
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
