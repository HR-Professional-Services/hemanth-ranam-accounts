# HR Accounts — V1 Security Policy

## Implemented Security Controls

### SQL Injection Defense
All queries use parameterized `?` placeholders. No f-string or string concatenation into SQL.

### Password Hashing
Admin credentials stored as salted SHA-256 hashes. Plaintext passwords never persisted.

### Input Validation
Pydantic schemas enforce positive monetary amounts, valid date formats, non-empty client names. `422` returned on invalid payloads.

### Invoice Number Integrity
Invoice and quote numbers carry `UNIQUE` DB constraints. Duplicate submissions are rejected at the database layer with `409 Conflict`.

### Financial Data Isolation
Each client's financial data is partitioned by `client_id` foreign key. Cross-client data leakage is prevented by parameterized queries.

---

## Future Security Roadmap (V2)
- Role-based access control: `Accounts Admin` vs `Read-Only Viewer`
- Audit log table for all invoice mutations (who, what, when)
- Invoice approval workflow for values above configurable thresholds
- HMRC-compliant VAT record retention policy enforcement
