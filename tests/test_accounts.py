import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from src.app import app
from src.database import init_db

@pytest.fixture
def client():
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    test_db.close()
    os.environ["ACCOUNTS_DB_PATH"] = test_db.name
    init_db(test_db.name)
    with TestClient(app) as c:
        yield c
    if os.path.exists(test_db.name):
        try:
            os.remove(test_db.name)
        except Exception:
            pass

def test_health_and_branding(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["service"] == "HR Accounts"

    b_res = client.get("/api/branding")
    assert b_res.status_code == 200
    assert b_res.json()["product_name"] == "HR Accounts"

def test_invoice_creation_and_payment(client):
    # 1. Create Client
    c_res = client.post("/api/clients", json={
        "name": "David Miller",
        "email": "david.m@test.com",
        "company": "Miller Logistics UK",
        "address": "London, UK"
    })
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]

    # 2. Create Invoice
    inv_res = client.post("/api/invoices", json={
        "client_id": client_id,
        "items": [
            {"description": "Cloud Deployment", "quantity": 1.0, "unit_price": 2000.0}
        ]
    })
    assert inv_res.status_code == 201
    inv_id = inv_res.json()["id"]
    assert inv_res.json()["total"] == 2400.0 # 2000 + 20% VAT

    # 3. Record Partial Payment
    p_res = client.post("/api/payments", json={
        "invoice_id": inv_id,
        "amount": 1000.0,
        "payment_method": "Bank Transfer"
    })
    assert p_res.status_code == 201
    assert p_res.json()["status"] == "Partially Paid"
    assert p_res.json()["balance_due"] == 1400.0

    # 4. Render Printable Invoice
    render_res = client.get(f"/api/invoices/{inv_id}/render")
    assert render_res.status_code == 200
    assert "HR PROFESSIONAL SERVICES" in render_res.text
