"""Contain file processor backend logic."""
import io
import httpx
import csv
import logging
import threading

logger = logging.getLogger(__name__)
MAX_EXTRACTED_CHARS = 6000
_BINARY_MIME_PREFIXES = ("image/", "audio/", "video/")
_BINARY_MIME_TYPES = {
    "application/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
}

_docling_converter = None
_docling_lock = threading.Lock()


def _get_docling_converter():
    global _docling_converter
    if _docling_converter is None:
        with _docling_lock:
            if _docling_converter is None:
                from docling.document_converter import DocumentConverter
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import PdfFormatOption

                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = False
                pipeline_options.do_table_structure = False

                _docling_converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                    }
                )
                logger.info("Docling converter initialized (singleton)")
    return _docling_converter


def extract_text_from_bytes(data: bytes, mime_type: str, filename: str = "") -> str:
    mt = mime_type.lower()
    if mt == "application/pdf" or filename.endswith(".pdf"):
        return _extract_pdf(data)
    if mt in ("text/csv", "application/csv") or filename.endswith(".csv"):
        return _extract_csv(data)
    if mt.startswith(_BINARY_MIME_PREFIXES) or mt in _BINARY_MIME_TYPES:
        return ""
    try:
        return data.decode("utf-8", errors="ignore")[:MAX_EXTRACTED_CHARS]
    except Exception:
        return ""


def _extract_pdf(data: bytes) -> str:
    import redis as redis_lib
    from config.settings import settings
    import tempfile
    import os

    _redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
    semaphore_key = "docling:active_count"
    MAX_CONCURRENT = 5

    acquired = False
    try:
        pipe = _redis.pipeline()
        pipe.incr(semaphore_key)
        pipe.expire(semaphore_key, 120)
        results = pipe.execute()
        current = int(str(results[0]))

        if current > MAX_CONCURRENT:
            _redis.decr(semaphore_key)
            logger.info(
                "Docling semaphore full (%d/%d) — falling back to pypdf",
                current, MAX_CONCURRENT,
            )
            return _extract_pdf_fallback(data)

        acquired = True
        converter = _get_docling_converter()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            result = converter.convert(tmp_path)
            text = result.document.export_to_markdown()
            logger.info("Docling PDF extraction succeeded len=%d", len(text))
            return text[:MAX_EXTRACTED_CHARS]
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.warning("docling PDF extraction failed, falling back to pypdf: %s", e)
        return _extract_pdf_fallback(data)

    finally:
        if acquired:
            try:
                current = int(str(_redis.get(semaphore_key) or 0))
                if current > 0:
                    _redis.decr(semaphore_key)
            except Exception:
                pass


def _extract_pdf_fallback(data: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
        return text[:MAX_EXTRACTED_CHARS]
    except Exception as e:
        raise ValueError(f"PDF extraction failed: {e}")


def _extract_csv(data: bytes) -> str:
    try:
        text = data.decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return text[:MAX_EXTRACTED_CHARS]
        result = "\n".join(
            ", ".join(f"{k}: {v}" for k, v in row.items())
            for row in rows
        )
        return result[:MAX_EXTRACTED_CHARS]
    except Exception as e:
        raise ValueError(f"CSV extraction failed: {e}")


def fetch_and_extract(
    url: str = "",
    headers: dict | None = None,
    mime_type: str = "",
    filename: str = "",
    data: bytes | None = None,
) -> tuple[str, bytes]:
    if data is None:
        if not url:
            raise ValueError("fetch_and_extract: url or data required")
        resp = httpx.get(url, headers=headers or {}, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        mime_type = mime_type or resp.headers.get("content-type", "").split(";")[0].strip()
    text = extract_text_from_bytes(data, mime_type, filename)
    return text, data