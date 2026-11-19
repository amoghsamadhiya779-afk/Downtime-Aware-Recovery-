if (Test-Path ".venv\Scripts\python.exe") {
    .venv\Scripts\python.exe scripts\build_comparison.py
} else {
    python scripts\build_comparison.py
}
