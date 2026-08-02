from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_vendor_and_workspace_imports_are_absent():
    assert not (ROOT / "vendor").exists()
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "sys.path" in text or "from tools" in text or "import tools." in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []

def test_official_forward_ledger_is_preserved():
    assert (ROOT / "data" / "predictions.jsonl").is_file()
