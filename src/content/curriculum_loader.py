"""Load curriculum structure from YAML files."""

import yaml
from pathlib import Path
from typing import Optional

from ..database import get_session, Subject, Module, Lesson


# Path to curriculum YAML files
CURRICULUM_DIR = Path(__file__).parent.parent.parent / "data" / "curriculum"


def load_curriculum_from_yaml(yaml_path: Path) -> Optional[dict]:
    """
    Load curriculum data from a YAML file.

    Expected YAML structure:
    ```yaml
    subject:
      code: PREALGEBRA
      name: Pre-Algebra
      description: Foundation for algebraic thinking
      grade_level: 6
      order: 2

    modules:
      - number: 1
        title: Integers and Operations
        description: Master adding, subtracting, multiplying, and dividing integers
        real_world_applications:
          - Temperature changes
          - Finance: debt and credit
        lessons:
          - number: 1
            title: Understanding Positive and Negative Numbers
            description: Introduction to integers
            concepts:
              - number line
              - opposites
              - absolute value
    ```
    """
    if not yaml_path.exists():
        return None

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data


def seed_subject(subject_data: dict, session=None) -> Optional[Subject]:
    """
    Seed a subject and its modules/lessons from curriculum data.

    Args:
        subject_data: Dictionary containing 'subject' and 'modules' keys
        session: Optional database session

    Returns:
        The created or updated Subject object
    """
    close_session = session is None
    if session is None:
        session = get_session().__enter__()

    try:
        subject_info = subject_data.get("subject", {})
        modules_data = subject_data.get("modules", [])

        if not subject_info.get("code"):
            return None

        # Get or create subject
        subject = (
            session.query(Subject)
            .filter(Subject.code == subject_info["code"])
            .first()
        )

        if not subject:
            subject = Subject(
                code=subject_info["code"],
                name=subject_info.get("name", subject_info["code"]),
                description=subject_info.get("description", ""),
                grade_level=subject_info.get("grade_level"),
                order=subject_info.get("order", 0),
            )
            session.add(subject)
            session.flush()  # Get the ID
        else:
            # Update existing subject
            subject.name = subject_info.get("name", subject.name)
            subject.description = subject_info.get("description", subject.description)
            subject.grade_level = subject_info.get("grade_level", subject.grade_level)
            subject.order = subject_info.get("order", subject.order)

        # Seed modules and lessons
        for module_data in modules_data:
            lessons_data = module_data.pop("lessons", [])

            # Get or create module
            module = (
                session.query(Module)
                .filter(
                    Module.subject_id == subject.id,
                    Module.number == module_data["number"]
                )
                .first()
            )

            if not module:
                module = Module(
                    subject_id=subject.id,
                    number=module_data["number"],
                    title=module_data.get("title", f"Module {module_data['number']}"),
                    description=module_data.get("description", ""),
                    real_world_applications=module_data.get("real_world_applications", []),
                )
                session.add(module)
                session.flush()
            else:
                # Update existing module
                module.title = module_data.get("title", module.title)
                module.description = module_data.get("description", module.description)
                module.real_world_applications = module_data.get(
                    "real_world_applications", module.real_world_applications
                )

            # Seed lessons
            for lesson_data in lessons_data:
                lesson = (
                    session.query(Lesson)
                    .filter(
                        Lesson.module_id == module.id,
                        Lesson.number == lesson_data["number"]
                    )
                    .first()
                )

                if not lesson:
                    lesson = Lesson(
                        module_id=module.id,
                        number=lesson_data["number"],
                        title=lesson_data.get("title", f"Lesson {lesson_data['number']}"),
                        description=lesson_data.get("description", ""),
                        concepts=lesson_data.get("concepts", []),
                        prerequisites=lesson_data.get("prerequisites", []),
                    )
                    session.add(lesson)
                else:
                    # Update existing lesson
                    lesson.title = lesson_data.get("title", lesson.title)
                    lesson.description = lesson_data.get("description", lesson.description)
                    lesson.concepts = lesson_data.get("concepts", lesson.concepts)
                    lesson.prerequisites = lesson_data.get("prerequisites", lesson.prerequisites)

        if close_session:
            session.commit()

        return subject

    finally:
        if close_session:
            session.__exit__(None, None, None)


def get_available_subjects() -> list[dict]:
    """
    Get list of available subjects from database.

    Returns:
        List of subject dictionaries with id, code, name, description, grade_level, order
    """
    with get_session() as session:
        subjects = session.query(Subject).order_by(Subject.order, Subject.grade_level).all()
        return [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "description": s.description,
                "grade_level": s.grade_level,
                "order": s.order,
                "module_count": len(s.modules),
            }
            for s in subjects
        ]


def get_available_curriculum_files() -> list[Path]:
    """Get list of YAML files in the curriculum directory."""
    if not CURRICULUM_DIR.exists():
        CURRICULUM_DIR.mkdir(parents=True, exist_ok=True)
        return []

    return list(CURRICULUM_DIR.glob("*.yaml")) + list(CURRICULUM_DIR.glob("*.yml"))


def load_all_curricula():
    """Load all curriculum YAML files and seed the database."""
    yaml_files = get_available_curriculum_files()

    if not yaml_files:
        return []

    loaded_subjects = []
    with get_session() as session:
        for yaml_path in yaml_files:
            data = load_curriculum_from_yaml(yaml_path)
            if data:
                subject = seed_subject(data, session)
                if subject:
                    loaded_subjects.append({
                        "code": subject.code,
                        "name": subject.name,
                        "file": yaml_path.name,
                    })

    return loaded_subjects


def enroll_student_in_subject(student_id: int, subject_id: int, session=None) -> dict:
    """
    Enroll a student in a subject, creating StudentSubjectProgress.

    Returns:
        Dictionary with enrollment status
    """
    from ..database import StudentSubjectProgress, Student

    close_session = session is None
    if session is None:
        session = get_session().__enter__()

    try:
        # Check if already enrolled
        existing = (
            session.query(StudentSubjectProgress)
            .filter(
                StudentSubjectProgress.student_id == student_id,
                StudentSubjectProgress.subject_id == subject_id
            )
            .first()
        )

        if existing:
            return {
                "status": "already_enrolled",
                "progress_id": existing.id,
                "message": "Student is already enrolled in this subject"
            }

        # Get subject and first module/lesson
        subject = session.query(Subject).get(subject_id)
        if not subject:
            return {"status": "error", "message": "Subject not found"}

        first_module = (
            session.query(Module)
            .filter(Module.subject_id == subject_id)
            .order_by(Module.number)
            .first()
        )

        first_lesson = first_module.lessons[0] if first_module and first_module.lessons else None

        # Create progress record
        progress = StudentSubjectProgress(
            student_id=student_id,
            subject_id=subject_id,
            current_module_id=first_module.id if first_module else None,
            current_lesson_id=first_lesson.id if first_lesson else None,
            status="active",
        )
        session.add(progress)

        if close_session:
            session.commit()

        return {
            "status": "enrolled",
            "progress_id": progress.id,
            "subject_name": subject.name,
            "starting_module": first_module.number if first_module else None,
            "starting_lesson": first_lesson.number if first_lesson else None,
        }

    finally:
        if close_session:
            session.__exit__(None, None, None)


def get_student_enrollments(student_id: int) -> list[dict]:
    """Get all subject enrollments for a student."""
    from ..database import StudentSubjectProgress

    with get_session() as session:
        enrollments = (
            session.query(StudentSubjectProgress)
            .filter(StudentSubjectProgress.student_id == student_id)
            .all()
        )

        return [
            {
                "id": e.id,
                "subject_id": e.subject_id,
                "subject_code": e.subject.code,
                "subject_name": e.subject.name,
                "status": e.status,
                "velocity_score": e.velocity_score,
                "consecutive_perfect": e.consecutive_perfect,
                "consecutive_struggles": e.consecutive_struggles,
                "enrolled_at": e.enrolled_at,
                "completed_at": e.completed_at,
            }
            for e in enrollments
        ]
