"""OpenCV preprocessing before OCR: denoise → contrast → deskew → binarize.

Aimed at real photos (blur, low contrast, rotation, JPEG noise). Each step is
independently toggleable (eng-review D1) so the eval can ablate — measure each
step's effect and drop any that regresses. Steps take and return a single-channel
(grayscale) uint8 ndarray.

  gray ─► denoise ─► CLAHE contrast ─► deskew (angle-guarded) ─► adaptive threshold ─► out
"""

from __future__ import annotations

import cv2
import numpy as np

# Per-step toggles (eng-review D1). The master on/off (PREPROCESS_ENABLED) lives
# in app/ocr.py.
#
# Tuned by the eval ablation (eval/ablate.py -> eval/REPORT.md). Re-run over a
# broadened degraded set (now 10 cases: rotation, blur, JPEG, low/uneven light,
# perspective, glare, shadow, sensor noise, blur+rotate), the winner is DESKEW
# ALONE: end-to-end 53.8% -> 69.2% with clean held at 100% and ~211 ms/label.
# The angle guard (below) leaves straight labels untouched, so the "geometric
# risk" is bounded — no clean case regresses. Combining steps is anti-synergistic:
# contrast+deskew drops back to 61.5%, and denoise only adds latency (no lift).
# A non-rotated, low-light-heavy deployment can flip contrast on and re-ablate.
STEPS = {"denoise": False, "contrast": False, "deskew": True, "binarize": False}

# Don't rotate a near-straight label — only correct skew above this (degrees).
DESKEW_MIN_ANGLE = 0.5
# Ignore implausibly large detected angles (likely a bad estimate, not real skew).
DESKEW_MAX_ANGLE = 30.0


def denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7,
                                    searchWindowSize=21)


def contrast(gray: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def detect_skew_angle(gray: np.ndarray) -> float:
    """Estimate the text skew in degrees (positive = needs CCW correction).

    Foreground (text) is found by Otsu on the inverted image; minAreaRect gives
    the dominant angle, normalized to [-45, 45].
    """
    inv = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle > 45:           # OpenCV 4.5+ reports (0, 90]; fold to [-45, 45]
        angle -= 90
    return float(angle)


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Straighten the image if skewed beyond the guard; rotate on white."""
    angle = detect_skew_angle(gray)
    if abs(angle) < DESKEW_MIN_ANGLE or abs(angle) > DESKEW_MAX_ANGLE:
        return gray, angle
    h, w = gray.shape
    # Rotate by the NEGATIVE detected angle to undo the skew (CCW skew -> CW fix).
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    return rotated, angle


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 10)


def preprocess(gray: np.ndarray) -> np.ndarray:
    """Apply the enabled steps to a grayscale ndarray; return the processed image."""
    out = gray
    if STEPS["denoise"]:
        out = denoise(out)
    if STEPS["contrast"]:
        out = contrast(out)
    if STEPS["deskew"]:
        out, _ = deskew(out)
    if STEPS["binarize"]:
        out = binarize(out)
    return out
