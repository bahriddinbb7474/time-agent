"""
Stage 19.8 Step 3 — safety checks for production OpenRouter smoke runner.

Verifies:
- shell syntax is valid via `bash -n`
- production DB path is `/app/data/app.db`
- forbidden `sqlite3 data/app.db` usage is absent
- daily request and cost limits are checked
- secret values and `.env` contents are not printed
- required commands are present: precheck / enable / verify / disable

Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_prod_openrouter_smoke_script.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "prod" / "run_19_8_openrouter_smoke.sh"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
SCRIPT_TEXT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_exists() -> None:
    assert SCRIPT_PATH.is_file(), f"missing script: {SCRIPT_PATH}"
    print("PASS: test_script_exists")


def test_script_passes_bash_syntax_check() -> None:
    assert GIT_BASH.is_file(), f"missing Git Bash: {GIT_BASH}"
    result = subprocess.run(
        [str(GIT_BASH), "-n", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "bash -n failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    print("PASS: test_script_passes_bash_syntax_check")


def test_script_uses_container_db_path() -> None:
    assert 'readonly DB_PATH="/app/data/app.db"' in SCRIPT_TEXT
    print("PASS: test_script_uses_container_db_path")


def test_script_does_not_use_forbidden_sqlite3_path() -> None:
    assert "sqlite3 data/app.db" not in SCRIPT_TEXT
    assert "sqlite3 /app/data/app.db" not in SCRIPT_TEXT
    print("PASS: test_script_does_not_use_forbidden_sqlite3_path")


def test_script_checks_daily_limits() -> None:
    assert 'request_limit="$(read_env_value LLM_DAILY_REQUEST_LIMIT)"' in SCRIPT_TEXT
    assert 'cost_limit="$(read_env_value LLM_DAILY_COST_USD_LIMIT)"' in SCRIPT_TEXT
    assert "LLM_DAILY_REQUEST_LIMIT must be a non-negative integer" in SCRIPT_TEXT
    assert "LLM_DAILY_COST_USD_LIMIT must be a non-negative decimal" in SCRIPT_TEXT
    print("PASS: test_script_checks_daily_limits")


def test_script_does_not_print_secret_values_or_env_contents() -> None:
    forbidden_snippets = [
        'say "OPENROUTER_API_KEY=$key"',
        'say "TELEGRAM_BOT_TOKEN=',
        "cat \"$ENV_FILE\"",
        "cat .env",
        "printenv",
        "env |",
        "grep OPENROUTER_API_KEY",
        "grep TELEGRAM_BOT_TOKEN",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in SCRIPT_TEXT, f"forbidden snippet found: {snippet}"

    assert 'say "OPENROUTER_API_KEY present: yes"' in SCRIPT_TEXT
    print("PASS: test_script_does_not_print_secret_values_or_env_contents")


def test_script_contains_required_commands() -> None:
    required_case_entries = [
        "precheck) cmd_precheck ;;",
        "enable) cmd_enable ;;",
        "verify) cmd_verify ;;",
        "disable) cmd_disable ;;",
    ]
    required_usage_lines = [
        "./scripts/prod/run_19_8_openrouter_smoke.sh precheck",
        "./scripts/prod/run_19_8_openrouter_smoke.sh enable",
        "./scripts/prod/run_19_8_openrouter_smoke.sh verify",
        "./scripts/prod/run_19_8_openrouter_smoke.sh disable",
    ]
    for line in required_case_entries + required_usage_lines:
        assert line in SCRIPT_TEXT, f"missing required command line: {line}"
    print("PASS: test_script_contains_required_commands")


TESTS = [
    test_script_exists,
    test_script_passes_bash_syntax_check,
    test_script_uses_container_db_path,
    test_script_does_not_use_forbidden_sqlite3_path,
    test_script_checks_daily_limits,
    test_script_does_not_print_secret_values_or_env_contents,
    test_script_contains_required_commands,
]


def main() -> None:
    for fn in TESTS:
        fn()
    print(f"\nALL {len(TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
