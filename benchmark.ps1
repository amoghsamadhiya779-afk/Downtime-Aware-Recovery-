if (Test-Path ".venv\Scripts\python.exe") {
    .venv\Scripts\python.exe scripts\benchmark.py
} else {
    python scripts\benchmark.py
}
