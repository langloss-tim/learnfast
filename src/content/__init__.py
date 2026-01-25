"""Curriculum structure and content generation."""

from .curriculum import MODULES, get_module, get_lesson
from .generator import ContentGenerator

__all__ = [
    "MODULES",
    "get_module",
    "get_lesson",
    "ContentGenerator",
]
