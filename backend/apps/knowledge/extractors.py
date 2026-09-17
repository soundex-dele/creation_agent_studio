import io
import re
import zipfile
from dataclasses import dataclass


class DocumentExtractionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExtractedSection:
    text: str
    page_number: int | None = None
    section_path: tuple[str, ...] = ()


def _decode_text(content):
    if b"\x00" in content:
        raise DocumentExtractionError("invalid_text", "Text files must not contain NUL bytes.")
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentExtractionError("invalid_text_encoding", "Text must use UTF-8 or GB18030 encoding.")


def extract_document(content: bytes, filename: str, mime_type: str = ""):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf":
        if not content.startswith(b"%PDF"):
            raise DocumentExtractionError("invalid_file_signature", "The file is not a valid PDF.")
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise DocumentExtractionError("encrypted_pdf", "Encrypted PDF files are not supported.")
            sections = [
                ExtractedSection((page.extract_text() or "").strip(), page_number=index)
                for index, page in enumerate(reader.pages, start=1)
            ]
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("invalid_pdf", "Unable to parse the PDF file.") from exc
    elif extension == "docx":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise DocumentExtractionError("invalid_file_signature", "The file is not a valid DOCX.")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise DocumentExtractionError("invalid_file_signature", "The file is not a valid DOCX.")
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise DocumentExtractionError(
                    "expanded_document_too_large",
                    "Expanded DOCX content exceeds the 100 MiB safety limit.",
                )
        try:
            from docx import Document
            document = Document(io.BytesIO(content))
            sections = []
            heading = ()
            for paragraph in document.paragraphs:
                value = paragraph.text.strip()
                if not value:
                    continue
                if str(paragraph.style.name).lower().startswith("heading"):
                    heading = (value,)
                sections.append(ExtractedSection(value, section_path=heading))
        except Exception as exc:
            raise DocumentExtractionError("invalid_docx", "Unable to parse the DOCX file.") from exc
    elif extension in {"md", "markdown"}:
        heading = ()
        sections = []
        for block in re.split(r"\n\s*\n", _decode_text(content)):
            block = block.strip()
            if not block:
                continue
            match = re.match(r"^#{1,6}\s+(.+)$", block.splitlines()[0])
            if match:
                heading = (match.group(1).strip(),)
            sections.append(ExtractedSection(block, section_path=heading))
    elif extension in {"txt", "text"} or mime_type.startswith("text/"):
        sections = [ExtractedSection(_decode_text(content).strip())]
    else:
        raise DocumentExtractionError("unsupported_type", "Only PDF, DOCX, Markdown and TXT are supported.")
    sections = [section for section in sections if section.text.strip()]
    if not sections:
        raise DocumentExtractionError(
            "no_extractable_text",
            "No extractable text was found. Scanned documents require OCR, which is not enabled.",
        )
    if sum(len(section.text) for section in sections) > 5_000_000:
        raise DocumentExtractionError(
            "extracted_text_too_large",
            "Extracted text exceeds the 5,000,000 character limit.",
        )
    return sections
