"""
app/parser.py
-------------
Step 1: Document upload and text extraction.

Supports DOCX and PDF file formats.
Returns clean plain-text content from the uploaded regulatory document.
"""

import io
import pdfplumber
from docx import Document


def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extract plain text from a DOCX file.

    Args:
        file_bytes: Raw bytes of the uploaded DOCX file.

    Returns:
        Extracted text as a single string.
    """
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract plain text from a PDF file.

    Args:
        file_bytes: Raw bytes of the uploaded PDF file.

    Returns:
        Extracted text as a single string.
    """
    pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    return "\n".join(pages)


def parse_document(file_bytes: bytes, filename: str) -> str:
    """
    Detect file type and extract text accordingly.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename (used to determine file type).

    Returns:
        Extracted plain text from the document.

    Raises:
        ValueError: If the file type is not supported.
    """
    lower_name = filename.lower()

    if lower_name.endswith(".docx"):
        return extract_text_from_docx(file_bytes)
    elif lower_name.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    else:
        raise ValueError(
            f"Unsupported file type: '{filename}'. "
            "Please upload a .docx or .pdf file."
        )


def get_document_preview(text: str, max_chars: int = 500) -> str:
    """
    Return a short preview of the extracted document text.

    Args:
        text:      Full extracted text.
        max_chars: Maximum characters to include in the preview.

    Returns:
        Truncated text with an ellipsis if truncated.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
