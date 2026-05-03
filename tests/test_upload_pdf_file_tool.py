from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.agent_tools import upload_pdf_file


PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n"
    b"<< /Type /Catalog /Pages 2 0 R >>\n"
    b"endobj\n"
    b"trailer\n"
    b"<< /Root 1 0 R >>\n"
    b"%%EOF\n"
)

FAKE_URI = "https://generativelanguage.googleapis.com/v1beta/files/abc123"


@pytest.mark.asyncio
async def test_upload_pdf_file_returns_uri_for_existing_pdf(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)

    mock_uploaded = MagicMock()
    mock_uploaded.uri = FAKE_URI

    with patch("tools.agent_tools.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.files.upload.return_value = mock_uploaded
        mock_client_cls.return_value = mock_client

        response = await upload_pdf_file.run_async(
            args={"filename": pdf_path.as_posix()},
            tool_context=None,
        )

    assert response["status"] == "success"
    assert response["filename"] == pdf_path.as_posix()
    assert response["file_uri"] == FAKE_URI
    assert response["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_pdf_file_returns_error_for_missing_file(tmp_path):
    missing_path = tmp_path / "missing.pdf"

    response = await upload_pdf_file.run_async(
        args={"filename": missing_path.as_posix()},
        tool_context=None,
    )

    assert response["status"] == "error"
    assert "File not found" in response["message"]


@pytest.mark.asyncio
async def test_upload_pdf_file_uses_cache_on_second_call(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)

    cache_file = tmp_path / "file_cache.json"
    cache_file.write_text(json.dumps({pdf_path.name: FAKE_URI}))

    with patch("tools.agent_tools.genai.Client") as mock_client_cls:
        response = await upload_pdf_file.run_async(
            args={"filename": pdf_path.as_posix()},
            tool_context=None,
        )
        mock_client_cls.assert_not_called()

    assert response["status"] == "success"
    assert response["file_uri"] == FAKE_URI


@pytest.mark.asyncio
async def test_upload_pdf_file_writes_cache_after_upload(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)

    mock_uploaded = MagicMock()
    mock_uploaded.uri = FAKE_URI

    with patch("tools.agent_tools.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.files.upload.return_value = mock_uploaded
        mock_client_cls.return_value = mock_client

        await upload_pdf_file.run_async(
            args={"filename": pdf_path.as_posix()},
            tool_context=None,
        )

    cache_file = tmp_path / "file_cache.json"
    assert cache_file.exists()
    cache_data = json.loads(cache_file.read_text())
    assert cache_data[pdf_path.name] == FAKE_URI
