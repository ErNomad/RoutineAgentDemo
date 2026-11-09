# Routine Agent Playground

A small web-based demonstration of the three-agent routine workflow. Choose **Good morning** or **Good night** and watch messages travel between the three agents. After starting a timer, Agent 3 confirms it to Agent 2, which sends a greeting back to Agent 1. The page switches between day and night themes, keeps separate elapsed-time clocks, and charts recorded wake and sleep times by day.

## Run locally

Use Python 3.9 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python web.py
```

Open <http://127.0.0.1:8000>. Set `HOST` and `PORT` environment variables to change the bind address and port.

The original console demo remains available with `python run.py`.

## Deployment

`web.py` serves the Flask application with Waitress, a production WSGI server; it does not use Flask's development server. Visitors are assigned an anonymous, signed browser session, and their timers, daily history, and recent events are stored separately in SQLite. The default database is `instance/routine-agent.sqlite3`; set `DATABASE_PATH` to choose another location.

For a public deployment:

- Set `SECRET_KEY` to a long, random value and keep it stable across restarts and deployments. For example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"` and configure it as a secret environment variable. If this key changes, existing browser sessions cannot reconnect to their saved routines.
- Use a persistent disk/volume and point `DATABASE_PATH` to it. For example, if the hosting provider mounts a persistent disk at `/var/data`, set `DATABASE_PATH=/var/data/routine-agent.sqlite3`. Without persistent storage, visitor data is lost when the instance is replaced.
- Terminate TLS at a trusted reverse proxy and set `COOKIE_SECURE=true` so session cookies are sent only over HTTPS.
- Keep the deployment to one app instance. The agent queues are in-process, and SQLite on a local persistent disk is not a shared database for multiple replicas. For multi-instance scaling, use a shared database and a dedicated job/message queue instead.

The app sets a restrictive Content Security Policy and standard browser security headers, validates request content, and does not enable cross-origin access. SQLite keeps each anonymous visitor's state separate; this demo does not provide user accounts or cross-device identity.

## Tests

```powershell
python -m unittest discover -s tests
```
