#!/usr/bin/env python3
"""
Diagnostic script for Learnfast.
Run this to check if everything is set up correctly.
"""

import sys
import os
from pathlib import Path

def check(name, condition, fix=""):
    if condition:
        print(f"  [OK] {name}")
        return True
    else:
        print(f"  [FAIL] {name}")
        if fix:
            print(f"         Fix: {fix}")
        return False

def main():
    print("=" * 50)
    print("  Learnfast Diagnostic Check")
    print("=" * 50)
    print()

    script_dir = Path(__file__).parent.resolve()
    os.chdir(script_dir)

    all_ok = True

    # Python version
    print("Python:")
    py_version = sys.version_info
    all_ok &= check(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}",
                    py_version >= (3, 9),
                    "Need Python 3.9+")
    print()

    # Project structure
    print("Project Structure:")
    all_ok &= check("src folder exists", (script_dir / "src").is_dir())
    all_ok &= check("dashboard.py exists", (script_dir / "src" / "web" / "dashboard.py").is_file())
    all_ok &= check("requirements.txt exists", (script_dir / "requirements.txt").is_file())
    all_ok &= check(".env exists", (script_dir / ".env").is_file())
    print()

    # Virtual environment
    print("Virtual Environment:")
    venv_dir = script_dir / "venv"
    venv_exists = venv_dir.is_dir()
    all_ok &= check("venv folder exists", venv_exists, "Run: python -m venv venv")

    if venv_exists:
        # Check for key packages
        if sys.platform == "win32":
            site_packages = venv_dir / "Lib" / "site-packages"
            streamlit_exe = venv_dir / "Scripts" / "streamlit.exe"
        else:
            site_packages = venv_dir / "lib" / f"python{py_version.major}.{py_version.minor}" / "site-packages"
            streamlit_exe = venv_dir / "bin" / "streamlit"

        all_ok &= check("streamlit installed", streamlit_exe.exists(),
                        "Activate venv then: pip install -r requirements.txt")
    print()

    # Environment
    print("Environment:")
    all_ok &= check(f"Working directory: {os.getcwd()}", True)

    # Try imports
    print()
    print("Module Imports:")
    sys.path.insert(0, str(script_dir))

    try:
        from src.config import ANTHROPIC_API_KEY, DATABASE_PATH
        all_ok &= check("src.config imports OK", True)
        all_ok &= check("API key configured", bool(ANTHROPIC_API_KEY),
                        "Set ANTHROPIC_API_KEY in .env file")
    except ImportError as e:
        all_ok &= check(f"src.config import FAILED: {e}", False)

    try:
        import streamlit
        all_ok &= check(f"streamlit {streamlit.__version__} imports OK", True)
    except ImportError:
        all_ok &= check("streamlit import FAILED", False,
                        "pip install streamlit")

    try:
        from src.database import init_db
        all_ok &= check("src.database imports OK", True)
    except ImportError as e:
        all_ok &= check(f"src.database import FAILED: {e}", False)

    print()
    print("=" * 50)
    if all_ok:
        print("  All checks passed! Try running:")
        print("    python run_dashboard.py")
    else:
        print("  Some checks failed. Fix the issues above.")
    print("=" * 50)

if __name__ == "__main__":
    main()
