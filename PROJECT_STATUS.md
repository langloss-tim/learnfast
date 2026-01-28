# Learnfast - Project Status

## Overview
Learnfast is an adaptive math learning system for teaching pre-algebra and 4th grade math to Tilley and Henry. It uses Claude AI for content generation and vision-based grading of handwritten work.

## Quick Start - Launching the Dashboard

From PowerShell:
```powershell
cd "C:\Users\langl\OneDrive\Desktop\Claude Access\prealgebra-learning"
venv\Scripts\activate
$env:PYTHONPATH = $PWD; streamlit run src\web\dashboard.py
```

Or double-click `launch.bat` in the project folder.

Dashboard opens at: http://localhost:8501

## Project Locations

| Location | Purpose |
|----------|---------|
| `C:\Users\langl\OneDrive\Desktop\Claude Access\prealgebra-learning` | Working directory (where you run code) |
| `E:\Dropbox\Github Folder\Learnfast\learnfast` | Git repo (synced to GitHub) |
| https://github.com/langloss-tim/learnfast | GitHub repository |

## Key Files

- `src/main.py` - CLI entry point
- `src/web/dashboard.py` - Streamlit web dashboard
- `src/content/generator.py` - Claude-powered content generation
- `src/grading/grader.py` - Claude Vision grading
- `src/adaptive/pacing.py` - Adaptive learning velocity
- `src/database/models.py` - Database models
- `.env` - API key and configuration (not in git)

## Launcher Scripts (created Jan 28, 2025)

- `launch.bat` - Double-click to start dashboard (Windows)
- `launch.ps1` - PowerShell launcher with auto-setup
- `run_dashboard.py` - Python launcher
- `diagnose.py` - Troubleshooting script

## Current Features

1. **Multi-student support** - Tilley (pink) and Henry (blue)
2. **Multi-subject support** - Pre-algebra, 4th Grade Math
3. **Content generation** - Lessons, practice, quizzes, tests, diagnostics
4. **PDF generation** - Printable worksheets with QR codes
5. **Vision grading** - Claude grades scanned handwritten work
6. **Adaptive pacing** - Adjusts difficulty based on performance
7. **Dispute system** - Students can dispute grades
8. **Web dashboard** - Streamlit-based UI

## Workflow

1. Generate lesson/practice PDF from dashboard
2. Print and have student complete on paper
3. Scan completed work (photo or PDF)
4. Upload through dashboard → Claude Vision grades it
5. Student reviews feedback, disputes if needed
6. Progress tracked, system adapts difficulty

## Dependencies

All in `requirements.txt`. Key ones:
- anthropic (Claude API)
- streamlit (web dashboard)
- sqlalchemy (database)
- reportlab (PDF generation)
- pillow, pyzbar, qrcode (image/QR handling)

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=your-key-here
DATABASE_PATH=data/prealgebra.db
SCANS_FOLDER=data/scans
GENERATED_FOLDER=data/generated
STUDENT_NAME=Tilley
```

## Pushing Changes to GitHub

1. Copy updated files from OneDrive to `E:\Dropbox\Github Folder\Learnfast\learnfast`
2. Open GitHub Desktop
3. Review changes, write commit message
4. Click "Commit to main"
5. Click "Push origin"

Or ask Claude to help sync and commit.

## Last Session (Jan 28, 2025)

- Created launcher scripts to fix dashboard startup issues
- Root cause: PYTHONPATH wasn't set, preventing module imports
- Added .gitignore to exclude venv, pycache, .env from repo
- Synced code to GitHub repo
- Dashboard is working

## Next Steps / Ideas

- [ ] Continue testing with Tilley and Henry
- [ ] Refine grading accuracy
- [ ] Add more subjects/curricula
- [ ] Improve error handling in dashboard
