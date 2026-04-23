from __future__ import annotations

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from tools.agent_tools import load_pdf_file


PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n"
    b"<< /Type /Catalog /Pages 2 0 R >>\n"
    b"endobj\n"
    b"2 0 obj\n"
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
    b"endobj\n"
    b"3 0 obj\n"
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\n"
    b"endobj\n"
    b"trailer\n"
    b"<< /Root 1 0 R >>\n"
    b"%%EOF\n"
)


@pytest.mark.asyncio
async def test_load_pdf_file_returns_metadata_for_existing_pdf(tmp_path):
    pdf_path = tmp_path / "table-heavy-paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)

    response = await load_pdf_file.run_async(
        args={"filename": pdf_path.as_posix()},
        tool_context=None,
    )

    assert response["status"] == "success"
    assert response["filename"] == pdf_path.as_posix()
    assert response["mime_type"] == "application/pdf"
    assert response["size_bytes"] == len(PDF_BYTES)


@pytest.mark.asyncio
async def test_load_pdf_file_attaches_original_pdf_bytes_to_llm_request(tmp_path):
    pdf_path = tmp_path / "table-heavy-paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    response = await load_pdf_file.run_async(
        args={"filename": pdf_path.as_posix()},
        tool_context=None,
    )

    request = LlmRequest(
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name="load_pdf_file",
                        response=response,
                    )
                ],
            )
        ]
    )

    await load_pdf_file.process_llm_request(
        tool_context=None,
        llm_request=request,
    )

    assert len(request.contents) == 2
    attached_pdf_part = request.contents[-1].parts[-1]
    assert attached_pdf_part.inline_data is not None
    assert attached_pdf_part.inline_data.mime_type == "application/pdf"
    assert attached_pdf_part.inline_data.data == PDF_BYTES


@pytest.mark.asyncio
async def test_load_pdf_file_does_not_attach_pdf_after_error_response(tmp_path):
    missing_path = tmp_path / "missing.pdf"
    response = await load_pdf_file.run_async(
        args={"filename": missing_path.as_posix()},
        tool_context=None,
    )
    request = LlmRequest(
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name="load_pdf_file",
                        response=response,
                    )
                ],
            )
        ]
    )

    await load_pdf_file.process_llm_request(
        tool_context=None,
        llm_request=request,
    )

    assert response["status"] == "error"
    assert len(request.contents) == 1


@pytest.mark.asyncio
async def test_load_pdf_file_rejects_non_pdf_suffix(tmp_path):
    text_path = tmp_path / "paper.txt"
    text_path.write_text("not a pdf", encoding="utf-8")

    response = await load_pdf_file.run_async(
        args={"filename": text_path.as_posix()},
        tool_context=None,
    )

    assert response["status"] == "error"
    assert "Expected a PDF file" in response["message"]
