import cv2 as cv
import numpy as np
import pytesseract
import re
import os

from ultralytics import YOLO


class LicensePlateAnalyzer:

    def __init__(
        self,
        model_path="models/best.pt",
        confidence=0.40,
        tesseract_path=None
    ):

        self.model_path = model_path
        self.confidence = confidence

        self.model = None

        self.image = None
        self.output_image = None

        self.plates = []
        self.numbers = []

        # ------------------------------------------------------
        # Tesseract configuration
        # ------------------------------------------------------

        if tesseract_path is None:

            tesseract_path = (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            )

        self.tesseract_path = tesseract_path

        if os.path.exists(
            self.tesseract_path
        ):

            pytesseract.pytesseract.tesseract_cmd = (
                self.tesseract_path
            )

            self.ocr_loaded = True

            print(
                "[INFO] Tesseract OCR loaded successfully."
            )

        else:

            self.ocr_loaded = False

            print(
                "[WARNING] Tesseract executable not found:"
            )

            print(
                self.tesseract_path
            )

        # ------------------------------------------------------
        # Load YOLO
        # ------------------------------------------------------

        self.load_model()

    # ==========================================================
    # LOAD YOLO
    # ==========================================================

    def load_model(self):

        print(
            f"[INFO] Loading YOLO model: "
            f"{self.model_path}"
        )

        self.model = YOLO(
            self.model_path
        )

        print(
            "[INFO] YOLO model loaded successfully."
        )

        try:

            print(
                f"[INFO] Model classes: "
                f"{self.model.names}"
            )

        except Exception:
            pass

    # ==========================================================
    # SET IMAGE
    # ==========================================================

    def set_image(
        self,
        image
    ):

        if image is None:

            raise ValueError(
                "Image cannot be None."
            )

        self.image = image.copy()

        self.output_image = image.copy()

        self.plates = []

        self.numbers = []

    # ==========================================================
    # DETECT PLATES
    # ==========================================================

    def detect_plates(
        self,
        image=None
    ):

        if image is not None:

            self.set_image(
                image
            )

        if self.image is None:

            raise ValueError(
                "No image supplied."
            )

        results = self.model.predict(

            source=self.image,

            imgsz=640,

            conf=self.confidence,

            iou=0.45,

            verbose=False

        )

        detected_plates = []

        if not results:

            return detected_plates

        result = results[0]

        if result.boxes is None:

            return detected_plates

        for box in result.boxes:

            xyxy = (
                box.xyxy[0]
                .cpu()
                .numpy()
            )

            x1, y1, x2, y2 = map(
                int,
                xyxy
            )

            confidence = float(
                box.conf[0]
                .cpu()
                .numpy()
            )

            class_id = int(
                box.cls[0]
                .cpu()
                .numpy()
            )

            class_name = "license_plate"

            try:

                class_name = self.model.names[
                    class_id
                ]

            except Exception:

                pass

            detected_plates.append({

                "bbox": (
                    x1,
                    y1,
                    x2,
                    y2
                ),

                "confidence": confidence,

                "class_id": class_id,

                "class_name": class_name

            })

        self.plates = detected_plates

        return detected_plates

    # ==========================================================
    # CROP PLATE
    # ==========================================================

    def crop_plate(
        self,
        plate,
        image=None,
        padding=8
    ):

        if image is None:

            image = self.image

        if image is None:

            return None

        if isinstance(
            plate,
            dict
        ):

            x1, y1, x2, y2 = plate[
                "bbox"
            ]

        else:

            x1, y1, x2, y2 = plate

        height, width = image.shape[:2]

        x1 = max(
            0,
            x1 - padding
        )

        y1 = max(
            0,
            y1 - padding
        )

        x2 = min(
            width,
            x2 + padding
        )

        y2 = min(
            height,
            y2 + padding
        )

        crop = image[
            y1:y2,
            x1:x2
        ]

        if crop.size == 0:

            return None

        return crop

    # ==========================================================
    # PREPROCESS FOR TESSERACT
    # ==========================================================

    def preprocess_plate(
        self,
        plate_image
    ):

        if plate_image is None:

            return None

        # ------------------------------------------------------
        # Upscale
        # ------------------------------------------------------

        height, width = plate_image.shape[:2]

        resized = cv.resize(

            plate_image,

            (
                width * 4,
                height * 4
            ),

            interpolation=cv.INTER_CUBIC

        )

        # ------------------------------------------------------
        # Grayscale
        # ------------------------------------------------------

        gray = cv.cvtColor(
            resized,
            cv.COLOR_BGR2GRAY
        )

        # ------------------------------------------------------
        # Noise removal
        # ------------------------------------------------------

        gray = cv.bilateralFilter(
            gray,
            9,
            75,
            75
        )

        # ------------------------------------------------------
        # Contrast
        # ------------------------------------------------------

        gray = cv.equalizeHist(
            gray
        )

        # ------------------------------------------------------
        # Threshold
        # ------------------------------------------------------

        threshold = cv.threshold(

            gray,

            0,

            255,

            cv.THRESH_BINARY
            + cv.THRESH_OTSU

        )[1]

        return threshold

    # ==========================================================
    # CLEAN PLATE
    # ==========================================================

    def clean_plate_number(
        self,
        text
    ):

        if not text:

            return ""

        text = str(
            text
        ).upper()

        # Remove whitespace

        text = re.sub(
            r"\s+",
            "",
            text
        )

        # Keep only A-Z and 0-9

        text = re.sub(
            r"[^A-Z0-9]",
            "",
            text
        )

        return text

    # ==========================================================
    # TESSERACT OCR
    # ==========================================================

    def read_plate(
        self,
        plate_image
    ):

        if plate_image is None:

            return ""

        if not self.ocr_loaded:

            return ""

        try:

            processed = (
                self.preprocess_plate(
                    plate_image
                )
            )

            # --------------------------------------------------
            # Tesseract configuration
            #
            # PSM 7:
            # Treat image as a single text line
            #
            # Whitelist:
            # only letters and numbers
            # --------------------------------------------------

            config = (
                "--psm 7 "
                "-c "
                "tessedit_char_whitelist="
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789"
            )

            text = pytesseract.image_to_string(

                processed,

                config=config
            )

            plate_number = (
                self.clean_plate_number(
                    text
                )
            )

            return plate_number

        except Exception as e:

            print(
                f"[TESSERACT ERROR] {e}"
            )

            return ""

    # ==========================================================
    # GET ONE PLATE NUMBER
    # ==========================================================

    def get_number_plate_number(
        self
    ):

        if not self.plates:

            self.detect_plates()

        if not self.plates:

            return ""

        plate = self.plates[0]

        crop = self.crop_plate(
            plate
        )

        return self.read_plate(
            crop
        )

    # ==========================================================
    # GET ALL PLATE NUMBERS
    # ==========================================================

    def get_all_number_plate_numbers(
        self
    ):

        if not self.plates:

            self.detect_plates()

        self.numbers = []

        for plate in self.plates:

            crop = self.crop_plate(
                plate
            )

            number = self.read_plate(
                crop
            )

            self.numbers.append(
                number
            )

        return self.numbers

    # ==========================================================
    # DRAW RESULTS
    # ==========================================================

    def draw_results(
        self
    ):

        if self.image is None:

            return None

        output = self.image.copy()

        for index, plate in enumerate(
            self.plates
        ):

            x1, y1, x2, y2 = plate[
                "bbox"
            ]

            confidence = plate[
                "confidence"
            ]

            number = ""

            if index < len(
                self.numbers
            ):

                number = self.numbers[
                    index
                ]

            if not number:

                number = "UNKNOWN"

            # --------------------------------------------------
            # Bounding box
            # --------------------------------------------------

            cv.rectangle(

                output,

                (x1, y1),

                (x2, y2),

                (0, 255, 0),

                3

            )

            # --------------------------------------------------
            # Label
            # --------------------------------------------------

            label = (
                f"{number} | "
                f"{confidence:.0%}"
            )

            font = (
                cv.FONT_HERSHEY_SIMPLEX
            )

            scale = 0.65

            thickness = 2

            (
                text_width,
                text_height
            ), baseline = cv.getTextSize(

                label,

                font,

                scale,

                thickness

            )

            label_y = max(
                y1,
                text_height + 10
            )

            cv.rectangle(

                output,

                (
                    x1,
                    label_y - text_height - 10
                ),

                (
                    x1 + text_width + 12,
                    label_y + baseline
                ),

                (0, 255, 0),

                -1

            )

            cv.putText(

                output,

                label,

                (
                    x1 + 6,
                    label_y
                ),

                font,

                scale,

                (0, 0, 0),

                thickness

            )

        self.output_image = output

        return output

    # ==========================================================
    # COMPLETE ANALYSIS
    # ==========================================================

    def analyze(
        self,
        image
    ):

        self.set_image(
            image
        )

        # YOLO

        self.detect_plates()

        # Tesseract

        self.get_all_number_plate_numbers()

        # Draw

        output = (
            self.draw_results()
        )

        return {

            "image": output,

            "plates": self.plates,

            "numbers": self.numbers,

            "plate_count":
                len(self.plates)

        }

    # ==========================================================
    # STATUS
    # ==========================================================

    def get_status(
        self
    ):

        return {

            "model_loaded":
                self.model is not None,

            "ocr_loaded":
                self.ocr_loaded,

            "ocr_engine":
                "Tesseract OCR",

            "model":
                "YOLOv8n",

            "task":
                "Object Detection",

            "classes":
                "license_plate",

            "input_size":
                "640x640",

            "plates_detected":
                len(self.plates),

            "plates_read":
                len([
                    x for x in self.numbers
                    if x
                ])

        }