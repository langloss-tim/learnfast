"""Learning state machine for teacher-directed learning flow.

This module implements a state machine that determines what the student
should be doing at any given time. The system acts like a good teacher
who knows exactly what the student needs next.

State Flow:
    NEEDS_DIAGNOSTIC -> LEARNING_LESSON -> PRACTICE_READY -> PRACTICING
                                                                  |
                             NEEDS_REMEDIATION <- (score < 100%)  |
                                    |                             v
                             REMEDIATING -> MASTERED_LESSON -> (next lesson)
                                                                  |
                                                    (last lesson in module)
                                                                  v
                                              TEST_READY -> TESTING -> MODULE_COMPLETE
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

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
from ..config import MASTERY_THRESHOLD, DIAGNOSTIC_REQUIRED, REQUIRE_TEST_BEFORE_NEXT_MODULE


class LearningState(Enum):
    """States in the teacher-directed learning flow."""
    NEEDS_DIAGNOSTIC = "needs_diagnostic"
    LEARNING_LESSON = "learning_lesson"
    PRACTICE_READY = "practice_ready"
    PRACTICING = "practicing"
    PENDING_GRADE = "pending_grade"
    NEEDS_REMEDIATION = "needs_remediation"
    REMEDIATING = "remediating"
    MASTERED_LESSON = "mastered_lesson"
    TEST_READY = "test_ready"
    TESTING = "testing"
    MODULE_COMPLETE = "module_complete"
    SUBJECT_COMPLETE = "subject_complete"


@dataclass
class Assignment:
    """Represents the current assignment for a student."""
    state: LearningState
    title: str
    instructions: str
    module_id: Optional[int] = None
    module_number: Optional[int] = None
    module_title: Optional[str] = None
    lesson_id: Optional[int] = None
    lesson_number: Optional[int] = None
    lesson_title: Optional[str] = None
    material_id: Optional[int] = None
    action_type: str = "continue"  # "download", "upload", "continue", "wait", "generate"
    action_label: str = "Continue"
    progress_percent: float = 0.0
    encouragement: str = ""


class LearningStateEngine:
    """Engine that determines and manages learning states."""

    def __init__(self):
        pass

    def get_current_state(self, student_id: int, subject_id: int) -> LearningState:
        """Determine the current learning state for a student in a subject."""
        assignment = self.get_current_assignment(student_id, subject_id)
        return assignment.state

    def get_current_assignment(self, student_id: int, subject_id: int) -> Assignment:
        """Get the current assignment for a student.

        This is the main entry point - it analyzes the student's progress
        and returns exactly what they should be doing right now.
        """
        with get_session() as session:
            # Get or create subject progress
            subject_progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not subject_progress:
                # Create initial progress
                first_module = (
                    session.query(Module)
                    .filter(Module.subject_id == subject_id)
                    .order_by(Module.number)
                    .first()
                )
                first_lesson = first_module.lessons[0] if first_module and first_module.lessons else None

                subject_progress = StudentSubjectProgress(
                    student_id=student_id,
                    subject_id=subject_id,
                    current_module_id=first_module.id if first_module else None,
                    current_lesson_id=first_lesson.id if first_lesson else None,
                )
                session.add(subject_progress)
                session.commit()

            # Check if diagnostic is needed
            if self._needs_diagnostic(student_id, subject_id, session):
                return self._create_diagnostic_assignment(student_id, subject_id, session)

            # Get all modules and lessons for this subject
            modules = (
                session.query(Module)
                .filter(Module.subject_id == subject_id)
                .order_by(Module.number)
                .all()
            )

            if not modules:
                return Assignment(
                    state=LearningState.SUBJECT_COMPLETE,
                    title="No Content",
                    instructions="No modules found for this subject.",
                    action_type="wait",
                    action_label="Waiting for content"
                )

            # Calculate overall progress
            total_lessons = sum(len(m.lessons) for m in modules)
            mastered_lessons = self._count_mastered_lessons(student_id, subject_id, session)
            progress_percent = (mastered_lessons / total_lessons * 100) if total_lessons > 0 else 0

            # Find the current position - first unmastered lesson
            current_lesson = None
            current_module = None

            for module in modules:
                for lesson in sorted(module.lessons, key=lambda l: l.number):
                    progress = (
                        session.query(Progress)
                        .filter(
                            Progress.student_id == student_id,
                            Progress.lesson_id == lesson.id
                        )
                        .first()
                    )

                    if not progress or not progress.mastered:
                        current_lesson = lesson
                        current_module = module
                        break

                if current_lesson:
                    break

            # Check if subject is complete
            if not current_lesson:
                return Assignment(
                    state=LearningState.SUBJECT_COMPLETE,
                    title="Subject Complete!",
                    instructions="Congratulations! You've mastered all the content in this subject!",
                    action_type="continue",
                    action_label="Celebrate!",
                    progress_percent=100.0,
                    encouragement="Amazing work! You've completed the entire subject!"
                )

            # Get progress record for current lesson
            lesson_progress = (
                session.query(Progress)
                .filter(
                    Progress.student_id == student_id,
                    Progress.lesson_id == current_lesson.id
                )
                .first()
            )

            # Determine state based on progress
            return self._determine_lesson_state(
                student_id=student_id,
                subject_id=subject_id,
                lesson=current_lesson,
                module=current_module,
                progress=lesson_progress,
                progress_percent=progress_percent,
                session=session
            )

    def _needs_diagnostic(self, student_id: int, subject_id: int, session) -> bool:
        """Check if student needs to take diagnostic."""
        if not DIAGNOSTIC_REQUIRED:
            return False

        # Check for any graded diagnostic submission for this subject
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

        # Check if any diagnostic is for this subject
        for submission in diagnostics:
            content = submission.material.content_json or {}
            if content.get("subject_id") == subject_id:
                return False

        return True

    def _create_diagnostic_assignment(self, student_id: int, subject_id: int, session) -> Assignment:
        """Create assignment for diagnostic test."""
        subject = session.query(Subject).get(subject_id)
        subject_name = subject.name if subject else "this subject"

        # Check if diagnostic has been generated but not graded
        pending_diagnostic = (
            session.query(Submission)
            .join(Material)
            .filter(
                Submission.student_id == student_id,
                Material.material_type == MaterialType.DIAGNOSTIC,
                Submission.status == SubmissionStatus.PENDING
            )
            .first()
        )

        if pending_diagnostic:
            return Assignment(
                state=LearningState.PENDING_GRADE,
                title="Diagnostic Pending Grading",
                instructions="Your diagnostic assessment is waiting to be graded. Upload your completed work!",
                material_id=pending_diagnostic.material_id,
                action_type="upload",
                action_label="Upload Completed Diagnostic",
                encouragement="Almost there! Just upload your work."
            )

        # Check if diagnostic material exists
        diagnostic_material = (
            session.query(Material)
            .filter(Material.material_type == MaterialType.DIAGNOSTIC)
            .order_by(Material.created_at.desc())
            .first()
        )

        if diagnostic_material:
            content = diagnostic_material.content_json or {}
            if content.get("subject_id") == subject_id:
                return Assignment(
                    state=LearningState.NEEDS_DIAGNOSTIC,
                    title=f"Welcome to {subject_name}!",
                    instructions="Let's see what you already know! Take this diagnostic assessment so we can skip the stuff you've mastered.",
                    material_id=diagnostic_material.id,
                    action_type="download",
                    action_label="Download Diagnostic",
                    encouragement="This helps us personalize your learning path!"
                )

        return Assignment(
            state=LearningState.NEEDS_DIAGNOSTIC,
            title=f"Welcome to {subject_name}!",
            instructions="Let's see what you already know! First, we'll generate a diagnostic assessment.",
            action_type="generate",
            action_label="Generate Diagnostic",
            encouragement="This helps us figure out where to start!"
        )

    def _determine_lesson_state(
        self,
        student_id: int,
        subject_id: int,
        lesson: Lesson,
        module: Module,
        progress: Optional[Progress],
        progress_percent: float,
        session
    ) -> Assignment:
        """Determine the current state for a specific lesson."""

        base_info = {
            "module_id": module.id,
            "module_number": module.number,
            "module_title": module.title,
            "lesson_id": lesson.id,
            "lesson_number": lesson.number,
            "lesson_title": lesson.title,
            "progress_percent": progress_percent,
        }

        # Check for pending submissions first
        pending_submission = (
            session.query(Submission)
            .join(Material)
            .filter(
                Submission.student_id == student_id,
                Material.lesson_id == lesson.id,
                Submission.status == SubmissionStatus.PENDING
            )
            .order_by(Submission.scanned_at.desc())
            .first()
        )

        if pending_submission:
            return Assignment(
                state=LearningState.PENDING_GRADE,
                title="Waiting for Grading",
                instructions="Your work is waiting to be graded. Upload your completed work if you haven't yet!",
                material_id=pending_submission.material_id,
                action_type="upload",
                action_label="Upload or Check Status",
                encouragement="Your hard work is about to pay off!",
                **base_info
            )

        # Check for needs_retry submissions (requires remediation)
        needs_retry = (
            session.query(Submission)
            .join(Material)
            .filter(
                Submission.student_id == student_id,
                Material.lesson_id == lesson.id,
                Submission.status == SubmissionStatus.NEEDS_RETRY
            )
            .order_by(Submission.graded_at.desc())
            .first()
        )

        if needs_retry:
            # Check if remediation material exists and hasn't been attempted
            remediation_material = (
                session.query(Material)
                .filter(
                    Material.lesson_id == lesson.id,
                    Material.material_type == MaterialType.REMEDIATION
                )
                .order_by(Material.created_at.desc())
                .first()
            )

            if remediation_material:
                # Check if there's a submission for this remediation
                remediation_submission = (
                    session.query(Submission)
                    .filter(
                        Submission.student_id == student_id,
                        Submission.material_id == remediation_material.id
                    )
                    .first()
                )

                if not remediation_submission:
                    return Assignment(
                        state=LearningState.REMEDIATING,
                        title=f"Extra Practice: {lesson.title}",
                        instructions="Let's work on the areas where you need more practice. Complete this remediation worksheet.",
                        material_id=remediation_material.id,
                        action_type="download",
                        action_label="Download Extra Practice",
                        encouragement="Everyone needs extra practice sometimes - you've got this!",
                        **base_info
                    )

            # Need to generate remediation
            return Assignment(
                state=LearningState.NEEDS_REMEDIATION,
                title=f"Let's Review: {lesson.title}",
                instructions="You scored below 100% on your last attempt. Let's generate some targeted practice.",
                action_type="generate",
                action_label="Generate Extra Practice",
                encouragement="Learning from mistakes is how we grow!",
                **base_info
            )

        # Check if lesson has been read
        if not progress or not progress.lesson_read:
            # Check if lesson material exists
            lesson_material = (
                session.query(Material)
                .filter(
                    Material.lesson_id == lesson.id,
                    Material.material_type == MaterialType.LESSON
                )
                .order_by(Material.created_at.desc())
                .first()
            )

            if lesson_material:
                return Assignment(
                    state=LearningState.LEARNING_LESSON,
                    title=f"Learn: {lesson.title}",
                    instructions="Read through this lesson carefully. When you understand the concepts, mark it as complete.",
                    material_id=lesson_material.id,
                    action_type="download",
                    action_label="Download Lesson PDF",
                    encouragement="Take your time - understanding is more important than speed!",
                    **base_info
                )
            else:
                # Need to generate lesson
                return Assignment(
                    state=LearningState.LEARNING_LESSON,
                    title=f"Learn: {lesson.title}",
                    instructions="Let's generate your lesson material.",
                    action_type="generate",
                    action_label="Generate Lesson",
                    encouragement="Your personalized lesson is coming right up!",
                    **base_info
                )

        # Lesson has been read - check for practice
        practice_material = (
            session.query(Material)
            .filter(
                Material.lesson_id == lesson.id,
                Material.material_type == MaterialType.PRACTICE
            )
            .order_by(Material.created_at.desc())
            .first()
        )

        # Check if we have a graded practice submission
        if progress and progress.practice_attempts > 0:
            # Check the most recent score
            last_practice = (
                session.query(Submission)
                .join(Material)
                .filter(
                    Submission.student_id == student_id,
                    Material.lesson_id == lesson.id,
                    Material.material_type == MaterialType.PRACTICE,
                    Submission.score.isnot(None)
                )
                .order_by(Submission.graded_at.desc())
                .first()
            )

            if last_practice and last_practice.score >= MASTERY_THRESHOLD:
                # Check if this is the last lesson in the module
                module_lessons = sorted(module.lessons, key=lambda l: l.number)
                is_last_lesson = lesson.id == module_lessons[-1].id

                if is_last_lesson:
                    # Check for module test
                    return self._check_module_test_state(
                        student_id, module, progress_percent, session
                    )
                else:
                    # Advance to next lesson (this state triggers auto-advance)
                    return Assignment(
                        state=LearningState.MASTERED_LESSON,
                        title=f"Great Job on {lesson.title}!",
                        instructions="You've mastered this lesson! Click continue for your next lesson.",
                        action_type="continue",
                        action_label="Continue to Next Lesson",
                        encouragement="Excellent work! Keep up the momentum!",
                        **base_info
                    )

        # Need practice
        if practice_material:
            return Assignment(
                state=LearningState.PRACTICING,
                title=f"Practice: {lesson.title}",
                instructions="Complete this practice worksheet. Print it out, solve the problems on paper, then upload your work.",
                material_id=practice_material.id,
                action_type="download",
                action_label="Download Practice PDF",
                encouragement="Practice makes perfect!",
                **base_info
            )
        else:
            return Assignment(
                state=LearningState.PRACTICE_READY,
                title=f"Ready to Practice: {lesson.title}",
                instructions="You've read the lesson - now let's practice! Generating your practice problems...",
                action_type="generate",
                action_label="Generate Practice",
                encouragement="Time to put your knowledge to work!",
                **base_info
            )

    def _check_module_test_state(
        self,
        student_id: int,
        module: Module,
        progress_percent: float,
        session
    ) -> Assignment:
        """Check if module test is needed and return appropriate state."""
        base_info = {
            "module_id": module.id,
            "module_number": module.number,
            "module_title": module.title,
            "progress_percent": progress_percent,
        }

        if not REQUIRE_TEST_BEFORE_NEXT_MODULE:
            return Assignment(
                state=LearningState.MODULE_COMPLETE,
                title=f"Module {module.number} Complete!",
                instructions=f"You've mastered all lessons in {module.title}! Ready for the next module.",
                action_type="continue",
                action_label="Start Next Module",
                encouragement="Amazing achievement!",
                **base_info
            )

        # Check for existing test material
        test_material = (
            session.query(Material)
            .join(Lesson)
            .filter(
                Lesson.module_id == module.id,
                Material.material_type == MaterialType.TEST
            )
            .order_by(Material.created_at.desc())
            .first()
        )

        # Check for pending test submission
        if test_material:
            pending_test = (
                session.query(Submission)
                .filter(
                    Submission.student_id == student_id,
                    Submission.material_id == test_material.id,
                    Submission.status == SubmissionStatus.PENDING
                )
                .first()
            )

            if pending_test:
                return Assignment(
                    state=LearningState.PENDING_GRADE,
                    title=f"Module {module.number} Test - Waiting",
                    instructions="Your test is waiting to be graded!",
                    material_id=test_material.id,
                    action_type="upload",
                    action_label="Upload Test",
                    encouragement="Almost done with this module!",
                    **base_info
                )

            # Check for graded test
            graded_test = (
                session.query(Submission)
                .filter(
                    Submission.student_id == student_id,
                    Submission.material_id == test_material.id,
                    Submission.score.isnot(None)
                )
                .order_by(Submission.graded_at.desc())
                .first()
            )

            if graded_test:
                if graded_test.score >= MASTERY_THRESHOLD:
                    return Assignment(
                        state=LearningState.MODULE_COMPLETE,
                        title=f"Module {module.number} Complete!",
                        instructions=f"You've passed the {module.title} test! Ready for the next module.",
                        action_type="continue",
                        action_label="Start Next Module",
                        encouragement="Outstanding work!",
                        **base_info
                    )
                else:
                    # Failed test - need to review
                    return Assignment(
                        state=LearningState.NEEDS_REMEDIATION,
                        title=f"Module {module.number} Test - Review Needed",
                        instructions=f"Your test score was {graded_test.score:.0f}%. Let's review before retrying.",
                        action_type="generate",
                        action_label="Generate Review Material",
                        encouragement="You're close! A little review and you'll ace it.",
                        **base_info
                    )

            # Test exists but not submitted
            return Assignment(
                state=LearningState.TESTING,
                title=f"Module {module.number} Test",
                instructions="Time to show what you know! Complete this test to finish the module.",
                material_id=test_material.id,
                action_type="download",
                action_label="Download Test PDF",
                encouragement="You've prepared well - go show it!",
                **base_info
            )

        # Need to generate test
        return Assignment(
            state=LearningState.TEST_READY,
            title=f"Ready for Module {module.number} Test!",
            instructions="You've mastered all lessons! Let's generate your module test.",
            action_type="generate",
            action_label="Generate Module Test",
            encouragement="You've got this!",
            **base_info
        )

    def _count_mastered_lessons(self, student_id: int, subject_id: int, session) -> int:
        """Count the number of mastered lessons in a subject."""
        return (
            session.query(Progress)
            .join(Lesson)
            .join(Module)
            .filter(
                Progress.student_id == student_id,
                Module.subject_id == subject_id,
                Progress.mastered == True
            )
            .count()
        )

    def mark_lesson_read(self, student_id: int, lesson_id: int) -> bool:
        """Mark a lesson as read by the student."""
        with get_session() as session:
            progress = (
                session.query(Progress)
                .filter(
                    Progress.student_id == student_id,
                    Progress.lesson_id == lesson_id
                )
                .first()
            )

            if not progress:
                progress = Progress(
                    student_id=student_id,
                    lesson_id=lesson_id
                )
                session.add(progress)

            progress.lesson_read = True
            progress.lesson_read_at = datetime.utcnow()
            session.commit()
            return True

    def advance_to_next(self, student_id: int, subject_id: int) -> Optional[Assignment]:
        """Advance the student to the next lesson/module.

        This is called after mastering a lesson to move to the next one.
        Returns the new assignment.
        """
        with get_session() as session:
            # Mark current lesson as mastered if not already
            subject_progress = (
                session.query(StudentSubjectProgress)
                .filter(
                    StudentSubjectProgress.student_id == student_id,
                    StudentSubjectProgress.subject_id == subject_id
                )
                .first()
            )

            if not subject_progress or not subject_progress.current_lesson_id:
                return self.get_current_assignment(student_id, subject_id)

            current_lesson = session.query(Lesson).get(subject_progress.current_lesson_id)
            if not current_lesson:
                return self.get_current_assignment(student_id, subject_id)

            current_module = current_lesson.module
            module_lessons = sorted(current_module.lessons, key=lambda l: l.number)

            # Find next lesson
            current_index = next(
                (i for i, l in enumerate(module_lessons) if l.id == current_lesson.id),
                -1
            )

            if current_index < len(module_lessons) - 1:
                # Move to next lesson in module
                next_lesson = module_lessons[current_index + 1]
                subject_progress.current_lesson_id = next_lesson.id
            else:
                # Move to next module
                modules = (
                    session.query(Module)
                    .filter(Module.subject_id == subject_id)
                    .order_by(Module.number)
                    .all()
                )
                current_mod_index = next(
                    (i for i, m in enumerate(modules) if m.id == current_module.id),
                    -1
                )

                if current_mod_index < len(modules) - 1:
                    next_module = modules[current_mod_index + 1]
                    if next_module.lessons:
                        next_lesson = sorted(next_module.lessons, key=lambda l: l.number)[0]
                        subject_progress.current_module_id = next_module.id
                        subject_progress.current_lesson_id = next_lesson.id
                # else: subject is complete

            session.commit()

        return self.get_current_assignment(student_id, subject_id)


def get_encouragement_for_state(state: LearningState) -> str:
    """Get an encouraging message based on the current state."""
    encouragements = {
        LearningState.NEEDS_DIAGNOSTIC: "Let's see what you already know!",
        LearningState.LEARNING_LESSON: "Take your time - understanding builds success!",
        LearningState.PRACTICE_READY: "You're ready to practice!",
        LearningState.PRACTICING: "Every problem you solve makes you stronger!",
        LearningState.PENDING_GRADE: "Your work is being reviewed!",
        LearningState.NEEDS_REMEDIATION: "Everyone needs extra practice sometimes!",
        LearningState.REMEDIATING: "You're building solid foundations!",
        LearningState.MASTERED_LESSON: "Excellent work - you've got this!",
        LearningState.TEST_READY: "Time to show what you know!",
        LearningState.TESTING: "Stay focused - you're prepared for this!",
        LearningState.MODULE_COMPLETE: "Amazing achievement!",
        LearningState.SUBJECT_COMPLETE: "You're a champion!",
    }
    return encouragements.get(state, "Keep going!")
