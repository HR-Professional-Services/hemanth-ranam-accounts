# HR Accounts — V1 Test Verification Suite

## Test Summary
- **Suite Script**: `scripts/e2e_qa_test.py`
- **Total Scenarios**: 7 | **Pass Rate**: 100% (7/7) | **Status**: 🔒 Verified Baseline

| Step | Test Objective | Assertion | Result |
| :--- | :--- | :--- | :--- |
| **01** | Health & Institutional Branding | `status == "healthy"` | ✅ PASSED |
| **02** | Client Debtor Registration | `status_code == 201`, name `Brightline Plumbing Ltd` | ✅ PASSED |
| **03** | Invoice Issuance | `total_gbp == 7800.0`, VAT calculated, number generated | ✅ PASSED |
| **04** | Partial Remittance | `status == "Partial"`, `outstanding == 5000.0` | ✅ PASSED |
| **05** | Full Settlement | `status == "Paid"`, `balance == 0.0` | ✅ PASSED |
| **06** | Printable HTML Invoice | `200 OK`, contains institutional bank details | ✅ PASSED |
| **07** | Data Sovereignty Exports | CSV and JSON `200 OK` | ✅ PASSED |
