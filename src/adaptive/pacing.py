"""Adaptive pacing and mastery tracking."""

from typing import Optional
from datetime import datetime

from ..config import (
    MASTERY_THRESHOLD,
    DIAGNOSTIC_MASTERY_THRESHOLD,
    SPEEDUP_STREAK,
    SLOWDOWN_STREAK,
    STRUGGLE_THRESHOLD,
    SKIP_OFFER_STREAK,
    MIN_PROBLEMS,
    MAX_PROBLEMS,
    BASE_PROBLEMS,
)
from ..database import (
    get_session,
    Student,
    Subject,
    StudentSubjectProgress,
    Progress,
    Submission,
    Material,
    Lesson,
    Module,
    MaterialType,
    SubmissionStatus,
)
from ..content.generator import ContentGenerator
from ..content.curriculum import get_next_lesson, get_lesson


class AdaptivePacer:
    """Manage adaptive pacing based on student performance."""

    def __init__(self):
        self.content_generator = ContentGenerator()

    def get_or_create_subject_progress(self, student_id: int, subject_id: int, session=None) -> StudentSubjectProgress:
        """Get or create a StudentSubjectProgress record."""
        close_session = session is None
        if session is None:
            session = get_session().__enter__()

        try:
            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                # Get first module/lesson of subject
                first_module = (
                    session.query(Module)
                    .filter(Module.subject_id == subject_id)
                    .order_by(Module.number)
                    .first()
                )
                first_lesson = first_module.lessons[0] if first_module and first_module.lessons else None

                progress = StudentSubjectProgress(
                    student_id=student_id,
                    subject_id=subject_id,
                    current_module_id=first_module.id if first_module else None,
                    current_lesson_id=first_lesson.id if first_lesson else None,
                )
                session.add(progress)
                if close_session:
                    session.commit()

            return progress
        finally:
            if close_session:
                session.__exit__(None, None, None)

    def calculate_problem_count(self, student_id: int, subject_id: int = None) -> int:
        """
        Calculate number of problems based on student's learning velocity.

        Returns fewer problems when excelling, more when struggling.
        - Base: 25 problems
        - Speed-up (3+ perfect): 15 problems
        - Slow-down (2+ struggles): 35 problems
        """
        with get_session() as session:
            # If no subject specified, try to get from student's current subject
            if subject_id is None:
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student_id,
                        StudentSubjectProgress.status == "active"
                    )
                    .first()
                )
                if subject_progress:
                    subject_id = subject_progress.subject_id
                else:
                    return BASE_PROBLEMS

            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                return BASE_PROBLEMS

            # Speeding up: fewer problems
            if progress.consecutive_perfect >= SPEEDUP_STREAK:
                return MIN_PROBLEMS

            # Slowing down: more problems with support
            if progress.consecutive_struggles >= SLOWDOWN_STREAK:
                return MAX_PROBLEMS

            return BASE_PROBLEMS

    def update_velocity(self, student_id: int, subject_id: int, score: float, session=None):
        """
        Update learning velocity after each graded submission.

        - Perfect score (100%): increment consecutive_perfect, reset struggles
        - Below struggle threshold (<70%): increment consecutive_struggles, reset perfect
        - Adjust velocity_score accordingly
        """
        close_session = session is None
        if session is None:
            session = get_session().__enter__()

        try:
            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                progress = self.get_or_create_subject_progress(student_id, subject_id, session)

            if score >= MASTERY_THRESHOLD:  # Perfect score (100%)
                progress.consecutive_perfect += 1
                progress.consecutive_struggles = 0
                # Increase velocity (max 2.0)
                progress.velocity_score = min(2.0, progress.velocity_score + 0.1)
            elif score < STRUGGLE_THRESHOLD:  # Struggling (<70%)
                progress.consecutive_struggles += 1
                progress.consecutive_perfect = 0
                # Decrease velocity (min 0.5)
                progress.velocity_score = max(0.5, progress.velocity_score - 0.1)
            else:  # Middle ground (70-99%)
                # Partial reset of streaks
                progress.consecutive_perfect = 0
                progress.consecutive_struggles = 0
                # Velocity stays relatively stable
                progress.velocity_score = max(0.5, min(2.0, progress.velocity_score))

            if close_session:
                session.commit()

        finally:
            if close_session:
                session.__exit__(None, None, None)

    def get_difficulty_adjustment(self, student_id: int, subject_id: int = None) -> str:
        """
        Return difficulty adjustment for content generation.

        Returns 'standard', 'easier', or 'harder' based on learning velocity.
        """
        with get_session() as session:
            if subject_id is None:
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student_id,
                        StudentSubjectProgress.status == "active"
                    )
                    .first()
                )
                if subject_progress:
                    subject_id = subject_progress.subject_id
                else:
                    return "standard"

            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                return "standard"

            # Struggling: provide easier problems with more scaffolding
            if progress.consecutive_struggles >= SLOWDOWN_STREAK:
                return "easier"

            # Excelling: provide more challenging problems
            if progress.consecutive_perfect >= SPEEDUP_STREAK:
                return "harder"

            return "standard"

    def should_offer_lesson_skip(self, student_id: int, lesson_id: int = None, subject_id: int = None) -> bool:
        """
        Check if we should offer a mastery assessment to skip the lesson.

        Offered when student has 5+ consecutive perfect scores.
        """
        with get_session() as session:
            if subject_id is None:
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student_id,
                        StudentSubjectProgress.status == "active"
                    )
                    .first()
                )
                if subject_progress:
                    subject_id = subject_progress.subject_id
                else:
                    return False

            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                return False

            return progress.consecutive_perfect >= SKIP_OFFER_STREAK

    def get_velocity_indicator(self, student_id: int, subject_id: int = None) -> dict:
        """
        Get velocity indicator for UI display.

        Returns dict with icon, label, and description.
        """
        with get_session() as session:
            if subject_id is None:
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student_id,
                        StudentSubjectProgress.status == "active"
                    )
                    .first()
                )
                if subject_progress:
                    subject_id = subject_progress.subject_id
                else:
                    return {"icon": "🚶", "label": "normal", "description": "Standard pace"}

            progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not progress:
                return {"icon": "🚶", "label": "normal", "description": "Standard pace"}

            if progress.consecutive_struggles >= SLOWDOWN_STREAK:
                return {
                    "icon": "🐢",
                    "label": "slow",
                    "description": f"Extra support mode ({progress.consecutive_struggles} struggles)"
                }

            if progress.consecutive_perfect >= SPEEDUP_STREAK:
                return {
                    "icon": "🏃",
                    "label": "fast",
                    "description": f"Accelerated pace ({progress.consecutive_perfect} perfect in a row!)"
                }

            return {
                "icon": "🚶",
                "label": "normal",
                "description": f"Standard pace (velocity: {progress.velocity_score:.1f})"
            }

    def get_student_status(self, student_id: int = None, subject_id: int = None) -> dict:
        """Get the current status and recommended next action for a student."""
        with get_session() as session:
            # Get student (or first/only student)
            if student_id:
                student = session.query(Student).get(student_id)
            else:
                student = session.query(Student).first()

            if not student:
                return {
                    "status": "new",
                    "message": "No student found. Run initialization first.",
                    "next_action": "initialize"
                }

            # Determine subject context
            subject = None
            subject_progress = None
            if subject_id:
                subject = session.query(Subject).get(subject_id)
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student.id,
                        StudentSubjectProgress.subject_id == subject_id
                    )
                    .first()
                )
            else:
                # Get active subject progress, default to first enrolled
                subject_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(
                        StudentSubjectProgress.student_id == student.id,
                        StudentSubjectProgress.status == "active"
                    )
                    .first()
                )
                if subject_progress:
                    subject = session.query(Subject).get(subject_progress.subject_id)

            # Get lessons (filter by subject if available)
            if subject:
                lessons = (
                    session.query(Lesson)
                    .join(Module)
                    .filter(Module.subject_id == subject.id)
                    .order_by(Module.number, Lesson.number)
                    .all()
                )
            else:
                lessons = session.query(Lesson).order_by(Lesson.module_id, Lesson.number).all()

            # Get progress records for the relevant lessons only
            lesson_ids = [l.id for l in lessons]
            progress_records = (
                session.query(Progress)
                .filter(
                    Progress.student_id == student.id,
                    Progress.lesson_id.in_(lesson_ids) if lesson_ids else True
                )
                .all()
            )
            progress_by_lesson = {p.lesson_id: p for p in progress_records}

            # Find current position
            current_lesson_obj = None

            for lesson in lessons:
                progress = progress_by_lesson.get(lesson.id)

                if not progress or not progress.mastered:
                    # This is where we are
                    current_lesson_obj = lesson
                    break
            else:
                # All lessons mastered!
                subject_name = subject.name if subject else "Pre-Algebra"
                return {
                    "status": "complete",
                    "message": f"Congratulations! All {subject_name} modules have been mastered!",
                    "next_action": None,
                    "modules_complete": len(set(l.module_id for l in lessons)),
                    "total_lessons_mastered": len([p for p in progress_records if p.mastered])
                }

            # Build current lesson details from the lesson object
            current = {
                "id": current_lesson_obj.id,
                "module_id": current_lesson_obj.module_id,
                "module_number": current_lesson_obj.module.number,
                "module_title": current_lesson_obj.module.title,
                "number": current_lesson_obj.number,
                "title": current_lesson_obj.title,
                "description": current_lesson_obj.description,
                "concepts": current_lesson_obj.concepts,
            }
            current_module = current_lesson_obj.module.number
            current_lesson = current_lesson_obj.number

            # Check for pending submissions
            pending = (
                session.query(Submission)
                .filter(
                    Submission.student_id == student.id,
                    Submission.status == SubmissionStatus.PENDING
                )
                .count()
            )

            # Check for needs_retry submissions
            needs_retry = (
                session.query(Submission)
                .join(Material)
                .join(Lesson)
                .filter(
                    Submission.student_id == student.id,
                    Submission.status == SubmissionStatus.NEEDS_RETRY,
                    Lesson.module_id == current["module_id"]
                )
                .first()
            )

            # Determine next action
            if pending > 0:
                next_action = "grade_pending"
                message = f"You have {pending} submission(s) waiting to be graded."
            elif needs_retry:
                next_action = "remediation"
                message = f"Remediation needed for {current['title']}. Some concepts need more practice."
            else:
                # Check what materials exist for current lesson
                materials = (
                    session.query(Material)
                    .filter(Material.lesson_id == current["id"])
                    .all()
                )
                material_types = {m.material_type for m in materials}

                if MaterialType.LESSON not in material_types:
                    next_action = "generate_lesson"
                    message = f"Ready to learn: {current['title']}"
                elif MaterialType.PRACTICE not in material_types:
                    next_action = "generate_practice"
                    message = f"Ready to practice: {current['title']}"
                else:
                    # Check if practice has been completed
                    progress = progress_by_lesson.get(current["id"])
                    if not progress or progress.practice_attempts == 0:
                        next_action = "do_practice"
                        message = f"Complete practice problems for: {current['title']}"
                    elif progress.mastered:
                        next_action = "next_lesson"
                        message = f"Mastered {current['title']}! Ready for the next lesson."
                    else:
                        next_action = "remediation"
                        message = f"More practice needed for: {current['title']}"

            # Get velocity info if subject progress exists
            velocity_info = None
            if subject_progress:
                velocity_info = {
                    "velocity_score": subject_progress.velocity_score,
                    "consecutive_perfect": subject_progress.consecutive_perfect,
                    "consecutive_struggles": subject_progress.consecutive_struggles,
                }

            return {
                "status": "in_progress",
                "student_name": student.name,
                "subject_id": subject.id if subject else None,
                "subject_code": subject.code if subject else None,
                "subject_name": subject.name if subject else "Pre-Algebra",
                "current_module": current_module,
                "current_lesson": current_lesson,
                "current_title": current["title"],
                "message": message,
                "next_action": next_action,
                "modules_complete": current_module - 1,
                "lessons_mastered": len([p for p in progress_records if p.mastered]),
                "pending_submissions": pending,
                "velocity": velocity_info,
            }

    def get_weak_concepts(self, student_id: int, lesson_id: int = None) -> list[str]:
        """Get weak concepts for a student based on error patterns."""
        with get_session() as session:
            query = session.query(Progress).filter(Progress.student_id == student_id)

            if lesson_id:
                query = query.filter(Progress.lesson_id == lesson_id)

            progress_records = query.all()

            # Aggregate error patterns
            all_patterns = {}
            for progress in progress_records:
                patterns = progress.error_patterns_json or {}
                for pattern, count in patterns.items():
                    all_patterns[pattern] = all_patterns.get(pattern, 0) + count

            # Sort by frequency
            sorted_patterns = sorted(all_patterns.items(), key=lambda x: x[1], reverse=True)

            # Return top patterns
            return [pattern for pattern, count in sorted_patterns[:5]]

    def generate_remediation(self, student_id: int, module_number: int, lesson_number: int) -> Optional[dict]:
        """Generate remediation problems targeting weak areas."""
        weak_concepts = self.get_weak_concepts(student_id)

        if not weak_concepts:
            # No specific weak areas, generate general review
            weak_concepts = ["general review"]

        return self.content_generator.generate_remediation(
            module_number,
            lesson_number,
            weak_concepts
        )

    def should_speed_up(self, student_id: int) -> bool:
        """Check if student should move faster based on performance."""
        with get_session() as session:
            # Get recent submissions
            recent = (
                session.query(Submission)
                .filter(Submission.student_id == student_id)
                .order_by(Submission.graded_at.desc())
                .limit(5)
                .all()
            )

            if len(recent) < 3:
                return False

            # Check if all recent are 100%
            all_perfect = all(s.score >= 100 for s in recent if s.score is not None)

            return all_perfect

    def get_progress_summary(self, student_id: int = None, subject_id: int = None) -> dict:
        """Get a comprehensive progress summary."""
        with get_session() as session:
            if student_id:
                student = session.query(Student).get(student_id)
            else:
                student = session.query(Student).first()

            if not student:
                return {"error": "No student found"}

            # Get subject context
            subject = None
            if subject_id:
                subject = session.query(Subject).get(subject_id)

            # Get all modules (filter by subject if available)
            if subject:
                modules = (
                    session.query(Module)
                    .filter(Module.subject_id == subject.id)
                    .order_by(Module.number)
                    .all()
                )
            else:
                modules = session.query(Module).order_by(Module.number).all()

            # Get progress for each module
            module_progress = []
            for module in modules:
                lessons = module.lessons
                lesson_ids = [l.id for l in lessons]

                progress_records = (
                    session.query(Progress)
                    .filter(
                        Progress.student_id == student.id,
                        Progress.lesson_id.in_(lesson_ids)
                    )
                    .all()
                )

                mastered = sum(1 for p in progress_records if p.mastered)
                total = len(lessons)

                module_progress.append({
                    "module_number": module.number,
                    "title": module.title,
                    "total_lessons": total,
                    "lessons_mastered": mastered,
                    "percent_complete": (mastered / total * 100) if total > 0 else 0,
                    "is_complete": mastered == total
                })

            # Overall stats
            total_lessons = sum(m["total_lessons"] for m in module_progress)
            total_mastered = sum(m["lessons_mastered"] for m in module_progress)

            # Submission stats
            all_submissions = (
                session.query(Submission)
                .filter(Submission.student_id == student.id)
                .all()
            )

            total_submissions = len(all_submissions)
            graded_submissions = [s for s in all_submissions if s.score is not None]
            average_score = (
                sum(s.score for s in graded_submissions) / len(graded_submissions)
                if graded_submissions else 0
            )
            perfect_scores = sum(1 for s in graded_submissions if s.score >= 100)

            return {
                "student_name": student.name,
                "subject_id": subject.id if subject else None,
                "subject_name": subject.name if subject else "Pre-Algebra",
                "modules": module_progress,
                "overall": {
                    "total_lessons": total_lessons,
                    "lessons_mastered": total_mastered,
                    "percent_complete": (total_mastered / total_lessons * 100) if total_lessons > 0 else 0,
                    "total_submissions": total_submissions,
                    "average_score": average_score,
                    "perfect_scores": perfect_scores,
                    "mastery_rate": (perfect_scores / len(graded_submissions) * 100) if graded_submissions else 0
                }
            }

    def recommend_next_steps(self, student_id: int = None) -> list[dict]:
        """Get a list of recommended next steps."""
        status = self.get_student_status(student_id)
        recommendations = []

        if status["status"] == "complete":
            recommendations.append({
                "priority": 1,
                "action": "celebrate",
                "description": "You've completed all pre-algebra modules! Consider reviewing any topics or moving to Algebra I."
            })
            return recommendations

        action = status.get("next_action")

        if action == "grade_pending":
            recommendations.append({
                "priority": 1,
                "action": "grade",
                "description": f"Grade {status.get('pending_submissions', 0)} pending submission(s)"
            })

        if action == "remediation":
            recommendations.append({
                "priority": 1,
                "action": "remediation",
                "description": f"Generate remediation practice for: {status.get('current_title')}"
            })

        if action in ["generate_lesson", "generate_practice"]:
            recommendations.append({
                "priority": 1,
                "action": action,
                "description": f"Generate {action.split('_')[1]} for: {status.get('current_title')}"
            })

        if action == "do_practice":
            recommendations.append({
                "priority": 1,
                "action": "print_and_complete",
                "description": f"Print and complete practice for: {status.get('current_title')}"
            })

        if action == "next_lesson":
            next_lesson = get_next_lesson(status["current_module"], status["current_lesson"])
            if next_lesson:
                recommendations.append({
                    "priority": 1,
                    "action": "advance",
                    "description": f"Ready for next lesson: {next_lesson['title']}"
                })

        return recommendations

    def apply_diagnostic_mastery(self, student_id: int, module_scores: dict, session=None):
        """
        Apply diagnostic results to mark mastered modules.

        Args:
            student_id: The student's ID
            module_scores: Dict mapping module_number to percentage score
            session: Optional existing database session
        """
        from datetime import datetime

        close_session = session is None
        if session is None:
            session = get_session().__enter__()

        try:
            # Get all modules
            modules = session.query(Module).order_by(Module.number).all()

            mastered_modules = []

            for module in modules:
                score = module_scores.get(module.number, 0)

                if score >= DIAGNOSTIC_MASTERY_THRESHOLD:
                    mastered_modules.append(module.number)

                    # Mark all lessons in this module as mastered
                    for lesson in module.lessons:
                        progress = (
                            session.query(Progress)
                            .filter(
                                Progress.student_id == student_id,
                                Progress.lesson_id == lesson.id
                            )
                            .first()
                        )

                        if not progress:
                            progress = Progress(
                                student_id=student_id,
                                lesson_id=lesson.id
                            )
                            session.add(progress)

                        progress.mastered = True
                        progress.mastered_at = datetime.utcnow()
                        progress.best_practice_score = 100.0

            # Update student's current position to first unmastered lesson
            student = session.query(Student).get(student_id)
            if student:
                # Find first unmastered lesson
                for module in modules:
                    if module.number not in mastered_modules:
                        if module.lessons:
                            student.current_module_id = module.id
                            student.current_lesson_id = module.lessons[0].id
                            break
                else:
                    # All modules mastered
                    if modules and modules[-1].lessons:
                        student.current_module_id = modules[-1].id
                        student.current_lesson_id = modules[-1].lessons[-1].id

            if close_session:
                session.commit()

            return {
                "mastered_modules": mastered_modules,
                "module_scores": module_scores
            }

        finally:
            if close_session:
                session.__exit__(None, None, None)

    def has_taken_diagnostic(self, student_id: int = None, subject_id: int = None) -> bool:
        """Check if the student has already taken a diagnostic assessment for a subject."""
        with get_session() as session:
            from ..database.models import MaterialType

            if student_id is None:
                student = session.query(Student).first()
                if not student:
                    return False
                student_id = student.id

            # Check for graded diagnostic submissions
            diagnostics = (
                session.query(Submission)
                .join(Material)
                .filter(
                    Submission.student_id == student_id,
                    Material.material_type == MaterialType.DIAGNOSTIC,
                    Submission.score.isnot(None)
                )
                .all()
            )

            # If no subject specified, return True if any diagnostic exists
            if subject_id is None:
                return len(diagnostics) > 0

            # Check if any diagnostic matches the subject
            for submission in diagnostics:
                content = submission.material.content_json or {}
                diag_subject_id = content.get("subject_id")
                if diag_subject_id == subject_id:
                    return True

            return False

    def get_diagnostic_results(self, student_id: int = None, subject_id: int = None) -> Optional[dict]:
        """Get the results of a completed diagnostic assessment for a subject."""
        with get_session() as session:
            from ..database.models import MaterialType

            if student_id is None:
                student = session.query(Student).first()
                if not student:
                    return None
                student_id = student.id

            # Get all diagnostic submissions for this student
            diagnostics = (
                session.query(Submission)
                .join(Material)
                .filter(
                    Submission.student_id == student_id,
                    Material.material_type == MaterialType.DIAGNOSTIC,
                    Submission.score.isnot(None)
                )
                .order_by(Submission.graded_at.desc())
                .all()
            )

            # Find the diagnostic for the specified subject
            submission = None
            for diag in diagnostics:
                content = diag.material.content_json or {}
                diag_subject_id = content.get("subject_id")
                if subject_id is None or diag_subject_id == subject_id:
                    submission = diag
                    break

            if not submission:
                return None

            # Calculate module scores from results
            content = submission.material.content_json or {}
            question_modules = content.get("question_modules", {})

            module_results = {}
            for r in (submission.results_json or []):
                q_num = str(r.get("number", ""))
                module_num = question_modules.get(q_num)
                if module_num is not None:
                    if module_num not in module_results:
                        module_results[module_num] = {"correct": 0, "total": 0}
                    module_results[module_num]["total"] += 1
                    if r.get("is_correct"):
                        module_results[module_num]["correct"] += 1

            module_scores = {}
            for module_num, counts in module_results.items():
                if counts["total"] > 0:
                    module_scores[module_num] = {
                        "score": (counts["correct"] / counts["total"]) * 100,
                        "correct": counts["correct"],
                        "total": counts["total"],
                        "mastered": (counts["correct"] / counts["total"]) * 100 >= DIAGNOSTIC_MASTERY_THRESHOLD
                    }

            # Get module titles
            modules = session.query(Module).order_by(Module.number).all()
            module_titles = {m.number: m.title for m in modules}

            return {
                "overall_score": submission.score,
                "graded_at": submission.graded_at,
                "module_scores": module_scores,
                "module_titles": module_titles,
                "modules_mastered": [m for m, data in module_scores.items() if data.get("mastered")],
                "modules_to_study": [m for m, data in module_scores.items() if not data.get("mastered")]
            }
