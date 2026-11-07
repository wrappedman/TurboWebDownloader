"""Startup diagnostics should work before any third-party packages are installed."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_without_dependencies():
    result = subprocess.run([sys.executable, '-S', 'run.py', '--help'], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert '--port' in result.stdout


def test_missing_dependency_is_actionable():
    result = subprocess.run([sys.executable, '-S', 'run.py'], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'missing Python dependency "flask"' in result.stderr
    assert sys.executable in result.stderr
    assert '-m pip install -r requirements.txt' in result.stderr
    assert 'start-web-windows.bat' in result.stderr
    assert 'Traceback' not in result.stderr
