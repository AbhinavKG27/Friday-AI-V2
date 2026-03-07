"""
voice/speaker.py
----------------
Text-to-Speech output module for Friday AI.

Uses pyttsx3 (offline, cross-platform TTS engine).
Runs speech synthesis in a background thread so the GUI never blocks.
"""

import threading
import queue
import logging

logger = logging.getLogger("friday")

_tts_queue: queue.Queue = queue.Queue()
_engine = None
_worker_thread: threading.Thread = None
_enabled: bool = True


def _tts_worker():
    """Background worker that drains the TTS queue."""
    global _engine
    try:
        import pyttsx3
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 175)
        _engine.setProperty("volume", 1.0)
        logger.info("[Speaker] pyttsx3 TTS engine initialised.")
    except Exception as exc:
        logger.warning(f"[Speaker] Could not initialise pyttsx3: {exc}")
        _engine = None

    while True:
        item = _tts_queue.get()
        if item is None:  # shutdown sentinel
            break
        text, rate, volume = item
        if _engine and _enabled:
            try:
                _engine.setProperty("rate", rate)
                _engine.setProperty("volume", volume)
                _engine.say(text)
                _engine.runAndWait()
            except Exception as exc:
                logger.warning(f"[Speaker] TTS error: {exc}")
        _tts_queue.task_done()


def start(rate: int = 175, volume: float = 1.0):
    """Start the background TTS worker thread."""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(
        target=_tts_worker, daemon=True, name="friday-tts"
    )
    _worker_thread.start()


def speak(text: str, rate: int = 175, volume: float = 1.0):
    """
    Queue text for speech synthesis (non-blocking).

    Args:
        text:   The string to speak.
        rate:   Words per minute (default 175).
        volume: 0.0 – 1.0 (default 1.0).
    """
    if not text or not text.strip():
        return
    if not _enabled:
        return
    _tts_queue.put((text.strip(), rate, volume))


def set_enabled(enabled: bool):
    """Toggle TTS on/off at runtime."""
    global _enabled
    _enabled = enabled
    logger.info(f"[Speaker] Voice output {'enabled' if enabled else 'disabled'}.")


def set_rate(rate: int):
    """Change speech rate (words per minute)."""
    global _engine
    if _engine:
        _engine.setProperty("rate", rate)


def set_volume(volume: float):
    """Change speech volume (0.0–1.0)."""
    global _engine
    if _engine:
        _engine.setProperty("volume", volume)


def shutdown():
    """Gracefully stop the TTS worker."""
    _tts_queue.put(None)
