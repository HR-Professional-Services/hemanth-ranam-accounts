import os
import json
import csv
import io
import time
import uuid
from datetime import datetime, date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from .database import get_db, init_db

app = FastAPI(
    title="HR Accounts — Hemanth Ranam Professional Services",
    description="Small-Business Invoicing, Quotes, Expenses & Cashflow Engine.",
    version="1.0.0"
)

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
        "brand_name": "Hemanth Ranam Professional Services",
        "product_name": "HR Accounts",
        "theme": {"primary_color": "#2563eb", "bg_canvas": "#ffffff"}
    }

@app.on_event("startup")
def on_startup():
    init_db()

# --- Pydantic Models ---
class ClientCreate(BaseModel):
    name: str
    email: str
    company: Optional[str] = ""
    address: Optional[str] = ""
    currency: Optional[str] = "USD"
    tax_id: Optional[str] = ""

class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float

class InvoiceCreate(BaseModel):
    client_id: int
    type: Optional[str] = "Invoice" # Invoice, Quote
    issue_date: str # YYYY-MM-DD
    due_date: str   # YYYY-MM-DD
    currency: Optional[str] = "USD"
    items: List[LineItem]
    tax_rate: Optional[float] = 0.0
    discount: Optional[float] = 0.0
    notes: Optional[str] = ""

class PaymentCreate(BaseModel):
    amount: float
    payment_date: str
    payment_method: Optional[str] = "Bank Transfer"
    reference: Optional[str] = ""

class ExpenseCreate(BaseModel):
    category: str
    vendor: str
    amount: float
    currency: Optional[str] = "USD"
    expense_date: str
    notes: Optional[str] = ""

# --- API Endpoints ---

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "HR Accounts",
        "version": "1.0.0",
        "database": "SQLite WAL"
    }

@app.get("/api/branding")
def branding():
    return load_branding()

@app.get("/api/stats")
def get_financial_stats():
    with get_db() as conn:
        cursor = conn.cursor()
        total_invoiced = cursor.execute("SELECT COALESCE(SUM(total), 0.0) FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'").fetchone()[0]
        total_paid = cursor.execute("SELECT COALESCE(SUM(amount_paid), 0.0) FROM invoices WHERE type = 'Invoice' AND status != 'Cancelled'").fetchone()[0]
        total_receivables = total_invoiced - total_paid
        total_expenses = cursor.execute("SELECT COALESCE(SUM(amount), 0.0) FROM expenses").fetchone()[0]
        net_profit = total_paid - total_expenses
        count_invoices = cursor.execute("SELECT COUNT(*) FROM invoices WHERE type = 'Invoice'").fetchone()[0]
        count_quotes = cursor.execute("SELECT COUNT(*) FROM invoices WHERE type = 'Quote'").fetchone()[0]

    return {
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_receivables": max(0.0, total_receivables),
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "count_invoices": count_invoices,
        "count_quotes": count_quotes
    }

# Clients CRUD
@app.get("/api/clients")
def list_clients():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/clients", status_code=201)
def create_client(client: ClientCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO clients (name, email, company, address, currency, tax_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (client.name, client.email, client.company, client.address, client.currency, client.tax_id))
        conn.commit()
        return {"id": cursor.lastrowid, **client.model_dump()}

# Invoices & Quotes CRUD
@app.get("/api/invoices")
def list_invoices(type: Optional[str] = None, status: Optional[str] = None):
    with get_db() as conn:
        query = """
        SELECT i.*, c.name as client_name, c.company as client_company, c.email as client_email
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE 1=1
        """
        params = []
        if type:
            query += " AND i.type = ?"
            params.append(type)
        if status:
            query += " AND i.status = ?"
            params.append(status)
        query += " ORDER BY i.issue_date DESC, i.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/invoices", status_code=201)
def create_invoice(req: InvoiceCreate):
    if not req.items:
        raise HTTPException(status_code=400, detail="Invoice must contain at least one line item")

    with get_db() as conn:
        cursor = conn.cursor()
        
        # Calculate totals
        subtotal = sum(item.quantity * item.unit_price for item in req.items)
        tax_amount = subtotal * (req.tax_rate / 100.0)
        total = subtotal + tax_amount - req.discount
        
        prefix = "INV" if req.type == "Invoice" else "QUO"
        invoice_number = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:4].upper()}"

        cursor.execute("""
        INSERT INTO invoices (invoice_number, client_id, type, issue_date, due_date, currency, subtotal, tax_rate, tax_amount, discount, total, amount_paid, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'Sent', ?)
        """, (invoice_number, req.client_id, req.type, req.issue_date, req.due_date, req.currency, subtotal, req.tax_rate, tax_amount, req.discount, total, req.notes))
        invoice_id = cursor.lastrowid

        for item in req.items:
            item_total = item.quantity * item.unit_price
            cursor.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (?, ?, ?, ?, ?)
            """, (invoice_id, item.description, item.quantity, item.unit_price, item_total))

        conn.commit()
        return {"id": invoice_id, "invoice_number": invoice_number, "total": total, "status": "Sent"}

# Record Payment
@app.post("/api/invoices/{invoice_id}/payments", status_code=201)
def record_payment(invoice_id: int, p: PaymentCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        inv = cursor.execute("SELECT total, amount_paid FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        new_paid = inv[1] + p.amount
        new_status = "Paid" if new_paid >= inv[0] else "Partially Paid"

        cursor.execute("""
        INSERT INTO payments (invoice_id, amount, payment_date, payment_method, reference)
        VALUES (?, ?, ?, ?, ?)
        """, (invoice_id, p.amount, p.payment_date, p.payment_method, p.reference))

        cursor.execute("UPDATE invoices SET amount_paid = ?, status = ? WHERE id = ?", (new_paid, new_status, invoice_id))
        conn.commit()

        return {"status": "success", "invoice_id": invoice_id, "new_paid_total": new_paid, "invoice_status": new_status}

# Expenses CRUD
@app.get("/api/expenses")
def list_expenses():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM expenses ORDER BY expense_date DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/expenses", status_code=201)
def create_expense(exp: ExpenseCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO expenses (category, vendor, amount, currency, expense_date, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (exp.category, exp.vendor, exp.amount, exp.currency, exp.expense_date, exp.notes))
        conn.commit()
        return {"id": cursor.lastrowid, **exp.model_dump()}

# Printable Invoice Render
@app.get("/api/invoices/{invoice_id}/render", response_class=HTMLResponse)
def render_invoice_html(invoice_id: int):
    branding = load_branding()
    biz = branding.get("business_info", {})
    with get_db() as conn:
        cursor = conn.cursor()
        inv = cursor.execute("""
            SELECT i.*, c.name as client_name, c.company as client_company, c.email as client_email, c.address as client_address
            FROM invoices i
            JOIN clients c ON i.client_id = c.id
            WHERE i.id = ?
        """, (invoice_id,)).fetchone()
        
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        items = cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,)).fetchall()

    items_html = "".join([f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e2e8f0;">{it['description']}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: center;">{it['quantity']}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: right;">{inv['currency']} {it['unit_price']:.2f}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600;">{inv['currency']} {it['total']:.2f}</td>
        </tr>
    """ for it in items])

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{inv['type']} {inv['invoice_number']} — {biz.get('legal_name', 'Hemanth Ranam')}</title>
        <style>
            body {{ font-family: 'Inter', system-ui, sans-serif; color: #0f172a; margin: 40px auto; max-width: 800px; line-height: 1.5; }}
            .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #2563eb; padding-bottom: 20px; }}
            .title {{ font-size: 28px; font-weight: 800; color: #2563eb; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; background: #ecfdf5; color: #059669; font-weight: 700; font-size: 12px; text-transform: uppercase; }}
            .meta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin: 30px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background: #f8fafc; padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; border-bottom: 2px solid #e2e8f0; }}
            .totals {{ margin-top: 30px; float: right; width: 300px; }}
            .totals-row {{ display: flex; justify-content: space-between; padding: 6px 0; }}
            .grand-total {{ font-size: 20px; font-weight: 800; color: #2563eb; border-top: 2px solid #e2e8f0; padding-top: 8px; }}
            .footer {{ clear: both; margin-top: 80px; padding-top: 20px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <div class="title">{biz.get('legal_name', 'Hemanth Ranam Professional Services')}</div>
                <div style="color: #64748b; font-size: 14px; margin-top: 4px;">{biz.get('address', 'London, UK')} • {biz.get('email', '')}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 20px; font-weight: 700;">{inv['type'].upper()}</div>
                <div style="font-weight: 600; color: #64748b;">{inv['invoice_number']}</div>
                <div class="badge" style="margin-top: 6px;">{inv['status']}</div>
            </div>
        </div>

        <div class="meta-grid">
            <div>
                <div style="font-size: 12px; text-transform: uppercase; color: #64748b; font-weight: 700;">Billed To:</div>
                <div style="font-weight: 700; font-size: 16px; margin-top: 4px;">{inv['client_name']}</div>
                <div>{inv['client_company'] or ''}</div>
                <div style="color: #64748b;">{inv['client_address'] or ''}</div>
                <div style="color: #64748b;">{inv['client_email']}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 12px; text-transform: uppercase; color: #64748b; font-weight: 700;">Invoice Details:</div>
                <div style="margin-top: 4px;"><strong>Issue Date:</strong> {inv['issue_date']}</div>
                <div><strong>Due Date:</strong> {inv['due_date']}</div>
                <div><strong>Currency:</strong> {inv['currency']}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Description</th>
                    <th style="text-align: center;">Qty</th>
                    <th style="text-align: right;">Unit Price</th>
                    <th style="text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>

        <div class="totals">
            <div class="totals-row"><span>Subtotal</span><span>{inv['currency']} {inv['subtotal']:.2f}</span></div>
            <div class="totals-row"><span>Tax ({inv['tax_rate']}%)</span><span>{inv['currency']} {inv['tax_amount']:.2f}</span></div>
            <div class="totals-row grand-total"><span>Total</span><span>{inv['currency']} {inv['total']:.2f}</span></div>
            <div class="totals-row" style="color: #059669; font-weight: 600;"><span>Amount Paid</span><span>{inv['currency']} {inv['amount_paid']:.2f}</span></div>
        </div>

        <div class="footer">
            <div><strong>Payment Details:</strong> {biz.get('bank_details', '')}</div>
            <div style="margin-top: 4px;">{biz.get('payment_terms', '')}</div>
        </div>
    </body>
    </html>
    """

# Data Export
@app.get("/api/export/csv")
def export_csv():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.id, i.invoice_number, i.type, i.issue_date, i.due_date, i.currency, i.total, i.amount_paid, i.status, c.name, c.company
            FROM invoices i
            JOIN clients c ON i.client_id = c.id
            ORDER BY i.issue_date DESC
        """).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Invoice Number", "Type", "Issue Date", "Due Date", "Currency", "Total", "Amount Paid", "Status", "Client Name", "Client Company"])
    for r in rows:
        writer.writerow(list(r))
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hr_accounts_invoices.csv"})

@app.get("/api/export/json")
def export_json():
    with get_db() as conn:
        invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices").fetchall()]
        clients = [dict(r) for r in conn.execute("SELECT * FROM clients").fetchall()]
        expenses = [dict(r) for r in conn.execute("SELECT * FROM expenses").fetchall()]
        payments = [dict(r) for r in conn.execute("SELECT * FROM payments").fetchall()]
    return JSONResponse(content={
        "metadata": {"exporter": "Hemanth Ranam Professional Services - HR Accounts", "version": "1.0.0"},
        "invoices": invoices,
        "clients": clients,
        "expenses": expenses,
        "payments": payments
    })

# HTML Dashboard Interface
UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Accounts — Hemanth Ranam Professional Services</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --primary: #2563eb;
      --deep-blue: #1d4ed8;
      --canvas: #ffffff;
      --secondary-bg: #f8fafc;
      --card-border: #e2e8f0;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --radius: 12px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--secondary-bg); color: var(--text-main); line-height: 1.5; }
    .header { background: white; border-bottom: 1px solid var(--card-border); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; }
    .logo-badge { font-weight: 700; font-size: 1.25rem; color: var(--primary); display: flex; align-items: center; gap: 0.5rem; }
    .logo-badge span { background: var(--primary); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.875rem; }
    .container { max-width: 1280px; margin: 2rem auto; padding: 0 1.5rem; }
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.25rem; margin-bottom: 2rem; }
    .metric-card { background: white; padding: 1.25rem; border-radius: var(--radius); border: 1px solid var(--card-border); }
    .metric-val { font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }
    .tabs { display: flex; gap: 1rem; border-bottom: 1px solid var(--card-border); margin-bottom: 1.5rem; }
    .tab { padding: 0.75rem 1rem; cursor: pointer; font-weight: 600; color: var(--text-muted); border-bottom: 2px solid transparent; }
    .tab.active { color: var(--primary); border-bottom-color: var(--primary); }
    .card { background: white; border-radius: var(--radius); border: 1px solid var(--card-border); overflow: hidden; margin-bottom: 1.5rem; }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { background: var(--secondary-bg); padding: 0.875rem 1.25rem; font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--card-border); }
    td { padding: 1rem 1.25rem; border-bottom: 1px solid var(--card-border); font-size: 0.875rem; }
    .badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; background: #eff6ff; color: var(--primary); }
    .badge-paid { background: #ecfdf5; color: #059669; }
    .btn { background: var(--primary); color: white; border: none; padding: 0.5rem 1rem; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 0.875rem; }
    .btn-secondary { background: white; color: var(--text-main); border: 1px solid var(--card-border); }
  </style>
</head>
<body>
  <header class="header">
    <div class="logo-badge"><span>HR</span> HR Accounts & Invoicing</div>
    <div style="display: flex; gap: 0.5rem;">
      <button class="btn btn-secondary" onclick="window.location.href='/api/export/csv'">Export CSV</button>
      <button class="btn btn-secondary" onclick="window.location.href='/api/export/json'">Full Backup</button>
      <button class="btn" onclick="openCreateInvoiceModal()">+ New Invoice</button>
    </div>
  </header>

  <div class="container">
    <div class="metrics-grid">
      <div class="metric-card"><small style="color:var(--text-muted);">Total Invoiced</small><div class="metric-val" id="m-inv">$0.00</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Collected Revenue</small><div class="metric-val" id="m-paid" style="color:#059669;">$0.00</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Outstanding Receivables</small><div class="metric-val" id="m-rec" style="color:#d97706;">$0.00</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Total Expenses</small><div class="metric-val" id="m-exp" style="color:#e11d48;">$0.00</div></div>
    </div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('invoices')">Invoices & Quotes</div>
      <div class="tab" onclick="switchTab('expenses')">Expenses & Costs</div>
      <div class="tab" onclick="switchTab('clients')">Client Directory</div>
    </div>

    <div id="tab-invoices" class="card">
      <table>
        <thead>
          <tr>
            <th>Number</th>
            <th>Client</th>
            <th>Type</th>
            <th>Due Date</th>
            <th>Total</th>
            <th>Paid</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="invoices-tbody">
          <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Loading invoices...</td></tr>
        </tbody>
      </table>
    </div>

    <div id="tab-expenses" class="card" style="display: none;">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Vendor</th>
            <th>Category</th>
            <th>Notes</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody id="expenses-tbody">
          <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Loading expenses...</td></tr>
        </tbody>
      </table>
    </div>

    <div id="tab-clients" class="card" style="display: none;">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Company</th>
            <th>Email</th>
            <th>Currency</th>
          </tr>
        </thead>
        <tbody id="clients-tbody">
          <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Loading clients...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    async function loadData() {
      const statsRes = await fetch('/api/stats');
      const stats = await statsRes.json();
      document.getElementById('m-inv').innerText = '$' + Number(stats.total_invoiced).toLocaleString();
      document.getElementById('m-paid').innerText = '$' + Number(stats.total_paid).toLocaleString();
      document.getElementById('m-rec').innerText = '$' + Number(stats.total_receivables).toLocaleString();
      document.getElementById('m-exp').innerText = '$' + Number(stats.total_expenses).toLocaleString();

      const invRes = await fetch('/api/invoices');
      const invoices = await invRes.json();
      const tbody = document.getElementById('invoices-tbody');
      if (invoices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No invoices found.</td></tr>';
      } else {
        tbody.innerHTML = invoices.map(i => `
          <tr>
            <td><strong>${i.invoice_number}</strong></td>
            <td><strong>${i.client_name}</strong><br><small style="color:var(--text-muted);">${i.client_company || ''}</small></td>
            <td>${i.type}</td>
            <td>${i.due_date}</td>
            <td><strong>${i.currency} ${Number(i.total).toFixed(2)}</strong></td>
            <td style="color:#059669;">${i.currency} ${Number(i.amount_paid).toFixed(2)}</td>
            <td><span class="badge ${i.status==='Paid'?'badge-paid':''}">${i.status}</span></td>
            <td>
              <a href="/api/invoices/${i.id}/render" target="_blank" class="btn btn-secondary" style="padding: 0.25rem 0.5rem; text-decoration: none; font-size: 0.75rem;">View PDF</a>
            </td>
          </tr>
        `).join('');
      }

      const expRes = await fetch('/api/expenses');
      const expenses = await expRes.json();
      const expBody = document.getElementById('expenses-tbody');
      expBody.innerHTML = expenses.map(e => `
        <tr>
          <td>${e.expense_date}</td>
          <td><strong>${e.vendor}</strong></td>
          <td><span class="badge">${e.category}</span></td>
          <td>${e.notes || '—'}</td>
          <td style="font-weight:700; color:#e11d48;">${e.currency} ${Number(e.amount).toFixed(2)}</td>
        </tr>
      `).join('');

      const cliRes = await fetch('/api/clients');
      const clients = await cliRes.json();
      const cliBody = document.getElementById('clients-tbody');
      cliBody.innerHTML = clients.map(c => `
        <tr>
          <td><strong>${c.name}</strong></td>
          <td>${c.company || '—'}</td>
          <td>${c.email}</td>
          <td>${c.currency}</td>
        </tr>
      `).join('');
    }

    function switchTab(tab) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById('tab-invoices').style.display = tab === 'invoices' ? 'block' : 'none';
      document.getElementById('tab-expenses').style.display = tab === 'expenses' ? 'block' : 'none';
      document.getElementById('tab-clients').style.display = tab === 'clients' ? 'block' : 'none';
    }

    async function openCreateInvoiceModal() {
      const desc = prompt("Enter service / line item description:", "Business Systems Consulting & Deployment");
      if (!desc) return;
      const amount = prompt("Enter line item amount ($):", "2500.00");
      if (!amount) return;

      const clientsRes = await fetch('/api/clients');
      const clients = await clientsRes.json();
      if (clients.length === 0) {
        alert("Please create a client first via demo seeder.");
        return;
      }

      const payload = {
        client_id: clients[0].id,
        type: "Invoice",
        issue_date: new Date().toISOString().split('T')[0],
        due_date: new Date(Date.now() + 14*86400000).toISOString().split('T')[0],
        currency: "USD",
        items: [{ description: desc, quantity: 1, unit_price: parseFloat(amount) }],
        tax_rate: 0.0,
        discount: 0.0,
        notes: "Thank you for your business!"
      };

      const res = await fetch('/api/invoices', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        alert("🎉 Invoice successfully created!");
        loadData();
      }
    }

    window.onload = loadData;
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return UI_HTML
