import tempfile
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web import RoutineWorkflow, SQLiteRoutineStore, create_app


class RoutineWebTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "routine.sqlite3"
        self.store = SQLiteRoutineStore(self.database_path)
        self.workflow = RoutineWorkflow(self.store)
        self.secret_key = "test-session-secret"
        self.app = create_app(
            self.workflow,
            secret_key=self.secret_key,
            cookie_secure=False,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.workflow.stop()

    def user_id(self, client=None):
        client = client or self.client
        client.get("/")
        with client.session_transaction() as user_session:
            return user_session["anonymous_user_id"]

    def wait_for_event(self, user_id, request_id, event_types, store=None):
        store = store or self.store
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            events = store.read_after(user_id, 0)["events"]
            result = next(
                (
                    event for event in events
                    if event["request_id"] == request_id
                    and event["type"] in event_types
                ),
                None,
            )
            if result is not None:
                return result, events
            time.sleep(0.01)
        self.fail(f"No {event_types!r} event received for request {request_id}")

    def submit(self, greeting, client=None):
        client = client or self.client
        response = client.post("/api/greetings", json={"greeting": greeting})
        self.assertEqual(response.status_code, 202)
        return response.get_json()["request_id"]

    def test_homepage_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Good morning", response.data)
        self.assertIn(b"Good night", response.data)
        self.assertIn(b'id="agent-flow"', response.data)
        self.assertIn(b'id="day-clock"', response.data)
        self.assertIn(b'id="sleep-clock"', response.data)
        self.assertIn(b'id="routine-chart"', response.data)
        self.assertIn(b"Wake &amp; sleep duration", response.data)
        self.assertIn(b"Daily awake and sleep intervals", response.data)
        self.assertIn(b"Dates are on the horizontal axis", response.data)
        self.assertIn(b"Adjacent red and blue bars show awake and sleep durations", response.data)
        self.assertNotIn(b'id="timeline"', response.data)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_rejects_invalid_greetings_and_event_cursors(self):
        user_id = self.user_id()
        response = self.client.post("/api/greetings", json={"greeting": "hello"})
        self.assertEqual(response.status_code, 400)
        events = self.store.read_after(user_id, 0)["events"]
        self.assertEqual(events, [])
        self.assertEqual(self.client.get("/api/events?after=-1").status_code, 400)
        self.assertEqual(self.client.get("/api/events?after=nope").status_code, 400)

    def test_greetings_flow_through_agents_and_alternate_state(self):
        user_id = self.user_id()
        morning_id = self.submit("Good morning")
        _, events = self.wait_for_event(user_id, morning_id, ("agent_reply",))
        result = next(event for event in events if event["request_id"] == morning_id and event["type"] == "result")
        self.assertEqual(result["state"], "day")
        self.assertEqual(
            [event["type"] for event in events if event["request_id"] == morning_id],
            ["user", "handoff", "translation", "result", "timer_ack", "agent_reply"],
        )
        self.assertEqual(
            [event["payload"] for event in events if event["request_id"] == morning_id and "payload" in event],
            ["Good morning", "Time to start the day", "day timer started", "Have a good day!"],
        )
        self.assertTrue(result["day_started_at"])
        self.assertIsNone(result["sleep_started_at"])
        self.assertEqual(result["day_elapsed_seconds"], 0)
        self.assertEqual(len(result["routine_history"]), 1)
        self.assertEqual(result["routine_history"][0]["wake_time"], result["day_started_at"])
        self.assertIsNone(result["routine_history"][0]["sleep_time"])
        self.assertEqual(self.client.get("/api/events").get_json()["routine_history"], result["routine_history"])

        duplicate_id = self.submit("Good morning")
        duplicate, _ = self.wait_for_event(user_id, duplicate_id, ("rejected",))
        self.assertEqual(duplicate["type"], "rejected")
        self.assertEqual(duplicate["state"], "day")

        night_id = self.submit("Good night")
        _, night_events = self.wait_for_event(user_id, night_id, ("agent_reply",))
        night = next(event for event in night_events if event["request_id"] == night_id and event["type"] == "result")
        self.assertEqual(night["type"], "result")
        self.assertEqual(night["state"], "sleep")
        self.assertEqual(
            [event["payload"] for event in night_events if event["request_id"] == night_id and "payload" in event],
            ["Good night", "It's time to sleep now", "night timer started", "Have a good night's sleep!"],
        )
        self.assertIsNone(night["day_started_at"])
        self.assertTrue(night["sleep_started_at"])
        self.assertEqual(night["routine_history"][0]["sleep_time"], night["sleep_started_at"])

        morning_id = self.submit("Good morning")
        _, morning_events = self.wait_for_event(user_id, morning_id, ("agent_reply",))
        morning = next(event for event in morning_events if event["request_id"] == morning_id and event["type"] == "result")
        self.assertEqual(morning["state"], "day")
        self.assertTrue(morning["day_started_at"])
        self.assertIsNone(morning["sleep_started_at"])
        self.assertIn("Last sleep lasted", morning["message"])
        self.assertEqual(len(morning["routine_history"]), 1)
        self.assertEqual(morning["routine_history"][0]["wake_time"], morning["day_started_at"])
        self.assertEqual(
            morning["routine_history"][0]["sleep_time"],
            night["sleep_started_at"],
        )

    def test_browser_sessions_have_isolated_routines(self):
        first_user_id = self.user_id(self.client)
        second_client = self.app.test_client()
        second_user_id = self.user_id(second_client)
        self.assertNotEqual(first_user_id, second_user_id)

        morning_id = self.submit("Good morning", self.client)
        self.wait_for_event(first_user_id, morning_id, ("agent_reply",))

        second_snapshot = second_client.get("/api/events").get_json()
        self.assertIsNone(second_snapshot["state"])
        self.assertEqual(second_snapshot["events"], [])
        self.assertEqual(second_snapshot["routine_history"], [])

        night_id = self.submit("Good night", second_client)
        self.wait_for_event(second_user_id, night_id, ("agent_reply",))
        self.assertEqual(second_client.get("/api/events").get_json()["state"], "sleep")
        self.assertEqual(self.client.get("/api/events").get_json()["state"], "day")

    def test_user_state_survives_workflow_restart(self):
        user_id = self.user_id()
        morning_id = self.submit("Good morning")
        self.wait_for_event(user_id, morning_id, ("agent_reply",))
        session_cookie = self.client.get_cookie("session")
        self.workflow.stop()

        restarted_store = SQLiteRoutineStore(self.database_path)
        restarted_workflow = RoutineWorkflow(restarted_store)
        self.addCleanup(restarted_workflow.stop)
        restarted_app = create_app(
            restarted_workflow,
            secret_key=self.secret_key,
            cookie_secure=False,
        )
        restarted_client = restarted_app.test_client()
        restarted_client.set_cookie("session", session_cookie.value)
        restored = restarted_client.get("/api/events").get_json()
        self.assertEqual(restored["state"], "day")
        self.assertEqual(restored["routine_history"][0]["wake_time"], restored["day_started_at"])

        response = restarted_client.post(
            "/api/greetings", json={"greeting": "Good night"}
        )
        self.assertEqual(response.status_code, 202)
        night_id = response.get_json()["request_id"]
        self.wait_for_event(
            user_id,
            night_id,
            ("agent_reply",),
            store=restarted_store,
        )
        snapshot = restarted_store.read_after(user_id, 0)
        self.assertEqual(snapshot["state"], "sleep")
        self.assertEqual(len(snapshot["routine_history"]), 1)
        self.assertIsNotNone(snapshot["routine_history"][0]["wake_time"])
        self.assertIsNotNone(snapshot["routine_history"][0]["sleep_time"])


if __name__ == "__main__":
    unittest.main()
