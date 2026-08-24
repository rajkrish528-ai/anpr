"""
ANPR Analyzer — YOLO vehicle detection + YOLO plate detection + Tesseract OCR.
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
DEBUG_DIR = "debug"

if DEBUG_ANPR:
    os.makedirs(DEBUG_DIR, exist_ok=True)

class LicensePlateAnalyzer:
    """AI-powered license plate recognition using YOLOv8 + Tesseract OCR."""

    def __init__(
        self,
        vehicle_model_path="yolo11n.pt",
        model_path="models/best.pt",
        confidence=0.30,
        tesseract_path=None,
    ):
        self.vehicle_model_path = vehicle_model_path
        self.model_path = model_path
        self.confidence = confidence

        # ── Tesseract configuration ──
        if tesseract_path is None:
            tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        self.tesseract_path = tesseract_path
        self.ocr_loaded = False
        
        # 1. First check if it's explicitly at the Windows path
        if os.path.exists(self.tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
            
        # 2. Try to get version (this will succeed if in PATH or if path above worked)
        try:
            version = pytesseract.get_tesseract_version()
            print(f"[INFO] Tesseract OCR loaded successfully. Version: {version}")
            self.ocr_loaded = True
        except Exception as e:
            print(f"[WARNING] Tesseract executable not found or failed to load: {e}")
            print(f"Looked at: {self.tesseract_path} and system PATH.")
            print("Please install Tesseract OCR and update the path.")

        # ── Load YOLO models ──
        print(f"[INFO] Loading YOLO models: {self.vehicle_model_path}, {self.model_path}")
        self.vehicle_model = YOLO(self.vehicle_model_path)
        self.plate_model = YOLO(self.model_path)
        print("[INFO] YOLO models loaded successfully.")

        self.vehicle_classes = {
            2: "car",
            3: "motorcycle",
            5: "bus",
            7: "truck",
        }

    # ──────────────────────────────────────────────────────────
    # Plate text cleaning & validation
    # ──────────────────────────────────────────────────────────

    def normalize_plate_number(self, text: str) -> str:
        """Keep only uppercase A-Z and 0-9."""
        if not text:
            return ""
        text = str(text).upper()
        # Remove anything that isn't a letter or number
        text = re.sub(r"[^A-Z0-9]", "", text)
        return text

    def validate_plate(self, text: str):
        """Reject garbage OCR. A valid plate must:
        - Be 6-13 characters (Indian plates are 8-10; relax to 6 minimum to handle partial reads)
        - Contain at LEAST 2 digits  (state code NN + district NN = always digits present)
        - Contain at LEAST 2 letters (state code = 2 letters minimum)
        Returns the cleaned text or empty string.
        """
        text = self.normalize_plate_number(text)
        if len(text) < 6 or len(text) > 13:
            return ""
        digit_count = sum(1 for c in text if c.isdigit())
        alpha_count = sum(1 for c in text if c.isalpha())
        if digit_count < 2 or alpha_count < 2:
            return ""  # 'NDLJB' (0 digits), '12345678' (0 letters) — both rejected
        return text

    # ──────────────────────────────────────────────────────────
    # Preprocessing for Tesseract
    # ──────────────────────────────────────────────────────────

    def get_preprocessing_variants(self, plate_image, fast: bool = False):
        """Create variants of the plate image for Tesseract.

        fast=True  → 2 variants (live camera, low latency).
        fast=False → 5 variants (uploaded image, maximum accuracy).

        Key design choices:
        - NEVER binarize large crops (>400px) with aggressive threshold.
          Tesseract's internal binarization handles that better.
        - Upscale only when the crop is too small (<150px wide).
        - Bilateral filter denoises while keeping character edges sharp.
        - CLAHE enhances local contrast without destroying character shape.
        """
        if plate_image is None or plate_image.size == 0:
            return []

        h, w = plate_image.shape[:2]
        variants = []

        # ── Choose upscale factor based on actual crop size ──
        # Large crops (phone photo, full-frame car) need NO upscaling;
        # tiny crops (small surveillance frame) need 3×.
        if max(w, h) >= 400:
            scale = 1   # already large and clear
        elif max(w, h) >= 150:
            scale = 2
        else:
            scale = 3

        # Produce scaled-up colour image and its grayscale
        if scale > 1:
            upscaled = cv2.resize(plate_image, (w * scale, h * scale),
                                  interpolation=cv2.INTER_CUBIC)
        else:
            upscaled = plate_image  # no copy needed — read-only below
        gray_upscaled = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)

        # 1. Original grayscale (fastest; best for clean, high-resolution plates)
        gray_original = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        variants.append(("original_gray", gray_original))

        # 2. Scaled grayscale (same as #1 when scale=1)
        variants.append(("upscaled_gray", gray_upscaled))

        if fast:
            return variants  # 2 variants ≈ 2 Tesseract calls for camera

        # 3. CLAHE-enhanced grayscale — NO binarization.
        #    CLAHE boosts local contrast; Tesseract's own binarizer handles the rest.
        #    Replacing the old CLAHE+Otsu which destroyed characters at large scales.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray_upscaled)
        variants.append(("clahe_gray", gray_clahe))

        # 4. Bilateral-denoised grayscale
        #    Smooths noise while preserving sharp character edges.
        #    Replaces sharpened_thresh which amplified noise at large scales
        #    and caused Tesseract to confidently read garbage patterns.
        gray_bilateral = cv2.bilateralFilter(gray_upscaled, d=9, sigmaColor=50, sigmaSpace=50)
        variants.append(("bilateral_gray", gray_bilateral))

        # 5. Adaptive threshold (useful when lighting is uneven across the plate)
        #    Only applied AFTER bilateral denoising to avoid amplifying noise.
        gray_denoised = cv2.GaussianBlur(gray_upscaled, (3, 3), 0)
        thresh_adaptive = cv2.adaptiveThreshold(
            gray_denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
        )
        variants.append(("adaptive_thresh", thresh_adaptive))

        return variants

    # ──────────────────────────────────────────────────────────
    # Tesseract OCR
    # ──────────────────────────────────────────────────────────

    def read_plate(self, plate_image, fast: bool = False):
        """Read text from a cropped plate image using multiple preprocessing strategies.
        Returns (best_normalized_text, confidence, raw_text).

        Scoring uses OCR confidence WEIGHTED by Indian plate format match:
          - Results matching Indian registration pattern get a 2× score bonus.
          - Results with 8-10 chars (typical Indian plate) get a slight length bonus.
        This prevents short garbage strings (e.g. 'NDLJB') from winning over
        partially-correct but format-like reads (e.g. 'GJ01HU696').

        fast=True  → 2 variants × 1 PSM = 2 Tesseract calls (live camera).
        fast=False → 5 variants × 3 PSMs = up to 15 calls (uploaded image).
        """
        if not self.ocr_loaded:
            if DEBUG_ANPR: print("[OCR] Failed: Tesseract not loaded")
            return "", 0.0, ""

        variants = self.get_preprocessing_variants(plate_image, fast=fast)
        if not variants:
            if DEBUG_ANPR: print("[OCR] Failed: No image variants generated")
            return "", 0.0, ""

        # PSM 7  = single text line   (best for one-line plates)
        # PSM 8  = single word        (good for licence plates with no spaces)
        # PSM 6  = uniform block      (fallback for two-line plates)
        # --oem 3 = LSTM neural engine (more accurate than legacy)
        all_configs = [
            "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        ]
        configs = all_configs[:1] if fast else all_configs

        # Indian plate pattern for format-weighted scoring
        # Covers: GJ01HU6963 / DL14TE5184 / MH12AB1234 / KA01MX5678 / HR26AY3232
        _indian_re = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$")

        best_plate = ""
        best_conf = 0.0
        best_raw = ""
        best_variant = ""
        best_weighted = 0.0  # weighted score used for selection

        for variant_name, img in variants:
            for config in configs:
                try:
                    raw_text = pytesseract.image_to_string(img, config=config).strip()
                except Exception as exc:
                    if DEBUG_ANPR:
                        print(f"  [OCR] Tesseract error on {variant_name}: {exc}")
                    continue

                normalized = self.normalize_plate_number(raw_text)
                valid_plate = self.validate_plate(normalized)
                if not valid_plate:
                    continue

                try:
                    data = pytesseract.image_to_data(
                        img, config=config, output_type=pytesseract.Output.DICT
                    )
                    confs = [int(c) for c in data["conf"] if int(c) > 0]
                    conf = (sum(confs) / len(confs) / 100.0) if confs else 0.5
                except Exception:
                    conf = 0.5

                # ── Format-weighted score ────────────────────────────
                # Indian-format match → 2× bonus; typical 8-10 char length → bonus
                format_bonus = 2.0 if _indian_re.match(valid_plate) else 1.0
                # Length bonus: 0 extra at 6 chars, up to +40% at 10+ chars
                length_bonus = 1.0 + max(0, len(valid_plate) - 6) * 0.05
                weighted = conf * format_bonus * length_bonus

                psm_str = config.split("--psm")[1].split()[0] if "--psm" in config else "?"
                if DEBUG_ANPR:
                    fmt_tag = " [INDIAN]" if format_bonus > 1 else ""
                    print(f"  [OCR] {variant_name} PSM{psm_str}: '{raw_text.strip()}' "
                          f"→ '{valid_plate}' conf={conf:.2f} w={weighted:.2f}{fmt_tag}")

                if weighted > best_weighted:
                    best_weighted = weighted
                    best_conf = conf
                    best_plate = valid_plate
                    best_raw = raw_text
                    best_variant = variant_name
                    if DEBUG_ANPR:
                        cv2.imwrite(
                            os.path.join(DEBUG_DIR, "latest_processed_plate.jpg"), img
                        )

                if best_weighted > 1.5:  # early exit: high-conf Indian-format match
                    break
            if best_weighted > 1.5:
                break

        if DEBUG_ANPR:
            print(f"[OCR] FINAL: '{best_raw.strip()}' → '{best_plate}' "
                  f"conf={best_conf:.2f} weighted={best_weighted:.2f} (from {best_variant})")
            if not best_plate:
                print("[OCR] No valid plate found across all variants.")

        return best_plate, best_conf, best_raw

    # ──────────────────────────────────────────────────────────
    # Full analysis pipeline
    # ──────────────────────────────────────────────────────────

    def analyze(self, image, fast: bool = False):
        """Run full ANPR pipeline on a single frame.

        fast=True  → use 2-variant OCR for live camera (low latency).
        fast=False → use 5-variant OCR for maximum accuracy.
        """
        if image is None:
            raise ValueError("Image cannot be None.")

        output_image = image.copy()
        h, w = image.shape[:2]

        if DEBUG_ANPR:
            print("\n" + "="*50)
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
                cv2.putText(
                    output_image,
                    f"{self.vehicle_classes[cls]} {conf:.2f}",
                    (vx1, vy1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 0, 0), 2,
                )
                vehicles.append({
                    "vehicle_type": self.vehicle_classes[cls],
                    "vehicle_confidence": round(float(conf), 3),
                })

        # 2. Detect plates — collect all, pick the best (highest confidence × area)
        plates = []
        numbers = []

        all_plate_boxes = []
        plate_results = self.plate_model(image, conf=self.confidence, verbose=False)
        for plate_result in plate_results:
            if plate_result.boxes is None:
                continue
            for box, conf in zip(plate_result.boxes.xyxy, plate_result.boxes.conf):
                px1, py1, px2, py2 = map(int, box)
                plate_confidence = float(conf)
                area = (px2 - px1) * (py2 - py1)
                score = plate_confidence * (area / max(1, w * h))
                all_plate_boxes.append({
                    "bbox": (px1, py1, px2, py2),
                    "confidence": plate_confidence,
                    "area": area,
                    "score": score,
                })
                plates.append({"confidence": plate_confidence})

        # Sort best-first; draw dim boxes for non-primary
        all_plate_boxes.sort(key=lambda d: d["score"], reverse=True)
        for det in all_plate_boxes[1:]:
            px1, py1, px2, py2 = det["bbox"]
            cv2.rectangle(output_image, (px1, py1), (px2, py2), (128, 128, 128), 1)

        if all_plate_boxes:
            primary = all_plate_boxes[0]
            px1, py1, px2, py2 = primary["bbox"]
            plate_confidence = primary["confidence"]

            if DEBUG_ANPR:
                print(f"[ANPR] Best plate: bbox={px1},{py1},{px2},{py2} conf={plate_confidence:.2f} score={primary['score']:.4f}")

            # Proportional padding: 6% of bbox dimension (reduced from 10%)
            # Rationale: 10% (81px) was too much on a 815px plate — included car body
            # on both sides which confused OCR. 6% (49px) gives safety margin while
            # keeping the crop focused on the plate region.
            bw = max(1, px2 - px1)
            bh = max(1, py2 - py1)
            pad_x = max(8, int(0.06 * bw))
            pad_y = max(5, int(0.06 * bh))

            cx1 = max(0, px1 - pad_x)
            cy1 = max(0, py1 - pad_y)
            cx2 = min(w, px2 + pad_x)
            cy2 = min(h, py2 + pad_y)

            plate_crop = image[cy1:cy2, cx1:cx2]
            crop_h, crop_w = plate_crop.shape[:2]

            if DEBUG_ANPR:
                print(f"[CROP] {crop_w}x{crop_h} (padded from {bw}x{bh})")
                cv2.imwrite(os.path.join(DEBUG_DIR, "latest_plate.jpg"), plate_crop)

            if crop_w < 40 or crop_h < 15:
                if DEBUG_ANPR:
                    print("[CROP] Plate too small for reliable OCR. Skipping.")
                cv2.rectangle(output_image, (px1, py1), (px2, py2), (0, 165, 255), 2)
                cv2.putText(output_image, "TOO SMALL", (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            else:
                plate_number, ocr_confidence, raw_text = self.read_plate(plate_crop, fast=fast)

                color = (0, 255, 0) if plate_number else (0, 165, 255)
                cv2.rectangle(output_image, (px1, py1), (px2, py2), color, 2)
                label = (f"{plate_number} {ocr_confidence:.0%}" if plate_number
                         else f"plate {plate_confidence:.2f}")
                cv2.putText(output_image, label, (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if plate_number:
                    numbers.append(plate_number)

        return {
            "image": output_image,
            "plates": plates,
            "numbers": numbers,
            "vehicles": vehicles,
        }

    # ──────────────────────────────────────────────────────────
    # Status (for pipeline info endpoint)
    # ──────────────────────────────────────────────────────────

    def get_status(self):
        return {
            "model_loaded": self.plate_model is not None,
            "ocr_loaded": self.ocr_loaded,
            "ocr_engine": "Tesseract OCR",
            "model": "YOLOv8",
            "task": "Object Detection",
            "classes": "vehicle + license_plate",
            "input_size": "640x640",
        }

    # ──────────────────────────────────────────────────────────
    # Extended analysis with crop images (for /api/anpr/image)
    # ──────────────────────────────────────────────────────────

    def analyze_with_crops(self, image):
        """Run full ANPR pipeline and also return base64-encoded crop images.

        KEY FIX: Instead of 'last detection wins', this method collects ALL
        plate detections, ranks them by (confidence × bbox_area / image_area),
        and uses only the TOP-RANKED detection for the crop and OCR.  This
        prevents the small 'IND' badge box (or any secondary detection) from
        overwriting the crop from the full plate box.

        Returns the analyze() keys plus:
          original_crop, preprocessed_crop, ocr_confidence,
          ocr_engine, is_valid_indian_format.
        """
        if image is None:
            raise ValueError("Image cannot be None.")

        output_image = image.copy()
        h, w = image.shape[:2]

        if DEBUG_ANPR:
            print("\n" + "="*50)
            print(f"[ANPR] analyze_with_crops ({w}x{h})")

        # ── 1. Vehicle detection ──────────────────────────────────────────
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
                cv2.putText(
                    output_image,
                    f"{self.vehicle_classes[cls_int]} {float(conf):.2f}",
                    (vx1, vy1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 0, 0), 2,
                )
                vehicles.append({
                    "vehicle_type": self.vehicle_classes[cls_int],
                    "vehicle_confidence": round(float(conf), 3),
                })

        # ── 2. Plate detection — collect ALL, rank by score ─────────────────
        plates = []
        numbers = []
        best_plate_number = ""
        best_yolo_confidence = 0.0
        best_ocr_confidence = 0.0
        original_crop_b64 = None
        preprocessed_crop_b64 = None

        all_detections = []
        plate_results = self.plate_model(image, conf=self.confidence, verbose=False)
        for plate_result in plate_results:
            if plate_result.boxes is None:
                continue
            for box, conf in zip(plate_result.boxes.xyxy, plate_result.boxes.conf):
                px1, py1, px2, py2 = map(int, box)
                plate_confidence = float(conf)
                area = (px2 - px1) * (py2 - py1)
                # Score = confidence × normalised area (prefers large confident boxes)
                score = plate_confidence * (area / max(1, w * h))
                all_detections.append({
                    "bbox": (px1, py1, px2, py2),
                    "confidence": plate_confidence,
                    "area": area,
                    "score": score,
                })
                plates.append({"confidence": plate_confidence})

        # Sort best-first
        all_detections.sort(key=lambda d: d["score"], reverse=True)

        if DEBUG_ANPR:
            for i, det in enumerate(all_detections):
                px1, py1, px2, py2 = det["bbox"]
                print(f"[DETECT] #{i} bbox=({px1},{py1},{px2},{py2}) conf={det['confidence']:.2f} area={det['area']} score={det['score']:.5f}")

        # Draw secondary (non-primary) detections as dim grey
        for det in all_detections[1:]:
            px1, py1, px2, py2 = det["bbox"]
            cv2.rectangle(output_image, (px1, py1), (px2, py2), (128, 128, 128), 1)

        # ── 3. Process ONLY the primary (best-scored) detection ────────────
        if all_detections:
            primary = all_detections[0]
            px1, py1, px2, py2 = primary["bbox"]
            plate_confidence = primary["confidence"]
            best_yolo_confidence = plate_confidence

            if DEBUG_ANPR:
                print(f"[PRIMARY] bbox=({px1},{py1},{px2},{py2}) conf={plate_confidence:.2f}")

            # Proportional padding: 6% of bbox dimension
            # (same as analyze() — reduced from 10% to avoid including car body)
            bw = max(1, px2 - px1)
            bh = max(1, py2 - py1)
            pad_x = max(8, int(0.06 * bw))
            pad_y = max(5, int(0.06 * bh))

            cx1 = max(0, px1 - pad_x)
            cy1 = max(0, py1 - pad_y)
            cx2 = min(w, px2 + pad_x)
            cy2 = min(h, py2 + pad_y)

            plate_crop = image[cy1:cy2, cx1:cx2]
            crop_h, crop_w = plate_crop.shape[:2]

            if DEBUG_ANPR:
                print(f"[CROP] raw bbox {bw}x{bh} → padded crop {crop_w}x{crop_h} (pad_x={pad_x}, pad_y={pad_y})")
                cv2.imwrite(os.path.join(DEBUG_DIR, "latest_plate.jpg"), plate_crop)

            # Always encode the raw crop (for display)
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
                # Run multi-variant OCR (full 5-variant mode — no fast shortcut for test images)
                plate_number, ocr_conf, _ = self.read_plate(plate_crop, fast=False)

                # Capture the preprocessed image that gave the best OCR result
                preprocessed_path = os.path.join(DEBUG_DIR, "latest_processed_plate.jpg")
                if os.path.exists(preprocessed_path):
                    prep_img = cv2.imread(preprocessed_path)
                    if prep_img is not None:
                        ok_prep, prep_enc = cv2.imencode(".jpg", prep_img)
                        if ok_prep:
                            preprocessed_crop_b64 = f"data:image/jpeg;base64,{base64.b64encode(prep_enc).decode()}"

                color = (0, 255, 0) if plate_number else (0, 165, 255)
                cv2.rectangle(output_image, (px1, py1), (px2, py2), color, 2)
                label = (f"{plate_number} {ocr_conf:.0%}" if plate_number
                         else f"plate {plate_confidence:.2f}")
                cv2.putText(output_image, label, (px1, py1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if plate_number:
                    numbers.append(plate_number)
                    best_plate_number = plate_number
                    best_ocr_confidence = ocr_conf

        # ── 4. Encode full annotated output image ───────────────────────
        ok_out, out_enc = cv2.imencode(".jpg", output_image)
        processed_b64 = (
            f"data:image/jpeg;base64,{base64.b64encode(out_enc).decode()}"
            if ok_out else None
        )

        # ── 5. Indian plate format validation ────────────────────────
        # Pattern covers: GJ01HU6963 / DL14TE5182 / MH12AB1234 / KA01MX5678
        indian_pattern = re.compile(
            r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$"
        )
        is_valid_indian = bool(best_plate_number and indian_pattern.match(best_plate_number))

        return {
            "image": output_image,
            "plates": plates,
            "numbers": numbers,
            "vehicles": vehicles,
            "best_plate_number": best_plate_number,
            "best_yolo_confidence": best_yolo_confidence,
            "best_ocr_confidence": best_ocr_confidence,
            "original_crop": original_crop_b64,
            "preprocessed_crop": preprocessed_crop_b64,
            "processedImage": processed_b64,
            "ocr_engine": "Tesseract OCR",
            "is_valid_indian_format": is_valid_indian,
        }

