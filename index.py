import sys
import os
import cv2
import numpy as np
from PIL import Image
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QLabel,
    QTextEdit, QFileDialog, QHBoxLayout, QVBoxLayout,
    QWidget, QMessageBox, QFrame, QScrollArea
)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QFont
from PyQt5.QtCore import Qt, QTimer, QRect, QSize


# -------------------------------
#   LABEL WITH DRAWABLE ROI (unchanged logic)
# -------------------------------
class ImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("background-color: #2b2b2b; border: 2px solid #444;")
        self.pix = None
        self.start_pos = None
        self.end_pos = None
        self._drawing = False
        self.roi_rect = None

    def setPixmap(self, pm: QPixmap):
        super().setPixmap(pm)
        self.pix = pm

    def mousePressEvent(self, event):
        if self.pix is None:
            return
        if event.button() == Qt.LeftButton:
            self._drawing = True
            self.start_pos = event.pos()
            self.end_pos = self.start_pos
            self.update()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drawing:
            self._drawing = False
            self.end_pos = event.pos()
            self._compute_roi()
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        pen = QPen(QColor(0, 255, 100), 3)
        painter.setPen(pen)

        if self._drawing and self.start_pos and self.end_pos:
            r = QRect(self.start_pos, self.end_pos).normalized()
            painter.drawRect(r)

        if self.roi_rect:
            pen2 = QPen(QColor(255, 80, 80), 3, Qt.DashLine)
            painter.setPen(pen2)
            x, y, w, h = self._image_to_display(self.roi_rect)
            painter.drawRect(QRect(int(x), int(y), int(w), int(h)))

    def _compute_roi(self):
        if not self.pix:
            return
        x1, y1 = self.start_pos.x(), self.start_pos.y()
        x2, y2 = self.end_pos.x(), self.end_pos.y()
        rx, ry, rw, rh = QRect(x1, y1, x2 - x1, y2 - y1).normalized().getRect()
        self.roi_rect = self._display_to_image(rx, ry, rw, rh)

    def _display_to_image(self, x, y, w, h):
        if self.pix is None:
            return 0, 0, 0, 0
        label_w, label_h = self.width(), self.height()
        pix_w, pix_h = self.pix.width(), self.pix.height()
        scale = max(pix_w / label_w, pix_h / label_h)
        ix = int(x * scale)
        iy = int(y * scale)
        iw = int(w * scale)
        ih = int(h * scale)
        ix = max(0, ix)
        iy = max(0, iy)
        iw = max(0, min(iw, pix_w - ix))
        ih = max(0, min(ih, pix_h - iy))
        return ix, iy, iw, ih

    def _image_to_display(self, rect):
        if not rect or not self.pix:
            return 0, 0, 0, 0
        x, y, w, h = rect
        pix_w, pix_h = self.pix.width(), self.pix.height()
        label_w, label_h = self.width(), self.height()
        scale = 1.0 / max(pix_w / label_w, pix_h / label_h)
        return x * scale, y * scale, w * scale, h * scale


# -------------------------------
#      MAIN OCR APPLICATION - MODERN UI
# -------------------------------
class OCRApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Printed Text Scanner")
        self.resize(1200, 720)

        self.image = None
        self.display_image = None
        self.capture = None

        self.timer = QTimer()
        self.timer.timeout.connect(self._update_frame)

        # === Main Widget & Layout ===
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === Left Panel: Image + Controls ===
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)

        # Image Display
        self.image_label = ImageLabel()
        self.image_label.setFixedSize(720, 540)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setText("No Image Loaded\nClick 'Load Image' or 'Start Camera'")
        self.image_label.setStyleSheet("""
            QLabel {
                color: #aaa;
                font-size: 18px;
                font-family: Segoe UI;
            }
        """)

        # Button Style
        btn_style = """
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: none;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 8px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QPushButton#primary {
                background-color: #007acc;
            }
            QPushButton#primary:hover {
                background-color: #1485d4;
            }
            QPushButton#danger {
                background-color: #d43f3a;
            }
            QPushButton#danger:hover {
                background-color: #e55a55;
            }
        """

        # Buttons
        load_btn = QPushButton("Load Image")
        cam_start = QPushButton("Start Camera")
        cam_stop = QPushButton("Stop Camera")
        capture = QPushButton("Capture Frame")
        ocr_btn = QPushButton("Run OCR")
        clear_btn = QPushButton("Clear ROI")
        save_btn = QPushButton("Save Result")

        # Assign styles
        ocr_btn.setObjectName("primary")
        clear_btn.setObjectName("danger")
        save_btn.setObjectName("primary")

        for btn in [load_btn, cam_start, cam_stop, capture, ocr_btn, clear_btn, save_btn]:
            btn.setStyleSheet(btn_style)
            btn.setCursor(Qt.PointingHandCursor)

        # Connect buttons
        load_btn.clicked.connect(self.load_image)
        cam_start.clicked.connect(self.start_camera)
        cam_stop.clicked.connect(self.stop_camera)
        capture.clicked.connect(self.capture_frame)
        ocr_btn.clicked.connect(self.run_ocr)
        clear_btn.clicked.connect(self.clear_roi)
        save_btn.clicked.connect(self.save_overlay)

        # Button Layout
        button_row1 = QHBoxLayout()
        for b in [load_btn, cam_start, cam_stop, capture]:
            button_row1.addWidget(b)

        button_row2 = QHBoxLayout()
        for b in [ocr_btn, clear_btn, save_btn]:
            button_row2.addWidget(b)
            button_row2.addStretch()

        button_container = QVBoxLayout()
        button_container.addLayout(button_row1)
        button_container.addLayout(button_row2)
        button_container.addStretch()

        # Add to left panel
        left_panel.addWidget(self.image_label, alignment=Qt.AlignCenter)
        left_panel.addLayout(button_container)

        # === Right Panel: Text Output ===
        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText("Extracted text will appear here...")
        self.text_area.setFont(QFont("Consolas", 11))
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 10px;
            }
        """)

        # Scroll area for better resizing
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.text_area)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("<b>Extracted Text</b>"))
        right_layout.addWidget(scroll)

        # === Final Layout Assembly ===
        main_layout.addLayout(left_panel, stretch=3)
        main_layout.addLayout(right_layout, stretch=2)

        # Overall window style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #252526;
            }
            QLabel {
                color: #cccccc;
                font-family: Segoe UI;
            }
        """)

    # === All original methods unchanged (load_image, camera, OCR, etc.) ===
    # (Keeping all your working logic exactly the same)

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        bgr = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            QMessageBox.warning(self, "Error", "Failed to load image.")
            return
        self.image = bgr
        self._show_image(self.image)

    def start_camera(self):
        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            QMessageBox.warning(self, "Camera", "Could not open camera.")
            return
        self.timer.start(30)

    def stop_camera(self):
        if self.timer.isActive():
            self.timer.stop()
        if self.capture:
            self.capture.release()
            self.capture = None

    def _update_frame(self):
        if not self.capture:
            return
        ret, frame = self.capture.read()
        if ret:
            self.image = frame.copy()
            self._show_image(self.image)

    def capture_frame(self):
        if self.image is None:
            QMessageBox.information(self, "Info", "No frame to capture.")
            return
        QMessageBox.information(self, "Captured", "Frame captured. Select ROI and click 'Run OCR'.")

    def _show_image(self, bgr, overlay_boxes=None, overlay_texts=None):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        disp = rgb.copy()

        if overlay_boxes:
            for (x, y, w, h), t in zip(overlay_boxes, overlay_texts):
                cv2.rectangle(disp, (x, y), (x + w, y + h), (80, 220, 100), 3)
                cv2.putText(disp, t[:30], (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 100), 2)

        self.display_image = disp
        h, w, ch = disp.shape
        qt_img = QImage(disp.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qt_img).scaled(self.image_label.width(), self.image_label.height(),
                                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)

    def run_ocr(self):
        if self.image is None:
            QMessageBox.information(self, "Info", "Load or capture an image first.")
            return

        roi = self.image_label.roi_rect
        target = self.image[roi[1]:roi[1] + roi[3], roi[0]:roi[0] + roi[2]] if roi else self.image

        if target.size == 0:
            QMessageBox.warning(self, "Error", "Invalid ROI.")
            return

        gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 9, 75, 75)
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12)
        proc = th

        pil_img = Image.fromarray(proc)
        config = r"--oem 3 --psm 6"

        try:
            data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT, config=config)
            text = pytesseract.image_to_string(pil_img, config=config)
        except Exception as e:
            QMessageBox.critical(self, "Tesseract Error", str(e))
            return

        boxes = []
        texts = []
        for i in range(len(data["text"])):
            try:
                conf = int(data["conf"][i])
            except:
                conf = -1
            if conf > 40:
                txt = data["text"][i].strip()
                if txt:
                    x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                    boxes.append((x, y, w, h))
                    texts.append(txt)

        if roi:
            ox, oy, _, _ = roi
            boxes = [(x + ox, y + oy, w, h) for (x, y, w, h) in boxes]

        display_copy = self.image.copy()
        self._show_image(display_copy, boxes, texts)
        self.text_area.setPlainText(text.strip() or "No text detected.")

    def clear_roi(self):
        self.image_label.roi_rect = None
        self.image_label.update()
        if self.image is not None:
            self._show_image(self.image)

    def save_overlay(self):
        if self.display_image is None:
            QMessageBox.information(self, "Info", "Nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Image", "ocr_result.png", "PNG (*.png)")
        if not path:
            return
        bgr = cv2.cvtColor(self.display_image, cv2.COLOR_RGB2BGR)
        cv2.imwrite(path, bgr)
        QMessageBox.information(self, "Saved", f"Result saved to:\n{path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Best for dark themes
    window = OCRApp()
    window.show()
    sys.exit(app.exec_())