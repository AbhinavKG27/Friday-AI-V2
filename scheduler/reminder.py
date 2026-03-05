"""
scheduler/reminder.py
Background thread-based reminder engine.
Stores reminders in a JSON file and checks every 30 seconds.
Fires a callback (or messagebox) when a reminder is due.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional, Dict, Any

from utils.config import Config


class ReminderEngine:
    """
    Manages reminders:
    - Persistent storage (JSON)
    - Background polling thread
    - Fires tkinter messagebox when due (safe cross-thread via callback)
    """

    CHECK_INTERVAL = 30   # seconds

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("Friday.Reminder")
        self._file = config.get("reminders_file", "data/reminders.json")
        self._reminders: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fire_callback: Optional[Callable[[str, str], None]] = None
        self._load()

    # ------------------------------------------------------------------ #

    def set_fire_callback(self, cb: Callable[[str, str], None]):
        """
        Set a callback invoked when a reminder fires.
        Signature: cb(time_str, message)
        """
        self._fire_callback = cb

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Friday-Reminders")
        self._thread.start()
        self.logger.info("Reminder engine started")

    def stop(self):
        self._running = False
        self.logger.info("Reminder engine stopped")

    # ------------------------------------------------------------------ #

    def add_reminder(self, hhmm: str, message: str):
        """Add a reminder. hhmm = '07:00', '14:30' etc."""
        reminder = {"time": hhmm, "message": message, "fired": False}
        with self._lock:
            self._reminders.append(reminder)
        self._save()
        self.logger.info("Reminder added: [%s] %s", hhmm, message)

    def list_reminders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [r for r in self._reminders if not r["fired"]]

    def clear_all(self):
        with self._lock:
            self._reminders.clear()
        self._save()

    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._running:
            self._check()
            time.sleep(self.CHECK_INTERVAL)

    def _check(self):
        now = datetime.now().strftime("%H:%M")
        fired_any = False
        with self._lock:
            for reminder in self._reminders:
                if not reminder["fired"] and reminder["time"] == now:
                    reminder["fired"] = True
                    fired_any = True
                    self.logger.info("Reminder fired: [%s] %s", now, reminder["message"])
                    if self._fire_callback:
                        # Schedule on main thread via tkinter-safe call
                        try:
                            self._fire_callback(reminder["time"], reminder["message"])
                        except Exception as e:
                            self.logger.error("Reminder callback error: %s", e)
        if fired_any:
            self._save()

    # ------------------------------------------------------------------ #

    def _load(self):
        if os.path.exists(self._file):
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Reset fired status for a new session (daily reminders)
                    for r in data:
                        r["fired"] = False
                    self._reminders = data
                self.logger.info("Loaded %d reminder(s)", len(self._reminders))
            except Exception as e:
                self.logger.warning("Could not load reminders: %s", e)
                self._reminders = []
        else:
            self._reminders = []

    def _save(self):
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._reminders, f, indent=2)
        except Exception as e:
            self.logger.error("Could not save reminders: %s", e)
