from __future__ import annotations

import csv
import random
import re
import time
from pathlib import Path

import requests

from card_renderer import (
    TextLayout,
    layout_field_lines,
    render_product_card,
)
from config import (
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    REQUEST_JITTER_SECONDS,
)
from pdf_exporter import export_pdfs
from product_parser import (
    CardTextFields,
    ProductData,
    build_card_text_fields,
    normalize_model_name,
    normalize_size,
    parse_product_page,
)
from qr_reader import decode_qr_images


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
CARDS_DIR = OUTPUT_DIR / "cards"
EDITABLE_PDF_PATH = OUTPUT_DIR / "all_cards_editable.pdf"
FLATTENED_PDF_PATH = OUTPUT_DIR / "all_cards_flattened.pdf"
LOG_PATH = OUTPUT_DIR / "processing_log.csv"
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def polite_delay() -> None:
    delay = REQUEST_DELAY_SECONDS + random.uniform(0, REQUEST_JITTER_SECONDS)
    print(f"Waiting {delay:.1f}s before website request...")
    time.sleep(delay)


def parse_product_with_retries(url: str) -> ProductData:
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        polite_delay()
        try:
            return parse_product_page(url)
        except requests.HTTPError as error:
            last_error = error
            response = error.response
            status_code = response.status_code if response is not None else None
            if status_code not in RETRY_STATUS_CODES or attempt == MAX_RETRIES:
                raise
            retry_delay = 3 * attempt
            print(f"HTTP {status_code}; retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        except requests.RequestException as error:
            last_error = error
            if attempt == MAX_RETRIES:
                raise
            retry_delay = 3 * attempt
            print(f"Request error; retrying in {retry_delay}s: {error}")
            time.sleep(retry_delay)

    raise RuntimeError(f"Request failed after retries: {last_error}")


def empty_log_row(filename: str) -> dict[str, str]:
    return {
        "filename": filename,
        "status": "",
        "reason": "",
        "url": "",
        "brand": "",
        "country": "",
        "size": "",
        "model_name": "",
        "brand_country": "",
        "tile_size": "",
        "tile_name": "",
        "size_source": "",
        "wrapped_brand_country": "",
        "wrapped_tile_size": "",
        "wrapped_tile_name": "",
        "tile_name_line_spacing": "",
        "card_png": "",
        "error": "",
        "pdf_status": "",
        "pdf_error": "",
    }


def product_to_log_fields(product: ProductData) -> dict[str, str]:
    return {
        "brand": product.brand or "",
        "country": product.country or "",
        "size": product.size or "",
        "model_name": product.model_name or "",
        "size_source": product.debug_sources.get("size", "not found"),
    }


def card_text_to_log_fields(card_text: CardTextFields) -> dict[str, str]:
    return {
        "brand_country": card_text.brand_country,
        "tile_size": card_text.tile_size,
        "tile_name": card_text.tile_name,
    }


def layout_to_log_fields(layout: TextLayout) -> dict[str, str]:
    return {
        "wrapped_brand_country": " | ".join(
            layout_field_lines(layout, "brand_country")
        ),
        "wrapped_tile_size": " | ".join(
            layout_field_lines(layout, "tile_size")
        ),
        "wrapped_tile_name": " | ".join(
            layout_field_lines(layout, "tile_name")
        ),
        "tile_name_line_spacing": (
            f"1.1 (line height {layout.line_height}px, "
            f"step {layout.line_height + layout.tile_name_line_gap}px, "
            f"gap {layout.tile_name_line_gap}px)"
        ),
    }


def product_from_filename(path: Path, url: str = "") -> ProductData:
    title = re.sub(r"^QR[\s_-]*", "", path.stem, flags=re.IGNORECASE).strip()
    size = normalize_size(title)
    first_word = title.split(maxsplit=1)[0] if title else None
    model_name = normalize_model_name(title, first_word, size)
    sources = {
        "title": f"filename fallback -> {title}",
        "model_name": f"filename fallback -> {model_name or title}",
    }
    if size:
        sources["size"] = (
            f"source: filename fallback; raw: {title}; normalized: {size}"
        )

    return ProductData(
        url=url,
        title=title or path.stem,
        product_type=first_word,
        size=size,
        model_name=model_name or title or path.stem,
        debug_sources=sources,
    )


def render_candidates(card_text: CardTextFields):
    candidates = [
        ("full card text", card_text),
        (
            "brand omitted to preserve full name at fixed 14 pt",
            CardTextFields(
                brand_country="",
                tile_size=card_text.tile_size,
                tile_name=card_text.tile_name,
            ),
        ),
        (
            "brand and size omitted to preserve full name at fixed 14 pt",
            CardTextFields(
                brand_country="",
                tile_size="",
                tile_name=card_text.tile_name,
            ),
        ),
    ]
    seen = set()
    for reason, candidate in candidates:
        key = (
            candidate.brand_country,
            candidate.tile_size,
            candidate.tile_name,
        )
        if key not in seen and not candidate.is_empty():
            seen.add(key)
            yield reason, candidate


def render_with_fallback(
    qr_image_path: Path,
    card_text: CardTextFields,
    output_path: Path,
) -> tuple[CardTextFields, TextLayout, str]:
    last_error = None
    for reason, candidate in render_candidates(card_text):
        try:
            layout = render_product_card(qr_image_path, candidate, output_path)
            return candidate, layout, reason
        except ValueError as error:
            last_error = error

    raise ValueError(last_error or "Card text could not be rendered")


def write_log(rows: list[dict[str, str]]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(empty_log_row("").keys())
    with LOG_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(
    input_count: int,
    rows: list[dict[str, str]],
    cards: list[dict],
    pdf_error: str = "",
) -> None:
    decoded_count = sum(bool(row["url"]) for row in rows)
    generated_count = sum(bool(row["card_png"]) for row in rows)
    failed_rows = [row for row in rows if row["status"] == "error"]
    fallback_count = sum(row["status"] == "fallback_success" for row in rows)

    print("=" * 40)
    print("DONE")
    print(f"Input files: {input_count}")
    print(f"Logged results: {len(rows)}")
    print(f"QR decoded: {decoded_count}")
    print(f"Cards generated: {generated_count}")
    print(f"Fallback cards: {fallback_count}")
    print(f"Failed: {len(failed_rows)}")
    print(f"Editable PDF: {EDITABLE_PDF_PATH.relative_to(BASE_DIR).as_posix() if cards else '-'}")
    print(f"Flattened PDF: {FLATTENED_PDF_PATH.relative_to(BASE_DIR).as_posix() if cards else '-'}")
    print(f"Log: {LOG_PATH.relative_to(BASE_DIR).as_posix()}")
    if failed_rows:
        print("Failed files:")
        for row in failed_rows:
            print(f"- {row['filename']}: {row['error'] or row['reason']}")
    if pdf_error:
        print(f"PDF export error: {pdf_error}")
    print("=" * 40)


def main():
    results = decode_qr_images(INPUT_DIR)

    if not results:
        print(f"No image files found in: {INPUT_DIR}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    product_cache: dict[str, ProductData] = {}
    log_rows: list[dict[str, str]] = []
    pdf_cards: list[dict] = []

    for result in results:
        print(f"File: {result.path.name}")
        row = empty_log_row(result.path.name)
        row["url"] = result.url or ""
        reasons: list[str] = []
        try:
            if result.url:
                print(f"QR URL: {result.url}")
                try:
                    if result.url in product_cache:
                        print("Using cached product data.")
                        product = product_cache[result.url]
                    else:
                        product = parse_product_with_retries(result.url)
                        product_cache[result.url] = product
                except Exception as error:
                    reasons.append(f"Parser error; filename fallback used: {error}")
                    product = product_from_filename(result.path, result.url)
            else:
                qr_error = result.error or "QR code not detected"
                reasons.append(f"QR decode error; filename fallback used: {qr_error}")
                print(f"QR error: {qr_error}")
                product = product_from_filename(result.path)

            row.update(product_to_log_fields(product))
            card_text = build_card_text_fields(product)
            if card_text.is_empty():
                reasons.append("No parsed card text; filename fallback used")
                product = product_from_filename(result.path, result.url)
                row.update(product_to_log_fields(product))
                card_text = build_card_text_fields(product)

            missing_fields = [
                field_name
                for field_name in ("brand_country", "tile_size", "tile_name")
                if not getattr(card_text, field_name)
            ]
            if missing_fields:
                reasons.append(
                    "Empty fields: " + ", ".join(missing_fields)
                )

            print("Card text fields:")
            print(f"  brand_country: {card_text.brand_country}")
            print(f"  tile_size: {card_text.tile_size}")
            print(f"  tile_name: {card_text.tile_name}")
            print(f"  size source: {row['size_source']}")

            output_path = CARDS_DIR / f"{result.path.stem}_card.png"
            rendered_text, layout, render_mode = render_with_fallback(
                result.path,
                card_text,
                output_path,
            )
            if render_mode != "full card text":
                reasons.append(f"Render fallback: {render_mode}")

            row.update(card_text_to_log_fields(rendered_text))
            row.update(layout_to_log_fields(layout))
            row["status"] = "fallback_success" if reasons else "success"
            row["reason"] = "; ".join(reasons)
            row["card_png"] = output_path.relative_to(BASE_DIR).as_posix()
            pdf_card = {
                "qr_image_path": result.path,
                "card_text": rendered_text,
                "card_png_path": output_path,
                "log_row": row,
            }
            pdf_cards.append(pdf_card)

            print(f"Saved card: {row['card_png']}")
            print(f"Final status: {row['status']}")
        except Exception as error:
            row["status"] = "error"
            row["reason"] = "; ".join(reasons)
            row["error"] = f"Card generation error: {error}"
            print(f"Final status: error")
            print(row["error"])
        finally:
            print("-" * 40)
        log_rows.append(row)

    pdf_error = ""
    if pdf_cards:
        try:
            export_pdfs(pdf_cards, EDITABLE_PDF_PATH, FLATTENED_PDF_PATH)
            for card in pdf_cards:
                card["log_row"]["pdf_status"] = "success"
        except Exception as error:
            pdf_error = str(error)
            for card in pdf_cards:
                card["log_row"]["pdf_status"] = "error"
                card["log_row"]["pdf_error"] = pdf_error
            print(f"PDF export error: {pdf_error}")

    write_log(log_rows)
    print_summary(len(results), log_rows, pdf_cards, pdf_error)


if __name__ == "__main__":
    main()
