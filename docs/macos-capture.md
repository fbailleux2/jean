# macOS App-Transition Capture — Setup Guide

This guide explains how to run `jean-agent` with live application-transition
capture on macOS using NSWorkspace notifications.

---

## Prerequisites

- macOS 13 (Ventura) or later
- Python 3.11+
- `uv` installed (`pip install uv`)
- Jean cloned and dependencies installed

---

## 1. Install pyobjc (macOS extra)

```bash
cd /path/to/jean
uv sync --extra macos
```

This installs `pyobjc-framework-Cocoa` into the virtual environment.
It is only needed on the workstation running `jean-agent`.

---

## 2. Grant Accessibility permission

Jean uses `NSWorkspace` to detect which application is in focus.
This requires the **Accessibility** permission.

1. Open **System Settings → Privacy & Security → Accessibility**
2. Click **+** and add your terminal application (Terminal, iTerm2, or the
   Python executable in the venv: `.venv/bin/python3`)
3. Toggle it **ON**

> **Note:** you may need to repeat this if you re-create the virtual environment,
> as macOS tracks the binary path.

---

## 3. Configure environment variables

Create a `.env` file (or export in your shell):

```bash
# The process context this workstation is being observed for
export JEAN_PROCESS_CONTEXT=invoice-exception

# Pseudonymous ID for this workstation — never use a username or email
export JEAN_WORKSTATION_ID=ws-$(uuidgen | tr '[:upper:]' '[:lower:]')

# URL of jean-aggregator
export JEAN_AGGREGATOR_URL=http://localhost:8100

# Path to the local SQLite buffer
export JEAN_BUFFER_PATH=~/.jean/agent.db
```

---

## 4. Start jean-aggregator (if not already running)

```bash
uv run jean-aggregator
# → listening on http://localhost:8100
```

---

## 5. Start jean-agent

```bash
uv run jean-agent
```

You should see log output like:

```
INFO  jean-agent starting  db=~/.jean/agent.db  aggregator=http://localhost:8100
INFO  Starting capture session  session_id=...  process_context=invoice-exception
```

Switch between applications — you should see events in the aggregator logs.

---

## 6. Verify capture is working

Check the aggregator's pattern endpoint:

```bash
curl http://localhost:8100/patterns | python3 -m json.tool
```

After several application transitions, patterns should appear.

---

## Privacy reminders

- Only the **application name** is captured — never window title or document path.
- No continuous recording. Jean is event-driven.
- Events are anonymized by the aggregator before any corpus storage.
- Inform users before deploying in an organizational context.
- See `VISION.md` in the FlowFabric repo for the full legal framework.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No events in aggregator | Missing Accessibility permission | Re-add terminal to Privacy → Accessibility |
| `ImportError: No module named 'AppKit'` | pyobjc not installed | `uv sync --extra macos` |
| `jean-agent` exits immediately | Aggregator not reachable | Start aggregator first |
| Events stop after sleep | macOS suspends the process | Disable App Nap: `defaults write -g NSAppSleepDisabled -bool YES` |
