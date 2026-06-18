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
# Tuned by the eval (eval/run_eval.py). Two complementary steps are ON:
#   * deskew  — straightens rotated labels (the rotation cases). Angle-guarded, so
#               straight labels are untouched and no clean case regresses.
#   * contrast (CLAHE) — local adaptive histogram equalization. Normalizes uneven
#               lighting, recovering the shadow case (a left-side shadow used to
#               drop the start of the brand "Stone's Throw" -> "ne's Throw" and the
#               warning header; CLAHE brings both back).
# Together they reach 12/13 confident-correct on the synthetic set with clean held
# at 100% and zero confident-wrong (~580 ms/label). Note CLAHE must run WITH deskew:
# contrast ALONE regresses (introduces confident-wrong reads). denoise/binarize add
# latency without lift and stay off.
STEPS = {"denoise": False, "contrast": True, "deskew": True, "binarize": False}

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
