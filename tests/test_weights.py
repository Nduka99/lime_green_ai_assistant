"""Checking the model files against their manifest. Every file is invented."""

import hashlib
import json
from pathlib import Path

import pytest

from limespec import cli, weights


def entry(file: str, data: bytes) -> dict[str, object]:
    return {
        "file": file,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_files_are_checked_by_size_and_sha256(tmp_path: Path) -> None:
    (tmp_path / "a.gguf").write_bytes(b"weights")
    (tmp_path / "b.gguf").write_bytes(b"weightz")  # same size, other content
    (tmp_path / "c.gguf").write_bytes(b"short")
    entries = [
        entry("a.gguf", b"weights"),
        entry("b.gguf", b"weights"),
        entry("c.gguf", b"weights"),
        entry("gone.gguf", b"weights"),
    ]

    assert weights.problems(entries, tmp_path, quick=False) == [
        "SHA-256 differs: b.gguf",
        "size differs: c.gguf",
        "missing: gone.gguf",
    ]
    assert weights.problems(entries, tmp_path, quick=True) == [
        "size differs: c.gguf",
        "missing: gone.gguf",
    ]
    assert weights.sha256(tmp_path / "a.gguf") == hashlib.sha256(b"weights").hexdigest()


def test_the_command_line_reports_the_manifest_check(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "a.gguf").write_bytes(b"weights")
    manifest = [entry("a.gguf", b"weights")]
    (tmp_path / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert cli.main(["models"]) == 0
    assert "1 model files checked, 0 problems" in capsys.readouterr().out
    (tmp_path / "models" / "a.gguf").write_bytes(b"changed!")
    assert cli.main(["models", "--quick"]) == 1
    assert "size differs: a.gguf" in capsys.readouterr().out
