"""
voice/tts.py  —  Friday v4
============================
Offline text-to-speech via pyttsx3.

ARCHITECTURE
------------
pyttsx3 requires that the engine is created and driven on a single
dedicated thread (Windows SAPI COM restriction). This class spawns one
background thread ("Friday-TTS") that owns the engine for its lifetime
and processes a queue of (text, done_event) tuples.

BLOCKING MODES
--------------
speak(text, block=True)
    The caller blocks until the audio has finished playing.
    Use this BEFORE opening the microphone — otherwise Friday's own
    voice bleeds back into the mic and gets misrecognised as a command.

speak(text, block=False)  [default]
    Returns immediately. Audio plays in the background.
    Use for responses after the mic has been closed.

AVAILABILITY CHECK
------------------
TextToSpeech.is_available is False when pyttsx3 is not installed.
All speak() calls are silently no-ops in that case, so the rest of
the codebase never needs to guard against a missing TTS.
"""

import logging
import threading
import queue
import re
import unicodedata
from typing import Optional, Callable


# ─────────────────────────────────────────────────
# Text sanitiser — strips symbols that sound bad
# ─────────────────────────────────────────────────

_CLEAN = [
    (re.compile(r"[●•◈▶►→↓↑◀▸\-\*#]"),      " "),
    (re.compile(r"[\U0001F300-\U0001FAFF]"),  " "),   # emoji
    (re.compile(r"─{2,}"),                    " "),
    (re.compile(r"\n+"),                      ". "),
    (re.compile(r"\s{2,}"),                   " "),
    (re.compile(r"\s+([,\.!?])\s*"),          r"\1 "),
]

_PUNCT_TRANSLATE = str.maketrans({
    "…": "...",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
})

def _clean(text: str) -> str:
    text = text.translate(_PUNCT_TRANSLATE)
    for pat, rep in _CLEAN:
        text = pat.sub(rep, text)
    # pyttsx3/SAPI can fail on some Unicode symbols depending on voice pack.
    # Force a plain-ASCII fallback so command replies are always spoken.
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" .")


# ─────────────────────────────────────────────────
# TextToSpeech
# ─────────────────────────────────────────────────

class TextToSpeech:
    """
    Thread-safe pyttsx3 wrapper.

    Parameters
    ----------
    rate         : int    words per minute  (default 170)
    volume       : float  0.0–1.0           (default 0.95)
    voice_gender : str    "female" | "male" (default "female")
    on_start     : Callable[[str], None]  — fired when an utterance starts
    on_finish    : Callable[[], None]     — fired when an utterance ends
    """

    BLOCK_TIMEOUT = 60   # maximum seconds to wait on a blocking speak()

    def __init__(
        self,
        rate:         int   = 170,
        volume:       float = 0.95,
        voice_gender: str   = "female",
        on_start:     Optional[Callable[[str], None]] = None,
        on_finish:    Optional[Callable[[], None]]    = None,
    ):
        self._log         = logging.getLogger("Friday.TTS")
        self.rate         = rate
        self.volume       = volume
        self.voice_gender = voice_gender
        self._on_start    = on_start
        self._on_finish   = on_finish

        self._available   = False
        self._q: queue.Queue = queue.Queue()
        self._stop        = threading.Event()
        self._worker: Optional[threading.Thread] = None

        self._init()

    # ─────────────────────────────────────────────
    # Initialisation
    # ─────────────────────────────────────────────

    def _init(self):
        try:
            import pyttsx3
            self._pyttsx3   = pyttsx3
            self._available = True
            self._log.info("pyttsx3 available — starting TTS worker")
            self._worker = threading.Thread(
                target=self._run, daemon=True, name="Friday-TTS"
            )
            self._worker.start()
        except ImportError:
            self._log.warning(
                "pyttsx3 not installed — TTS disabled. "
                "Run:  pip install pyttsx3"
            )

    def _run(self):
        """Worker thread: own the pyttsx3 engine for its entire lifetime."""
        # ── Engine init ────────────────────────────────────────────────
        try:
            engine = self._pyttsx3.init()
            engine.setProperty("rate",   self.rate)
            engine.setProperty("volume", self.volume)
            self._select_voice(engine)
            self._log.info(
                "TTS ready — voice=%s  rate=%d  volume=%.2f",
                engine.getProperty("voice"), self.rate, self.volume,
            )
        except Exception as exc:
            self._log.error("TTS engine init failed: %s", exc)
            self._available = False
            return

        # ── Processing loop ────────────────────────────────────────────
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.3)
            except queue.Empty:
                continue

            text, done_evt = item
            if text is None:      # sentinel → shut down
                break

            try:
                self._log.debug("Speaking: %s", text[:100])
                if self._on_start:
                    self._on_start(text)
                engine.say(text)
                engine.runAndWait()
                if self._on_finish:
                    self._on_finish()
            except Exception as exc:
                self._log.error("TTS speak error: %s", exc)
            finally:
                if done_evt:
                    done_evt.set()
                try:
                    self._q.task_done()
                except ValueError:
                    pass

        try:
            engine.stop()
        except Exception:
            pass

    def _select_voice(self, engine):
        """Pick the best voice matching the requested gender."""
        voices = engine.getProperty("voices") or []
        female_kw = ["zira", "female", "woman", "helen", "eva",
                     "susan", "hazel", "cortana"]
        male_kw   = ["david", "male", "man", "mark", "george",
                     "james", "richard"]
        kws = female_kw if self.voice_gender == "female" else male_kw
        for v in voices:
            if any(k in (v.name or "").lower() for k in kws):
                engine.setProperty("voice", v.id)
                return
        if voices:
            engine.setProperty("voice", voices[0].id)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._available

    def speak(self, text: str, block: bool = False) -> None:
        """
        Queue text for speech synthesis.

        block=True  — blocks caller until audio finishes.
                      Required before opening the microphone.
        block=False — returns immediately; audio plays asynchronously.
        """
        if not self._available:
            return
        cleaned = _clean(text)
        if not cleaned:
            return

        done_evt = threading.Event() if block else None
        self._q.put((cleaned, done_evt))

        if block and done_evt:
            done_evt.wait(timeout=self.BLOCK_TIMEOUT)

    def speak_async(self, text: str) -> None:
        """Alias: speak(text, block=False)."""
        self.speak(text, block=False)

    def clear_queue(self) -> None:
        """Discard all pending utterances (e.g. on sudden state change)."""
        while True:
            try:
                self._q.get_nowait()
                try:
                    self._q.task_done()
                except ValueError:
                    pass
            except queue.Empty:
                break

    def stop(self) -> None:
        """Gracefully shut down the worker thread."""
        self._stop.set()
        self._q.put((None, None))   # sentinel