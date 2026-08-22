"""
ANPR Analyzer — YOLO vehicle detection + YOLO plate detection + Tesseract OCR.
"""
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
        confidence=0.40,
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
        """Do not accept garbage OCR. Ensure it looks somewhat like a plate."""
        text = self.normalize_plate_number(text)
        # Indian plates generally have at least 4 chars (e.g. up to 10 chars like MH12AB1234)
        # We enforce a reasonable minimum to drop garbage like "ABC" or "123"
        if len(text) < 4 or len(text) > 13:
            return ""
        return text

    # ──────────────────────────────────────────────────────────
    # Preprocessing for Tesseract
    # ──────────────────────────────────────────────────────────

    def get_preprocessing_variants(self, plate_image):
        """Create multiple variants of the plate image to give Tesseract the best chance."""
        if plate_image is None or plate_image.size == 0:
            return []

        variants = []
        
        # 1. Original + grayscale
        gray_original = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        variants.append(("original_gray", gray_original))
        
        # Upscale
        h, w = plate_image.shape[:2]
        upscaled = cv2.resize(plate_image, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
        gray_upscaled = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
        
        # 2. Upscaled + grayscale
        variants.append(("upscaled_gray", gray_upscaled))
        
        # 3. Upscaled + threshold
        gray_blur = cv2.bilateralFilter(gray_upscaled, 9, 75, 75)
        gray_eq = cv2.equalizeHist(gray_blur)
        _, thresh_otsu = cv2.threshold(gray_eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("upscaled_thresh", thresh_otsu))
        
        # 4. Upscaled + adaptive threshold
        thresh_adaptive = cv2.adaptiveThreshold(
            gray_upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        variants.append(("upscaled_adaptive", thresh_adaptive))
        
        # 5. Sharpened + threshold
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray_upscaled, -1, kernel)
        _, thresh_sharp = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("sharpened_thresh", thresh_sharp))

        return variants

    # ──────────────────────────────────────────────────────────
    # Tesseract OCR
    # ──────────────────────────────────────────────────────────

    def read_plate(self, plate_image):
        """Read text from a cropped plate image using multiple strategies.
        Returns (best_normalized_text, confidence, raw_text)."""
        if not self.ocr_loaded:
            if DEBUG_ANPR: print("[OCR] Failed: Tesseract not loaded")
            return "", 0.0, ""

        variants = self.get_preprocessing_variants(plate_image)
        if not variants:
            if DEBUG_ANPR: print("[OCR] Failed: No image variants generated")
            return "", 0.0, ""

        configs = [
            "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", # Single line
            "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", # Uniform block (2 lines)
            "--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" # Sparse text
        ]

        best_plate = ""
        best_conf = 0.0
        best_raw = ""
        best_variant = ""

        # Loop through all variants and configs to find the highest confidence valid read
        for variant_name, img in variants:
            for config in configs:
                raw_text = pytesseract.image_to_string(img, config=config).strip()
                normalized = self.normalize_plate_number(raw_text)
                
                valid_plate = self.validate_plate(normalized)
                if not valid_plate:
                    continue

                try:
                    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
                    confs = [int(c) for c in data["conf"] if int(c) > 0]
                    conf = (sum(confs) / len(confs) / 100.0) if confs else 0.5
                except Exception:
                    conf = 0.5
                    
                if DEBUG_ANPR:
                    print(f"  [OCR-TEST] Variant: {variant_name}, PSM: {config[:8]}, Raw: '{raw_text}', Norm: '{normalized}', Conf: {conf:.2f}")

                if conf > best_conf:
                    best_conf = conf
                    best_plate = valid_plate
                    best_raw = raw_text
                    best_variant = variant_name

                    # Save the variant that worked best
                    if DEBUG_ANPR:
                        cv2.imwrite(os.path.join(DEBUG_DIR, "latest_processed_plate.jpg"), img)

                # Early exit if we get a very high confidence read
                if best_conf > 0.85:
                    break
            if best_conf > 0.85:
                break

        if DEBUG_ANPR:
            print(f"[OCR] FINAL SELECTED -> Raw: '{best_raw}', Normalized: '{best_plate}', Conf: {best_conf:.2f} (from {best_variant})")
            if not best_plate:
                print("[OCR] OCR failed or returned garbage.")

        return best_plate, best_conf, best_raw

    # ──────────────────────────────────────────────────────────
    # Full analysis pipeline
    # ──────────────────────────────────────────────────────────

    def analyze(self, image):
        """Run full ANPR pipeline on a single frame."""
        if image is None:
            raise ValueError("Image cannot be None.")

        output_image = image.copy()
        h, w = image.shape[:2]
        
        if DEBUG_ANPR:
            print("\n" + "="*50)
            print(f"[ANPR] Analyzing new frame ({w}x{h})")

        # 1. Detect and draw vehicles
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

        # 2. Detect plates on the FULL image
        plates = []
        numbers = []

        plate_results = self.plate_model(image, conf=self.confidence, verbose=False)
        for plate_result in plate_results:
            if plate_result.boxes is None:
                continue
            for box, conf in zip(plate_result.boxes.xyxy, plate_result.boxes.conf):
                px1, py1, px2, py2 = map(int, box)
                plate_confidence = float(conf)
                
                if DEBUG_ANPR:
                    print(f"[ANPR] YOLO detected plate")
                    print(f"       Bounding box: {px1},{py1},{px2},{py2}")
                    print(f"       Confidence: {plate_confidence:.2f}")

                # Configurable padding
                padding = 10
                cx1 = max(0, px1 - padding)
                cy1 = max(0, py1 - padding)
                cx2 = min(w, px2 + padding)
                cy2 = min(h, py2 + padding)

                plate_crop = image[cy1:cy2, cx1:cx2]
                
                crop_h, crop_w = plate_crop.shape[:2]
                if DEBUG_ANPR:
                    print(f"[CROP] Width: {crop_w}, Height: {crop_h}")
                    cv2.imwrite(os.path.join(DEBUG_DIR, "latest_plate.jpg"), plate_crop)

                if crop_w < 40 or crop_h < 15:
                    if DEBUG_ANPR:
                        print("[CROP] Plate too small for reliable OCR. Skipping.")
                    # Draw orange box to indicate detection but skipped OCR
                    cv2.rectangle(output_image, (px1, py1), (px2, py2), (0, 165, 255), 2)
                    cv2.putText(output_image, "TOO SMALL", (px1, py1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                    plates.append({"confidence": plate_confidence})
                    continue

                # Run OCR
                plate_number, ocr_confidence, raw_text = self.read_plate(plate_crop)

                # Draw bounding box — green if OCR succeeded, orange if plate detected but OCR failed
                color = (0, 255, 0) if plate_number else (0, 165, 255)
                cv2.rectangle(output_image, (px1, py1), (px2, py2), color, 2)

                label = f"{plate_number} {ocr_confidence:.0%}" if plate_number else f"plate {plate_confidence:.2f}"
                cv2.putText(
                    output_image, label,
                    (px1, py1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, color, 2,
                )

                if plate_number:
                    numbers.append(plate_number)
                plates.append({"confidence": plate_confidence})

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