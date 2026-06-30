from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from card_renderer import (
    build_card_text_layout,
    find_cormorant_font,
    layout_field_lines,
    layout_field_line_gap,
    layout_field_y,
    prepare_qr_image,
)
from config import (
    BACKGROUND_COLOR,
    BOTTOM_SAFE_MARGIN,
    CARD_HEIGHT,
    CARD_TEXT_FIELD_ORDER,
    CARD_TEXT_FONT_SIZE_PT,
    CARD_WIDTH,
    DPI,
    QR_SIZE,
    QR_TO_TEXT_GAP,
    QR_TOP_MARGIN,
    TEXT_COLOR,
    TEXT_SIDE_MARGIN,
)
from product_parser import CardTextFields


PDF_FONT_NAME = "CormorantGaramond"


def px_to_pt(value: float) -> float:
    return value / DPI * 72


def page_size_points() -> tuple[float, float]:
    return px_to_pt(CARD_WIDTH), px_to_pt(CARD_HEIGHT)


def register_pdf_font() -> Path:
    font_path = find_cormorant_font()
    registered = set(pdfmetrics.getRegisteredFontNames())
    if PDF_FONT_NAME not in registered:
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(font_path)))
    return font_path


def build_layout_for_pdf(card_text: CardTextFields):
    dummy = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(dummy)
    max_text_width = CARD_WIDTH - (TEXT_SIDE_MARGIN * 2)
    text_start_y = QR_TOP_MARGIN + QR_SIZE + QR_TO_TEXT_GAP
    text_area_bottom = CARD_HEIGHT - BOTTOM_SAFE_MARGIN
    layout = build_card_text_layout(
        card_text,
        draw,
        max_text_width,
        text_start_y,
        text_area_bottom,
    )
    return layout


def draw_centered_pdf_text(
    c: canvas.Canvas,
    text: str,
    baseline_y: float,
    page_width: float,
    tracking_pt: float,
) -> None:
    text_width = pdfmetrics.stringWidth(
        text,
        PDF_FONT_NAME,
        CARD_TEXT_FONT_SIZE_PT,
    )
    text_width += tracking_pt * max(0, len(text) - 1)
    text_object = c.beginText()
    text_object.setTextOrigin((page_width - text_width) / 2, baseline_y)
    text_object.setFont(PDF_FONT_NAME, CARD_TEXT_FONT_SIZE_PT)
    text_object.setCharSpace(tracking_pt)
    text_object.textOut(text)
    c.drawText(text_object)


def draw_editable_card_page(
    c: canvas.Canvas,
    qr_image_path: Path,
    card_text: CardTextFields,
) -> None:
    page_width, page_height = page_size_points()
    c.setFillColorRGB(*(channel / 255 for channel in BACKGROUND_COLOR))
    c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    qr_image = prepare_qr_image(qr_image_path)
    qr_size_pt = px_to_pt(QR_SIZE)
    qr_x = px_to_pt((CARD_WIDTH - QR_SIZE) / 2)
    qr_y = page_height - px_to_pt(QR_TOP_MARGIN + QR_SIZE)
    c.drawImage(ImageReader(qr_image), qr_x, qr_y, width=qr_size_pt, height=qr_size_pt, mask="auto")

    layout = build_layout_for_pdf(card_text)
    baseline_offset = CARD_TEXT_FONT_SIZE_PT * 0.78
    tracking_pt = px_to_pt(layout.tracking)

    c.setFillColorRGB(*(channel / 255 for channel in TEXT_COLOR))

    for field_name in CARD_TEXT_FIELD_ORDER:
        lines = layout_field_lines(layout, field_name)
        y_px = layout_field_y(layout, field_name)
        if not lines or y_px is None:
            continue
        for line_index, line in enumerate(lines):
            baseline_y = page_height - px_to_pt(y_px) - baseline_offset
            draw_centered_pdf_text(
                c,
                line,
                baseline_y,
                page_width,
                tracking_pt,
            )
            y_px += layout.line_height
            if line_index < len(lines) - 1:
                y_px += layout_field_line_gap(layout, field_name)


def export_editable_pdf(cards: list[dict], output_path: Path) -> None:
    if not cards:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    register_pdf_font()
    c = canvas.Canvas(str(output_path), pagesize=page_size_points())
    c.setTitle("QR Product Cards Editable")

    for card in cards:
        draw_editable_card_page(c, card["qr_image_path"], card["card_text"])
        c.showPage()

    c.save()


def export_flattened_pdf(cards: list[dict], output_path: Path) -> None:
    if not cards:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for card in cards:
        image = Image.open(card["card_png_path"]).convert("RGB")
        images.append(image)

    first, rest = images[0], images[1:]
    first.save(output_path, "PDF", save_all=True, append_images=rest, resolution=DPI)


def export_pdfs(cards: list[dict], editable_pdf_path: Path, flattened_pdf_path: Path) -> None:
    export_editable_pdf(cards, editable_pdf_path)
    export_flattened_pdf(cards, flattened_pdf_path)
