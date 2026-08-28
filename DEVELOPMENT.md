# HR Accounts — V1 Development Guide

## Local Setup
```bash
cd products/hemanth-ranam-accounts
pip install fastapi uvicorn pydantic httpx pytest
python3 -m uvicorn src.app:app --host 127.0.0.1 --port 8004 --reload
```

## Run E2E Tests
```bash
python3 scripts/e2e_qa_test.py
```
Expected:
```
✅ [1/7] Health & Institutional Branding verified.
✅ [2/7] Client debtor profile created.
✅ [3/7] Invoice issued (INV-2026-78021, Total: £7,800.00).
✅ [4/7] Partial remittance recorded (Paid: £2,800.00, Remaining: £5,000.00).
✅ [5/7] Final invoice settlement confirmed (Status: Paid).
✅ [6/7] Institutional printable HTML/PDF invoice verified.
✅ [7/7] CSV and JSON financial ledger exports verified.
🎉 ALL REAL-WORLD HR ACCOUNTS QA TESTS PASSED WITH 100% SUCCESS!
```
