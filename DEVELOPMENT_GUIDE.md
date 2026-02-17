# Learnfast - Development Guide

## Overview

This is a Streamlit-based adaptive learning system for pre-algebra students. It generates personalized lessons, practice problems, and diagnostics, then grades handwritten student work using Claude Vision API.

**Live Site:** https://learnfast.streamlit.app/

**GitHub Repo:** https://github.com/langloss-tim/learnfast

## Project Structure

```
learnfast/
├── src/
│   ├── web/
│   │   └── dashboard.py      # Main Streamlit UI (1800+ lines)
│   ├── grading/
│   │   ├── grader.py         # Claude Vision grading logic
│   │   ├── scanner.py        # PDF/image processing
│   │   └── qr_scanner.py     # QR code detection
│   ├── content/
│   │   ├── generator.py      # AI-powered lesson/practice generation
│   │   ├── curriculum.py     # Curriculum navigation
│   │   └── curriculum_loader.py  # YAML curriculum loading
│   ├── adaptive/
│   │   └── pacing.py         # Adaptive learning algorithms
│   ├── pdf/
│   │   └── generator.py      # PDF generation for printable materials
│   ├── database/
│   │   ├── models.py         # SQLAlchemy models
│   │   └── db.py             # Database initialization
│   └── config.py             # Configuration (supports st.secrets + env vars)
├── data/
│   ├── prealgebra.db         # SQLite database
│   ├── scans/                # Uploaded student work scans
│   └── curricula/            # YAML curriculum definitions
├── .streamlit/
│   └── config.toml           # Streamlit configuration
├── packages.txt              # System dependencies for Streamlit Cloud
├── requirements.txt          # Python dependencies
└── README.md
```

## Quick Start

### Local Development
```bash
cd "/mnt/e/Dropbox/Github Folder/Learnfast/learnfast"
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key-here"
streamlit run src/web/dashboard.py
```

The app will be available at http://localhost:8501

### Streamlit Cloud Deployment
The app auto-deploys from the `main` branch. Secrets are configured in:
- Streamlit Cloud Dashboard → App Settings → Secrets
- Required: `ANTHROPIC_API_KEY`
- Optional: `STUDENT_NAME` (default first student)

## Key Features

### 1. Multi-Student Support
- Students managed via sidebar dropdown
- Each student has independent progress tracking
- Student colors: Tilley (pink), Henry (blue)

### 2. Content Generation
- **Lessons**: AI-generated explanations with examples
- **Practice**: Problems with answer keys, QR codes for tracking
- **Quizzes/Tests**: Module assessments
- **Diagnostics**: Full curriculum assessment
- **Tailored Lessons**: Remediation for weak areas

### 3. Grading System
- Upload scanned work (PNG/JPG/PDF)
- QR code auto-detection for assignment matching
- Claude Vision reads handwritten answers
- Two-stage grading: transcription → comparison

### 4. Adaptive Pacing
- Tracks velocity (learning speed)
- Adjusts problem count based on performance
- Offers lesson skipping for high performers

## Dashboard Pages

| Page | Purpose |
|------|---------|
| **Home** | Current status, next steps, diagnostic results |
| **Generate Materials** | Create lessons, practice, quizzes, tests |
| **Progress** | Module-by-module mastery tracking |
| **Pending Grading** | Upload and grade scanned work |
| **Work History** | View past submissions and feedback |
| **Disputes** | Handle grade disputes |
| **Settings** | System configuration |

## Database Schema (Key Tables)

- **students**: id, name, created_at
- **subjects**: id, code, name, grade_level
- **student_subject_progress**: tracks per-student, per-subject progress
- **modules**: id, subject_id, number, title
- **lessons**: id, module_id, number, title, concepts
- **materials**: id, lesson_id, material_type, content_json, answer_key_json, qr_code
- **submissions**: id, student_id, material_id, scan_path, score, status
- **progress**: id, student_id, lesson_id, mastered

## Configuration

Key settings in `src/config.py`:
- `ANTHROPIC_API_KEY`: Required for AI features
- `CLAUDE_MODEL`: Model for content generation
- `CLAUDE_VISION_MODEL`: Model for grading
- `MASTERY_THRESHOLD`: Score needed for mastery (default 100%)

The `get_secret()` helper reads from `st.secrets` (Streamlit Cloud) or `os.getenv()` (local).

## Development Workflow

### Two Folders Setup
The user maintains two folders:
1. **Development**: `C:\Users\langl\Desktop\Claude Access\prealgebra-learning`
2. **GitHub (Live)**: `E:\Dropbox\Github Folder\Learnfast\learnfast`

Changes should be made in the GitHub folder for deployment, or copied from dev → GitHub.

### Deploying Changes
1. Make changes in the GitHub folder
2. Open GitHub Desktop
3. Commit changes
4. Click "Push origin"
5. Streamlit Cloud auto-deploys in ~1-2 minutes

## Known Issues

### Grading Accuracy
Claude Vision sometimes misreads handwriting:
- Similar digits: 1/7, 3/8, 4/9, 6/0
- Comma-separated values merged (e.g., "6, 9" → "69")
- Remainder notation ("R3" → "13")

**Current mitigations:**
- Two-stage grading (transcription separate from comparison)
- Expanded equivalence rules for answer matching
- Answer key pre-computed at generation time

### Streamlit Cloud Limitations
- Ephemeral filesystem (database resets on redeploy)
- Consider external database for persistence (Supabase, PlanetScale)

## Session History

### Session 2026-02-17 - Bug Fixes for Live Site

**Problem:** Website couldn't create new exercises, showing database errors.

**Bugs Fixed:**

| Bug | File | Fix |
|-----|------|-----|
| Infinite recursion in `_api_call_with_retry` | `generator.py` | Changed recursive call to `self.client.messages.create()` |
| Missing Streamlit secrets support | `config.py` | Added `get_secret()` helper function |
| Database crash on subject change | `dashboard.py` | Added try-except around `last_accessed_at` update |
| Undefined variable `selected_material_id` | `dashboard.py` | Removed dead code block |
| Cross-filesystem file move fails | `dashboard.py` | Changed `Path.rename()` to `shutil.move()` |
| Hardcoded model name | `grader.py` | Use `CLAUDE_VISION_MODEL` config constant |
| Missing dependency | `requirements.txt` | Added `pymupdf>=1.24.0` |

**Files Changed:**
- `src/config.py` - Added `get_secret()` function
- `src/content/generator.py` - Fixed API retry method
- `src/grading/grader.py` - Use config constant for model
- `src/web/dashboard.py` - Multiple fixes (shutil, error handling, dead code)
- `requirements.txt` - Added pymupdf

**Verification:** All features working on live site after deployment.

### Session 2026-02-04 - Streamlit Cloud Deployment

- Added `get_secret()` for st.secrets support
- Created `packages.txt` (libzbar0)
- Created `.streamlit/config.toml`
- Added pymupdf, pyyaml to requirements.txt

### Session 2026-01-28 - Code Quality & Testing

- Added 38 unit tests
- Created CI/CD with GitHub Actions
- Fixed datetime deprecations
- Added logging throughout
- Created Dockerfile
- Added API retry logic

### Earlier Sessions

- Set up virtual environment
- Built Streamlit dashboard
- Implemented content generation
- Implemented Claude Vision grading
- Added adaptive pacing
- Debugged grading accuracy issues

## Useful Commands

```bash
# Start local server
streamlit run src/web/dashboard.py

# Run tests (in dev folder)
python -m pytest tests/ -v

# Check git status
git status

# Push to deploy
git add . && git commit -m "message" && git push
```

## Future Improvements

1. **External Database**: Supabase or PlanetScale for persistent storage
2. **Grading Accuracy**: Structured answer sheets, human review for low confidence
3. **More Subjects**: Currently has Pre-Algebra, can add more via YAML curricula
4. **Mobile-Friendly**: Improve responsive design

## Contact

For issues, check the GitHub repo or the Streamlit Cloud logs (Manage app → Logs).
