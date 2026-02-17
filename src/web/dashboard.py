"""Streamlit web dashboard for Learnfast."""

import shutil
import streamlit as st
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.database import init_db, get_session, Student, Subject, StudentSubjectProgress, Material, Submission, Progress, Module, Lesson
from src.database.models import MaterialType, SubmissionStatus
from src.content.generator import ContentGenerator
from src.content.curriculum import get_all_modules, get_module, get_lesson
from src.content.curriculum_loader import get_available_subjects, get_student_enrollments, enroll_student_in_subject
from src.pdf.generator import PDFGenerator
from src.grading.scanner import get_pending_submissions
from src.grading.grader import Grader
from src.grading.feedback import generate_feedback, generate_diagnostic_feedback
from src.adaptive.pacing import AdaptivePacer
from src.adaptive.learning_state import LearningState, LearningStateEngine
from src.adaptive.assignment_controller import AssignmentController
from src.config import STUDENT_NAME, SCANS_FOLDER, GENERATED_FOLDER, ANTHROPIC_API_KEY, STUDENT_COLORS


def init_session_state():
    """Initialize session state variables."""
    if "initialized" not in st.session_state:
        init_db()
        st.session_state.initialized = True

        # Create default student if none exists
        with get_session() as session:
            if not session.query(Student).first():
                student = Student(name=STUDENT_NAME)
                session.add(student)
                session.commit()

    # Initialize selected student
    if "selected_student_id" not in st.session_state:
        with get_session() as session:
            first_student = session.query(Student).first()
            if first_student:
                st.session_state.selected_student_id = first_student.id
                st.session_state.selected_student_name = first_student.name

    # Initialize selected subject
    if "selected_subject_id" not in st.session_state:
        st.session_state.selected_subject_id = None
        st.session_state.selected_subject_name = None


def get_current_student():
    """Get the currently selected student."""
    with get_session() as session:
        student_id = st.session_state.get("selected_student_id")
        if student_id:
            student = session.get(Student, student_id)
            if student:
                return {"id": student.id, "name": student.name}
        # Fallback to first student
        student = session.query(Student).first()
        if student:
            return {"id": student.id, "name": student.name}
        return None


def get_student_color(student_name: str) -> str:
    """Get the accent color for a student."""
    return STUDENT_COLORS.get(student_name, STUDENT_COLORS.get("default", "#6B7280"))


def main():
    """Main dashboard application."""
    st.set_page_config(
        page_title="Learnfast",
        page_icon="📐",
        layout="wide"
    )

    init_session_state()

    # Student selector in sidebar
    st.sidebar.title("Student")

    with get_session() as session:
        students = session.query(Student).order_by(Student.name).all()
        student_options = {s.name: s.id for s in students}

    # Add "Add New Student" option
    student_names = list(student_options.keys()) + ["➕ Add New Student"]

    # Find current selection index
    current_name = st.session_state.get("selected_student_name", student_names[0] if student_names else None)
    current_index = student_names.index(current_name) if current_name in student_names else 0

    selected = st.sidebar.selectbox(
        "Select Student",
        student_names,
        index=current_index,
        key="student_selector"
    )

    # Handle new student creation
    if selected == "➕ Add New Student":
        new_name = st.sidebar.text_input("Enter student name:")
        if st.sidebar.button("Create Student", type="primary"):
            if new_name and new_name.strip():
                with get_session() as session:
                    # Check if name already exists
                    existing = session.query(Student).filter(Student.name == new_name.strip()).first()
                    if existing:
                        st.sidebar.error("A student with this name already exists.")
                    else:
                        new_student = Student(name=new_name.strip())
                        session.add(new_student)
                        session.commit()
                        st.session_state.selected_student_id = new_student.id
                        st.session_state.selected_student_name = new_student.name
                        st.rerun()
            else:
                st.sidebar.error("Please enter a name.")
        # Don't proceed with rest of page while adding student
        return
    else:
        # Update selected student
        if selected in student_options:
            st.session_state.selected_student_id = student_options[selected]
            st.session_state.selected_student_name = selected

    # Get current student info and color
    current_student = get_current_student()
    if not current_student:
        st.error("No student selected. Please create a student first.")
        return

    student_color = get_student_color(current_student["name"])

    # Apply student-specific styling
    st.markdown(f"""
        <style>
        .stApp > header {{
            background-color: {student_color}20;
        }}
        div[data-testid="stSidebarContent"] {{
            border-top: 4px solid {student_color};
        }}
        .student-banner {{
            background-color: {student_color}30;
            padding: 10px 15px;
            border-radius: 8px;
            border-left: 4px solid {student_color};
            margin-bottom: 15px;
        }}
        </style>
    """, unsafe_allow_html=True)

    # Show current student banner
    st.sidebar.markdown(f"""
        <div class="student-banner">
            <strong>📚 {current_student['name']}'s Learning</strong>
        </div>
    """, unsafe_allow_html=True)

    # Subject selector
    st.sidebar.title("Subject")

    # Get enrolled subjects for this student
    enrollments = get_student_enrollments(current_student["id"])

    if enrollments:
        subject_options = {e["subject_name"]: e["subject_id"] for e in enrollments}
        subject_names = list(subject_options.keys())

        # Add option to enroll in new subject
        subject_names.append("➕ Enroll in New Subject")

        # Find current selection - prefer most recently accessed subject
        current_subject_name = st.session_state.get("selected_subject_name")
        if current_subject_name not in subject_names:
            # Find most recently accessed subject for this student
            with get_session() as session:
                from datetime import datetime
                recent_progress = (
                    session.query(StudentSubjectProgress)
                    .filter(StudentSubjectProgress.student_id == current_student["id"])
                    .order_by(StudentSubjectProgress.last_accessed_at.desc().nulls_last())
                    .first()
                )
                if recent_progress:
                    recent_subject = session.query(Subject).filter(Subject.id == recent_progress.subject_id).first()
                    if recent_subject and recent_subject.name in subject_names:
                        current_subject_name = recent_subject.name
                        st.session_state.selected_subject_id = recent_subject.id
                        st.session_state.selected_subject_name = recent_subject.name

            # Fallback to first subject if still not set
            if current_subject_name not in subject_names:
                current_subject_name = subject_names[0] if subject_names else None

        current_subject_index = subject_names.index(current_subject_name) if current_subject_name in subject_names else 0

        selected_subject = st.sidebar.selectbox(
            "Select Subject",
            subject_names,
            index=current_subject_index,
            key="subject_selector"
        )

        if selected_subject == "➕ Enroll in New Subject":
            available_subjects = get_available_subjects()
            enrolled_ids = {e["subject_id"] for e in enrollments}
            unenrolled = [s for s in available_subjects if s["id"] not in enrolled_ids]

            if unenrolled:
                new_subject_options = {s["name"]: s["id"] for s in unenrolled}
                new_subject = st.sidebar.selectbox(
                    "Choose a subject",
                    list(new_subject_options.keys()),
                    key="new_subject_selector"
                )
                if st.sidebar.button("Enroll", type="primary"):
                    result = enroll_student_in_subject(
                        current_student["id"],
                        new_subject_options[new_subject]
                    )
                    if result["status"] == "enrolled":
                        st.sidebar.success(f"Enrolled in {new_subject}!")
                        st.session_state.selected_subject_id = new_subject_options[new_subject]
                        st.session_state.selected_subject_name = new_subject
                        st.rerun()
                    else:
                        st.sidebar.error(result.get("message", "Enrollment failed"))
            else:
                st.sidebar.info("Already enrolled in all available subjects!")
        else:
            # Update selected subject
            if selected_subject in subject_options:
                new_subject_id = subject_options[selected_subject]
                st.session_state.selected_subject_id = new_subject_id
                st.session_state.selected_subject_name = selected_subject

                # Update last_accessed_at for this subject
                try:
                    with get_session() as session:
                        from datetime import datetime, timezone
                        progress = (
                            session.query(StudentSubjectProgress)
                            .filter(
                                StudentSubjectProgress.student_id == current_student["id"],
                                StudentSubjectProgress.subject_id == new_subject_id
                            )
                            .first()
                        )
                        if progress:
                            progress.last_accessed_at = datetime.now(timezone.utc)
                            session.commit()
                except Exception:
                    # Non-critical update, don't crash if it fails
                    pass

        # Show velocity indicator for selected subject
        if st.session_state.get("selected_subject_id"):
            pacer = AdaptivePacer()
            velocity = pacer.get_velocity_indicator(
                current_student["id"],
                st.session_state.selected_subject_id
            )
            st.sidebar.markdown(f"**Pace:** {velocity['icon']} {velocity['label'].title()}")
            st.sidebar.caption(velocity['description'])

    else:
        # No enrollments - prompt to enroll
        st.sidebar.info("Not enrolled in any subjects yet.")
        available_subjects = get_available_subjects()
        if available_subjects:
            subject_options = {s["name"]: s["id"] for s in available_subjects}
            new_subject = st.sidebar.selectbox(
                "Choose a subject to start",
                list(subject_options.keys()),
                key="first_subject_selector"
            )
            if st.sidebar.button("Start Learning", type="primary"):
                result = enroll_student_in_subject(
                    current_student["id"],
                    subject_options[new_subject]
                )
                if result["status"] == "enrolled":
                    st.sidebar.success(f"Enrolled in {new_subject}!")
                    st.session_state.selected_subject_id = subject_options[new_subject]
                    st.session_state.selected_subject_name = new_subject
                    st.rerun()

    st.sidebar.divider()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to",
        ["Today's Assignment", "Progress", "Upload Work", "Work History", "Disputes", "Settings"]
    )

    if page == "Today's Assignment":
        show_todays_assignment()
    elif page == "Progress":
        show_progress()
    elif page == "Upload Work":
        show_pending()
    elif page == "Work History":
        show_feedback_history()
    elif page == "Disputes":
        show_disputes()
    elif page == "Settings":
        show_settings()


def show_todays_assignment():
    """Show today's assignment - the single-focus teacher-directed view."""
    current_student = get_current_student()
    student_id = current_student["id"]
    student_name = current_student["name"]
    subject_id = st.session_state.get("selected_subject_id")
    subject_name = st.session_state.get("selected_subject_name", "Math")

    if not subject_id:
        st.warning("Please select a subject from the sidebar to begin.")
        return

    # Initialize assignment controller
    controller = AssignmentController()
    assignment = controller.get_assignment(student_id, subject_id)
    ui_config = controller.get_state_ui_config(assignment.state)

    # Get velocity indicator
    pacer = AdaptivePacer()
    velocity = pacer.get_velocity_indicator(student_id, subject_id)

    # Main assignment card
    st.markdown(f"""
        <div style="text-align: center; padding: 10px; background-color: #f0f2f6; border-radius: 10px; margin-bottom: 20px;">
            <h2 style="margin: 0;">TODAY'S ASSIGNMENT - {student_name}</h2>
            <p style="margin: 5px 0; color: #666;">{subject_name}</p>
        </div>
    """, unsafe_allow_html=True)

    # Phase indicator
    phase = ui_config.get("phase", "LEARNING")
    phase_color = _get_phase_color(phase)

    st.markdown(f"""
        <div style="background-color: {phase_color}20; padding: 15px; border-radius: 8px; border-left: 4px solid {phase_color}; margin-bottom: 20px;">
            <h4 style="margin: 0; color: {phase_color};">{phase} PHASE</h4>
        </div>
    """, unsafe_allow_html=True)

    # Module and lesson info
    if assignment.module_number and assignment.lesson_number:
        st.markdown(f"**Module {assignment.module_number}:** {assignment.module_title}")
        st.markdown(f"**Lesson {assignment.lesson_number}:** {assignment.lesson_title}")
    elif assignment.module_number:
        st.markdown(f"**Module {assignment.module_number}:** {assignment.module_title}")

    st.divider()

    # Assignment title and instructions
    st.subheader(assignment.title)
    st.write(assignment.instructions)

    # Encouragement message
    if assignment.encouragement:
        st.info(assignment.encouragement)

    st.divider()

    # Action buttons based on state
    _render_assignment_actions(
        assignment=assignment,
        controller=controller,
        student_id=student_id,
        subject_id=subject_id,
        student_name=student_name,
        ui_config=ui_config
    )

    # Progress footer
    st.divider()
    _render_progress_footer(assignment, velocity, subject_id, student_id)


def _get_phase_color(phase: str) -> str:
    """Get color for a learning phase."""
    colors = {
        "ASSESSMENT": "#3B82F6",  # Blue
        "LEARNING": "#10B981",    # Green
        "PRACTICE": "#F59E0B",    # Yellow/Orange
        "REVIEW": "#F97316",      # Orange
        "TEST": "#8B5CF6",        # Purple
        "GRADING": "#6B7280",     # Gray
        "COMPLETE": "#10B981",    # Green
        "MODULE COMPLETE": "#EAB308",  # Gold
        "FINISHED!": "#EAB308",   # Gold
    }
    return colors.get(phase, "#6B7280")


def _render_assignment_actions(
    assignment,
    controller: AssignmentController,
    student_id: int,
    subject_id: int,
    student_name: str,
    ui_config: dict
):
    """Render the appropriate action buttons for the current assignment."""
    state = assignment.state

    # Handle generation states
    if assignment.action_type == "generate":
        if st.button(assignment.action_label, type="primary", use_container_width=True):
            with st.spinner(f"Generating your {_get_material_type_name(state)}..."):
                result = controller.generate_material_for_assignment(
                    assignment, student_id, subject_id, student_name
                )
                if result:
                    st.session_state.generated_material = result
                    st.success("Generated successfully!")
                    st.rerun()
                else:
                    st.error("Failed to generate material. Please check your API key.")

        # Show download if just generated
        if st.session_state.get("generated_material"):
            result = st.session_state.generated_material
            file_path = result.get("file_path")
            if file_path and Path(file_path).exists():
                with open(file_path, "rb") as f:
                    st.download_button(
                        label="Download PDF",
                        data=f.read(),
                        file_name=Path(file_path).name,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                st.caption(f"QR Code: {result.get('qr_code', 'N/A')}")
        return

    # Handle download states
    if assignment.action_type == "download" and assignment.material_id:
        download_info = controller.get_material_download_info(assignment.material_id)
        if download_info and download_info.get("exists"):
            with open(download_info["file_path"], "rb") as f:
                st.download_button(
                    label=assignment.action_label,
                    data=f.read(),
                    file_name=download_info["filename"],
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            st.caption(f"QR Code: {download_info.get('qr_code', 'N/A')}")

            # For lesson materials, show "I've Read the Lesson" button
            if state == LearningState.LEARNING_LESSON:
                st.write("")  # Spacer
                if st.button("I've Read the Lesson - Ready for Practice", type="secondary", use_container_width=True):
                    controller.mark_lesson_complete(student_id, assignment.lesson_id)
                    st.session_state.generated_material = None  # Clear any cached material
                    st.success("Great! Let's generate your practice problems.")
                    st.rerun()
        else:
            # Material doesn't exist, offer to regenerate
            st.warning("Material file not found. Let's generate it again.")
            if st.button("Regenerate " + _get_material_type_name(state), type="primary"):
                with st.spinner("Regenerating..."):
                    result = controller.generate_material_for_assignment(
                        assignment, student_id, subject_id, student_name
                    )
                    if result:
                        st.session_state.generated_material = result
                        st.rerun()
        return

    # Handle upload states
    if assignment.action_type == "upload":
        st.info("Upload your completed work using the 'Upload Work' page in the sidebar.")
        if st.button("Go to Upload Work", use_container_width=True):
            st.session_state.page = "Upload Work"
            st.rerun()
        return

    # Handle continue states (mastered lesson, module complete)
    if assignment.action_type == "continue":
        if state == LearningState.MASTERED_LESSON:
            if st.button(assignment.action_label, type="primary", use_container_width=True):
                controller.advance_student(student_id, subject_id)
                st.session_state.generated_material = None
                st.rerun()

        elif state == LearningState.MODULE_COMPLETE:
            st.balloons()
            if st.button(assignment.action_label, type="primary", use_container_width=True):
                controller.advance_student(student_id, subject_id)
                st.session_state.generated_material = None
                st.rerun()

        elif state == LearningState.SUBJECT_COMPLETE:
            st.balloons()
            st.success("Congratulations on completing the entire subject!")
        return

    # Handle wait states
    if assignment.action_type == "wait":
        st.info("Please wait while we prepare your next assignment.")


def _get_material_type_name(state: LearningState) -> str:
    """Get a friendly name for the material type based on state."""
    names = {
        LearningState.NEEDS_DIAGNOSTIC: "diagnostic assessment",
        LearningState.LEARNING_LESSON: "lesson",
        LearningState.PRACTICE_READY: "practice problems",
        LearningState.PRACTICING: "practice problems",
        LearningState.NEEDS_REMEDIATION: "extra practice",
        LearningState.REMEDIATING: "extra practice",
        LearningState.TEST_READY: "module test",
        LearningState.TESTING: "module test",
    }
    return names.get(state, "material")


def _render_progress_footer(assignment, velocity: dict, subject_id: int, student_id: int):
    """Render the progress footer with progress bar and pace indicator."""
    col1, col2 = st.columns([3, 1])

    with col1:
        # Progress bar
        progress_pct = assignment.progress_percent / 100
        st.progress(progress_pct)

        # Position info
        if assignment.module_number:
            pacer = AdaptivePacer()
            summary = pacer.get_progress_summary(student_id, subject_id)
            total_modules = len(summary.get("modules", []))

            st.caption(
                f"Module {assignment.module_number}/{total_modules} | "
                f"Lesson {assignment.lesson_number or '?'} | "
                f"{assignment.progress_percent:.0f}% complete"
            )
        else:
            st.caption(f"{assignment.progress_percent:.0f}% complete")

    with col2:
        # Pace indicator
        st.markdown(f"**Pace:** {velocity['icon']} {velocity['label'].title()}")


def show_home():
    """Legacy home page - redirects to today's assignment."""
    show_todays_assignment()


def show_progress():
    """Show progress tracking page."""
    current_student = get_current_student()
    student_id = current_student["id"]
    student_name = current_student["name"]
    subject_id = st.session_state.get("selected_subject_id")
    subject_name = st.session_state.get("selected_subject_name", "Math")

    st.title(f"Progress - {student_name} - {subject_name}")

    pacer = AdaptivePacer()
    summary = pacer.get_progress_summary(student_id, subject_id)

    if "error" in summary:
        st.error(summary["error"])
        return

    # Check for diagnostic results
    diagnostic_results = pacer.get_diagnostic_results(student_id) if pacer.has_taken_diagnostic(student_id) else None

    if diagnostic_results:
        st.info(f"Diagnostic taken - {len(diagnostic_results['modules_mastered'])} module(s) mastered via diagnostic")

    # Show velocity indicator
    velocity = pacer.get_velocity_indicator(student_id, subject_id)
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"### {velocity['icon']}")
    with col2:
        st.write(f"**Learning Pace:** {velocity['label'].title()}")
        st.caption(velocity['description'])

    st.divider()

    # Overall progress bar
    overall = summary.get("overall", {})
    st.subheader("Overall Progress")
    st.progress(overall.get("percent_complete", 0) / 100)
    st.write(f"{overall.get('lessons_mastered', 0)} of {overall.get('total_lessons', 0)} lessons mastered")

    # Module breakdown
    st.subheader("Module Progress")

    for module in summary.get("modules", []):
        # Check if this module was mastered via diagnostic
        diagnostic_mastered = (
            diagnostic_results and
            module['module_number'] in diagnostic_results.get('modules_mastered', [])
        )

        module_label = f"Module {module['module_number']}: {module['title']}"
        if diagnostic_mastered:
            module_label += " (Diagnostic)"

        with st.expander(module_label, expanded=module.get('percent_complete', 0) < 100):
            col1, col2 = st.columns([3, 1])

            with col1:
                st.progress(module.get("percent_complete", 0) / 100)

            with col2:
                if module.get("is_complete"):
                    if diagnostic_mastered:
                        st.success("Skipped!")
                    else:
                        st.success("Complete!")
                else:
                    st.write(f"{module.get('lessons_mastered', 0)}/{module.get('total_lessons', 0)}")

    # Performance stats
    st.subheader("Performance")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Submissions", overall.get("total_submissions", 0))
    with col2:
        st.metric("Average Score", f"{overall.get('average_score', 0):.1f}%")
    with col3:
        st.metric("Perfect Scores", overall.get("perfect_scores", 0))


def show_pending():
    """Show pending grading page."""
    current_student = get_current_student()
    student_id = current_student["id"]
    student_name = current_student["name"]

    st.title(f"Pending Grading - {student_name}")

    # Upload section
    st.subheader(f"Upload {student_name}'s Completed Work")

    from src.grading.qr_scanner import auto_identify_upload, scan_qr_from_file
    from src.database.models import MaterialType
    import uuid
    from datetime import datetime as dt

    # File uploader
    uploaded_file = st.file_uploader(
        "Upload scanned work (photo or PDF)",
        type=["png", "jpg", "jpeg", "pdf"],
        help="Upload the completed worksheet - the QR code will be automatically detected"
    )

    if uploaded_file is not None:
        # Save to temp file for QR scanning
        file_ext = Path(uploaded_file.name).suffix
        temp_filename = f"temp_{uuid.uuid4().hex[:8]}{file_ext}"
        temp_path = SCANS_FOLDER / temp_filename

        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # Auto-detect assignment via QR code
        detection_result = auto_identify_upload(temp_path)

        if detection_result["success"]:
            # QR code detected successfully
            st.success(f"**Auto-detected:** {detection_result['message']}")

            detected_material_id = detection_result["material_id"]

            col1, col2 = st.columns([3, 1])
            with col1:
                if st.button("Submit for Grading", type="primary", key="submit_auto"):
                    # Rename temp file to permanent
                    final_filename = f"scan_{dt.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{file_ext}"
                    final_path = SCANS_FOLDER / final_filename
                    shutil.move(str(temp_path), str(final_path))

                    # Create submission
                    from src.database.models import SubmissionStatus
                    with get_session() as session:
                        submission = Submission(
                            student_id=student_id,
                            material_id=detected_material_id,
                            scan_path=str(final_path),
                            status=SubmissionStatus.PENDING
                        )
                        session.add(submission)
                        session.commit()
                        st.success(f"Uploaded! Ready for grading.")
                        st.rerun()

            with col2:
                if st.button("Wrong assignment?", key="override_btn"):
                    st.session_state.show_manual_select = True

        else:
            # QR code not found - show manual selection
            st.warning(f"Could not auto-detect: {detection_result['message']}")
            st.session_state.show_manual_select = True

        # Manual selection fallback
        if st.session_state.get("show_manual_select", False):
            st.write("**Select assignment manually:**")

            with get_session() as session:
                materials = (
                    session.query(Material)
                    .join(Lesson)
                    .join(Module)
                    .filter(Material.material_type.in_([
                        MaterialType.PRACTICE,
                        MaterialType.REMEDIATION,
                        MaterialType.QUIZ,
                        MaterialType.TEST
                    ]))
                    .order_by(Module.number, Lesson.number, Material.created_at.desc())
                    .all()
                )

                diagnostics = (
                    session.query(Material)
                    .filter(Material.material_type == MaterialType.DIAGNOSTIC)
                    .order_by(Material.created_at.desc())
                    .all()
                )

                material_options = {"Select the assignment...": None}

                for mat in diagnostics:
                    label = f"DIAGNOSTIC Assessment - {mat.qr_code}"
                    material_options[label] = mat.id

                for mat in materials:
                    label = f"M{mat.lesson.module.number} L{mat.lesson.number}: {mat.lesson.title} ({mat.material_type.value}) - {mat.qr_code}"
                    material_options[label] = mat.id

            selected_label = st.selectbox(
                "Which assignment is this?",
                list(material_options.keys()),
                key="manual_material_select"
            )
            selected_material_id = material_options[selected_label]

            if selected_material_id and st.button("Submit for Grading", type="primary", key="submit_manual"):
                # Rename temp file to permanent
                final_filename = f"scan_{dt.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{file_ext}"
                final_path = SCANS_FOLDER / final_filename
                shutil.move(str(temp_path), str(final_path))

                from src.database.models import SubmissionStatus
                with get_session() as session:
                    submission = Submission(
                        student_id=student_id,
                        material_id=selected_material_id,
                        scan_path=str(final_path),
                        status=SubmissionStatus.PENDING
                    )
                    session.add(submission)
                    session.commit()
                    st.session_state.show_manual_select = False
                    st.success("Uploaded! Ready for grading.")
                    st.rerun()

        # Clean up temp file if not submitted
        if temp_path.exists() and not st.session_state.get("submitted"):
            pass  # Keep temp file until user submits or uploads new file

    st.divider()

    # Get pending submissions for this student
    pending = get_pending_submissions(student_id=student_id)

    if not pending:
        st.info(f"No submissions pending grading for {student_name}.")
        return

    st.subheader(f"{len(pending)} Pending Submission(s) for {student_name}")

    for sub in pending:
        with st.expander(f"Submission {sub['id']} - {sub['material_type'].title()}"):
            st.write(f"**Scan path:** {sub['scan_path']}")
            st.write(f"**Material QR:** {sub['qr_code'] or 'Unknown'}")
            st.write(f"**Scanned:** {sub['scanned_at']}")

            col1, col2 = st.columns(2)

            with col1:
                if sub['material_type'] in ['practice', 'remediation', 'diagnostic']:
                    if st.button(f"Auto-Grade #{sub['id']}", key=f"grade_{sub['id']}"):
                        with st.spinner("Grading with Claude Vision..."):
                            grader = Grader()
                            result = grader.grade_submission(sub['id'])

                            if "error" in result:
                                st.error(result["error"])
                            else:
                                if sub['material_type'] == 'diagnostic':
                                    # Show diagnostic-specific results
                                    st.success(f"Diagnostic Complete! Overall Score: {result['score']:.1f}%")

                                    # Show module scores summary
                                    if 'module_scores' in result:
                                        st.write("### Module Results")
                                        cols = st.columns(4)
                                        for i, mod_num in enumerate(sorted(result['module_scores'].keys())):
                                            score = result['module_scores'][mod_num]
                                            with cols[i % 4]:
                                                if score >= 100:
                                                    st.success(f"**M{mod_num}**: {score:.0f}% ✓")
                                                else:
                                                    st.warning(f"**M{mod_num}**: {score:.0f}%")

                                    # Generate diagnostic feedback PDF with mini-lessons
                                    diagnostic_feedback = result.get('diagnostic_feedback', {})
                                    feedback_path = generate_diagnostic_feedback(sub['id'], diagnostic_feedback)

                                    if feedback_path and Path(feedback_path).exists():
                                        with open(feedback_path, "rb") as f:
                                            st.download_button(
                                                label="Download Diagnostic Feedback PDF",
                                                data=f.read(),
                                                file_name=Path(feedback_path).name,
                                                mime="application/pdf",
                                                key=f"dl_diag_feedback_{sub['id']}",
                                                type="primary"
                                            )
                                        st.info("The feedback PDF includes question-by-question results and mini-lessons for areas to review.")

                                    # Show warning if there are low-confidence readings
                                    needs_review = result.get("needs_review", [])
                                    if needs_review:
                                        review_nums = [item.get("question") for item in needs_review]
                                        st.warning(f"⚠️ {len(needs_review)} question(s) had unclear handwriting: Q{', Q'.join(str(n) for n in review_nums)}. Please check Work History to verify.")

                                    st.info("Check the Home page to see your updated starting position!")
                                else:
                                    if result.get("is_mastery"):
                                        st.success(f"Score: {result['score']:.1f}% - MASTERY!")
                                    else:
                                        st.warning(f"Score: {result['score']:.1f}% - Needs more practice")

                                    # Show warning if there are low-confidence readings
                                    needs_review = result.get("needs_review", [])
                                    if needs_review:
                                        review_nums = [item.get("question") for item in needs_review]
                                        st.warning(f"⚠️ {len(needs_review)} question(s) had unclear handwriting: Q{', Q'.join(str(n) for n in review_nums)}. Please check Work History to verify.")

                                    # Generate feedback PDF
                                    feedback_path = generate_feedback(sub['id'])
                                    if feedback_path and Path(feedback_path).exists():
                                        with open(feedback_path, "rb") as f:
                                            st.download_button(
                                                label="Download Feedback PDF",
                                                data=f.read(),
                                                file_name=Path(feedback_path).name,
                                                mime="application/pdf",
                                                key=f"dl_feedback_{sub['id']}"
                                            )

            with col2:
                if st.button(f"View Scan #{sub['id']}", key=f"view_{sub['id']}"):
                    scan_path = Path(sub['scan_path'])
                    try:
                        if scan_path.suffix.lower() == '.pdf':
                            # Convert PDF pages to images using PyMuPDF
                            import fitz  # PyMuPDF
                            doc = fitz.open(scan_path)
                            st.write(f"**Scan: {scan_path.name}** ({len(doc)} page{'s' if len(doc) > 1 else ''})")

                            for page_num in range(len(doc)):
                                page = doc[page_num]
                                # Render page to image at 150 DPI for good quality
                                mat = fitz.Matrix(150/72, 150/72)
                                pix = page.get_pixmap(matrix=mat)
                                img_data = pix.tobytes("png")
                                st.image(img_data, caption=f"Page {page_num + 1}", use_container_width=True)
                            doc.close()

                            # Also offer download
                            with open(scan_path, "rb") as f:
                                st.download_button(
                                    label="Download PDF",
                                    data=f.read(),
                                    file_name=scan_path.name,
                                    mime="application/pdf",
                                    key=f"dl_scan_{sub['id']}"
                                )
                        else:
                            # Display image
                            from PIL import Image
                            img = Image.open(scan_path)
                            st.image(img, caption="Scanned Work", use_container_width=True)
                    except Exception as e:
                        st.error(f"Could not load scan: {e}")
                        # Offer download as fallback
                        if scan_path.exists():
                            with open(scan_path, "rb") as f:
                                st.download_button(
                                    label="Download Scan File",
                                    data=f.read(),
                                    file_name=scan_path.name,
                                    key=f"dl_fallback_{sub['id']}"
                                )


def show_feedback_history():
    """Show comprehensive work history with scans and feedback."""
    current_student = get_current_student()
    student_id = current_student["id"]
    student_name = current_student["name"]

    st.title(f"Work History - {student_name}")

    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        show_filter = st.selectbox(
            "Show",
            ["All Submissions", "Graded Only", "Pending Only", "Mastered Only"],
            key="history_filter"
        )
    with col2:
        sort_order = st.selectbox(
            "Sort by",
            ["Newest First", "Oldest First", "Highest Score", "Lowest Score"],
            key="history_sort"
        )

    with get_session() as session:
        query = session.query(Submission).filter(Submission.student_id == student_id)

        # Apply filters
        if show_filter == "Graded Only":
            query = query.filter(Submission.score.isnot(None))
        elif show_filter == "Pending Only":
            query = query.filter(Submission.score.is_(None))
        elif show_filter == "Mastered Only":
            query = query.filter(Submission.score >= 100)

        # Apply sorting
        if sort_order == "Newest First":
            query = query.order_by(Submission.scanned_at.desc())
        elif sort_order == "Oldest First":
            query = query.order_by(Submission.scanned_at.asc())
        elif sort_order == "Highest Score":
            query = query.order_by(Submission.score.desc().nullslast())
        elif sort_order == "Lowest Score":
            query = query.order_by(Submission.score.asc().nullsfirst())

        submissions = query.all()

        if not submissions:
            st.info(f"No submissions found for {student_name}.")
            return

        st.write(f"**{len(submissions)} submission(s) found**")
        st.divider()

        for sub in submissions:
            material = sub.material
            if not material:
                continue

            # Determine title and status
            if material.lesson:
                title = f"M{material.lesson.module.number} L{material.lesson.number}: {material.lesson.title}"
            else:
                title = "Diagnostic Assessment"

            material_type = material.material_type.value.title()

            if sub.score is not None:
                mastery = "MASTERED" if sub.score >= 100 else "Needs Work"
                status_icon = "✅" if sub.score >= 100 else "📝"
                score_display = f"{sub.score:.0f}%"
            else:
                mastery = "Pending"
                status_icon = "⏳"
                score_display = "Not graded"

            # Format date
            date_str = sub.scanned_at.strftime('%b %d, %Y') if sub.scanned_at else "Unknown"

            with st.expander(
                f"{status_icon} {material_type}: {title} - {score_display} ({date_str})"
            ):
                # Info row
                info_col1, info_col2, info_col3 = st.columns(3)

                with info_col1:
                    st.write(f"**Status:** {mastery}")
                    if sub.score is not None:
                        st.write(f"**Score:** {sub.score:.1f}%")

                with info_col2:
                    st.write(f"**Submitted:** {sub.scanned_at.strftime('%Y-%m-%d %H:%M') if sub.scanned_at else 'N/A'}")
                    if sub.graded_at:
                        st.write(f"**Graded:** {sub.graded_at.strftime('%Y-%m-%d %H:%M')}")

                with info_col3:
                    st.write(f"**QR Code:** {material.qr_code}")

                # Results summary
                results = sub.results_json or []
                if results:
                    correct = sum(1 for r in results if r.get("is_correct", False))
                    st.write(f"**Questions:** {correct} / {len(results)} correct")

                st.divider()

                # Action buttons
                btn_col1, btn_col2, btn_col3 = st.columns(3)

                with btn_col1:
                    # View scan button
                    if sub.scan_path and Path(sub.scan_path).exists():
                        if st.button(f"View Scan", key=f"view_scan_hist_{sub.id}"):
                            st.session_state[f"show_scan_{sub.id}"] = True

                with btn_col2:
                    # Download feedback PDF
                    if sub.feedback_pdf_path and Path(sub.feedback_pdf_path).exists():
                        with open(sub.feedback_pdf_path, "rb") as f:
                            st.download_button(
                                label="Download Feedback",
                                data=f.read(),
                                file_name=Path(sub.feedback_pdf_path).name,
                                mime="application/pdf",
                                key=f"dl_feedback_hist_{sub.id}"
                            )
                    elif sub.score is None:
                        st.write("*Not yet graded*")

                with btn_col3:
                    # Download original scan
                    if sub.scan_path and Path(sub.scan_path).exists():
                        scan_path = Path(sub.scan_path)
                        with open(scan_path, "rb") as f:
                            mime = "application/pdf" if scan_path.suffix.lower() == ".pdf" else "image/*"
                            st.download_button(
                                label="Download Scan",
                                data=f.read(),
                                file_name=scan_path.name,
                                mime=mime,
                                key=f"dl_scan_hist_{sub.id}"
                            )

                # Show scan if requested
                if st.session_state.get(f"show_scan_{sub.id}", False):
                    st.write("**Scanned Work:**")
                    scan_path = Path(sub.scan_path)
                    try:
                        if scan_path.suffix.lower() == '.pdf':
                            import fitz
                            doc = fitz.open(scan_path)
                            for page_num in range(len(doc)):
                                page = doc[page_num]
                                mat = fitz.Matrix(150/72, 150/72)
                                pix = page.get_pixmap(matrix=mat)
                                img_data = pix.tobytes("png")
                                st.image(img_data, caption=f"Page {page_num + 1}", use_container_width=True)
                            doc.close()
                        else:
                            from PIL import Image
                            img = Image.open(scan_path)
                            st.image(img, caption="Scanned Work", use_container_width=True)
                    except Exception as e:
                        st.error(f"Could not display scan: {e}")

                    if st.button("Hide Scan", key=f"hide_scan_{sub.id}"):
                        st.session_state[f"show_scan_{sub.id}"] = False
                        st.rerun()

                # Show question-by-question results if graded
                if results and sub.score is not None:
                    # Check for needs_review items from confidence levels
                    feedback = sub.feedback_json or {}
                    needs_review_list = feedback.get("needs_review", [])
                    needs_review_nums = {item.get("question") for item in needs_review_list}

                    # Show warning banner if any questions need review
                    if needs_review_nums:
                        st.warning(f"⚠️ {len(needs_review_nums)} question(s) had unclear handwriting and may need review: Q{', Q'.join(str(n) for n in sorted(needs_review_nums))}")

                    with st.expander("Question Details & Disputes", expanded=False):
                        for r in results:
                            is_correct = r.get("is_correct", False)
                            needs_review = r.get("needs_review", False) or r.get("number") in needs_review_nums
                            confidence = r.get("reading_confidence", "high").lower()

                            # Icon based on correctness and review status
                            if needs_review:
                                icon = "⚠️" if is_correct else "❓"
                            else:
                                icon = "✅" if is_correct else "❌"
                            q_num = r.get('number')

                            col1, col2 = st.columns([4, 1])
                            with col1:
                                answer_display = f"{icon} **Q{q_num}**: {r.get('student_answer', 'N/A')}"
                                if needs_review:
                                    answer_display += f" *(confidence: {confidence})*"
                                st.write(answer_display)
                                if not is_correct:
                                    st.write(f"   Correct: {r.get('correct_answer', 'N/A')}")
                                if r.get('notes'):
                                    st.caption(f"   Note: {r.get('notes')}")
                            with col2:
                                # Dispute button
                                dispute_key = f"dispute_{sub.id}_{q_num}"
                                if st.button("Dispute", key=dispute_key, type="secondary"):
                                    st.session_state[f"show_dispute_form_{sub.id}_{q_num}"] = True

                            # Show dispute form if button was clicked
                            if st.session_state.get(f"show_dispute_form_{sub.id}_{q_num}"):
                                with st.form(key=f"dispute_form_{sub.id}_{q_num}"):
                                    st.write(f"**Dispute Q{q_num}**")
                                    reason = st.text_area(
                                        "Why do you think this is graded incorrectly?",
                                        key=f"reason_{sub.id}_{q_num}",
                                        placeholder="Explain why you believe your answer should be marked differently..."
                                    )
                                    col_submit, col_cancel = st.columns(2)
                                    with col_submit:
                                        if st.form_submit_button("Submit Dispute", type="primary"):
                                            if reason.strip():
                                                # Save dispute to database
                                                from src.database import Dispute, DisputeStatus
                                                with get_session() as dispute_session:
                                                    dispute = Dispute(
                                                        submission_id=sub.id,
                                                        question_number=q_num,
                                                        student_reason=reason.strip(),
                                                        original_correct=is_correct
                                                    )
                                                    dispute_session.add(dispute)
                                                    dispute_session.commit()
                                                st.success("Dispute submitted!")
                                                st.session_state[f"show_dispute_form_{sub.id}_{q_num}"] = False
                                                st.rerun()
                                            else:
                                                st.error("Please enter a reason for your dispute.")
                                    with col_cancel:
                                        if st.form_submit_button("Cancel"):
                                            st.session_state[f"show_dispute_form_{sub.id}_{q_num}"] = False
                                            st.rerun()

                # Show error patterns
                if sub.error_patterns:
                    st.write("**Areas to improve:**")
                    for pattern in sub.error_patterns:
                        st.write(f"- {pattern.get('pattern', 'Unknown')}: {pattern.get('description', '')}")


def show_disputes():
    """Show disputes page for reviewing and resolving grade disputes."""
    from src.database import Dispute, DisputeStatus
    from sqlalchemy.orm.attributes import flag_modified

    current_student = get_current_student()
    student_id = current_student["id"]
    student_name = current_student["name"]

    st.title(f"Grade Disputes - {student_name}")

    with get_session() as session:
        # Get all disputes for this student's submissions
        disputes = (
            session.query(Dispute)
            .join(Submission)
            .filter(Submission.student_id == student_id)
            .order_by(Dispute.created_at.desc())
            .all()
        )

        if not disputes:
            st.info("No disputes submitted yet.")
            st.write("You can dispute any graded question from the **Work History** page.")
            return

        # Separate pending and resolved
        pending = [d for d in disputes if d.status == DisputeStatus.PENDING]
        resolved = [d for d in disputes if d.status != DisputeStatus.PENDING]

        # Show pending disputes
        if pending:
            st.subheader(f"Pending Disputes ({len(pending)})")

            for dispute in pending:
                sub = dispute.submission
                material = sub.material
                content = material.content_json or {}
                subject_name = content.get("subject_name", "Unknown")

                with st.expander(f"Q{dispute.question_number} - {subject_name} (Submitted {dispute.created_at.strftime('%Y-%m-%d %H:%M')})", expanded=True):
                    # Get the question details
                    results = sub.results_json or []
                    q_result = next((r for r in results if r.get("number") == dispute.question_number), None)

                    if q_result:
                        st.write(f"**Student Answer:** {q_result.get('student_answer', 'N/A')}")
                        st.write(f"**Correct Answer:** {q_result.get('correct_answer', 'N/A')}")
                        st.write(f"**Currently Marked:** {'✅ Correct' if q_result.get('is_correct') else '❌ Wrong'}")

                    st.write(f"**Student's Reason for Dispute:**")
                    st.info(dispute.student_reason)

                    # Resolution form (for parent/teacher)
                    st.write("---")
                    st.write("**Resolve this dispute:**")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("✅ Approve (Mark Correct)", key=f"approve_{dispute.id}", type="primary"):
                            resolve_dispute(session, dispute, sub, approved=True)
                            st.rerun()
                    with col2:
                        if st.button("❌ Reject (Keep as Wrong)", key=f"reject_{dispute.id}"):
                            resolve_dispute(session, dispute, sub, approved=False)
                            st.rerun()
                    with col3:
                        notes = st.text_input("Notes (optional)", key=f"notes_{dispute.id}")
                        if notes:
                            dispute.resolution_notes = notes

        # Show resolved disputes
        if resolved:
            st.subheader(f"Resolved Disputes ({len(resolved)})")

            for dispute in resolved:
                sub = dispute.submission
                material = sub.material
                content = material.content_json or {}
                subject_name = content.get("subject_name", "Unknown")

                status_icon = "✅" if dispute.status == DisputeStatus.APPROVED else "❌"
                status_text = "Approved" if dispute.status == DisputeStatus.APPROVED else "Rejected"

                with st.expander(f"{status_icon} Q{dispute.question_number} - {subject_name} ({status_text})", expanded=False):
                    st.write(f"**Original Reason:** {dispute.student_reason}")
                    if dispute.resolution_notes:
                        st.write(f"**Resolution Notes:** {dispute.resolution_notes}")
                    if dispute.resolved_at:
                        st.caption(f"Resolved: {dispute.resolved_at.strftime('%Y-%m-%d %H:%M')}")


def resolve_dispute(session, dispute, submission, approved: bool):
    """Resolve a dispute and update the submission score if needed."""
    from src.database import DisputeStatus
    from sqlalchemy.orm.attributes import flag_modified
    from datetime import datetime

    dispute.status = DisputeStatus.APPROVED if approved else DisputeStatus.REJECTED
    dispute.resolved_at = datetime.utcnow()
    dispute.new_correct = approved

    # If approved, update the submission results
    if approved:
        results = list(submission.results_json or [])
        for r in results:
            if r.get("number") == dispute.question_number:
                r["is_correct"] = True
                r["partial_credit"] = 1.0
                r["notes"] = f"Corrected via dispute: {dispute.student_reason[:50]}..."
                break

        # Recalculate score
        total = len(results)
        correct = sum(1 for r in results if r.get("is_correct"))
        new_score = (correct / total * 100) if total > 0 else 0

        submission.results_json = results
        submission.score = new_score
        flag_modified(submission, "results_json")

    session.commit()


def show_settings():
    """Show settings page."""
    st.title("Settings")

    st.subheader("Configuration")
    st.write(f"**Student Name:** {STUDENT_NAME}")
    st.write(f"**Scans Folder:** {SCANS_FOLDER}")
    st.write(f"**Generated PDFs Folder:** {GENERATED_FOLDER}")
    st.write(f"**API Key Configured:** {'Yes' if ANTHROPIC_API_KEY else 'No'}")

    st.subheader("System Check")

    # Check API key
    if ANTHROPIC_API_KEY:
        st.success("Anthropic API key is configured")
    else:
        st.error("Anthropic API key is NOT configured. Set ANTHROPIC_API_KEY in .env")

    # Check folders
    if SCANS_FOLDER.exists():
        st.success(f"Scans folder exists: {SCANS_FOLDER}")
    else:
        st.warning(f"Scans folder does not exist: {SCANS_FOLDER}")

    if GENERATED_FOLDER.exists():
        st.success(f"Generated folder exists: {GENERATED_FOLDER}")
    else:
        st.warning(f"Generated folder does not exist: {GENERATED_FOLDER}")

    st.subheader("Database")

    with get_session() as session:
        student_count = session.query(Student).count()
        material_count = session.query(Material).count()
        submission_count = session.query(Submission).count()

        st.write(f"- Students: {student_count}")
        st.write(f"- Materials generated: {material_count}")
        st.write(f"- Submissions: {submission_count}")

    if st.button("Reinitialize Database"):
        init_db()
        st.success("Database reinitialized!")


if __name__ == "__main__":
    main()
