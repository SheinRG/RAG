"""Upload validation."""

import pytest

from config import MAX_FILE_SIZE_BYTES
from utils.file_handler import get_file_type, validate_file


@pytest.mark.parametrize("name", ["a.pdf", "A.PDF", "notes.md", "sheet.xlsx", "deck.pptx"])
def test_supported_extensions_are_accepted(name):
    ok, _ = validate_file(name, 1024)
    assert ok


@pytest.mark.parametrize("name", ["run.exe", "script.sh", "archive.zip", "noextension"])
def test_unsupported_extensions_are_rejected(name):
    ok, msg = validate_file(name, 1024)
    assert not ok
    assert "not supported" in msg


def test_oversized_file_is_rejected():
    ok, msg = validate_file("big.pdf", MAX_FILE_SIZE_BYTES + 1)
    assert not ok
    assert "size" in msg.lower()


def test_file_exactly_at_the_limit_is_accepted():
    ok, _ = validate_file("edge.pdf", MAX_FILE_SIZE_BYTES)
    assert ok


def test_double_extension_uses_the_last_one():
    """report.pdf.exe must be judged on .exe, not .pdf."""
    ok, _ = validate_file("report.pdf.exe", 10)
    assert not ok


def test_get_file_type_strips_the_dot_and_lowercases():
    assert get_file_type("Report.PDF") == "pdf"
