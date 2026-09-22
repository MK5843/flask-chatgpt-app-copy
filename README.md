# Flask AI Chat Application (Shareable Copy)

A full-stack AI chat application built with Flask, featuring dual-AI failover (OpenAI + Google Gemini), encrypted message storage, real user authentication, a ChatGPT-style interface, structured error logging, an automated CI/CD pipeline, a scheduled ETL job, and a Power BI analytics dashboard.

This is a **shareable copy** of the original project — no real credentials, API keys, or passwords are included. You'll set up your own in a few minutes using the guide below.

---

## Get Started

**👉 [SETUP_GUIDE.html](./docs/new_user_guide_setup_documentation.html)** — start here. It walks through everything from opening this folder for the first time to running the app on your own computer, in plain language, no experience assumed.

Two more references, if you want to go deeper:

| Guide | Use this if you want to... |
|---|---|
| **[TECHNICAL_DOC.md](./docs/new_technical_documentation.md)** | A concise technical reference — architecture diagram, database schema, tech stack, and design decisions |

## What's Included

- The full application code
- `.env.example` — a template showing which secret values you'll need to provide yourself
- Sample database exports (structure + some data) so you can see the app working right away, without needing to build up test data manually
- Both Power BI dashboard files — their saved credentials have been cleared, so you'll connect them to your own database
- A working CI/CD pipeline (GitHub Actions) and a scheduled ETL job — functional out of the box for testing, optional to fully configure for your own live deployment

## What's Not Included (on purpose)

- Any real API keys, passwords, or database credentials
- The original `venv/` — you'll create your own from `requirements.txt`

## Quick Start

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
python app.py
```

This assumes you've already set up a local PostgreSQL database and created your own `.env` file — see **[SETUP_GUIDE.html](./SETUP_GUIDE.html)** for the full walkthrough, including where to get free API keys.

## Going Live (Optional)

Once you have it running locally, `SETUP_GUIDE.html` also covers putting your own copy on the internet — using Neon for a free cloud database and Render for free hosting, the same way the original was deployed.

## Tech Stack

Python, Flask, PostgreSQL, SQLAlchemy, OpenAI API, Google Gemini API, Flask-Login, Authlib (Google OAuth), `cryptography` (Fernet encryption), Power BI Desktop, GitHub Actions.