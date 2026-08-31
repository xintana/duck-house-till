"""Daily stock counts for the Duck House Cafe till.

One row per ingredient per day: how much was physically on the shelf. Because
the app already knows what was bought (cost.ingredient_purchases) and what the
recipes say the day's sales consumed (cost.usage_between), a count can be
checked against an expectation instead of just being filed away:

    expected today = last count + bought since - sold since
    variance       = counted today - expected today

A negative variance is waste, spillage, free staff drinks, or an over-generous
pour; a positive one usually means a delivery was never logged or a recipe
amount is set too high. Either way it is a number worth seeing, which is the
whole reason for counting daily rather than guessing.

Quantities are stored in the ingredient's base unit, like everything else in
cost.py, with what the user actually typed kept alongside.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import cost
import db

# How far back "how fast are we getting through this" looks when working out
# days of cover. Long enough to survive one quiet day, short enough to notice a
# drink that suddenly took off.
USAGE_WINDOW_DAYS = 14

# Days of cover at or below which an ingredient is called out as running out,
# for ingredients with no reorder level set by hand.
LOW_DAYS_COVER = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_counts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    count_date    TEXT    NOT NULL,                        -- 'YYYY-MM-DD' (local)
    quantity      REAL    NOT NULL CHECK (quantity >= 0),  -- in the base unit
    entered_qty   REAL    NOT NULL,                        -- as typed: 1.5...
    entered_unit  TEXT    NOT NULL,                        -- ...kg
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    -- One count per ingredient per day: recounting a shelf corrects the day's
    -- figure rather than adding a second, contradictory one.
    UNIQUE (ingredient_id, count_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_counts (count_date);
CREATE INDEX IF NOT EXISTS idx_stock_ing ON stock_counts (ingredient_id);
"""


def init_db(db_path: str | Path) -> None:
    """Create the stock table. Safe to call on every launch."""
    with db.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _round(n: float, places: int = 3) -> float:
    return round(float(n), places)


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def _latest_counts(conn, day: str, before: bool = False) -> dict[int, dict]:
    """Each ingredient's most recent count up to `day` (or strictly before it)."""
    op = "<" if before else "<="
    rows = conn.execute(
        f"SELECT s.* FROM stock_counts s WHERE s.count_date {op} ? AND s.id = ("
        f"  SELECT s2.id FROM stock_counts s2 "
        f"  WHERE s2.ingredient_id = s.ingredient_id AND s2.count_date {op} ? "
        f"  ORDER BY s2.count_date DESC LIMIT 1)",
        (day, day),
    ).fetchall()
    return {r["ingredient_id"]: dict(r) for r in rows}


def _purchases_between(conn, after: str, through: str) -> dict[int, float]:
    """Stock bought in (after, through], per ingredient, in base units."""
    return {
        r["ingredient_id"]: r["qty"]
        for r in conn.execute(
            "SELECT ingredient_id, SUM(quantity) AS qty FROM ingredient_purchases "
            "WHERE buy_date > ? AND buy_date <= ? GROUP BY ingredient_id",
            (after, through),
        ).fetchall()
    }


def get_status(db_path: str | Path, day: str | None = None) -> dict:
    """Everything the stock screen needs for one day.

    For each ingredient: what was counted that day (if anything), what the
    figures say should be there, the gap between the two, what it is worth, and
    how long it will last at the recent rate of use.
    """
    day = day or db.today_local()
    ingredients = cost.get_ingredients(db_path)
    costs = cost.unit_costs(db_path)
    window_start = _shift(day, -USAGE_WINDOW_DAYS)

    with db.connect(db_path) as conn:
        counted_today = {
            r["ingredient_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM stock_counts WHERE count_date = ?", (day,)
            ).fetchall()
        }
        # The count each expectation is measured from: the last one BEFORE today,
        # so a figure typed today can be compared against it rather than itself.
        basis = _latest_counts(conn, day, before=True)
        in_a_recipe = {
            r[0] for r in conn.execute("SELECT DISTINCT ingredient_id FROM recipe_lines")
        }
        # Ingredients usually share one basis date (a stock take covers the whole
        # shelf), so grouping keeps this to a query or two rather than one each.
        basis_dates = {b["count_date"] for b in basis.values()}
        bought_since = {d: _purchases_between(conn, d, day) for d in basis_dates}

    used_since = {d: cost.usage_between(db_path, d, day) for d in basis_dates}
    window_usage = cost.usage_between(db_path, window_start, day)
    window_days = max(cost.trading_days_between(db_path, window_start, day), 1)

    rows, total_value, counted_n, variance_value = [], 0.0, 0, 0.0
    for ing in ingredients:
        iid = ing["id"]
        mine = counted_today.get(iid)
        base = basis.get(iid)
        costed = iid in in_a_recipe

        expected = None
        bought = used = 0.0
        if base:
            bought = bought_since[base["count_date"]].get(iid, 0.0)
            used = used_since[base["count_date"]].get(iid, 0.0)
            expected = base["quantity"] + bought - used

        counted = mine["quantity"] if mine else None
        # What we believe is on the shelf: the count if one was taken, otherwise
        # the best estimate the figures support.
        on_hand = counted if counted is not None else expected

        variance = None
        if counted is not None and expected is not None:
            variance = counted - expected

        unit_price = costs.get(iid)
        value = on_hand * unit_price if on_hand is not None and unit_price else None

        per_day = window_usage.get(iid, 0.0) / window_days
        days_left = on_hand / per_day if per_day > 0 and on_hand is not None else None

        low = False
        if on_hand is not None:
            if ing["min_stock"] is not None:
                low = on_hand <= ing["min_stock"]
            elif days_left is not None:
                low = days_left <= LOW_DAYS_COVER

        if value:
            total_value += value
        if counted is not None:
            counted_n += 1
        # Only variance we can actually explain: an ingredient in no recipe has
        # no modelled usage, so its gap is meaningless, not alarming.
        if variance is not None and costed and unit_price:
            variance_value += variance * unit_price

        rows.append({
            "id": iid,
            "name": ing["name"],
            "unit": ing["unit"],
            "units": ing["units"],
            "min_stock": ing["min_stock"],
            "counted": _round(counted) if counted is not None else None,
            "entered_qty": mine["entered_qty"] if mine else None,
            "entered_unit": mine["entered_unit"] if mine else None,
            "note": mine["note"] if mine else "",
            "basis_date": base["count_date"] if base else None,
            "basis_qty": _round(base["quantity"]) if base else None,
            "bought_since": _round(bought),
            "used_since": _round(used),
            "expected": _round(expected) if expected is not None else None,
            "variance": _round(variance) if variance is not None else None,
            "on_hand": _round(on_hand) if on_hand is not None else None,
            "unit_cost": round(unit_price, 4) if unit_price else None,
            "value": round(value, 2) if value else None,
            "per_day": _round(per_day, 4),
            "days_left": round(days_left, 1) if days_left is not None else None,
            "in_a_recipe": costed,
            "low": low,
        })

    return {
        "date": day,
        "rows": rows,
        "total_value": round(total_value, 2),
        "counted": counted_n,
        "ingredients": len(rows),
        "low": [r["name"] for r in rows if r["low"]],
        "variance_value": round(variance_value, 2),
        "window_days": USAGE_WINDOW_DAYS,
    }


def get_history(db_path: str | Path, ingredient_id: int, limit: int = 30) -> list[dict]:
    """Recent counts for one ingredient, newest first."""
    with db.connect(db_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM stock_counts WHERE ingredient_id = ? "
                "ORDER BY count_date DESC LIMIT ?",
                (ingredient_id, int(limit)),
            ).fetchall()
        ]


def save_counts(db_path: str | Path, day: str, counts: list[dict]) -> dict:
    """Save a whole stock take at once.

    Each entry needs `ingredient_id` and `quantity`, optionally `unit` (defaults
    to the ingredient's base unit) and `note`. Saving is all-or-nothing: a
    single bad row must not leave half a stock take recorded.
    """
    day = day or db.today_local()
    if not counts:
        raise ValueError("Nothing to save — enter at least one count.")

    with db.connect(db_path) as conn:
        units = {
            r["id"]: r["unit"]
            for r in conn.execute("SELECT id, unit FROM ingredients").fetchall()
        }
        prepared = []
        for entry in counts:
            iid = int(entry["ingredient_id"])
            if iid not in units:
                raise ValueError("No such ingredient.")
            typed = float(entry["quantity"])
            if typed < 0:
                raise ValueError("A stock count cannot be negative.")
            unit = entry.get("unit") or units[iid]
            prepared.append((
                iid, day, cost.to_base(typed, unit, units[iid]), typed, unit,
                str(entry.get("note", "")).strip(),
                db.now_local().isoformat(timespec="seconds"),
            ))

        conn.executemany(
            "INSERT INTO stock_counts (ingredient_id, count_date, quantity, "
            "entered_qty, entered_unit, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (ingredient_id, count_date) DO UPDATE SET "
            "quantity = excluded.quantity, entered_qty = excluded.entered_qty, "
            "entered_unit = excluded.entered_unit, note = excluded.note, "
            "created_at = excluded.created_at",
            prepared,
        )
    return {"saved": len(prepared), "date": day}


def delete_count(db_path: str | Path, ingredient_id: int, day: str) -> None:
    with db.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM stock_counts WHERE ingredient_id = ? AND count_date = ?",
            (ingredient_id, day),
        )


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "duckhouse_stock_check.db"
    tmp.unlink(missing_ok=True)
    db.init_db(tmp)
    cost.init_db(tmp)
    init_db(tmp)

    ings = {i["name"]: i["id"] for i in cost.get_ingredients(tmp)}
    beans, milk = ings["เมล็ดกาแฟ Sunset arabica 100%"], ings["นมเมจิ Ray"]
    today = db.today_local()
    yesterday = _shift(today, -1)

    cost.add_purchase(tmp, beans, 2, 1, "kg", 900, buy_date=yesterday)
    with db.connect(tmp) as conn:
        latte = conn.execute(
            "SELECT id FROM menu_items WHERE name = 'Latte' AND temperature = 'Iced'"
        ).fetchone()["id"]
    cost.set_recipe_line(tmp, latte, beans, 18)
    cost.set_recipe_line(tmp, latte, milk, 150)

    # Counted 2 kg of beans last night, sold 10 lattes today = 180 g gone.
    save_counts(tmp, yesterday, [{"ingredient_id": beans, "quantity": 2, "unit": "kg"}])
    db.create_order(tmp, [{"name": "Latte", "temperature": "Iced",
                           "quantity": 10, "unit_price": 65}], "Cash")

    row = next(r for r in get_status(tmp, today)["rows"] if r["id"] == beans)
    print(f"Beans: expected {row['expected']} g (2000 counted - {row['used_since']} used)")

    # Only 1,750 g actually on the shelf: 70 g unaccounted for.
    save_counts(tmp, today, [{"ingredient_id": beans, "quantity": 1750}])
    s = get_status(tmp, today)
    row = next(r for r in s["rows"] if r["id"] == beans)
    print(f"Counted {row['counted']} g -> variance {row['variance']} g, "
          f"{row['days_left']} days left, worth {row['value']} baht")
    print(f"Stock value {s['total_value']} baht, counted {s['counted']}/{s['ingredients']}, "
          f"unexplained {s['variance_value']} baht")
    tmp.unlink(missing_ok=True)
