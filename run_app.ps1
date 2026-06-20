$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m pdd_art_manager.app

