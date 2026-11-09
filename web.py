import atexit
from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

from agent import Agent1, Agent2, Agent3


class SQLiteRoutineStore:
    """Stores anonymous visitor state and events in a shared SQLite database."""

    def __init__(self, path, event_limit=500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.event_limit = event_limit
        self._initialize_lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._initialize_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS routine_state (
                    user_id TEXT PRIMARY KEY,
                    state TEXT,
                    day_started_at TEXT,
                    sleep_started_at TEXT,
                    day_elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                    sleep_elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                    routine_history TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS routine_events (
                    user_id TEXT NOT NULL,
                    event_id INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, event_id)
                )
            """)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _ensure_user(self, connection, user_id):
        connection.execute(
            """INSERT OR IGNORE INTO routine_state (user_id, updated_at)
               VALUES (?, ?)""",
            (user_id, self._now()),
        )

    def get_user_state(self, user_id):
        with self._connect() as connection:
            self._ensure_user(connection, user_id)
            row = connection.execute(
                "SELECT * FROM routine_state WHERE user_id = ?", (user_id,)
            ).fetchone()
        return {
            "state": row["state"],
            "day_started_at": row["day_started_at"],
            "sleep_started_at": row["sleep_started_at"],
            "day_elapsed_seconds": row["day_elapsed_seconds"],
            "sleep_elapsed_seconds": row["sleep_elapsed_seconds"],
            "routine_history": json.loads(row["routine_history"]),
        }

    def publish(self, event):
        user_id = event.get("user_id")
        if not user_id:
            raise ValueError("Routine events must belong to an anonymous user")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user(connection, user_id)
            event_id = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) + 1 FROM routine_events WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
            timestamp = self._now()
            stored_event = {**event, "id": event_id, "timestamp": timestamp}
            connection.execute(
                """INSERT INTO routine_events (user_id, event_id, event_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, event_id, json.dumps(stored_event), timestamp),
            )

            state_values = None
            if "routine_history" in event:
                state_values = event
            elif "state" in event:
                state_values = {"state": event["state"]}
            if state_values is not None:
                row = connection.execute(
                    "SELECT * FROM routine_state WHERE user_id = ?", (user_id,)
                ).fetchone()
                current = {
                    "state": row["state"],
                    "day_started_at": row["day_started_at"],
                    "sleep_started_at": row["sleep_started_at"],
                    "day_elapsed_seconds": row["day_elapsed_seconds"],
                    "sleep_elapsed_seconds": row["sleep_elapsed_seconds"],
                    "routine_history": json.loads(row["routine_history"]),
                }
                current.update(state_values)
                connection.execute(
                    """UPDATE routine_state
                       SET state = ?, day_started_at = ?, sleep_started_at = ?,
                           day_elapsed_seconds = ?, sleep_elapsed_seconds = ?,
                           routine_history = ?, updated_at = ?
                       WHERE user_id = ?""",
                    (
                        current["state"],
                        current["day_started_at"],
                        current["sleep_started_at"],
                        current["day_elapsed_seconds"],
                        current["sleep_elapsed_seconds"],
                        json.dumps(current["routine_history"]),
                        timestamp,
                        user_id,
                    ),
                )
            connection.execute(
                """DELETE FROM routine_events
                   WHERE user_id = ? AND event_id <= ?""",
                (user_id, event_id - self.event_limit),
            )
        return stored_event

    def read_after(self, user_id, event_id):
        with self._connect() as connection:
            self._ensure_user(connection, user_id)
            rows = connection.execute(
                """SELECT event_json FROM routine_events
                   WHERE user_id = ? AND event_id > ? ORDER BY event_id""",
                (user_id, event_id),
            ).fetchall()
            state = connection.execute(
                "SELECT * FROM routine_state WHERE user_id = ?", (user_id,)
            ).fetchone()
        return {
            "events": [json.loads(row["event_json"]) for row in rows],
            "state": state["state"],
            "day_started_at": state["day_started_at"],
            "sleep_started_at": state["sleep_started_at"],
            "day_elapsed_seconds": state["day_elapsed_seconds"],
            "sleep_elapsed_seconds": state["sleep_elapsed_seconds"],
            "routine_history": json.loads(state["routine_history"]),
        }


class RoutineWorkflow:
    """One agent pipeline routes messages while keeping visitor data isolated."""

    def __init__(self, store):
        self.store = store
        self.agent3 = Agent3(self.store.publish, state_loader=self.store.get_user_state)
        self.agent2 = Agent2(self.agent3, self.store.publish)
        self.agent1 = Agent1(self.agent2, self.store.publish)
        self.agent2.agent1 = self.agent1
        self.agent3.agent2 = self.agent2
        self.agents = (self.agent1, self.agent2, self.agent3)
        self._started = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._started:
                return
            for agent in self.agents:
                agent.start()
            self._started = True

    def stop(self):
        with self._lock:
            if not self._started:
                return
            for agent in self.agents:
                agent.stop()
            for agent in self.agents:
                agent.join(timeout=2)
            self._started = False

    def submit(self, user_id, greeting):
        request_id = str(uuid.uuid4())
        self.store.publish({
            "type": "user",
            "agent": "You",
            "title": "Greeting sent",
            "message": greeting,
            "request_id": request_id,
            "user_id": user_id,
        })
        self.agent1.send(greeting, request_id, user_id=user_id)
        return request_id


def create_app(workflow=None, database_path=None, secret_key=None, cookie_secure=None):
    app = Flask(__name__)
    database_path = database_path or os.environ.get(
        "DATABASE_PATH",
        str(Path(app.instance_path) / "routine-agent.sqlite3"),
    )
    app.config.update(
        MAX_CONTENT_LENGTH=1024,
        JSON_SORT_KEYS=False,
        SECRET_KEY=secret_key or os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(
            os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")
            if cookie_secure is None
            else cookie_secure
        ),
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    )
    store = workflow.store if workflow is not None else SQLiteRoutineStore(database_path)
    routine = workflow or RoutineWorkflow(store)
    routine.start()
    app.extensions["routine_workflow"] = routine
    app.extensions["routine_store"] = store

    @app.before_request
    def set_anonymous_user():
        if "anonymous_user_id" not in session:
            session["anonymous_user_id"] = secrets.token_urlsafe(32)
        session.permanent = True

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/events")
    def get_events():
        raw_after = request.args.get("after", "0")
        try:
            event_id = int(raw_after)
        except ValueError:
            return jsonify(error="The 'after' cursor must be a non-negative integer."), 400
        if event_id < 0:
            return jsonify(error="The 'after' cursor must be a non-negative integer."), 400
        response = jsonify(
            store.read_after(session["anonymous_user_id"], event_id)
        )
        return response

    @app.post("/api/greetings")
    def submit_greeting():
        if not request.is_json:
            return jsonify(error="Send a JSON body with a greeting field."), 415
        payload = request.get_json(silent=True)
        greeting = payload.get("greeting") if isinstance(payload, dict) else None
        if greeting not in ("Good morning", "Good night"):
            return jsonify(error="Greeting must be 'Good morning' or 'Good night'."), 400
        request_id = routine.submit(session["anonymous_user_id"], greeting)
        response = jsonify(request_id=request_id, accepted=True)
        return response, 202

    return app


app = create_app()
atexit.register(app.extensions["routine_workflow"].stop)


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving Routine Agent Playground at http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=8)
