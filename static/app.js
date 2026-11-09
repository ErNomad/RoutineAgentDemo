const stateLabel = document.querySelector("#state-label");
const stateIcon = document.querySelector("#state-icon");
const themeColor = document.querySelector("#theme-color");
const connectionStatus = document.querySelector("#connection-status");
const connectionLabel = document.querySelector("#connection-label");
const errorMessage = document.querySelector("#error-message");
const buttons = [...document.querySelectorAll("[data-greeting]")];
const agents = [
  document.querySelector("#agent-one"),
  document.querySelector("#agent-two"),
  document.querySelector("#agent-three"),
];
const agentStatuses = [
  document.querySelector("#agent-one-status"),
  document.querySelector("#agent-two-status"),
  document.querySelector("#agent-three-status"),
];
const dayClock = document.querySelector("#day-clock");
const sleepClock = document.querySelector("#sleep-clock");
const dayClockStatus = document.querySelector("#day-clock-status");
const sleepClockStatus = document.querySelector("#sleep-clock-status");
const routineChart = document.querySelector("#routine-chart");
const chartEmpty = document.querySelector("#chart-empty");
const SVG_NS = "http://www.w3.org/2000/svg";

let cursor = 0;
let currentState = null;
let routineHistory = [];
let initialized = false;
let submitting = false;
let dayStartedAt = null;
let sleepStartedAt = null;
let dayElapsedSeconds = 0;
let sleepElapsedSeconds = 0;
const pageLoadedAt = Date.now();
const pendingRequests = new Set();
const completedRequests = new Set();

function updateControls() {
  const isDay = currentState === "day";
  const isSleep = currentState === "sleep";
  stateLabel.textContent = isDay
    ? "Day in progress"
    : isSleep
      ? "Sleep in progress"
      : "Ready for a greeting";
  stateIcon.textContent = isDay ? "☀" : isSleep ? "☾" : "✦";

  for (const button of buttons) {
    const disabledByState =
      (isDay && button.dataset.greeting === "Good morning") ||
      (isSleep && button.dataset.greeting === "Good night");
    button.disabled = submitting || pendingRequests.size > 0 || disabledByState;
  }
}

function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const remainingSeconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${remainingSeconds}`;
}

function elapsedSince(startedAt) {
  if (!startedAt) return 0;
  return Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
}

function updateClocks() {
  dayClock.textContent = formatDuration(
    dayElapsedSeconds + (dayStartedAt ? elapsedSince(dayStartedAt) : 0),
  );
  sleepClock.textContent = formatDuration(
    sleepElapsedSeconds + (sleepStartedAt ? elapsedSince(sleepStartedAt) : 0),
  );
  dayClockStatus.textContent = dayStartedAt
    ? "Running"
    : routineHistory.some((record) => record.wake_time)
      ? "Complete"
      : "Not started";
  sleepClockStatus.textContent = sleepStartedAt
    ? "Running"
    : routineHistory.some((record) => record.sleep_time)
      ? "Complete"
      : "Not started";
}

function setAgent(index, status, phase = "active") {
  const agent = agents[index];
  for (const state of ["is-active", "is-complete", "is-rejected"]) {
    agent.classList.remove(state);
  }
  if (phase !== "idle") agent.classList.add(`is-${phase}`);
  agentStatuses[index].textContent = status;
}

function setWaitingAgents() {
  for (let index = 0; index < agents.length; index += 1) {
    agents[index].classList.remove("is-active", "is-complete", "is-rejected");
    agentStatuses[index].textContent = "Waiting";
  }
}

function applyRoutine(event) {
  currentState = event.state;
  dayStartedAt = event.day_started_at;
  sleepStartedAt = event.sleep_started_at;
  dayElapsedSeconds = event.day_elapsed_seconds || 0;
  sleepElapsedSeconds = event.sleep_elapsed_seconds || 0;
  routineHistory = event.routine_history || routineHistory;

  document.body.classList.toggle("theme-day", currentState === "day");
  document.body.classList.toggle("theme-night", currentState === "sleep");
  themeColor.content = currentState === "sleep" ? "#171c31" : "#f5f4f0";
  updateClocks();
  renderChart();
  updateControls();
}

function addSvgElement(tag, attributes = {}, text = "") {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  if (text) element.textContent = text;
  routineChart.append(element);
  return element;
}

function renderChart() {
  routineChart.replaceChildren(
    Object.assign(document.createElementNS(SVG_NS, "title"), {
      textContent: "Daily awake and sleep intervals",
    }),
    Object.assign(document.createElementNS(SVG_NS, "desc"), {
      textContent: "Dates are on the horizontal axis and time of day is on the vertical axis. Adjacent red and blue bars show awake and sleep durations.",
    }),
  );
  const records = routineHistory.slice(-14);
  const wakeTimes = records
    .map((record) => Date.parse(record.wake_time))
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
  const intervals = [];
  for (const [index, record] of records.entries()) {
    const wake = Date.parse(record.wake_time);
    const sleep = Date.parse(record.sleep_time);
    const isCurrentRecord = index === records.length - 1;
    const nextWake = Number.isFinite(sleep)
      ? wakeTimes.find((time) => time > sleep)
      : undefined;
    const wakeEnd = Number.isFinite(wake)
      ? Number.isFinite(sleep) && sleep > wake
        ? new Date(sleep)
        : currentState === "day" && isCurrentRecord
          ? new Date()
          : null
      : null;
    const sleepEnd = Number.isFinite(sleep)
      ? nextWake !== undefined
        ? new Date(nextWake)
        : currentState === "sleep" && isCurrentRecord
          ? new Date()
          : null
      : null;
    if ((!Number.isFinite(wake) || wakeEnd === null) && (!Number.isFinite(sleep) || sleepEnd === null)) {
      continue;
    }

    intervals.push({
      date: record.date,
      index,
      wake: Number.isFinite(wake) ? new Date(wake) : null,
      wakeEnd,
      sleep: Number.isFinite(sleep) ? new Date(sleep) : null,
      sleepEnd,
    });
  }

  chartEmpty.hidden = intervals.length > 0;
  const bounds = { left: 82, right: 698, top: 38, bottom: 338 };
  const columnWidth = (bounds.right - bounds.left) / Math.max(1, records.length);
  const xForIndex = (index) => bounds.left + columnWidth * (index + 0.5);
  const yForTime = (date) => {
    const time = date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
    return bounds.bottom - (time / 24) * (bounds.bottom - bounds.top);
  };
  addSvgElement("text", {
    x: 19,
    y: (bounds.top + bounds.bottom) / 2,
    transform: `rotate(-90 19 ${(bounds.top + bounds.bottom) / 2})`,
    class: "chart-axis-label",
  }, "Time of day");

  for (let hour = 0; hour <= 24; hour += 1) {
    const y = bounds.bottom - (hour / 24) * (bounds.bottom - bounds.top);
    addSvgElement("line", {
      x1: bounds.left,
      x2: bounds.right,
      y1: y,
      y2: y,
      class: "chart-gridline",
    });
    addSvgElement("text", {
      x: bounds.left - 9,
      y: y + 4,
      "text-anchor": "end",
      class: "chart-axis-label chart-hour-label",
    }, hour === 0 ? "0:00" : hour === 24 ? "24:00" : `${String(hour).padStart(2, "0")}:00`);
  }

  addSvgElement("text", {
    x: (bounds.left + bounds.right) / 2,
    y: 382,
    "text-anchor": "middle",
    class: "chart-axis-label",
  }, "Date");

  for (const [index, record] of records.entries()) {
    const date = new Date(`${record.date}T12:00:00`);
    addSvgElement("text", {
      x: xForIndex(index),
      y: bounds.bottom + 17,
      "text-anchor": "middle",
      class: "chart-axis-label chart-date-label",
    }, date.toLocaleDateString([], { month: "short", day: "numeric" }));
    addSvgElement("line", {
      x1: bounds.left + columnWidth * index,
      x2: bounds.left + columnWidth * index,
      y1: bounds.top,
      y2: bounds.bottom,
      class: "chart-gridline chart-date-gridline",
    });
  }

  if (records.length > 0) {
    addSvgElement("line", {
      x1: bounds.right,
      x2: bounds.right,
      y1: bounds.top,
      y2: bounds.bottom,
      class: "chart-gridline chart-date-gridline",
    });
  }

  const addIntervalBox = (x, start, end, intervalClass, titleText) => {
    if (start === null || end === null || end <= start) return;
    const startY = yForTime(start);
    const endY = yForTime(end);
    const pieces = end.getTime() > start.getTime() && endY >= startY
      ? [[bounds.top, startY], [endY, bounds.bottom]]
      : [[startY, endY]];

    for (const [firstY, secondY] of pieces) {
      const actualTop = Math.min(firstY, secondY);
      const actualHeight = Math.abs(secondY - firstY);
      const height = Math.max(3, actualHeight);
      const top = Math.max(
        bounds.top,
        Math.min(bounds.bottom - height, actualTop - (height - actualHeight) / 2),
      );
      const box = addSvgElement("rect", {
        x: x - 5,
        y: top,
        width: 10,
        height,
        rx: 1.5,
        class: `duration-box ${intervalClass}`,
      });
      const title = document.createElementNS(SVG_NS, "title");
      title.textContent = titleText;
      box.append(title);
    }
  };

  const formatElapsed = (milliseconds) => {
    const totalSeconds = Math.floor(milliseconds / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return `${hours}h ${minutes}m ${seconds}s`;
  };

  for (const interval of intervals) {
    const center = xForIndex(interval.index);
    const wakeDuration = interval.wake && interval.wakeEnd
      ? (interval.wakeEnd - interval.wake) / 3_600_000
      : null;
    const sleepDuration = interval.sleep && interval.sleepEnd
      ? (interval.sleepEnd - interval.sleep) / 3_600_000
      : null;
    addIntervalBox(
      center - 7,
      interval.wake,
      interval.wakeEnd,
      "wake-duration",
      wakeDuration === null
        ? ""
        : `${interval.date}: awake ${formatElapsed(interval.wakeEnd - interval.wake)}, ` +
          `${interval.wake.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to ` +
          `${interval.wakeEnd.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
    );
    addIntervalBox(
      center + 7,
      interval.sleep,
      interval.sleepEnd,
      "sleep-duration",
      sleepDuration === null
        ? ""
        : `${interval.date}: sleep ${formatElapsed(interval.sleepEnd - interval.sleep)}, ` +
          `${interval.sleep.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to ` +
          `${interval.sleepEnd.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
    );
  }

  const description = `Date is on the horizontal axis and time of day is on the vertical axis. ` +
    `Adjacent red boxes show awake intervals and blue boxes show sleep intervals; ` +
    `box length represents duration. ${intervals.length} day(s) with intervals.`;
  routineChart.setAttribute("aria-label", description);
  routineChart.querySelector("desc").textContent = description;
}

function animatePacket(laneId, packetId, message, kind, direction = "forward") {
  const lane = document.querySelector(`#${laneId}`);
  const packet = document.querySelector(`#${packetId}`);
  packet.textContent = message;
  packet.className = `message-packet packet-${kind} ${direction === "reverse" ? "packet-reverse" : ""}`;
  lane.classList.toggle("is-reverse", direction === "reverse");
  void packet.offsetWidth;
  packet.classList.add("is-moving");
  const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? 100
    : 1450;
  return new Promise((resolve) => {
    window.setTimeout(() => {
      packet.classList.remove("is-moving");
      lane.classList.remove("is-reverse");
      resolve();
    }, duration);
  });
}

function resetForGreeting() {
  setWaitingAgents();
  setAgent(0, "Greeting received");
}

async function showEvent(event) {
  if (event.type === "system") return;

  if (event.type === "user") {
    resetForGreeting();
    if (event.request_id) pendingRequests.add(event.request_id);
    updateControls();
    return;
  }

  if (event.type === "handoff") {
    setAgent(0, "Sending greeting", "active");
    setAgent(1, "Receiving message", "active");
    await animatePacket("lane-one", "packet-one", event.payload, "greeting");
    setAgent(0, "Message sent", "complete");
    setAgent(1, "Greeting received", "complete");
    return;
  }

  if (event.type === "translation") {
    setAgent(1, "Translating", "active");
    setAgent(2, "Receiving instruction", "active");
    await animatePacket("lane-two", "packet-two", event.payload, "instruction");
    setAgent(1, "Instruction sent", "complete");
    setAgent(2, "Updating routine", "active");
    return;
  }

  if (event.type === "timer_ack") {
    setAgent(2, "Timer started", "complete");
    setAgent(1, "Sending acknowledgement", "active");
    await animatePacket("lane-two", "packet-two", event.payload, "acknowledgement", "reverse");
    setAgent(2, "Timer started", "complete");
    setAgent(1, "Sending well-wishes", "active");
    return;
  }

  if (event.type === "agent_reply") {
    setAgent(1, "Sending well-wishes", "active");
    setAgent(0, "Receiving reply", "active");
    await animatePacket("lane-one", "packet-one", event.payload, "reply", "reverse");
    setAgent(1, "Timer started", "complete");
    setAgent(0, event.payload, "complete");
    if (event.request_id) {
      completedRequests.add(event.request_id);
      pendingRequests.delete(event.request_id);
    }
    updateControls();
    return;
  }

  if (event.type === "result") {
    applyRoutine(event);
    setAgent(0, "Greeting received", "complete");
    setAgent(2, "Timer started", "complete");
    setAgent(1, "Waiting for timer notice", "complete");
    updateControls();
    return;
  }

  if (event.type === "rejected") {
    if (event.state !== undefined) currentState = event.state;
    const agentIndex = event.agent === "Agent2" ? 1 : 2;
    setAgent(agentIndex, "Already in this routine state", "rejected");
    setAgent(0, event.state === "day" ? "Waiting for night" : "Waiting for morning", "complete");
    if (event.request_id) {
      completedRequests.add(event.request_id);
      pendingRequests.delete(event.request_id);
    }
    updateControls();
  }
}

function hydrate(data) {
  currentState = data.state;
  routineHistory = data.routine_history || [];
  renderChart();
  const lastResult = [...data.events].reverse().find((event) => event.type === "result");
  if (lastResult) {
    applyRoutine(lastResult);
    setAgent(0, "Greeting received", "complete");
    setAgent(1, "Timer started", "complete");
    setAgent(2, currentState === "day" ? "Day timer running" : "Sleep timer running", "complete");
  } else {
    updateControls();
  }
  const latestEvent = data.events[data.events.length - 1];
  cursor = latestEvent ? latestEvent.id : cursor;
  initialized = true;
}

async function pollEvents() {
  let delay = 450;
  while (true) {
    try {
      const response = await fetch(`/api/events?after=${cursor}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Activity request failed (${response.status}).`);
      const data = await response.json();

      if (!initialized) {
        hydrate(data);
        const freshEvents = data.events.filter(
          (event) => event.type !== "system" && Date.parse(event.timestamp) >= pageLoadedAt,
        );
        if (freshEvents.length) {
          cursor = freshEvents[0].id - 1;
          for (const event of freshEvents) {
            await showEvent(event);
            cursor = event.id;
          }
        }
      } else {
        for (const event of data.events) {
          await showEvent(event);
          cursor = event.id;
        }
      }

      errorMessage.hidden = true;
      connectionStatus.classList.remove("connection-error");
      connectionLabel.textContent = "Live";
      delay = 450;
    } catch (error) {
      connectionStatus.classList.add("connection-error");
      connectionLabel.textContent = "Reconnecting";
      errorMessage.textContent = `Unable to load agent activity. ${error.message}`;
      errorMessage.hidden = false;
      delay = Math.min(delay * 2, 5000);
    }
    await new Promise((resolve) => window.setTimeout(resolve, delay));
  }
}

async function sendGreeting(greeting) {
  if (submitting || pendingRequests.size > 0) return;
  submitting = true;
  errorMessage.hidden = true;
  updateControls();
  try {
    const response = await fetch("/api/greetings", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ greeting }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Greeting request failed (${response.status}).`);
    if (!completedRequests.has(data.request_id)) pendingRequests.add(data.request_id);
  } catch (error) {
    errorMessage.textContent = error.message;
    errorMessage.hidden = false;
  } finally {
    submitting = false;
    updateControls();
  }
}

for (const button of buttons) {
  button.addEventListener("click", () => sendGreeting(button.dataset.greeting));
}

updateClocks();
window.setInterval(updateClocks, 250);
window.setInterval(() => {
  if (currentState === "day" || currentState === "sleep") renderChart();
}, 1_000);
updateControls();
pollEvents();
