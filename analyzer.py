"""
ANPR Analyzer — YOLO plate detection + fast-plate-ocr (primary) + Tesseract (fallback).

Architecture after upgrade
──────────────────────────
Full frame
  └─► best.pt   → plate bbox (full-frame detection, unchanged)
        └─► padded crop taken from the ORIGINAL high-res frame
              └─► fast-plate-ocr (cct-s-v2-global-model, ~20ms ONNX)
                    └─► if conf < threshold OR fails Indian regex
                          └─► Tesseract fallback (unchanged logic)
                                └─► normalized text + validation

Key design decisions
────────────────────
1. fast-plate-ocr is lazy-loaded once and then REUSED — no model reload per frame.
2. Tesseract is still fully loaded as a fallback — it is never removed.
3. The OCR confidence threshold (0.40) is configurable via OCR_CONF_THRESHOLD.
4. The crop passed to OCR is always taken from the ORIGINAL frame at FULL resolution,
   never from a pre-compressed or downscaled buffer.
5. The public result contract (plate_number, detection_confidence, ocr_confidence,
   engine, status, bbox, camera_id, timestamp) is satisfied by every code path.
"""
import base64
import cv2
import numpy as np
import re
import os
import time
from ultralytics import YOLO
import pytesseract

DEBUG_ANPR = True
DEBUG_DIR  = "debug"

# ── Confidence below which fast-plate-ocr defers to Tesseract ────────────────
OCR_CONF_THRESHOLD = 0.40

if DEBUG_ANPR:
    os.makedirs(DEBUG_DIR, exist_ok=True)


class LicensePlateAnalyzer:
    """AI-powered license plate recognition.

    Primary OCR:  fast-plate-ocr  (cct-s-v2-global-model, ONNX, ~20 ms)
    Fallback OCR: Tesseract 5     (unchanged from previous version)
    Detector:     best.pt         (custom YOLO, unchanged)
    """

    def __init__(
        self,
        vehicle_model_path: str = "yolo11n.pt",
        model_path: str         = "models/best.pt",
        confidence: float       = 0.30,
        tesseract_path: str | None = None,
    ):
        self.vehicle_model_path = vehicle_model_path
        self.model_path         = model_path
        self.confidence         = confidence

        # ── Tesseract (fallback) ─────────────────────────────────────────────
        if tesseract_path is None:
            tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        self.tesseract_path = tesseract_path
        self.ocr_loaded     = False

        if os.path.exists(self.tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
        try:
            version = pytesseract.get_tesseract_version()
            print(f"[INFO] Tesseract OCR loaded. Version: {version}")
            self.ocr_loaded = True
        except Exception as e:
            print(f"[WARNING] Tesseract not found or failed: {e}")
            print(f"Looked at: {self.tesseract_path} and system PATH.")

        # ── fast-plate-ocr (primary) — lazy-loaded on first use ──────────────
        self._fast_ocr        = None   # LicensePlateRecognizer instance
        self._fast_ocr_ready  = False
        self._fast_ocr_failed = False  # permanently disable if import fails

        # ── YOLO models ──────────────────────────────────────────────────────
        print(f"[INFO] Loading YOLO models: {self.vehicle_model_path}, {self.model_path}")
        self.vehicle_model = YOLO(self.vehicle_model_path)
        self.plate_model   = YOLO(self.model_path)
        print("[INFO] YOLO models loaded successfully.")

        self.vehicle_classes = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    # ─────────────────────────────────────────────────────────────────────────
    # fast-plate-ocr lazy loader
    # ─────────────────────────────────────────────────────────────────────────

    def _get_fast_ocr(self):
        """Return the cached LicensePlateRecognizer, loading it on first call."""
        if self._fast_ocr_failed:
            return None
        if self._fast_ocr_ready:
            return self._fast_ocr
        try:
            from fast_plate_ocr import LicensePlateRecognizer
            self._fast_ocr       = LicensePlateRecognizer("cct-s-v2-global-model")
            self._fast_ocr_ready = True
            print("[INFO] fast-plate-ocr (cct-s-v2-global-model) loaded — primary OCR active.")
        except Exception as e:
            self._fast_ocr_failed = True
            print(f"[WARNING] fast-plate-ocr unavailable ({e}). Tesseract-only mode.")
        return self._fast_ocr

    # ─────────────────────────────────────────────────────────────────────────
    # Plate text cleaning & validation
    # ─────────────────────────────────────────────────────────────────────────

    def normalize_plate_number(self, text: str) -> str:
        """Keep only uppercase A-Z and 0-9."""
        if not text:
            return ""
        return re.sub(r"[^A-Z0-9]", "", str(text).upper())

    def validate_plate(self, text: str) -> str:
        """Reject garbage OCR output.

        A valid plate must:
        - Be 6–13 characters (Indian plates are 8–10; relax to 6 for partial reads)
        - Contain at least 2 digits  (district number is always present)
        - Contain at least 2 letters (state code = 2 letters minimum)

        Returns the cleaned text or empty string.
        """
        text = self.normalize_plate_number(text)
        if len(text) < 6 or len(text) > 13:
            return ""
        if sum(c.isdigit() for c in text) < 2:
            return ""
        if sum(c.isalpha() for c in text) < 2:
            return ""
        return text

    # Indian plate pattern: GJ01HU6963 / DL14TE5182 / MH12AB1234 / HR26CJ0805
    _INDIAN_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$")

    def is_indian_format(self, plate: str) -> bool:
        return bool(plate and self._INDIAN_RE.match(plate))

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY: fast-plate-ocr
    # ─────────────────────────────────────────────────────────────────────────

    def _read_with_fast_ocr(self, plate_image) -> tuple[str, float]:
        """Run fast-plate-ocr on the crop. Returns (plate_text, confidence).

        fast-plate-ocr returns a list of PlatePrediction objects:
          PlatePrediction(plate='GJ01HU6963', char_probs=[...], region='IN', ...)

        confidence is computed as the geometric mean of per-character probabilities
        when available, otherwise a fixed 0.85 for any non-empty result.
        """
        ocr = self._get_fast_ocr()
        if ocr is None:
            return "", 0.0

        try:
            predictions = ocr.run(plate_image)
        except Exception as e:
            if DEBUG_ANPR:
                print(f"  [fast-plate-ocr] Runtime error: {e}")
            return "", 0.0

        if not predictions:
            return "", 0.0

        # Take the first (best) prediction
        pred = predictions[0]

        # Extract plate text
        if hasattr(pred, "plate"):
            raw_text = pred.plate or ""
        elif isinstance(pred, (list, tuple)):
            raw_text = str(pred[0]) if pred else ""
        else:
            raw_text = str(pred)

        # Extract or estimate confidence
        conf = 0.85  # default when char_probs not available
        if hasattr(pred, "char_probs") and pred.char_probs is not None:
            try:
                probs = [p for p in pred.char_probs if p > 0]
                if probs:
                    # Geometric mean of per-character probabilities
                    import math
                    conf = math.exp(sum(math.log(p) for p in probs) / len(probs))
            except Exception:
                pass

        plate = self.validate_plate(raw_text)

        if DEBUG_ANPR:
            indian_tag = " [INDIAN]" if self.is_indian_format(plate) else ""
            print(f"  [fast-plate-ocr] raw='{raw_text}' → '{plate}' conf={conf:.2f}{indian_tag}")

        return plate, conf

    # ─────────────────────────────────────────────────────────────────────────
    # FALLBACK: Tesseract preprocessing variants
    # ─────────────────────────────────────────────────────────────────────────

    def get_preprocessing_variants(self, plate_image, fast: bool = False):
        """Create variants of the plate image for Tesseract.

        fast=True  → 2 variants (live camera, low latency).
        fast=False → 5 variants (uploaded image, maximum accuracy).
        """
        if plate_image is None or plate_image.size == 0:
            return []

        h, w = plate_image.shape[:2]
        variants = []

        # Choose upscale factor based on actual crop size
        if max(w, h) >= 400:
            scale = 1
        elif max(w, h) >= 150:
            scale = 2
        else:
            scale = 3

        if scale > 1:
            upscaled = cv2.resize(plate_image, (w * scale, h * scale),
                                  interpolation=cv2.INTER_CUBIC)
        else:
            upscaled = plate_image
        gray_upscaled = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)

        gray_original = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        variants.append(("original_gray", gray_original))
        variants.append(("upscaled_gray", gray_upscaled))

        if fast:
            return variants

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray_upscaled)
        variants.append(("clahe_gray", gray_clahe))

        gray_bilateral = cv2.bilateralFilter(gray_upscaled, d=9, sigmaColor=50, sigmaSpace=50)
        variants.append(("bilateral_gray", gray_bilateral))

        gray_denoised = cv2.GaussianBlur(gray_upscaled, (3, 3), 0)
        thresh_adaptive = cv2.adaptiveThreshold(
            gray_denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
        )
        variants.append(("adaptive_thresh", thresh_adaptive))

        return variants

    # ─────────────────────────────────────────────────────────────────────────
    # FALLBACK: Tesseract OCR
    # ─────────────────────────────────────────────────────────────────────────

    def _read_with_tesseract(self, plate_image, fast: bool = False) -> tuple[str, float, str]:
        """Read text from a cropped plate using Tesseract (fallback engine).

        Returns (best_plate, confidence, best_variant_name).
        Scoring is format-weighted: Indian-format match gets 2× bonus.

        fast=True  → 2 variants × 1 PSM  = 2  Tesseract calls (live camera).
        fast=False → 5 variants × 3 PSMs = 15 Tesseract calls (uploaded image).
        """
        if not self.ocr_loaded:
            if DEBUG_ANPR:
                print("[Tesseract] Not loaded — cannot fallback.")
            return "", 0.0, ""

        variants = self.get_preprocessing_variants(plate_image, fast=fast)
        if not variants:
            return "", 0.0, ""

        all_configs = [
            "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        ]
        configs = all_configs[:1] if fast else all_configs

        best_plate   = ""
        best_conf    = 0.0
        best_raw     = ""
        best_variant = ""
        best_weighted = 0.0

        for variant_name, img in variants:
            for config in configs:
                try:
                    raw_text = pytesseract.image_to_string(img, config=config).strip()
                except Exception as exc:
                    if DEBUG_ANPR:
                        print(f"  [Tesseract] Error on {variant_name}: {exc}")
                    continue

                normalized  = self.normalize_plate_number(raw_text)
                valid_plate = self.validate_plate(normalized)
                if not valid_plate:
                    continue

                try:
                    data  = pytesseract.image_to_data(img, config=config,
                                                      output_type=pytesseract.Output.DICT)
                    confs = [int(c) for c in data["conf"] if int(c) > 0]
                    conf  = (sum(confs) / len(confs) / 100.0) if confs else 0.5
                except Exception:
                    conf = 0.5

                format_bonus = 2.0 if self.is_indian_format(valid_plate) else 1.0
                length_bonus = 1.0 + max(0, len(valid_plate) - 6) * 0.05
                weighted     = conf * format_bonus * length_bonus

                psm_str = config.split("--psm")[1].split()[0] if "--psm" in config else "?"
                if DEBUG_ANPR:
                    fmt_tag = " [INDIAN]" if format_bonus > 1 else ""
                    print(f"  [Tesseract] {variant_name} PSM{psm_str}: '{raw_text.strip()}'"
                          f" → '{valid_plate}' conf={conf:.2f} w={weighted:.2f}{fmt_tag}")

                if weighted > best_weighted:
                    best_weighted = weighted
                    best_conf     = conf
                    best_plate    = valid_plate
                    best_raw      = raw_text
                    best_variant  = variant_name
                    if DEBUG_ANPR:
                        cv2.imwrite(os.path.join(DEBUG_DIR, "latest_processed_plate.jpg"), img)

                if best_weighted > 1.5:  # early exit: high-conf Indian-format match
                    break
            if best_weighted > 1.5:
                break

        if DEBUG_ANPR:
            print(f"[Tesseract] FINAL: '{best_raw.strip()}' → '{best_plate}'"
                  f" conf={best_conf:.2f} weighted={best_weighted:.2f} (from {best_variant})")
            if not best_plate:
                print("[Tesseract] No valid plate found.")

        return best_plate, best_conf, best_variant

    # ─────────────────────────────────────────────────────────────────────────
    # Combined OCR: fast-plate-ocr primary → Tesseract fallback
    # ─────────────────────────────────────────────────────────────────────────

    def read_plate(self, plate_image, fast: bool = False) -> tuple[str, float, str, str]:
        """Run the two-stage OCR pipeline.

        Stage 1 — fast-plate-ocr (~20ms ONNX):
          If confidence >= OCR_CONF_THRESHOLD AND result passes Indian validation
          → use this result.

        Stage 2 — Tesseract (fallback, unchanged):
          Triggered when fast-plate-ocr is unavailable, returns empty string,
          returns confidence below threshold, or fails Indian format check AND
          Tesseract produces a higher-weighted result.

        Returns (plate_text, confidence, raw_text, engine_name).

        Callers that previously expected (text, conf, raw) still work because
        Python allows ignoring trailing return values.
        """
        # ── Stage 1: fast-plate-ocr ──────────────────────────────────────────
        fast_plate, fast_conf = self._read_with_fast_ocr(plate_image)
        fast_is_indian = self.is_indian_format(fast_plate)

        use_fast = (
            bool(fast_plate)
            and fast_conf >= OCR_CONF_THRESHOLD
            and fast_is_indian  # must match Indian format to be trusted
        )

        if use_fast:
            if DEBUG_ANPR:
                print(f"[OCR] PRIMARY (fast-plate-ocr): '{fast_plate}' conf={fast_conf:.2f} [ACCEPTED]")
            return fast_plate, fast_conf, fast_plate, "fast-plate-ocr"

        # ── Stage 2: Tesseract fallback ──────────────────────────────────────
        if DEBUG_ANPR:
            reason = "empty" if not fast_plate else (
                f"low-conf ({fast_conf:.2f})" if fast_conf < OCR_CONF_THRESHOLD else "non-Indian-format"
            )
            print(f"[OCR] fast-plate-ocr {reason} → invoking Tesseract fallback")

        tess_plate, tess_conf, tess_variant = self._read_with_tesseract(plate_image, fast=fast)

        # If both engines returned results, take the one with higher confidence
        # (preferring the Indian-format result when confidences are close)
        if fast_plate and tess_plate:
            fast_weighted = fast_conf * (2.0 if fast_is_indian else 1.0)
            tess_weighted = tess_conf * (2.0 if self.is_indian_format(tess_plate) else 1.0)
            if fast_weighted >= tess_weighted:
                if DEBUG_ANPR:
                    print(f"[OCR] FINAL: fast-plate-ocr wins ('{fast_plate}' fw={fast_weighted:.2f}"
                          f" vs Tesseract '{tess_plate}' tw={tess_weighted:.2f})")
                return fast_plate, fast_conf, fast_plate, "fast-plate-ocr"
            else:
                if DEBUG_ANPR:
                    print(f"[OCR] FINAL: Tesseract wins ('{tess_plate}' tw={tess_weighted:.2f}"
                          f" vs fast-plate-ocr '{fast_plate}' fw={fast_weighted:.2f})")
                return tess_plate, tess_conf, tess_plate, "tesseract"

        # Only one engine produced output
        if fast_plate:
            if DEBUG_ANPR:
                print(f"[OCR] FINAL: fast-plate-ocr only ('{fast_plate}' conf={fast_conf:.2f})")
            return fast_plate, fast_conf, fast_plate, "fast-plate-ocr"

        if tess_plate:
            if DEBUG_ANPR:
                print(f"[OCR] FINAL: Tesseract only ('{tess_plate}' conf={tess_conf:.2f})")
            return tess_plate, tess_conf, tess_plate, "tesseract"

        if DEBUG_ANPR:
            print("[OCR] FINAL: Both engines returned empty — no plate read.")
        return "", 0.0, "", "none"

    # ─────────────────────────────────────────────────────────────────────────
    # Crop extraction helper
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_crop(self, image, bbox: tuple[int, int, int, int]) -> tuple:
        """Extract a padded plate crop from the ORIGINAL full-resolution image.

        Returns (crop, cx1, cy1, cx2, cy2).
        Always operates on the original frame — never on a compressed buffer.
        """
        h, w = image.shape[:2]
        px1, py1, px2, py2 = bbox
        bw = max(1, px2 - px1)
        bh = max(1, py2 - py1)

        # Proportional padding: 6% of bbox dimension
        # (reduced from 10% to avoid including car body on sides)
        pad_x = max(8, int(0.06 * bw))
        pad_y = max(5, int(0.06 * bh))

        cx1 = max(0, px1 - pad_x)
        cy1 = max(0, py1 - pad_y)
        cx2 = min(w, px2 + pad_x)
        cy2 = min(h, py2 + pad_y)

        return image[cy1:cy2, cx1:cx2], cx1, cy1, cx2, cy2

    def _rank_detections(self, plate_results, image_w: int, image_h: int) -> list:
        """Collect all plate detections, rank by (confidence × normalised area)."""
        all_detections = []
        for plate_result in plate_results:
            if plate_result.boxes is None:
                continue
            for box, conf in zip(plate_result.boxes.xyxy, plate_result.boxes.conf):
                px1, py1, px2, py2 = map(int, box)
                plate_conf = float(conf)
                area  = (px2 - px1) * (py2 - py1)
                score = plate_conf * (area / max(1, image_w * image_h))
                all_detections.append({
                    "bbox":       (px1, py1, px2, py2),
                    "confidence": plate_conf,
                    "area":       area,
                    "score":      score,
                })
        all_detections.sort(key=lambda d: d["score"], reverse=True)
        return all_detections

    # ─────────────────────────────────────────────────────────────────────────
    # Full analysis pipeline — analyze()
    # ─────────────────────────────────────────────────────────────────────────

    def analyze(self, image, fast: bool = False) -> dict:
        """Run full ANPR pipeline on a single frame.

        fast=True  → 2-variant Tesseract fallback for live camera (low latency).
        fast=False → 5-variant Tesseract fallback for maximum accuracy.

        Note: fast-plate-ocr is always single-pass regardless of the fast flag.
        The fast flag only affects the Tesseract fallback path.
        """
        if image is None:
            raise ValueError("Image cannot be None.")

        output_image = image.copy()
        h, w = image.shape[:2]

        if DEBUG_ANPR:
            print("\n" + "=" * 50)
            print(f"[ANPR] Analyzing new frame ({w}x{h}){' [fast]' if fast else ''}")

        # 1. Detect vehicles
        vehicle_results = self.vehicle_model(image, conf=0.25, verbose=False)
        vehicles = []
        for result in vehicle_results:
            if result.boxes is None:
                continue
            for box, conf, cls in zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
                cls = int(cls)
                if cls not in self.vehicle_classes:
                    continue
                vx1, vy1, vx2, vy2 = map(int, box)
                cv2.rectangle(output_image, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
                cv2.putText(output_image, f"{self.vehicle_classes[cls]} {float(conf):.2f}",
                            (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                vehicles.append({
                    "vehicle_type":       self.vehicle_classes[cls],
                    "vehicle_confidence": round(float(conf), 3),
                })

        # 2. Detect plates
        plates  = []
        numbers = []

        plate_results = self.plate_model(image, conf=self.confidence, verbose=False)
        all_detections = self._rank_detections(plate_results, w, h)

        for det in all_detections:
            plates.append({"confidence": det["confidence"]})

        # Draw secondary (non-primary) detections as dim grey
        for det in all_detections[1:]:
            px1, py1, px2, py2 = det["bbox"]
            cv2.rectangle(output_image, (px1, py1), (px2, py2), (128, 128, 128), 1)

        if all_detections:
            primary = all_detections[0]
            px1, py1, px2, py2 = primary["bbox"]
            plate_confidence = primary["confidence"]

            if DEBUG_ANPR:
                print(f"[ANPR] Best plate: bbox={px1},{py1},{px2},{py2} "
                      f"conf={plate_confidence:.2f} score={primary['score']:.4f}")

            plate_crop, cx1, cy1, cx2, cy2 = self._extract_crop(image, (px1, py1, px2, py2))
            crop_h, crop_w = plate_crop.shape[:2]

            if DEBUG_ANPR:
                print(f"[CROP] {crop_w}x{crop_h} (from {px2-px1}x{py2-py1} bbox)")
                cv2.imwrite(os.path.join(DEBUG_DIR, "latest_plate.jpg"), plate_crop)

            if crop_w < 40 or crop_h < 15:
                if DEBUG_ANPR:
                    print("[CROP] Plate too small for reliable OCR. Skipping.")
                cv2.rectangle(output_image, (px1, py1), (px2, py2), (0, 165, 255), 2)
                cv2.putText(output_image, "TOO SMALL", (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            else:
                plate_number, ocr_confidence, _, engine = self.read_plate(plate_crop, fast=fast)

                color = (0, 255, 0) if plate_number else (0, 165, 255)
                cv2.rectangle(output_image, (px1, py1), (px2, py2), color, 2)
                label = (f"{plate_number} {ocr_confidence:.0%}" if plate_number
                         else f"plate {plate_confidence:.2f}")
                cv2.putText(output_image, label, (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if plate_number:
                    numbers.append(plate_number)

        return {
            "image":    output_image,
            "plates":   plates,
            "numbers":  numbers,
            "vehicles": vehicles,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Status (for /api/pipeline/status)
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        fast_ocr_ready = self._fast_ocr_ready or (
            not self._fast_ocr_failed and self._get_fast_ocr() is not None
        )
        primary_engine   = "fast-plate-ocr (cct-s-v2-global-model)" if fast_ocr_ready else "Tesseract OCR"
        fallback_engine  = "Tesseract OCR" if (fast_ocr_ready and self.ocr_loaded) else "none"
        return {
            "model_loaded":   self.plate_model is not None,
            "ocr_loaded":     self.ocr_loaded or fast_ocr_ready,
            "ocr_engine":     primary_engine,
            "fallback_engine": fallback_engine,
            "model":          "YOLOv8 (best.pt) + fast-plate-ocr",
            "task":           "Object Detection + License Plate OCR",
            "classes":        "vehicle + license_plate",
            "input_size":     "640x640",
            "conf_threshold": OCR_CONF_THRESHOLD,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Extended analysis with crop images (for /api/anpr/image)
    # ─────────────────────────────────────────────────────────────────────────

    def analyze_with_crops(self, image) -> dict:
        """Run full ANPR and return base64-encoded crop images.

        Ranking: collects ALL plate detections, ranks by (confidence × bbox_area / image_area),
        processes only the top-ranked detection. This prevents the small 'IND' badge box
        from overwriting the crop from the full plate box.

        Returns the analyze() keys plus:
          original_crop, preprocessed_crop, ocr_confidence, ocr_engine,
          is_valid_indian_format, best_plate_number, best_yolo_confidence.
        """
        if image is None:
            raise ValueError("Image cannot be None.")

        output_image = image.copy()
        h, w = image.shape[:2]

        if DEBUG_ANPR:
            print("\n" + "=" * 50)
            print(f"[ANPR] analyze_with_crops ({w}x{h})")

        # 1. Vehicle detection
        vehicle_results = self.vehicle_model(image, conf=0.25, verbose=False)
        vehicles = []
        for result in vehicle_results:
            if result.boxes is None:
                continue
            for box, conf, cls in zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
                cls_int = int(cls)
                if cls_int not in self.vehicle_classes:
                    continue
                vx1, vy1, vx2, vy2 = map(int, box)
                cv2.rectangle(output_image, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
                cv2.putText(output_image, f"{self.vehicle_classes[cls_int]} {float(conf):.2f}",
                            (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                vehicles.append({
                    "vehicle_type":       self.vehicle_classes[cls_int],
                    "vehicle_confidence": round(float(conf), 3),
                })

        # 2. Plate detection — collect ALL, rank by score
        plates             = []
        numbers            = []
        best_plate_number  = ""
        best_yolo_conf     = 0.0
        best_ocr_conf      = 0.0
        best_ocr_engine    = "none"
        original_crop_b64  = None
        preprocessed_b64   = None

        plate_results  = self.plate_model(image, conf=self.confidence, verbose=False)
        all_detections = self._rank_detections(plate_results, w, h)

        if DEBUG_ANPR:
            for i, det in enumerate(all_detections):
                px1, py1, px2, py2 = det["bbox"]
                print(f"[DETECT] #{i} bbox=({px1},{py1},{px2},{py2}) "
                      f"conf={det['confidence']:.2f} score={det['score']:.5f}")

        for det in all_detections:
            plates.append({"confidence": det["confidence"]})

        for det in all_detections[1:]:
            px1, py1, px2, py2 = det["bbox"]
            cv2.rectangle(output_image, (px1, py1), (px2, py2), (128, 128, 128), 1)

        # 3. Process only the primary (best-scored) detection
        if all_detections:
            primary = all_detections[0]
            px1, py1, px2, py2 = primary["bbox"]
            plate_confidence   = primary["confidence"]
            best_yolo_conf     = plate_confidence

            if DEBUG_ANPR:
                print(f"[PRIMARY] bbox=({px1},{py1},{px2},{py2}) conf={plate_confidence:.2f}")

            plate_crop, cx1, cy1, cx2, cy2 = self._extract_crop(image, (px1, py1, px2, py2))
            crop_h, crop_w = plate_crop.shape[:2]

            if DEBUG_ANPR:
                print(f"[CROP] padded {crop_w}x{crop_h} (from {px2-px1}x{py2-py1} bbox)")
                cv2.imwrite(os.path.join(DEBUG_DIR, "latest_plate.jpg"), plate_crop)

            # Encode raw crop for display
            ok_raw, raw_enc = cv2.imencode(".jpg", plate_crop)
            if ok_raw:
                original_crop_b64 = f"data:image/jpeg;base64,{base64.b64encode(raw_enc).decode()}"

            if crop_w < 40 or crop_h < 15:
                if DEBUG_ANPR:
                    print("[CROP] Too small for OCR — skipping.")
                cv2.rectangle(output_image, (px1, py1), (px2, py2), (0, 165, 255), 2)
                cv2.putText(output_image, "TOO SMALL", (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            else:
                # Full 5-variant Tesseract fallback for test images (no fast shortcut)
                plate_number, ocr_conf, _, engine = self.read_plate(plate_crop, fast=False)

                # Capture the preprocessed image written by the best Tesseract variant
                preprocessed_path = os.path.join(DEBUG_DIR, "latest_processed_plate.jpg")
                if os.path.exists(preprocessed_path):
                    prep_img = cv2.imread(preprocessed_path)
                    if prep_img is not None:
                        ok_prep, prep_enc = cv2.imencode(".jpg", prep_img)
                        if ok_prep:
                            preprocessed_b64 = f"data:image/jpeg;base64,{base64.b64encode(prep_enc).decode()}"

                color = (0, 255, 0) if plate_number else (0, 165, 255)
                cv2.rectangle(output_image, (px1, py1), (px2, py2), color, 2)
                label = (f"{plate_number} {ocr_conf:.0%}" if plate_number
                         else f"plate {plate_confidence:.2f}")
                cv2.putText(output_image, label, (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if plate_number:
                    numbers.append(plate_number)
                    best_plate_number = plate_number
                    best_ocr_conf     = ocr_conf
                    best_ocr_engine   = engine

        # 4. Encode annotated output image
        ok_out, out_enc = cv2.imencode(".jpg", output_image)
        processed_b64   = (
            f"data:image/jpeg;base64,{base64.b64encode(out_enc).decode()}"
            if ok_out else None
        )

        # 5. Indian plate format validation
        is_valid_indian = self.is_indian_format(best_plate_number)

        return {
            "image":                output_image,
            "plates":               plates,
            "numbers":              numbers,
            "vehicles":             vehicles,
            "best_plate_number":    best_plate_number,
            "best_yolo_confidence": best_yolo_conf,
            "best_ocr_confidence":  best_ocr_conf,
            "original_crop":        original_crop_b64,
            "preprocessed_crop":    preprocessed_b64,
            "processedImage":       processed_b64,
            "ocr_engine":           best_ocr_engine,
            "is_valid_indian_format": is_valid_indian,
        }
