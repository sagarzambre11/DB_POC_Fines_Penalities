"""
app/parser.py
-------------
Step 1: Document upload and text extraction.

Supports DOCX and PDF file formats.
Returns clean plain-text content from the uploaded regulatory document.
"""

import io
import re
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


def clean_document_text(text: str, max_chars: int = 40_000) -> str:
    """
    Remove noise from extracted document text and cap length.

    Collapses excessive whitespace, removes page-number patterns,
    and truncates to max_chars to avoid sending excessive tokens to
    the LLM.  40,000 characters ≈ ~30,000 tokens — sufficient for
    any enforcement document while reducing extraction costs by 30-50%.

    Args:
        text:      Raw extracted text.
        max_chars: Maximum characters to keep (default 40,000).

    Returns:
        Cleaned and optionally truncated text.
    """
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Collapse 2+ spaces to 1
    text = re.sub(r' {2,}', ' ', text)
    # Remove common page-number patterns
    text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
    # Collapse any new excessive whitespace introduced by removals
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    # Cap length
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[Document truncated for processing]"
    return text


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
        return clean_document_text(extract_text_from_docx(file_bytes))
    elif lower_name.endswith(".pdf"):
        return clean_document_text(extract_text_from_pdf(file_bytes))
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
