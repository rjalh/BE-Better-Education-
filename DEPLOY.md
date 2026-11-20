# Deployment instructions — Better Education pilot

## Local pilot

Inside the extracted project, `docker compose up --build`, then open `http://localhost:8000`. For simple Python setup, see README.

## Hosted pilot

Choose a host that runs Docker containers and provides persistent storage. Configure these server environment variables:

- `BE_DEMO_MODE=0`
- `SESSION_SECRET=<at least 48 random characters>`
- `ADMIN_EMAIL=<your admin email>`
- `ADMIN_PASSWORD=<strong unique initial password>`
- `COOKIE_SECURE=1`
- `DATABASE_URL=postgresql+psycopg://<user>:<password>@<database-host>:5432/<database>`
- `OPENAI_API_KEY` (optional; only for generative tutor)

Create a PostgreSQL database and ensure it has routine backups. Set the service's start command to `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` (if the platform provides its port via `$PORT`, use that). Configure HTTPS at the host's reverse proxy. Verify the `/health` endpoint and then login with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

Use the admin panel to create teachers, classes, course assignments, and students. Then teachers can publish content and quizzes.

**Security note:** The included app is a fully running pilot, not an audited child-data processing system. Before using actual minors' personal data at public scale, address the production gaps listed in README and TEST_REPORT, especially verified guardian consent, incident handling, user lifecycle, and security review.

## Known infrastructure constraints

- The basic `compose.yaml` uses a single SQLite volume for a small local pilot. It does **not** automatically configure a PostgreSQL service.
- This artifact does **not** create a public domain, provision hosting, or activate a paid AI account.
- Multi-instance/multi-worker operation should be paired with shared rate limiting and session/revocation infrastructure.
- Database schema currently uses `create_all()`; adopt managed schema migrations before ongoing production upgrades.
