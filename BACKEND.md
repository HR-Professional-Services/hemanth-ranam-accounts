# HR Accounts — V1 Backend Architecture

## Framework
- **Web Engine**: FastAPI, Python 3.12, Uvicorn ASGI
- **Entrypoint**: `src/app.py`
- **Startup**: `init_db()` on `@app.on_event("startup")` — creates tables, seeds demo clients and invoices

---

## Business Logic Engines

### 1. Invoice Numbering
Auto-incremented sequential format: `INV-YYYY-NNNNN` where `NNNNN` = current year's invoice count + 78000 offset. Guarantees uniqueness via `UNIQUE` constraint on `invoices.invoice_number`.

### 2. Quote-to-Invoice Conversion
`POST /api/quotes/{id}/convert`:
1. Fetch quote and its line items.
2. Create a new invoice with identical line items.
3. Update `quote.status = 'Converted'` and `quote.converted_to_invoice_id`.
4. Return new invoice ID and number.

### 3. Payment & Balance Ledger
On each `POST /api/invoices/{id}/payments`:
1. Insert payment record into `payments`.
2. Recompute `amount_paid_gbp = SUM(payments.amount_gbp)` for the invoice.
3. Recompute `amount_outstanding_gbp = total_gbp - amount_paid_gbp`.
4. Auto-transition status: `outstanding <= 0 → Paid`; `0 < paid < total → Partial`.

### 4. P&L Aggregation
`GET /api/reports/pl` performs two aggregate queries:
- `SELECT SUM(total_gbp) FROM invoices WHERE status='Paid'`
- `SELECT SUM(amount_gbp) FROM expenses`

---

## Validation
- Pydantic schemas: `InvoiceCreate`, `PaymentCreate`, `QuoteCreate`, `ClientCreate`, `ExpenseCreate`
- `422` on missing required fields; `404` on unknown resource IDs; `409` on duplicate invoice numbers
