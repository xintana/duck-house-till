"""SQLite data layer for the Duck House Cafe order till.

Three tables:
  menu_items  — the drinks/desserts the cashier can tap (price built in)
  orders      — one customer transaction (payment + comment + total)
  order_lines — the individual drinks within an order

The DB file path is resolved by config.py so it can live in a cloud folder.
"""

from __future__ import annotations

import calendar
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PAYMENT_METHODS = ("Cash", "Transfer")

# All timestamps recorded/reported by this app use Thailand local time,
# regardless of the timezone the host server (or the cashier's phone) is set to.
TZ = ZoneInfo("Asia/Bangkok")


def now_local() -> datetime:
    return datetime.now(TZ)


def today_local() -> str:
    return now_local().strftime("%Y-%m-%d")

SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    temperature TEXT    NOT NULL DEFAULT '',     -- 'Hot' / 'Iced' / '' (none)
    price       REAL,                            -- NULL for custom-price items
    is_custom   INTEGER NOT NULL DEFAULT 0,      -- 1 = cashier types name+price
    active      INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date      TEXT    NOT NULL,              -- 'YYYY-MM-DD' (local)
    created_at     TEXT    NOT NULL,              -- ISO timestamp (local)
    payment_method TEXT    NOT NULL,
    comment        TEXT    NOT NULL DEFAULT '',
    total          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,                 -- display name (incl. temp / custom)
    temperature TEXT    NOT NULL DEFAULT '',
    quantity    REAL    NOT NULL CHECK (quantity > 0),
    unit_price  REAL    NOT NULL CHECK (unit_price >= 0),
    line_total  REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_date ON orders (sale_date);
CREATE INDEX IF NOT EXISTS idx_lines_order ON order_lines (order_id);
"""

# Menu extracted from Menu.png (Duck House Cafe). Each (item, temperature) with a
# price is one tappable button. Tuple: (category, name, temperature, price).
_MENU_SEED = [
    # Coffee
    ("Coffee", "Espresso", "Hot", 50), ("Coffee", "Espresso", "Iced", 55),
    ("Coffee", "Americano", "Hot", 50), ("Coffee", "Americano", "Iced", 55),
    ("Coffee", "Americano Yuzu", "Iced", 70),
    ("Coffee", "Americano Coconut", "Iced", 70),
    ("Coffee", "Cappuccino", "Hot", 60), ("Coffee", "Cappuccino", "Iced", 65),
    ("Coffee", "Mocha", "Hot", 60), ("Coffee", "Mocha", "Iced", 65),
    ("Coffee", "Latte", "Hot", 60), ("Coffee", "Latte", "Iced", 65),
    ("Coffee", "Vanilla Latte", "Hot", 70), ("Coffee", "Vanilla Latte", "Iced", 75),
    ("Coffee", "Es Yen", "Iced", 60),
    ("Coffee", "Affogato", "Iced", 75),
    # Non-Coffee
    ("Non-Coffee", "Fresh Milk", "Hot", 35), ("Non-Coffee", "Fresh Milk", "Iced", 40),
    ("Non-Coffee", "Honey Milk", "Iced", 50),
    ("Non-Coffee", "Iced Cocoa", "Iced", 65),
    ("Non-Coffee", "Honey Lemon", "Iced", 55),
    ("Non-Coffee", "Honey Lemon Soda", "Iced", 55),
    ("Non-Coffee", "Yuzu Juice", "Iced", 70),
    ("Non-Coffee", "Yuzu Soda", "Iced", 70),
    # Matcha (all iced)
    ("Matcha", "Pure Matcha", "Iced", 65),
    ("Matcha", "Matcha Honey Lemon", "Iced", 75),
    ("Matcha", "Matcha Coconut", "Iced", 75),
    ("Matcha", "Matcha Yuzu", "Iced", 75),
    ("Matcha", "Matcha Latte", "Iced", 75),
    ("Matcha", "Strawberry Matcha Latte", "Iced", 80),
    ("Matcha", "Matcha Latte on Cloud", "Iced", 80),
    ("Matcha", "Matcha Coconut on Cloud", "Iced", 80),
    # Tea (all iced)
    ("Tea", "Thai Milk Tea", "Iced", 60),
    ("Tea", "Ovaltine Thai Tea", "Iced", 65),
    ("Tea", "Assam Milk Tea", "Iced", 50),
]


@contextmanager
def connect(db_path: str | Path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    """Create schema and seed the menu on first run. Safe to call every launch."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        already = conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        if already == 0:
            rows = [
                (cat, name, temp, price, 0, i)
                for i, (cat, name, temp, price) in enumerate(_MENU_SEED)
            ]
            # One custom-price dessert button (name + price typed at order time).
            rows.append(("Dessert", "Dessert", "", None, 1, len(_MENU_SEED)))
            conn.executemany(
                "INSERT INTO menu_items (category, name, temperature, price, "
                "is_custom, sort) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )


# ---- reads -----------------------------------------------------------------

def get_menu(db_path: str | Path) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM menu_items WHERE active = 1 ORDER BY sort"
        ).fetchall()
        return [dict(r) for r in rows]


def get_orders_for_date(db_path: str | Path, day: str) -> list[dict]:
    """All orders (with their lines) for a given 'YYYY-MM-DD'."""
    with connect(db_path) as conn:
        orders = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM orders WHERE sale_date = ? ORDER BY id DESC", (day,)
            ).fetchall()
        ]
        for o in orders:
            o["lines"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_lines WHERE order_id = ? ORDER BY id",
                    (o["id"],),
                ).fetchall()
            ]
        return orders


def get_day_summary(db_path: str | Path, day: str) -> dict:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue "
            "FROM orders WHERE sale_date = ?",
            (day,),
        ).fetchone()
        by_pm = {
            r["payment_method"]: r["revenue"]
            for r in conn.execute(
                "SELECT payment_method, COALESCE(SUM(total),0) AS revenue "
                "FROM orders WHERE sale_date = ? GROUP BY payment_method",
                (day,),
            ).fetchall()
        }
    return {
        "date": day,
        "orders": row["orders"],
        "revenue": row["revenue"],
        "by_payment": by_pm,
    }


def get_month_summary(db_path: str | Path, year_month: str) -> dict:
    """Sales summary for a whole month ('YYYY-MM'): totals, top-selling items,
    and a per-day breakdown (so the caller can find the busiest day)."""
    year, month = (int(p) for p in year_month.split("-"))
    days_in_month = calendar.monthrange(year, month)[1]
    like = f"{year_month}%"

    with connect(db_path) as conn:
        totals = conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue "
            "FROM orders WHERE sale_date LIKE ?",
            (like,),
        ).fetchone()
        by_pm = {
            r["payment_method"]: r["revenue"]
            for r in conn.execute(
                "SELECT payment_method, COALESCE(SUM(total),0) AS revenue "
                "FROM orders WHERE sale_date LIKE ? GROUP BY payment_method",
                (like,),
            ).fetchall()
        }
        by_day_rows = {
            r["sale_date"]: {"orders": r["orders"], "revenue": r["revenue"]}
            for r in conn.execute(
                "SELECT sale_date, COUNT(*) AS orders, COALESCE(SUM(total),0) AS revenue "
                "FROM orders WHERE sale_date LIKE ? GROUP BY sale_date",
                (like,),
            ).fetchall()
        }
        top_items = [
            dict(r)
            for r in conn.execute(
                "SELECT ol.name AS name, ol.temperature AS temperature, "
                "SUM(ol.quantity) AS quantity, SUM(ol.line_total) AS revenue "
                "FROM order_lines ol JOIN orders o ON o.id = ol.order_id "
                "WHERE o.sale_date LIKE ? "
                "GROUP BY ol.name, ol.temperature ORDER BY quantity DESC LIMIT 10",
                (like,),
            ).fetchall()
        ]

    by_day = []
    for d in range(1, days_in_month + 1):
        day_str = f"{year_month}-{d:02d}"
        rec = by_day_rows.get(day_str, {"orders": 0, "revenue": 0})
        by_day.append({"date": day_str, "day": d, **rec})

    best_day = max(by_day, key=lambda x: x["orders"]) if any(x["orders"] for x in by_day) else None

    return {
        "month": year_month,
        "orders": totals["orders"],
        "revenue": totals["revenue"],
        "by_payment": by_pm,
        "top_items": top_items,
        "by_day": by_day,
        "best_day": best_day,
    }


def get_orders_for_month(db_path: str | Path, year_month: str) -> list[dict]:
    """All orders (with lines) for a given 'YYYY-MM', oldest first — used for exports."""
    like = f"{year_month}%"
    with connect(db_path) as conn:
        orders = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM orders WHERE sale_date LIKE ? ORDER BY sale_date, id",
                (like,),
            ).fetchall()
        ]
        for o in orders:
            o["lines"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_lines WHERE order_id = ? ORDER BY id",
                    (o["id"],),
                ).fetchall()
            ]
        return orders


# ---- writes ----------------------------------------------------------------

def create_order(
    db_path: str | Path,
    lines: list[dict],
    payment_method: str,
    comment: str = "",
) -> int:
    """Save one order. `lines` items need: name, temperature, quantity, unit_price."""
    if not lines:
        raise ValueError("An order needs at least one item.")
    if payment_method not in PAYMENT_METHODS:
        raise ValueError(f"Unknown payment method: {payment_method!r}")

    now = now_local()
    prepared, total = [], 0.0
    for ln in lines:
        qty = float(ln["quantity"])
        unit = float(ln["unit_price"])
        if qty <= 0 or unit < 0:
            raise ValueError("Quantity must be > 0 and price >= 0.")
        line_total = round(qty * unit, 2)
        total += line_total
        prepared.append(
            (ln["name"], ln.get("temperature", ""), qty, unit, line_total)
        )
    total = round(total, 2)

    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO orders (sale_date, created_at, payment_method, comment, "
            "total) VALUES (?, ?, ?, ?, ?)",
            (now.strftime("%Y-%m-%d"), now.isoformat(timespec="seconds"),
             payment_method, comment.strip(), total),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_lines (order_id, name, temperature, quantity, "
            "unit_price, line_total) VALUES (?, ?, ?, ?, ?, ?)",
            [(order_id, *p) for p in prepared],
        )
    return order_id


def delete_order(db_path: str | Path, order_id: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "duckhouse_check.db"
    tmp.unlink(missing_ok=True)
    init_db(tmp)
    print("Menu items seeded:", len(get_menu(tmp)))
    oid = create_order(
        tmp,
        [
            {"name": "Latte (Iced)", "temperature": "Iced", "quantity": 2, "unit_price": 65},
            {"name": "Pudding", "temperature": "", "quantity": 1, "unit_price": 45},
        ],
        "Cash",
        "table 3",
    )
    print("Created order", oid)
    print("Summary:", get_day_summary(tmp, date.today().strftime("%Y-%m-%d")))
    tmp.unlink(missing_ok=True)
