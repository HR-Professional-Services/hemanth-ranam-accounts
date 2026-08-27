#!/usr/bin/env python3
"""
HR Accounts — Invoicing, VAT Calculation & Printable PDF Simulation E2E Test
"""

import os
import sys
import tempfile
from pathlib import Path

test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db.close()
os.environ["ACCOUNTS_DB_PATH"] = test_db.name

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient
from src.app import app
from src.database import init_db

def run_accounts_qa():
    print("==================================================")
    print("🧪 REAL-WORLD QA SIMULATION: 04 — HR ACCOUNTS")
    print("==================================================")
    init_db(test_db.name)
    client = TestClient(app)

    # 1. Health & Branding
    health = client.get("/api/health")
    assert health.status_code == 200
    branding = client.get("/api/branding")
    assert branding.status_code == 200
    assert branding.json()["product_name"] == "HR Accounts"
    print("✅ [1/7] Health & Institutional Branding verified.")

    # 2. Client Debtor Profile Creation
    c_res = client.post("/api/clients", json={
        "name": "Julian North",
        "email": "j.north@northstar-consulting.com",
        "company": "Northstar Management Consulting",
        "address": "10 Deansgate, Manchester, UK",
        "currency": "GBP",
        "tax_id": "GB 948 2011 88"
    })
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]
    print(f"✅ [2/7] Client debtor profile created (ID: {client_id}, Northstar Consulting).")

    # 3. Multi-Line Item Invoice Generation
    inv_res = client.post("/api/invoices", json={
        "client_id": client_id,
        "items": [
            {"description": "Custom Architecture Consulting & Engineering", "quantity": 1.0, "unit_price": 5000.00},
            {"description": "Dedicated Cloud Cluster Provisioning", "quantity": 2.0, "unit_price": 750.00}
        ]
    })
    assert inv_res.status_code == 201
    inv_data = inv_res.json()
    assert inv_data["total"] == 7800.00 # (5000 + 1500) * 1.20 = 7800
    print(f"✅ [3/7] Invoice issued (Number: {inv_data['invoice_number']}, Subtotal: £6,500.00, Total: £{inv_data['total']:,.2f}).")

    # 4. Partial Payment Record
    p1_res = client.post("/api/payments", json={
        "invoice_id": inv_data["id"],
        "amount": 2800.00,
        "payment_method": "Bank Transfer",
        "reference": "WIRE-NS-01"
    })
    assert p1_res.status_code == 201
    assert p1_res.json()["status"] == "Partially Paid"
    assert p1_res.json()["balance_due"] == 5000.00
    print(f"✅ [4/7] Partial remittance recorded (Paid: £2,800.00, Remaining Balance: £5,000.00).")

    # 5. Full Settlement Payment
    p2_res = client.post("/api/payments", json={
        "invoice_id": inv_data["id"],
        "amount": 5000.00,
        "payment_method": "Bank Transfer",
        "reference": "WIRE-NS-02"
    })
    assert p2_res.status_code == 201
    assert p2_res.json()["status"] == "Paid"
    assert p2_res.json()["balance_due"] == 0.00
    print("✅ [5/7] Final invoice settlement confirmed (Status: Paid, Balance Due: £0.00).")

    # 6. Institutional Printable Invoice Render
    render_res = client.get(f"/api/invoices/{inv_data['id']}/render")
    assert render_res.status_code == 200
    assert "HR PROFESSIONAL SERVICES" in render_res.text
    print("✅ [6/7] Institutional printable HTML/PDF invoice verified.")

    # 7. CSV & JSON Export
    csv_res = client.get("/api/export/csv")
    assert csv_res.status_code == 200
    json_res = client.get("/api/export/json")
    assert json_res.status_code == 200
    print("✅ [7/7] CSV and JSON financial ledger exports verified.")

    print("\n🎉 ALL REAL-WORLD HR ACCOUNTS QA TESTS PASSED WITH 100% SUCCESS!\n")

    if os.path.exists(test_db.name):
        os.remove(test_db.name)

if __name__ == "__main__":
    run_accounts_qa()
