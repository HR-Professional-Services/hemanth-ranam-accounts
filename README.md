# HR Accounts — Hemanth Ranam Professional Services

[![CI](https://github.com/HR-Professional-Services/hemanth-ranam-accounts/actions/workflows/ci.yml/badge.svg)](https://github.com/HR-Professional-Services/hemanth-ranam-accounts/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE-COMPLIANCE.md)
[![Zero Monthly Cost](https://img.shields.io/badge/Hosting-Zero--Cost%20Tier-success.svg)](DEPLOYMENT.md)

> **"Small-business invoicing, quotes, multi-currency accounting, expense tracking, and PDF generation with zero mandatory SaaS subscriptions."**

---

## 🌟 Executive Overview
**HR Accounts** is an institutional, white-labelled invoicing, quotes, and financial records management platform engineered by **Hemanth Ranam Professional Services**. Built for freelancers, digital agencies, consultancies, contractors, and service businesses, it eliminates costly monthly recurring software fees ($30–$80/mo on QuickBooks, FreshBooks, or Xero) while providing 100% data sovereignty and printable PDF invoicing.

---

## 💼 Core Business Features
* **Invoicing & Quotation Engine**: Issue professional multi-item quotes and invoices with configurable tax rates and discounts.
* **Multi-Currency Global Support**: Seamlessly bill clients in USD, GBP, EUR, CAD, AUD, and INR.
* **Instant PDF & Printable Rendering**: Institutional invoice generation with bank details and custom payment terms.
* **Payment Tracking & Receivables**: Record full and partial payments, track outstanding balances, and update statuses (`Sent`, `Partially Paid`, `Paid`, `Overdue`).
* **Expense & Overhead Logging**: Categorize operating expenses (Hosting, Software, Contractors, Office, Travel) and monitor net margins.
* **100% Client Data Sovereignty**: 1-click CSV & JSON complete accounting database export.

---

## 🎨 White-Label Branding
Configure brand identity, legal entity details, banking instructions, and payment terms in `src/branding.json`.

---

## 🚀 Quickstart Installation
```bash
# 1. Clone repository
git clone https://github.com/HR-Professional-Services/hemanth-ranam-accounts.git
cd hemanth-ranam-accounts

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed demo accounts data
python scripts/seed_demo_data.py

# 4. Start local server
uvicorn src.app:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) for the financial dashboard.

---

## 🐳 Docker Deployment
```bash
docker build -t hemanth-ranam-accounts .
docker run -d -p 8000:8000 -v $(pwd)/data:/app/data --name hr-accounts hemanth-ranam-accounts
```

---

## 📦 Client Handover Suite
* [CLIENT-ONBOARDING.md](client/CLIENT-ONBOARDING.md)
* [SETUP-CHECKLIST.md](client/SETUP-CHECKLIST.md)
* [HANDOVER.md](client/HANDOVER.md)
* [ADMIN-GUIDE.md](client/ADMIN-GUIDE.md)
* [USER-GUIDE.md](client/USER-GUIDE.md)
* [TRAINING.md](client/TRAINING.md)
* [SUPPORT.md](client/SUPPORT.md)

---

## 🏛️ Commercial Services
**Hemanth Ranam Professional Services**  
* **Live Hub**: [https://app.hemanth-ranam.workers.dev/](https://app.hemanth-ranam.workers.dev/)  
* **Direct Inquiry**: [hemanth.ranam@gmail.com](mailto:hemanth.ranam@gmail.com) | WhatsApp: `+91 7675815245`
