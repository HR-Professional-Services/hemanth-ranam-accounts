# HR Accounts — V1 API Specification

## Overview
- **Service Name**: HR Accounts
- **Port**: 8004
- **Protocol**: HTTP/1.1 REST JSON + Server-Rendered SPA
- **Currency**: GBP (£) — ISO 4217 `GBP`
- **Status**: 🔒 V1 Locked

---

## Endpoint Reference

### 1. System & Health
#### `GET /api/health`
- **Response**: `200 OK` (`{"status": "healthy", "service": "HR Accounts", "version": "2.0.0"}`)

#### `GET /api/branding`
- **Response**: `200 OK` (Brand tokens, currency symbol, VAT rate)

---

### 2. Dashboard & Financial KPIs
#### `GET /api/dashboard/stats`
- **Description**: Aggregates live financial KPIs: total invoiced, total collected, outstanding balance, net cash margin, and aged receivables breakdown.
- **Response**: `200 OK`
```json
{
  "total_invoiced_gbp": 45300.0,
  "total_paid_gbp": 32100.0,
  "total_outstanding_gbp": 13200.0,
  "net_cash_margin_gbp": 28750.0,
  "overdue_count": 2,
  "recent_invoices": []
}
```

---

### 3. Clients & Debtors
#### `GET /api/clients`
- **Description**: Lists all client debtors with total billed, total paid, and outstanding balance per client.
- **Response**: `200 OK`

#### `POST /api/clients`
- **Request Body**: `{"name": "Brightline Plumbing Ltd", "email": "...", "phone": "...", "address": "..."}`
- **Response**: `201 Created` (`{"id": 4, "name": "Brightline Plumbing Ltd"}`)

---

### 4. Invoices
#### `GET /api/invoices`
- **Parameters**: `status` (optional: `Draft`, `Sent`, `Partial`, `Paid`, `Overdue`, `Cancelled`), `client_id`, `search`
- **Response**: `200 OK`

#### `POST /api/invoices`
- **Description**: Issues a new invoice. Auto-generates sequential invoice number (`INV-2026-XXXXX`). Calculates VAT at 20% from subtotal.
- **Request Body**:
```json
{
  "client_id": 1,
  "line_items": [
    {"description": "Cloud Architecture Consulting", "quantity": 5, "unit_price_gbp": 1300.0}
  ],
  "due_date": "2026-09-28",
  "notes": "Payment due within 30 days"
}
```
- **Response**: `201 Created` (`{"id": 4, "invoice_number": "INV-2026-78021", "total_gbp": 7800.0, "status": "Sent"}`)

#### `GET /api/invoices/{id}/pdf`
- **Description**: Returns an institutional printable HTML invoice with line items, tax summary, and bank payment details (Barclays Corporate UK).
- **Response**: `200 OK` (`text/html`)

---

### 5. Payments & Remittances
#### `POST /api/invoices/{id}/payments`
- **Description**: Records a partial or full payment against an invoice. Recalculates `amount_paid` and `amount_outstanding`. Transitions invoice status to `Partial` or `Paid`.
- **Request Body**: `{"amount_gbp": 2800.0, "method": "BACS", "reference": "TRF-28082026"}`
- **Response**: `200 OK` (`{"status": "Partial", "amount_outstanding": 5000.0}`)

---

### 6. Quotes / Estimates
#### `GET /api/quotes`
- **Response**: `200 OK`

#### `POST /api/quotes`
- **Description**: Creates an unsigned quote with line items. Auto-generates quote number (`QUO-2026-XXXXX`).
- **Response**: `201 Created`

#### `POST /api/quotes/{id}/convert`
- **Description**: One-click conversion: accepts a quote, generates a live invoice from it, and marks the quote as `Converted`.
- **Response**: `201 Created` (`{"invoice_id": 7, "invoice_number": "INV-2026-78027", "converted_from_quote": "QUO-2026-12345"}`)

---

### 7. Expenses
#### `GET /api/expenses`
- **Response**: `200 OK`

#### `POST /api/expenses`
- **Request Body**: `{"description": "Office Supplies", "amount_gbp": 145.50, "category": "Office", "expense_date": "2026-08-01"}`
- **Response**: `201 Created`

#### `DELETE /api/expenses/{id}`
- **Response**: `200 OK`

---

### 8. Reporting
#### `GET /api/reports/pl`
- **Description**: Returns gross revenue (total invoiced), total expenses (outflow), and net profit margin for the current financial year.
- **Response**: `200 OK` (`{"gross_revenue": 45300.0, "total_expenses": 4200.0, "net_margin": 41100.0}`)

---

### 9. Data Sovereignty
#### `GET /api/export/csv`
- **Response**: `200 OK` (`text/csv`)

#### `GET /api/export/json`
- **Response**: `200 OK` (`application/json`)
