from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_PDF_BYTES = 20 * 1024 * 1024   # 20mb image limit

def pdf_to_image_bytes(pdf_bytes: bytes, page: int = 0) -> tuple[bytes, str]:
    """
    Convert one PDF page to JPEG bytes for vision API input.
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")

    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise ValueError(f"PDF too large ({len(pdf_bytes)} bytes) — max {_MAX_PDF_BYTES}")

    try:
        from pdf2image import convert_from_bytes  # type: ignore
        import io
        images = convert_from_bytes(
            pdf_bytes, first_page=page + 1, last_page=page + 1, dpi=150
        )
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="JPEG", quality=85)
            logger.debug("pdf_to_image_bytes: pdf2image succeeded page=%d", page)
            return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.debug("pdf_to_image_bytes: pdf2image failed, trying fallback: %s", exc)

    try:
        import io
        import pypdf
        from PIL import Image, ImageDraw  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        target = min(page, len(reader.pages) - 1)
        text = reader.pages[target].extract_text() or ""

        img = Image.new("RGB", (800, 1100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        y = 20
        for line in text.splitlines():
            draw.text((20, y), line[:120], fill=(0, 0, 0))
            y += 16
            if y > 1060:
                break

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        logger.debug("pdf_to_image_bytes: pillow fallback succeeded page=%d", page)
        return buf.getvalue(), "image/jpeg"

    except Exception as exc:
        raise ValueError(f"pdf_to_image_bytes: both strategies failed: {exc}") from exc

def enrich_vision_prompt(base_prompt: str, client_id: str) -> str:
    """
    Append a small client-specific tax/currency block to an existing vision prompt.
    """
    if not client_id:
        return base_prompt

    try:
        from config.client_config import get_client_financial_config
        fc = get_client_financial_config(client_id)

        base_currency = fc.get("base_currency", "")
        tax_name      = fc.get("tax_name", "")
        tax_rate      = float(fc.get("tax_rate", 0.0))
        tax_inclusive = fc.get("tax_inclusive", False)

        lines: list[str] = []

        if base_currency:
            lines.append(f"Default currency for this client: {base_currency}.")

        if tax_inclusive and tax_rate > 0 and tax_name:
            pct = round(tax_rate * 100)
            lines.append(
                f"Amounts on documents for this client INCLUDE {tax_name} at {pct}%. "
                f"Extract the TOTAL (tax-inclusive) as 'amount' and the {tax_name} "
                f"portion as 'tax_amount'."
            )

        if not lines:
            return base_prompt

        injection = "\n\nCLIENT CONTEXT:\n" + "\n".join(lines)
        return base_prompt + injection

    except Exception as exc:
        logger.debug("enrich_vision_prompt failed client=%s (returning base): %s", client_id, exc)
        return base_prompt

def to_base_currency(
    amount: float,
    from_currency: str,
    client_id: str,
) -> tuple[float, float]:
    """
    Convert amount to the client's base currency.
    """
    try:
        from config.client_config import get_client_financial_config
        fc = get_client_financial_config(client_id)

        if not fc.get("fx_enabled", False):
            return round(amount, 2), 1.0

        base = fc.get("base_currency", "USD").upper()
        src  = (from_currency or base).upper()

        if src == base:
            return round(amount, 2), 1.0

        rate = _get_fx_rate(src, base)
        if rate is None:
            logger.warning(
                "to_base_currency: rate unavailable %s→%s client=%s", src, base, client_id
            )
            return round(amount, 2), 1.0

        converted = round(amount * rate, 2)
        logger.info(
            "FX %s %.2f → %s %.2f (rate %.4f) client=%s",
            src, amount, base, converted, rate, client_id,
        )
        return converted, rate

    except Exception as exc:
        logger.warning("to_base_currency failed client=%s: %s", client_id, exc)
        return round(amount, 2), 1.0


def _get_fx_rate(from_currency: str, to_currency: str) -> float | None:
    """Fetch rate with 6-hour Redis cache. Returns None on any failure."""
    import httpx

    try:
        import redis as redis_lib
        from config.settings import settings
        _redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

        cache_key = f"fx:{from_currency}:{to_currency}"
        cached = _redis.get(cache_key)
        if cached:
            return round(float(str(cached)), 6)

        rate = None

        try:
            resp = httpx.get(
                f"https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}",
                timeout=10,
            )
            resp.raise_for_status()
            rate = resp.json().get("rates", {}).get(to_currency)
        except Exception:
            pass

        if not rate:
            resp = httpx.get(
                f"https://api.exchangerate-api.com/v4/latest/{from_currency}",
                timeout=10,
            )
            resp.raise_for_status()
            rate = resp.json().get("rates", {}).get(to_currency)

        if rate:
            rate = round(float(rate), 6)
            _redis.setex(cache_key, 21600, str(rate))
        return rate if rate else None

    except Exception as exc:
        logger.warning("_get_fx_rate %s→%s failed: %s", from_currency, to_currency, exc)
        return None