"""
utils/config.py
Centralised configuration management for Friday.

KEY CHANGE (v4)
---------------
enable_voice_output now defaults to True.
The old default of False was the primary reason TTS was never triggered.
"""

import os
import json
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "assistant_name":          "Friday",
    "wake_word":               "hey friday",
    "porcupine_access_key":    "",
    "porcupine_keyword_path":  "",
    "voice_language":          "en-US",
    "speech_timeout":          6,
    "speech_phrase_limit":     12,
    "log_level":               "INFO",
    "log_dir":                 os.path.join(BASE_DIR, "logs"),
    "data_dir":                os.path.join(BASE_DIR, "data"),
    "reminders_file":          os.path.join(BASE_DIR, "data", "reminders.json"),
    "command_history_file":    os.path.join(BASE_DIR, "data", "history.json"),
    "gui_theme":               "dark",
    "gui_width":               980,
    "gui_height":              700,
    "max_history_display":     200,
    "search_root_dirs": [
        os.path.expanduser("~\\Desktop"),
        os.path.expanduser("~\\Documents"),
        os.path.expanduser("~\\Downloads"),
        os.path.expanduser("~"),
    ],
    "browser_path":            "",
    "text_editor_path":        "",
    # ── Voice flags ────────────────────────────────────────────────────
    "enable_wake_word":        True,
    "enable_voice_input":      True,
    "enable_voice_output":     True,   # FIX: was False — this disabled all TTS
    # ── TTS settings ───────────────────────────────────────────────────
    "tts_rate":                170,
    "tts_volume":              0.95,
    "tts_voice_gender":        "female",
    # ── Conversation timeouts ──────────────────────────────────────────
    "conv_listen_timeout":     12,
    "conv_max_failures":       3,
}


class Config:
    """Loads, validates, and provides access to all Friday settings."""

    CONFIG_FILE = os.path.join(BASE_DIR, "friday_config.json")

    def __init__(self):
        self._data = dict(DEFAULTS)
        self._load()
        self._ensure_dirs()

    def _load(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                self._data.update(user_cfg)
            except Exception as e:
                logging.getLogger("Friday.Config").warning(
                    "Could not load config file: %s — using defaults", e
                )
        else:
            self.save()

    def save(self):
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logging.getLogger("Friday.Config").error("Could not save config: %s", e)

    def _ensure_dirs(self):
        for key in ("log_dir", "data_dir"):
            os.makedirs(self._data[key], exist_ok=True)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self.set(key, value)