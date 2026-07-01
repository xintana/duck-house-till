"""Duck House Cafe order till — web app.

Run:  py app.py
Then open the printed URL on this laptop, or on your phone using the
LAN address shown (same Wi-Fi).
"""

from __future__ import annotations

import io
import os
import socket
from pathlib import Path

from flask import Flask, jsonify, request, render_template, send_file

import config
import db
import export

app = Flask(__name__)


def _db_path() -> str:
    """Resolve the data file.

    Priority: SALES_DB_PATH env var (used when deployed online, see DEPLOY.md)
    -> the per-laptop configured path -> a local file next to this script.
    """
    path = os.environ.get("SALES_DB_PATH") or config.get_db_path()
    if not path:
        path = str(Path(__file__).with_name("sales.db"))
        config.set_db_path(path)
    db.init_db(path)
    return path


def _today() -> str:
    """Today's date in Thailand local time, regardless of the server's own timezone."""
    return db.today_local()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/menu")
def api_menu():
    include_inactive = request.args.get("all") == "1"
    return jsonify(db.get_menu(_db_path(), include_inactive=include_inactive))


@app.post("/api/menu")
def api_create_menu_item():
    data = request.get_json(silent=True) or {}
    try:
        item_id = db.create_menu_item(
            _db_path(),
            category=data.get("category", ""),
            name=data.get("name", ""),
            temperature=data.get("temperature", ""),
            price=data.get("price"),
            is_custom=bool(data.get("is_custom", False)),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": item_id})


@app.patch("/api/menu/<int:item_id>")
def api_update_menu_item(item_id: int):
    data = request.get_json(silent=True) or {}
    try:
        db.update_menu_item(_db_path(), item_id, **data)
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.delete("/api/menu/<int:item_id>")
def api_delete_menu_item(item_id: int):
    db.delete_menu_item(_db_path(), item_id)
    return jsonify({"ok": True})


@app.get("/api/summary")
def api_summary():
    day = request.args.get("date") or _today()
    return jsonify(db.get_day_summary(_db_path(), day))


@app.get("/api/orders")
def api_orders():
    day = request.args.get("date") or _today()
    return jsonify(db.get_orders_for_date(_db_path(), day))


@app.post("/api/orders")
def api_create_order():
    data = request.get_json(silent=True) or {}
    try:
        order_id = db.create_order(
            _db_path(),
            lines=data.get("lines", []),
            payment_method=data.get("payment_method", ""),
            comment=data.get("comment", ""),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": order_id, "summary": db.get_day_summary(_db_path(), _today())})


@app.delete("/api/orders/<int:order_id>")
def api_delete_order(order_id: int):
    db.delete_order(_db_path(), order_id)
    return jsonify({"ok": True, "summary": db.get_day_summary(_db_path(), _today())})


def _month() -> str:
    return request.args.get("month") or db.today_local()[:7]


@app.get("/api/summary/day")
def api_day_summary():
    day = request.args.get("date") or _today()
    return jsonify(db.get_day_detail(_db_path(), day))


@app.get("/api/summary/month")
def api_month_summary():
    return jsonify(db.get_month_summary(_db_path(), _month()))


@app.get("/api/export/excel")
def api_export_excel():
    month = _month()
    summary = db.get_month_summary(_db_path(), month)
    orders = db.get_orders_for_month(_db_path(), month)
    data = export.build_excel(summary, orders)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=f"sales-{month}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/export/pdf")
def api_export_pdf():
    month = _month()
    summary = db.get_month_summary(_db_path(), month)
    orders = db.get_orders_for_month(_db_path(), month)
    data = export.build_pdf(summary, orders)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=f"sales-{month}.pdf",
        mimetype="application/pdf",
    )


def _lan_ip() -> str:
    """Best-effort LAN IP so the user can reach the till from their phone."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    path = _db_path()
    ip = _lan_ip()
    port = int(os.environ.get("PORT", 5000))
    print("=" * 56)
    print("  Duck House Cafe - order till is running")
    print(f"  Data file : {path}")
    print(f"  This laptop : http://127.0.0.1:{port}")
    print(f"  Phone (same Wi-Fi): http://{ip}:{port}")
    print("  Press CTRL+C to stop.")
    print("=" * 56)
    app.run(host="0.0.0.0", port=port, debug=False)
