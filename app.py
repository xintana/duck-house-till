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
import cost
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
    cost.init_db(path)
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
    # If this basket came off the hold shelf, clear it here rather than in a
    # second request — a dropped follow-up call would leave the bill parked and
    # risk it being charged to the customer twice.
    held_id = data.get("held_id")
    if held_id is not None:
        db.delete_held_order(_db_path(), int(held_id))
    return jsonify({
        "id": order_id,
        "summary": db.get_day_summary(_db_path(), _today()),
        "held": db.get_held_orders(_db_path()),
    })


@app.delete("/api/orders/<int:order_id>")
def api_delete_order(order_id: int):
    db.delete_order(_db_path(), order_id)
    return jsonify({"ok": True, "summary": db.get_day_summary(_db_path(), _today())})


# ---- held (parked) bills ---------------------------------------------------

@app.get("/api/held")
def api_held_orders():
    return jsonify(db.get_held_orders(_db_path()))


@app.post("/api/held")
def api_hold_order():
    """Park the current basket so the cashier can serve the next customer."""
    data = request.get_json(silent=True) or {}
    try:
        held_id = db.hold_order(
            _db_path(),
            lines=data.get("lines", []),
            payment_method=data.get("payment_method", ""),
            comment=data.get("comment", ""),
            label=data.get("label", ""),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": held_id, "held": db.get_held_orders(_db_path())})


@app.put("/api/held/<int:held_id>")
def api_update_held_order(held_id: int):
    """Re-park a bill that was resumed and then held again."""
    if db.get_held_order(_db_path(), held_id) is None:
        return jsonify({"error": "That held bill no longer exists."}), 404
    data = request.get_json(silent=True) or {}
    try:
        db.update_held_order(
            _db_path(),
            held_id,
            lines=data.get("lines", []),
            payment_method=data.get("payment_method", ""),
            comment=data.get("comment", ""),
            label=data.get("label", ""),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": held_id, "held": db.get_held_orders(_db_path())})


@app.delete("/api/held/<int:held_id>")
def api_delete_held_order(held_id: int):
    db.delete_held_order(_db_path(), held_id)
    return jsonify({"ok": True, "held": db.get_held_orders(_db_path())})


def _month() -> str:
    return request.args.get("month") or db.today_local()[:7]


def _year() -> str:
    return request.args.get("year") or db.today_local()[:4]


def _export_period() -> tuple[str, dict, list[dict]]:
    """Resolve the requested export period into (file stem, summary, orders).

    A `year` query param switches both exports to the whole-year report; with
    no `year` they stay on the month, so existing links keep working.
    """
    path = _db_path()
    if request.args.get("year"):
        year = _year()
        return f"sales-{year}", db.get_year_summary(path, year), db.get_orders_for_year(path, year)
    month = _month()
    return f"sales-{month}", db.get_month_summary(path, month), db.get_orders_for_month(path, month)


@app.get("/api/summary/day")
def api_day_summary():
    day = request.args.get("date") or _today()
    return jsonify(db.get_day_detail(_db_path(), day))


@app.get("/api/summary/month")
def api_month_summary():
    return jsonify(db.get_month_summary(_db_path(), _month()))


@app.get("/api/summary/year")
def api_year_summary():
    return jsonify(db.get_year_summary(_db_path(), _year()))


@app.get("/api/export/excel")
def api_export_excel():
    stem, summary, orders = _export_period()
    data = export.build_excel(summary, orders)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=f"{stem}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/export/pdf")
def api_export_pdf():
    stem, summary, orders = _export_period()
    data = export.build_pdf(summary, orders)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=f"{stem}.pdf",
        mimetype="application/pdf",
    )


# ---- ingredient costs ------------------------------------------------------

def _cost_period() -> str:
    """The sale_date/buy_date prefix asked for: a day, a month, or a year."""
    if request.args.get("date"):
        return request.args["date"]
    if request.args.get("year"):
        return request.args["year"]
    return request.args.get("month") or db.today_local()[:7]


@app.get("/api/ingredients")
def api_ingredients():
    include_inactive = request.args.get("all") == "1"
    return jsonify({
        "units": {u: {"family": fam, "factor": f} for u, (fam, f) in cost.UNITS.items()},
        "ingredients": cost.get_ingredients(_db_path(), include_inactive=include_inactive),
    })


@app.post("/api/ingredients")
def api_create_ingredient():
    data = request.get_json(silent=True) or {}
    try:
        ing_id = cost.create_ingredient(
            _db_path(),
            name=data.get("name", ""),
            unit=data.get("unit", ""),
            note=data.get("note", ""),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": ing_id})


@app.patch("/api/ingredients/<int:ingredient_id>")
def api_update_ingredient(ingredient_id: int):
    data = request.get_json(silent=True) or {}
    try:
        cost.update_ingredient(_db_path(), ingredient_id, **data)
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.delete("/api/ingredients/<int:ingredient_id>")
def api_delete_ingredient(ingredient_id: int):
    cost.delete_ingredient(_db_path(), ingredient_id)
    return jsonify({"ok": True})


@app.get("/api/ingredients/<int:ingredient_id>/usage")
def api_ingredient_usage(ingredient_id: int):
    """Which menu items use this ingredient, and how much each one takes."""
    return jsonify({
        "menu_items": cost.get_ingredient_usage(_db_path(), ingredient_id),
        "purchases": cost.get_purchases(_db_path(), ingredient_id=ingredient_id, limit=20),
    })


@app.get("/api/purchases")
def api_purchases():
    ing = request.args.get("ingredient_id", type=int)
    limit = request.args.get("limit", default=60, type=int)
    return jsonify(cost.get_purchases(_db_path(), ingredient_id=ing, limit=limit))


@app.post("/api/purchases")
def api_add_purchase():
    """Log one shopping trip: 'How much did we buy this time, and for how much?'"""
    data = request.get_json(silent=True) or {}
    try:
        result = cost.add_purchase(
            _db_path(),
            ingredient_id=int(data["ingredient_id"]),
            packs=data.get("packs", 1),
            pack_size=data["pack_size"],
            pack_unit=data.get("pack_unit", ""),
            total_price=data["total_price"],
            buy_date=data.get("buy_date"),
            note=data.get("note", ""),
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.delete("/api/purchases/<int:purchase_id>")
def api_delete_purchase(purchase_id: int):
    cost.delete_purchase(_db_path(), purchase_id)
    return jsonify({"ok": True})


@app.get("/api/recipes/<int:menu_item_id>")
def api_recipe(menu_item_id: int):
    try:
        return jsonify(cost.get_recipe(_db_path(), menu_item_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.post("/api/recipes/<int:menu_item_id>")
def api_set_recipe_line(menu_item_id: int):
    """Set how much of one ingredient goes into one serving of this item."""
    data = request.get_json(silent=True) or {}
    try:
        cost.set_recipe_line(
            _db_path(),
            menu_item_id,
            ingredient_id=int(data["ingredient_id"]),
            amount=data["amount"],
        )
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(cost.get_recipe(_db_path(), menu_item_id))


@app.delete("/api/recipes/lines/<int:line_id>")
def api_delete_recipe_line(line_id: int):
    cost.delete_recipe_line(_db_path(), line_id)
    return jsonify({"ok": True})


@app.get("/api/costs/menu")
def api_menu_costs():
    return jsonify(cost.get_menu_costs(_db_path()))


@app.get("/api/costs/period")
def api_period_cost():
    """Ingredient cost of what was sold, and cash actually spent restocking."""
    path, period = _db_path(), _cost_period()
    return jsonify({
        "sold": cost.get_period_cost(path, period),
        "spend": cost.get_spend(path, period),
    })


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
