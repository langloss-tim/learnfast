"""Folder watcher for scanned student work."""

import time
import base64
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

PYZBAR_AVAILABLE = False
decode = None
Image = None

try:
    from pyzbar.pyzbar import decode as _decode
    from PIL import Image as _Image
    decode = _decode
    Image = _Image
    PYZBAR_AVAILABLE = True
except (ImportError, OSError, Exception):
    # pyzbar requires libzbar0 system library
    pass

from ..config import SCANS_FOLDER
from ..database import get_session, Material, Submission, Student, SubmissionStatus


class ScanHandler(FileSystemEventHandler):
    """Handle new scan files in the watched folder."""

    SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf', '.tiff', '.tif'}

    def __init__(self, on_scan_detected: Callable[[str, str], None]):
        """
        Initialize the handler.

        Args:
            on_scan_detected: Callback function(scan_path, qr_code) called when scan is detected
        """
        self.on_scan_detected = on_scan_detected

    def on_created(self, event: FileCreatedEvent):
        """Handle file creation event."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's a supported file type
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            return

        # Wait a moment for file to be fully written
        time.sleep(1)

        # Try to extract QR code
        qr_code = self._extract_qr_code(file_path)

        if qr_code:
            print(f"Scan detected: {file_path.name} -> QR: {qr_code}")
            self.on_scan_detected(str(file_path), qr_code)
        else:
            print(f"Scan detected but no QR code found: {file_path.name}")
            # Still process it, but will need manual association
            self.on_scan_detected(str(file_path), None)

    def _extract_qr_code(self, file_path: Path) -> Optional[str]:
        """Extract QR code from an image file."""
        if not PYZBAR_AVAILABLE:
            return None

        try:
            image = Image.open(file_path)
            decoded_objects = decode(image)

            for obj in decoded_objects:
                data = obj.data.decode('utf-8')
                # Our QR codes start with "PA-"
                if data.startswith("PA-"):
                    return data

            return None
        except Exception as e:
            print(f"Error extracting QR code: {e}")
            return None


class ScanWatcher:
    """Watch a folder for new scans and process them."""

    def __init__(self, on_practice_scan: Callable = None, on_assessment_scan: Callable = None):
        """
        Initialize the watcher.

        Args:
            on_practice_scan: Callback for practice/remediation scans (auto-grade)
            on_assessment_scan: Callback for quiz/test scans (queue for manual)
        """
        self.on_practice_scan = on_practice_scan
        self.on_assessment_scan = on_assessment_scan
        self.observer = None

    def _handle_scan(self, scan_path: str, qr_code: Optional[str]):
        """Handle a detected scan."""
        with get_session() as session:
            # Get or create default student
            student = session.query(Student).first()
            if not student:
                student = Student(name="Student")
                session.add(student)
                session.flush()

            # Find the material by QR code
            material = None
            if qr_code:
                material = session.query(Material).filter(Material.qr_code == qr_code).first()

            if not material:
                print(f"Warning: Could not find material for scan {scan_path}")
                # Create a pending submission anyway
                submission = Submission(
                    student_id=student.id,
                    material_id=None,
                    scan_path=scan_path,
                    status=SubmissionStatus.PENDING
                )
                session.add(submission)
                session.commit()
                return

            # Create submission record
            submission = Submission(
                student_id=student.id,
                material_id=material.id,
                scan_path=scan_path,
                status=SubmissionStatus.PENDING
            )
            session.add(submission)
            session.commit()

            # Determine how to handle based on material type
            from ..database import MaterialType

            if material.material_type in [MaterialType.PRACTICE, MaterialType.REMEDIATION, MaterialType.DIAGNOSTIC]:
                # Auto-grade practice work and diagnostics
                if self.on_practice_scan:
                    self.on_practice_scan(submission.id)
            else:
                # Queue quiz/test for manual grading
                if self.on_assessment_scan:
                    self.on_assessment_scan(submission.id)
                print(f"Assessment scan queued for manual grading: {material.material_type.value}")

    def start(self, folder: Path = None):
        """Start watching the folder."""
        folder = folder or SCANS_FOLDER
        folder.mkdir(parents=True, exist_ok=True)

        handler = ScanHandler(self._handle_scan)
        self.observer = Observer()
        self.observer.schedule(handler, str(folder), recursive=False)
        self.observer.start()

        print(f"Watching for scans in: {folder}")

    def stop(self):
        """Stop watching."""
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def run_forever(self):
        """Run the watcher until interrupted."""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


def get_pending_submissions(material_type: str = None, student_id: int = None) -> list[dict]:
    """Get all pending submissions, optionally filtered by type and/or student."""
    from ..database import MaterialType

    with get_session() as session:
        query = (
            session.query(Submission)
            .filter(Submission.status == SubmissionStatus.PENDING)
            .join(Material, isouter=True)
        )

        if student_id:
            query = query.filter(Submission.student_id == student_id)

        if material_type:
            if material_type == "practice":
                query = query.filter(Material.material_type.in_([MaterialType.PRACTICE, MaterialType.REMEDIATION]))
            elif material_type == "quiz":
                query = query.filter(Material.material_type == MaterialType.QUIZ)
            elif material_type == "test":
                query = query.filter(Material.material_type == MaterialType.TEST)
            elif material_type == "diagnostic":
                query = query.filter(Material.material_type == MaterialType.DIAGNOSTIC)

        submissions = query.all()

        return [
            {
                "id": s.id,
                "scan_path": s.scan_path,
                "scanned_at": s.scanned_at.isoformat() if s.scanned_at else None,
                "material_id": s.material_id,
                "material_type": s.material.material_type.value if s.material else "unknown",
                "qr_code": s.material.qr_code if s.material else None
            }
            for s in submissions
        ]


def _compress_image_to_limit(img, max_bytes=4_500_000, max_dimension=7500):
    """Compress a PIL Image to fit within size and dimension limits, returns JPEG bytes."""
    import io
    from PIL import Image

    # Convert to RGB if needed
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # First, resize if any dimension exceeds max
    width, height = img.size
    if width > max_dimension or height > max_dimension:
        scale = min(max_dimension / width, max_dimension / height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        img = img.resize((new_width, new_height), Image.LANCZOS)

    # Try different quality levels
    for quality in [85, 70, 55, 40, 25]:
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()

    # If still too large, resize further
    while True:
        width, height = img.size
        img = img.resize((int(width * 0.8), int(height * 0.8)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=40, optimize=True)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()


def get_image_as_base64(file_path: str) -> str:
    """Read an image file and return as base64 string. Converts PDFs to JPEG."""
    from PIL import Image
    import io
    ext = Path(file_path).suffix.lower()

    if ext == '.pdf':
        # Convert PDF to image using PyMuPDF
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)

        # Get the first page (or all pages combined)
        if len(doc) == 1:
            page = doc[0]
            # Render at 1.5x resolution (good balance of quality/size)
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
            jpeg_data = _compress_image_to_limit(img)
            return base64.standard_b64encode(jpeg_data).decode("utf-8")
        else:
            # Multiple pages - combine vertically
            images = []
            for page in doc:
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)

            doc.close()

            # Combine images vertically
            total_height = sum(img.height for img in images)
            max_width = max(img.width for img in images)
            combined = Image.new('RGB', (max_width, total_height), 'white')

            y_offset = 0
            for img in images:
                combined.paste(img, (0, y_offset))
                y_offset += img.height

            jpeg_data = _compress_image_to_limit(combined)
            return base64.standard_b64encode(jpeg_data).decode("utf-8")
    else:
        # Regular image file - check size and compress if needed
        with open(file_path, "rb") as f:
            data = f.read()

        if len(data) > 4_500_000:
            img = Image.open(io.BytesIO(data))
            jpeg_data = _compress_image_to_limit(img)
            return base64.standard_b64encode(jpeg_data).decode("utf-8")

        return base64.standard_b64encode(data).decode("utf-8")


def get_image_media_type(file_path: str) -> str:
    """Get the media type for an image file. PDFs and large images become JPEG."""
    ext = Path(file_path).suffix.lower()

    if ext == '.pdf':
        return 'image/jpeg'  # PDFs are converted to JPEG

    # Check if file is large and would be compressed to JPEG
    try:
        size = Path(file_path).stat().st_size
        if size > 4_500_000:
            return 'image/jpeg'
    except:
        pass

    media_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    return media_types.get(ext, 'image/jpeg')
