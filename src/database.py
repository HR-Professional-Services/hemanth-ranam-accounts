import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("ACCOUNTS_DB_PATH", "accounts.db")

def init_db(db_path: str = DB_PATH):
    """Initializes SQLite database with WAL mode and Accounts tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    cursor = conn.cursor()

    # Clients / Customers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        company TEXT,
        address TEXT,
        currency TEXT DEFAULT 'USD',
        tax_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Invoices & Quotes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT,
        type TEXT DEFAULT 'Invoice', -- Invoice, Quote
        issue_date DATE NOT NULL,
        due_date DATE NOT NULL,
        currency TEXT DEFAULT 'USD',
        subtotal REAL NOT NULL,
        tax_rate REAL DEFAULT 0.0,
        tax_amount REAL DEFAULT 0.0,
        discount REAL DEFAULT 0.0,
        total REAL NOT NULL,
        amount_paid REAL DEFAULT 0.0,
        status TEXT DEFAULT 'Draft', -- Draft, Sent, Paid, Overdue, Cancelled
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Invoice Line Items
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

    # Expenses
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL, -- Software, Hosting, Contractors, Office, Travel
        vendor TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        expense_date DATE NOT NULL,
        notes TEXT,
        receipt_ref TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Payments Recorded
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
        amount REAL NOT NULL,
        payment_date DATE NOT NULL,
        payment_method TEXT DEFAULT 'Bank Transfer', -- Bank Transfer, Card, Cash, Stripe
        reference TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

@contextmanager
def get_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()
