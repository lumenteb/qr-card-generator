from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

try:
    import cv2
    import numpy as np
except ImportError as error:
    raise SystemExit(
        "OpenCV dependencies are missing. Install them with: pip install -r requirements"
    ) from error


PathLike = Union[str, Path]

IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True)
class QRDecodeResult:
    path: Path
    url: Optional[str]
    error: Optional[str] = None


def find_image_files(input_dir: PathLike) -> List[Path]:
    directory = Path(input_dir)

    if not directory.exists():
        return []

    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def read_image(image_path: PathLike):
    image_path = Path(image_path)

    try:
        image_data = np.fromfile(str(image_path), dtype=np.uint8)
        return cv2.imdecode(image_data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def add_white_border(image, border_size=80):
    return cv2.copyMakeBorder(
        image,
        border_size,
        border_size,
        border_size,
        border_size,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )


def generate_qr_candidates(image):
    yield image
    yield add_white_border(image)

    for scale in (2, 3, 4):
        resized = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        yield resized
        yield add_white_border(resized)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    yield gray
    yield cv2.equalizeHist(gray)
    yield add_white_border(gray)

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    yield otsu
    yield add_white_border(otsu)

    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    yield adaptive
    yield add_white_border(adaptive)

    for scale in (2, 3, 4):
        resized_gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        yield resized_gray
        yield add_white_border(resized_gray)

        _, resized_otsu = cv2.threshold(
            resized_gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        yield resized_otsu
        yield add_white_border(resized_otsu)


def try_decode_qr(image):
    detector = cv2.QRCodeDetector()

    for candidate in generate_qr_candidates(image):
        decoded_text, _, _ = detector.detectAndDecode(candidate)
        decoded_text = decoded_text.strip()

        if decoded_text:
            return decoded_text

    return None


def decode_qr_image(image_path: PathLike) -> QRDecodeResult:
    image_path = Path(image_path)
    image = read_image(image_path)

    if image is None:
        return QRDecodeResult(
            path=image_path,
            url=None,
            error="file found, but OpenCV could not read it",
        )

    decoded_text = try_decode_qr(image)

    if not decoded_text:
        return QRDecodeResult(
            path=image_path,
            url=None,
            error="QR code not found or could not be decoded",
        )

    return QRDecodeResult(path=image_path, url=decoded_text)


def decode_qr_images(input_dir: PathLike) -> List[QRDecodeResult]:
    return [decode_qr_image(image_path) for image_path in find_image_files(input_dir)]
