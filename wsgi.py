"""WSGI entry point for PythonAnywhere (and other WSGI hosts).

PythonAnywhere loads a WSGI file from /var/www/<user>_pythonanywhere_com_wsgi.py.
The simplest setup is to make that file's contents identical to this one
(adjusting the path), OR to import from this module. See DEPLOY_PYTHONANYWHERE.md.

It pins the SQLite database to a persistent folder on the host so sales data
survives restarts and redeploys.
"""

import os
import sys

# Folder this file lives in (the cloned repo) = the app's home.
PROJECT_HOME = os.path.dirname(os.path.abspath(__file__))
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# Persistent SQLite location (kept out of git via .gitignore).
os.environ.setdefault(
    "SALES_DB_PATH", os.path.join(PROJECT_HOME, "data", "sales.db")
)

from app import app as application  # noqa: E402  (must come after sys.path setup)
