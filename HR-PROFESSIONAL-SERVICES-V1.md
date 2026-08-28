# HR Accounts — Master V1 Architecture Specification

## Baseline
- **Product**: HR Accounts
- **Repository**: `hemanth-ranam-accounts`
- **Port**: `8004`
- **Version**: `1.0.0` | **Status**: 🔒 FINAL / LOCKED BASELINE

## Purpose
HR Accounts delivers a complete double-entry-ready professional services financial ledger covering invoice lifecycle management, payment tracking, quote-to-invoice conversion, operating expense recording, and P&L reporting in GBP.

## Core Modules
1. **Invoice Engine**: Issue, track, partially pay, and settle invoices with VAT at 20%
2. **Quote Engine**: Create estimates; one-click conversion to live invoices
3. **Payment Ledger**: Multi-remittance tracking with automatic status transitions
4. **Client Debtor Registry**: Lifetime value and outstanding balance per client
5. **Expense Recorder**: Operating cost categories and P&L aggregation
6. **P&L Reporter**: Gross revenue, expenses, and net margin for the financial year
7. **Printable Invoice Generator**: Institutional HTML invoice with Barclays bank details
8. **Data Sovereignty Exporter**: CSV and JSON export streams

## Technology Stack
- **Backend**: FastAPI, Python 3.12, Uvicorn ASGI
- **Database**: SQLite 3 WAL
- **Frontend**: Native HTML5 SPA, Vanilla JS
- **Currency**: GBP (£), VAT 20%
- **Theme**: Pure Light Mode Only

## Architecture Freeze
This repository is locked at V1. No accounting model changes (VAT rate, invoice number format, status enum) without explicit approval and DB migration plan.
