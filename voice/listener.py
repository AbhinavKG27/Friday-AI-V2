"""
voice/listener.py
Handles microphone capture and speech-to-text conversion.
Uses SpeechRecognition (Google offline / Sphinx fallback).

Supports both the original listen_once() API and
the new listen_once_with_callbacks() API used by ConversationManager.
"""

import logging
import threading
from typing import Callable, Optional


class VoiceListener:
    """
    Captures audio from the microphone and converts it to text.
    Runs in a background thread.

    Two interfaces:
      1. listen_once() — uses callbacks set at construction time
      2. listen_once_with_callbacks(on_result, on_error) — per-call callbacks
    """

    def __init__(
        self,
        on_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        timeout: int = 5,
        phrase_limit: int = 10,
        language: str = "en-US",
    ):
        self.logger = logging.getLogger("Friday.Voice")
        self._default_on_result = on_result or (lambda t: None)
        self._default_on_error  = on_error  or (lambda m: None)
        self._default_on_status = on_status or (lambda m: None)
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self.language = language

        self._recognizer = None
        self._available = False
        self._active_thread: Optional[threading.Thread] = None
        self._init_recognizer()

    # ------------------------------------------------------------------ #

    def _init_recognizer(self):
        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = 300
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.pause_threshold = 0.8
            self._available = True
            self.logger.info("SpeechRecognition initialised")
        except ImportError:
            self.logger.warning(
                "speech_recognition not installed. Voice input disabled. "
                "Run: pip install SpeechRecognition"
            )
            self._available = False

    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._available

    def listen_once(self):
        """Listen using the default callbacks provided at construction."""
        self.listen_once_with_callbacks(
            on_result=self._default_on_result,
            on_error=self._default_on_error,
            on_status=self._default_on_status,
        )

    def listen_once_with_callbacks(
        self,
        on_result: Callable[[str], None],
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        """Start a single capture cycle in a background thread."""
        if not self._available:
            if on_error:
                on_error("Voice input not available. Install: pip install SpeechRecognition")
            return

        if self._active_thread and self._active_thread.is_alive():
            self.logger.debug("Voice capture already in progress, skipping")
            return

        on_error  = on_error  or (lambda m: None)
        on_status = on_status or (lambda m: None)

        self._active_thread = threading.Thread(
            target=self._capture,
            args=(on_result, on_error, on_status),
            daemon=True,
            name="Friday-VoiceCapture",
        )
        self._active_thread.start()

    # ------------------------------------------------------------------ #

    def _capture(self, on_result, on_error, on_status):
        sr = self._sr
        on_status("🎙️ Listening…")
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                on_status("🎙️ Speak now…")
                audio = self._recognizer.listen(
                    source,
                    timeout=self.timeout,
                    phrase_time_limit=self.phrase_limit,
                )
            on_status("⏳ Processing speech…")
            text = self._recognise(audio)
            if text:
                self.logger.info("Recognised: %s", text)
                on_status("✅ Got it")
                on_result(text)
            else:
                on_error("Couldn't understand. Please try again.")
                on_status("Ready")
        except sr.WaitTimeoutError:
            on_error("No speech detected within timeout.")
            on_status("Ready")
        except sr.RequestError as e:
            on_error(f"Speech service error: {e}")
            on_status("Ready")
        except Exception as e:
            on_error(f"Voice error: {e}")
            on_status("Ready")

    def _recognise(self, audio) -> Optional[str]:
        sr = self._sr
        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            pass
        except sr.RequestError:
            self.logger.debug("Google Speech unavailable, trying Sphinx")
        try:
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            pass
        return None