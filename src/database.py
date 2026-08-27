import sqlite3
import os
import hashlib
from typing import Optional
from contextlib import contextmanager

def hash_password(password: str) -> str:
    salt = "hr_accounts_salt_2026"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def get_db_path():
    return os.getenv("ACCOUNTS_DB_PATH", "accounts.db")

def init_db(db_path: Optional[str] = None):
    """Initializes SQLite database with WAL mode, foreign keys, and comprehensive Accounts tables."""
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    cursor = conn.cursor()

    # 1. Users table (RBAC)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT DEFAULT 'Finance Manager', -- 'Admin', 'Finance Manager', 'Auditor'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Clients / Debtors
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        company TEXT,
        address TEXT,
        currency TEXT DEFAULT 'GBP',
        tax_id TEXT,
        payment_terms_days INTEGER DEFAULT 14,
        total_invoiced REAL DEFAULT 0.0,
        total_paid REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Invoices & Quotes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT,
        type TEXT DEFAULT 'Invoice', -- 'Invoice', 'Quote'
        issue_date DATE NOT NULL,
        due_date DATE NOT NULL,
        currency TEXT DEFAULT 'GBP',
        subtotal REAL NOT NULL,
        tax_rate REAL DEFAULT 0.20,
        tax_amount REAL DEFAULT 0.0,
        discount REAL DEFAULT 0.0,
        total REAL NOT NULL,
        amount_paid REAL DEFAULT 0.0,
        balance_due REAL NOT NULL,
        status TEXT DEFAULT 'Sent', -- 'Draft', 'Sent', 'Partially Paid', 'Paid', 'Overdue', 'Cancelled'
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Invoice Line Items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
        description TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        total REAL NOT NULL
    );
    """)

    # 5. Expenses
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL, -- 'Cloud Infrastructure', 'Software Tools', 'Contractors', 'Office & Facilities', 'Legal & Professional'
        vendor TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'GBP',
        expense_date DATE NOT NULL,
        notes TEXT,
        receipt_ref TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6. Payments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
        amount REAL NOT NULL,
        payment_date DATE NOT NULL,
        payment_method TEXT DEFAULT 'Bank Transfer', -- 'Bank Transfer', 'Card', 'Stripe', 'Cash'
        reference TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed Default Finance Admin if empty
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO users (email, password_hash, full_name, role)
        VALUES (?, ?, ?, ?);
        """, ("finance@demo.local", hash_password("demo123"), "Hemanth Ranam", "Admin"))

    # Seed Realistic Clients if empty
    cursor.execute("SELECT COUNT(*) FROM clients;")
    if cursor.fetchone()[0] == 0:
        clients = [
            ("Florian Steiner", "florian.s@vanguardwealth.ch", "Vanguard Wealth Management SA", "Bahnhofstrasse 45, 8001 Zurich, Switzerland", "GBP", "CHE-112.483.921 TVA", 14, 17500.0, 10000.0),
            ("Gareth Hopkins", "gareth@cardifffitness.wales", "Cardiff Fitness & Wellness Ltd", "88 Queen St, Cardiff, CF10 2GR, UK", "GBP", "GB 392 4819 02", 30, 6500.0, 6500.0),
            ("Dr. Emily Vance", "emily.vance@greenleafdental.co.uk", "Green Leaf Dental Care Ltd", "14 Harley St, London, W1G 9PQ, UK", "GBP", "GB 201 9844 11", 14, 4800.0, 0.0)
        ]
        cursor.executemany("""
        INSERT INTO clients (name, email, company, address, currency, tax_id, payment_terms_days, total_invoiced, total_paid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, clients)

        # Seed Invoices
        invoices = [
            ("INV-2026-001", 1, "Invoice", "2026-08-01", "2026-08-15", "GBP", 8333.33, 0.20, 1666.67, 0.0, 10000.00, 10000.00, 0.0, "Paid", "Full custom ERP & financial module delivery retainer"),
            ("INV-2026-002", 1, "Invoice", "2026-08-20", "2026-09-03", "GBP", 6250.00, 0.20, 1250.00, 0.0, 7500.00, 2500.00, 5000.00, "Partially Paid", "Multi-tenant cloud architecture phase 2"),
            ("INV-2026-003", 2, "Invoice", "2026-08-10", "2026-08-24", "GBP", 5416.67, 0.20, 1083.33, 0.0, 6500.00, 6500.00, 0.0, "Paid", "Check-in POS & booking kiosk configuration"),
            ("INV-2026-004", 3, "Invoice", "2026-08-25", "2026-09-08", "GBP", 4000.00, 0.20, 800.00, 0.0, 4800.00, 0.0, 4800.00, "Sent", "Multi-branch appointment scheduling setup")
        ]
        cursor.executemany("""
        INSERT INTO invoices (invoice_number, client_id, type, issue_date, due_date, currency, subtotal, tax_rate, tax_amount, discount, total, amount_paid, balance_due, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, invoices)

        # Seed Line Items
        line_items = [
            (1, "Enterprise ERP Control Plane Architecture", 1.0, 5000.00, 5000.00),
            (1, "Database Partitioning & Backup Automation", 1.0, 3333.33, 3333.33),
            (2, "Dedicated Multi-Tenant Staging Server Setup", 1.0, 6250.00, 6250.00),
            (3, "POS Hardware Terminal & Barcode Bridge Integration", 1.0, 5416.67, 5416.67),
            (4, "Online Appointment Scheduling Engine & Staff Training", 1.0, 4000.00, 4000.00)
        ]
        cursor.executemany("""
        INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
        VALUES (?, ?, ?, ?, ?);
        """, line_items)

        # Seed Payments
        payments = [
            (1, 10000.00, "2026-08-14", "Bank Transfer", "WIRE-CH-84920"),
            (2, 2500.00, "2026-08-22", "Bank Transfer", "WIRE-CH-99124"),
            (3, 6500.00, "2026-08-20", "Stripe", "ch_3Pz981023910")
        ]
        cursor.executemany("""
        INSERT INTO payments (invoice_id, amount, payment_date, payment_method, reference)
        VALUES (?, ?, ?, ?, ?);
        """, payments)

        # Seed Operating Expenses
        expenses = [
            ("Cloud Infrastructure", "Hetzner Dedicated Server", 85.00, "GBP", "2026-08-01", "Production cluster hosting", "HET-94821"),
            ("Software Tools", "Cloudflare Business Gateway", 40.00, "GBP", "2026-08-05", "DDoS mitigation & DNS proxy", "CF-20199"),
            ("Legal & Professional", "UK Companies House Annual Return", 34.00, "GBP", "2026-08-12", "Filing compliance", "CH-2026-88")
        ]
        cursor.executemany("""
        INSERT INTO expenses (category, vendor, amount, currency, expense_date, notes, receipt_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, expenses)

    conn.commit()
    conn.close()

@contextmanager
def get_db(db_path: Optional[str] = None):
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()
