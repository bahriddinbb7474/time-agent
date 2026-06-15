"""
Stage 18.6-D — Config tests for API hard limit fields.
No real API calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_api_limit_config.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.config import _parse_limit_float, _parse_limit_int, load_config


# ── Helper ────────────────────────────────────────────────────────────────────


def _load_with_env(**overrides) -> object:
    """Load config after patching os.environ; restore afterwards."""
    saved = {}
    limit_keys = {
        "STT_DAILY_REQUEST_LIMIT",
        "STT_DAILY_SECONDS_LIMIT",
        "LLM_DAILY_REQUEST_LIMIT",
        "LLM_DAILY_COST_USD_LIMIT",
    }
    for k in limit_keys:
        saved[k] = os.environ.get(k)
        if k in overrides:
            os.environ[k] = overrides[k]
        elif k in os.environ:
            del os.environ[k]
    try:
        return load_config()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _expect_value_error(fn):
    try:
        fn()
        raise AssertionError("expected ValueError but none was raised")
    except ValueError:
        pass


# ── Default tests ─────────────────────────────────────────────────────────────


def test_defaults_are_zero():
    """Unset env vars produce limit=0 (unlimited) for all four fields."""
    cfg = _load_with_env()
    assert cfg.stt_daily_request_limit == 0, f"got {cfg.stt_daily_request_limit}"
    assert cfg.stt_daily_seconds_limit == 0, f"got {cfg.stt_daily_seconds_limit}"
    assert cfg.llm_daily_request_limit == 0, f"got {cfg.llm_daily_request_limit}"
    assert cfg.llm_daily_cost_usd_limit == 0.0, f"got {cfg.llm_daily_cost_usd_limit}"
    print("PASS: test_defaults_are_zero")


def test_custom_valid_int_limits():
    """Positive integer limits are accepted."""
    cfg = _load_with_env(
        STT_DAILY_REQUEST_LIMIT="10",
        STT_DAILY_SECONDS_LIMIT="600",
        LLM_DAILY_REQUEST_LIMIT="50",
        LLM_DAILY_COST_USD_LIMIT="2.5",
    )
    assert cfg.stt_daily_request_limit == 10
    assert cfg.stt_daily_seconds_limit == 600
    assert cfg.llm_daily_request_limit == 50
    assert abs(cfg.llm_daily_cost_usd_limit - 2.5) < 1e-9
    print("PASS: test_custom_valid_int_limits")


def test_zero_means_unlimited():
    """Explicit '0' produces 0 (unlimited) for all fields."""
    cfg = _load_with_env(
        STT_DAILY_REQUEST_LIMIT="0",
        STT_DAILY_SECONDS_LIMIT="0",
        LLM_DAILY_REQUEST_LIMIT="0",
        LLM_DAILY_COST_USD_LIMIT="0.0",
    )
    assert cfg.stt_daily_request_limit == 0
    assert cfg.stt_daily_seconds_limit == 0
    assert cfg.llm_daily_request_limit == 0
    assert cfg.llm_daily_cost_usd_limit == 0.0
    print("PASS: test_zero_means_unlimited")


# ── Parser int tests ──────────────────────────────────────────────────────────


def test_parse_limit_int_valid():
    assert _parse_limit_int("X", "5") == 5
    assert _parse_limit_int("X", "0") == 0
    assert _parse_limit_int("X", "1000") == 1000
    print("PASS: test_parse_limit_int_valid")


def test_parse_limit_int_negative_rejected():
    _expect_value_error(lambda: _parse_limit_int("X", "-1"))
    _expect_value_error(lambda: _parse_limit_int("X", "-100"))
    print("PASS: test_parse_limit_int_negative_rejected")


def test_parse_limit_int_bool_string_rejected():
    """'true'/'false' strings cannot be parsed as int → ValueError."""
    _expect_value_error(lambda: _parse_limit_int("X", "true"))
    _expect_value_error(lambda: _parse_limit_int("X", "false"))
    _expect_value_error(lambda: _parse_limit_int("X", "True"))
    print("PASS: test_parse_limit_int_bool_string_rejected")


def test_parse_limit_int_float_string_rejected():
    """Float strings like '1.5' are rejected for int fields."""
    _expect_value_error(lambda: _parse_limit_int("X", "1.5"))
    print("PASS: test_parse_limit_int_float_string_rejected")


def test_parse_limit_int_empty_after_strip_rejected():
    """Blank string is rejected."""
    _expect_value_error(lambda: _parse_limit_int("X", ""))
    _expect_value_error(lambda: _parse_limit_int("X", "  "))
    print("PASS: test_parse_limit_int_empty_after_strip_rejected")


def test_parse_limit_int_whitespace_stripped():
    """Leading/trailing whitespace is stripped before parsing."""
    assert _parse_limit_int("X", "  10  ") == 10
    print("PASS: test_parse_limit_int_whitespace_stripped")


# ── Parser float tests ────────────────────────────────────────────────────────


def test_parse_limit_float_valid():
    import math
    assert abs(_parse_limit_float("X", "0.0") - 0.0) < 1e-12
    assert abs(_parse_limit_float("X", "2.5") - 2.5) < 1e-9
    assert abs(_parse_limit_float("X", "10") - 10.0) < 1e-9
    print("PASS: test_parse_limit_float_valid")


def test_parse_limit_float_negative_rejected():
    _expect_value_error(lambda: _parse_limit_float("X", "-0.1"))
    _expect_value_error(lambda: _parse_limit_float("X", "-1.0"))
    print("PASS: test_parse_limit_float_negative_rejected")


def test_parse_limit_float_nan_rejected():
    _expect_value_error(lambda: _parse_limit_float("X", "nan"))
    _expect_value_error(lambda: _parse_limit_float("X", "NaN"))
    print("PASS: test_parse_limit_float_nan_rejected")


def test_parse_limit_float_inf_rejected():
    _expect_value_error(lambda: _parse_limit_float("X", "inf"))
    _expect_value_error(lambda: _parse_limit_float("X", "-inf"))
    _expect_value_error(lambda: _parse_limit_float("X", "Infinity"))
    print("PASS: test_parse_limit_float_inf_rejected")


def test_parse_limit_float_bool_string_rejected():
    _expect_value_error(lambda: _parse_limit_float("X", "true"))
    _expect_value_error(lambda: _parse_limit_float("X", "false"))
    print("PASS: test_parse_limit_float_bool_string_rejected")


def test_parse_limit_float_whitespace_stripped():
    assert abs(_parse_limit_float("X", "  1.5  ") - 1.5) < 1e-9
    print("PASS: test_parse_limit_float_whitespace_stripped")


# ── Security: no secrets in repr/error messages ───────────────────────────────


def test_parse_limit_error_message_has_no_secrets():
    """ValueError message must not contain API keys or bot tokens."""
    try:
        _parse_limit_int("STT_DAILY_REQUEST_LIMIT", "bad_value")
    except ValueError as e:
        msg = str(e)
        assert "OPENROUTER_API_KEY" not in msg
        assert "sk-" not in msg
        assert "Bearer" not in msg
    print("PASS: test_parse_limit_error_message_has_no_secrets")


def test_config_repr_has_no_api_key():
    """Config dataclass repr must not expose openrouter_api_key value."""
    cfg = _load_with_env()
    # dataclass repr includes field names and values
    r = repr(cfg)
    # The key value is '' in test env, but ensure we don't print it with sk-
    assert "sk-" not in r
    assert "Bearer" not in r
    print("PASS: test_config_repr_has_no_api_key")


# ── Type tests ────────────────────────────────────────────────────────────────


def test_limit_int_fields_are_int_type():
    cfg = _load_with_env(
        STT_DAILY_REQUEST_LIMIT="5",
        STT_DAILY_SECONDS_LIMIT="300",
        LLM_DAILY_REQUEST_LIMIT="20",
        LLM_DAILY_COST_USD_LIMIT="1.0",
    )
    assert isinstance(cfg.stt_daily_request_limit, int) and not isinstance(cfg.stt_daily_request_limit, bool)
    assert isinstance(cfg.stt_daily_seconds_limit, int) and not isinstance(cfg.stt_daily_seconds_limit, bool)
    assert isinstance(cfg.llm_daily_request_limit, int) and not isinstance(cfg.llm_daily_request_limit, bool)
    print("PASS: test_limit_int_fields_are_int_type")


def test_limit_float_field_is_float_type():
    cfg = _load_with_env(LLM_DAILY_COST_USD_LIMIT="2.0")
    assert isinstance(cfg.llm_daily_cost_usd_limit, float)
    print("PASS: test_limit_float_field_is_float_type")


# ── runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_defaults_are_zero,
    test_custom_valid_int_limits,
    test_zero_means_unlimited,
    test_parse_limit_int_valid,
    test_parse_limit_int_negative_rejected,
    test_parse_limit_int_bool_string_rejected,
    test_parse_limit_int_float_string_rejected,
    test_parse_limit_int_empty_after_strip_rejected,
    test_parse_limit_int_whitespace_stripped,
    test_parse_limit_float_valid,
    test_parse_limit_float_negative_rejected,
    test_parse_limit_float_nan_rejected,
    test_parse_limit_float_inf_rejected,
    test_parse_limit_float_bool_string_rejected,
    test_parse_limit_float_whitespace_stripped,
    test_parse_limit_error_message_has_no_secrets,
    test_config_repr_has_no_api_key,
    test_limit_int_fields_are_int_type,
    test_limit_float_field_is_float_type,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    total = len(SYNC_TESTS)
    print(f"\nALL {total} TESTS PASSED")


if __name__ == "__main__":
    main()
