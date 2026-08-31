"""Ingredient costs for the Duck House Cafe till.

Answers the four questions the Cost tab is built around:

  1. "How much did we buy X this time?"  -> ingredient_purchases (packs x size, price paid)
  2. "How much does X cost?"             -> unit cost derived from the latest purchase
  3. "Which menu items use X?"           -> recipe_lines, read ingredient-first
  4. "How much X for one Y?"             -> recipe_lines.amount, read menu-item-first

Everything is stored in the ingredient's own base unit (g / ml / pcs / ...), so a
1 kg bag of beans and a 250 g bag are directly comparable. What the cashier
actually typed is kept alongside it so a purchase row still reads like the receipt.

Shares the SQLite file (and connection helper) with db.py; db.py does not import
this module, so app.py initialises the two schemas side by side.
"""

from __future__ import annotations

from pathlib import Path

import db

# What one scoop of ice cream weighs. Ice cream is bought by the tub in
# kilograms but served by the scoop, so the scoop has to be a weight for the two
# to meet. Weigh a scoop on the shop's own scales and change this one number if
# it is not 60 g — every ice cream cost and stock figure follows from it.
SCOOP_GRAMS = 60.0

# unit -> (family, how many base units it is worth). Units only convert within a
# family: kg -> g is fine, ml -> g is not (we do not know the density).
# Every count unit is worth 1 so a shop can buy in ขวด and keep the recipe in ลูก
# without the numbers drifting.
UNITS: dict[str, tuple[str, float]] = {
    "g": ("weight", 1.0),
    "kg": ("weight", 1000.0),
    "scoop": ("weight", SCOOP_GRAMS),
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
    "pcs": ("count", 1.0),
    "ขวด": ("count", 1.0),
    "ลูก": ("count", 1.0),
    "ถุง": ("count", 1.0),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,
    unit      TEXT    NOT NULL,              -- base unit everything is stored in
    note      TEXT    NOT NULL DEFAULT '',
    active    INTEGER NOT NULL DEFAULT 1,
    sort      INTEGER NOT NULL DEFAULT 0,
    min_stock REAL                           -- reorder level, NULL = no alert
);

-- One shopping trip's worth of one ingredient.
CREATE TABLE IF NOT EXISTS ingredient_purchases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    buy_date      TEXT    NOT NULL,                          -- 'YYYY-MM-DD' (local)
    packs         REAL    NOT NULL CHECK (packs > 0),        -- as bought: 2 bags...
    pack_size     REAL    NOT NULL CHECK (pack_size > 0),    -- ...of 1 each...
    pack_unit     TEXT    NOT NULL,                          -- ...kg
    quantity      REAL    NOT NULL CHECK (quantity > 0),     -- = 2000, in base unit
    total_price   REAL    NOT NULL CHECK (total_price >= 0), -- baht paid in total
    unit_cost     REAL    NOT NULL,                          -- price / quantity, frozen
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL
);

-- How much of one ingredient goes into ONE serving of one menu item.
CREATE TABLE IF NOT EXISTS recipe_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_item_id  INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    amount        REAL    NOT NULL CHECK (amount > 0),       -- in the base unit
    UNIQUE (menu_item_id, ingredient_id)
);

CREATE INDEX IF NOT EXISTS idx_purchases_ing ON ingredient_purchases (ingredient_id);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON ingredient_purchases (buy_date);
CREATE INDEX IF NOT EXISTS idx_recipe_item ON recipe_lines (menu_item_id);
CREATE INDEX IF NOT EXISTS idx_recipe_ing ON recipe_lines (ingredient_id);
"""

# The cafe's shopping list. Units are the sensible default for each item and can
# be changed later in the Cost tab.
_INGREDIENT_SEED = [
    ("เมล็ดกาแฟ Sunset arabica 100%", "g"),
    ("น้ำ RO", "ml"),
    ("น้ำแพ็ค", "ขวด"),
    ("ไซรัป Yuzu house", "ml"),
    ("ลูกมะพร้าว", "ลูก"),
    ("นมเมจิ Ray", "ml"),
    ("Chocolate chip Tulip", "g"),
    ("Vanilla syrup Mathieu Teisseire", "ml"),
    ("นมข้นหวาน Carnations Plus", "g"),
    ("นมข้นจืด Carnation Extra", "g"),
    ("ผง Matcha Noko", "g"),
    ("Strawberry แพ็คแช่แข็ง", "g"),
    ("ผงชาไทยสูตร 1 Santi Panich", "g"),
    ("ผง Ovaltine", "g"),
    ("ผงชาอัสสัม Better tea", "g"),
    ("น้ำผึ้งขวด", "ml"),
    ("ผงโกโก้ Coffman", "g"),
    ("Soda Rock Mountain แพ็ค", "ขวด"),
    # Bought by the tub in kilograms, served by the scoop — stored in grams so
    # both can be entered and the tub price divides down to the scoop honestly.
    ("ice cream vanilla", "g"),
    ("ice cream fresh milk", "g"),
    ("Lemon", "ลูก"),
]


def init_db(db_path: str | Path) -> None:
    """Create the cost tables and seed the shopping list. Safe on every launch."""
    with db.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS leaves an older table untouched, so columns
        # added after a release have to be patched in for databases already live.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(ingredients)")}
        if "min_stock" not in columns:
            conn.execute("ALTER TABLE ingredients ADD COLUMN min_stock REAL")
        _rebase_scoops_to_grams(conn)
        already = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
        if already == 0:
            conn.executemany(
                "INSERT INTO ingredients (name, unit, sort) VALUES (?, ?, ?)",
                [(name, unit, i) for i, (name, unit) in enumerate(_INGREDIENT_SEED)],
            )


def _rebase_scoops_to_grams(conn) -> None:
    """Move ingredients still measured in scoops onto grams.

    A scoop used to be a countable thing worth 1, which meant a tub bought in
    kilograms could not be entered against it at all. It is now a weight, so any
    figure previously stored as "3 scoops" means 3 x SCOOP_GRAMS and has to be
    restated — otherwise the same rows would silently be read as 3 grams.
    Quantities scale up and per-unit costs scale down; the money paid is
    unchanged. What the user typed ("2 scoop") is left alone: it stays true.
    """
    stale = conn.execute("SELECT id FROM ingredients WHERE unit = 'scoop'").fetchall()
    if not stale:
        return
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for row in stale:
        iid = row["id"]
        if "ingredient_purchases" in tables:
            conn.execute(
                "UPDATE ingredient_purchases SET quantity = quantity * ?, "
                "unit_cost = unit_cost / ? WHERE ingredient_id = ?",
                (SCOOP_GRAMS, SCOOP_GRAMS, iid),
            )
        if "recipe_lines" in tables:
            conn.execute(
                "UPDATE recipe_lines SET amount = amount * ? WHERE ingredient_id = ?",
                (SCOOP_GRAMS, iid),
            )
        # Written by stock.py, which initialises after this module on a fresh file.
        if "stock_counts" in tables:
            conn.execute(
                "UPDATE stock_counts SET quantity = quantity * ? WHERE ingredient_id = ?",
                (SCOOP_GRAMS, iid),
            )
        conn.execute(
            "UPDATE ingredients SET unit = 'g', "
            "min_stock = min_stock * ? WHERE id = ?",
            (SCOOP_GRAMS, iid),
        )


# ---- units -----------------------------------------------------------------

def units_for(base_unit: str) -> list[str]:
    """Units a purchase may be entered in for an ingredient measured in `base_unit`."""
    family = UNITS.get(base_unit, ("count", 1.0))[0]
    return [u for u, (fam, _) in UNITS.items() if fam == family]


def to_base(value: float, from_unit: str, base_unit: str) -> float:
    """Convert `value` from_unit into the ingredient's base unit."""
    if from_unit not in UNITS:
        raise ValueError(f"Unknown unit: {from_unit!r}")
    if base_unit not in UNITS:
        raise ValueError(f"Unknown unit: {base_unit!r}")
    src_fam, src_factor = UNITS[from_unit]
    dst_fam, dst_factor = UNITS[base_unit]
    if src_fam != dst_fam:
        raise ValueError(f"Cannot measure {base_unit} in {from_unit}.")
    return float(value) * src_factor / dst_factor


# ---- reads -----------------------------------------------------------------

def _round(n: float, places: int = 4) -> float:
    return round(float(n), places)


def get_ingredients(db_path: str | Path, include_inactive: bool = False) -> list[dict]:
    """Every ingredient with what it currently costs and how it is used.

    `unit_cost` is taken from the most recent purchase - that is what the next
    drink actually costs to make. `avg_unit_cost` (all money spent / all quantity
    bought) is carried alongside it so a one-off expensive trip is visible.
    """
    with db.connect(db_path) as conn:
        sql = "SELECT * FROM ingredients"
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY sort, id"
        rows = [dict(r) for r in conn.execute(sql).fetchall()]

        # buy_date first, id second: two trips on the same day still order correctly.
        latest = {
            r["ingredient_id"]: dict(r)
            for r in conn.execute(
                "SELECT p.* FROM ingredient_purchases p "
                "WHERE p.id = (SELECT p2.id FROM ingredient_purchases p2 "
                "              WHERE p2.ingredient_id = p.ingredient_id "
                "              ORDER BY p2.buy_date DESC, p2.id DESC LIMIT 1)"
            ).fetchall()
        }
        totals = {
            r["ingredient_id"]: dict(r)
            for r in conn.execute(
                "SELECT ingredient_id, COUNT(*) AS purchases, "
                "SUM(quantity) AS qty, SUM(total_price) AS spent "
                "FROM ingredient_purchases GROUP BY ingredient_id"
            ).fetchall()
        }
        used_in = {
            r["ingredient_id"]: r["n"]
            for r in conn.execute(
                "SELECT ingredient_id, COUNT(*) AS n FROM recipe_lines GROUP BY ingredient_id"
            ).fetchall()
        }

    for ing in rows:
        last = latest.get(ing["id"])
        tot = totals.get(ing["id"])
        ing["units"] = units_for(ing["unit"])
        ing["last_purchase"] = last
        ing["unit_cost"] = _round(last["unit_cost"]) if last else None
        ing["purchases"] = tot["purchases"] if tot else 0
        ing["total_spent"] = _round(tot["spent"], 2) if tot else 0
        ing["total_quantity"] = _round(tot["qty"], 3) if tot else 0
        ing["avg_unit_cost"] = (
            _round(tot["spent"] / tot["qty"]) if tot and tot["qty"] else None
        )
        ing["used_in"] = used_in.get(ing["id"], 0)
    return rows


def get_purchases(
    db_path: str | Path, ingredient_id: int | None = None, limit: int = 100
) -> list[dict]:
    """Purchase history, newest first, with the unit-cost change since the
    previous trip for the same ingredient so price creep is visible."""
    sql = (
        "SELECT p.*, i.name AS ingredient_name, i.unit AS base_unit "
        "FROM ingredient_purchases p JOIN ingredients i ON i.id = p.ingredient_id"
    )
    params: list = []
    if ingredient_id is not None:
        sql += " WHERE p.ingredient_id = ?"
        params.append(ingredient_id)
    sql += " ORDER BY p.buy_date DESC, p.id DESC LIMIT ?"
    params.append(int(limit))

    with db.connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # The row directly older than each one, per ingredient.
        previous = {
            (r["ingredient_id"], r["id"]): r["prev_cost"]
            for r in conn.execute(
                "SELECT ingredient_id, id, ("
                "  SELECT p2.unit_cost FROM ingredient_purchases p2 "
                "  WHERE p2.ingredient_id = p.ingredient_id "
                "    AND (p2.buy_date < p.buy_date "
                "         OR (p2.buy_date = p.buy_date AND p2.id < p.id)) "
                "  ORDER BY p2.buy_date DESC, p2.id DESC LIMIT 1"
                ") AS prev_cost FROM ingredient_purchases p"
            ).fetchall()
        }

    for r in rows:
        prev = previous.get((r["ingredient_id"], r["id"]))
        r["prev_unit_cost"] = _round(prev) if prev is not None else None
        r["unit_cost_change"] = _round(r["unit_cost"] - prev) if prev else None
    return rows


def get_recipe(db_path: str | Path, menu_item_id: int) -> dict:
    """The full recipe for one menu item: what goes in, how much, what it costs.

    `cost` only counts ingredients that have been bought at least once; anything
    still unpriced is listed in `missing` so a margin is never quietly overstated.
    """
    with db.connect(db_path) as conn:
        item = conn.execute(
            "SELECT * FROM menu_items WHERE id = ?", (menu_item_id,)
        ).fetchone()
        if item is None:
            raise ValueError("No such menu item.")
        item = dict(item)
        lines = [
            dict(r)
            for r in conn.execute(
                "SELECT r.id, r.ingredient_id, r.amount, i.name, i.unit "
                "FROM recipe_lines r JOIN ingredients i ON i.id = r.ingredient_id "
                "WHERE r.menu_item_id = ? ORDER BY i.sort, i.id",
                (menu_item_id,),
            ).fetchall()
        ]

    costs = unit_costs(db_path)
    total, missing = 0.0, []
    for ln in lines:
        uc = costs.get(ln["ingredient_id"])
        ln["unit_cost"] = _round(uc) if uc is not None else None
        ln["line_cost"] = _round(ln["amount"] * uc, 2) if uc is not None else None
        if uc is None:
            missing.append(ln["name"])
        else:
            total += ln["amount"] * uc

    return {
        "item": item,
        "lines": lines,
        "cost": _round(total, 2),
        "missing": missing,
        **_margin(item.get("price"), total, bool(lines) and not missing),
    }


def unit_costs(db_path: str | Path) -> dict[int, float]:
    """ingredient_id -> latest unit cost, for every ingredient ever bought."""
    with db.connect(db_path) as conn:
        return {
            r["ingredient_id"]: r["unit_cost"]
            for r in conn.execute(
                "SELECT p.ingredient_id, p.unit_cost FROM ingredient_purchases p "
                "WHERE p.id = (SELECT p2.id FROM ingredient_purchases p2 "
                "              WHERE p2.ingredient_id = p.ingredient_id "
                "              ORDER BY p2.buy_date DESC, p2.id DESC LIMIT 1)"
            ).fetchall()
        }


def _margin(price, cost: float, complete: bool) -> dict:
    """Profit on one serving. `complete` is False when part of the recipe is
    still unpriced (or missing entirely), which makes the margin a ceiling, not a fact."""
    if price is None:
        return {"price": None, "margin": None, "margin_pct": None, "complete": complete}
    margin = float(price) - cost
    return {
        "price": float(price),
        "margin": _round(margin, 2),
        "margin_pct": _round(margin / float(price) * 100, 1) if price else None,
        "complete": complete,
    }


def get_menu_costs(db_path: str | Path, include_inactive: bool = False) -> list[dict]:
    """Cost, price and margin for every menu item, in normal menu order so the
    table reads in the same sequence as the till buttons."""
    costs = unit_costs(db_path)
    with db.connect(db_path) as conn:
        sql = "SELECT * FROM menu_items"
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY sort, id"
        items = [dict(r) for r in conn.execute(sql).fetchall()]
        lines_by_item: dict[int, list[dict]] = {}
        for r in conn.execute(
            "SELECT r.menu_item_id, r.ingredient_id, r.amount, i.name, i.unit "
            "FROM recipe_lines r JOIN ingredients i ON i.id = r.ingredient_id"
        ).fetchall():
            lines_by_item.setdefault(r["menu_item_id"], []).append(dict(r))

    out = []
    for item in items:
        lines = lines_by_item.get(item["id"], [])
        total, missing = 0.0, []
        for ln in lines:
            uc = costs.get(ln["ingredient_id"])
            if uc is None:
                missing.append(ln["name"])
            else:
                total += ln["amount"] * uc
        complete = bool(lines) and not missing
        out.append({
            "id": item["id"],
            "category": item["category"],
            "name": item["name"],
            "temperature": item["temperature"],
            "is_custom": item["is_custom"],
            "active": item["active"],
            "recipe_lines": len(lines),
            "cost": _round(total, 2),
            "missing": missing,
            **_margin(item["price"], total, complete),
        })
    return out


def usage_between(
    db_path: str | Path, after: str, through: str
) -> dict[int, float]:
    """How much of each ingredient the sales in (after, through] should have used.

    `after` is exclusive so it can be handed a stock-count date directly: what
    was counted that evening is the opening figure, and only the days since it
    count against it. Sold lines are matched to the menu by (name, temperature);
    a drink with no recipe simply contributes nothing, which is why the caller
    has to say whether an ingredient is costed at all before trusting a total.
    """
    with db.connect(db_path) as conn:
        return {
            r["ingredient_id"]: r["used"]
            for r in conn.execute(
                "SELECT rl.ingredient_id, SUM(rl.amount * ol.quantity) AS used "
                "FROM order_lines ol "
                "JOIN orders o ON o.id = ol.order_id "
                "JOIN menu_items m ON m.id = ("
                "  SELECT m2.id FROM menu_items m2 "
                "  WHERE m2.name = ol.name AND m2.temperature = ol.temperature "
                "  ORDER BY m2.id LIMIT 1) "
                "JOIN recipe_lines rl ON rl.menu_item_id = m.id "
                "WHERE o.sale_date > ? AND o.sale_date <= ? "
                "GROUP BY rl.ingredient_id",
                (after, through),
            ).fetchall()
        }


def trading_days_between(db_path: str | Path, after: str, through: str) -> int:
    """Days in (after, through] that actually took money — the divisor for an
    average that should not be watered down by days the cafe was shut."""
    with db.connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(DISTINCT sale_date) FROM orders "
            "WHERE sale_date > ? AND sale_date <= ?",
            (after, through),
        ).fetchone()[0]


def get_ingredient_usage(db_path: str | Path, ingredient_id: int) -> list[dict]:
    """Every menu item this ingredient goes into, and how much of it each one takes."""
    with db.connect(db_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT m.id AS menu_item_id, m.category, m.name, m.temperature, "
                "m.price, m.active, r.amount, r.id AS recipe_line_id "
                "FROM recipe_lines r JOIN menu_items m ON m.id = r.menu_item_id "
                "WHERE r.ingredient_id = ? ORDER BY m.sort, m.id",
                (ingredient_id,),
            ).fetchall()
        ]


def get_period_cost(db_path: str | Path, prefix: str) -> dict:
    """Estimated ingredient cost of everything sold in a period.

    `prefix` is a sale_date prefix: 'YYYY', 'YYYY-MM' or a full 'YYYY-MM-DD'.
    Sold lines are matched back to the menu by (name, temperature) - the same
    pair the till writes - so a typed-in dessert or a since-renamed item has no
    recipe to cost and is reported under `unpriced_qty` instead of being ignored.
    """
    costs = unit_costs(db_path)
    like = f"{prefix}%"
    with db.connect(db_path) as conn:
        totals = conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue "
            "FROM orders WHERE sale_date LIKE ?",
            (like,),
        ).fetchone()
        sold = [
            dict(r)
            for r in conn.execute(
                "SELECT ol.name, ol.temperature, SUM(ol.quantity) AS qty, "
                "SUM(ol.line_total) AS revenue, "
                "(SELECT m.id FROM menu_items m "
                " WHERE m.name = ol.name AND m.temperature = ol.temperature "
                " ORDER BY m.id LIMIT 1) AS menu_item_id "
                "FROM order_lines ol JOIN orders o ON o.id = ol.order_id "
                "WHERE o.sale_date LIKE ? GROUP BY ol.name, ol.temperature",
                (like,),
            ).fetchall()
        ]
        recipe_by_item: dict[int, list[dict]] = {}
        for r in conn.execute(
            "SELECT r.menu_item_id, r.ingredient_id, r.amount, i.name, i.unit "
            "FROM recipe_lines r JOIN ingredients i ON i.id = r.ingredient_id"
        ).fetchall():
            recipe_by_item.setdefault(r["menu_item_id"], []).append(dict(r))

    usage: dict[int, dict] = {}
    cost_total, priced_qty, unpriced_qty = 0.0, 0.0, 0.0
    for s in sold:
        lines = recipe_by_item.get(s["menu_item_id"] or -1, [])
        if not lines or any(costs.get(ln["ingredient_id"]) is None for ln in lines):
            unpriced_qty += s["qty"]
            continue
        priced_qty += s["qty"]
        for ln in lines:
            used = ln["amount"] * s["qty"]
            spend = used * costs[ln["ingredient_id"]]
            cost_total += spend
            rec = usage.setdefault(
                ln["ingredient_id"],
                {"name": ln["name"], "unit": ln["unit"], "quantity": 0.0, "cost": 0.0},
            )
            rec["quantity"] += used
            rec["cost"] += spend

    for rec in usage.values():
        rec["quantity"] = _round(rec["quantity"], 2)
        rec["cost"] = _round(rec["cost"], 2)
    by_ingredient = sorted(usage.values(), key=lambda r: -r["cost"])

    revenue = totals["revenue"]
    return {
        "period": prefix,
        "orders": totals["orders"],
        "revenue": _round(revenue, 2),
        "cost": _round(cost_total, 2),
        "gross_profit": _round(revenue - cost_total, 2),
        "cost_pct": _round(cost_total / revenue * 100, 1) if revenue else None,
        "priced_qty": _round(priced_qty, 2),
        "unpriced_qty": _round(unpriced_qty, 2),
        "by_ingredient": by_ingredient,
    }


def get_spend(db_path: str | Path, prefix: str) -> dict:
    """What was actually spent on ingredients in a period (money out of the till),
    as opposed to get_period_cost() which is the cost of what was sold."""
    like = f"{prefix}%"
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS purchases, COALESCE(SUM(total_price), 0) AS spent "
            "FROM ingredient_purchases WHERE buy_date LIKE ?",
            (like,),
        ).fetchone()
        by_ingredient = [
            dict(r)
            for r in conn.execute(
                "SELECT i.name, i.unit, SUM(p.quantity) AS quantity, "
                "SUM(p.total_price) AS spent, COUNT(*) AS purchases "
                "FROM ingredient_purchases p JOIN ingredients i ON i.id = p.ingredient_id "
                "WHERE p.buy_date LIKE ? GROUP BY p.ingredient_id "
                "ORDER BY spent DESC",
                (like,),
            ).fetchall()
        ]
    return {
        "period": prefix,
        "purchases": row["purchases"],
        "spent": _round(row["spent"], 2),
        "by_ingredient": by_ingredient,
    }


# ---- writes ----------------------------------------------------------------

def create_ingredient(db_path: str | Path, name: str, unit: str, note: str = "") -> int:
    name, unit = name.strip(), unit.strip()
    if not name:
        raise ValueError("An ingredient needs a name.")
    if unit not in UNITS:
        raise ValueError(f"Unknown unit: {unit!r}")
    with db.connect(db_path) as conn:
        if conn.execute("SELECT 1 FROM ingredients WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"'{name}' is already on the list.")
        nxt = conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM ingredients").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO ingredients (name, unit, note, sort) VALUES (?, ?, ?, ?)",
            (name, unit, note.strip(), nxt),
        )
        return cur.lastrowid


def update_ingredient(db_path: str | Path, ingredient_id: int, **fields) -> None:
    """Update name/unit/note/active/min_stock. Changing the unit does NOT restate
    past purchases - their unit cost was frozen in the old unit - so the UI warns first."""
    allowed = {"name", "unit", "note", "active", "min_stock"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    # An empty reorder level means "stop alerting me", which has to reach the
    # column as NULL — the filter above would otherwise drop it.
    if fields.get("min_stock", False) in ("", None) and "min_stock" in fields:
        updates["min_stock"] = None
    elif "min_stock" in updates:
        updates["min_stock"] = float(updates["min_stock"])
        if updates["min_stock"] < 0:
            raise ValueError("Reorder level cannot be negative.")
    if not updates:
        return
    if "unit" in updates and updates["unit"] not in UNITS:
        raise ValueError(f"Unknown unit: {updates['unit']!r}")
    if "name" in updates:
        updates["name"] = str(updates["name"]).strip()
        if not updates["name"]:
            raise ValueError("An ingredient needs a name.")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db.connect(db_path) as conn:
        conn.execute(
            f"UPDATE ingredients SET {set_clause} WHERE id = ?",
            (*updates.values(), ingredient_id),
        )


def delete_ingredient(db_path: str | Path, ingredient_id: int) -> None:
    """Removes the ingredient, its purchase history and its recipe lines."""
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM ingredients WHERE id = ?", (ingredient_id,))


def add_purchase(
    db_path: str | Path,
    ingredient_id: int,
    packs: float,
    pack_size: float,
    pack_unit: str,
    total_price: float,
    buy_date: str | None = None,
    note: str = "",
) -> dict:
    """Record one shopping trip: `packs` x `pack_size` `pack_unit` for `total_price`."""
    packs, pack_size, total_price = float(packs), float(pack_size), float(total_price)
    if packs <= 0 or pack_size <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if total_price < 0:
        raise ValueError("Price cannot be negative.")

    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT unit FROM ingredients WHERE id = ?", (ingredient_id,)
        ).fetchone()
        if row is None:
            raise ValueError("No such ingredient.")
        base_unit = row["unit"]

    quantity = to_base(packs * pack_size, pack_unit, base_unit)
    unit_cost = total_price / quantity
    when = buy_date or db.today_local()

    with db.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO ingredient_purchases (ingredient_id, buy_date, packs, "
            "pack_size, pack_unit, quantity, total_price, unit_cost, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ingredient_id, when, packs, pack_size, pack_unit,
                _round(quantity, 4), round(total_price, 2), unit_cost,
                note.strip(), db.now_local().isoformat(timespec="seconds"),
            ),
        )
        return {
            "id": cur.lastrowid,
            "quantity": _round(quantity, 4),
            "unit": base_unit,
            "unit_cost": _round(unit_cost),
        }


def delete_purchase(db_path: str | Path, purchase_id: int) -> None:
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM ingredient_purchases WHERE id = ?", (purchase_id,))


def set_recipe_line(
    db_path: str | Path,
    menu_item_id: int,
    ingredient_id: int,
    amount: float,
    unit: str | None = None,
) -> int:
    """Set how much of one ingredient goes into one serving. Re-setting an
    existing pair overwrites it, so the same ingredient can never be listed twice.

    `unit` lets a recipe be written the way it is actually made — one scoop of
    ice cream rather than 60 g of it — and is converted to the base unit here.
    """
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    with db.connect(db_path) as conn:
        if conn.execute("SELECT 1 FROM menu_items WHERE id = ?", (menu_item_id,)).fetchone() is None:
            raise ValueError("No such menu item.")
        base = conn.execute(
            "SELECT unit FROM ingredients WHERE id = ?", (ingredient_id,)
        ).fetchone()
        if base is None:
            raise ValueError("No such ingredient.")
        if unit:
            amount = to_base(amount, unit, base["unit"])
        conn.execute(
            "INSERT INTO recipe_lines (menu_item_id, ingredient_id, amount) "
            "VALUES (?, ?, ?) ON CONFLICT (menu_item_id, ingredient_id) "
            "DO UPDATE SET amount = excluded.amount",
            (menu_item_id, ingredient_id, amount),
        )
        return conn.execute(
            "SELECT id FROM recipe_lines WHERE menu_item_id = ? AND ingredient_id = ?",
            (menu_item_id, ingredient_id),
        ).fetchone()["id"]


def delete_recipe_line(db_path: str | Path, line_id: int) -> None:
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM recipe_lines WHERE id = ?", (line_id,))


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "duckhouse_cost_check.db"
    tmp.unlink(missing_ok=True)
    db.init_db(tmp)
    init_db(tmp)

    ings = {i["name"]: i["id"] for i in get_ingredients(tmp)}
    print("Ingredients seeded:", len(ings))

    beans = ings["เมล็ดกาแฟ Sunset arabica 100%"]
    milk = ings["นมเมจิ Ray"]
    # 2 bags of 1 kg for 900 baht -> 2000 g at 0.45 B/g
    print("Bought beans:", add_purchase(tmp, beans, packs=2, pack_size=1, pack_unit="kg", total_price=900))
    print("Bought milk :", add_purchase(tmp, milk, packs=4, pack_size=2, pack_unit="l", total_price=560))

    with db.connect(tmp) as conn:
        latte = conn.execute(
            "SELECT id FROM menu_items WHERE name = 'Latte' AND temperature = 'Iced'"
        ).fetchone()["id"]
    set_recipe_line(tmp, latte, beans, 18)     # 18 g of beans
    set_recipe_line(tmp, latte, milk, 150)     # 150 ml of milk

    r = get_recipe(tmp, latte)
    print("Iced Latte costs", r["cost"], "sells for", r["price"], "margin", r["margin"], f"({r['margin_pct']}%)")
    print("Beans are used in:", [(u["name"], u["temperature"], u["amount"]) for u in get_ingredient_usage(tmp, beans)])

    db.create_order(tmp, [{"name": "Latte", "temperature": "Iced", "quantity": 3, "unit_price": 65}], "Cash")
    print("Today's cost of sales:", get_period_cost(tmp, db.today_local()))
    print("Today's ingredient spend:", get_spend(tmp, db.today_local())["spent"])
    tmp.unlink(missing_ok=True)
