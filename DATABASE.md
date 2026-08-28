# HR Accounts — V1 Database Schema

## Storage Architecture
- **Engine**: SQLite 3, WAL journal mode
- **Default Database File**: `accounts.db`
- **Foreign Keys**: Enforced via `PRAGMA foreign_keys = ON;`

---

## Table DDL

### 1. `clients` (Debtor Registry)
```sql
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. `invoices` (Billing Documents)
```sql
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,       -- Format: INV-YYYY-NNNNN
    client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT,
    issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date DATE NOT NULL,
    status TEXT DEFAULT 'Sent',               -- Draft|Sent|Partial|Paid|Overdue|Cancelled
    subtotal_gbp REAL NOT NULL DEFAULT 0.0,
    vat_amount_gbp REAL NOT NULL DEFAULT 0.0, -- 20% of subtotal
    total_gbp REAL NOT NULL DEFAULT 0.0,      -- subtotal + vat
    amount_paid_gbp REAL NOT NULL DEFAULT 0.0,
    amount_outstanding_gbp REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3. `invoice_line_items` (Line Items)
```sql
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1.0,
    unit_price_gbp REAL NOT NULL,
    line_total_gbp REAL NOT NULL  -- quantity * unit_price_gbp
);
```

### 4. `payments` (Remittance Records)
```sql
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    amount_gbp REAL NOT NULL,
    method TEXT DEFAULT 'BACS',  -- BACS|Cheque|Card|Cash
    reference TEXT,
    payment_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. `quotes` (Unsigned Estimates)
```sql
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_number TEXT UNIQUE NOT NULL,   -- Format: QUO-YYYY-NNNNN
    client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT,
    issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE NOT NULL,
    status TEXT DEFAULT 'Pending',       -- Pending|Accepted|Rejected|Converted
    subtotal_gbp REAL NOT NULL DEFAULT 0.0,
    total_gbp REAL NOT NULL DEFAULT 0.0,
    converted_to_invoice_id INTEGER REFERENCES invoices(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6. `expenses` (Operating Outflows)
```sql
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount_gbp REAL NOT NULL,
    category TEXT DEFAULT 'General',    -- Office|Software|Travel|Professional|General
    expense_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Accounting Logic Reference

### VAT Calculation
```
VAT Amount = Subtotal × 0.20
Total      = Subtotal + VAT Amount
```

### Invoice Status Transitions
```
Draft → Sent → Partial (part payment received) → Paid (full settlement)
             ↘ Overdue (due_date passed, no full payment)
             ↘ Cancelled (voided)
```

### Outstanding Balance
```
amount_outstanding_gbp = total_gbp - amount_paid_gbp
Status = 'Paid' when amount_outstanding_gbp <= 0.0
Status = 'Partial' when 0 < amount_paid_gbp < total_gbp
```

### P&L Calculation
```
Gross Revenue  = SUM(total_gbp) from invoices WHERE status = 'Paid'
Total Expenses = SUM(amount_gbp) from expenses
Net Margin     = Gross Revenue - Total Expenses
```
