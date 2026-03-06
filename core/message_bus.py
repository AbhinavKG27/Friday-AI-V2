"""
core/message_bus.py  —  Friday v4
====================================
Unified message dispatch pipeline.

Every single message in Friday — user speech, assistant response,
system note, reminder — flows through ONE function:

    bus.dispatch(source, text)

This guarantees perfect sync between the three output channels:
    1. Log file   (always)
    2. GUI panel  (always)
    3. TTS voice  (only when source == "FRIDAY" or "REMINDER")

Thread safety
-------------
dispatch() is safe to call from ANY thread. The gui_callback must
schedule Tkinter updates via root.after(0, ...) — the GUI does this.
TTS has its own worker thread and is inherently thread-safe.
"""

import logging
from typing import Callable, Optional, Set


class MessageBus:
    """
    Central message hub.

    Parameters
    ----------
    tts           : TextToSpeech | None
    gui_callback  : Callable[[str, str], None]
                    Signature: gui_callback(source, text)
                    Called for EVERY message regardless of source.
                    Must be thread-safe (use root.after in the GUI).
    speak_sources : which sources get spoken aloud.
                    Default: {"FRIDAY", "REMINDER"}
    """

    def __init__(
        self,
        tts,
        gui_callback: Callable[[str, str], None],
        speak_sources: Optional[Set[str]] = None,
    ):
        self._logger        = logging.getLogger("Friday.MessageBus")
        self._tts           = tts
        self._gui_cb        = gui_callback
        self._speak_sources = speak_sources if speak_sources is not None \
                              else {"FRIDAY", "REMINDER"}
        # When True, TTS blocks the caller until speech finishes.
        # Set True before opening the mic so we don't record our own voice.
        self._block_tts: bool = False

    # ──────────────────────────────────────────────────────
    # Core dispatch — the ONLY function that writes to all 3
    # ──────────────────────────────────────────────────────

    def dispatch(self, source: str, text: str, *, block: Optional[bool] = None) -> None:
        """
        Send a message through all active channels.

        Parameters
        ----------
        source : "FRIDAY" | "USER" | "SYSTEM" | "REMINDER"
        text   : message text
        block  : override the blocking mode for this one call.
                 None → use the current self._block_tts setting.

        Example
        -------
        bus.dispatch("FRIDAY", "Opening downloads folder.")
        bus.dispatch("USER",   "open downloads")
        bus.dispatch("SYSTEM", "Wake word detected")
        """
        if not text:
            return
        text = text.strip()
        if not text:
            return

        # ── 1. Log ───────────────────────────────────────────────────────
        self._logger.info("[%s] %s", source, text[:300])

        # ── 2. GUI ───────────────────────────────────────────────────────
        try:
            self._gui_cb(source, text)
        except Exception as exc:
            self._logger.error("GUI callback error: %s", exc)

        # ── 3. TTS (only for speaking sources) ───────────────────────────
        if source in self._speak_sources:
            should_block = self._block_tts if block is None else block
            if self._tts and self._tts.is_available:
                try:
                    self._tts.speak(text, block=should_block)
                except Exception as exc:
                    self._logger.error("TTS error: %s", exc)

    # ──────────────────────────────────────────────────────
    # Convenience shortcuts
    # ──────────────────────────────────────────────────────

    def say(self, text: str, *, block: Optional[bool] = None) -> None:
        """Dispatch as FRIDAY — spoken + logged + displayed."""

        # ensure voice output always happens
        if block is None:
            block = False

        self.dispatch("FRIDAY", text, block=block)

    def user(self, text: str) -> None:
        """Dispatch as USER — logged + displayed, NOT spoken."""
        self.dispatch("USER", text)

    def system(self, text: str) -> None:
        """Dispatch as SYSTEM — logged + displayed as italic note, NOT spoken."""
        self.dispatch("SYSTEM", text)

    def reminder(self, text: str) -> None:
        """Dispatch as REMINDER — spoken + logged + displayed."""
        self.dispatch("REMINDER", text)

    # ──────────────────────────────────────────────────────
    # TTS blocking control
    # ──────────────────────────────────────────────────────

    def set_block(self, block: bool) -> None:
        """
        Control whether TTS blocks the caller.

        set_block(True)  — use BEFORE opening the microphone so the mic
                           doesn't record Friday's own voice as a command.
        set_block(False) — use when the mic is closed / for async responses.
        """
        self._block_tts = block

    def clear_queue(self) -> None:
        """Discard pending TTS utterances (e.g. on sudden state change)."""
        if self._tts:
            try:
                self._tts.clear_queue()
            except Exception:
                pass
