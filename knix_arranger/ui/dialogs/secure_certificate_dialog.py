"""
KNX-Secure-Zertifikate einlesen (FA-2704b): Aufkleber-Text eintippen oder
einfügen, QR-Codes aus einem Foto oder live von der Kamera. Jedes Zertifikat
findet sein Gerät über die Seriennummer; ohne bekannte Seriennummer wählt
man das Gerät, es übernimmt die Seriennummer.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...services import knx_secure_certificate as kc

_COL_SERIAL, _COL_DEVICE, _COL_STATUS, _COL_TAKE = range(4)
_SCAN_INTERVAL_MS = 400
_SCAN_WIDTH = 1280


def qimage_to_gray(image: QImage, max_width: int = _SCAN_WIDTH) -> QImage:
    """Für die QR-Erkennung: Graustufen, verkleinert (zxing-cpp liest QImage
    direkt; numpy ist im Release-Build nicht enthalten)."""
    if max_width and image.width() > max_width:
        image = image.scaledToWidth(max_width, Qt.SmoothTransformation)
    return image.convertToFormat(QImage.Format_Grayscale8)


def _device_text(device) -> str:
    return f"{device.physical_address or '–'}  {kc.device_name(device)}"


class SecureCertificateDialog(QDialog):
    """Zertifikate sammeln, Geräten zuordnen, ins (entsperrte) Archiv übernehmen."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KNX-Secure-Zertifikate einlesen")
        self.setMinimumSize(900, 640)
        self._project = project
        self._config = project.knx_secure
        self._scanned: list[kc.Certificate] = []      # Foto/Kamera
        self._typed: list[kc.Certificate] = []        # Textfeld
        self._choice: dict[kc.Certificate, str] = {}  # Zertifikat -> Geräte-id
        self._take: dict[kc.Certificate, bool] = {}
        self._camera = self._session = self._video = None
        self._frame: QImage | None = None
        self.applied = 0
        self._matches: list = []

        layout = QVBoxLayout(self)
        info = QLabel(
            "Zertifikat vom Aufkleber oder von der Secure-Karte: Text eintippen bzw. "
            "einfügen (36 Zeichen, auch mehrere), Foto laden oder Karten vor die "
            "Kamera halten. Das Gerät wird über die Seriennummer gefunden.")
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("z.B. ADCQCC-EKHG54-RTEP53-UOT3TA-EAVHUV-3QG3YL")
        self._text.setFixedHeight(72)
        self._text.textChanged.connect(self._on_text_changed)
        row.addWidget(self._text, 1)
        side = QVBoxLayout()
        self._btn_photo = QPushButton("Foto laden…")
        self._btn_photo.clicked.connect(self._load_photo)
        side.addWidget(self._btn_photo)
        self._camera_combo = QComboBox()
        side.addWidget(self._camera_combo)
        self._btn_camera = QPushButton("Kamera starten")
        self._btn_camera.clicked.connect(self._toggle_camera)
        side.addWidget(self._btn_camera)
        row.addLayout(side)
        layout.addLayout(row)

        self._video_host = QWidget()
        self._video_layout = QVBoxLayout(self._video_host)
        self._video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_host.setVisible(False)
        layout.addWidget(self._video_host)
        self._camera_status = QLabel("")
        self._camera_status.setStyleSheet("color: #2E7D32;")
        layout.addWidget(self._camera_status)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Seriennummer", "Gerät", "Status", "Übernehmen"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(_COL_DEVICE, self._table.horizontalHeader().ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(_SCAN_INTERVAL_MS)
        self._timer.timeout.connect(self._scan_frame)
        self._setup_sources()

    # ── Quellen ──

    def _setup_sources(self) -> None:
        if not kc.qr_available():
            for w in (self._btn_photo, self._btn_camera, self._camera_combo):
                w.setEnabled(False)
                w.setToolTip("QR-Erkennung nicht verfügbar (zxing-cpp fehlt)")
            return
        try:
            from PySide6.QtMultimedia import QMediaDevices
            cameras = QMediaDevices.videoInputs()
        except ImportError:
            cameras = []
        for camera in cameras:
            self._camera_combo.addItem(camera.description(), camera)
        if not cameras:
            self._camera_combo.addItem("keine Kamera")
            self._camera_combo.setEnabled(False)
            self._btn_camera.setEnabled(False)

    def _on_text_changed(self) -> None:
        self._typed = kc.certificates_in_text(self._text.toPlainText())
        self._refresh()

    def _add_scanned(self, certificates: list) -> int:
        new = [c for c in certificates if c not in self._scanned and c not in self._typed]
        self._scanned.extend(new)
        if new:
            QApplication.beep()
            self._refresh()
        return len(new)

    def _load_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Foto mit Zertifikaten", "", "Bilder (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Foto", "Das Bild lässt sich nicht öffnen.")
            return
        # Volle Auflösung: auf einem Foto mehrerer Karten sind die Codes klein
        found = kc.certificates_in_image(qimage_to_gray(image, max_width=0))
        added = self._add_scanned(found)
        if not found:
            QMessageBox.information(self, "Foto", "Im Bild wurde kein Zertifikat-QR-Code gefunden.")
        else:
            self._camera_status.setText(f"Foto: {len(found)} Zertifikat(e) erkannt, {added} neu.")

    def _toggle_camera(self) -> None:
        if self._camera is not None:
            self._stop_camera()
            return
        from PySide6.QtMultimedia import QCamera, QMediaCaptureSession
        from PySide6.QtMultimediaWidgets import QVideoWidget
        device = self._camera_combo.currentData()
        if device is None:
            return
        self._camera = QCamera(device)
        self._session = QMediaCaptureSession()
        self._session.setCamera(self._camera)
        self._video = QVideoWidget()
        self._video.setMinimumHeight(300)
        self._video_layout.addWidget(self._video)
        self._session.setVideoOutput(self._video)
        self._video.videoSink().videoFrameChanged.connect(self._on_frame)
        self._camera.errorOccurred.connect(
            lambda _e, text: self._camera_status.setText(f"Kamera: {text}"))
        self._video_host.setVisible(True)
        self._camera.start()
        self._timer.start()
        self._btn_camera.setText("Kamera stoppen")
        self._camera_status.setText("Karte mit dem QR-Code vor die Kamera halten …")

    def _stop_camera(self) -> None:
        self._timer.stop()
        if self._camera is not None:
            self._camera.stop()
        if self._video is not None:
            self._video.deleteLater()
        self._camera = self._session = self._video = None
        self._frame = None
        self._video_host.setVisible(False)
        self._btn_camera.setText("Kamera starten")

    def _on_frame(self, frame) -> None:
        self._frame = frame

    def _scan_frame(self) -> None:
        frame, self._frame = self._frame, None
        if frame is None or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        found = kc.certificates_in_image(qimage_to_gray(image))
        if self._add_scanned(found):
            self._camera_status.setText(
                f"Erkannt: {', '.join(c.label for c in found)} – nächste Karte …")

    # ── Tabelle ──

    def certificates(self) -> list:
        return self._typed + [c for c in self._scanned if c not in self._typed]

    def _refresh(self) -> None:
        matches = kc.match_certificates(self._config, self._project, self.certificates())
        assignable = kc.assignable_devices(self._project, self._config)
        self._matches = matches
        self._table.setRowCount(len(matches))
        for row, match in enumerate(matches):
            cert = match.certificate
            self._table.setItem(row, _COL_SERIAL, QTableWidgetItem(cert.label))
            if match.device is not None:
                self._table.setCellWidget(row, _COL_DEVICE, None)
                self._table.setItem(row, _COL_DEVICE, QTableWidgetItem(_device_text(match.device)))
            else:
                combo = QComboBox()
                combo.addItem("– Gerät wählen –", "")
                for device in assignable:
                    combo.addItem(_device_text(device), device.id)
                index = combo.findData(self._choice.get(cert, ""))
                combo.setCurrentIndex(max(index, 0))
                combo.currentIndexChanged.connect(
                    lambda _i, c=cert, cb=combo: self._choose(c, cb.currentData()))
                self._table.setCellWidget(row, _COL_DEVICE, combo)
            status = self._status_text(match)
            item = QTableWidgetItem(status)
            if match.status == kc.DIFFERENT:
                item.setForeground(QColor("#C62828"))
            elif match.status == kc.KNOWN:
                item.setForeground(QColor("#757575"))
            self._table.setItem(row, _COL_STATUS, item)
            check = QCheckBox()
            check.setChecked(self._take.get(cert, match.status in (kc.NEW, kc.UNKNOWN)))
            check.setEnabled(match.status != kc.KNOWN)
            check.toggled.connect(lambda on, c=cert: self._take.__setitem__(c, on))
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setAlignment(Qt.AlignCenter)
            box.addWidget(check)
            self._table.setCellWidget(row, _COL_TAKE, holder)
        self._table.resizeColumnToContents(_COL_SERIAL)
        self._table.resizeColumnToContents(_COL_STATUS)

    @staticmethod
    def _status_text(match) -> str:
        if match.status == kc.DIFFERENT:
            return "anderer FDSK erfasst – Haken ersetzt ihn"
        if match.status == kc.UNKNOWN:
            return "Seriennummer unbekannt – Gerät wählen"
        return match.status

    def _choose(self, cert, device_id: str) -> None:
        self._choice[cert] = device_id

    # ── Übernehmen ──

    def _apply(self) -> None:
        devices = {d.id: d for a in self._project.topology.areas for l in a.lines
                   for d in l.devices}
        applied, missing = 0, []
        for match in self._matches:
            cert = match.certificate
            if not self._take.get(cert, match.status in (kc.NEW, kc.UNKNOWN)):
                continue
            device = match.device or devices.get(self._choice.get(cert, ""))
            if device is None:
                if match.status == kc.UNKNOWN:
                    missing.append(cert.label)
                continue
            status = kc.apply_certificate(self._config, device, cert,
                                          overwrite=match.status == kc.DIFFERENT)
            applied += status in (kc.NEW, kc.DIFFERENT)
        if missing and QMessageBox.question(
                self, "Gerät fehlt",
                "Ohne gewähltes Gerät nicht übernommen:\n" + "\n".join(missing)
                + "\n\nTrotzdem schliessen?") != QMessageBox.Yes:
            return
        self.applied = applied
        self._stop_camera()
        self.accept()

    def reject(self) -> None:
        self._stop_camera()
        super().reject()
