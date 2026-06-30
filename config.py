from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DPI = 300

CARD_WIDTH_MM = 42
CARD_HEIGHT_MM = 60
QR_SIZE_MM = 26.5
CARD_TEXT_FONT_SIZE_PT = 14
FONT_SIZE_PT = CARD_TEXT_FONT_SIZE_PT


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return round(mm / 25.4 * dpi)


def pt_to_px(pt: float, dpi: int = DPI) -> int:
    return round(pt / 72 * dpi)


CARD_WIDTH = mm_to_px(CARD_WIDTH_MM)
CARD_HEIGHT = mm_to_px(CARD_HEIGHT_MM)
QR_SIZE = mm_to_px(QR_SIZE_MM)
FONT_SIZE = pt_to_px(FONT_SIZE_PT)

QR_TOP_MARGIN_ORIGINAL_MM = 4.8
QR_MOVE_UP_MM = 2.0
QR_TOP_MARGIN = max(0, mm_to_px(QR_TOP_MARGIN_ORIGINAL_MM - QR_MOVE_UP_MM))
QR_MOVE_UP_PX = mm_to_px(QR_MOVE_UP_MM)
QR_ACTUAL_MOVE_UP_PX = mm_to_px(QR_TOP_MARGIN_ORIGINAL_MM) - QR_TOP_MARGIN
QR_TO_TEXT_GAP = mm_to_px(1.7)
BOTTOM_SAFE_MARGIN = mm_to_px(1.0)

TEXT_SIDE_MARGIN_MM = 1.7
TEXT_FIELD_GAP_MM = 1.6
MIN_TEXT_FIELD_GAP_MM = 1.1
MAX_TEXT_FIELD_GAP_MM = 2.2
INNER_LINE_GAP_MM = 0.35
COMPACT_INNER_LINE_GAP_MM = 0.2
BRAND_COUNTRY_MAX_LINES = 2
TILE_SIZE_MAX_LINES = 1
TILE_NAME_MAX_LINES = 4
TILE_NAME_LINE_HEIGHT_MULTIPLIER = 1.1

TEXT_SIDE_MARGIN = mm_to_px(TEXT_SIDE_MARGIN_MM)
TEXT_FIELD_GAP = mm_to_px(TEXT_FIELD_GAP_MM)
MIN_TEXT_FIELD_GAP = mm_to_px(MIN_TEXT_FIELD_GAP_MM)
MAX_TEXT_FIELD_GAP = mm_to_px(MAX_TEXT_FIELD_GAP_MM)
INNER_LINE_GAP = mm_to_px(INNER_LINE_GAP_MM)
COMPACT_INNER_LINE_GAP = mm_to_px(COMPACT_INNER_LINE_GAP_MM)

CARD_TEXT_FIELD_ORDER = ("brand_country", "tile_size", "tile_name")
TILE_SIZE_LABEL = "\u041f\u043b\u0438\u0442\u043a\u0430"
TEXT_TRACKING_PT = 0.0
COMPACT_TEXT_TRACKING_PT = -0.2
MIN_TEXT_TRACKING_PT = -0.5

BACKGROUND_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 0, 0)

FONTS_DIR = BASE_DIR / "fonts"
PREFERRED_FONT_KEYWORDS = ["Cormorant", "CormorantGaramond"]
PRIMARY_FONT_PATH = FONTS_DIR / "CormorantGaramond-Regular.ttf"
FONT_CANDIDATES = (
    PRIMARY_FONT_PATH,
    BASE_DIR / "fonts" / "CormorantGaramond-Medium.ttf",
    BASE_DIR / "fonts" / "CormorantGaramond-SemiBold.ttf",
    BASE_DIR / "fonts" / "card_font.ttf",
    Path("C:/Windows/Fonts/times.ttf"),
    Path("C:/Windows/Fonts/georgia.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)

REQUEST_DELAY_SECONDS = 1.5
REQUEST_JITTER_SECONDS = 0.7
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; QRCardGenerator/1.0; +local script)"
