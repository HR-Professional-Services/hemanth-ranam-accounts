import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.database import get_db, init_db

def seed():
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM payments")
        cursor.execute("DELETE FROM invoice_items")
        cursor.execute("DELETE FROM invoices")
        cursor.execute("DELETE FROM expenses")
        cursor.execute("DELETE FROM clients")

        # Clients
        clients = [
            ("Apex Logistics UK", "billing@apexlogistics.co.uk", "Apex Logistics Ltd", "100 Bishopsgate, London EC2N 4AG", "GBP", "GB998877665"),
            ("Aura Aesthetics Clinic", "accounts@auraclinic.co.uk", "Aura Clinic Global", "45 King St, Manchester M2 7AT", "GBP", "GB112233445"),
            ("Vortex Digital Agency", "finance@vortexmedia.io", "Vortex Digital Ltd", "Victoria St, Bristol BS1 6AA", "USD", "US1234567")
        ]
        c_ids = []
        for c in clients:
            cursor.execute("""
            INSERT INTO clients (name, email, company, address, currency, tax_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """, c)
            c_ids.append(cursor.lastrowid)

        # Invoices
        today = datetime.now().strftime("%Y-%m-%d")
        due = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

        invoices_data = [
            ("INV-2026-001", c_ids[0], "Invoice", today, due, "GBP", 4500.0, 20.0, 900.0, 0.0, 5400.0, 5400.0, "Paid", "Enterprise ERP deployment milestone 1."),
            ("INV-2026-002", c_ids[1], "Invoice", today, due, "GBP", 2200.0, 20.0, 440.0, 0.0, 2640.0, 0.0, "Sent", "Aesthetics Clinic CRM & 24/7 Booking integration."),
            ("QUO-2026-001", c_ids[2], "Quote", today, due, "USD", 3500.0, 0.0, 0.0, 0.0, 3500.0, 0.0, "Sent", "Algorithmic webhook ingestion engine quote.")
        ]

        for inv in invoices_data:
            cursor.execute("""
            INSERT INTO invoices (invoice_number, client_id, type, issue_date, due_date, currency, subtotal, tax_rate, tax_amount, discount, total, amount_paid, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, inv)
            inv_id = cursor.lastrowid

            cursor.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (?, ?, 1, ?, ?)
            """, (inv_id, inv[13], inv[6], inv[6]))

            if inv[12] == "Paid":
                cursor.execute("""
                INSERT INTO payments (invoice_id, amount, payment_date, payment_method, reference)
                VALUES (?, ?, ?, 'Bank Transfer', 'BACS-REF-9921')
                """, (inv_id, inv[10], today))

        # Expenses
        expenses = [
            ("Hosting", "Cloudflare Inc", 20.00, "USD", today, "Workers Paid Plan & Domain Registration"),
            ("Software", "GitHub Enterprise", 21.00, "USD", today, "Organization CI/CD & Team Seats"),
            ("Office", "Workspace London", 350.00, "GBP", today, "Monthly Dedicated Desk Facility")
        ]
        for exp in expenses:
            cursor.execute("""
            INSERT INTO expenses (category, vendor, amount, currency, expense_date, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """, exp)

        conn.commit()
    print("✅ HR Accounts demo dataset seeded successfully!")

if __name__ == "__main__":
    seed()
