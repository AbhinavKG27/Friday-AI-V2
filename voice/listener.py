"""
voice/listener.py  —  Friday v4
=================================
Microphone capture + SpeechRecognition transcription.

DESIGN RULES
------------
1. listen_once_with_callbacks() is the ONLY entry point used by
   ConversationManager. It is fully asynchronous: it starts a background
   thread and returns immediately. Results arrive via callbacks:
     on_result(text)  — speech successfully recognised
     on_error(msg)    — recognition failed, timed out, or mic error
     on_status(msg)   — optional status string for the GUI

2. Thread serialisation: we join() any previous capture thread (with a
   short timeout) before starting a new one. This prevents silent
   dropped requests — the bug that caused the v2/v3 loop to stall.

3. Recognition cascade:
     a. Google Web Speech API (best accuracy, needs internet)
     b. CMU Sphinx             (fully offline, lower accuracy)
   If both fail, on_error() is called with a user-friendly message.

4. Microphone parameters are tuned for typical quiet desktop use.
   Raise energy_threshold (200–800) if you get too many false triggers,
   lower it if the mic doesn't pick up speech.
"""

import logging
import threading
from typing import Callable, Optional


class VoiceListener:
    """
    One-shot asynchronous microphone capture.

    Parameters
    ----------
    timeout      : int   seconds to wait for speech to begin (default 6)
    phrase_limit : int   maximum seconds for a single utterance (default 12)
    language     : str   BCP-47 language tag for Google STT (default "en-US")
    """

    def __init__(
        self,
        on_result:    Optional[Callable[[str], None]] = None,
        on_error:     Optional[Callable[[str], None]] = None,
        on_status:    Optional[Callable[[str], None]] = None,
        timeout:      int = 6,
        phrase_limit: int = 12,
        language:     str = "en-US",
    ):
        self._log         = logging.getLogger("Friday.Voice")
        self._def_result  = on_result or (lambda t: None)
        self._def_error   = on_error  or (lambda m: None)
        self._def_status  = on_status or (lambda m: None)
        self.timeout      = timeout
        self.phrase_limit = phrase_limit
        self.language     = language

        self._sr          = None
        self._recognizer  = None
        self._available   = False

        self._thread: Optional[threading.Thread] = None
        self._t_lock  = threading.Lock()   # serialises capture requests

        self._init()

    # ─────────────────────────────────────────────
    # Init
    # ─────────────────────────────────────────────

    def _init(self):
        try:
            import speech_recognition as sr
            self._sr         = sr
            self._recognizer = sr.Recognizer()
            # Tuned defaults — adjust energy_threshold for your microphone
            self._recognizer.energy_threshold         = 300
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.pause_threshold          = 0.8
            self._recognizer.non_speaking_duration    = 0.5
            self._available = True
            self._log.info(
                "SpeechRecognition ready  timeout=%ds  phrase_limit=%ds",
                self.timeout, self.phrase_limit,
            )
        except ImportError:
            self._log.warning(
                "speech_recognition not installed — voice input disabled. "
                "Run:  pip install SpeechRecognition pyaudio"
            )

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._available

    def listen_once(self) -> None:
        """Legacy: uses the callbacks supplied at construction time."""
        self.listen_once_with_callbacks(
            on_result=self._def_result,
            on_error=self._def_error,
            on_status=self._def_status,
        )

    def listen_once_with_callbacks(
        self,
        on_result: Callable[[str], None],
        on_error:  Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Start one capture cycle on a background thread (non-blocking).

        Waits up to 1 second for any previous capture to finish before
        starting, preventing silent dropped requests.

        Callbacks fire on the Friday-Voice thread — if they update the
        GUI they must use root.after(0, ...).
        """
        if not self._available:
            if on_error:
                on_error(
                    "Voice input unavailable — "
                    "run: pip install SpeechRecognition pyaudio"
                )
            return

        _err    = on_error  or (lambda m: None)
        _status = on_status or (lambda m: None)

        with self._t_lock:
            # Serialise: wait briefly for the previous capture to end
            if self._thread and self._thread.is_alive():
                self._log.debug("Waiting for previous capture thread…")
                self._thread.join(timeout=1.0)
                if self._thread.is_alive():
                    self._log.warning("Capture thread still alive — skipping request")
                    _err("Microphone busy — please wait a moment.")
                    return

            self._thread = threading.Thread(
                target=self._capture,
                args=(on_result, _err, _status),
                daemon=True,
                name="Friday-Voice",
            )
            self._thread.start()

    # ─────────────────────────────────────────────
    # Capture implementation
    # ─────────────────────────────────────────────

    def _capture(
        self,
        on_result: Callable[[str], None],
        on_error:  Callable[[str], None],
        on_status: Callable[[str], None],
    ) -> None:
        sr = self._sr
        on_status("🎙️ Listening…")

        try:
            with sr.Microphone() as source:
                # Brief ambient-noise calibration
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                on_status("🎙️ Speak now…")
                audio = self._recognizer.listen(
                    source,
                    timeout=self.timeout,
                    phrase_time_limit=self.phrase_limit,
                )

            on_status("⏳ Recognising…")
            text = self._recognise(audio)

            if text:
                self._log.info("Recognised: '%s'", text)
                on_status("✅ Got it")
                on_result(text)
            else:
                on_error("Could not understand the audio. Please try again.")
                on_status("❓ Unclear")

        except sr.WaitTimeoutError:
            on_error("No speech detected.")
            on_status("⏱️ Timeout")
        except sr.RequestError as exc:
            on_error(f"Speech service unavailable: {exc}")
            on_status("❌ Service error")
        except OSError as exc:
            on_error(f"Microphone error: {exc}")
            on_status("❌ Mic error")
        except Exception as exc:
            on_error(f"Voice capture error: {exc}")
            on_status("❌ Error")
            self._log.exception("Unexpected voice capture error")

    def _recognise(self, audio) -> Optional[str]:
        """
        Try Google STT first (best accuracy, internet required).
        Fall back to CMU Sphinx if Google is unreachable.
        Returns None if both fail.
        """
        sr = self._sr

        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            pass
        except sr.RequestError:
            self._log.debug("Google STT unavailable — falling back to Sphinx")

        try:
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            pass

        return None