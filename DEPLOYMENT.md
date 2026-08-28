# HR Accounts — V1 Deployment & Operational Guide

## System Requirements
- **Runtime**: Python 3.10+
- **Port**: `8004`

## Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8004` | Uvicorn port |
| `ACCOUNTS_DB_PATH` | `accounts.db` | SQLite database path |

## Startup Commands
```bash
# Development
python3 -m uvicorn src.app:app --host 0.0.0.0 --port 8004 --reload

# Production
python3 -m uvicorn src.app:app --host 0.0.0.0 --port 8004 --workers 2
```

## Health Check
```bash
curl http://127.0.0.1:8004/api/health
```

## Backup
```bash
sqlite3 accounts.db ".backup 'accounts_snapshot_$(date +%Y%m%d).db'"
curl -s http://127.0.0.1:8004/api/export/json > accounts_backup.json
```

## Notes
- The `accounts.db` file contains live invoice, payment, and client data. Back up before any schema changes.
- Printable PDF invoices are generated server-side as HTML; no external PDF library required in V1.
