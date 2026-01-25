"""QR code scanning for automatic assignment identification."""

from pathlib import Path
from typing import Optional
import io

# Try to import pyzbar, but don't fail if zbar library isn't installed
PYZBAR_AVAILABLE = False
pyzbar = None

try:
    from pyzbar import pyzbar as _pyzbar
    pyzbar = _pyzbar
    PYZBAR_AVAILABLE = True
except (ImportError, OSError, Exception):
    # pyzbar requires libzbar0 system library
    # If not installed, QR scanning will be disabled
    pass

# PIL is always needed for image handling
try:
    from PIL import Image
except ImportError:
    Image = None


def is_qr_scanning_available() -> bool:
    """Check if QR scanning is available."""
    return PYZBAR_AVAILABLE


def scan_qr_from_image(image_path: Path) -> Optional[str]:
    """
    Scan a QR code from an image file.

    Args:
        image_path: Path to the image file

    Returns:
        The decoded QR code data, or None if no QR code found
    """
    if not PYZBAR_AVAILABLE:
        return None

    try:
        img = Image.open(image_path)
        decoded = pyzbar.decode(img)

        for obj in decoded:
            if obj.type == 'QRCODE':
                return obj.data.decode('utf-8')

        return None
    except Exception as e:
        print(f"Error scanning QR from image: {e}")
        return None


def scan_qr_from_pdf(pdf_path: Path) -> Optional[str]:
    """
    Scan a QR code from a PDF file (checks first few pages).

    Args:
        pdf_path: Path to the PDF file

    Returns:
        The decoded QR code data, or None if no QR code found
    """
    if not PYZBAR_AVAILABLE:
        return None

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)

        # Check first 3 pages (QR is usually on first page)
        for page_num in range(min(3, len(doc))):
            page = doc[page_num]

            # Render at higher DPI for better QR detection
            mat = fitz.Matrix(200/72, 200/72)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # Try to decode QR
            decoded = pyzbar.decode(img)

            for obj in decoded:
                if obj.type == 'QRCODE':
                    doc.close()
                    return obj.data.decode('utf-8')

        doc.close()
        return None

    except Exception as e:
        print(f"Error scanning QR from PDF: {e}")
        return None


def scan_qr_from_file(file_path: Path) -> Optional[str]:
    """
    Scan a QR code from any supported file type.

    Args:
        file_path: Path to the file (image or PDF)

    Returns:
        The decoded QR code data, or None if no QR code found
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == '.pdf':
        return scan_qr_from_pdf(file_path)
    elif suffix in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']:
        return scan_qr_from_image(file_path)
    else:
        # Try as image first
        result = scan_qr_from_image(file_path)
        if result:
            return result
        # Then try as PDF
        return scan_qr_from_pdf(file_path)


def identify_material_from_qr(qr_code: str) -> Optional[int]:
    """
    Look up the material ID from a QR code.

    Args:
        qr_code: The QR code string

    Returns:
        The material ID, or None if not found
    """
    from ..database import get_session, Material

    with get_session() as session:
        material = session.query(Material).filter(
            Material.qr_code == qr_code
        ).first()

        if material:
            return material.id

        return None


def auto_identify_upload(file_path: Path) -> dict:
    """
    Automatically identify an uploaded file by scanning for QR code.

    Args:
        file_path: Path to the uploaded file

    Returns:
        dict with:
            - success: bool
            - material_id: int or None
            - qr_code: str or None
            - message: str
    """
    # Check if QR scanning is available
    if not PYZBAR_AVAILABLE:
        return {
            "success": False,
            "material_id": None,
            "qr_code": None,
            "message": "QR scanning not available. Install libzbar0: sudo apt-get install libzbar0"
        }

    # Scan for QR code
    qr_code = scan_qr_from_file(file_path)

    if not qr_code:
        return {
            "success": False,
            "material_id": None,
            "qr_code": None,
            "message": "No QR code found in the uploaded file. Please ensure the QR code is visible."
        }

    # Look up material
    material_id = identify_material_from_qr(qr_code)

    if not material_id:
        return {
            "success": False,
            "material_id": None,
            "qr_code": qr_code,
            "message": f"QR code '{qr_code}' not found in database. This may be an old or invalid assignment."
        }

    # Get material details
    from ..database import get_session, Material

    with get_session() as session:
        material = session.query(Material).get(material_id)
        if material:
            lesson_title = material.lesson.title if material.lesson else "Unknown"
            material_type = material.material_type.value.title()

            return {
                "success": True,
                "material_id": material_id,
                "qr_code": qr_code,
                "material_type": material_type,
                "lesson_title": lesson_title,
                "message": f"Identified: {material_type} - {lesson_title}"
            }

    return {
        "success": False,
        "material_id": None,
        "qr_code": qr_code,
        "message": "Error looking up material details."
    }
