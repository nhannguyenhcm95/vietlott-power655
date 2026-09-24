"""M2-T3 §2.9-5 / §2.10: static checks on the .ps1 files. Never executes a script."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPTS = ["run_refresh.ps1", "register_refresh_task.ps1", "unregister_refresh_task.ps1"]

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

PARSE_CHECK_PS1 = """
param([string]$Path)
$errs = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errs) | Out-Null
if ($errs.Count -gt 0) {
    $errs | ForEach-Object { Write-Output $_.ToString() }
    exit 1
} else {
    Write-Output "OK"
    exit 0
}
"""


@pytest.fixture(scope="module")
def parse_checker(tmp_path_factory):
    """A tiny helper .ps1 that only calls the Parser API -- it never invokes the script under test."""
    d = tmp_path_factory.mktemp("parse_checker")
    path = d / "parse_check.ps1"
    path.write_text(PARSE_CHECK_PS1, encoding="utf-8")
    return path


pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed")


@pytest.mark.parametrize("name", SCRIPTS)
def test_ps1_parse_only(name, parse_checker):
    """Each script must be syntactically valid PowerShell. This only parses; it never runs the script."""
    script = SCRIPTS_DIR / name
    assert script.exists(), f"{script} is missing"
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(parse_checker), "-Path", str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{name} failed to parse:\n{result.stdout}\n{result.stderr}"
    assert "OK" in result.stdout


@pytest.mark.parametrize("name", SCRIPTS)
def test_ps1_no_hardcoded_user_paths(name):
    text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "--log-level" not in text


def test_ps1_sets_location_and_no_log_level():
    text = (SCRIPTS_DIR / "run_refresh.ps1").read_text(encoding="utf-8")
    assert "Set-Location" in text
    assert "exit $code" in text
    assert "--log-level" not in text


def test_register_rejects_windowsapps_and_checks_imports():
    text = (SCRIPTS_DIR / "register_refresh_task.ps1").read_text(encoding="utf-8")
    assert "\\WindowsApps\\" in text
    assert "import pandas, bs4, src.cli" in text
