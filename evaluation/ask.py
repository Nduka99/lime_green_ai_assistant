"""Ask every question of a set through a deployed endpoint and save the answers.

The system is measured as people reach it, over HTTP, not by importing its code,
so a run also covers the web layer, the configuration and the model servers the
deployment really uses. A stopped run resumes and skips the ids already saved.
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return records


def write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(records, indent=1, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def ask_one(client: httpx.Client, endpoint: str, row: dict[str, str]) -> dict[str, Any]:
    """One answer record: the reader's view, or the error the endpoint returned."""
    started = time.perf_counter()
    try:
        response = client.get(endpoint, params={"q": row["question"]})
    except httpx.HTTPError as error:
        record: dict[str, Any] = {"http": None, "error": str(error)}
    else:
        record = {"http": response.status_code}
        if response.status_code == 200:
            record["view"] = response.json()
        else:
            record["error"] = response.text
    seconds = round(time.perf_counter() - started, 1)
    return {"id": row["id"], "question": row["question"], **record, "seconds": seconds}


def ask_all(
    questions: list[dict[str, str]],
    client: httpx.Client,
    endpoint: str,
    out: Path,
) -> list[dict[str, Any]]:
    """Answer every question not yet saved, saving after each one."""
    records = read_records(out)
    done = {record["id"] for record in records}
    for row in questions:
        if row["id"] in done:
            continue
        records.append(ask_one(client, endpoint, row))
        write_records(out, records)
        latest = records[-1]
        status = latest.get("view", {}).get("status", f"error {latest['http']}")
        print(row["id"], status, latest["seconds"], "s", flush=True)
    return records
