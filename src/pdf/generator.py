"""PDF generation for printable learning materials."""

import io
from pathlib import Path
from datetime import datetime
from typing import Optional

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
    PageBreak,
    Image,
    KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import qrcode

from ..config import GENERATED_FOLDER, STUDENT_NAME
from ..database import get_session, Material, MaterialType


class PDFGenerator:
    """Generate printable PDFs for lessons, practice, quizzes, and tests."""

    def __init__(self, student_name: str = None):
        self.student_name = student_name or STUDENT_NAME
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Set up custom paragraph styles."""
        self.styles.add(ParagraphStyle(
            name='MaterialTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=20,
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name='SectionHeading',
            parent=self.styles['Heading2'],
            fontSize=16,
            spaceBefore=15,
            spaceAfter=10,
            textColor=colors.darkblue
        ))
        self.styles.add(ParagraphStyle(
            name='Problem',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceBefore=8,
            spaceAfter=4,
            leftIndent=20
        ))
        self.styles.add(ParagraphStyle(
            name='AnswerSpace',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceBefore=5,
            spaceAfter=15,
            leftIndent=40,
            textColor=colors.gray
        ))
        self.styles.add(ParagraphStyle(
            name='RealWorld',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceBefore=10,
            spaceAfter=10,
            leftIndent=15,
            rightIndent=15,
            backColor=colors.lightblue,
            borderPadding=10
        ))
        self.styles.add(ParagraphStyle(
            name='Example',
            parent=self.styles['Normal'],
            fontSize=11,
            leftIndent=30,
            spaceBefore=5,
            spaceAfter=5
        ))

    def _generate_qr_image(self, qr_code: str) -> Image:
        """Generate a QR code image for the material."""
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(qr_code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Save to bytes buffer
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return Image(buffer, width=0.8*inch, height=0.8*inch)

    def _add_header(self, elements: list, title: str, qr_code: str, material_type: str):
        """Add header with title, date, and QR code."""
        # Header table with title and QR code
        qr_img = self._generate_qr_image(qr_code)

        header_data = [
            [
                Paragraph(title, self.styles['MaterialTitle']),
                qr_img
            ],
            [
                Paragraph(f"Student: {self.student_name}", self.styles['Normal']),
                Paragraph(f"ID: {qr_code}", self.styles['Normal'])
            ],
            [
                Paragraph(f"Date: _______________", self.styles['Normal']),
                Paragraph(f"Type: {material_type}", self.styles['Normal'])
            ]
        ]

        header_table = Table(header_data, colWidths=[5.5*inch, 1.5*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))

        elements.append(header_table)
        elements.append(Spacer(1, 0.3*inch))

        # Divider line
        divider = Table([['']], colWidths=[7*inch])
        divider.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, -1), 1, colors.darkblue),
        ]))
        elements.append(divider)
        elements.append(Spacer(1, 0.2*inch))

    def generate_lesson_pdf(self, material_id: int) -> Optional[str]:
        """Generate a lesson PDF."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material or material.material_type != MaterialType.LESSON:
                return None

            content = material.content_json
            lesson = material.lesson
            module = lesson.module

            # Create PDF
            filename = f"lesson_m{module.number}_l{lesson.number}_{material.qr_code}.pdf"
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

            # Header
            self._add_header(
                elements,
                content.get("title", f"Lesson {lesson.number}: {lesson.title}"),
                material.qr_code,
                "LESSON"
            )

            # Introduction
            if content.get("introduction"):
                elements.append(Paragraph(content["introduction"], self.styles['Normal']))
                elements.append(Spacer(1, 0.15*inch))

            # Real-world connection box
            if content.get("real_world_connection"):
                elements.append(Paragraph(
                    f"<b>Real-World Connection:</b> {content['real_world_connection']}",
                    self.styles['RealWorld']
                ))
                elements.append(Spacer(1, 0.15*inch))

            # Sections
            for section in content.get("sections", []):
                elements.append(Paragraph(section.get("heading", ""), self.styles['SectionHeading']))

                if section.get("explanation"):
                    elements.append(Paragraph(section["explanation"], self.styles['Normal']))
                    elements.append(Spacer(1, 0.1*inch))

                # Examples
                for i, example in enumerate(section.get("examples", []), 1):
                    example_content = [
                        Paragraph(f"<b>Example {i}:</b> {example.get('problem', '')}", self.styles['Example']),
                    ]
                    if example.get("solution"):
                        example_content.append(Paragraph(
                            f"<b>Solution:</b> {example['solution']}",
                            self.styles['Example']
                        ))
                    if example.get("explanation"):
                        example_content.append(Paragraph(
                            f"<i>{example['explanation']}</i>",
                            self.styles['Example']
                        ))
                    example_content.append(Spacer(1, 0.1*inch))
                    elements.append(KeepTogether(example_content))

                # Key points
                if section.get("key_points"):
                    elements.append(Paragraph("<b>Key Points:</b>", self.styles['Normal']))
                    for point in section["key_points"]:
                        elements.append(Paragraph(f"  * {point}", self.styles['Normal']))
                    elements.append(Spacer(1, 0.15*inch))

            # Vocabulary
            if content.get("vocabulary"):
                elements.append(PageBreak())
                elements.append(Paragraph("Vocabulary", self.styles['SectionHeading']))
                for term in content["vocabulary"]:
                    elements.append(Paragraph(
                        f"<b>{term.get('term', '')}:</b> {term.get('definition', '')}",
                        self.styles['Normal']
                    ))
                elements.append(Spacer(1, 0.15*inch))

            # Summary
            if content.get("summary"):
                elements.append(Paragraph("<b>Summary:</b>", self.styles['SectionHeading']))
                elements.append(Paragraph(content["summary"], self.styles['Normal']))

            # Practice preview
            if content.get("practice_preview"):
                elements.append(Spacer(1, 0.2*inch))
                elements.append(Paragraph("Try These:", self.styles['SectionHeading']))
                for i, prob in enumerate(content["practice_preview"], 1):
                    elements.append(Paragraph(f"{i}. {prob.get('problem', '')}", self.styles['Problem']))
                    elements.append(Paragraph("Answer: _________________", self.styles['AnswerSpace']))

            doc.build(elements)

            # Update material with file path
            material.file_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_practice_pdf(self, material_id: int) -> Optional[str]:
        """Generate a practice problem set PDF."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material or material.material_type not in [MaterialType.PRACTICE, MaterialType.REMEDIATION]:
                return None

            content = material.content_json
            lesson = material.lesson
            module = lesson.module

            mat_type = "practice" if material.material_type == MaterialType.PRACTICE else "remediation"
            filename = f"{mat_type}_m{module.number}_l{lesson.number}_{material.qr_code}.pdf"
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

            # Header
            self._add_header(
                elements,
                content.get("title", f"Practice: {lesson.title}"),
                material.qr_code,
                mat_type.upper()
            )

            # Instructions
            if content.get("instructions"):
                elements.append(Paragraph(f"<b>Instructions:</b> {content['instructions']}", self.styles['Normal']))
                elements.append(Spacer(1, 0.2*inch))

            # Problems
            for problem in content.get("problems", []):
                num = problem.get("number", "")
                text = problem.get("problem", "")

                # Problem with answer space
                problem_block = [
                    Paragraph(f"<b>{num}.</b> {text}", self.styles['Problem']),
                ]

                # Add hint if this is remediation and has hint
                if material.material_type == MaterialType.REMEDIATION and problem.get("hint"):
                    problem_block.append(Paragraph(
                        f"<i>Hint: {problem['hint']}</i>",
                        self.styles['Example']
                    ))

                # Answer space
                problem_block.append(Spacer(1, 0.1*inch))
                problem_block.append(Paragraph("Answer: _________________________________", self.styles['AnswerSpace']))

                # Work space for harder problems
                if problem.get("difficulty") in ["medium", "hard"]:
                    problem_block.append(Paragraph("Show your work:", self.styles['AnswerSpace']))
                    problem_block.append(Spacer(1, 0.5*inch))

                problem_block.append(Spacer(1, 0.1*inch))
                elements.append(KeepTogether(problem_block))

            doc.build(elements)

            material.file_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_quiz_pdf(self, material_id: int) -> Optional[str]:
        """Generate a quiz PDF."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material or material.material_type != MaterialType.QUIZ:
                return None

            content = material.content_json
            lesson = material.lesson
            module = lesson.module

            filename = f"quiz_m{module.number}_{material.qr_code}.pdf"
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

            # Header
            self._add_header(
                elements,
                content.get("title", f"Quiz: Module {module.number}"),
                material.qr_code,
                "QUIZ"
            )

            # Score box
            total_points = content.get("total_points", len(content.get("questions", [])))
            score_table = Table(
                [[f"Score: _____ / {total_points}", "Mastery: YES / NO"]],
                colWidths=[3.5*inch, 3.5*inch]
            )
            score_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('PADDING', (0, 0), (-1, -1), 10),
            ]))
            elements.append(score_table)
            elements.append(Spacer(1, 0.2*inch))

            # Instructions
            if content.get("instructions"):
                elements.append(Paragraph(f"<b>Instructions:</b> {content['instructions']}", self.styles['Normal']))
                elements.append(Spacer(1, 0.2*inch))

            # Questions
            for question in content.get("questions", []):
                num = question.get("number", "")
                text = question.get("question", "")
                points = question.get("points", 1)

                question_block = [
                    Paragraph(f"<b>{num}.</b> ({points} pt) {text}", self.styles['Problem']),
                    Spacer(1, 0.1*inch),
                    Paragraph("Answer: _________________________________", self.styles['AnswerSpace']),
                ]

                if question.get("requires_work", False):
                    question_block.append(Paragraph("Show your work:", self.styles['AnswerSpace']))
                    question_block.append(Spacer(1, 0.6*inch))

                question_block.append(Spacer(1, 0.15*inch))
                elements.append(KeepTogether(question_block))

            doc.build(elements)

            material.file_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_test_pdf(self, material_id: int) -> Optional[str]:
        """Generate a test PDF."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material or material.material_type != MaterialType.TEST:
                return None

            content = material.content_json
            lesson = material.lesson
            module = lesson.module

            filename = f"test_m{module.number}_{material.qr_code}.pdf"
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

            # Header
            self._add_header(
                elements,
                content.get("title", f"Module {module.number} Test"),
                material.qr_code,
                "TEST"
            )

            # Score box
            total_points = content.get("total_points", len(content.get("questions", [])))
            score_table = Table(
                [
                    [f"Score: _____ / {total_points}", f"Percentage: _____ %"],
                    ["MASTERY ACHIEVED:", "YES  /  NO  (100% required)"]
                ],
                colWidths=[3.5*inch, 3.5*inch]
            )
            score_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 2, colors.darkblue),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('PADDING', (0, 0), (-1, -1), 10),
                ('BACKGROUND', (0, 1), (-1, 1), colors.lightyellow),
            ]))
            elements.append(score_table)
            elements.append(Spacer(1, 0.2*inch))

            # Instructions
            if content.get("instructions"):
                elements.append(Paragraph(f"<b>Instructions:</b> {content['instructions']}", self.styles['Normal']))
                elements.append(Spacer(1, 0.2*inch))

            # Questions
            for question in content.get("questions", []):
                num = question.get("number", "")
                text = question.get("question", "")
                points = question.get("points", 1)

                question_block = [
                    Paragraph(f"<b>{num}.</b> ({points} pt) {text}", self.styles['Problem']),
                    Spacer(1, 0.1*inch),
                    Paragraph("Answer: _________________________________", self.styles['AnswerSpace']),
                ]

                if question.get("requires_work", True):  # Tests default to requiring work
                    question_block.append(Paragraph("Show your work:", self.styles['AnswerSpace']))
                    question_block.append(Spacer(1, 0.7*inch))

                question_block.append(Spacer(1, 0.15*inch))
                elements.append(KeepTogether(question_block))

            doc.build(elements)

            material.file_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_diagnostic_pdf(self, material_id: int) -> Optional[str]:
        """Generate a diagnostic assessment PDF."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material or material.material_type != MaterialType.DIAGNOSTIC:
                return None

            content = material.content_json

            filename = f"diagnostic_{material.qr_code}.pdf"
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

            # Header
            self._add_header(
                elements,
                content.get("title", "Pre-Algebra Diagnostic Assessment"),
                material.qr_code,
                "DIAGNOSTIC"
            )

            # Info box
            total_questions = content.get("total_questions", 32)
            info_table = Table(
                [
                    ["This assessment covers all 8 modules of pre-algebra."],
                    [f"Total Questions: {total_questions}"],
                    ["Score 100% on a module's questions to skip that module."]
                ],
                colWidths=[7*inch]
            )
            info_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 1, colors.darkblue),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('PADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, -1), colors.lightyellow),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 0.2*inch))

            # Instructions
            if content.get("instructions"):
                elements.append(Paragraph(f"<b>Instructions:</b> {content['instructions']}", self.styles['Normal']))
                elements.append(Spacer(1, 0.2*inch))

            # Questions by module
            global_num = 1
            for module_section in content.get("modules", []):
                module_num = module_section.get("module_number", "?")
                module_title = module_section.get("module_title", "")

                # Module header
                elements.append(Paragraph(
                    f"<b>Module {module_num}: {module_title}</b>",
                    self.styles['SectionHeading']
                ))

                for question in module_section.get("questions", []):
                    text = question.get("question", "")

                    question_block = [
                        Paragraph(f"<b>{global_num}.</b> {text}", self.styles['Problem']),
                        Spacer(1, 0.1*inch),
                        Paragraph("Answer: _________________________________", self.styles['AnswerSpace']),
                        Spacer(1, 0.3*inch),
                    ]
                    elements.append(KeepTogether(question_block))
                    global_num += 1

                elements.append(Spacer(1, 0.1*inch))

            doc.build(elements)

            material.file_path = str(filepath)
            session.commit()

            return str(filepath)

    def generate_pdf(self, material_id: int) -> Optional[str]:
        """Generate a PDF for any material type."""
        with get_session() as session:
            material = session.query(Material).get(material_id)
            if not material:
                return None

            if material.material_type == MaterialType.LESSON:
                return self.generate_lesson_pdf(material_id)
            elif material.material_type in [MaterialType.PRACTICE, MaterialType.REMEDIATION]:
                return self.generate_practice_pdf(material_id)
            elif material.material_type == MaterialType.QUIZ:
                return self.generate_quiz_pdf(material_id)
            elif material.material_type == MaterialType.TEST:
                return self.generate_test_pdf(material_id)
            elif material.material_type == MaterialType.DIAGNOSTIC:
                return self.generate_diagnostic_pdf(material_id)

            return None
