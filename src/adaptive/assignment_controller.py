"""Assignment controller for teacher-directed learning.

This module integrates the learning state machine with content generation
to automatically produce the right material for each student's assignment.
"""

from pathlib import Path
from typing import Optional, Dict, Any

from .learning_state import LearningState, LearningStateEngine, Assignment
from .pacing import AdaptivePacer
from ..database import get_session, Material, Lesson, Module, MaterialType
from ..content.generator import ContentGenerator
from ..pdf.generator import PDFGenerator


class AssignmentController:
    """Controller for managing student assignments in teacher-directed mode."""

    def __init__(self):
        self.state_engine = LearningStateEngine()
        self.pacer = AdaptivePacer()
        self.content_generator = ContentGenerator()

    def get_assignment(self, student_id: int, subject_id: int) -> Assignment:
        """Get the current assignment for a student.

        This is the main entry point for the dashboard to determine
        what to show the student.
        """
        return self.state_engine.get_current_assignment(student_id, subject_id)

    def generate_material_for_assignment(
        self,
        assignment: Assignment,
        student_id: int,
        subject_id: int,
        student_name: str = "Student"
    ) -> Optional[Dict[str, Any]]:
        """Generate the appropriate material for an assignment.

        Returns dict with material_id, file_path, qr_code on success.
        Returns None on failure.
        """
        state = assignment.state
        module_number = assignment.module_number
        lesson_number = assignment.lesson_number

        pdf_gen = PDFGenerator(student_name=student_name)
        result = None
        pdf_path = None

        if state == LearningState.NEEDS_DIAGNOSTIC:
            result = self.content_generator.generate_diagnostic(
                questions_per_module=4,
                subject_id=subject_id
            )
            if result:
                pdf_path = pdf_gen.generate_diagnostic_pdf(result["material_id"])

        elif state == LearningState.LEARNING_LESSON:
            if module_number and lesson_number:
                result = self.content_generator.generate_lesson(
                    module_number,
                    lesson_number,
                    subject_id=subject_id
                )
                if result:
                    pdf_path = pdf_gen.generate_lesson_pdf(result["material_id"])

        elif state in (LearningState.PRACTICE_READY, LearningState.PRACTICING):
            if module_number and lesson_number:
                # Get adaptive problem count and difficulty
                num_problems = self.pacer.calculate_problem_count(student_id, subject_id)
                difficulty = self.pacer.get_difficulty_adjustment(student_id, subject_id)

                result = self.content_generator.generate_practice(
                    module_number,
                    lesson_number,
                    num_problems=num_problems,
                    difficulty=difficulty,
                    subject_id=subject_id
                )
                if result:
                    pdf_path = pdf_gen.generate_practice_pdf(result["material_id"])

        elif state in (LearningState.NEEDS_REMEDIATION, LearningState.REMEDIATING):
            if module_number and lesson_number:
                # Get weak concepts for targeted remediation
                weak_concepts = self.pacer.get_weak_concepts(student_id, assignment.lesson_id)

                result = self.content_generator.generate_remediation(
                    module_number,
                    lesson_number,
                    weak_concepts if weak_concepts else ["general review"]
                )
                if result:
                    pdf_path = pdf_gen.generate_practice_pdf(result["material_id"])

        elif state == LearningState.TEST_READY:
            if module_number:
                result = self.content_generator.generate_test(
                    module_number,
                    subject_id=subject_id
                )
                if result:
                    pdf_path = pdf_gen.generate_test_pdf(result["material_id"])

        if result and pdf_path:
            return {
                "material_id": result.get("material_id"),
                "file_path": pdf_path,
                "qr_code": result.get("qr_code"),
                "content": result
            }

        return None

    def mark_lesson_complete(self, student_id: int, lesson_id: int) -> bool:
        """Mark a lesson as read/complete.

        Called when student clicks "I've Read the Lesson" button.
        """
        return self.state_engine.mark_lesson_read(student_id, lesson_id)

    def advance_student(self, student_id: int, subject_id: int) -> Assignment:
        """Advance the student to the next lesson/module.

        Called after mastering a lesson to move forward.
        Returns the new assignment.
        """
        return self.state_engine.advance_to_next(student_id, subject_id)

    def get_progress_info(self, student_id: int, subject_id: int) -> Dict[str, Any]:
        """Get progress information for display.

        Returns overall progress, pace info, and current position.
        """
        assignment = self.get_assignment(student_id, subject_id)
        velocity = self.pacer.get_velocity_indicator(student_id, subject_id)
        summary = self.pacer.get_progress_summary(student_id, subject_id)

        return {
            "assignment": assignment,
            "velocity": velocity,
            "summary": summary,
            "progress_percent": assignment.progress_percent,
            "module_number": assignment.module_number,
            "lesson_number": assignment.lesson_number,
            "total_modules": len(summary.get("modules", [])),
        }

    def auto_generate_if_needed(
        self,
        assignment: Assignment,
        student_id: int,
        subject_id: int,
        student_name: str = "Student"
    ) -> Optional[Dict[str, Any]]:
        """Automatically generate material if the assignment requires it.

        This checks if material needs to be generated and does so.
        Returns generation result or None if no generation needed.
        """
        # Only auto-generate if action_type is "generate"
        if assignment.action_type != "generate":
            return None

        return self.generate_material_for_assignment(
            assignment,
            student_id,
            subject_id,
            student_name
        )

    def get_material_download_info(self, material_id: int) -> Optional[Dict[str, Any]]:
        """Get information needed to download a material.

        Returns dict with file_path, filename, exists, qr_code.
        """
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material:
                return None

            file_path = Path(material.file_path) if material.file_path else None
            exists = file_path.exists() if file_path else False

            return {
                "material_id": material.id,
                "file_path": str(file_path) if file_path else None,
                "filename": file_path.name if file_path else None,
                "exists": exists,
                "qr_code": material.qr_code,
                "material_type": material.material_type.value,
            }

    def get_state_ui_config(self, state: LearningState) -> Dict[str, Any]:
        """Get UI configuration for a specific state.

        Returns colors, icons, and other UI hints for each state.
        """
        configs = {
            LearningState.NEEDS_DIAGNOSTIC: {
                "icon": "clipboard-list",
                "color": "blue",
                "phase": "ASSESSMENT",
                "show_download": False,
                "show_upload": False,
                "show_generate": True,
            },
            LearningState.LEARNING_LESSON: {
                "icon": "book-open",
                "color": "green",
                "phase": "LEARNING",
                "show_download": True,
                "show_upload": False,
                "show_generate": False,
                "show_complete_button": True,
            },
            LearningState.PRACTICE_READY: {
                "icon": "pencil",
                "color": "yellow",
                "phase": "PRACTICE",
                "show_download": False,
                "show_upload": False,
                "show_generate": True,
            },
            LearningState.PRACTICING: {
                "icon": "pencil",
                "color": "yellow",
                "phase": "PRACTICE",
                "show_download": True,
                "show_upload": True,
                "show_generate": False,
            },
            LearningState.PENDING_GRADE: {
                "icon": "clock",
                "color": "gray",
                "phase": "GRADING",
                "show_download": False,
                "show_upload": True,
                "show_generate": False,
            },
            LearningState.NEEDS_REMEDIATION: {
                "icon": "refresh",
                "color": "orange",
                "phase": "REVIEW",
                "show_download": False,
                "show_upload": False,
                "show_generate": True,
            },
            LearningState.REMEDIATING: {
                "icon": "refresh",
                "color": "orange",
                "phase": "REVIEW",
                "show_download": True,
                "show_upload": True,
                "show_generate": False,
            },
            LearningState.MASTERED_LESSON: {
                "icon": "check-circle",
                "color": "green",
                "phase": "COMPLETE",
                "show_download": False,
                "show_upload": False,
                "show_generate": False,
                "show_continue": True,
            },
            LearningState.TEST_READY: {
                "icon": "clipboard-check",
                "color": "purple",
                "phase": "TEST",
                "show_download": False,
                "show_upload": False,
                "show_generate": True,
            },
            LearningState.TESTING: {
                "icon": "clipboard-check",
                "color": "purple",
                "phase": "TEST",
                "show_download": True,
                "show_upload": True,
                "show_generate": False,
            },
            LearningState.MODULE_COMPLETE: {
                "icon": "trophy",
                "color": "gold",
                "phase": "MODULE COMPLETE",
                "show_download": False,
                "show_upload": False,
                "show_generate": False,
                "show_continue": True,
            },
            LearningState.SUBJECT_COMPLETE: {
                "icon": "star",
                "color": "gold",
                "phase": "FINISHED!",
                "show_download": False,
                "show_upload": False,
                "show_generate": False,
            },
        }

        return configs.get(state, {
            "icon": "question",
            "color": "gray",
            "phase": "UNKNOWN",
        })
