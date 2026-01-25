"""Curriculum structure and helpers for accessing modules and lessons."""

from typing import Optional
from ..database import get_session, Module, Lesson


def get_all_modules() -> list[dict]:
    """Get all modules with their lesson counts."""
    with get_session() as session:
        modules = session.query(Module).order_by(Module.number).all()
        return [
            {
                "id": m.id,
                "number": m.number,
                "title": m.title,
                "description": m.description,
                "real_world_applications": m.real_world_applications,
                "lesson_count": len(m.lessons)
            }
            for m in modules
        ]


def get_module(module_number: int) -> Optional[dict]:
    """Get a specific module by number."""
    with get_session() as session:
        module = session.query(Module).filter(Module.number == module_number).first()
        if not module:
            return None
        return {
            "id": module.id,
            "number": module.number,
            "title": module.title,
            "description": module.description,
            "real_world_applications": module.real_world_applications,
            "lessons": [
                {
                    "id": l.id,
                    "number": l.number,
                    "title": l.title,
                    "description": l.description,
                    "concepts": l.concepts
                }
                for l in module.lessons
            ]
        }


def get_lesson(module_number: int, lesson_number: int) -> Optional[dict]:
    """Get a specific lesson by module and lesson number."""
    with get_session() as session:
        lesson = (
            session.query(Lesson)
            .join(Module)
            .filter(Module.number == module_number, Lesson.number == lesson_number)
            .first()
        )
        if not lesson:
            return None
        return {
            "id": lesson.id,
            "module_id": lesson.module_id,
            "module_number": lesson.module.number,
            "module_title": lesson.module.title,
            "number": lesson.number,
            "title": lesson.title,
            "description": lesson.description,
            "concepts": lesson.concepts,
            "real_world_applications": lesson.module.real_world_applications
        }


def get_next_lesson(module_number: int, lesson_number: int) -> Optional[dict]:
    """Get the next lesson in sequence (within module or next module)."""
    current = get_lesson(module_number, lesson_number)
    if not current:
        return None

    # Try next lesson in same module
    next_in_module = get_lesson(module_number, lesson_number + 1)
    if next_in_module:
        return next_in_module

    # Try first lesson in next module
    return get_lesson(module_number + 1, 1)


def get_module_progress_summary(module_number: int, student_id: int) -> dict:
    """Get progress summary for a module."""
    from ..database import Progress

    module = get_module(module_number)
    if not module:
        return {}

    with get_session() as session:
        progress_records = (
            session.query(Progress)
            .join(Lesson)
            .join(Module)
            .filter(Module.number == module_number, Progress.student_id == student_id)
            .all()
        )

        lessons_mastered = sum(1 for p in progress_records if p.mastered)
        total_lessons = len(module["lessons"])

        return {
            "module_number": module_number,
            "module_title": module["title"],
            "total_lessons": total_lessons,
            "lessons_mastered": lessons_mastered,
            "percent_complete": (lessons_mastered / total_lessons * 100) if total_lessons > 0 else 0,
            "is_complete": lessons_mastered == total_lessons
        }


# Convenience constant for module count
TOTAL_MODULES = 8
MODULES = list(range(1, TOTAL_MODULES + 1))
