"""Claude Vision-powered grading for scanned student work."""

import json
from typing import Optional
from datetime import datetime
from anthropic import Anthropic

from ..config import ANTHROPIC_API_KEY, CLAUDE_VISION_MODEL, MASTERY_THRESHOLD, DIAGNOSTIC_MASTERY_THRESHOLD
from ..database import get_session, Submission, Material, Progress, SubmissionStatus, MaterialType
from .scanner import get_image_as_base64, get_image_media_type


class Grader:
    """Grade scanned student work using Claude Vision."""

    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)

    def grade_submission(self, submission_id: int) -> dict:
        """
        Grade a submission using Claude Vision.

        Returns:
            dict with score, results, feedback, and error_patterns
        """
        with get_session() as session:
            submission = session.query(Submission).get(submission_id)
            if not submission:
                return {"error": "Submission not found"}

            if not submission.material:
                return {"error": "No material associated with submission"}

            material = submission.material
            answer_key = material.answer_key_json or {}
            content = material.content_json or {}

            # Get problems/questions text for context
            if material.material_type.value in ["practice", "remediation"]:
                items = content.get("problems", [])
                item_key = "problem"
            else:
                items = content.get("questions", [])
                item_key = "question"

            # Build context for Claude
            problems_context = "\n".join([
                f"{item.get('number', i+1)}. {item.get(item_key, '')}"
                for i, item in enumerate(items)
            ])

            answer_context = "\n".join([
                f"{num}. {answer}"
                for num, answer in answer_key.items()
            ])

            # Read the scanned image
            try:
                image_data = get_image_as_base64(submission.scan_path)
                media_type = get_image_media_type(submission.scan_path)
            except Exception as e:
                return {"error": f"Could not read scan: {e}"}

            # Create grading prompt
            prompt = f"""You are grading a student's handwritten math work. Analyze the scanned image carefully.

PROBLEMS/QUESTIONS:
{problems_context}

CORRECT ANSWERS:
{answer_context}

Instructions:
1. Read each handwritten answer from the scan
2. Compare to the correct answers
3. For math problems, accept equivalent forms (e.g., 1/2 = 0.5)
4. Note any work shown and whether the approach is correct
5. IMPORTANT: If a question has NO answer (blank, empty, unanswered), mark it as is_correct: false with student_answer: "(no answer)"
6. IMPORTANT: If student wrote "?", "help", "please help", "I don't know", "IDK", or similar - these are NOT answers. Mark as is_correct: false with student_answer: "(asked for help)"
7. Rate your confidence in reading each answer: "high" (clear handwriting), "medium" (somewhat unclear), "low" (very hard to read, guessing)

Respond in JSON format:
{{
    "results": [
        {{
            "number": 1,
            "student_answer": "what you read from the scan",
            "correct_answer": "the expected answer",
            "is_correct": true/false,
            "partial_credit": 0-1 (1 = full, 0.5 = half, etc.),
            "reading_confidence": "high/medium/low",
            "work_shown": true/false,
            "work_correct": true/false/null,
            "notes": "observations referencing the EXACT original question - do not make up different numbers"
        }}
    ],
    "error_patterns": [
        {{
            "pattern": "Name of the error pattern (e.g., 'sign errors', 'fraction division')",
            "count": number of occurrences,
            "description": "Brief description"
        }}
    ],
    "overall_notes": "General observations about the student's work",
    "encouragement": "A brief encouraging note for the student"
}}

Be precise in reading handwriting. If something is unclear, note it but make your best interpretation."""

            # Call Claude Vision
            response = self.client.messages.create(
                model=CLAUDE_VISION_MODEL,
                max_tokens=8000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )

            # Parse response
            response_text = response.content[0].text
            try:
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                if start == -1 or end == 0:
                    return {"error": f"No JSON found in response: {response_text[:500]}"}
                json_text = response_text[start:end]
                grading_result = json.loads(json_text)
            except json.JSONDecodeError as e:
                return {"error": f"Could not parse grading response: {e}. Response: {response_text[:500]}"}

            # Calculate score
            results = grading_result.get("results", [])

            # Post-process: ensure blank/empty/help-seeking answers are marked incorrect
            non_answers = [
                "(no answer)", "no answer", "", "blank", "n/a", "none", "-",
                "?", "??", "???", "help", "please help", "i don't know",
                "idk", "i dont know", "don't know", "dont know", "unsure",
                "(asked for help)", "help me", "i need help"
            ]
            needs_review = []

            for r in results:
                student_answer = str(r.get("student_answer", "")).strip().lower()
                if not student_answer or student_answer in non_answers:
                    r["is_correct"] = False
                    r["partial_credit"] = 0
                    if not r.get("student_answer") or r.get("student_answer", "").strip() == "":
                        r["student_answer"] = "(no answer)"
                    elif student_answer in ["?", "??", "???", "help", "please help", "help me", "i need help"]:
                        r["student_answer"] = "(asked for help)"

                # Flag low/medium confidence readings for review
                confidence = r.get("reading_confidence", "high").lower()
                if confidence in ["low", "medium"]:
                    r["needs_review"] = True
                    needs_review.append({
                        "question": r.get("number"),
                        "answer_read": r.get("student_answer"),
                        "confidence": confidence,
                        "marked_correct": r.get("is_correct")
                    })

            total_points = len(answer_key)
            earned_points = sum(
                r.get("partial_credit", 1.0 if r.get("is_correct") else 0)
                for r in results
            )
            score = (earned_points / total_points * 100) if total_points > 0 else 0

            # Update submission
            submission.score = score
            submission.graded_at = datetime.utcnow()
            submission.results_json = results
            submission.feedback_json = {
                "overall_notes": grading_result.get("overall_notes", ""),
                "encouragement": grading_result.get("encouragement", ""),
                "needs_review": needs_review  # Questions with low/medium confidence readings
            }
            submission.error_patterns = grading_result.get("error_patterns", [])

            # Determine status
            if score >= MASTERY_THRESHOLD:
                submission.status = SubmissionStatus.GRADED
            else:
                submission.status = SubmissionStatus.NEEDS_RETRY

            # Handle diagnostic specially
            if material.material_type == MaterialType.DIAGNOSTIC:
                module_scores = self._calculate_module_scores(results, content)
                self._apply_diagnostic_results(session, submission, module_scores)
                session.commit()

                # Generate mini-lessons for areas needing work
                diagnostic_feedback = self.generate_diagnostic_feedback(
                    submission_id, results, module_scores, content
                )

                return {
                    "score": score,
                    "is_mastery": score >= MASTERY_THRESHOLD,
                    "results": results,
                    "module_scores": module_scores,
                    "error_patterns": grading_result.get("error_patterns", []),
                    "feedback": grading_result.get("overall_notes", ""),
                    "encouragement": grading_result.get("encouragement", ""),
                    "diagnostic_feedback": diagnostic_feedback,
                    "needs_review": needs_review  # Questions with uncertain handwriting readings
                }

            # Update progress for non-diagnostic materials
            self._update_progress(session, submission, grading_result.get("error_patterns", []))

            # Update adaptive velocity
            self._update_adaptive_velocity(session, submission, score)

            session.commit()

            return {
                "score": score,
                "is_mastery": score >= MASTERY_THRESHOLD,
                "results": results,
                "error_patterns": grading_result.get("error_patterns", []),
                "feedback": grading_result.get("overall_notes", ""),
                "encouragement": grading_result.get("encouragement", ""),
                "needs_review": needs_review  # Questions with uncertain handwriting readings
            }

    def _calculate_module_scores(self, results: list, content: dict) -> dict:
        """Calculate per-module scores from diagnostic results."""
        question_modules = content.get("question_modules", {})

        # Group results by module
        module_results = {}
        for r in results:
            q_num = str(r.get("number", ""))
            module_num = question_modules.get(q_num)
            if module_num is not None:
                if module_num not in module_results:
                    module_results[module_num] = {"correct": 0, "total": 0}
                module_results[module_num]["total"] += 1
                if r.get("is_correct"):
                    module_results[module_num]["correct"] += 1

        # Calculate percentage for each module
        module_scores = {}
        for module_num, counts in module_results.items():
            if counts["total"] > 0:
                module_scores[module_num] = (counts["correct"] / counts["total"]) * 100
            else:
                module_scores[module_num] = 0

        return module_scores

    def _apply_diagnostic_results(self, session, submission: Submission, module_scores: dict):
        """Apply diagnostic results to mark mastered modules."""
        from ..adaptive.pacing import AdaptivePacer

        pacer = AdaptivePacer()
        pacer.apply_diagnostic_mastery(submission.student_id, module_scores, session)

    def _update_progress(self, session, submission: Submission, error_patterns: list):
        """Update student progress based on grading results."""
        if not submission.material:
            return

        lesson_id = submission.material.lesson_id
        student_id = submission.student_id

        # Get or create progress record
        progress = (
            session.query(Progress)
            .filter(Progress.student_id == student_id, Progress.lesson_id == lesson_id)
            .first()
        )

        if not progress:
            progress = Progress(student_id=student_id, lesson_id=lesson_id)
            session.add(progress)

        # Update based on material type
        material_type = submission.material.material_type.value

        if material_type in ["practice", "remediation"]:
            progress.practice_attempts = (progress.practice_attempts or 0) + 1
            if progress.best_practice_score is None or submission.score > progress.best_practice_score:
                progress.best_practice_score = submission.score

            # Check for mastery
            if submission.score >= MASTERY_THRESHOLD:
                progress.mastered = True
                progress.mastered_at = datetime.utcnow()

        elif material_type == "quiz":
            progress.quiz_attempts = (progress.quiz_attempts or 0) + 1
            if progress.best_quiz_score is None or submission.score > progress.best_quiz_score:
                progress.best_quiz_score = submission.score

        # Accumulate error patterns
        for pattern in error_patterns:
            progress.add_error_pattern(pattern.get("pattern", "unknown"), pattern.get("count", 1))

    def _update_adaptive_velocity(self, session, submission: Submission, score: float):
        """Update student's adaptive learning velocity based on score."""
        if not submission.material or not submission.material.lesson:
            return

        # Get the subject from the lesson's module
        lesson = submission.material.lesson
        module = lesson.module
        if not module or not module.subject_id:
            return

        from ..adaptive.pacing import AdaptivePacer
        pacer = AdaptivePacer()
        pacer.update_velocity(
            student_id=submission.student_id,
            subject_id=module.subject_id,
            score=score,
            session=session
        )

    def generate_diagnostic_feedback(self, submission_id: int, results: list, module_scores: dict, content: dict) -> dict:
        """
        Generate detailed feedback with mini-lessons for diagnostic results.

        Args:
            submission_id: The diagnostic submission ID
            results: List of graded question results
            module_scores: Dict of module_num -> score percentage
            content: The diagnostic content with questions and module mapping

        Returns:
            dict with wrong_answers and mini_lessons for areas needing work
        """
        # Find wrong answers grouped by module
        question_modules = content.get("question_modules", {})
        questions = content.get("questions", [])

        # Build a lookup for question text
        question_text = {q.get("number", i+1): q.get("question", "") for i, q in enumerate(questions)}

        # Group wrong answers by module
        wrong_by_module = {}
        for r in results:
            if not r.get("is_correct"):
                q_num = str(r.get("number", ""))
                module_num = question_modules.get(q_num)
                if module_num is not None:
                    if module_num not in wrong_by_module:
                        wrong_by_module[module_num] = []
                    wrong_by_module[module_num].append({
                        "number": r.get("number"),
                        "question": question_text.get(r.get("number"), ""),
                        "student_answer": r.get("student_answer", ""),
                        "correct_answer": r.get("correct_answer", ""),
                        "notes": r.get("notes", "")
                    })

        if not wrong_by_module:
            return {"wrong_answers": {}, "mini_lessons": {}}

        # Get module titles
        from ..database import get_session, Module
        module_titles = {}
        with get_session() as session:
            for mod_num in wrong_by_module.keys():
                module = session.query(Module).filter(Module.number == mod_num).first()
                if module:
                    module_titles[mod_num] = module.title
                else:
                    module_titles[mod_num] = f"Module {mod_num}"

        # Generate mini-lessons for each struggling module
        mini_lessons = {}

        for mod_num, wrong_answers in wrong_by_module.items():
            module_title = module_titles.get(mod_num, f"Module {mod_num}")
            score = module_scores.get(mod_num, 0)

            # Only generate mini-lessons for modules not mastered
            if score < 100:
                # Build context for Claude
                wrong_context = "\n".join([
                    f"- Question {w['number']}: {w['question']}\n"
                    f"  Student answered: {w['student_answer']}\n"
                    f"  Correct answer: {w['correct_answer']}\n"
                    f"  Notes: {w['notes']}"
                    for w in wrong_answers
                ])

                prompt = f"""A student just took a diagnostic assessment for {module_title} and got these questions wrong:

{wrong_context}

Please provide a brief, encouraging mini-lesson (2-3 paragraphs) that:
1. Explains the key concept(s) the student is struggling with
2. Provides a clear, simple explanation with an example
3. Gives them a tip or strategy to remember

Keep it friendly and encouraging - this is for a pre-algebra student. Format in markdown with headers."""

                try:
                    response = self.client.messages.create(
                        model=CLAUDE_VISION_MODEL,
                        max_tokens=1500,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    mini_lessons[mod_num] = {
                        "title": module_title,
                        "score": score,
                        "lesson": response.content[0].text,
                        "wrong_count": len(wrong_answers)
                    }
                except Exception as e:
                    mini_lessons[mod_num] = {
                        "title": module_title,
                        "score": score,
                        "lesson": f"Review the concepts in {module_title}. Focus on the questions you missed.",
                        "wrong_count": len(wrong_answers),
                        "error": str(e)
                    }

        return {
            "wrong_answers": wrong_by_module,
            "mini_lessons": mini_lessons,
            "module_titles": module_titles
        }

    def grade_manually(self, submission_id: int, results: list[dict]) -> dict:
        """
        Record manual grading results.

        Args:
            submission_id: The submission to grade
            results: List of {number, is_correct, notes} for each question

        Returns:
            dict with score and status
        """
        with get_session() as session:
            submission = session.query(Submission).get(submission_id)
            if not submission:
                return {"error": "Submission not found"}

            material = submission.material
            total_points = len(material.answer_key_json or {})
            correct = sum(1 for r in results if r.get("is_correct", False))
            score = (correct / total_points * 100) if total_points > 0 else 0

            submission.score = score
            submission.graded_at = datetime.utcnow()
            submission.results_json = results
            submission.status = SubmissionStatus.GRADED if score >= MASTERY_THRESHOLD else SubmissionStatus.NEEDS_RETRY

            self._update_progress(session, submission, [])
            session.commit()

            return {
                "score": score,
                "is_mastery": score >= MASTERY_THRESHOLD,
                "correct": correct,
                "total": total_points
            }


def auto_grade_practice(submission_id: int):
    """Auto-grade a practice submission."""
    grader = Grader()
    result = grader.grade_submission(submission_id)

    if "error" in result:
        print(f"Grading error: {result['error']}")
    else:
        print(f"Graded: {result['score']:.1f}% - {'MASTERY!' if result['is_mastery'] else 'Needs retry'}")

    return result
