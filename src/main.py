"""Main CLI entry point for the Adaptive Math Learning System."""

import click
from pathlib import Path

from src.database import init_db, get_session, Student, Subject, StudentSubjectProgress
from src.config import (
    SCANS_FOLDER,
    GENERATED_FOLDER,
    ANTHROPIC_API_KEY,
    STUDENT_NAME,
    validate_config
)


@click.group()
def cli():
    """Pre-Algebra Mastery Learning System CLI."""
    pass


@cli.command()
def init():
    """Initialize the database and create default student."""
    click.echo("Initializing Pre-Algebra Learning System...")

    # Validate config
    issues = validate_config()
    if issues:
        for issue in issues:
            click.echo(f"  Warning: {issue}", err=True)

    # Initialize database
    init_db()
    click.echo("Database initialized with curriculum.")

    # Create default student if needed
    with get_session() as session:
        if not session.query(Student).first():
            student = Student(name=STUDENT_NAME)
            session.add(student)
            session.commit()
            click.echo(f"Created student profile: {STUDENT_NAME}")
        else:
            click.echo(f"Student profile already exists.")

    click.echo(f"\nScans folder: {SCANS_FOLDER}")
    click.echo(f"Generated PDFs: {GENERATED_FOLDER}")
    click.echo("\nReady to start learning!")


@cli.command()
@click.option("--student", "-s", type=str, default=None, help="Student name")
@click.option("--subject", "-j", type=str, default=None, help="Subject code (e.g., PREALGEBRA, 4TH_GRADE)")
def status(student, subject):
    """Show current learning status and recommended next action."""
    from .adaptive.pacing import AdaptivePacer

    init_db()

    # Get student
    with get_session() as session:
        if student:
            student_obj = session.query(Student).filter(Student.name == student).first()
        else:
            student_obj = session.query(Student).first()

        if not student_obj:
            click.echo("No student found. Run 'python -m src.main init' first.")
            return

        student_id = student_obj.id
        student_name = student_obj.name

        # Get subject
        subject_id = None
        subject_name = None
        if subject:
            subject_obj = session.query(Subject).filter(Subject.code == subject.upper()).first()
            if subject_obj:
                subject_id = subject_obj.id
                subject_name = subject_obj.name
            else:
                click.echo(f"Subject '{subject}' not found. Run 'python -m src.main subjects' to see available subjects.")
                return

    pacer = AdaptivePacer()
    status_info = pacer.get_student_status(student_id, subject_id)

    title = subject_name or status_info.get('subject_name', 'Math')
    click.echo(f"\n=== {title} Learning Status ===\n")

    if status_info["status"] == "new":
        click.echo("No student found. Run 'python -m src.main init' first.")
        return

    if status_info["status"] == "complete":
        click.echo(f"Congratulations! All {title} modules completed!")
        click.echo(f"Total lessons mastered: {status_info.get('total_lessons_mastered', 0)}")
        return

    click.echo(f"Student: {status_info.get('student_name', 'Unknown')}")
    click.echo(f"Subject: {status_info.get('subject_name', title)}")
    click.echo(f"Current: Module {status_info.get('current_module', 1)}, Lesson {status_info.get('current_lesson', 1)}")
    click.echo(f"Topic: {status_info.get('current_title', 'Unknown')}")
    click.echo(f"Lessons mastered: {status_info.get('lessons_mastered', 0)}")

    # Show velocity info
    velocity = status_info.get('velocity')
    if velocity:
        velocity_indicator = pacer.get_velocity_indicator(student_id, subject_id)
        click.echo(f"Pace: {velocity_indicator['icon']} {velocity_indicator['description']}")

    click.echo(f"\n{status_info.get('message', '')}")

    # Recommendations
    recommendations = pacer.recommend_next_steps(student_id)
    if recommendations:
        click.echo("\nRecommended actions:")
        for rec in recommendations:
            click.echo(f"  - {rec.get('description', '')}")


@cli.command()
@click.option("--module", "-m", type=int, default=None, help="Module number")
@click.option("--lesson", "-l", type=int, default=None, help="Lesson number")
@click.option("--type", "material_type", type=click.Choice(["lesson", "practice", "quiz", "test"]), default="lesson")
@click.option("--student", "-s", type=str, default=None, help="Student name")
@click.option("--subject", "-j", type=str, default=None, help="Subject code (e.g., PREALGEBRA, 4TH_GRADE)")
def generate(module, lesson, material_type, student, subject):
    """Generate learning materials."""
    from .content.generator import ContentGenerator
    from .pdf.generator import PDFGenerator
    from .adaptive.pacing import AdaptivePacer

    init_db()

    # Get student and subject
    with get_session() as session:
        if student:
            student_obj = session.query(Student).filter(Student.name == student).first()
        else:
            student_obj = session.query(Student).first()

        student_id = student_obj.id if student_obj else None
        student_name = student_obj.name if student_obj else STUDENT_NAME

        subject_id = None
        subject_name = None
        if subject:
            subject_obj = session.query(Subject).filter(Subject.code == subject.upper()).first()
            if subject_obj:
                subject_id = subject_obj.id
                subject_name = subject_obj.name

    # If no module/lesson specified, use current position
    if module is None or lesson is None:
        pacer = AdaptivePacer()
        status = pacer.get_student_status(student_id, subject_id)
        module = module or status.get("current_module", 1)
        lesson = lesson or status.get("current_lesson", 1)
        subject_name = subject_name or status.get("subject_name", "Math")

    click.echo(f"Generating {material_type} for {subject_name or 'Math'} Module {module}, Lesson {lesson}...")

    generator = ContentGenerator()
    pdf_gen = PDFGenerator(student_name=student_name)
    pacer = AdaptivePacer()

    result = None
    pdf_path = None

    if material_type == "lesson":
        result = generator.generate_lesson(module, lesson, subject_id=subject_id)
        if result:
            pdf_path = pdf_gen.generate_lesson_pdf(result["material_id"])

    elif material_type == "practice":
        # Use adaptive problem count and difficulty
        num_problems = pacer.calculate_problem_count(student_id, subject_id) if student_id else None
        difficulty = pacer.get_difficulty_adjustment(student_id, subject_id) if student_id else "standard"

        if num_problems:
            click.echo(f"Adaptive settings: {num_problems} problems, {difficulty} difficulty")

        result = generator.generate_practice(
            module, lesson,
            num_problems=num_problems,
            difficulty=difficulty,
            subject_id=subject_id
        )
        if result:
            pdf_path = pdf_gen.generate_practice_pdf(result["material_id"])

    elif material_type == "quiz":
        result = generator.generate_quiz(module)
        if result:
            pdf_path = pdf_gen.generate_quiz_pdf(result["material_id"])

    elif material_type == "test":
        result = generator.generate_test(module)
        if result:
            pdf_path = pdf_gen.generate_test_pdf(result["material_id"])

    if result:
        click.echo(f"\nGenerated successfully!")
        click.echo(f"QR Code: {result.get('qr_code', 'N/A')}")
        click.echo(f"PDF: {pdf_path}")

        # Auto-copy to Claude Projects folder if configured
        from .config import CLAUDE_PROJECTS_DIR
        if CLAUDE_PROJECTS_DIR and pdf_path:
            import shutil
            from pathlib import Path
            dest_dir = Path(CLAUDE_PROJECTS_DIR)
            if dest_dir.exists():
                dest_path = dest_dir / Path(pdf_path).name
                shutil.copy2(pdf_path, dest_path)
                click.echo(f"Copied to: {dest_path}")

        click.echo("\nPrint this PDF and complete the work on paper!")
    else:
        click.echo("Failed to generate. Check your API key and try again.", err=True)


@cli.command()
@click.option("--type", "submission_type", type=click.Choice(["all", "practice", "quiz", "test"]), default="all")
def pending(submission_type):
    """List pending submissions waiting for grading."""
    from .grading.scanner import get_pending_submissions

    init_db()

    type_filter = None if submission_type == "all" else submission_type
    submissions = get_pending_submissions(type_filter)

    if not submissions:
        click.echo("No pending submissions.")
        return

    click.echo(f"\n=== Pending Submissions ({len(submissions)}) ===\n")

    for sub in submissions:
        click.echo(f"ID: {sub['id']}")
        click.echo(f"  Type: {sub['material_type']}")
        click.echo(f"  QR: {sub['qr_code'] or 'Unknown'}")
        click.echo(f"  Scan: {sub['scan_path']}")
        click.echo()


@cli.command()
@click.option("--id", "submission_id", type=int, help="Specific submission ID to grade")
@click.option("--all", "grade_all", is_flag=True, help="Grade all pending practice submissions")
def grade(submission_id, grade_all):
    """Grade pending submissions using Claude Vision."""
    from .grading.scanner import get_pending_submissions
    from .grading.grader import Grader, auto_grade_practice
    from .grading.feedback import generate_feedback

    init_db()

    if submission_id:
        # Grade specific submission
        click.echo(f"Grading submission {submission_id}...")
        grader = Grader()
        result = grader.grade_submission(submission_id)

        if "error" in result:
            click.echo(f"Error: {result['error']}", err=True)
        else:
            mastery = "MASTERY!" if result.get("is_mastery") else "Needs more practice"
            click.echo(f"Score: {result['score']:.1f}% - {mastery}")

            # Generate feedback
            feedback_path = generate_feedback(submission_id)
            if feedback_path:
                click.echo(f"Feedback PDF: {feedback_path}")

    elif grade_all:
        # Grade all pending practice submissions
        submissions = get_pending_submissions("practice")

        if not submissions:
            click.echo("No pending practice submissions to grade.")
            return

        click.echo(f"Grading {len(submissions)} practice submission(s)...\n")

        for sub in submissions:
            click.echo(f"Grading {sub['id']}...")
            result = auto_grade_practice(sub["id"])

            if "error" not in result:
                generate_feedback(sub["id"])

        click.echo("\nAll practice submissions graded!")

    else:
        click.echo("Specify --id <submission_id> or --all to grade submissions.")


@cli.command()
def watch():
    """Watch the scans folder and auto-grade practice submissions."""
    from .grading.scanner import ScanWatcher
    from .grading.grader import auto_grade_practice

    init_db()

    click.echo(f"Watching for scans in: {SCANS_FOLDER}")
    click.echo("Press Ctrl+C to stop.\n")

    def on_practice(submission_id):
        click.echo(f"Auto-grading practice submission {submission_id}...")
        auto_grade_practice(submission_id)

    def on_assessment(submission_id):
        click.echo(f"Assessment submission {submission_id} queued for manual grading.")

    watcher = ScanWatcher(
        on_practice_scan=on_practice,
        on_assessment_scan=on_assessment
    )

    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped watching.")


@cli.command()
def dashboard():
    """Launch the web dashboard."""
    import subprocess
    import sys

    dashboard_path = Path(__file__).parent / "web" / "dashboard.py"

    click.echo("Launching web dashboard...")
    click.echo("Open http://localhost:8501 in your browser")

    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


@cli.command()
@click.option("--limit", "-n", default=10, help="Number of results to show")
def history(limit):
    """View grading history and results."""
    from .database import Submission, Material, SubmissionStatus

    init_db()

    with get_session() as session:
        submissions = (
            session.query(Submission)
            .filter(Submission.score.isnot(None))
            .order_by(Submission.graded_at.desc())
            .limit(limit)
            .all()
        )

        if not submissions:
            click.echo("No graded submissions yet.")
            return

        click.echo(f"\n=== Grading History (Last {len(submissions)}) ===\n")

        for sub in submissions:
            material = sub.material
            if not material:
                continue

            # Determine status
            if sub.score >= 100:
                status = click.style("MASTERY", fg="green", bold=True)
            elif sub.score >= 80:
                status = click.style("GOOD", fg="yellow")
            else:
                status = click.style("NEEDS WORK", fg="red")

            lesson = material.lesson
            module = lesson.module if lesson else None

            click.echo(f"Module {module.number if module else '?'}, Lesson {lesson.number if lesson else '?'}: {lesson.title if lesson else 'Unknown'}")
            click.echo(f"  Type: {material.material_type.value.upper()}")
            click.echo(f"  Score: {sub.score:.0f}% - {status}")
            click.echo(f"  Date: {sub.graded_at.strftime('%Y-%m-%d %H:%M') if sub.graded_at else 'N/A'}")

            # Show error patterns if any
            if sub.error_patterns and sub.score < 100:
                patterns = [p.get('pattern', '') for p in sub.error_patterns[:3]]
                if patterns:
                    click.echo(f"  Areas to review: {', '.join(patterns)}")

            click.echo()


@cli.command()
@click.option("--subject", "-j", type=str, default=None, help="Subject code (e.g., PREALGEBRA, 4TH_GRADE)")
def curriculum(subject):
    """View the curriculum for a subject."""
    from .database import Module

    init_db()

    with get_session() as session:
        # Get subject
        subject_obj = None
        if subject:
            subject_obj = session.query(Subject).filter(Subject.code == subject.upper()).first()
            if not subject_obj:
                click.echo(f"Subject '{subject}' not found.", err=True)
                click.echo("Available subjects:")
                for s in session.query(Subject).all():
                    click.echo(f"  - {s.code}: {s.name}")
                return
        else:
            # Default to first subject
            subject_obj = session.query(Subject).order_by(Subject.order).first()

        if not subject_obj:
            click.echo("No subjects found. Run 'python -m src.main init' to load curricula.")
            return

        click.echo("\n" + "=" * 60)
        click.echo(f"{subject_obj.name.upper()} CURRICULUM")
        click.echo("=" * 60)
        if subject_obj.description:
            click.echo(f"\n{subject_obj.description}")

        modules = (
            session.query(Module)
            .filter(Module.subject_id == subject_obj.id)
            .order_by(Module.number)
            .all()
        )

        for module in modules:
            click.echo(f"\nMODULE {module.number}: {module.title}")
            click.echo(f"  {module.description}")
            apps = module.real_world_applications or []
            if apps:
                click.echo(f"  Real-world: {', '.join(apps[:2])}...")
            click.echo("  Lessons:")
            for lesson in module.lessons:
                click.echo(f"    {lesson.number}. {lesson.title}")


@cli.command()
@click.option("--questions", "-q", type=int, default=4, help="Questions per module (default: 4)")
def diagnostic(questions):
    """Generate a diagnostic assessment to evaluate current knowledge."""
    from .content.generator import ContentGenerator
    from .pdf.generator import PDFGenerator
    from .adaptive.pacing import AdaptivePacer

    init_db()

    # Check if diagnostic already taken
    pacer = AdaptivePacer()
    if pacer.has_taken_diagnostic():
        results = pacer.get_diagnostic_results()
        if results:
            click.echo("\n=== Previous Diagnostic Results ===\n")
            click.echo(f"Overall Score: {results['overall_score']:.1f}%")
            click.echo(f"Graded: {results['graded_at'].strftime('%Y-%m-%d %H:%M') if results['graded_at'] else 'N/A'}")

            click.echo("\nModule Scores:")
            for mod_num in sorted(results['module_scores'].keys()):
                data = results['module_scores'][mod_num]
                title = results['module_titles'].get(mod_num, f"Module {mod_num}")
                status = click.style("MASTERED", fg="green") if data['mastered'] else click.style("NEEDS STUDY", fg="yellow")
                click.echo(f"  Module {mod_num} ({title}): {data['score']:.0f}% ({data['correct']}/{data['total']}) - {status}")

            click.echo(f"\nModules Mastered: {len(results['modules_mastered'])}")
            click.echo(f"Modules to Study: {len(results['modules_to_study'])}")

            if not click.confirm("\nGenerate a new diagnostic assessment?"):
                return

    click.echo(f"Generating diagnostic assessment ({questions} questions per module)...")

    generator = ContentGenerator()
    result = generator.generate_diagnostic(questions_per_module=questions)

    if not result:
        click.echo("Failed to generate diagnostic. Check your API key.", err=True)
        return

    click.echo(f"Generated {result['total_questions']} questions across {result['modules_covered']} modules")

    # Generate PDF
    pdf_gen = PDFGenerator()
    pdf_path = pdf_gen.generate_diagnostic_pdf(result["material_id"])

    if pdf_path:
        click.echo(f"\nDiagnostic Assessment generated!")
        click.echo(f"QR Code: {result.get('qr_code', 'N/A')}")
        click.echo(f"PDF: {pdf_path}")

        # Auto-copy to Claude Projects folder if configured
        from .config import CLAUDE_PROJECTS_DIR
        if CLAUDE_PROJECTS_DIR and pdf_path:
            import shutil
            from pathlib import Path
            dest_dir = Path(CLAUDE_PROJECTS_DIR)
            if dest_dir.exists():
                dest_path = dest_dir / Path(pdf_path).name
                shutil.copy2(pdf_path, dest_path)
                click.echo(f"Copied to: {dest_path}")

        click.echo("\nPrint this PDF and complete all questions on paper.")
        click.echo("Then scan and upload through the dashboard to determine your starting point!")
    else:
        click.echo("Failed to generate PDF.", err=True)


@cli.command()
def subjects():
    """List all available subjects and enrollments."""
    from .content.curriculum_loader import get_available_subjects, get_student_enrollments

    init_db()

    click.echo("\n=== Available Subjects ===\n")

    available = get_available_subjects()
    if not available:
        click.echo("No subjects found. Run 'python -m src.main init' to load curricula.")
        return

    for subj in available:
        grade = f"Grade {subj['grade_level']}" if subj.get('grade_level') else ""
        modules = f"{subj['module_count']} modules" if subj.get('module_count') else ""
        click.echo(f"  {subj['code']}: {subj['name']} ({grade}, {modules})")
        if subj.get('description'):
            click.echo(f"    {subj['description'][:70]}...")

    # Show student enrollments
    click.echo("\n=== Student Enrollments ===\n")

    with get_session() as session:
        students = session.query(Student).all()

        for student in students:
            enrollments = get_student_enrollments(student.id)
            if enrollments:
                click.echo(f"  {student.name}:")
                for e in enrollments:
                    velocity = f"velocity={e['velocity_score']:.1f}" if e.get('velocity_score') else ""
                    status_str = e.get('status', 'active')
                    click.echo(f"    - {e['subject_name']} ({status_str}, {velocity})")
            else:
                click.echo(f"  {student.name}: Not enrolled in any subjects")


@cli.command()
@click.argument("student_name")
@click.argument("subject_code")
def enroll(student_name, subject_code):
    """Enroll a student in a subject.

    Example: python -m src.main enroll Henry 4TH_GRADE
    """
    from .content.curriculum_loader import enroll_student_in_subject

    init_db()

    with get_session() as session:
        # Find student
        student = session.query(Student).filter(Student.name == student_name).first()
        if not student:
            click.echo(f"Student '{student_name}' not found.", err=True)
            click.echo("Available students:")
            for s in session.query(Student).all():
                click.echo(f"  - {s.name}")
            return

        # Find subject
        subject = session.query(Subject).filter(Subject.code == subject_code.upper()).first()
        if not subject:
            click.echo(f"Subject '{subject_code}' not found.", err=True)
            click.echo("Available subjects:")
            for s in session.query(Subject).all():
                click.echo(f"  - {s.code}: {s.name}")
            return

    # Enroll
    result = enroll_student_in_subject(student.id, subject.id)

    if result["status"] == "enrolled":
        click.echo(f"\n✓ Enrolled {student_name} in {subject.name}!")
        click.echo(f"  Starting at Module {result.get('starting_module', 1)}, Lesson {result.get('starting_lesson', 1)}")
    elif result["status"] == "already_enrolled":
        click.echo(f"{student_name} is already enrolled in {subject.name}.")
    else:
        click.echo(f"Enrollment failed: {result.get('message', 'Unknown error')}", err=True)


@cli.command()
@click.option("--student", "-s", type=str, default=None, help="Student name")
@click.option("--subject", "-j", type=str, default=None, help="Subject code")
def progress(student, subject):
    """Show detailed progress summary."""
    from .adaptive.pacing import AdaptivePacer

    init_db()

    # Get student
    with get_session() as session:
        if student:
            student_obj = session.query(Student).filter(Student.name == student).first()
        else:
            student_obj = session.query(Student).first()

        if not student_obj:
            click.echo("No student found.", err=True)
            return

        student_id = student_obj.id
        student_name = student_obj.name

        # Get subject
        subject_id = None
        subject_name = None
        if subject:
            subject_obj = session.query(Subject).filter(Subject.code == subject.upper()).first()
            if subject_obj:
                subject_id = subject_obj.id
                subject_name = subject_obj.name

    pacer = AdaptivePacer()
    summary = pacer.get_progress_summary(student_id, subject_id)

    if "error" in summary:
        click.echo(summary["error"], err=True)
        return

    subject_display = subject_name or summary.get('subject_name', 'Math')
    click.echo(f"\n=== Progress Report: {student_name} - {subject_display} ===\n")

    # Show velocity
    velocity = pacer.get_velocity_indicator(student_id, subject_id)
    click.echo(f"Learning Pace: {velocity['icon']} {velocity['description']}")

    overall = summary.get("overall", {})
    click.echo(f"\nOverall: {overall.get('percent_complete', 0):.1f}% complete")
    click.echo(f"Lessons mastered: {overall.get('lessons_mastered', 0)} / {overall.get('total_lessons', 0)}")
    click.echo(f"Total submissions: {overall.get('total_submissions', 0)}")
    click.echo(f"Average score: {overall.get('average_score', 0):.1f}%")
    click.echo(f"Mastery rate: {overall.get('mastery_rate', 0):.1f}%")

    click.echo("\nModule Progress:")
    for mod in summary.get("modules", []):
        status = "COMPLETE" if mod.get("is_complete") else f"{mod.get('lessons_mastered', 0)}/{mod.get('total_lessons', 0)}"
        bar_len = int(mod.get("percent_complete", 0) / 5)
        bar = "#" * bar_len + "-" * (20 - bar_len)
        click.echo(f"  Module {mod['module_number']}: [{bar}] {status}")


if __name__ == "__main__":
    cli()
