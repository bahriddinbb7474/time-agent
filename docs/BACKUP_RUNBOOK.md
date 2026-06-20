# Backup Runbook — Time-Agent Production Finish

> Historical references to Stage 22.1 mean the backup work now consolidated into
> Stage 23 Production finish. The operational commands remain valid.

## What this does

A nightly APScheduler job creates a gzip-compressed SQLite backup, runs
`PRAGMA integrity_check` on the copy, and sends the `.sqlite.gz` file to
the owner's Telegram chat. Old local backups beyond the retention window
are deleted automatically. Nothing touches production data/app.db after
the backup copy is written.

## Env vars

| Variable | Default | Description |
|---|---|---|
| `BACKUP_ENABLED` | `false` | Set to `true` to enable the nightly job |
| `BACKUP_TELEGRAM_CHAT_ID` | *(empty)* | Chat ID to send backup to. Falls back to `ALLOWED_TELEGRAM_ID` if unset |
| `BACKUP_HOUR` | `2` | Hour of backup in Asia/Tashkent TZ |
| `BACKUP_MINUTE` | `30` | Minute of backup |
| `BACKUP_RETENTION_DAYS` | `7` | Local files older than this are deleted. `0` = keep all |
| `BACKUP_DIR` | `data/backups` | Directory for local backup files |

**Defaults are safe**: backup is disabled unless `BACKUP_ENABLED=true` is set.

## How to enable (VPS)

Add to `/opt/time-agent-secrets/bot.env` (or the relevant `.env` override):

```env
BACKUP_ENABLED=true
BACKUP_HOUR=2
BACKUP_MINUTE=30
BACKUP_RETENTION_DAYS=7
```

Then restart the container:

```bash
docker compose up -d --no-deps bot
```

The backup job will appear in the scheduler logs at startup:
```
Nightly backup scheduled at 02:30 TZ=Asia/Tashkent
```

## How to verify restore (restore_check utility)

Run from the project root against a backup file:

```bash
python -m app.db.restore_check data/backups/app.db.20260616_020000.sqlite.gz
```

Expected output for a good backup:
```
Checking: app.db.20260616_020000.sqlite.gz
OK: integrity_check = ok
OK: schema_migrations = 5 version(s)
  - 20260101_0000_baseline_pre_stage14
  - 20260609_1300_add_daily_plan_lifecycle
  - 20260612_0300_add_capture_drafts
  - 20260614_2000_add_api_usage
  - 20260615_1000_add_token_usage

PASS: app.db.20260616_020000.sqlite.gz
```

Exit code 0 = PASS, exit code 1 = FAIL.

## What NOT to do

- Do not run `BACKUP_ENABLED=true` without also ensuring `ALLOWED_TELEGRAM_ID`
  or `BACKUP_TELEGRAM_CHAT_ID` is set — the job skips silently if no chat ID is available.
- Do not run the restore_check utility against production `data/app.db` directly —
  it is for backup files (`.sqlite.gz`) only.
- Do not commit `data/backups/` to git.
- Do not manually delete `data/backups/` on VPS while the bot is running —
  use `BACKUP_RETENTION_DAYS` to control cleanup.
- Do not change `BACKUP_DIR` to point inside `data/` at a path that conflicts
  with `data/app.db` or `data/app.db.pre-*.backup` files.

## Backup file naming

```
data/backups/app.db.YYYYMMDD_HHMMSS.sqlite.gz
```

Timestamp is UTC. The file is a gzip-compressed SQLite database that can be
opened with `sqlite3` after decompression:

```bash
gunzip -k app.db.20260616_020000.sqlite.gz
sqlite3 app.db.20260616_020000.sqlite "PRAGMA integrity_check;"
```
