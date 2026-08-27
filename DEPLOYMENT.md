# DEPLOYMENT GUIDE — HR ACCOUNTS

**System**: HR Accounts (Product 04)  
**Provider**: Hemanth Ranam Professional Services  
**Source Hub**: [https://app.hemanth-ranam.workers.dev/](https://app.hemanth-ranam.workers.dev/)

---

## 1. Hosting Classifications
* **Tier A (Recommended)**: Cloudflare Pages + Serverless SQLite WAL ($0.00/mo).
* **Tier B**: Micro Container / Docker on Fly.io / Render ($0.00 - $5.00/mo).
* **Tier C**: Dedicated Ubuntu VPS with PostgreSQL 16 ($10.00/mo).

---

## 2. Docker Deployment
```bash
git clone https://github.com/HR-Professional-Services/hemanth-ranam-accounts.git
cd hemanth-ranam-accounts
docker compose up -d --build
```
