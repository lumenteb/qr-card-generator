from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from config import (
    BACKGROUND_COLOR,
    BOTTOM_SAFE_MARGIN,
    BRAND_COUNTRY_MAX_LINES,
    CARD_TEXT_FIELD_ORDER,
    CARD_TEXT_FONT_SIZE_PT,
    COMPACT_INNER_LINE_GAP,
    COMPACT_TEXT_TRACKING_PT,
    CARD_HEIGHT,
    CARD_WIDTH,
    DPI,
    FONT_CANDIDATES,
    FONT_SIZE,
    FONTS_DIR,
    INNER_LINE_GAP,
    MAX_TEXT_FIELD_GAP,
    MIN_TEXT_FIELD_GAP,
    MIN_TEXT_TRACKING_PT,
    PREFERRED_FONT_KEYWORDS,
    QR_ACTUAL_MOVE_UP_PX,
    QR_MOVE_UP_MM,
    QR_MOVE_UP_PX,
    QR_SIZE,
    QR_TO_TEXT_GAP,
    QR_TOP_MARGIN,
    TEXT_COLOR,
    TEXT_FIELD_GAP,
    TEXT_SIDE_MARGIN,
    TEXT_SIDE_MARGIN_MM,
    TEXT_TRACKING_PT,
    TILE_SIZE_LABEL,
    TILE_NAME_LINE_HEIGHT_MULTIPLIER,
    TILE_NAME_MAX_LINES,
    TILE_SIZE_MAX_LINES,
)
from product_parser import CardTextFields


MAX_FIELD_LINES = {
    "brand_country": BRAND_COUNTRY_MAX_LINES,
    "tile_size": TILE_SIZE_MAX_LINES,
    "tile_name": TILE_NAME_MAX_LINES,
}
FINISH_PREFIXES = {
    "cepillado",
    "glossy",
    "lapp",
    "leviglass",
    "mat",
    "matt",
    "matte",
    "nat",
    "natural",
    "naturale",
    "polished",
    "pul",
    "pulido",
    "rec",
    "rett",
    "satinado",
}
_FONT_INFO_PRINTED = False
_FONT_PATH_CACHE: Path | None = None

DEBUG_LAYOUT = False

@dataclass(frozen=True)
class TextLayout:
    font: ImageFont.ImageFont
    font_size: int
    brand_country_raw: str
    tile_size_raw: str
    tile_name_raw: str
    brand_country_lines: list[str]
    tile_size_lines: list[str]
    tile_name_lines: list[str]
    line_height: int
    line_gap: int
    tile_name_line_gap: int
    field_gap: int
    bottom_safe_margin: int
    total_height: int
    tracking: float
    text_area_top: int
    text_area_bottom: int
    max_text_width: int
    brand_country_y: int | None
    tile_size_y: int | None
    tile_name_y: int | None
    mode: str


def format_font_path(font_path: Path) -> str:
    try:
        return font_path.relative_to(Path(__file__).resolve().parent).as_posix()
    except ValueError:
        return font_path.as_posix()


def font_priority(font_path: Path) -> tuple[int, str]:
    name = font_path.stem.lower().replace("-", "").replace("_", "")
    if "regular" in name:
        priority = 0
    elif "medium" in name:
        priority = 1
    elif "semibold" in name:
        priority = 2
    else:
        priority = 3
    return priority, name


def find_card_font() -> Path:
    global _FONT_PATH_CACHE

    if _FONT_PATH_CACHE is not None:
        return _FONT_PATH_CACHE

    local_font_files: list[Path] = []

    if FONTS_DIR.exists():
        local_font_files = [
            path
            for path in FONTS_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".ttf", ".otf"}
            and any(
                keyword.lower() in path.stem.lower()
                for keyword in PREFERRED_FONT_KEYWORDS
            )
        ]

    candidates = [
        *sorted(local_font_files, key=font_priority),
        *FONT_CANDIDATES,
    ]

    for font_path in candidates:
        if font_path.exists() and font_path.is_file():
            _FONT_PATH_CACHE = font_path
            return _FONT_PATH_CACHE

    raise FileNotFoundError(
        "No usable font found. "
        "Add CormorantGaramond-Regular.ttf to fonts/ "
        "or update FONT_CANDIDATES in config.py."
    )


def load_font(size: int):
    global _FONT_INFO_PRINTED

    font_path = find_card_font()
    font = ImageFont.truetype(str(font_path), size=size)

    if not _FONT_INFO_PRINTED:
        print(f"Using font file: {font_path}")
        try:
            print(f"Font name: {font.getname()}")
        except Exception:
            print("Font name: unavailable")
        print(f"Rendering card with font file: {format_font_path(font_path)}")
        _FONT_INFO_PRINTED = True

    return font


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def measure_text_with_tracking(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    tracking: float = 0.0,
) -> float:
    if not text:
        return 0.0

    left, _, right, _ = text_bbox(draw, text, font)
    return float(right - left) + tracking * max(0, len(text) - 1)


def measure_line_height(draw: ImageDraw.ImageDraw, font, lines: list[str] | None = None) -> int:
    probe_lines = ["Agjpqy", *(lines or [])]
    heights = []
    for line in probe_lines:
        _, top, _, bottom = text_bbox(draw, line, font)
        heights.append(bottom - top)
    return max(1, max(heights))


def wrap_text_to_width(
    text: str,
    font,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    tracking: float,
) -> list[str]:
    words = str(text).strip().split()
    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or measure_text_with_tracking(draw, candidate, font, tracking) <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word

    if current:
        lines.append(current)

    return lines


def is_short_code_suffix(word: str) -> bool:
    cleaned = word.strip(".,;:()[]{}")
    if not 2 <= len(cleaned) <= 6:
        return False

    has_digit = any(char.isdigit() for char in cleaned)
    has_letter = any(char.isalpha() for char in cleaned)
    is_upper = cleaned.upper() == cleaned and has_letter
    return has_digit or is_upper


def starts_with_finish_descriptor(line: str) -> bool:
    words = line.lower().replace(".", "").split()
    return bool(words) and words[0] in FINISH_PREFIXES


def partition_words(words: list[str], line_count: int) -> list[list[str]]:
    if line_count < 1 or line_count > len(words):
        return []

    variants: list[list[str]] = []
    for breaks in combinations(range(1, len(words)), line_count - 1):
        start = 0
        lines = []
        for end in (*breaks, len(words)):
            lines.append(" ".join(words[start:end]))
            start = end
        variants.append(lines)

    return variants


def candidate_fits(
    lines: list[str],
    font,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    tracking: float,
) -> bool:
    return all(
        measure_text_with_tracking(draw, line, font, tracking) <= max_width
        for line in lines
    )


def score_model_candidate(
    lines: list[str],
    font,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    tracking: float,
) -> float:
    widths = [
        measure_text_with_tracking(draw, line, font, tracking)
        for line in lines
    ]
    last_word = lines[-1].split()[-1] if lines and lines[-1].split() else ""
    suffix_alone = len(lines[-1].split()) == 1 and is_short_code_suffix(last_word)

    if suffix_alone and len(lines) > 1:
        balance_widths = widths[:-1]
    else:
        balance_widths = widths

    if balance_widths:
        balance_penalty = max(balance_widths) - min(balance_widths)
        target = max_width * 0.72
        fill_penalty = sum(abs(width - target) for width in balance_widths) / len(balance_widths)
    else:
        balance_penalty = 0
        fill_penalty = 0

    orphan_penalty = 0
    for index, line in enumerate(lines):
        if len(line.split()) == 1 and not (index == len(lines) - 1 and suffix_alone):
            orphan_penalty += 180

    suffix_bonus = -350 if suffix_alone else 0
    finish_bonus = -400 if starts_with_finish_descriptor(lines[-1]) else 0
    line_count_penalty = abs(len(lines) - (3 if suffix_alone else min(2, len(lines)))) * 35

    return (
        balance_penalty * 1.2
        + fill_penalty
        + orphan_penalty
        + line_count_penalty
        + suffix_bonus
        + finish_bonus
    )


def wrap_model_name_balanced(
    text: str,
    font,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    tracking: float,
) -> list[str]:
    words = str(text).strip().split()
    if not words:
        return []

    candidates: list[list[str]] = []
    max_lines = min(TILE_NAME_MAX_LINES, len(words))

    for line_count in range(1, max_lines + 1):
        candidates.extend(partition_words(words, line_count))

    if len(words) >= 3 and is_short_code_suffix(words[-1]):
        prefix_words = words[:-1]
        suffix = words[-1]
        for prefix_lines in partition_words(prefix_words, min(2, len(prefix_words))):
            candidates.append([*prefix_lines, suffix])

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)

    fitting_candidates = [
        candidate
        for candidate in unique_candidates
        if candidate_fits(candidate, font, max_width, draw, tracking)
    ]

    if fitting_candidates:
        preferred_candidates = [
            candidate for candidate in fitting_candidates if len(candidate) <= 3
        ]
        return min(
            preferred_candidates or fitting_candidates,
            key=lambda candidate: score_model_candidate(
                candidate,
                font,
                max_width,
                draw,
                tracking,
            ),
        )

    return wrap_text_to_width(text, font, max_width, draw, tracking)


def wrap_field(
    field_name: str,
    value: str,
    font,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    tracking: float,
) -> list[str]:
    if not value:
        return []

    if field_name == "brand_country":
        lines: list[str] = []
        for explicit_line in value.splitlines():
            lines.extend(
                wrap_text_to_width(
                    explicit_line,
                    font,
                    max_width,
                    draw,
                    tracking,
                )
            )
        return lines

    if field_name == "tile_name":
        normalized_value = " ".join(value.splitlines())
        return wrap_model_name_balanced(
            normalized_value,
            font,
            max_width,
            draw,
            tracking,
        )

    return wrap_text_to_width(value, font, max_width, draw, tracking)


def calculate_field_height(
    field_name: str,
    lines: list[str],
    line_height: int,
    inner_line_gap: int,
    tile_name_line_gap: int,
) -> int:
    if not lines:
        return 0
    line_gap = (
        tile_name_line_gap
        if field_name == "tile_name"
        else inner_line_gap
    )
    return len(lines) * line_height + (len(lines) - 1) * line_gap


def card_text_values(card_text: CardTextFields) -> dict[str, str]:
    return {
        field_name: str(getattr(card_text, field_name, "") or "").strip()
        for field_name in CARD_TEXT_FIELD_ORDER
    }


def display_text_values(card_text: CardTextFields) -> dict[str, str]:
    values = card_text_values(card_text)
    if values["tile_size"]:
        size = values["tile_size"]
        if not size.casefold().startswith(TILE_SIZE_LABEL.casefold()):
            values["tile_size"] = f"{TILE_SIZE_LABEL} {size}"
    return values


def layout_field_lines(layout: TextLayout, field_name: str) -> list[str]:
    return getattr(layout, f"{field_name}_lines")


def layout_field_y(layout: TextLayout, field_name: str) -> int | None:
    return getattr(layout, f"{field_name}_y")


def layout_field_line_gap(layout: TextLayout, field_name: str) -> int:
    if field_name == "tile_name":
        return layout.tile_name_line_gap
    return layout.line_gap


def make_layout_candidate(
    card_text: CardTextFields,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    text_area_top: int,
    text_area_bottom: int,
    inner_line_gap: int,
    tracking: float,
    mode: str,
) -> TextLayout:
    font = load_font(FONT_SIZE)
    raw_values = card_text_values(card_text)
    values = display_text_values(card_text)
    wrapped_fields = {
        field_name: wrap_field(
            field_name,
            values[field_name],
            font,
            max_width,
            draw,
            tracking,
        )
        for field_name in CARD_TEXT_FIELD_ORDER
    }
    all_lines = [
        line
        for field_name in CARD_TEXT_FIELD_ORDER
        for line in wrapped_fields[field_name]
    ]
    line_height = measure_line_height(draw, font, all_lines)
    tile_name_line_step = round(FONT_SIZE * TILE_NAME_LINE_HEIGHT_MULTIPLIER)
    tile_name_line_gap = max(
        0,
        tile_name_line_step - line_height,
    )
    visible_field_names = [
        field_name
        for field_name in CARD_TEXT_FIELD_ORDER
        if wrapped_fields[field_name]
    ]
    field_heights = {
        field_name: calculate_field_height(
            field_name,
            wrapped_fields[field_name],
            line_height,
            inner_line_gap,
            tile_name_line_gap,
        )
        for field_name in CARD_TEXT_FIELD_ORDER
    }
    fields_height = sum(field_heights[name] for name in visible_field_names)
    gap_count = max(0, len(visible_field_names) - 1)
    available_height = text_area_bottom - text_area_top

    if gap_count:
        maximum_fitting_gap = (available_height - fields_height) // gap_count
        field_gap = max(
            0,
            min(
                TEXT_FIELD_GAP,
                MAX_TEXT_FIELD_GAP,
                maximum_fitting_gap,
            ),
        )
    else:
        field_gap = 0

    positions: dict[str, int | None] = {
        field_name: None for field_name in CARD_TEXT_FIELD_ORDER
    }
    cursor_y = text_area_top
    for index, field_name in enumerate(visible_field_names):
        positions[field_name] = cursor_y
        cursor_y += field_heights[field_name]
        if index < len(visible_field_names) - 1:
            cursor_y += field_gap

    total_height = fields_height + gap_count * field_gap
    if field_gap < TEXT_FIELD_GAP and gap_count:
        mode = f"{mode}, fitted field gap"

    return TextLayout(
        font=font,
        font_size=FONT_SIZE,
        brand_country_raw=raw_values["brand_country"],
        tile_size_raw=raw_values["tile_size"],
        tile_name_raw=raw_values["tile_name"],
        brand_country_lines=wrapped_fields["brand_country"],
        tile_size_lines=wrapped_fields["tile_size"],
        tile_name_lines=wrapped_fields["tile_name"],
        line_height=line_height,
        line_gap=inner_line_gap,
        tile_name_line_gap=tile_name_line_gap,
        field_gap=field_gap,
        bottom_safe_margin=BOTTOM_SAFE_MARGIN,
        total_height=total_height,
        tracking=tracking,
        text_area_top=text_area_top,
        text_area_bottom=text_area_bottom,
        max_text_width=max_width,
        brand_country_y=positions["brand_country"],
        tile_size_y=positions["tile_size"],
        tile_name_y=positions["tile_name"],
        mode=mode,
    )


def layout_fits(
    layout: TextLayout,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> bool:
    line_counts_fit = all(
        len(layout_field_lines(layout, field_name)) <= MAX_FIELD_LINES[field_name]
        for field_name in CARD_TEXT_FIELD_ORDER
    )
    widths_fit = all(
        measure_text_with_tracking(
            draw,
            line,
            layout.font,
            layout.tracking,
        ) <= max_width
        for field_name in CARD_TEXT_FIELD_ORDER
        for line in layout_field_lines(layout, field_name)
    )
    visible_field_count = sum(
        bool(layout_field_lines(layout, field_name))
        for field_name in CARD_TEXT_FIELD_ORDER
    )
    gap_fits = (
        visible_field_count <= 1
        or layout.field_gap >= MIN_TEXT_FIELD_GAP
    )
    vertical_fits = (
        layout.text_area_top + layout.total_height
        <= layout.text_area_bottom
    )
    return line_counts_fit and widths_fit and gap_fits and vertical_fits


def build_card_text_layout(
    card_text: CardTextFields,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    text_area_top: int,
    text_area_bottom: int,
) -> TextLayout:
    px_per_pt = DPI / 72
    attempts = (
        (
            INNER_LINE_GAP,
            TEXT_TRACKING_PT * px_per_pt,
            "normal grid",
        ),
        (
            COMPACT_INNER_LINE_GAP,
            TEXT_TRACKING_PT * px_per_pt,
            "compact inner grid",
        ),
        (
            COMPACT_INNER_LINE_GAP,
            COMPACT_TEXT_TRACKING_PT * px_per_pt,
            "compact inner grid and tracking",
        ),
        (
            COMPACT_INNER_LINE_GAP,
            MIN_TEXT_TRACKING_PT * px_per_pt,
            "minimum tracking",
        ),
    )

    for inner_line_gap, tracking, mode in attempts:
        layout = make_layout_candidate(
            card_text,
            draw,
            max_width,
            text_area_top,
            text_area_bottom,
            inner_line_gap,
            tracking,
            mode,
        )
        if layout_fits(layout, max_width, draw):
            return layout

    raise ValueError(
        f"Text does not fit at fixed {CARD_TEXT_FONT_SIZE_PT:g} pt font size"
    )


def build_text_layout(
    card_text: CardTextFields,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    available_height: int,
) -> TextLayout:
    """Compatibility alias for callers using the previous function name."""
    return build_card_text_layout(
        card_text,
        draw,
        max_width,
        0,
        available_height,
    )


def trim_large_white_border(image: Image.Image) -> Image.Image:
    rgb_image = image.convert("RGB")
    background = Image.new("RGB", rgb_image.size, BACKGROUND_COLOR)
    diff = ImageChops.difference(rgb_image, background)
    bbox = diff.getbbox()

    if not bbox:
        return rgb_image

    left, top, right, bottom = bbox
    width, height = rgb_image.size
    content_width = right - left
    content_height = bottom - top

    if content_width > width * 0.92 and content_height > height * 0.92:
        return rgb_image

    padding = max(12, int(max(content_width, content_height) * 0.06))
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width, right + padding)
    bottom = min(height, bottom + padding)

    return rgb_image.crop((left, top, right, bottom))


def prepare_qr_image(qr_image_path: Path) -> Image.Image:
    qr_image = Image.open(qr_image_path).convert("RGB")
    qr_image = trim_large_white_border(qr_image)
    resample = getattr(getattr(Image, "Resampling", Image), "NEAREST")
    return qr_image.resize((QR_SIZE, QR_SIZE), resample)


def draw_centered_text_with_tracking(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font,
    tracking: float = 0.0,
) -> None:
    if not text:
        return

    left, top, right, _ = text_bbox(draw, text, font)
    visual_width = (right - left) + tracking * max(0, len(text) - 1)
    origin_x = (CARD_WIDTH - visual_width) / 2 - left
    origin_y = y - top

    if tracking == 0:
        draw.text((origin_x, origin_y), text, fill=TEXT_COLOR, font=font)
        return

    for index, character in enumerate(text):
        prefix_width = draw.textlength(text[:index], font=font)
        x = origin_x + prefix_width + tracking * index
        draw.text((x, origin_y), character, fill=TEXT_COLOR, font=font)


def draw_text_layout(
    draw: ImageDraw.ImageDraw,
    layout: TextLayout,
) -> None:
    for field_name in CARD_TEXT_FIELD_ORDER:
        lines = layout_field_lines(layout, field_name)
        y = layout_field_y(layout, field_name)
        if not lines or y is None:
            continue
        for line_index, line in enumerate(lines):
            draw_centered_text_with_tracking(
                draw,
                line,
                y,
                layout.font,
                layout.tracking,
            )
            y += layout.line_height
            if line_index < len(lines) - 1:
                y += layout_field_line_gap(layout, field_name)


def layout_bottom_y(layout: TextLayout) -> int:
    return layout.text_area_top + layout.total_height


def print_layout_debug(layout: TextLayout) -> None:
    print(f"Card size: {CARD_WIDTH} x {CARD_HEIGHT} px")
    print(f"QR size: {QR_SIZE} x {QR_SIZE} px")
    print(f"QR top margin: {QR_TOP_MARGIN} px")
    print(f"QR moved up by requested: {QR_MOVE_UP_MM} mm ({QR_MOVE_UP_PX} px)")
    print(f"QR moved up by actual: {QR_ACTUAL_MOVE_UP_PX} px")
    print(f"QR to text gap: {QR_TO_TEXT_GAP} px")
    print(f"Text side margin mm: {TEXT_SIDE_MARGIN_MM:g}")
    print(f"Text max width: {layout.max_text_width} px")
    print(f"Text area top: {layout.text_area_top} px")
    print(f"Text area bottom: {layout.text_area_bottom} px")
    print(f"Layout mode: {layout.mode}")
    print(f"Selected font size pt: {CARD_TEXT_FONT_SIZE_PT:g}")
    print(f"Selected font size px: {layout.font_size}")
    print(f"Inner line gap: {layout.line_gap} px")
    print(
        "Tile name line spacing: "
        f"{TILE_NAME_LINE_HEIGHT_MULTIPLIER:g} "
        f"(step {layout.line_height + layout.tile_name_line_gap} px, "
        f"gap {layout.tile_name_line_gap} px)"
    )
    print(f"Computed field gap: {layout.field_gap} px")
    print(f"Text group total height: {layout.total_height} px")
    print(f"Tracking applied: {layout.tracking:.2f} px")
    for field_name in CARD_TEXT_FIELD_ORDER:
        print(f"{field_name} raw: {getattr(layout, f'{field_name}_raw')}")
        print(
            f"{field_name} wrapped lines: "
            f"{layout_field_lines(layout, field_name)}"
        )
        print(f"{field_name} block y: {layout_field_y(layout, field_name)}")


def render_product_card(
    qr_image_path: Path,
    card_text: CardTextFields,
    output_path: Path,
) -> TextLayout:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BACKGROUND_COLOR)
    qr_image = prepare_qr_image(qr_image_path)

    qr_x = (CARD_WIDTH - QR_SIZE) // 2
    card.paste(qr_image, (qr_x, QR_TOP_MARGIN))

    draw = ImageDraw.Draw(card)
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

    final_bottom = layout_bottom_y(layout)
    safe_bottom = CARD_HEIGHT - layout.bottom_safe_margin
    if final_bottom > safe_bottom:
        raise ValueError(
            f"Text layout does not fit: bottom {final_bottom}px > safe bottom {safe_bottom}px"
        )

    if DEBUG_LAYOUT:
        print_layout_debug(layout)

    draw_text_layout(draw, layout)

    card.save(output_path, "PNG", dpi=(DPI, DPI))
    return layout
