"""Grading system: folder watching, OCR, and feedback."""

from .grader import Grader
from .feedback import FeedbackGenerator

# ScanWatcher imported lazily to avoid pyzbar dependency at module load
def get_scan_watcher():
    from .scanner import ScanWatcher
    return ScanWatcher

__all__ = ["Grader", "FeedbackGenerator", "get_scan_watcher"]
