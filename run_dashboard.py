#!/usr/bin/env python3
"""
Simple launcher for Learnfast Dashboard.
Run this with: python run_dashboard.py
"""

import subprocess
import sys
import os
from pathlib import Path

def main():
    # Get the directory where this script lives
    script_dir = Path(__file__).parent.resolve()

    # Change to that directory
    os.chdir(script_dir)

    # Add to Python path
    sys.path.insert(0, str(script_dir))
    os.environ['PYTHONPATH'] = str(script_dir)

    dashboard_path = script_dir / "src" / "web" / "dashboard.py"

    if not dashboard_path.exists():
        print(f"Error: Dashboard not found at {dashboard_path}")
        sys.exit(1)

    print("=" * 50)
    print("  Starting Learnfast Dashboard")
    print("=" * 50)
    print(f"\nWorking directory: {script_dir}")
    print(f"Dashboard: {dashboard_path}")
    print("\nDashboard will open at: http://localhost:8501")
    print("Press Ctrl+C to stop\n")

    # Run streamlit
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_path),
        "--server.headless", "true"
    ])

if __name__ == "__main__":
    main()
