"""Generate feedback PDFs for graded work."""

from pathlib import Path
from typing import Optional
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.lib.enums import TA_CENTER

from ..config import GENERATED_FOLDER, STUDENT_NAME, MASTERY_THRESHOLD
from ..database import get_session, Submission, Material, SubmissionStatus


class FeedbackGenerator:
    """Generate feedback PDFs for graded submissions."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Set up custom paragraph styles."""
        self.styles.add(ParagraphStyle(
            name='FeedbackTitle',
            parent=self.styles['Heading1'],
            fontSize=20,
            spaceAfter=15,
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name='Correct',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.darkgreen,
            leftIndent=20
        ))
        self.styles.add(ParagraphStyle(
            name='Incorrect',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.darkred,
            leftIndent=20
        ))
        self.styles.add(ParagraphStyle(
            name='Encouragement',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceBefore=15,
            spaceAfter=15,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            borderPadding=10,
            backColor=colors.lightyellow
        ))

    def _markdown_to_html(self, text: str) -> str:
        """Convert basic markdown to ReportLab-compatible HTML."""
        import re

        # Escape any existing HTML-like characters that aren't our tags
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;').replace('>', '&gt;')

        # Convert **bold** to <b>bold</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

        # Convert *italic* to <i>italic</i> (but not if it's part of **)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

        # Convert `code` to <font face="Courier">code</font>
        text = re.sub(r'`(.+?)`', r'<font face="Courier">\1</font>', text)

        # Handle bullet points (- item)
        lines = text.split('\n')
        converted_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('- '):
                converted_lines.append(f"  \u2022 {stripped[2:]}")
            elif stripped.startswith('* ') and not stripped.startswith('**'):
                converted_lines.append(f"  \u2022 {stripped[2:]}")
            else:
                converted_lines.append(line)
        text = '\n'.join(converted_lines)

        return text

    def generate_feedback_pdf(self, submission_id: int) -> Optional[str]:
        """Generate a feedback PDF for a graded submission."""
        with get_session() as session:
            submission = session.query(Submission).get(submission_id)
            if not submission or not submission.material:
                return None

            material = submission.material
            lesson = material.lesson
            module = lesson.module
            results = submission.results_json or []
            feedback = submission.feedback_json or {}
            error_patterns = submission.error_patterns or []

            # Create PDF
            filename = f"feedback_{material.qr_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = GENERATED_FOLDER / filename

            doc = SimpleDocTemplate(
                str(filepath),
                pagesize=letter,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=0.75*inch,
                bottomMargin=0.75*inch
            )

            elements = []

            # Title
            elements.append(Paragraph(
                f"Feedback: {lesson.title}",
                self.styles['FeedbackTitle']
            ))

            # Score summary
            score = submission.score or 0
            is_mastery = score >= MASTERY_THRESHOLD
            correct_count = sum(1 for r in results if r.get("is_correct", False))
            total_count = len(results)

            score_color = colors.darkgreen if is_mastery else colors.darkred
            score_text = "MASTERY ACHIEVED!" if is_mastery else "Keep practicing - you've got this!"

            score_data = [
                [f"Score: {score:.1f}%", f"Correct: {correct_count} / {total_count}"],
                [score_text, f"Date: {submission.graded_at.strftime('%B %d, %Y') if submission.graded_at else 'N/A'}"]
            ]

            score_table = Table(score_data, colWidths=[3.5*inch, 3.5*inch])
            score_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 2, score_color),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('PADDING', (0, 0), (-1, -1), 10),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ]))
            elements.append(score_table)
            elements.append(Spacer(1, 0.3*inch))

            # Encouragement
            encouragement = feedback.get("encouragement", "")
            if encouragement:
                elements.append(Paragraph(encouragement, self.styles['Encouragement']))

            # Detailed results
            elements.append(Paragraph("<b>Problem-by-Problem Review:</b>", self.styles['Heading2']))
            elements.append(Spacer(1, 0.1*inch))

            for result in results:
                num = result.get("number", "?")
                is_correct = result.get("is_correct", False)
                student_answer = result.get("student_answer", "")
                correct_answer = result.get("correct_answer", "")
                notes = result.get("notes", "")

                style = self.styles['Correct'] if is_correct else self.styles['Incorrect']
                status = "Correct" if is_correct else "Incorrect"

                result_block = [
                    Paragraph(f"<b>Problem {num}:</b> {status}", style),
                ]

                if not is_correct:
                    result_block.append(Paragraph(
                        f"Your answer: {student_answer}",
                        self.styles['Normal']
                    ))
                    result_block.append(Paragraph(
                        f"Correct answer: <b>{correct_answer}</b>",
                        self.styles['Normal']
                    ))

                if notes:
                    result_block.append(Paragraph(
                        f"<i>Note: {notes}</i>",
                        self.styles['Normal']
                    ))

                result_block.append(Spacer(1, 0.1*inch))
                elements.append(KeepTogether(result_block))

            # Error patterns
            if error_patterns and not is_mastery:
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph("<b>Areas to Focus On:</b>", self.styles['Heading2']))

                for pattern in error_patterns:
                    pattern_name = pattern.get("pattern", "")
                    description = pattern.get("description", "")
                    elements.append(Paragraph(
                        f"* <b>{pattern_name}</b>: {description}",
                        self.styles['Normal']
                    ))

            # Overall notes
            overall_notes = feedback.get("overall_notes", "")
            if overall_notes:
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph("<b>Overall Notes:</b>", self.styles['Heading2']))
                elements.append(Paragraph(overall_notes, self.styles['Normal']))

            # Next steps
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("<b>Next Steps:</b>", self.styles['Heading2']))

            if is_mastery:
                elements.append(Paragraph(
                    "Excellent work! You've mastered this material. You're ready to move on to the next lesson!",
                    self.styles['Normal']
                ))
            else:
                elements.append(Paragraph(
                    "You're making progress! Review the problems you missed, then try the remediation practice to strengthen your understanding.",
                    self.styles['Normal']
                ))

            doc.build(elements)

            # Update submission with feedback PDF path
            submission.feedback_pdf_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_diagnostic_feedback_pdf(self, submission_id: int, diagnostic_feedback: dict) -> Optional[str]:
        """Generate a feedback PDF for a diagnostic submission with mini-lessons."""
        with get_session() as session:
            submission = session.query(Submission).get(submission_id)
            if not submission or not submission.material:
                return None

            material = submission.material
            results = submission.results_json or []
            content = material.content_json or {}
            question_modules = content.get("question_modules", {})

            # Get module info
            mini_lessons = diagnostic_feedback.get("mini_lessons", {})
            module_titles = diagnostic_feedback.get("module_titles", {})
            wrong_answers = diagnostic_feedback.get("wrong_answers", {})

            # Create PDF
            filename = f"diagnostic_feedback_{material.qr_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = GENERATED_FOLDER / filename

            doc = SimpleDocTemplate(
                str(filepath),
                pagesize=letter,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=0.75*inch,
                bottomMargin=0.75*inch
            )

            elements = []

            # Title
            elements.append(Paragraph(
                "Diagnostic Assessment Results",
                self.styles['FeedbackTitle']
            ))

            # Get student name
            student_name = submission.student.name if submission.student else "Student"
            elements.append(Paragraph(
                f"<b>{student_name}</b>",
                ParagraphStyle('StudentName', parent=self.styles['Normal'], alignment=TA_CENTER, fontSize=14)
            ))
            elements.append(Spacer(1, 0.2*inch))

            # Score summary
            score = submission.score or 0
            correct_count = sum(1 for r in results if r.get("is_correct", False))
            total_count = len(results)

            # Calculate modules mastered vs needing study
            from ..database import Module
            module_scores = {}
            for r in results:
                q_num = str(r.get("number", ""))
                mod_num = question_modules.get(q_num)
                if mod_num is not None:
                    if mod_num not in module_scores:
                        module_scores[mod_num] = {"correct": 0, "total": 0}
                    module_scores[mod_num]["total"] += 1
                    if r.get("is_correct"):
                        module_scores[mod_num]["correct"] += 1

            modules_mastered = sum(1 for m in module_scores.values() if m["correct"] == m["total"])
            modules_to_study = len(module_scores) - modules_mastered

            score_color = colors.darkgreen if score >= 80 else colors.orange if score >= 60 else colors.darkred

            score_data = [
                [f"Overall Score: {score:.1f}%", f"Questions: {correct_count} / {total_count}"],
                [f"Modules Mastered: {modules_mastered}", f"Modules to Study: {modules_to_study}"],
                [f"Date: {submission.graded_at.strftime('%B %d, %Y') if submission.graded_at else 'N/A'}", ""]
            ]

            score_table = Table(score_data, colWidths=[3.5*inch, 3.5*inch])
            score_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 2, score_color),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('PADDING', (0, 0), (-1, -1), 10),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ]))
            elements.append(score_table)
            elements.append(Spacer(1, 0.3*inch))

            # Group results by module
            results_by_module = {}
            for r in results:
                q_num = str(r.get("number", ""))
                mod_num = question_modules.get(q_num, 0)
                if mod_num not in results_by_module:
                    results_by_module[mod_num] = []
                results_by_module[mod_num].append(r)

            # Question-by-question review grouped by module
            elements.append(Paragraph("<b>Question-by-Question Review</b>", self.styles['Heading2']))
            elements.append(Spacer(1, 0.1*inch))

            for mod_num in sorted(results_by_module.keys()):
                mod_results = results_by_module[mod_num]
                mod_title = module_titles.get(mod_num, f"Module {mod_num}")
                mod_correct = sum(1 for r in mod_results if r.get("is_correct"))
                mod_total = len(mod_results)
                mod_mastered = mod_correct == mod_total

                # Module header
                mod_color = colors.darkgreen if mod_mastered else colors.darkred
                mod_status = "MASTERED" if mod_mastered else f"{mod_correct}/{mod_total}"

                elements.append(Paragraph(
                    f"<b>Module {mod_num}: {mod_title}</b> - {mod_status}",
                    ParagraphStyle('ModuleHeader', parent=self.styles['Heading3'], textColor=mod_color)
                ))

                # Questions in this module
                for result in mod_results:
                    num = result.get("number", "?")
                    is_correct = result.get("is_correct", False)
                    student_answer = result.get("student_answer", "")
                    correct_answer = result.get("correct_answer", "")
                    notes = result.get("notes", "")

                    style = self.styles['Correct'] if is_correct else self.styles['Incorrect']
                    status = "✓ Correct" if is_correct else "✗ Incorrect"

                    result_block = [
                        Paragraph(f"<b>Question {num}:</b> {status}", style),
                    ]

                    if not is_correct:
                        result_block.append(Paragraph(
                            f"Your answer: {student_answer}",
                            self.styles['Normal']
                        ))
                        result_block.append(Paragraph(
                            f"Correct answer: <b>{correct_answer}</b>",
                            self.styles['Normal']
                        ))

                    if notes:
                        result_block.append(Paragraph(
                            f"<i>Note: {notes}</i>",
                            self.styles['Normal']
                        ))

                    result_block.append(Spacer(1, 0.05*inch))
                    elements.append(KeepTogether(result_block))

                elements.append(Spacer(1, 0.15*inch))

            # Mini-lessons section
            if mini_lessons:
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph(
                    "<b>Review Lessons</b>",
                    self.styles['Heading1']
                ))
                elements.append(Paragraph(
                    "Based on your diagnostic results, here are focused mini-lessons for the areas that need more practice:",
                    self.styles['Normal']
                ))
                elements.append(Spacer(1, 0.15*inch))

                # Add mini-lesson style
                lesson_style = ParagraphStyle(
                    'MiniLesson',
                    parent=self.styles['Normal'],
                    fontSize=10,
                    leftIndent=10,
                    rightIndent=10,
                    spaceBefore=5,
                    spaceAfter=10
                )

                for mod_num in sorted(mini_lessons.keys()):
                    lesson_data = mini_lessons[mod_num]
                    title = lesson_data.get("title", f"Module {mod_num}")
                    score_pct = lesson_data.get("score", 0)
                    wrong_count = lesson_data.get("wrong_count", 0)
                    lesson_text = lesson_data.get("lesson", "")

                    # Module lesson header
                    elements.append(Paragraph(
                        f"<b>{title}</b> (Score: {score_pct:.0f}% - {wrong_count} question{'s' if wrong_count != 1 else ''} missed)",
                        ParagraphStyle('LessonHeader', parent=self.styles['Heading3'], textColor=colors.darkblue)
                    ))

                    # Parse markdown-like content and convert to paragraphs
                    # Simple conversion: split by double newlines for paragraphs
                    lesson_paragraphs = lesson_text.split('\n\n')
                    for para in lesson_paragraphs:
                        para = para.strip()
                        if para:
                            # Handle headers (lines starting with #)
                            if para.startswith('###'):
                                header_text = self._markdown_to_html(para.replace('###', '').strip())
                                elements.append(Paragraph(
                                    f"<b>{header_text}</b>",
                                    self.styles['Heading4'] if 'Heading4' in self.styles.byName else self.styles['Normal']
                                ))
                            elif para.startswith('##'):
                                header_text = self._markdown_to_html(para.replace('##', '').strip())
                                elements.append(Paragraph(
                                    f"<b>{header_text}</b>",
                                    self.styles['Heading3']
                                ))
                            elif para.startswith('#'):
                                header_text = self._markdown_to_html(para.replace('#', '').strip())
                                elements.append(Paragraph(
                                    f"<b>{header_text}</b>",
                                    self.styles['Heading3']
                                ))
                            else:
                                # Regular paragraph - convert markdown to HTML
                                para = self._markdown_to_html(para)
                                elements.append(Paragraph(para, lesson_style))

                    elements.append(Spacer(1, 0.2*inch))

            # Next steps
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("<b>What's Next?</b>", self.styles['Heading2']))

            if modules_to_study == 0:
                elements.append(Paragraph(
                    "Amazing work! You've demonstrated mastery of all diagnostic topics. "
                    "You're ready to move forward with confidence!",
                    self.styles['Normal']
                ))
            else:
                elements.append(Paragraph(
                    f"You've shown strong skills in {modules_mastered} module{'s' if modules_mastered != 1 else ''}! "
                    f"The system will now guide you through the {modules_to_study} area{'s' if modules_to_study != 1 else ''} "
                    "that need more practice. Review the mini-lessons above, then dive into the lessons when you're ready.",
                    self.styles['Normal']
                ))

            elements.append(Spacer(1, 0.1*inch))
            elements.append(Paragraph(
                "<i>Remember: This diagnostic helps us find the perfect starting point for you. "
                "Every mathematician started somewhere!</i>",
                self.styles['Normal']
            ))

            doc.build(elements)

            # Update submission with feedback PDF path
            submission.feedback_pdf_path = str(filepath)
            session.commit()

            return str(filepath)


def generate_feedback(submission_id: int) -> Optional[str]:
    """Generate feedback PDF for a submission."""
    generator = FeedbackGenerator()
    return generator.generate_feedback_pdf(submission_id)


def generate_diagnostic_feedback(submission_id: int, diagnostic_feedback: dict) -> Optional[str]:
    """Generate diagnostic feedback PDF with mini-lessons."""
    generator = FeedbackGenerator()
    return generator.generate_diagnostic_feedback_pdf(submission_id, diagnostic_feedback)
