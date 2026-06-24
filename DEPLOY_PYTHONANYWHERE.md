# Put the till online — PythonAnywhere (free) + GitHub

End result: a public link like `https://YOURNAME.pythonanywhere.com` that works
on any phone, anywhere, with the laptop turned off.

Replace **YOURNAME** with your PythonAnywhere username and **YOURREPO** with the
GitHub repo URL everywhere below.

---

## Part A — Get the code on GitHub (done with help from this chat)
1. Go to https://github.com/new and create a **new empty repo** (no README,
   no .gitignore — leave it blank). Name it e.g. `duck-house-till`.
2. Copy the repo URL (looks like `https://github.com/YOU/duck-house-till.git`).
3. Paste it back in chat — the assistant will connect it and push the code.
   (You may get a one-time GitHub sign-in popup; approve it.)

## Part B — Create a PythonAnywhere account
1. Sign up (free "Beginner" plan) at https://www.pythonanywhere.com/registration/register/beginner/
2. Confirm your email and log in to the **Dashboard**.

## Part C — Pull the code onto PythonAnywhere
1. Dashboard → **Consoles** → start a **Bash** console.
2. Clone your repo:
   ```bash
   git clone YOURREPO
   ```
   This makes a folder, e.g. `~/duck-house-till`.
3. Create a virtual environment and install Flask:
   ```bash
   cd ~/duck-house-till
   python3.10 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Part D — Create the web app
1. Top menu → **Web** → **Add a new web app** → **Next**.
2. Choose **Manual configuration** (NOT "Flask") → pick **Python 3.10** → Next.
3. On the Web tab, set these fields:
   - **Source code:** `/home/YOURNAME/duck-house-till`
   - **Working directory:** `/home/YOURNAME/duck-house-till`
   - **Virtualenv:** `/home/YOURNAME/duck-house-till/.venv`
4. Click the **WSGI configuration file** link (near the top of the Web tab).
   Delete everything in it and paste this, then **Save**:
   ```python
   import os, sys
   PROJECT_HOME = "/home/YOURNAME/duck-house-till"
   if PROJECT_HOME not in sys.path:
       sys.path.insert(0, PROJECT_HOME)
   os.environ["SALES_DB_PATH"] = os.path.join(PROJECT_HOME, "data", "sales.db")
   from app import app as application
   ```
5. Back on the Web tab, click the big green **Reload** button.
6. Open `https://YOURNAME.pythonanywhere.com` — the till is live. 🎉
   The menu seeds automatically on first load.

## Part E — Use it on your phone
- Open the link on your phone, then **Add to Home Screen** for an app-like icon.
- The laptop can be off. Orders save on PythonAnywhere's disk
  (`~/duck-house-till/data/sales.db`).

---

## Updating later (after you change the code)
On your laptop: commit + push the change to GitHub. Then in the PythonAnywhere
Bash console:
```bash
cd ~/duck-house-till && git pull && touch /var/www/YOURNAME_pythonanywhere_com_wsgi.py
```
(The `touch` line tells the site to reload. You can also click **Reload** on the Web tab.)

## Backups
Your data now lives on PythonAnywhere. To keep a copy, periodically download
`data/sales.db` from the **Files** tab, or we can add a one-click CSV export.

## Notes / limits (free plan)
- Free accounts must click a **"Run until 3 months from today"** button on the
  Web tab every ~3 months to keep the app alive — PythonAnywhere emails a reminder.
- Free CPU is limited but plenty for a single cafe till.
- The public URL has no password yet — if you want, we can add a simple PIN screen.
