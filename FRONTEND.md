# HR Accounts — V1 Frontend Architecture

## Design System & Theme
- **Theme**: 100% Light Mode Only (`#F8FAFC` canvas, `#FFFFFF` cards)
- **Primary Color**: `#2563EB`, Hover: `#1D4ED8`
- **Typography**: Inter, System UI; JetBrains Mono for monetary values
- **Micro-Interactions**: 150ms transitions; badge colour-coding for invoice status

## SPA Views (6 Active)
1. **`view-dashboard`**: Live financial KPIs, aged receivables, recent invoice table
2. **`view-invoices`**: Invoice ledger with status filter, Issue New Invoice modal, Pay modal, PDF print action
3. **`view-quotes`**: Quote list with Convert to Invoice button, Create Quote modal
4. **`view-clients`**: Client debtor ledger with outstanding balance per client
5. **`view-expenses`**: Expense list with category tags, Record Expense modal, Delete action
6. **`view-reports`**: P&L summary, gross revenue, outflows, net margin; CSV/JSON export buttons

## Modals (Placed outside `<script>`)
- `#modal-invoice`: Issue new invoice with dynamic line item rows; auto-calculates VAT
- `#modal-payment`: Record partial or full remittance; updates outstanding balance live
- `#modal-client`: Add client account to debtor ledger
- `#modal-expense`: Record operating expense with category selector

## Invoice Status Badge Colours
| Status | Background | Text |
| :--- | :--- | :--- |
| `Draft` | `#F1F5F9` | `#475569` |
| `Sent` | `#DBEAFE` | `#1D4ED8` |
| `Partial` | `#FEF3C7` | `#D97706` |
| `Paid` | `#DCFCE7` | `#16A34A` |
| `Overdue` | `#FEE2E2` | `#DC2626` |
| `Cancelled` | `#F1F5F9` | `#64748B` |

## PDF Invoice Generation
- Triggered via `GET /api/invoices/{id}/pdf`
- Returns institutional HTML with line items table, VAT calculation, total, and Barclays bank details
- Browser `window.print()` with CSS `@media print` suppresses navigation chrome
