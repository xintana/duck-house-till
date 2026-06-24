# Deploy online — so the phone works anywhere (not just same Wi-Fi)

This is the planned next step, captured so today's code stays compatible with it.

## Why it's needed
Right now the till runs on the laptop and the phone reaches it over the **same
Wi-Fi** (`http://192.168.x.x:5000`). To use it on mobile data or from another
location, the app must run on a host that's always online, with a public URL.

## The one real change: where the data lives
Online hosts cannot see `G:\My Drive\SalesTracker\sales.db` (that's a local
Google Drive folder). So deploying online means the database has to move too.
The code already supports this — the DB path is read from the `SALES_DB_PATH`
environment variable, falling back to the configured local path:

- **Local (today):** `SALES_DB_PATH` unset → uses Google Drive file.
- **Hosted:** set `SALES_DB_PATH` to a path on the host's persistent disk, OR
  swap `db.py` to a hosted database (Postgres/Turso). The functions in `db.py`
  are the only place that touches storage, so this is a contained change.

## Recommended host options (single-user, low/zero cost)
1. **Render / Railway / Fly.io** — run this Flask app directly. Add a small
   persistent disk for `sales.db`, or attach their free Postgres.
2. **Turso (libSQL)** — keep SQLite-style code, but the DB is hosted and
   reachable from anywhere. Smallest change to `db.py`.

## Production server (not the dev server)
The current `app.py` uses Flask's built-in dev server (fine for the counter
laptop). For a public deploy, run behind a production server:
- `pip install waitress` then `waitress-serve --port=$PORT app:app`, or
- `gunicorn app:app` on Linux hosts.

## Checklist when we do it
- [ ] Move/seed data into the hosted DB
- [ ] Set `SALES_DB_PATH` (or hosted DB credentials)
- [ ] Add a production WSGI server (waitress/gunicorn)
- [ ] Add a simple password/PIN screen (public URL = needs basic protection)
- [ ] Point phone at the new public URL; keep Google Drive as a backup export
