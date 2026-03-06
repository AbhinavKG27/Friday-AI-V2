"""
core/conversation.py  —  Friday v4
=====================================
Conversation state machine.

Every output — greeting, command response, error message, exit farewell —
flows through MessageBus.dispatch() which writes to log, GUI and TTS in
one atomic call. Nothing can appear in the log without appearing in the
GUI, and nothing Friday says can be unspoken.

STATE MACHINE
─────────────
  IDLE
    │  start()
    ▼
  WAKE_LISTENING  ◄────────────────────────────────────┐
    │  wake word / Activate button                     │
    ▼                                                  │
  GREETING                                             │
    │  greeting spoken (blocking TTS)                  │
    ▼                                                  │
  COMMAND_LISTENING  ◄──────────────────────────────┐  │
    │  speech recognised                            │  │
    ▼                                               │  │
  PROCESSING                                        │  │
    │  safe cmd ──────────► EXECUTING               │  │
    │  dangerous cmd ──────► AWAITING_INPUT ─► yes ─┘  │
    │                                        ─► no ─┘  │
    ▼  (after execution)                              │
  COMMAND_LISTENING (loop)                           │
    │  "friday exit" / timeout                       │
    ▼                                                │
  CONVERSATION_END ─────────────────────────────────┘

THREAD MODEL
────────────
  Friday-ConvMgr  — this file's _loop()
  Friday-WakeWord — pvporcupine / software spotter
  Friday-TTS      — pyttsx3 worker queue
  Friday-Voice    — SpeechRecognition capture
  Tk main thread  — GUI (all Tk calls go via root.after)
"""

import logging
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional

from core.message_bus import MessageBus


# ═══════════════════════════════════════════════
# States
# ═══════════════════════════════════════════════

class ConvState(Enum):
    IDLE              = auto()
    WAKE_LISTENING    = auto()
    GREETING          = auto()
    COMMAND_LISTENING = auto()
    PROCESSING        = auto()
    AWAITING_INPUT    = auto()
    EXECUTING         = auto()
    CONVERSATION_END  = auto()


# ═══════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════

CONFIRMATION_TRIGGERS = [
    "delete", "remove", "shutdown", "shut down", "restart", "reboot",
    "format", "uninstall", "overwrite",
]

YES_PHRASES = [
    "yes", "yeah", "yep", "sure", "go ahead", "do it",
    "confirm", "proceed", "ok", "okay", "affirmative",
]
NO_PHRASES = [
    "no", "nope", "cancel", "abort", "don't", "negative", "back off",
]

# Any of these phrases ends the conversation and returns to standby
EXIT_PHRASES = [
    "friday exit", "exit friday", "goodbye friday", "bye friday",
    "stop listening", "that's all", "that is all", "dismiss",
]

# Artefacts from wake-word audio bleed — drop without responding
IGNORE_PHRASES = {
    "hey friday", "hi friday", "hello friday", "ok friday", "okay friday",
    "hey", "hi", "hello", "friday", "",
}

COMMAND_LISTEN_TIMEOUT  = 12   # s — no speech at all → return to standby
FOLLOWUP_LISTEN_TIMEOUT = 14   # s — no answer to confirmation → cancel
MAX_FAILURES            =  3   # consecutive recognition failures → standby


# ═══════════════════════════════════════════════
# ConversationManager
# ═══════════════════════════════════════════════

class ConversationManager:
    """
    Drives the full voice-interaction loop.

    All output goes through the MessageBus — never directly to TTS or GUI.

    Parameters
    ----------
    assistant       : FridayAssistant
    bus             : MessageBus
    voice_listener  : VoiceListener
    wake_detector   : WakeWordDetector | None
    config          : Config
    on_state_change : Callable[[ConvState], None]  — GUI state indicator
    on_status       : Callable[[str], None]        — GUI status text
    """

    def __init__(
        self,
        assistant,
        bus:             MessageBus,
        voice_listener,
        wake_detector,
        config,
        on_state_change: Optional[Callable[[ConvState], None]] = None,
        on_status:       Optional[Callable[[str], None]]       = None,
    ):
        self._log    = logging.getLogger("Friday.Conversation")
        self.asst    = assistant
        self.bus     = bus
        self.voice   = voice_listener
        self.wake    = wake_detector
        self.cfg     = config

        self._cb_state  = on_state_change or (lambda s: None)
        self._cb_status = on_status       or (lambda t: None)

        self._state  = ConvState.IDLE
        self._lock   = threading.Lock()

        self._pending_cmd: Optional[str] = None
        self._pending_ctx: Optional[str] = None

        # Speech result — written by Friday-Voice thread, read by ConvMgr
        self._speech_text:  Optional[str] = None
        self._speech_error: Optional[str] = None
        self._speech_evt    = threading.Event()

        self._fail_count  = 0
        self._running     = False
        self._thread: Optional[threading.Thread] = None

    # ═══════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════

    def start(self):
        """Start the state machine — enters WAKE_LISTENING immediately."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="Friday-ConvMgr"
        )
        self._thread.start()
        self._log.info("ConversationManager started")

    def stop(self):
        """Graceful shutdown."""
        self._running = False
        self._speech_evt.set()
        self._log.info("ConversationManager stopped")

    def trigger_wake(self):
        """
        Called by WakeWordDetector or the GUI Activate button.
        Only acts when the system is in a true idle/standby state.
        """
        with self._lock:
            if self._state in (
                ConvState.WAKE_LISTENING,
                ConvState.IDLE,
                ConvState.CONVERSATION_END,
            ):
                self._log.info("Wake triggered")
                self._set_state(ConvState.GREETING)
                self._speech_evt.set()   # unblock _state_wake_listening()

    def submit_text_command(self, text: str):
        """
        Inject a text command from the GUI input box.
        Can be called in any state — skips the greeting.
        Note: the GUI already rendered the user message in the chat box;
        we only pass it to the state machine for execution here.
        """
        text = text.strip()
        if not text:
            return

        with self._lock:
            curr = self._state

        # Wake from standby — jump straight to COMMAND_LISTENING (no greeting)
        if curr in (ConvState.WAKE_LISTENING, ConvState.IDLE, ConvState.CONVERSATION_END):
            self._set_state(ConvState.COMMAND_LISTENING)

        # Inject into the speech slot so the current state picks it up
        self._speech_text  = text
        self._speech_error = None
        self._speech_evt.set()

    # ═══════════════════════════════════════════
    # State machine loop
    # ═══════════════════════════════════════════

    def _loop(self):
        self._set_state(ConvState.WAKE_LISTENING)
        self._cb_status("👂 Listening for 'Hey Friday'…")

        while self._running:
            s = self._state
            if   s == ConvState.WAKE_LISTENING:    self._state_wake_listening()
            elif s == ConvState.GREETING:           self._state_greeting()
            elif s == ConvState.COMMAND_LISTENING:  self._state_command_listening()
            elif s == ConvState.PROCESSING:         self._state_processing()
            elif s == ConvState.AWAITING_INPUT:     self._state_awaiting_input()
            elif s == ConvState.EXECUTING:          time.sleep(0.05)
            elif s == ConvState.CONVERSATION_END:   self._state_end()
            else:                                   time.sleep(0.1)

    # ═══════════════════════════════════════════
    # State handlers
    # ═══════════════════════════════════════════

    def _state_wake_listening(self):
        """
        Standby. Parks with near-zero CPU until WakeWordDetector fires
        trigger_wake() which sets state→GREETING and fires _speech_evt.
        """
        self._speech_evt.clear()
        self._speech_evt.wait(timeout=1.0)

    def _state_greeting(self):
        """
        Respond to wake word.
        TTS is BLOCKING: mic must NOT open while Friday is still speaking
        or it will hear its own voice as a command.
        """
        self._fail_count = 0
        self.bus.set_block(True)
        self.bus.say("Hey there. How can I help you?")
        # After greeting finishes, use non-blocking TTS for responses
        self.bus.set_block(False)
        self._cb_status("🎙️ Listening for your command…")
        self._set_state(ConvState.COMMAND_LISTENING)

    def _state_command_listening(self):
        """
        Open mic, wait for one command.

        After a successful command is executed, this state is re-entered
        automatically — the conversation CONTINUES until:
          • user says an exit phrase → _state_do_exit()
          • COMMAND_LISTEN_TIMEOUT seconds of silence → standby
          • MAX_FAILURES consecutive recognition errors → standby
        """
        self._reset_speech()
        self._cb_status("🎙️ Listening… (say 'Friday exit' to stop)")

        # Start microphone capture on background thread
        self._open_mic()

        # Block until voice thread delivers a result (or timeout)
        got = self._speech_evt.wait(timeout=COMMAND_LISTEN_TIMEOUT)

        # ── Hard timeout: no audio activity at all ────────────────────
        if not got or (self._speech_text is None and self._speech_error is None):
            self.bus.set_block(False)
            self.bus.say(
                "I haven't heard anything for a while. Going back to standby. "
                "Say Hey Friday to wake me."
            )
            self._set_state(ConvState.CONVERSATION_END)
            return

        # ── Speech recognition failed ─────────────────────────────────
        if self._speech_error and self._speech_text is None:
            self._fail_count += 1
            self._log.warning("Recognition failure #%d: %s", self._fail_count, self._speech_error)

            if self._fail_count >= MAX_FAILURES:
                self.bus.set_block(False)
                self.bus.say(
                    "I'm having trouble hearing you. Going back to standby."
                )
                self._set_state(ConvState.CONVERSATION_END)
            else:
                # Retry — speak error then loop back to COMMAND_LISTENING
                self.bus.set_block(True)
                self.bus.say("I didn't catch that. Please try again.")
                self.bus.set_block(False)
                # State stays COMMAND_LISTENING — loop repeats
            return

        # ── Good speech received ──────────────────────────────────────
        self._fail_count = 0
        text = self._speech_text.strip()
        self._log.info("Command heard: '%s'", text)

        # Drop wake-word audio bleed silently
        if text.lower() in IGNORE_PHRASES:
            self._log.debug("Ignoring artefact: '%s'", text)
            return  # stay in COMMAND_LISTENING

        # Route user speech through the bus (logged + displayed, not spoken)
        self.bus.user(text)

        # Check for exit phrase
        if self._is_exit(text):
            self._state_do_exit()
            return

        # Move to processing
        with self._lock:
            self._pending_cmd = text
            self._set_state(ConvState.PROCESSING)

    def _state_processing(self):
        """Route command: ask for confirmation if dangerous, else execute."""
        cmd = self._pending_cmd
        if not cmd:
            self._set_state(ConvState.COMMAND_LISTENING)
            return

        self._cb_status(f"⏳ Processing: {cmd[:50]}…")

        if self._needs_confirm(cmd):
            self.bus.set_block(True)
            self.bus.say("This action requires confirmation. Should I go ahead?")
            self.bus.set_block(False)
            with self._lock:
                self._pending_ctx = "confirm"
                self._set_state(ConvState.AWAITING_INPUT)
        else:
            self._execute(cmd)

    def _state_awaiting_input(self):
        """Wait for a yes/no confirmation answer."""
        self._reset_speech()
        self._cb_status("🎙️ Waiting for your answer…")
        self._open_mic()

        got = self._speech_evt.wait(timeout=FOLLOWUP_LISTEN_TIMEOUT)

        if not got or self._speech_text is None:
            self.bus.set_block(False)
            self.bus.say("I didn't hear an answer. Cancelling.")
            with self._lock:
                self._pending_cmd = None
                self._pending_ctx = None
                self._set_state(ConvState.COMMAND_LISTENING)
            return

        answer = self._speech_text.strip()
        self.bus.user(answer)
        self._log.info("Confirmation answer: '%s'", answer)

        if self._pending_ctx == "confirm":
            if self._is_yes(answer):
                self.bus.set_block(True)
                self.bus.say("Got it, executing now.")
                self.bus.set_block(False)
                self._execute(self._pending_cmd)
            elif self._is_no(answer):
                self.bus.set_block(False)
                self.bus.say("Understood, cancelling that action.")
                with self._lock:
                    self._pending_cmd = None
                    self._pending_ctx = None
                    self._set_state(ConvState.COMMAND_LISTENING)
            else:
                self.bus.set_block(True)
                self.bus.say("Sorry, please say yes or no.")
                self.bus.set_block(False)
                # Stay in AWAITING_INPUT — loop re-enters
        else:
            combined = f"{self._pending_cmd} {answer}"
            self._pending_cmd = combined
            self._pending_ctx = None
            self._execute(combined)

    def _state_end(self):
        """Transition from CONVERSATION_END back to WAKE_LISTENING."""
        self._cb_status("👂 Listening for 'Hey Friday'…")
        self._set_state(ConvState.WAKE_LISTENING)

    # ═══════════════════════════════════════════
    # Command execution
    # ═══════════════════════════════════════════

    def _execute(self, cmd_text: str):
        """
        Run command via FridayAssistant and dispatch the response.

        assistant._conv_active = True suppresses the legacy GUI callback
        so the response never appears twice in the chat window.

        CRITICAL: After execution we return to COMMAND_LISTENING, not to
        standby. The conversation continues until the user exits.
        """
        self._set_state(ConvState.EXECUTING)
        self._cb_status("⚙️ Executing…")

        try:
            self.asst._conv_active = True
            result = self.asst.process_command(cmd_text)
            response = result.message

            # Single dispatch call → log + GUI display + TTS voice
            self.bus.set_block(False)
            self.bus.say(response)

        except Exception as exc:
            self._log.error("Execute error for '%s': %s", cmd_text, exc, exc_info=True)
            self.bus.set_block(False)
            self.bus.say("Something went wrong. Please try a different command.")

        finally:
            self.asst._conv_active = False
            with self._lock:
                self._pending_cmd = None
                self._pending_ctx = None
                # *** Return to COMMAND_LISTENING — conversation continues ***
                self._set_state(ConvState.COMMAND_LISTENING)
            self._cb_status("🎙️ What else can I do? (say 'Friday exit' to stop)")

    # ═══════════════════════════════════════════
    # Exit
    # ═══════════════════════════════════════════

    def _state_do_exit(self):
        self.bus.set_block(False)
        self.bus.say("Going back to standby. Say 'Hey Friday' whenever you need me.")
        self._cb_status("👂 Listening for 'Hey Friday'…")
        with self._lock:
            self._pending_cmd = None
            self._pending_ctx = None
            self._set_state(ConvState.CONVERSATION_END)

    # ═══════════════════════════════════════════
    # Voice capture helpers
    # ═══════════════════════════════════════════

    def _reset_speech(self):
        self._speech_text  = None
        self._speech_error = None
        self._speech_evt.clear()

    def _open_mic(self):
        """
        Start one capture cycle on the Friday-Voice thread.
        Results land in _on_voice_ok / _on_voice_err.
        If voice is unavailable, the GUI text box is the fallback.
        """
        if self.voice and self.voice.is_available:
            self.voice.listen_once_with_callbacks(
                on_result=self._on_voice_ok,
                on_error=self._on_voice_err,
            )

    def _on_voice_ok(self, text: str):
        """Called by Friday-Voice thread — recognition succeeded."""
        self._speech_text  = text
        self._speech_error = None
        self._speech_evt.set()

    def _on_voice_err(self, error: str):
        """Called by Friday-Voice thread — recognition failed / timed out."""
        self._speech_error = error
        self._speech_text  = None
        self._speech_evt.set()

    # ═══════════════════════════════════════════
    # State helper
    # ═══════════════════════════════════════════

    def _set_state(self, new: ConvState):
        old = self._state
        self._state = new
        if old != new:
            self._log.info("State: %s → %s", old.name, new.name)
            self._cb_state(new)

    @property
    def state(self) -> ConvState:
        return self._state

    # ═══════════════════════════════════════════
    # Phrase helpers
    # ═══════════════════════════════════════════

    @staticmethod
    def _needs_confirm(text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in CONFIRMATION_TRIGGERS)

    @staticmethod
    def _is_exit(text: str) -> bool:
        t = text.lower().strip()
        return any(p in t for p in EXIT_PHRASES)

    @staticmethod
    def _is_yes(text: str) -> bool:
        t = text.lower().strip()
        return any(t == p or t.startswith(p + " ") for p in YES_PHRASES)

    @staticmethod
    def _is_no(text: str) -> bool:
        t = text.lower().strip()
        return any(t == p or t.startswith(p + " ") for p in NO_PHRASES)