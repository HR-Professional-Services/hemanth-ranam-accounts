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
        "brand_name": "HR",
        "product_name": "HR Accounts",
        "author": "Hemanth Ranam",
        "primary_color": "#3b82f6",
        "dark_bg": "#090d16",
        "surface_bg": "#101726"
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
        net_profit = total_collected - total_expenses
        profit_margin = round((net_profit / total_collected * 100), 1) if total_collected > 0 else 0.0

        # Overdue Invoices
        overdue_count = conn.execute("SELECT COUNT(*) FROM invoices WHERE status != 'Paid' AND due_date < date('now')").fetchone()[0]
        overdue_amount = conn.execute("SELECT COALESCE(SUM(balance_due), 0) FROM invoices WHERE status != 'Paid' AND due_date < date('now')").fetchone()[0]

        # Expense Breakdown by Category
        expenses_by_cat = conn.execute("""
        SELECT category, COALESCE(SUM(amount), 0) as total FROM expenses GROUP BY category ORDER BY total DESC
        """).fetchall()

        return {
            "total_invoiced": total_invoiced,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "profit_margin_pct": profit_margin,
            "overdue_count": overdue_count,
            "overdue_amount": overdue_amount,
            "expense_categories": [dict(r) for r in expenses_by_cat]
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
        if status:
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
        tax_amt = (subtotal - payload.discount) * payload.tax_rate
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
        rows = conn.execute("SELECT * FROM expenses ORDER BY expense_date DESC").fetchall()
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

# --- Institutional Printable HTML / PDF Invoice Renderer ---
@app.get("/api/invoices/{invoice_id}/render", response_class=HTMLResponse)
@app.get("/api/invoices/{invoice_id}/pdf", response_class=HTMLResponse)
def render_invoice_pdf(invoice_id: int):
    detail = get_invoice_detail(invoice_id)
    inv = detail["invoice"]
    items = detail["items"]

    items_html = "".join([f"""
    <tr>
      <td style="padding: 12px; border-bottom: 1px solid #e2e8f0;">{itm['description']}</td>
      <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: center;">{itm['quantity']}</td>
      <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: right;">{inv['currency']} {itm['unit_price']:,.2f}</td>
      <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold;">{inv['currency']} {itm['total']:,.2f}</td>
    </tr>
    """ for itm in items])

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Invoice {inv['invoice_number']} — Hemanth Ranam Professional Services</title>
  <style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; background: #fff; padding: 40px; margin: 0; }}
    .invoice-card {{ max-width: 800px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 40px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #2563eb; padding-bottom: 20px; }}
    .brand-title {{ font-size: 24px; font-weight: 800; color: #1e3a8a; }}
    .inv-title {{ font-size: 28px; font-weight: 800; color: #2563eb; text-align: right; }}
    .badge-paid {{ color: #10b981; border: 2px solid #10b981; padding: 4px 12px; border-radius: 4px; font-weight: 800; font-size: 14px; text-transform: uppercase; }}
  </style>
</head>
<body>
  <div class="invoice-card">
    <div class="header">
      <div>
        <div class="brand-title">HR PROFESSIONAL SERVICES</div>
        <div style="font-size: 13px; color: #64748b; margin-top: 4px;">Hemanth Ranam Solutions Architecture & Engineering</div>
        <div style="font-size: 12px; color: #64748b;">Enterprise Business Automation & Cloud Systems</div>
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
        <div>Account: Hemanth Ranam Professional Services</div>
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
        <div style="display: flex; justify-content: space-between; padding: 10px 0; border-top: 2px solid #e2e8f0; font-size: 16px; font-weight: bold; color: #1e3a8a;">
          <span>Total:</span>
          <span>{inv['currency']} {inv['total']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 6px 0; color: #10b981; font-weight: bold;">
          <span>Amount Paid:</span>
          <span>{inv['currency']} {inv['amount_paid']:,.2f}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 6px 0; color: #ef4444; font-weight: bold; border-top: 1px solid #e2e8f0;">
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
        return {"export_timestamp": "2026-08-28T00:00:00Z", "invoices": invoices, "clients": clients, "expenses": expenses, "payments": payments}

# --- Main Multi-View Shell UI ---
@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Accounts — Invoicing, Ledger & Financial Analytics</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --hr-primary: #2563eb;
      --hr-primary-hover: #1d4ed8;
      --hr-primary-light: #eff6ff;
      --hr-success: #10b981;
      --hr-warning: #f59e0b;
      --hr-danger: #ef4444;
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
    .nav-item a { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: var(--hr-text-secondary); text-decoration: none; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 500; }
    .nav-item a:hover { background: var(--hr-surface-hover); color: var(--hr-text); }
    .nav-item.active a { background: var(--hr-primary-light); color: var(--hr-primary); font-weight: 600; border-left: 3px solid var(--hr-primary); }

    .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .top-bar { height: 64px; background: var(--hr-surface); border-bottom: 1px solid var(--hr-border); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; }
    .content-body { flex: 1; overflow-y: auto; padding: 28px; }
    .view-section { display: none; }
    .view-section.active { display: block; }

    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; border: none; }
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
    .badge-paid { background: #ecfdf5; color: #10b981; }
    .badge-partial { background: #fffbeb; color: #f59e0b; }
    .badge-sent { background: #eff6ff; color: #3b82f6; }
    .badge-draft { background: #f1f5f9; color: #64748b; }
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
      <li class="nav-item active" id="nav-dashboard"><a href="#dashboard" onclick="navigate('dashboard')">📊 Financial Overview</a></li>
      <li class="nav-item" id="nav-invoices"><a href="#invoices" onclick="navigate('invoices')">🧾 Invoices & Billing</a></li>
      <li class="nav-item" id="nav-clients"><a href="#clients" onclick="navigate('clients')">👥 Clients & Debtors</a></li>
      <li class="nav-item" id="nav-expenses"><a href="#expenses" onclick="navigate('expenses')">💸 Expenses</a></li>
      <li class="nav-item" id="nav-reports"><a href="#reports" onclick="navigate('reports')">📈 P&L & Tax Export</a></li>
    </ul>
    <div style="padding:16px; border-top:1px solid var(--border-subtle); font-size:12px; color:var(--text-secondary);">
      Ledger: <strong>Single-Tenant Base</strong>
    </div>
  </aside>

  <main class="main-wrapper">
    <header class="top-bar">
      <div style="font-size: 18px; font-weight: 700;" id="top-title">Financial Dashboard</div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-secondary" onclick="window.open('/api/export/csv')">📥 Export CSV</button>
        <button class="btn btn-primary" onclick="openInvoiceModal()">+ New Invoice</button>
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
            <div class="kpi-val" id="kpi-collected" style="color:var(--accent-success);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Outstanding Receivables</div>
            <div class="kpi-val" id="kpi-outstanding" style="color:var(--accent-warning);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Net Profit (Cash Margin)</div>
            <div class="kpi-val" id="kpi-netprofit" style="color:var(--accent-primary);">£0.00</div>
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
            <button class="btn btn-primary" onclick="openInvoiceModal()">+ Create Invoice</button>
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

      <!-- 3. CLIENTS VIEW -->
      <section id="view-clients" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Client Accounts & Billing Profiles</div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Company Name</th>
                <th>Contact</th>
                <th>VAT/Tax ID</th>
                <th>Total Billed</th>
                <th>Outstanding</th>
                <th>Terms</th>
              </tr>
            </thead>
            <tbody id="clients-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 4. EXPENSES VIEW -->
      <section id="view-expenses" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Operating Expenses & Outflows</div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Vendor</th>
                <th>Amount</th>
                <th>Receipt Ref</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody id="expenses-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 5. REPORTS VIEW -->
      <section id="view-reports" class="view-section">
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Export Invoices (CSV)</div>
            <button class="btn btn-primary" style="margin-top:10px;" onclick="window.open('/api/export/csv')">📥 Download Invoices CSV</button>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Export Complete Financial JSON</div>
            <button class="btn btn-secondary" style="margin-top:10px;" onclick="window.open('/api/export/json')">📦 Export Complete JSON</button>
          </div>
        </div>
      </section>

    </div>
  </main>

  <script>
    function navigate(view) {
      document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      const sec = document.getElementById('view-' + view);
      const nav = document.getElementById('nav-' + view);
      if (sec) sec.classList.add('active');
      if (nav) nav.classList.add('active');
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
      const iRes = await fetch('/api/invoices');
      const invoices = await iRes.json();

      const invoiceRows = invoices.map(inv => `
        <tr>
          <td><strong>${inv.invoice_number}</strong></td>
          <td><strong>${inv.client_company || inv.client_name}</strong><br><span style="font-size:11px; color:var(--text-muted);">${inv.client_email}</span></td>
          <td style="font-family:var(--font-mono); font-size:12px;">${inv.issue_date}<br><span style="color:var(--text-muted);">Due: ${inv.due_date}</span></td>
          <td style="font-family:var(--font-mono); font-weight:700;">£${inv.total.toFixed(2)}</td>
          <td style="font-family:var(--font-mono); color:var(--accent-success);">£${inv.amount_paid.toFixed(2)}</td>
          <td style="font-family:var(--font-mono); color:${inv.balance_due > 0 ? 'var(--accent-warning)' : 'var(--text-muted)'}; font-weight:700;">£${inv.balance_due.toFixed(2)}</td>
          <td><span class="badge ${inv.status === 'Paid' ? 'badge-paid' : (inv.status === 'Partially Paid' ? 'badge-partial' : 'badge-sent')}">${inv.status}</span></td>
          <td>
            <a href="/api/invoices/${inv.id}/render" target="_blank" class="btn btn-secondary" style="padding:4px 8px; font-size:11px; text-decoration:none;">📄 View / Print</a>
          </td>
        </tr>
      `).join('');

      document.getElementById('dash-invoices-tbody').innerHTML = invoiceRows;
      document.getElementById('invoices-tbody').innerHTML = invoiceRows;

      // 3. Clients List
      const cRes = await fetch('/api/clients');
      const clients = await cRes.json();
      document.getElementById('clients-tbody').innerHTML = clients.map(c => `
        <tr>
          <td><strong>${c.company || c.name}</strong></td>
          <td>${c.name}<br><span style="font-size:11px; color:var(--text-muted);">${c.email}</span></td>
          <td style="font-family:var(--font-mono); font-size:12px;">${c.tax_id || '—'}</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-primary);">£${c.total_billed.toFixed(2)}</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-warning);">£${c.total_receivable.toFixed(2)}</td>
          <td>Net ${c.payment_terms_days} days</td>
        </tr>
      `).join('');

      // 4. Expenses List
      const eRes = await fetch('/api/expenses');
      const expenses = await eRes.json();
      document.getElementById('expenses-tbody').innerHTML = expenses.map(e => `
        <tr>
          <td style="font-family:var(--font-mono);">${e.expense_date}</td>
          <td><strong>${e.category}</strong></td>
          <td>${e.vendor}</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-danger);">£${e.amount.toFixed(2)}</td>
          <td style="font-family:var(--font-mono); font-size:12px; color:var(--text-muted);">${e.receipt_ref || '—'}</td>
          <td style="font-size:12px; color:var(--text-secondary);">${e.notes || ''}</td>
        </tr>
      `).join('');
    }

  <!-- Create Invoice Modal -->
  <div class="modal-overlay" id="modal-invoice" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:640px; max-height:90vh; overflow-y:auto; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);">Issue New Client Invoice</h3>
        <button style="background:none; border:none; color:var(--hr-muted); cursor:pointer; font-size:18px;" onclick="closeModals()">✕</button>
      </div>
      <form id="form-invoice" onsubmit="submitInvoice(event)">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Select Client</label>
            <select id="inv-client" class="search-box" style="width:100%;" required>
              <!-- Populated dynamically -->
            </select>
          </div>
          <div>
            <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Invoice Type</label>
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
              <input type="text" class="search-box line-desc" style="width:100%;" placeholder="Description of service/deliverable" required value="Professional Services Consultation">
              <input type="number" class="search-box line-qty" style="width:100%;" placeholder="Qty" value="1" min="1" required>
              <input type="number" step="0.01" class="search-box line-price" style="width:100%;" placeholder="Price (£)" value="450.00" required>
            </div>
          </div>
        </div>

        <div style="margin-bottom:16px;">
          <label style="display:block; font-size:12px; font-weight:600; color:var(--hr-muted); margin-bottom:4px;">Payment Instructions / Notes</label>
          <textarea id="inv-notes" class="search-box" style="width:100%; height:60px; resize:none;" placeholder="Bank transfer terms, payment details..."></textarea>
        </div>

        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" id="btn-submit-inv" class="btn btn-primary">Generate Invoice</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Record Payment Modal -->
  <div class="modal-overlay" id="modal-payment" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
    <div class="modal-box" style="background:#fff; border:1px solid var(--hr-border); border-radius:10px; width:100%; max-width:460px; padding:24px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
        <h3 style="font-size:16px; font-weight:700; color:var(--hr-text);">Record Client Payment</h3>
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
          <input type="text" id="pay-ref" class="search-box" style="width:100%;" placeholder="e.g. TXN-998822 / Bank Ref">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" onclick="closeModals()">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Payment</button>
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
      t.style.background = isSuccess ? '#0f172a' : '#ef4444';
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 3000);
    }

    function openInvoiceModal() {
      document.getElementById('form-invoice').reset();
      const sel = document.getElementById('inv-client');
      sel.innerHTML = clientsCache.map(c => `<option value="${c.id}">${c.company || c.name} (${c.email})</option>`).join('');
      document.getElementById('modal-invoice').style.display = 'flex';
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
        <input type="number" step="0.01" class="search-box line-price" style="width:100%;" placeholder="Price (£)" value="100.00" required>
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
          showToast('✓ Invoice issued successfully!');
          closeModals();
          loadAccountsData();
        } else {
          showToast('Failed to issue invoice', false);
        }
      } catch (err) {
        showToast('Error connecting to server', false);
      } finally {
        btn.innerText = 'Generate Invoice';
        btn.disabled = false;
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

    async function cancelInvoice(id) {
      if (confirm('Cancel this invoice?')) {
        await fetch(`/api/invoices/${id}/cancel`, { method: 'PATCH' });
        showToast('✓ Invoice cancelled');
        loadAccountsData();
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      loadAccountsData();
      const hash = window.location.hash.replace('#', '') || 'dashboard';
      navigate(hash);
    });
  </script>
</body>
</html>
"""
