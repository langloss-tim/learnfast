"""Claude-powered content generation for lessons and problems."""

import json
import uuid
from typing import Optional
from anthropic import Anthropic

from ..config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    PROBLEMS_PER_PRACTICE,
    QUESTIONS_PER_QUIZ,
    QUESTIONS_PER_TEST,
    MASTERY_ASSESSMENT_QUESTIONS,
)
from ..database import get_session, Material, MaterialType, Lesson, Module, Student, Subject


class ContentGenerator:
    """Generate lesson content, problems, and assessments using Claude."""

    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)

    def _generate_qr_code(self) -> str:
        """Generate a unique QR code identifier."""
        return f"PA-{uuid.uuid4().hex[:8].upper()}"

    def generate_lesson(self, module_number: int, lesson_number: int, subject_id: int = None) -> Optional[dict]:
        """Generate a lesson with explanations and examples."""
        with get_session() as session:
            query = session.query(Lesson).join(Module).filter(
                Module.number == module_number,
                Lesson.number == lesson_number
            )
            if subject_id:
                query = query.filter(Module.subject_id == subject_id)

            lesson = query.first()
            if not lesson:
                return None

            module = lesson.module
            subject = module.subject if module.subject_id else None
            subject_name = subject.name if subject else "Pre-Algebra"
            grade_desc = f"grade {subject.grade_level}" if subject and subject.grade_level else "advanced fifth-grader"

            prompt = f"""Generate a comprehensive {subject_name} lesson for a {grade_desc} student.

MODULE: {module.number}. {module.title}
LESSON: {lesson.number}. {lesson.title}
CONCEPTS TO COVER: {', '.join(lesson.concepts or [])}
REAL-WORLD APPLICATIONS: {', '.join(module.real_world_applications or [])}

Generate the lesson content in JSON format with this structure:
{{
    "title": "Lesson title",
    "introduction": "2-3 sentences introducing the topic and why it matters",
    "real_world_connection": "A specific real-world scenario that uses this math (make it engaging for a 10-11 year old)",
    "sections": [
        {{
            "heading": "Section heading",
            "explanation": "Clear explanation of the concept",
            "examples": [
                {{
                    "problem": "Example problem",
                    "solution": "Step-by-step solution",
                    "explanation": "Why each step works"
                }}
            ],
            "key_points": ["Important point 1", "Important point 2"]
        }}
    ],
    "practice_preview": [
        {{
            "problem": "A practice problem",
            "answer": "The answer"
        }}
    ],
    "vocabulary": [
        {{
            "term": "Mathematical term",
            "definition": "Clear definition for a 5th grader"
        }}
    ],
    "summary": "Brief summary of what was learned"
}}

Make the content:
- Clear and age-appropriate for an advanced 5th grader
- Include 2-3 worked examples per section
- Connect to real-world applications throughout
- Build on concepts progressively
- Include visual descriptions where helpful (e.g., "imagine a number line...")"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            # Extract JSON from response
            try:
                # Find JSON in response
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            # Create material record
            qr_code = self._generate_qr_code()
            material = Material(
                lesson_id=lesson.id,
                material_type=MaterialType.LESSON,
                content_json=content_json,
                answer_key_json=None,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json
            }

    def generate_practice(
        self,
        module_number: int,
        lesson_number: int,
        num_problems: int = None,
        difficulty: str = "standard",
        subject_id: int = None
    ) -> Optional[dict]:
        """
        Generate a practice problem set for a lesson.

        Args:
            module_number: Module number within subject
            lesson_number: Lesson number within module
            num_problems: Number of problems (uses adaptive count if None)
            difficulty: "easier", "standard", or "harder" - adjusts problem difficulty mix
            subject_id: Subject ID for multi-subject support
        """
        num_problems = num_problems or PROBLEMS_PER_PRACTICE

        with get_session() as session:
            # Build query with optional subject filter
            query = session.query(Lesson).join(Module).filter(
                Module.number == module_number,
                Lesson.number == lesson_number
            )
            if subject_id:
                query = query.filter(Module.subject_id == subject_id)

            lesson = query.first()
            if not lesson:
                return None

            module = lesson.module
            subject = module.subject if module.subject_id else None
            subject_name = subject.name if subject else "Pre-Algebra"

            # Adjust difficulty mix based on adaptive setting
            if difficulty == "easier":
                difficulty_instruction = """
Requirements:
- Difficulty mix: 60% easy, 30% medium, 10% hard
- Start with simpler versions of each concept
- Include extra hints and scaffolding
- Word problems should be straightforward
- Focus on building confidence"""
            elif difficulty == "harder":
                difficulty_instruction = """
Requirements:
- Difficulty mix: 20% easy, 40% medium, 40% hard
- Include challenging extension problems
- Word problems should require multi-step reasoning
- Add some problems that combine multiple concepts
- Challenge the student to think deeply"""
            else:  # standard
                difficulty_instruction = """
Requirements:
- Mix of difficulty levels (40% easy, 40% medium, 20% hard)
- Include 3-4 word problems that apply concepts to real situations
- Clear, unambiguous problems
- Answers should be specific (not ranges)
- Progress from easier to harder
- Include some challenging extension problems"""

            prompt = f"""Generate {num_problems} practice problems for a {subject_name} lesson.

MODULE: {module.number}. {module.title}
LESSON: {lesson.number}. {lesson.title}
CONCEPTS: {', '.join(lesson.concepts or [])}

Generate problems in JSON format:
{{
    "title": "Practice: {lesson.title}",
    "instructions": "Clear instructions for the student",
    "problems": [
        {{
            "number": 1,
            "problem": "The problem text (use clear mathematical notation)",
            "answer": "The correct answer",
            "concept": "Which concept this tests",
            "difficulty": "easy|medium|hard",
            "hint": "A hint if they're stuck (optional)"
        }}
    ]
}}
{difficulty_instruction}"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            # Extract answer key
            answer_key = {
                str(p["number"]): p["answer"]
                for p in content_json.get("problems", [])
            }

            qr_code = self._generate_qr_code()
            material = Material(
                lesson_id=lesson.id,
                material_type=MaterialType.PRACTICE,
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "problem_count": len(content_json.get("problems", []))
            }

    def generate_quiz(self, module_number: int, up_to_lesson: int = None, subject_id: int = None) -> Optional[dict]:
        """Generate a quiz covering lessons in a module."""
        num_questions = QUESTIONS_PER_QUIZ

        with get_session() as session:
            query = session.query(Module).filter(Module.number == module_number)
            if subject_id:
                query = query.filter(Module.subject_id == subject_id)
            module = query.first()
            if not module:
                return None

            lessons = module.lessons
            if up_to_lesson:
                lessons = [l for l in lessons if l.number <= up_to_lesson]

            all_concepts = []
            for lesson in lessons:
                all_concepts.extend(lesson.concepts or [])

            prompt = f"""Generate a {num_questions}-question quiz for pre-algebra.

MODULE: {module.number}. {module.title}
COVERING LESSONS: {', '.join(l.title for l in lessons)}
CONCEPTS: {', '.join(all_concepts)}

Generate the quiz in JSON format:
{{
    "title": "Quiz: {module.title}",
    "instructions": "Answer each question. Show your work where applicable.",
    "questions": [
        {{
            "number": 1,
            "question": "The question text",
            "answer": "The correct answer",
            "concept": "Which concept this tests",
            "points": 1,
            "requires_work": true/false
        }}
    ],
    "total_points": {num_questions}
}}

Requirements:
- Cover all lessons proportionally
- Mix of question types (calculation, word problem, conceptual)
- Clear, specific answers
- Include at least 2 real-world application problems"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            answer_key = {
                str(q["number"]): q["answer"]
                for q in content_json.get("questions", [])
            }

            qr_code = self._generate_qr_code()

            # Use first lesson for association (quiz covers multiple)
            material = Material(
                lesson_id=lessons[0].id if lessons else None,
                material_type=MaterialType.QUIZ,
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "question_count": len(content_json.get("questions", []))
            }

    def generate_test(self, module_number: int, subject_id: int = None) -> Optional[dict]:
        """Generate an end-of-module test."""
        num_questions = QUESTIONS_PER_TEST

        with get_session() as session:
            query = session.query(Module).filter(Module.number == module_number)
            if subject_id:
                query = query.filter(Module.subject_id == subject_id)
            module = query.first()
            if not module:
                return None

            all_concepts = []
            for lesson in module.lessons:
                all_concepts.extend(lesson.concepts or [])

            prompt = f"""Generate a comprehensive {num_questions}-question test for pre-algebra.

MODULE: {module.number}. {module.title}
ALL LESSONS: {', '.join(l.title for l in module.lessons)}
ALL CONCEPTS: {', '.join(all_concepts)}
REAL-WORLD APPLICATIONS: {', '.join(module.real_world_applications or [])}

Generate the test in JSON format:
{{
    "title": "Module {module.number} Test: {module.title}",
    "instructions": "Complete all questions. Show all work. You must demonstrate mastery of all concepts.",
    "questions": [
        {{
            "number": 1,
            "question": "The question text",
            "answer": "The correct answer",
            "concept": "Which concept this tests",
            "points": 1,
            "requires_work": true/false
        }}
    ],
    "total_points": {num_questions}
}}

Requirements:
- Comprehensive coverage of ALL concepts
- 30% easy, 50% medium, 20% challenging
- At least 5 real-world application problems
- Include multi-step problems
- Test deep understanding, not just procedures"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            answer_key = {
                str(q["number"]): q["answer"]
                for q in content_json.get("questions", [])
            }

            qr_code = self._generate_qr_code()

            material = Material(
                lesson_id=module.lessons[0].id if module.lessons else None,
                material_type=MaterialType.TEST,
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "question_count": len(content_json.get("questions", []))
            }

    def generate_remediation(self, module_number: int, lesson_number: int, weak_concepts: list[str], num_problems: int = 15) -> Optional[dict]:
        """Generate targeted remediation problems for weak areas."""
        with get_session() as session:
            lesson = (
                session.query(Lesson)
                .join(Module)
                .filter(Module.number == module_number, Lesson.number == lesson_number)
                .first()
            )
            if not lesson:
                return None

            prompt = f"""Generate {num_problems} remediation practice problems targeting specific weak areas.

LESSON: {lesson.title}
WEAK CONCEPTS IDENTIFIED: {', '.join(weak_concepts)}

Generate problems in JSON format:
{{
    "title": "Extra Practice: {lesson.title}",
    "instructions": "These problems focus on concepts that need more practice. Take your time!",
    "problems": [
        {{
            "number": 1,
            "problem": "The problem text",
            "answer": "The correct answer",
            "concept": "Which weak concept this addresses",
            "teaching_note": "Brief explanation of the concept",
            "hint": "A helpful hint"
        }}
    ]
}}

Requirements:
- Focus exclusively on the weak concepts listed
- Start with simpler versions, build up
- Include extra hints and teaching notes
- Make problems approachable but educational"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            answer_key = {
                str(p["number"]): p["answer"]
                for p in content_json.get("problems", [])
            }

            qr_code = self._generate_qr_code()
            material = Material(
                lesson_id=lesson.id,
                material_type=MaterialType.REMEDIATION,
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "problem_count": len(content_json.get("problems", []))
            }

    def generate_diagnostic(self, questions_per_module: int = 4, subject_id: int = None) -> Optional[dict]:
        """Generate a diagnostic assessment covering all modules for a subject.

        The diagnostic tests knowledge across all modules to determine
        which modules the student has already mastered.

        Args:
            questions_per_module: Number of questions per module
            subject_id: Subject to generate diagnostic for (required)
        """
        with get_session() as session:
            # Get subject info
            if subject_id:
                subject = session.query(Subject).filter(Subject.id == subject_id).first()
                modules = (
                    session.query(Module)
                    .filter(Module.subject_id == subject_id)
                    .order_by(Module.number)
                    .all()
                )
            else:
                # Fallback to Pre-Algebra for backwards compatibility
                subject = session.query(Subject).filter(Subject.code == "PREALGEBRA").first()
                modules = (
                    session.query(Module)
                    .filter(Module.subject_id == subject.id)
                    .order_by(Module.number)
                    .all()
                ) if subject else session.query(Module).order_by(Module.number).all()

            if not modules:
                return None

            subject_name = subject.name if subject else "Pre-Algebra"

            # Build module info for the prompt
            module_info = []
            for module in modules:
                lessons = module.lessons
                all_concepts = []
                for lesson in lessons:
                    all_concepts.extend(lesson.concepts or [])

                module_info.append({
                    "number": module.number,
                    "title": module.title,
                    "concepts": all_concepts[:8]  # Limit concepts for prompt size
                })

            modules_text = "\n".join([
                f"Module {m['number']}: {m['title']}\n  Concepts: {', '.join(m['concepts'])}"
                for m in module_info
            ])

            prompt = f"""Generate a diagnostic assessment for {subject_name} with {questions_per_module} questions per module.

MODULES TO COVER:
{modules_text}

Generate the diagnostic in JSON format:
{{
    "title": "{subject_name} Diagnostic Assessment",
    "instructions": "Complete all questions to determine your starting point. Show your work where helpful.",
    "modules": [
        {{
            "module_number": 1,
            "module_title": "Module title",
            "questions": [
                {{
                    "number": 1,
                    "question": "The question text",
                    "answer": "The correct answer",
                    "concept": "Which concept this tests"
                }}
            ]
        }}
    ],
    "total_questions": {questions_per_module * len(modules)}
}}

Requirements:
- {questions_per_module} questions per module, totaling {questions_per_module * len(modules)} questions
- Questions should be at medium difficulty - representative of what mastery looks like
- Include a mix of calculation and word problems
- Each question should clearly test one of the module's key concepts
- Questions should be answerable without a calculator
- Clear, unambiguous answers"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            # Build answer key with module tracking
            answer_key = {}
            question_modules = {}  # Maps question number to module number

            global_q_num = 1
            for module_section in content_json.get("modules", []):
                module_num = module_section.get("module_number")
                for q in module_section.get("questions", []):
                    answer_key[str(global_q_num)] = q["answer"]
                    question_modules[str(global_q_num)] = module_num
                    q["global_number"] = global_q_num
                    global_q_num += 1

            # Store module mapping and subject info in content for grading
            content_json["question_modules"] = question_modules
            content_json["subject_id"] = subject.id if subject else None
            content_json["subject_name"] = subject_name

            qr_code = self._generate_qr_code()

            # Use first module's first lesson for association
            first_lesson = modules[0].lessons[0] if modules[0].lessons else None

            material = Material(
                lesson_id=first_lesson.id if first_lesson else None,
                material_type=MaterialType.DIAGNOSTIC,
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "total_questions": global_q_num - 1,
                "modules_covered": len(modules)
            }

    def generate_mastery_assessment(
        self,
        module_number: int,
        lesson_number: int,
        subject_id: int = None,
        num_questions: int = None
    ) -> Optional[dict]:
        """
        Generate a quick mastery assessment for lesson skipping.

        This is a short assessment (5 questions by default) that a student
        who has been excelling can take to demonstrate mastery and skip ahead.
        """
        num_questions = num_questions or MASTERY_ASSESSMENT_QUESTIONS

        with get_session() as session:
            query = session.query(Lesson).join(Module).filter(
                Module.number == module_number,
                Lesson.number == lesson_number
            )
            if subject_id:
                query = query.filter(Module.subject_id == subject_id)

            lesson = query.first()
            if not lesson:
                return None

            module = lesson.module
            subject = module.subject if module.subject_id else None
            subject_name = subject.name if subject else "Pre-Algebra"

            prompt = f"""Generate a {num_questions}-question mastery assessment for a {subject_name} lesson.

This is a quick assessment to determine if a student can skip this lesson because they already know the material.

MODULE: {module.number}. {module.title}
LESSON: {lesson.number}. {lesson.title}
CONCEPTS: {', '.join(lesson.concepts or [])}

Generate the assessment in JSON format:
{{
    "title": "Mastery Check: {lesson.title}",
    "instructions": "Demonstrate your mastery of this topic. You must get ALL questions correct to skip this lesson.",
    "questions": [
        {{
            "number": 1,
            "question": "The question text",
            "answer": "The correct answer",
            "concept": "Which concept this tests"
        }}
    ]
}}

Requirements:
- Exactly {num_questions} questions covering the key concepts
- Questions should be at medium-to-hard difficulty - representative of true mastery
- Include at least one word problem
- Clear, unambiguous answers
- Cover the most important concepts that prove understanding"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            content_text = response.content[0].text

            try:
                start = content_text.find("{")
                end = content_text.rfind("}") + 1
                content_json = json.loads(content_text[start:end])
            except json.JSONDecodeError:
                return None

            # Build answer key
            answer_key = {
                str(q["number"]): q["answer"]
                for q in content_json.get("questions", [])
            }

            qr_code = self._generate_qr_code()
            material = Material(
                lesson_id=lesson.id,
                material_type=MaterialType.QUIZ,  # Use QUIZ type for mastery assessments
                content_json=content_json,
                answer_key_json=answer_key,
                qr_code=qr_code
            )
            session.add(material)
            session.commit()

            return {
                "material_id": material.id,
                "qr_code": qr_code,
                "content": content_json,
                "question_count": len(content_json.get("questions", [])),
                "is_mastery_check": True
            }
