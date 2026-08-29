import os
import json
import csv
import io
import time
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Response, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from src.database import init_db, get_db, get_db_path, hash_password

app = FastAPI(title="HR Accounts", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BRANDING_FILE = os.path.join(os.path.dirname(__file__), "branding.json")

def load_branding():
    if os.path.exists(BRANDING_FILE):
        with open(BRANDING_FILE, "r") as f:
            return json.load(f)
    return {
        "brand_name": "HR Services",
        "product_name": "HR Accounts",
        "primary_color": "#2563eb",
        "bg_canvas": "#ffffff",
        "bg_secondary": "#f8fafc",
        "text_primary": "#0f172a",
        "text_muted": "#64748b"
    }

@app.on_event("startup")
def startup_event():
    init_db()

# --- Pydantic Data Models ---
class InvoiceItemCreate(BaseModel):
    description: str
    quantity: float
    unit_price: float

class InvoiceCreate(BaseModel):
    client_id: int
    type: Optional[str] = "Invoice" # Invoice, Quote
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = "GBP"
    tax_rate: Optional[float] = 0.20
    discount: Optional[float] = 0.0
    items: List[InvoiceItemCreate]
    notes: Optional[str] = ""

class ClientCreate(BaseModel):
    name: str
    email: str
    company: Optional[str] = ""
    address: Optional[str] = ""
    currency: Optional[str] = "GBP"
    tax_id: Optional[str] = ""
    payment_terms_days: Optional[int] = 14

class PaymentCreate(BaseModel):
    invoice_id: int
    amount: float
    payment_method: Optional[str] = "Bank Transfer"
    reference: Optional[str] = ""

class ExpenseCreate(BaseModel):
    category: str
    vendor: str
    amount: float
    currency: Optional[str] = "GBP"
    expense_date: Optional[str] = None
    notes: Optional[str] = ""
    receipt_ref: Optional[str] = ""

# --- API Endpoints ---
@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "HR Accounts", "version": "2.0.0", "database": "SQLite WAL"}

@app.get("/api/branding")
def get_branding():
    return load_branding()

@app.get("/api/dashboard/stats")
def dashboard_stats():
    with get_db() as conn:
        total_invoiced = conn.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'").fetchone()[0]
        total_collected = conn.execute("SELECT COALESCE(SUM(amount_paid), 0) FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'").fetchone()[0]
        total_outstanding = conn.execute("SELECT COALESCE(SUM(balance_due), 0) FROM invoices WHERE type = 'Invoice' AND status NOT IN ('Paid', 'Cancelled')").fetchone()[0]
        total_expenses = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()[0]
        total_quotes = conn.execute("SELECT COUNT(*) FROM invoices WHERE type = 'Quote'").fetchone()[0]
        quotes_value = conn.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE type = 'Quote'").fetchone()[0]
        net_profit = total_collected - total_expenses
        profit_margin = round((net_profit / total_collected * 100), 1) if total_collected > 0 else 0.0

        # Overdue Invoices
        overdue_count = conn.execute("SELECT COUNT(*) FROM invoices WHERE type = 'Invoice' AND status NOT IN ('Paid', 'Cancelled') AND due_date < date('now')").fetchone()[0]
        overdue_amount = conn.execute("SELECT COALESCE(SUM(balance_due), 0) FROM invoices WHERE type = 'Invoice' AND status NOT IN ('Paid', 'Cancelled') AND due_date < date('now')").fetchone()[0]

        # Expense Breakdown by Category
        expenses_by_cat = conn.execute("""
        SELECT category, COALESCE(SUM(amount), 0) as total FROM expenses GROUP BY category ORDER BY total DESC
        """).fetchall()

        # Monthly Revenue Trend (Recent 6 entries)
        monthly_trend = conn.execute("""
        SELECT strftime('%Y-%m', issue_date) as month, SUM(total) as invoiced, SUM(amount_paid) as collected
        FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'
        GROUP BY month ORDER BY month DESC LIMIT 6
        """).fetchall()

        return {
            "total_invoiced": total_invoiced,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "total_expenses": total_expenses,
            "total_quotes": total_quotes,
            "quotes_value": quotes_value,
            "net_profit": net_profit,
            "profit_margin_pct": profit_margin,
            "overdue_count": overdue_count,
            "overdue_amount": overdue_amount,
            "expense_categories": [dict(r) for r in expenses_by_cat],
            "monthly_trend": [dict(r) for r in monthly_trend]
        }

@app.get("/api/invoices")
def list_invoices(type: Optional[str] = "Invoice", status: Optional[str] = None):
    with get_db() as conn:
        query = """
        SELECT i.*, c.name as client_name, c.company as client_company, c.email as client_email
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.type = ?
        """
        params = [type]
        if status and status != 'All':
            query += " AND i.status = ?"
            params.append(status)
        query += " ORDER BY i.issue_date DESC, i.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/invoices", status_code=201)
def create_invoice(payload: InvoiceCreate):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Invoice must contain at least one line item")

    with get_db() as conn:
        client = conn.execute("SELECT * FROM clients WHERE id = ?", (payload.client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        issue_d = payload.issue_date or datetime.now().strftime("%Y-%m-%d")
        due_d = payload.due_date or (datetime.now() + timedelta(days=client["payment_terms_days"])).strftime("%Y-%m-%d")

        subtotal = sum(itm.quantity * itm.unit_price for itm in payload.items)
        tax_amt = (subtotal - payload.discount) * (payload.tax_rate or 0.20)
        total = round((subtotal - payload.discount) + tax_amt, 2)

        prefix = "INV" if payload.type == "Invoice" else "QUO"
        inv_num = f"{prefix}-2026-{int(time.time()) % 100000:05d}"

        cur = conn.execute("""
        INSERT INTO invoices (invoice_number, client_id, type, issue_date, due_date, currency, subtotal, tax_rate, tax_amount, discount, total, amount_paid, balance_due, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, 'Sent', ?)
        """, (inv_num, payload.client_id, payload.type, issue_d, due_d, payload.currency, round(subtotal, 2),
              payload.tax_rate, round(tax_amt, 2), payload.discount, total, total, payload.notes))
        inv_id = cur.lastrowid

        for itm in payload.items:
            line_tot = itm.quantity * itm.unit_price
            conn.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (?, ?, ?, ?, ?)
            """, (inv_id, itm.description, itm.quantity, itm.unit_price, round(line_tot, 2)))

        # Update client totals if invoice
        if payload.type == "Invoice":
            conn.execute("UPDATE clients SET total_invoiced = total_invoiced + ? WHERE id = ?", (total, payload.client_id))

        conn.commit()
        return {"id": inv_id, "invoice_number": inv_num, "total": total, "balance_due": total, "status": "Sent"}

@app.get("/api/invoices/{invoice_id}")
def get_invoice_detail(invoice_id: int):
    with get_db() as conn:
        inv = conn.execute("""
        SELECT i.*, c.name as client_name, c.company as client_company, c.email as client_email, c.address as client_address, c.tax_id as client_tax_id
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = ?
        """, (invoice_id,)).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,)).fetchall()
        payments = conn.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date DESC", (invoice_id,)).fetchall()

        return {
            "invoice": dict(inv),
            "items": [dict(r) for r in items],
            "payments": [dict(r) for r in payments]
        }

@app.post("/api/invoices/{invoice_id}/convert-quote")
def convert_quote_to_invoice(invoice_id: int):
    with get_db() as conn:
        quote = conn.execute("SELECT * FROM invoices WHERE id = ? AND type = 'Quote'", (invoice_id,)).fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        new_inv_num = f"INV-2026-{int(time.time()) % 100000:05d}"
        due_d = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        
        conn.execute("""
        UPDATE invoices 
        SET type = 'Invoice', invoice_number = ?, issue_date = date('now'), due_date = ?, status = 'Sent'
        WHERE id = ?
        """, (new_inv_num, due_d, invoice_id))

        conn.execute("UPDATE clients SET total_invoiced = total_invoiced + ? WHERE id = ?", (quote["total"], quote["client_id"]))
        conn.commit()
        return {"status": "Converted", "new_invoice_number": new_inv_num, "id": invoice_id}

@app.post("/api/payments", status_code=201)
def record_payment(payload: PaymentCreate):
    with get_db() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (payload.invoice_id,)).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        pay_d = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
        INSERT INTO payments (invoice_id, amount, payment_date, payment_method, reference)
        VALUES (?, ?, ?, ?, ?)
        """, (payload.invoice_id, payload.amount, pay_d, payload.payment_method, payload.reference))

        new_paid = inv["amount_paid"] + payload.amount
        new_balance = max(0.0, round(inv["total"] - new_paid, 2))
        new_status = "Paid" if new_balance <= 0.0 else "Partially Paid"

        conn.execute("""
        UPDATE invoices SET amount_paid = ?, balance_due = ?, status = ? WHERE id = ?
        """, (new_paid, new_balance, new_status, payload.invoice_id))

        conn.execute("UPDATE clients SET total_paid = total_paid + ? WHERE id = ?", (payload.amount, inv["client_id"]))

        conn.commit()
        return {"status": new_status, "amount_paid": new_paid, "balance_due": new_balance}

@app.patch("/api/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: int):
    with get_db() as conn:
        conn.execute("UPDATE invoices SET status = 'Cancelled', balance_due = 0.0 WHERE id = ?", (invoice_id,))
        conn.commit()
        return {"status": "Cancelled", "id": invoice_id}

@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
        conn.execute("DELETE FROM payments WHERE invoice_id = ?", (invoice_id,))
        conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        conn.commit()
        return {"status": "deleted", "id": invoice_id}

@app.get("/api/clients")
def list_clients():
    with get_db() as conn:
        rows = conn.execute("""
        SELECT c.*, 
               COALESCE(SUM(i.total), 0) as total_billed,
               COALESCE(SUM(i.amount_paid), 0) as total_received,
               COALESCE(SUM(i.balance_due), 0) as total_receivable
        FROM clients c
        LEFT JOIN invoices i ON c.id = i.client_id AND i.type = 'Invoice' AND i.status != 'Cancelled'
        GROUP BY c.id ORDER BY total_billed DESC
        """).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/clients", status_code=201)
def create_client(payload: ClientCreate):
    with get_db() as conn:
        cur = conn.execute("""
        INSERT INTO clients (name, email, company, address, currency, tax_id, payment_terms_days)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (payload.name, payload.email, payload.company, payload.address, payload.currency, payload.tax_id, payload.payment_terms_days))
        conn.commit()
        return {"id": cur.lastrowid, "message": "Client created successfully"}

@app.get("/api/expenses")
def list_expenses():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM expenses ORDER BY expense_date DESC, id DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/expenses", status_code=201)
def create_expense(payload: ExpenseCreate):
    with get_db() as conn:
        exp_d = payload.expense_date or datetime.now().strftime("%Y-%m-%d")
        cur = conn.execute("""
        INSERT INTO expenses (category, vendor, amount, currency, expense_date, notes, receipt_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (payload.category, payload.vendor, payload.amount, payload.currency, exp_d, payload.notes, payload.receipt_ref))
        conn.commit()
        return {"id": cur.lastrowid, "message": "Expense recorded successfully"}

@app.delete("/api/expenses/{expense_id}")
def delete_expense(expense_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()
        return {"status": "deleted", "id": expense_id}

@app.get("/api/reports/pnl")
def report_pnl():
    with get_db() as conn:
        total_rev = conn.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'").fetchone()[0]
        total_exp = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()[0]
        net_profit = total_rev - total_exp
        margin = round((net_profit / total_rev * 100), 1) if total_rev > 0 else 0.0

        exp_breakdown = conn.execute("""
        SELECT category, SUM(amount) as amount FROM expenses GROUP BY category ORDER BY amount DESC
        """).fetchall()

        return {
            "gross_revenue": total_rev,
            "total_expenses": total_exp,
            "net_profit": net_profit,
            "margin_pct": margin,
            "expense_breakdown": [dict(r) for r in exp_breakdown]
        }

# --- Printable Invoice HTML Document ---
@app.get("/api/invoices/{invoice_id}/render", response_class=HTMLResponse)
def render_invoice_document(invoice_id: int):
    with get_db() as conn:
        inv = conn.execute("""
        SELECT i.*, c.name as client_name, c.company as client_company, c.email as client_email, c.address as client_address, c.tax_id as client_tax_id
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = ?
        """, (invoice_id,)).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,)).fetchall()

    items_html = "".join([f"""
    <tr>
      <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0;">{itm['description']}</td>
      <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: center;">{itm['quantity']}</td>
      <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right;">{inv['currency']} {itm['unit_price']:,.2f}</td>
      <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600;">{inv['currency']} {itm['total']:,.2f}</td>
    </tr>
    """ for itm in items])

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Invoice {inv['invoice_number']} — HR Services</title>
  <style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #0f172a; background: #fff; padding: 40px; margin: 0; }}
    .invoice-card {{ max-width: 800px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 40px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #2563eb; padding-bottom: 20px; }}
    .brand-title {{ font-size: 22px; font-weight: 800; color: #0f172a; }}
    .badge-paid {{ color: #16a34a; border: 2px solid #16a34a; padding: 4px 12px; border-radius: 4px; font-weight: 800; font-size: 14px; text-transform: uppercase; }}
  </style>
</head>
<body>
  <div class="invoice-card">
    <div class="header">
      <div>
        <div class="brand-title">HR SERVICES</div>
        <div style="font-size: 13px; color: #64748b; margin-top: 4px;">Enterprise Architecture & Business Management Systems</div>
        <div style="font-size: 12px; color: #64748b;">100 Bishopsgate, London, EC2N 4AG &bull; accounts@hr-services.local</div>
      </div>
      <div>
        <div class="inv-title">{inv['type'].upper()}</div>
        <div style="font-size: 13px; color: #64748b; text-align: right;">{inv['invoice_number']}</div>
        <div style="text-align: right; margin-top: 8px;">
          <span class="badge-paid">{inv['status']}</span>
        </div>
      </div>
    </div>

    <div style="display: flex; justify-content: space-between; margin: 30px 0; font-size: 13px;">
      <div>
        <div style="font-weight: bold; color: #64748b; text-transform: uppercase; font-size: 11px; margin-bottom: 4px;">Billed To:</div>
        <div style="font-weight: bold; font-size: 15px;">{inv['client_company'] or inv['client_name']}</div>
        <div>Attn: {inv['client_name']}</div>
        <div>{inv['client_address'] or ''}</div>
        <div>{inv['client_email']}</div>
        {f"<div>Tax/VAT: {inv['client_tax_id']}</div>" if inv['client_tax_id'] else ""}
      </div>
      <div style="text-align: right;">
        <div style="margin-bottom: 6px;"><span style="color: #64748b;">Issue Date:</span> <strong>{inv['issue_date']}</strong></div>
        <div style="margin-bottom: 6px;"><span style="color: #64748b;">Payment Due:</span> <strong>{inv['due_date']}</strong></div>
        <div><span style="color: #64748b;">Currency:</span> <strong>{inv['currency']}</strong></div>
      </div>
    </div>

    <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 24px;">
      <thead>
        <tr style="background: #f8fafc; color: #475569; text-transform: uppercase; font-size: 11px;">
          <th style="padding: 12px; text-align: left;">Description</th>
          <th style="padding: 12px; text-align: center;">Qty</th>
          <th style="padding: 12px; text-align: right;">Unit Price</th>
          <th style="padding: 12px; text-align: right;">Amount</th>
        </tr>
      </thead>
      <tbody>
        {items_html}
      </tbody>
    </table>

    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
      <div style="font-size: 12px; color: #64748b; max-width: 400px;">
        <div style="font-weight: bold; margin-bottom: 4px;">Remittance & Bank Details:</div>
        <div>Bank: Barclays Corporate Banking UK</div>
        <div>Account: HR Services Ltd</div>
        <div>Sort Code: 20-00-00 | Account No: 88291044</div>
      </div>

      <div style="width: 250px; font-size: 13px;">
        <div style="display: flex; justify-content: space-between; padding: 6px 0;">
          <span style="color: #64748b;">Subtotal:</span>
          <span>{inv['currency']} {inv['subtotal']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 6px 0;">
          <span style="color: #64748b;">VAT ({int(inv['tax_rate']*100)}%):</span>
          <span>{inv['currency']} {inv['tax_amount']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 10px 0; border-top: 2px solid #e2e8f0; font-size: 16px; font-weight: bold; color: #0f172a;">
          <span>Total:</span>
          <span>{inv['currency']} {inv['total']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 6px 0; color: #16a34a; font-weight: bold;">
          <span>Amount Paid:</span>
          <span>{inv['currency']} {inv['amount_paid']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 6px 0; color: #dc2626; font-weight: bold; border-top: 1px solid #e2e8f0;">
          <span>Balance Due:</span>
          <span>{inv['currency']} {inv['balance_due']:,.2f}</span>
        </div>
      </div>
    </div>
  </div>



</body>
</html>
"""

# --- Export Endpoints ---
@app.get("/api/export/csv")
def export_csv():
    with get_db() as conn:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Invoice Number", "Client", "Issue Date", "Due Date", "Subtotal", "Tax", "Total", "Paid", "Balance Due", "Status"])
        rows = conn.execute("""
        SELECT i.invoice_number, c.name, i.issue_date, i.due_date, i.subtotal, i.tax_amount, i.total, i.amount_paid, i.balance_due, i.status
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        ORDER BY i.id DESC
        """).fetchall()
        for r in rows:
            writer.writerow(list(r))
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hr_accounts_invoices.csv"})

@app.get("/api/export/json")
def export_json():
    with get_db() as conn:
        invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices").fetchall()]
        clients = [dict(r) for r in conn.execute("SELECT * FROM clients").fetchall()]
        expenses = [dict(r) for r in conn.execute("SELECT * FROM expenses").fetchall()]
        payments = [dict(r) for r in conn.execute("SELECT * FROM payments").fetchall()]
        return {"export_timestamp": datetime.now().isoformat(), "invoices": invoices, "clients": clients, "expenses": expenses, "payments": payments}

# --- Main Multi-View Shell UI ---
@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Accounts — Financial Invoicing & Ledger</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --hr-primary: #2563eb;
      --hr-primary-hover: #1d4ed8;
      --hr-primary-light: #eff6ff;
      --hr-success: #16a34a;
      --hr-warning: #d97706;
      --hr-danger: #dc2626;
      --hr-bg: #f8fafc;
      --hr-surface: #ffffff;
      --hr-surface-elevated: #f1f5f9;
      --hr-surface-hover: #f8fafc;
      --hr-text: #0f172a;
      --hr-text-secondary: #475569;
      --hr-muted: #64748b;
      --hr-border: #e2e8f0;
      --hr-border-subtle: #f1f5f9;
      --hr-radius-sm: 6px;
      --hr-radius-md: 10px;
      --hr-font-sans: 'Inter', sans-serif;
      --hr-font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--hr-bg); color: var(--hr-text); font-family: var(--hr-font-sans); display: flex; height: 100vh; overflow: hidden; }
    
    .sidebar { width: 250px; background: var(--hr-surface); border-right: 1px solid var(--hr-border); display: flex; flex-direction: column; flex-shrink: 0; }
    .brand-header { padding: 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--hr-border); }
    .brand-badge { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; font-weight: 800; font-size: 16px; padding: 6px 10px; border-radius: 8px; }
    .brand-title { font-weight: 700; font-size: 16px; color: var(--hr-text); }

    .nav-menu { list-style: none; padding: 16px 12px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .nav-item a { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: var(--hr-text-secondary); text-decoration: none; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 500; cursor: pointer; }
    .nav-item a:hover { background: var(--hr-surface-hover); color: var(--hr-text); }
    .nav-item.active a { background: var(--hr-primary-light); color: var(--hr-primary); font-weight: 600; border-left: 3px solid var(--hr-primary); }

    .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .top-bar { height: 64px; background: var(--hr-surface); border-bottom: 1px solid var(--hr-border); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; }
    .content-body { flex: 1; overflow-y: auto; padding: 28px; }
    .view-section { display: none; }
    .view-section.active { display: block; }

    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.15s; }
    .btn-primary { background: var(--hr-primary); color: #fff; }
    .btn-primary:hover { background: var(--hr-primary-hover); }
    .btn-secondary { background: var(--hr-surface); color: var(--hr-text); border: 1px solid var(--hr-border); }
    .btn-secondary:hover { background: var(--hr-surface-hover); }

    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .kpi-card { background: var(--hr-surface); border: 1px solid var(--hr-border); border-radius: var(--hr-radius-md); padding: 20px; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.03); }
    .kpi-label { font-size: 12px; color: var(--hr-muted); text-transform: uppercase; margin-bottom: 8px; font-weight: 600; }
    .kpi-val { font-size: 24px; font-weight: 800; font-family: var(--hr-font-mono); color: var(--hr-text); }

    .data-card { background: var(--hr-surface); border: 1px solid var(--hr-border); border-radius: var(--hr-radius-md); overflow: hidden; margin-bottom: 24px; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.03); }
    .card-header { padding: 18px 22px; border-bottom: 1px solid var(--hr-border); display: flex; justify-content: space-between; align-items: center; }
    .card-title { font-size: 15px; font-weight: 700; color: var(--hr-text); }

    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
    th { padding: 12px 18px; background: #f8fafc; color: var(--hr-muted); font-weight: 600; border-bottom: 1px solid var(--hr-border); font-size: 11px; text-transform: uppercase; }
    td { padding: 14px 18px; border-bottom: 1px solid var(--hr-border); color: var(--hr-text); }
    tr:hover td { background: #f8fafc; }

    .badge { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
    .badge-paid { background: #ecfdf5; color: #16a34a; }
    .badge-partial { background: #fffbeb; color: #d97706; }
    .badge-sent { background: #eff6ff; color: #2563eb; }
    .badge-draft { background: #f1f5f9; color: #64748b; }
    .badge-cancelled { background: #fef2f2; color: #dc2626; }

    .search-box { background: var(--hr-surface); border: 1px solid var(--hr-border); border-radius: 6px; padding: 8px 12px; font-size: 13px; color: var(--hr-text); font-family: inherit; }
  </style>
</head>
<body>

  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="brand-header">
      <div class="brand-badge">HR</div>
      <div>
        <div class="brand-title">HR Accounts</div>
        <div style="font-size:11px; color:var(--hr-muted);">Invoicing & Financial Ledger</div>
      </div>
    </div>
    <ul class="nav-menu">
      <li class="nav-item active" id="nav-dashboard"><a onclick="navigate('dashboard')">📊 Financial Overview</a></li>
      <li class="nav-item" id="nav-invoices"><a onclick="navigate('invoices')">🧾 Invoices & Billing</a></li>
      <li class="nav-item" id="nav-quotes"><a onclick="navigate('quotes')">📑 Quotations & Estimates</a></li>
      <li class="nav-item" id="nav-clients"><a onclick="navigate('clients')">👥 Clients & Debtors</a></li>
      <li class="nav-item" id="nav-expenses"><a onclick="navigate('expenses')">💸 Operating Expenses</a></li>
      <li class="nav-item" id="nav-reports"><a onclick="navigate('reports')">📈 P&L & Tax Reports</a></li>
    </ul>
    <div style="padding:16px; border-top:1px solid var(--hr-border); font-size:12px; color:var(--hr-text-secondary);">
      Ledger: <strong>UK Corporate Base (GBP)</strong>
    </div>
  </aside>

  <main class="main-wrapper">
    <header class="top-bar">
      <div style="font-size: 18px; font-weight: 700;" id="top-title">Financial Dashboard</div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-secondary" onclick="window.open('/api/export/csv')">📥 Export CSV</button>
        <button class="btn btn-primary" onclick="openInvoiceModal('Invoice')">+ New Invoice</button>
      </div>
    </header>

    <div class="content-body">
      
      <!-- 1. DASHBOARD VIEW -->
      <section id="view-dashboard" class="view-section active">
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Total Invoiced</div>
            <div class="kpi-val" id="kpi-invoiced">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Collected (Paid)</div>
            <div class="kpi-val" id="kpi-collected" style="color:var(--hr-success);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Outstanding Receivables</div>
            <div class="kpi-val" id="kpi-outstanding" style="color:var(--hr-warning);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Net Profit (Cash Margin)</div>
            <div class="kpi-val" id="kpi-netprofit" style="color:var(--hr-primary);">£0.00</div>
          </div>
        </div>

        <div class="data-card">
          <div class="card-header"><div class="card-title">Recent Invoices & Payment Status</div></div>
          <table>
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Client Company</th>
                <th>Issue / Due Date</th>
                <th>Total</th>
                <th>Balance Due</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="dash-invoices-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 2. INVOICES VIEW -->
      <section id="view-invoices" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">All Issued Invoices</div>
            <button class="btn btn-primary" onclick="openInvoiceModal('Invoice')">+ Create Invoice</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Client</th>
                <th>Dates</th>
                <th>Total (GBP)</th>
                <th>Paid</th>
                <th>Balance</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="invoices-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 3. QUOTES VIEW -->
      <section id="view-quotes" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Commercial Quotations & Estimates</div>
            <button class="btn btn-primary" onclick="openInvoiceModal('Quote')">+ Create Quote</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Quote #</th>
                <th>Client</th>
                <th>Issue Date</th>
                <th>Valid Until</th>
                <th>Total (GBP)</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="quotes-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 4. CLIENTS VIEW -->
      <section id="view-clients" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Client Accounts & Debtor Ledger</div>
            <button class="btn btn-primary" onclick="openClientModal()">+ Add Client</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Company Name</th>
                <th>Contact</th>
                <th>VAT/Tax ID</th>
                <th>Total Billed</th>
                <th>Outstanding</th>
                <th>Payment Terms</th>
              </tr>
            </thead>
            <tbody id="clients-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 5. EXPENSES VIEW -->
      <section id="view-expenses" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Operating Expenses & Cost Outflows</div>
            <button class="btn btn-primary" onclick="openExpenseModal()">+ Record Expense</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Vendor</th>
                <th>Amount (GBP)</th>
                <th>Receipt Ref</th>
                <th>Notes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="expenses-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 6. REPORTS VIEW -->
      <section id="view-reports" class="view-section">
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Gross Revenue (Invoiced)</div>
            <div class="kpi-val" id="rep-rev">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Total Outflows (Expenses)</div>
            <div class="kpi-val" id="rep-exp" style="color:var(--hr-danger);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Net Operating Margin</div>
            <div class="kpi-val" id="rep-profit" style="color:var(--hr-success);">£0.00</div>
          </div>
        </div>

        <div class="data-card">
          <div class="card-header"><div class="card-title">Expense Category Breakdown (P&L Impact)</div></div>
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Total Outflow (GBP)</th>
                <th>Share of Total Cost</th>
              </tr>
            </thead>
            <tbody id="rep-expense-tbody"></tbody>
          </table>
        </div>

        <div class="data-card">
          <div class="card-header"><div class="card-title">Data Sovereignty & Financial Ledger Exports</div></div>
          <div style="padding:20px; display:flex; gap:12px;">
            <button class="btn btn-primary" onclick="window.open('/api/export/csv')">📥 Download Invoices Ledger (CSV)</button>
            <button class="btn btn-secondary" onclick="window.open('/api/export/json')">📦 Export Complete Financial Dataset (JSON)</button>
          </div>
        </div>
      </section>

    </div>
  </main>

  <!-- Create Invoice / Quote Modal -->
  <div class="modal-overlay" id="modal-invoice" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:640px; max-height:90vh; overflow-y:auto; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);" id="modal-inv-title">Issue New Invoice</h3>
        <button style="background:none; border:none; color:var(--hr-muted); cursor:pointer; font-size:18px;" onclick="closeModals()">✕</button>
      </div>
      <form id="form-invoice" onsubmit="submitInvoice(event)">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Select Client</label>
            <select id="inv-client" class="search-box" style="width:100%;" required></select>
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Document Type</label>
            <select id="inv-type" class="search-box" style="width:100%;">
              <option value="Invoice">Tax Invoice (Standard)</option>
              <option value="Quote">Formal Quotation</option>
            </select>
          </div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:16px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Issue Date</label>
            <input type="date" id="inv-issue-date" class="search-box" style="width:100%;">
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Due Date</label>
            <input type="date" id="inv-due-date" class="search-box" style="width:100%;">
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">VAT Rate</label>
            <select id="inv-tax-rate" class="search-box" style="width:100%;">
              <option value="0.20">Standard UK VAT (20%)</option>
              <option value="0.00">Zero Rated (0%)</option>
            </select>
          </div>
        </div>

        <div style="border-top:1px solid var(--hr-border); padding-top:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong style="font-size:13px;">Line Items</strong>
            <button type="button" class="btn btn-secondary" style="padding:4px 8px; font-size:11px;" onclick="addInvoiceLine()">+ Add Item</button>
          </div>
          <div id="invoice-lines-container">
            <div class="inv-line-row" style="display:grid; grid-template-columns:3fr 1fr 1.5fr; gap:8px; margin-bottom:8px;">
              <input type="text" class="search-box line-desc" style="width:100%;" placeholder="Description of service/deliverable" required value="Professional Services Advisory Retainer">
              <input type="number" class="search-box line-qty" style="width:100%;" placeholder="Qty" value="1" min="1" required>
              <input type="number" step="0.01" class="search-box line-price" style="width:100%;" placeholder="Price (£)" value="750.00" required>
            </div>
          </div>
        </div>

        <div style="margin-bottom:16px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Payment Instructions / Notes</label>
          <textarea id="inv-notes" class="search-box" style="width:100%; height:60px; resize:none;" placeholder="Bank transfer instructions, remittance terms..."></textarea>
        </div>

        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" id="btn-submit-inv" class="btn btn-primary">Generate Document</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Record Payment Modal -->
  <div class="modal-overlay" id="modal-payment" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:460px; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);">Record Client Remittance</h3>
        <button style="background:none; border:none; color:var(--hr-muted); cursor:pointer; font-size:18px;" onclick="closeModals()">✕</button>
      </div>
      <form id="form-payment" onsubmit="submitPayment(event)">
        <input type="hidden" id="pay-inv-id">
        <div style="margin-bottom:12px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Invoice Number</label>
          <input type="text" id="pay-inv-num" class="search-box" style="width:100%; background:#f8fafc;" readonly>
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Amount Received (£)</label>
          <input type="number" step="0.01" id="pay-amount" class="search-box" style="width:100%; font-size:16px; font-weight:700;" required>
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Payment Method</label>
          <select id="pay-method" class="search-box" style="width:100%;">
            <option value="Bank Transfer">Bank Transfer (BACS/Faster Payments)</option>
            <option value="Credit/Debit Card">Credit/Debit Card</option>
            <option value="Direct Debit">Direct Debit</option>
            <option value="Cash">Cash / Cheque</option>
          </select>
        </div>
        <div style="margin-bottom:18px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Transaction Reference</label>
          <input type="text" id="pay-ref" class="search-box" style="width:100%;" placeholder="e.g. BACS-882910 / Bank Ref">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Payment</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Create Client Modal -->
  <div class="modal-overlay" id="modal-client" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:500px; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);">Add New Client Account</h3>
        <button style="background:none; border:none; color:var(--hr-muted); cursor:pointer; font-size:18px;" onclick="closeModals()">✕</button>
      </div>
      <form id="form-client" onsubmit="submitClient(event)">
        <div style="margin-bottom:12px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Company Name</label>
          <input type="text" id="cl-company" class="search-box" style="width:100%;" placeholder="e.g. Apex Precision Engineering Ltd" required>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Contact Person</label>
            <input type="text" id="cl-name" class="search-box" style="width:100%;" placeholder="e.g. Marcus Hughes" required>
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Email Address</label>
            <input type="email" id="cl-email" class="search-box" style="width:100%;" placeholder="e.g. accounts@apex.co.uk" required>
          </div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">VAT / Tax ID</label>
            <input type="text" id="cl-tax" class="search-box" style="width:100%;" placeholder="e.g. GB 992 1044 22">
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Payment Terms</label>
            <select id="cl-terms" class="search-box" style="width:100%;">
              <option value="14">Net 14 Days</option>
              <option value="30">Net 30 Days</option>
              <option value="7">Net 7 Days</option>
              <option value="0">Due on Receipt</option>
            </select>
          </div>
        </div>
        <div style="margin-bottom:18px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Billing Address</label>
          <input type="text" id="cl-address" class="search-box" style="width:100%;" placeholder="e.g. 54 Exchange Square, Birmingham, UK">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Client</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Create Expense Modal -->
  <div class="modal-overlay" id="modal-expense" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:480px; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);">Record Operating Expense</h3>
        <button style="background:none; border:none; color:var(--hr-muted); cursor:pointer; font-size:18px;" onclick="closeModals()">✕</button>
      </div>
      <form id="form-expense" onsubmit="submitExpense(event)">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Expense Category</label>
            <select id="exp-cat" class="search-box" style="width:100%;">
              <option value="Cloud Infrastructure">Cloud Infrastructure</option>
              <option value="Software Tools">Software Tools</option>
              <option value="Contractors">Contractors & Specialized Personnel</option>
              <option value="Office & Facilities">Office & Facilities</option>
              <option value="Legal & Professional">Legal & Professional</option>
            </select>
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Vendor / Payee</label>
            <input type="text" id="exp-vendor" class="search-box" style="width:100%;" placeholder="e.g. AWS Cloud UK" required>
          </div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Amount (£)</label>
            <input type="number" step="0.01" id="exp-amount" class="search-box" style="width:100%; font-size:15px; font-weight:700;" required placeholder="0.00">
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Expense Date</label>
            <input type="date" id="exp-date" class="search-box" style="width:100%;">
          </div>
        </div>
        <div style="margin-bottom:18px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Receipt Ref / Description</label>
          <input type="text" id="exp-notes" class="search-box" style="width:100%;" placeholder="e.g. Monthly cloud server cluster hosting">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Expense</button>
        </div>
      </form>
    </div>
  </div>

  <div id="hr-toast" style="position:fixed; bottom:24px; right:24px; background:#0f172a; color:#fff; padding:12px 20px; border-radius:8px; font-size:13px; font-weight:600; display:none; z-index:9999; box-shadow:0 10px 15px -3px rgba(0,0,0,0.2);">
    Action Complete
  </div>

  <script>
    let clientsCache = [];

    function showToast(msg, isSuccess = true) {
      const t = document.getElementById('hr-toast');
      t.innerText = msg;
      t.style.background = isSuccess ? '#0f172a' : '#dc2626';
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 3000);
    }

    function navigate(view) {
      document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      
      const sec = document.getElementById('view-' + view);
      const nav = document.getElementById('nav-' + view);
      if (sec) sec.classList.add('active');
      if (nav) nav.classList.add('active');

      const titles = {
        'dashboard': 'Financial Dashboard',
        'invoices': 'Invoices & Billing',
        'quotes': 'Quotations & Commercial Estimates',
        'clients': 'Clients & Debtor Profiles',
        'expenses': 'Operating Expenses',
        'reports': 'Financial Reports & P&L Analysis'
      };
      document.getElementById('top-title').innerText = titles[view] || 'Financial Management';
      window.location.hash = view;
      loadAccountsData();
    }

    async function loadAccountsData() {
      // 1. Dashboard Stats
      const res = await fetch('/api/dashboard/stats');
      const stats = await res.json();

      document.getElementById('kpi-invoiced').innerText = '£' + stats.total_invoiced.toLocaleString(undefined, {minimumFractionDigits:2});
      document.getElementById('kpi-collected').innerText = '£' + stats.total_collected.toLocaleString(undefined, {minimumFractionDigits:2});
      document.getElementById('kpi-outstanding').innerText = '£' + stats.total_outstanding.toLocaleString(undefined, {minimumFractionDigits:2});
      document.getElementById('kpi-netprofit').innerText = '£' + stats.net_profit.toLocaleString(undefined, {minimumFractionDigits:2});

      // 2. Invoices List
      const iRes = await fetch('/api/invoices?type=Invoice');
      const invoices = await iRes.json();

      const invoiceRows = invoices.map(inv => `
        <tr>
          <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-primary);">${inv.invoice_number}</td>
          <td><strong>${inv.client_company || inv.client_name}</strong><br><span style="font-size:11px; color:var(--hr-muted);">${inv.client_email}</span></td>
          <td style="font-family:var(--hr-font-mono); font-size:12px;">${inv.issue_date}<br><span style="color:var(--hr-muted);">Due: ${inv.due_date}</span></td>
          <td style="font-family:var(--hr-font-mono); font-weight:700;">£${inv.total.toFixed(2)}</td>
          <td style="font-family:var(--hr-font-mono); color:var(--hr-success);">£${inv.amount_paid.toFixed(2)}</td>
          <td style="font-family:var(--hr-font-mono); color:${inv.balance_due > 0 ? 'var(--hr-warning)' : 'var(--hr-muted)'}; font-weight:700;">£${inv.balance_due.toFixed(2)}</td>
          <td><span class="badge ${inv.status === 'Paid' ? 'badge-paid' : (inv.status === 'Partially Paid' ? 'badge-partial' : (inv.status === 'Cancelled' ? 'badge-cancelled' : 'badge-sent'))}">${inv.status}</span></td>
          <td>
            <div style="display:flex; gap:6px;">
              <a href="/api/invoices/${inv.id}/render" target="_blank" class="btn btn-secondary" style="padding:4px 8px; font-size:11px; text-decoration:none;">📄 View</a>
              ${inv.balance_due > 0 && inv.status !== 'Cancelled' ? `
                <button class="btn btn-primary" style="padding:4px 8px; font-size:11px;" onclick="openPaymentModal(${inv.id}, '${inv.invoice_number}', ${inv.balance_due})">💳 Pay</button>
                <button class="btn btn-secondary" style="padding:4px 8px; font-size:11px; color:var(--hr-danger);" onclick="cancelInvoice(${inv.id})">Cancel</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `).join('');

      document.getElementById('dash-invoices-tbody').innerHTML = invoiceRows;
      document.getElementById('invoices-tbody').innerHTML = invoiceRows;

      // 3. Quotes List
      const qRes = await fetch('/api/invoices?type=Quote');
      const quotes = await qRes.json();
      document.getElementById('quotes-tbody').innerHTML = quotes.map(q => `
        <tr>
          <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-primary);">${q.invoice_number}</td>
          <td><strong>${q.client_company || q.client_name}</strong><br><span style="font-size:11px; color:var(--hr-muted);">${q.client_email}</span></td>
          <td style="font-family:var(--hr-font-mono); font-size:12px;">${q.issue_date}</td>
          <td style="font-family:var(--hr-font-mono); font-size:12px;">${q.due_date}</td>
          <td style="font-family:var(--hr-font-mono); font-weight:700;">£${q.total.toFixed(2)}</td>
          <td><span class="badge badge-sent">${q.status}</span></td>
          <td>
            <div style="display:flex; gap:6px;">
              <a href="/api/invoices/${q.id}/render" target="_blank" class="btn btn-secondary" style="padding:4px 8px; font-size:11px; text-decoration:none;">📄 View</a>
              <button class="btn btn-primary" style="padding:4px 8px; font-size:11px;" onclick="convertQuote(${q.id})">⚡ Convert to Invoice</button>
            </div>
          </td>
        </tr>
      `).join('');

      // 4. Clients List
      const cRes = await fetch('/api/clients');
      clientsCache = await cRes.json();
      document.getElementById('clients-tbody').innerHTML = clientsCache.map(c => `
        <tr>
          <td><strong>${c.company || c.name}</strong></td>
          <td>${c.name}<br><span style="font-size:11px; color:var(--hr-muted);">${c.email}</span></td>
          <td style="font-family:var(--hr-font-mono); font-size:12px;">${c.tax_id || '—'}</td>
          <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-primary);">£${c.total_billed.toFixed(2)}</td>
          <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-warning);">£${c.total_receivable.toFixed(2)}</td>
          <td>Net ${c.payment_terms_days} days</td>
        </tr>
      `).join('');

      // 5. Expenses List
      const eRes = await fetch('/api/expenses');
      const expenses = await eRes.json();
      document.getElementById('expenses-tbody').innerHTML = expenses.map(e => `
        <tr>
          <td style="font-family:var(--hr-font-mono);">${e.expense_date}</td>
          <td><strong>${e.category}</strong></td>
          <td>${e.vendor}</td>
          <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-danger);">-£${e.amount.toFixed(2)}</td>
          <td style="font-family:var(--hr-font-mono); font-size:12px; color:var(--hr-muted);">${e.receipt_ref || '—'}</td>
          <td style="font-size:12px; color:var(--hr-text-secondary);">${e.notes || ''}</td>
          <td>
            <button class="btn btn-secondary" style="padding:4px 8px; font-size:11px; color:var(--hr-danger);" onclick="deleteExpense(${e.id})">Delete</button>
          </td>
        </tr>
      `).join('');

      // 6. Reports View
      const pnlRes = await fetch('/api/reports/pnl');
      const pnl = await pnlRes.json();
      document.getElementById('rep-rev').innerText = '£' + pnl.gross_revenue.toLocaleString(undefined, {minimumFractionDigits:2});
      document.getElementById('rep-exp').innerText = '-£' + pnl.total_expenses.toLocaleString(undefined, {minimumFractionDigits:2});
      document.getElementById('rep-profit').innerText = '£' + pnl.net_profit.toLocaleString(undefined, {minimumFractionDigits:2}) + ` (${pnl.margin_pct}%)`;

      document.getElementById('rep-expense-tbody').innerHTML = pnl.expense_breakdown.map(eb => {
        const pct = pnl.total_expenses > 0 ? ((eb.amount / pnl.total_expenses) * 100).toFixed(1) : '0';
        return `
          <tr>
            <td><strong>${eb.category}</strong></td>
            <td style="font-family:var(--hr-font-mono); font-weight:700; color:var(--hr-danger);">£${eb.amount.toFixed(2)}</td>
            <td style="font-family:var(--hr-font-mono); font-weight:600;">${pct}%</td>
          </tr>
        `;
      }).join('');
    }

    function openInvoiceModal(type = 'Invoice') {
      document.getElementById('form-invoice').reset();
      document.getElementById('inv-type').value = type;
      document.getElementById('modal-inv-title').innerText = type === 'Invoice' ? 'Issue New Client Invoice' : 'Create Formal Quotation';
      
      const sel = document.getElementById('inv-client');
      sel.innerHTML = clientsCache.map(c => `<option value="${c.id}">${c.company || c.name} (${c.email})</option>`).join('');
      document.getElementById('modal-invoice').style.display = 'flex';
    }

    function openClientModal() {
      document.getElementById('form-client').reset();
      document.getElementById('modal-client').style.display = 'flex';
    }

    function openExpenseModal() {
      document.getElementById('form-expense').reset();
      document.getElementById('exp-date').value = new Date().toISOString().split('T')[0];
      document.getElementById('modal-expense').style.display = 'flex';
    }

    function closeModals() {
      document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
    }

    function addInvoiceLine() {
      const div = document.createElement('div');
      div.className = 'inv-line-row';
      div.style.cssText = 'display:grid; grid-template-columns:3fr 1fr 1.5fr; gap:8px; margin-bottom:8px;';
      div.innerHTML = `
        <input type="text" class="search-box line-desc" style="width:100%;" placeholder="Description of service/deliverable" required>
        <input type="number" class="search-box line-qty" style="width:100%;" placeholder="Qty" value="1" min="1" required>
        <input type="number" step="0.01" class="search-box line-price" style="width:100%;" placeholder="Price (£)" value="150.00" required>
      `;
      document.getElementById('invoice-lines-container').appendChild(div);
    }

    async function submitInvoice(e) {
      e.preventDefault();
      const btn = document.getElementById('btn-submit-inv');
      btn.innerText = 'Generating...';
      btn.disabled = true;

      const lineRows = document.querySelectorAll('.inv-line-row');
      const items = Array.from(lineRows).map(row => ({
        description: row.querySelector('.line-desc').value,
        quantity: parseFloat(row.querySelector('.line-qty').value),
        unit_price: parseFloat(row.querySelector('.line-price').value)
      }));

      const payload = {
        client_id: parseInt(document.getElementById('inv-client').value),
        type: document.getElementById('inv-type').value,
        issue_date: document.getElementById('inv-issue-date').value || null,
        due_date: document.getElementById('inv-due-date').value || null,
        tax_rate: parseFloat(document.getElementById('inv-tax-rate').value),
        items: items,
        notes: document.getElementById('inv-notes').value
      };

      try {
        const res = await fetch('/api/invoices', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.status === 201) {
          showToast('✓ Document generated successfully!');
          closeModals();
          loadAccountsData();
        } else {
          showToast('Failed to generate document', false);
        }
      } catch (err) {
        showToast('Error connecting to server', false);
      } finally {
        btn.innerText = 'Generate Document';
        btn.disabled = false;
      }
    }

    async function submitClient(e) {
      e.preventDefault();
      const payload = {
        company: document.getElementById('cl-company').value,
        name: document.getElementById('cl-name').value,
        email: document.getElementById('cl-email').value,
        tax_id: document.getElementById('cl-tax').value,
        payment_terms_days: parseInt(document.getElementById('cl-terms').value),
        address: document.getElementById('cl-address').value
      };

      const res = await fetch('/api/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.status === 201) {
        showToast('✓ Client created successfully!');
        closeModals();
        loadAccountsData();
      }
    }

    async function submitExpense(e) {
      e.preventDefault();
      const payload = {
        category: document.getElementById('exp-cat').value,
        vendor: document.getElementById('exp-vendor').value,
        amount: parseFloat(document.getElementById('exp-amount').value),
        expense_date: document.getElementById('exp-date').value || null,
        notes: document.getElementById('exp-notes').value
      };

      const res = await fetch('/api/expenses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.status === 201) {
        showToast('✓ Expense recorded!');
        closeModals();
        loadAccountsData();
      }
    }

    function openPaymentModal(invId, invNum, balance) {
      document.getElementById('pay-inv-id').value = invId;
      document.getElementById('pay-inv-num').value = invNum;
      document.getElementById('pay-amount').value = balance.toFixed(2);
      document.getElementById('modal-payment').style.display = 'flex';
    }

    async function submitPayment(e) {
      e.preventDefault();
      const invId = parseInt(document.getElementById('pay-inv-id').value);
      const payload = {
        invoice_id: invId,
        amount: parseFloat(document.getElementById('pay-amount').value),
        payment_method: document.getElementById('pay-method').value,
        reference: document.getElementById('pay-ref').value
      };

      const res = await fetch('/api/payments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.status === 201) {
        showToast('✓ Payment recorded successfully!');
        closeModals();
        loadAccountsData();
      }
    }

    async function convertQuote(id) {
      if (confirm('Convert this Quotation into a live Invoice?')) {
        const res = await fetch(`/api/invoices/${id}/convert-quote`, { method: 'POST' });
        if (res.ok) {
          showToast('✓ Quotation converted to live Tax Invoice!');
          loadAccountsData();
        }
      }
    }

    async function cancelInvoice(id) {
      if (confirm('Cancel this invoice?')) {
        await fetch(`/api/invoices/${id}/cancel`, { method: 'PATCH' });
        showToast('✓ Invoice cancelled');
        loadAccountsData();
      }
    }

    async function deleteExpense(id) {
      if (confirm('Delete this expense record?')) {
        await fetch(`/api/expenses/${id}`, { method: 'DELETE' });
        showToast('✓ Expense deleted');
        loadAccountsData();
      }
    }

    // Keyboard ESC listener
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeModals();
    });

    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace('#', '') || 'dashboard';
      navigate(hash);
    });

    window.addEventListener('DOMContentLoaded', () => {
      const hash = window.location.hash.replace('#', '') || 'dashboard';
      navigate(hash);
    });
  </script>
</body>
</html>
"""
