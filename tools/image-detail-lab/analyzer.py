"""Heuristic image analysis and conservative AI-guided suggestions."""

import cv2
import numpy as np
from PIL import Image


def analyze_image(image: Image.Image) -> dict:
    """Compute quality metrics for a single image."""
    rgb = np.array(image.convert("RGB"))
    img_cv = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # Sharpness — Laplacian variance (higher = sharper)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(laplacian.var())

    # Contrast — standard deviation of luminance
    contrast = float(gray.std())

    # Detail — mean gradient magnitude via Sobel
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    detail = float(np.sqrt(gx ** 2 + gy ** 2).mean())

    # Noise — robust estimate from Laplacian MAD
    noise = float(np.median(np.abs(laplacian - np.median(laplacian)))) * 1.4826

    # Brightness
    brightness = float(gray.mean())

    # Posterization risk — many empty histogram bins
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    zero_bins = int(np.sum(hist == 0))
    posterization_risk = zero_bins > 100

    # Clipping risk
    total = gray.size
    clip_dark = float(np.sum(gray < 5)) / total
    clip_bright = float(np.sum(gray > 250)) / total
    clipping_risk = clip_dark > 0.05 or clip_bright > 0.05

    return {
        "sharpness": round(sharpness, 2),
        "contrast": round(contrast, 2),
        "detail": round(detail, 2),
        "noise": round(noise, 2),
        "brightness": round(brightness, 2),
        "posterization_risk": posterization_risk,
        "clipping_risk": clipping_risk,
        "clip_dark_pct": round(clip_dark * 100, 1),
        "clip_bright_pct": round(clip_bright * 100, 1),
    }


def rank_variants(analyses: dict[str, dict]) -> list[tuple[str, float, str]]:
    """Rank variants by composite quality score.

    Returns [(name, score, reason), ...] sorted best-first.
    """
    if not analyses:
        return []

    metrics = ["sharpness", "contrast", "detail"]
    normalized = {}
    for m in metrics:
        vals = [a[m] for a in analyses.values()]
        lo, hi = min(vals), max(vals)
        span = hi - lo if hi > lo else 1.0
        normalized[m] = {n: (a[m] - lo) / span for n, a in analyses.items()}

    noise_vals = [a["noise"] for a in analyses.values()]
    nlo, nhi = min(noise_vals), max(noise_vals)
    nspan = nhi - nlo if nhi > nlo else 1.0
    noise_norm = {n: (a["noise"] - nlo) / nspan for n, a in analyses.items()}

    results = []
    for name, analysis in analyses.items():
        score = (
            normalized["sharpness"][name] * 0.35
            + normalized["contrast"][name] * 0.25
            + normalized["detail"][name] * 0.30
            - noise_norm[name] * 0.10
        )

        strengths = []
        if normalized["sharpness"][name] > 0.7:
            strengths.append("high sharpness")
        if normalized["contrast"][name] > 0.7:
            strengths.append("good contrast")
        if normalized["detail"][name] > 0.7:
            strengths.append("rich detail")

        warnings = []
        if analysis["posterization_risk"]:
            warnings.append("possible posterization")
        if analysis["clipping_risk"]:
            warnings.append("tonal clipping detected")
        if noise_norm[name] > 0.7:
            warnings.append("elevated noise")

        parts = []
        if strengths:
            parts.append("Strengths: " + ", ".join(strengths))
        if warnings:
            parts.append("Caution: " + ", ".join(warnings))
        if not parts:
            parts.append("Average across metrics")

        results.append((name, round(score, 3), "; ".join(parts)))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def generate_suggestions(
    analyses: dict[str, dict], rankings: list[tuple[str, float, str]]
) -> list[str]:
    """Generate conservative, hedged AI guidance."""
    if not rankings:
        return ["Load an image to begin analysis."]

    suggestions = []
    top_name = rankings[0][0]
    suggestions.append(
        f'"{top_name}" appears to show the most detail '
        f"based on measured sharpness and contrast."
    )

    for name, analysis in analyses.items():
        if analysis["posterization_risk"]:
            suggestions.append(
                f'"{name}" may have posterization artifacts '
                f"— verify smooth gradients manually."
            )
        if analysis["clipping_risk"]:
            dark = analysis["clip_dark_pct"]
            bright = analysis["clip_bright_pct"]
            if dark > 5:
                suggestions.append(
                    f'"{name}" has {dark}% crushed shadows '
                    f"— dark detail may be lost."
                )
            if bright > 5:
                suggestions.append(
                    f'"{name}" has {bright}% blown highlights '
                    f"— bright detail may be lost."
                )

    suggestions.append(
        "Note: These are heuristic estimates. "
        "Visual inspection should always guide final selection."
    )
    return suggestions
