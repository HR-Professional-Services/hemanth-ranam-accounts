import pytest
import os
import tempfile
from fastapi.testclient import TestClient

test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_path = test_db_file.name
os.environ["ACCOUNTS_DB_PATH"] = test_db_path

from src.app import app
from src.database import init_db

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db(test_db_path)
    yield
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

@pytest.fixture
def client():
    return TestClient(app)

def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["service"] == "HR Accounts"

def test_client_and_invoice_creation(client):
    c_res = client.post("/api/clients", json={
        "name": "Global Tech Ventures",
        "email": "billing@globaltech.com",
        "company": "Global Tech Ltd",
        "address": "1 Silicon Way, Cambridge",
        "currency": "USD"
    })
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]

    inv_payload = {
        "client_id": client_id,
        "type": "Invoice",
        "issue_date": "2026-08-27",
        "due_date": "2026-09-10",
        "currency": "USD",
        "tax_rate": 10.0,
        "discount": 100.0,
        "items": [
            {"description": "Workflow Automation Engine Architecture", "quantity": 1, "unit_price": 2000.0},
            {"description": "Telegram Alert Bot Integration", "quantity": 1, "unit_price": 500.0}
        ]
    }
    inv_res = client.post("/api/invoices", json=inv_payload)
    assert inv_res.status_code == 201
    inv_data = inv_res.json()
    assert inv_data["id"] is not None
    # Subtotal: 2500, Tax 10%: 250, Discount: 100 => Total: 2650
    assert inv_data["total"] == 2650.0

def test_payment_recording_and_status_update(client):
    invoices = client.get("/api/invoices").json()
    inv = invoices[0]
    inv_id = inv["id"]

    # Record partial payment
    p_res = client.post(f"/api/invoices/{inv_id}/payments", json={
        "amount": 1000.0,
        "payment_date": "2026-08-27",
        "payment_method": "Bank Transfer",
        "reference": "WIRE-001"
    })
    assert p_res.status_code == 201
    assert p_res.json()["invoice_status"] == "Partially Paid"

    # Record remaining payment
    remaining = inv["total"] - 1000.0
    p_res2 = client.post(f"/api/invoices/{inv_id}/payments", json={
        "amount": remaining,
        "payment_date": "2026-08-27",
        "payment_method": "Bank Transfer",
        "reference": "WIRE-002"
    })
    assert p_res2.status_code == 201
    assert p_res2.json()["invoice_status"] == "Paid"

def test_expense_logging_and_stats(client):
    exp_res = client.post("/api/expenses", json={
        "category": "Hosting",
        "vendor": "Cloudflare",
        "amount": 50.0,
        "currency": "USD",
        "expense_date": "2026-08-27",
        "notes": "Edge Workers Production Plan"
    })
    assert exp_res.status_code == 201

    stats_res = client.get("/api/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_expenses"] >= 50.0
    assert stats["total_paid"] >= 2650.0

def test_invoice_render_html(client):
    invoices = client.get("/api/invoices").json()
    inv_id = invoices[0]["id"]
    render_res = client.get(f"/api/invoices/{inv_id}/render")
    assert render_res.status_code == 200
    assert "INVOICE" in render_res.text
    assert "Global Tech Ventures" in render_res.text
