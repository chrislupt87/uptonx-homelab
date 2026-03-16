"""Image enhancement variant generation using OpenCV and Pillow."""

import cv2
import numpy as np
from PIL import Image


def generate_variants(image: Image.Image) -> dict[str, Image.Image]:
    """Generate standard enhancement variants from an input image.

    Returns dict mapping variant name to PIL Image.
    Original is NOT included — caller should add it separately.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")

    img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    variants = {}

    # 1. Sharpened — unsharp mask
    blurred = cv2.GaussianBlur(img_cv, (0, 0), 3)
    sharpened = cv2.addWeighted(img_cv, 1.5, blurred, -0.5, 0)
    variants["Sharpened"] = _cv2_to_pil(sharpened)

    # 2. CLAHE — adaptive local contrast
    lab = cv2.cvtColor(img_cv, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    variants["CLAHE"] = _cv2_to_pil(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR))

    # 3. Histogram equalization — global, on luminance channel
    lab2 = cv2.cvtColor(img_cv, cv2.COLOR_BGR2LAB)
    lab2[:, :, 0] = cv2.equalizeHist(lab2[:, :, 0])
    variants["Histogram EQ"] = _cv2_to_pil(cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR))

    # 4. Edge enhanced — Canny edges overlaid in green
    edges = cv2.Canny(gray, 50, 150)
    edge_overlay = img_cv.copy()
    edge_overlay[edges > 0] = [0, 255, 0]
    variants["Edge Enhanced"] = _cv2_to_pil(edge_overlay)

    # 5. Denoised — non-local means
    denoised = cv2.fastNlMeansDenoisingColored(img_cv, None, 10, 10, 7, 21)
    variants["Denoised"] = _cv2_to_pil(denoised)

    # 6. Shadow reveal — gamma lift for dark regions
    lut = np.array(
        [((i / 255.0) ** 0.4) * 255 for i in range(256)]
    ).astype("uint8")
    variants["Shadow Reveal"] = _cv2_to_pil(cv2.LUT(img_cv, lut))

    # 7. Detail boost — high-pass overlay
    blur_hp = cv2.GaussianBlur(img_cv, (0, 0), 10)
    high_pass = cv2.subtract(img_cv, blur_hp)
    variants["Detail Boost"] = _cv2_to_pil(cv2.add(img_cv, high_pass))

    # 8. Grayscale enhanced — equalized grayscale
    variants["Grayscale Enhanced"] = Image.fromarray(cv2.equalizeHist(gray))

    return variants


def _cv2_to_pil(img_cv: np.ndarray) -> Image.Image:
    """Convert OpenCV BGR image to PIL RGB Image."""
    return Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
