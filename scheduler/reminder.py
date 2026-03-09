"""
scheduler/reminder.py
Hybrid Reminder Engine (V1 + V2)

Features:
- GUI popup reminders (V1 style)
- Background reminder scheduling (V2 style)
- Persistent storage (JSON)
- Thread-safe reminder checking
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional, Dict, Any

import tkinter.simpledialog as simpledialog
import tkinter.messagebox as messagebox

from utils.config import Config


class ReminderEngine:

    CHECK_INTERVAL = 30

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

    # -------------------------------------------------------

    def set_fire_callback(self, cb: Callable[[str, str], None]):
        """
        Callback fired when reminder triggers
        """
        self._fire_callback = cb

    # -------------------------------------------------------

    def start(self):

        self._running = True

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="Friday-ReminderEngine"
        )

        self._thread.start()

        self.logger.info("Reminder engine started")

    def stop(self):

        self._running = False

        self.logger.info("Reminder engine stopped")

    # -------------------------------------------------------
    # V2 Scheduled Reminder
    # -------------------------------------------------------

    def add_reminder(self, hhmm: str, message: str):

        reminder = {
            "time": hhmm,
            "message": message,
            "fired": False
        }

        with self._lock:
            self._reminders.append(reminder)

        self._save()

        self.logger.info("Reminder added: [%s] %s", hhmm, message)

    # -------------------------------------------------------
    # V1 Style GUI Reminder
    # -------------------------------------------------------

    def add_reminder_dialog(self):

        time_str = simpledialog.askstring(
            "Add Reminder",
            "Enter time (HH:MM)"
        )

        if not time_str:
            return

        message = simpledialog.askstring(
            "Reminder Message",
            "What should I remind you about?"
        )

        if not message:
            return

        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:

            messagebox.showerror(
                "Invalid Time",
                "Time must be in HH:MM format."
            )

            return

        self.add_reminder(time_str, message)

        messagebox.showinfo(
            "Friday",
            f"Reminder set for {time_str}"
        )

    # -------------------------------------------------------

    def list_reminders(self):

        with self._lock:

            active = [r for r in self._reminders if not r["fired"]]

        return active

    # -------------------------------------------------------

    def view_reminders_dialog(self):

        reminders = self.list_reminders()

        if not reminders:

            messagebox.showinfo(
                "Friday",
                "No reminders set."
            )

            return

        text = ""

        for r in reminders:
            text += f"{r['time']}  -  {r['message']}\n"

        messagebox.showinfo(
            "Your Reminders",
            text
        )

    # -------------------------------------------------------

    def clear_all(self):

        with self._lock:
            self._reminders.clear()

        self._save()

        self.logger.info("All reminders cleared")

    # -------------------------------------------------------

    def _loop(self):

        while self._running:

            self._check()

            time.sleep(self.CHECK_INTERVAL)

    # -------------------------------------------------------

    def _check(self):

        now = datetime.now().strftime("%H:%M")

        fired_any = False

        with self._lock:

            for reminder in self._reminders:

                if not reminder["fired"] and reminder["time"] == now:

                    reminder["fired"] = True

                    fired_any = True

                    msg = reminder["message"]

                    self.logger.info(
                        "Reminder fired: [%s] %s",
                        now,
                        msg
                    )

                    if self._fire_callback:

                        try:
                            self._fire_callback(
                                reminder["time"],
                                msg
                            )

                        except Exception as e:

                            self.logger.error(
                                "Reminder callback error: %s",
                                e
                            )

        if fired_any:
            self._save()

    # -------------------------------------------------------

    def _load(self):

        if os.path.exists(self._file):

            try:

                with open(self._file, "r", encoding="utf-8") as f:

                    data = json.load(f)

                    for r in data:
                        r["fired"] = False

                    self._reminders = data

                self.logger.info(
                    "Loaded %d reminder(s)",
                    len(self._reminders)
                )

            except Exception as e:

                self.logger.warning(
                    "Could not load reminders: %s",
                    e
                )

                self._reminders = []

        else:

            self._reminders = []

    # -------------------------------------------------------

    def _save(self):

        os.makedirs(os.path.dirname(self._file), exist_ok=True)

        try:

            with open(self._file, "w", encoding="utf-8") as f:

                json.dump(self._reminders, f, indent=2)

        except Exception as e:

            self.logger.error(
                "Could not save reminders: %s",
                e
            )