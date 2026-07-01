"""Excel / PDF export for a month's sales summary.

Both builders take the same monthly summary dict from db.get_month_summary()
plus the raw order list from db.get_orders_for_month(), and return raw bytes
ready to hand back as a Flask file download.
"""

from __future__ import annotations

import io


def build_excel(summary: dict, orders: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    ws.append([f"Sales summary — {summary['month']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Orders", summary["orders"]])
    ws.append(["Revenue", summary["revenue"]])
    for pm, amt in summary["by_payment"].items():
        ws.append([pm, amt])
    if summary["best_day"]:
        ws.append(["Busiest day", summary["best_day"]["date"], summary["best_day"]["orders"], "orders"])
    ws.append([])
    ws.append(["Top-selling items"])
    ws[f"A{ws.max_row}"].font = bold
    ws.append(["Item", "Temperature", "Quantity sold", "Revenue"])
    for c in ws[ws.max_row]:
        c.font = bold
    for it in summary["top_items"]:
        ws.append([it["name"], it["temperature"], it["quantity"], it["revenue"]])
    ws.append([])
    ws.append(["Day", "Orders", "Revenue"])
    for c in ws[ws.max_row]:
        c.font = bold
    for d in summary["by_day"]:
        ws.append([d["date"], d["orders"], d["revenue"]])
    for col in "ABCD":
        ws.column_dimensions[col].width = 20

    ws2 = wb.create_sheet("Orders")
    ws2.append(["Order ID", "Date", "Time", "Payment", "Item", "Temperature",
                "Qty", "Unit price", "Line total", "Order total", "Comment"])
    for c in ws2[1]:
        c.font = bold
    for o in orders:
        time = (o["created_at"] or "")[11:16]
        if not o["lines"]:
            ws2.append([o["id"], o["sale_date"], time, o["payment_method"],
                        "", "", "", "", "", o["total"], o["comment"]])
            continue
        for ln in o["lines"]:
            ws2.append([o["id"], o["sale_date"], time, o["payment_method"],
                        ln["name"], ln["temperature"], ln["quantity"],
                        ln["unit_price"], ln["line_total"], o["total"], o["comment"]])
    for col in "ABCDEFGHIJK":
        ws2.column_dimensions[col].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pdf(summary: dict, orders: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Sales summary - {summary['month']}", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Orders: {summary['orders']}    Revenue: THB {summary['revenue']:.2f}", ln=True)
    for pm, amt in summary["by_payment"].items():
        pdf.cell(0, 7, f"  {pm}: THB {amt:.2f}", ln=True)
    if summary["best_day"]:
        bd = summary["best_day"]
        pdf.cell(0, 7, f"Busiest day: {bd['date']} ({bd['orders']} orders, THB {bd['revenue']:.2f})", ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Top-selling items", ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 7, "Item", border=1)
    pdf.cell(30, 7, "Temp", border=1)
    pdf.cell(30, 7, "Qty", border=1)
    pdf.cell(30, 7, "Revenue", border=1, ln=True)
    pdf.set_font("Helvetica", "", 10)
    for it in summary["top_items"]:
        pdf.cell(90, 7, str(it["name"])[:45], border=1)
        pdf.cell(30, 7, str(it["temperature"] or "-"), border=1)
        pdf.cell(30, 7, f"{it['quantity']:g}", border=1)
        pdf.cell(30, 7, f"{it['revenue']:.2f}", border=1, ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Orders per day", ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 7, "Date", border=1)
    pdf.cell(40, 7, "Orders", border=1)
    pdf.cell(40, 7, "Revenue", border=1, ln=True)
    pdf.set_font("Helvetica", "", 10)
    for d in summary["by_day"]:
        if d["orders"] == 0 and d["revenue"] == 0:
            continue
        pdf.cell(60, 7, d["date"], border=1)
        pdf.cell(40, 7, str(d["orders"]), border=1)
        pdf.cell(40, 7, f"{d['revenue']:.2f}", border=1, ln=True)

    return bytes(pdf.output())
