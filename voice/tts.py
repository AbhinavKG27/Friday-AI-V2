"""
voice/tts.py
Text-to-Speech engine for Friday.
Uses pyttsx3 (offline, no internet required).
Falls back gracefully when unavailable.
"""

import logging
import threading
import queue
from typing import Optional, Callable


class TextToSpeech:
    """
    Offline TTS using pyttsx3.
    Runs speech synthesis in a dedicated thread to prevent blocking the GUI
    or the conversation state machine.

    Usage:
        tts = TextToSpeech()
        tts.speak("Hello, how can I help you?")
        tts.speak("Opening Chrome now.", block=True)  # wait until done
    """

    def __init__(
        self,
        rate: int = 175,
        volume: float = 0.95,
        voice_gender: str = "female",
        on_start: Optional[Callable[[str], None]] = None,
        on_finish: Optional[Callable[[], None]] = None,
    ):
        self.logger = logging.getLogger("Friday.TTS")
        self.rate = rate
        self.volume = volume
        self.voice_gender = voice_gender
        self.on_start = on_start
        self.on_finish = on_finish

        self._engine = None
        self._available = False
        self._speech_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._init_engine()

    # ------------------------------------------------------------------ #
    # Initialisation
    # ------------------------------------------------------------------ #

    def _init_engine(self):
        try:
            import pyttsx3
            self._pyttsx3 = pyttsx3
            self._available = True
            self.logger.info("pyttsx3 TTS engine available")
            self._start_worker()
        except ImportError:
            self.logger.warning(
                "pyttsx3 not installed – TTS disabled. Run: pip install pyttsx3"
            )

    def _start_worker(self):
        """Dedicated thread for TTS (pyttsx3 must run on the same thread it was created on)."""
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="Friday-TTS"
        )
        self._worker_thread.start()

    def _worker_loop(self):
        """TTS worker: creates engine, then processes the speech queue."""
        try:
            engine = self._pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)

            # Select voice by gender preference
            voices = engine.getProperty("voices")
            selected = None
            for v in voices:
                name_lower = v.name.lower() if v.name else ""
                if self.voice_gender == "female" and any(
                    w in name_lower for w in ["zira", "female", "woman", "helen", "eva", "susan"]
                ):
                    selected = v.id
                    break
                elif self.voice_gender == "male" and any(
                    w in name_lower for w in ["david", "male", "man", "mark", "george", "james"]
                ):
                    selected = v.id
                    break
            if selected:
                engine.setProperty("voice", selected)
            elif voices:
                engine.setProperty("voice", voices[0].id)

            self.logger.info(
                "TTS voice: %s",
                engine.getProperty("voice"),
            )

            while not self._stop_event.is_set():
                try:
                    text, done_event = self._speech_queue.get(timeout=0.3)
                    if text is None:  # sentinel
                        break
                    if self.on_start:
                        self.on_start(text)
                    engine.say(text)
                    engine.runAndWait()
                    if self.on_finish:
                        self.on_finish()
                    if done_event:
                        done_event.set()
                    self._speech_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.error("TTS speak error: %s", e)

            engine.stop()
        except Exception as e:
            self.logger.error("TTS worker crashed: %s", e)
            self._available = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._available

    def speak(self, text: str, block: bool = False):
        """
        Speak text aloud.
        - block=False (default): returns immediately, speech plays async.
        - block=True: waits until speech finishes before returning.
        """
        if not self._available:
            self.logger.debug("TTS not available, skipping: %s", text[:60])
            return

        # Clean text for speech (strip markdown symbols)
        clean = self._clean_for_speech(text)
        if not clean:
            return

        self.logger.debug("TTS speak: %s", clean[:80])

        done_event = threading.Event() if block else None
        self._speech_queue.put((clean, done_event))

        if block and done_event:
            done_event.wait(timeout=30)

    def speak_async(self, text: str):
        """Non-blocking speak (alias for clarity)."""
        self.speak(text, block=False)

    def stop(self):
        """Stop TTS and shut down worker thread."""
        self._stop_event.set()
        self._speech_queue.put((None, None))  # sentinel

    def clear_queue(self):
        """Flush any pending speech items."""
        while not self._speech_queue.empty():
            try:
                self._speech_queue.get_nowait()
                self._speech_queue.task_done()
            except queue.Empty:
                break

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Strip symbols that sound bad when spoken."""
        import re
        text = re.sub(r"[●•◈▶►→↓↑►◀▸]", "", text)
        text = re.sub(r"[📁📂📄🖥️🔊🔉🔇💻🌐🔒📸🔋💾⏰✅❌⚠️🎙️🔴⏳👂🔍]", "", text)
        text = re.sub(r"─{2,}", "", text)
        text = re.sub(r"\n+", ". ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip(" .")
