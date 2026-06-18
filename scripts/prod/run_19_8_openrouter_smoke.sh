#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_DIR="/opt/time-agent"
readonly TARGET_BRANCH="main"
readonly MINIMUM_BASE_HEAD="5d8f064"
readonly CONTAINER="time_agent_bot"
readonly DB_PATH="/app/data/app.db"
readonly ENV_FILE=".env"
readonly ENV_BACKUP=".env.backup_pre_19_8_openrouter"
readonly REQUEST_LIMIT="10"
readonly COST_LIMIT="0.05"

say() {
    printf '%s\n' "$*"
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_project_dir() {
    local current_dir
    current_dir="$(pwd -P)"
    [[ "$current_dir" == "$PROJECT_DIR" ]] || \
        die "Run this script only from $PROJECT_DIR"
    [[ -f "$ENV_FILE" ]] || die "$PROJECT_DIR/$ENV_FILE not found"
    [[ "$(git rev-parse --show-toplevel 2>/dev/null)" == "$PROJECT_DIR" ]] || \
        die "$PROJECT_DIR is not the Git worktree root"
}

require_runtime_commands() {
    require_command git
    require_command docker
    require_command awk
    require_command grep
    require_command date
    docker compose version >/dev/null 2>&1 || die "docker compose is unavailable"
}

read_env_value() {
    local key="$1"
    local value first last

    value="$(awk -v wanted="$key" '
        $0 ~ "^[[:space:]]*" wanted "[[:space:]]*=" {
            line = $0
            sub("^[[:space:]]*" wanted "[[:space:]]*=[[:space:]]*", "", line)
            found = line
        }
        END {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", found)
            printf "%s", found
        }
    ' "$ENV_FILE")"

    if (( ${#value} >= 2 )); then
        first="${value:0:1}"
        last="${value: -1}"
        if [[ ( "$first" == '"' && "$last" == '"' ) || \
              ( "$first" == "'" && "$last" == "'" ) ]]; then
            value="${value:1:${#value}-2}"
        fi
    fi

    printf '%s' "$value"
}

set_env_value() {
    local key="$1"
    local value="$2"
    local tmp

    tmp="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
    if ! awk -v wanted="$key" -v replacement="$value" '
        BEGIN { written = 0 }
        $0 ~ "^[[:space:]]*" wanted "[[:space:]]*=" {
            if (!written) {
                print wanted "=" replacement
                written = 1
            }
            next
        }
        { print }
        END {
            if (!written) {
                print wanted "=" replacement
            }
        }
    ' "$ENV_FILE" >"$tmp"; then
        rm -f -- "$tmp"
        die "Failed to prepare safe $ENV_FILE update"
    fi

    chmod --reference="$ENV_FILE" "$tmp"
    mv -f -- "$tmp" "$ENV_FILE"
}

require_target_checkout() {
    local branch head remote_head
    branch="$(git branch --show-current)"
    head="$(git rev-parse --short=7 HEAD)"
    remote_head="$(git rev-parse --short=7 origin/$TARGET_BRANCH)"
    [[ "$branch" == "$TARGET_BRANCH" ]] || \
        die "Expected branch $TARGET_BRANCH, found $branch"
    [[ "$head" == "$remote_head" ]] || \
        die "Expected local HEAD to match origin/$TARGET_BRANCH ($remote_head), found $head"
    git merge-base --is-ancestor "$MINIMUM_BASE_HEAD" HEAD || \
        die "Expected HEAD to contain base commit $MINIMUM_BASE_HEAD"
    say "Git branch/head: $branch $head (matches origin/$TARGET_BRANCH)"
    say "Base commit present: $MINIMUM_BASE_HEAD"
}

require_container_running() {
    local running
    running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
    [[ "$running" == "true" ]] || die "Container $CONTAINER is not running"
    say "Container: $CONTAINER running"
}

run_db_python() {
    # All production DB access stays inside the application container.
    docker exec -i time_agent_bot python - "$DB_PATH"
}

check_db_structure() {
    run_db_python <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
required_tables = {
    "api_usage",
    "capture_drafts",
    "daily_target_definitions",
    "daily_target_progress",
}

with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise SystemExit("DB integrity check failed")

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(required_tables - tables)
    if missing:
        raise SystemExit("Missing required DB tables: " + ", ".join(missing))

    capture_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(capture_drafts)")
    }
    if "advisor_proposal_json" not in capture_columns:
        raise SystemExit("capture_drafts.advisor_proposal_json is missing")

print("DB integrity: ok")
print("Required DB tables: present")
print("capture_drafts.advisor_proposal_json: present")
PY
}

check_key_and_limits() {
    local key request_limit cost_limit
    key="$(read_env_value OPENROUTER_API_KEY)"
    request_limit="$(read_env_value LLM_DAILY_REQUEST_LIMIT)"
    cost_limit="$(read_env_value LLM_DAILY_COST_USD_LIMIT)"

    [[ -n "$key" ]] || die \
        "OPENROUTER_API_KEY is missing. Owner must add it manually to $PROJECT_DIR/$ENV_FILE."
    say "OPENROUTER_API_KEY present: yes"

    [[ "$request_limit" =~ ^[0-9]+$ ]] || \
        die "LLM_DAILY_REQUEST_LIMIT must be a non-negative integer"
    (( request_limit > 0 )) || die "LLM_DAILY_REQUEST_LIMIT=0 is unsafe for this smoke"

    [[ "$cost_limit" =~ ^[0-9]+([.][0-9]+)?$ ]] || \
        die "LLM_DAILY_COST_USD_LIMIT must be a non-negative decimal"
    awk -v value="$cost_limit" 'BEGIN { exit !((value + 0) > 0) }' || \
        die "LLM_DAILY_COST_USD_LIMIT=0.0 is unsafe for this smoke"

    say "LLM_DAILY_REQUEST_LIMIT: $request_limit"
    say "LLM_DAILY_COST_USD_LIMIT: $cost_limit"
    if [[ "$request_limit" != "$REQUEST_LIMIT" || "$cost_limit" != "$COST_LIMIT" ]]; then
        say "Recommended smoke limits: requests=$REQUEST_LIMIT cost_usd=$COST_LIMIT"
    fi
}

assert_no_traceback() {
    local logs
    logs="$(docker logs --since 2m "$CONTAINER" 2>&1 || true)"
    if grep -q 'Traceback' <<<"$logs"; then
        unset logs
        die "Traceback detected in recent $CONTAINER logs"
    fi
    unset logs
    say "Recent logs: no Traceback"
}

wait_for_stable_container() {
    local attempt running restarts_before restarts_after

    for attempt in $(seq 1 30); do
        running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
        [[ "$running" == "true" ]] && break
        sleep 1
    done
    [[ "${running:-}" == "true" ]] || die "Container $CONTAINER did not become running"

    restarts_before="$(docker inspect --format '{{.RestartCount}}' "$CONTAINER")"
    sleep 5
    running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER")"
    restarts_after="$(docker inspect --format '{{.RestartCount}}' "$CONTAINER")"

    [[ "$running" == "true" ]] || die "Container $CONTAINER stopped after restart"
    [[ "$restarts_after" == "$restarts_before" ]] || \
        die "Container restart count is not stable"
    say "Container running; restart count stable at $restarts_after"
}

backup_database() {
    local timestamp backup_path
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup_path="/app/data/backups/app.db.pre-19.8.${timestamp}.backup"

    docker exec -i time_agent_bot python - "$DB_PATH" "$backup_path" <<'PY'
import os
import sqlite3
import sys

source_path, backup_path = sys.argv[1:3]
os.makedirs(os.path.dirname(backup_path), mode=0o700, exist_ok=True)
if os.path.exists(backup_path):
    raise SystemExit("Refusing to overwrite existing DB backup")

with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise SystemExit("DB backup integrity check failed")

os.chmod(backup_path, 0o600)
print("DB backup integrity: ok")
print("DB backup: " + backup_path)
PY
}

verify_usage_schema_and_rows() {
    run_db_python <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
forbidden = {"prompt", "response", "transcript", "user_text", "raw_text"}
required_usage = {
    "provider",
    "service_type",
    "model",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "status",
}

with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise SystemExit("DB integrity check failed")

    usage_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(api_usage)")
    }
    present_forbidden = sorted(forbidden & usage_columns)
    if present_forbidden:
        raise SystemExit(
            "Forbidden api_usage columns present: " + ", ".join(present_forbidden)
        )
    missing_usage = sorted(required_usage - usage_columns)
    if missing_usage:
        raise SystemExit(
            "Required api_usage columns missing: " + ", ".join(missing_usage)
        )

    capture_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(capture_drafts)")
    }
    if "advisor_proposal_json" not in capture_columns:
        raise SystemExit("capture_drafts.advisor_proposal_json is missing")

    rows = conn.execute(
        """
        SELECT provider, service_type, model, input_tokens, output_tokens,
               estimated_cost_usd, status
        FROM api_usage
        WHERE service_type = 'llm'
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

print("DB integrity: ok")
print("api_usage privacy schema: ok")
print("capture_drafts.advisor_proposal_json: present")
print("Last LLM usage rows (technical fields only):")
if not rows:
    print("  none")
else:
    for row in rows:
        provider, service_type, model, input_tokens, output_tokens, cost, status = row
        print(
            "  provider={} service_type={} model={} input_tokens={} "
            "output_tokens={} estimated_cost_usd={:.8f} status={}".format(
                provider,
                service_type,
                model,
                input_tokens,
                output_tokens,
                cost,
                status,
            )
        )
PY
}

cmd_precheck() {
    require_project_dir
    require_runtime_commands
    require_target_checkout
    require_container_running
    check_db_structure
    check_key_and_limits
    say "Precheck: PASS"
}

cmd_enable() {
    cmd_precheck
    [[ ! -e "$ENV_BACKUP" ]] || \
        die "$ENV_BACKUP already exists; run disable or resolve it manually first"

    backup_database
    cp -p -- "$ENV_FILE" "$ENV_BACKUP"
    chmod 600 "$ENV_BACKUP"
    say "Environment backup created: $ENV_BACKUP"

    set_env_value ADVISOR_PROVIDER openrouter
    set_env_value LLM_DAILY_REQUEST_LIMIT "$REQUEST_LIMIT"
    set_env_value LLM_DAILY_COST_USD_LIMIT "$COST_LIMIT"
    say "Safe advisor settings applied; secret values were not read or changed"

    docker compose up -d --no-deps bot
    wait_for_stable_container
    assert_no_traceback
    say "Advisor enabled with controlled limits"
}

cmd_verify() {
    local provider request_limit cost_limit key

    require_project_dir
    require_runtime_commands
    require_target_checkout
    require_container_running

    provider="$(read_env_value ADVISOR_PROVIDER)"
    request_limit="$(read_env_value LLM_DAILY_REQUEST_LIMIT)"
    cost_limit="$(read_env_value LLM_DAILY_COST_USD_LIMIT)"
    key="$(read_env_value OPENROUTER_API_KEY)"

    [[ "$provider" == "openrouter" ]] || die "ADVISOR_PROVIDER is not openrouter"
    [[ "$request_limit" == "$REQUEST_LIMIT" ]] || \
        die "Unexpected LLM_DAILY_REQUEST_LIMIT"
    [[ "$cost_limit" == "$COST_LIMIT" ]] || \
        die "Unexpected LLM_DAILY_COST_USD_LIMIT"

    say "ADVISOR_PROVIDER=openrouter"
    say "LLM_DAILY_REQUEST_LIMIT=$request_limit"
    say "LLM_DAILY_COST_USD_LIMIT=$cost_limit"
    if [[ -n "$key" ]]; then
        say "OPENROUTER_API_KEY present: yes"
    else
        say "OPENROUTER_API_KEY present: no"
    fi

    verify_usage_schema_and_rows
    assert_no_traceback

    cat <<'CHECKLIST'
Telegram smoke checklist (perform manually, one item at a time):
  1. /health
  2. Купить молоко -> old rules path
  3. Cancel
  4. Вода +500 мл -> daily targets, not advisor
  5. /targets
  6. как пользоваться ботом -> advisor help
  7. Cancel
  8. что ты умеешь -> advisor help
  9. Cancel
 10. хочу 2 литра воды -> advisor settings proposal
 11. Применить (AI) -> stub, no target mutation
 12. ок -> advisor clarification
CHECKLIST
}

cmd_disable() {
    local provider

    require_project_dir
    require_runtime_commands

    if [[ -f "$ENV_BACKUP" ]]; then
        mv -f -- "$ENV_BACKUP" "$ENV_FILE"
        say "Environment restored from $ENV_BACKUP"
    else
        set_env_value ADVISOR_PROVIDER disabled
        say "Environment backup absent; advisor disabled in $ENV_FILE"
    fi

    provider="$(read_env_value ADVISOR_PROVIDER)"
    if [[ "$provider" != "disabled" ]]; then
        set_env_value ADVISOR_PROVIDER disabled
        say "Restored environment required a safety override: advisor disabled"
    fi

    docker compose up -d --no-deps bot
    wait_for_stable_container
    assert_no_traceback

    provider="$(read_env_value ADVISOR_PROVIDER)"
    [[ "$provider" == "disabled" ]] || die "Failed to disable advisor"
    say "ADVISOR_PROVIDER=disabled"
    say "Advisor disabled: PASS"
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/prod/run_19_8_openrouter_smoke.sh precheck
  ./scripts/prod/run_19_8_openrouter_smoke.sh enable
  ./scripts/prod/run_19_8_openrouter_smoke.sh verify
  ./scripts/prod/run_19_8_openrouter_smoke.sh disable
USAGE
}

[[ $# -eq 1 ]] || {
    usage >&2
    exit 2
}

case "$1" in
    precheck) cmd_precheck ;;
    enable) cmd_enable ;;
    verify) cmd_verify ;;
    disable) cmd_disable ;;
    *)
        usage >&2
        exit 2
        ;;
esac
