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


def ask_one(
    client: httpx.Client,
    endpoint: str,
    row: dict[str, str],
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """One answer record: the reader's view, or the error the endpoint returned.

    The v1 API (`/api/v1/answers`) takes the question as JSON, with the conversation
    it continues if any, and returns the view with the id of its audit record and
    its place in a conversation; the submitted v5 answers `GET /api/answer?q=`.
    """
    started = time.perf_counter()
    v1 = endpoint.startswith("/api/v1/")
    try:
        if v1:
            body: dict[str, str] = {"question": row["question"]}
            if conversation_id is not None:
                body["conversation_id"] = conversation_id
            response = client.post(endpoint, json=body)
        else:
            response = client.get(endpoint, params={"q": row["question"]})
    except httpx.HTTPError as error:
        record: dict[str, Any] = {"http": None, "error": str(error)}
    else:
        record = {"http": response.status_code}
        if response.status_code == 200 and v1:
            answered = response.json()
            record["view"] = answered["answer"]
            record["answer_id"] = answered["id"]
            record["conversation_id"] = answered["conversation_id"]
            record["turn"] = answered["turn"]
        elif response.status_code == 200:
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
    converse: bool = False,
) -> list[dict[str, Any]]:
    """Answer every question not yet saved, saving after each one. With `converse`
    (a conversation set, in turn order), each question continues its conversation
    (`row["conversation"]`) under the id the API gave that conversation's first
    turn, so the server builds each history from what it showed."""
    records = read_records(out)
    saved = {record["id"]: record for record in records}
    started: dict[str, str] = {}
    for row in questions:
        record = saved.get(row["id"])
        if record is None:
            asked = started.get(row["conversation"]) if converse else None
            record = ask_one(client, endpoint, row, asked)
            records.append(record)
            write_records(out, records)
            status = record.get("view", {}).get("status", f"error {record['http']}")
            print(row["id"], status, record["seconds"], "s", flush=True)
        if converse and "conversation_id" in record:
            started[row["conversation"]] = record["conversation_id"]
    return records
