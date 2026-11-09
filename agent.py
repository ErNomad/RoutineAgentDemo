import queue
import threading
import time
from datetime import datetime


class Agent(threading.Thread):
    """Base agent: a thread that blocks on its inbox and reacts to each message."""

    def __init__(self, name, on_event=None):
        super().__init__(name=name, daemon=True)
        self.inbox = queue.Queue()
        self.on_event = on_event

    def send(self, text, request_id=None, user_id=None, message_type="message"):
        self.inbox.put((message_type, text, request_id, user_id))

    def send_control(self, message_type, text, request_id=None, user_id=None):
        self.send(text, request_id, user_id, message_type)

    def stop(self):
        self.inbox.put(None)

    def run(self):
        while True:
            message = self.inbox.get()
            if message is None:
                break
            message_type, text, request_id, user_id = message
            if message_type == "message":
                self.on_message(text, request_id, user_id)
            else:
                self.on_control_message(message_type, text, request_id, user_id)

    def emit(self, event, user_id=None):
        if self.on_event is not None:
            if user_id is not None:
                event = {**event, "user_id": user_id}
            self.on_event(event)

    def on_message(self, text, request_id=None, user_id=None):
        raise NotImplementedError

    def on_control_message(self, message_type, text, request_id=None, user_id=None):
        raise ValueError(f"{self.name} cannot handle control message {message_type!r}")


class Agent1(Agent):
    """Receives what the user types and passes it on to Agent2."""

    def __init__(self, agent2, on_event=None):
        super().__init__("Agent1", on_event)
        self.agent2 = agent2

    def on_message(self, text, request_id=None, user_id=None):
        print(f"Agent1: sending '{text}'")
        self.emit({
            "type": "handoff",
            "agent": self.name,
            "title": "Greeting received",
            "message": f"Passing “{text}” to Agent 2.",
            "payload": text,
            "request_id": request_id,
        }, user_id)
        self.agent2.send(text, request_id, user_id)

    def on_control_message(self, message_type, text, request_id=None, user_id=None):
        if message_type != "agent_reply":
            return super().on_control_message(message_type, text, request_id, user_id)
        self.emit({
            "type": "agent_reply",
            "agent": self.name,
            "title": "Routine message delivered",
            "message": text,
            "payload": text,
            "direction": "reverse",
            "request_id": request_id,
        }, user_id)


class Agent2(Agent):
    """Translates greetings into instructions for Agent3."""

    def __init__(self, agent3, on_event=None):
        super().__init__("Agent2", on_event)
        self.agent3 = agent3
        self.agent1 = None

    def on_message(self, text, request_id=None, user_id=None):
        msg = text.strip().lower()
        if msg == "good morning":
            out = "Time to start the day"
        elif msg == "good night":
            out = "It's time to sleep now"
        else:
            print(f"Agent2: I don't understand '{text}'")
            self.emit({
                "type": "rejected",
                "agent": self.name,
                "title": "Input not understood",
                "message": f"Agent 2 could not interpret “{text}”.",
                "request_id": request_id,
            }, user_id)
            return
        print(f"Agent2: sending '{out}'")
        self.emit({
            "type": "translation",
            "agent": self.name,
            "title": "Greeting translated",
            "message": f"Converted the greeting into “{out}” and sent it to Agent 3.",
            "payload": out,
            "request_id": request_id,
        }, user_id)
        self.agent3.send(out, request_id, user_id)

    def on_control_message(self, message_type, text, request_id=None, user_id=None):
        if message_type != "timer_started":
            return super().on_control_message(message_type, text, request_id, user_id)
        state = text
        timer_name = "day" if state == "day" else "night"
        greeting = "Have a good day!" if state == "day" else "Have a good night's sleep!"
        self.emit({
            "type": "timer_ack",
            "agent": self.name,
            "title": "Timer start acknowledged",
            "message": f"Agent 3 reports the {timer_name} timer started.",
            "payload": f"{timer_name} timer started",
            "direction": "reverse",
            "request_id": request_id,
        }, user_id)
        if self.agent1 is None:
            raise RuntimeError("Agent2 cannot send its reply before Agent1 is connected")
        self.agent1.send_control("agent_reply", greeting, request_id, user_id)


class Agent3(Agent):
    """Tracks how long the day and the sleep last."""

    def __init__(self, on_event=None, state_loader=None, history_limit=14):
        super().__init__("Agent3", on_event)
        self.state_loader = state_loader
        self.state = None  # None (nothing yet), "day" or "sleep"
        self.wake_time = None
        self.day_start = None
        self.sleep_start = None
        self.day_started_at = None
        self.sleep_started_at = None
        self.day_elapsed_seconds = 0
        self.sleep_elapsed_seconds = 0
        self.routine_history = []
        self.history_limit = history_limit
        self.agent2 = None
        self.active_history_record = None

    def on_message(self, text, request_id=None, user_id=None):
        if self.state_loader is not None:
            self._restore_state(self.state_loader(user_id))

        # Only alternate: a day must be followed by sleep and vice versa.
        if text == "Time to start the day" and self.state == "day":
            print("Agent3: The day has already started. Only 'Good night' is accepted now.")
            self.emit({
                "type": "rejected",
                "agent": self.name,
                "title": "Day already in progress",
                "message": "The day has already started. Try Good night next.",
                "state": self.state,
                "request_id": request_id,
            }, user_id)
            return
        if text == "It's time to sleep now" and self.state == "sleep":
            print("Agent3: Already sleeping. Only 'Good morning' is accepted now.")
            self.emit({
                "type": "rejected",
                "agent": self.name,
                "title": "Sleep already in progress",
                "message": "Sleep is already in progress. Try Good morning next.",
                "state": self.state,
                "request_id": request_id,
            }, user_id)
            return

        detail = ""
        if text == "Time to start the day":
            self.state = "day"
            if self.sleep_start is not None:
                slept = time.monotonic() - self.sleep_start
                self.sleep_elapsed_seconds = int(slept)
                detail = f" Last sleep lasted {self.fmt(slept)}."
                print(f"Agent3: Sleep lasted {self.fmt(slept)}")
                self.sleep_start = None
            self.sleep_started_at = None
            self.day_elapsed_seconds = 0
            started_at = datetime.now().astimezone()
            self.wake_time = started_at
            self.day_start = time.monotonic()
            self.day_started_at = started_at.isoformat()
            day = started_at.date().isoformat()
            self.active_history_record = next(
                (record for record in reversed(self.routine_history) if record["date"] == day),
                None,
            )
            if self.active_history_record is None:
                self.active_history_record = {
                    "date": day,
                    "wake_time": None,
                    "sleep_time": None,
                }
                self.routine_history.append(self.active_history_record)
            self.active_history_record["wake_time"] = self.day_started_at
            self.routine_history = self.routine_history[-self.history_limit:]
            print(f"Agent3: Day timer started at {self.wake_time:%H:%M:%S}")

        elif text == "It's time to sleep now":
            self.state = "sleep"
            started_at = datetime.now().astimezone()
            if self.day_start is not None:
                day_length = time.monotonic() - self.day_start
                self.day_elapsed_seconds = int(day_length)
                detail = f" The day lasted {self.fmt(day_length)}."
                print(f"Agent3: Woke at {self.wake_time:%H:%M:%S}, "
                      f"day lasted {self.fmt(day_length)}")
                self.day_start = None
            self.day_started_at = None
            self.sleep_elapsed_seconds = 0
            self.sleep_start = time.monotonic()
            self.sleep_started_at = started_at.isoformat()
            if self.active_history_record is not None:
                self.active_history_record["sleep_time"] = self.sleep_started_at
            else:
                day = started_at.date().isoformat()
                self.active_history_record = next(
                    (record for record in reversed(self.routine_history) if record["date"] == day),
                    None,
                )
                if self.active_history_record is None:
                    self.active_history_record = {
                        "date": day,
                        "wake_time": None,
                        "sleep_time": None,
                    }
                    self.routine_history.append(self.active_history_record)
                self.active_history_record["sleep_time"] = self.sleep_started_at
                self.routine_history = self.routine_history[-self.history_limit:]
            self.active_history_record = None
            print("Agent3: Sleep timer started")

        state_message = (
            "Your day is underway."
            if self.state == "day"
            else "Sleep is underway."
        )
        self.emit({
            "type": "result",
            "agent": self.name,
            "title": "Routine updated",
            "message": f"{state_message}{detail}",
            "state": self.state,
            "day_started_at": self.day_started_at,
            "sleep_started_at": self.sleep_started_at,
            "day_elapsed_seconds": self.day_elapsed_seconds,
            "sleep_elapsed_seconds": self.sleep_elapsed_seconds,
            "routine_history": [dict(record) for record in self.routine_history],
            "request_id": request_id,
        }, user_id)
        if self.agent2 is not None:
            self.agent2.send_control("timer_started", self.state, request_id, user_id)

    def _restore_state(self, stored):
        self.state = stored["state"]
        self.day_started_at = stored["day_started_at"]
        self.sleep_started_at = stored["sleep_started_at"]
        self.day_elapsed_seconds = stored["day_elapsed_seconds"]
        self.sleep_elapsed_seconds = stored["sleep_elapsed_seconds"]
        self.routine_history = stored["routine_history"]
        self.day_start = self._monotonic_start(self.day_started_at)
        self.sleep_start = self._monotonic_start(self.sleep_started_at)
        self.wake_time = (
            datetime.fromisoformat(self.day_started_at)
            if self.day_started_at is not None
            else None
        )
        self.active_history_record = None
        if self.state == "day" and self.routine_history:
            self.active_history_record = self.routine_history[-1]

    @staticmethod
    def _monotonic_start(started_at):
        if started_at is None:
            return None
        start = datetime.fromisoformat(started_at).timestamp()
        elapsed = max(0, datetime.now().astimezone().timestamp() - start)
        return time.monotonic() - elapsed

    @staticmethod
    def fmt(seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s"