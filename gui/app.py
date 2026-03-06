"""
gui/app.py  —  Friday v4
==========================
Tkinter GUI.

All conversation messages are received through the MessageBus via
_on_message(source, text) which is registered as the bus GUI callback.
This means the GUI is guaranteed to display EVERY message that also
appears in the log and is spoken via TTS — they all flow through one
central dispatch_message() call.

Auto-start: wake word detection and the conversation loop both start
automatically when the application launches. No button press required.

The Activate button acts as a manual override (e.g. if no microphone
or when wake word detection is disabled).
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox
import logging
from datetime import datetime

from utils.config import Config
from models.command import CommandResult
from core.conversation import ConvState


# ═══════════════════════════════════════════
# Colour palette
# ═══════════════════════════════════════════

C = {
    "bg":      "#0d0d0d",
    "panel":   "#141414",
    "sidebar": "#0a0a0a",
    "border":  "#222222",
    "accent":  "#00d4ff",
    "accent2": "#7b2fff",
    "green":   "#00ff88",
    "red":     "#ff4444",
    "yellow":  "#ffcc00",
    "orange":  "#ff8800",
    "text":    "#e8e8e8",
    "dim":     "#888888",
    "muted":   "#444444",
    "inp":     "#1a1a1a",
    "hover":   "#00b8d9",
}
F = "Consolas"

STATE_DOT = {
    ConvState.IDLE:              "#444444",
    ConvState.WAKE_LISTENING:    "#00d4ff",
    ConvState.GREETING:          "#00ff88",
    ConvState.COMMAND_LISTENING: "#ff8800",
    ConvState.PROCESSING:        "#ffcc00",
    ConvState.AWAITING_INPUT:    "#ff8800",
    ConvState.EXECUTING:         "#7b2fff",
    ConvState.CONVERSATION_END:  "#00d4ff",
}
STATE_NAME = {
    ConvState.IDLE:              "Idle",
    ConvState.WAKE_LISTENING:    "Wake Listening",
    ConvState.GREETING:          "Greeting",
    ConvState.COMMAND_LISTENING: "Listening…",
    ConvState.PROCESSING:        "Processing",
    ConvState.AWAITING_INPUT:    "Awaiting Answer",
    ConvState.EXECUTING:         "Executing",
    ConvState.CONVERSATION_END:  "Standby",
}

# Message source → chat display colour
SOURCE_TAG = {
    "FRIDAY":   ("fri",  "ok"),    # (label tag, text tag)
    "USER":     ("you",  "plain"),
    "SYSTEM":   ("sys",  "sys"),
    "REMINDER": ("rem",  "ok"),
}


class FridayApp:
    def __init__(self, assistant, config: Config):
        self.assistant = assistant
        self.config    = config
        self.logger    = logging.getLogger("Friday.GUI")

        self.root            = tk.Tk()
        self._conv_manager   = None
        self._tts            = None
        self._voice_listener = None
        self._bus            = None
        self._cmd_history    = []
        self._hist_idx       = -1
        self._hidden_standby = False

        self._setup_window()
        self._build_ui()
        self._wire_assistant()
        self._init_voice_systems()   # ← starts everything automatically
        self._show_welcome()

    # ═══════════════════════════════════════
    # Window
    # ═══════════════════════════════════════

    def _setup_window(self):
        w = self.config.get("gui_width", 960)
        h = self.config.get("gui_height", 680)
        self.root.title("Friday — AI Voice Assistant")
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(700, 500)
        self.root.configure(bg=C["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=C["sidebar"], width=230)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        # Logo
        tk.Label(sb, text="◈",       font=(F, 34),        fg=C["accent"], bg=C["sidebar"]).pack(pady=(20, 2))
        tk.Label(sb, text="FRIDAY",  font=(F, 15, "bold"), fg=C["accent"], bg=C["sidebar"]).pack()
        tk.Label(sb, text="Voice AI Assistant", font=(F, 8), fg=C["dim"],  bg=C["sidebar"]).pack(pady=(0, 10))
        self._divider(sb)

        # Status block
        sf = tk.Frame(sb, bg=C["sidebar"], pady=14)
        sf.pack(fill=tk.X, padx=14)
        tk.Label(sf, text="STATUS", font=(F, 8, "bold"), fg=C["muted"], bg=C["sidebar"]).pack(anchor=tk.W)
        dr = tk.Frame(sf, bg=C["sidebar"])
        dr.pack(anchor=tk.W)
        self._dot = tk.Label(dr, text="●", font=(F, 16), fg=C["accent"], bg=C["sidebar"])
        self._dot.pack(side=tk.LEFT)
        self._state_lbl = tk.Label(dr, text="Initialising…", font=(F, 9), fg=C["text"], bg=C["sidebar"])
        self._state_lbl.pack(side=tk.LEFT, padx=6)
        self._status_lbl = tk.Label(
            sf, text="Starting up…", font=(F, 9), fg=C["dim"],
            bg=C["sidebar"], wraplength=196, justify=tk.LEFT,
        )
        self._status_lbl.pack(anchor=tk.W, pady=(4, 0))
        self._divider(sb)

        # Wake word indicator
        self._wake_lbl = tk.Label(
            sb, text="👂 Wake Word: Checking…",
            font=(F, 8), fg=C["muted"], bg=C["sidebar"], pady=8,
        )
        self._wake_lbl.pack()
        self._divider(sb)

        # TTS indicator
        self._tts_lbl = tk.Label(
            sb, text="🔊 Voice Output: Checking…",
            font=(F, 8), fg=C["muted"], bg=C["sidebar"], pady=4,
        )
        self._tts_lbl.pack()
        self._divider(sb)

        # Quick commands
        tk.Label(sb, text="QUICK COMMANDS", font=(F, 8, "bold"),
                 fg=C["muted"], bg=C["sidebar"]).pack(anchor=tk.W, padx=14, pady=(10, 4))

        for label, cmd in [
            ("📁 Downloads",  "open downloads folder"),
            ("🖥️ System Info", "system info"),
            ("📸 Screenshot",  "take screenshot"),
            ("🔒 Lock Screen", "lock screen"),
            ("💾 Disk Space",  "disk space"),
            ("🔋 Battery",     "battery level"),
            ("📋 Reminders",   "show reminders"),
            ("❓ Help",        "what can you do"),
        ]:
            b = tk.Button(
                sb, text=label, font=(F, 9),
                fg=C["text"], bg=C["sidebar"],
                activeforeground=C["accent"], activebackground=C["panel"],
                relief=tk.FLAT, cursor="hand2", anchor=tk.W, padx=14, pady=3,
                command=lambda c=cmd: self._submit(c),
            )
            b.pack(fill=tk.X)
            self._hover(b, C["panel"], C["sidebar"])

        tk.Frame(sb, bg=C["sidebar"]).pack(fill=tk.BOTH, expand=True)
        tk.Label(sb, text="Friday v4.0", font=(F, 7), fg=C["muted"], bg=C["sidebar"], pady=8).pack()

    def _build_main(self):
        main = tk.Frame(self.root, bg=C["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        # Header
        hdr = tk.Frame(main, bg=C["panel"], height=50)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        tk.Label(hdr, text="Conversation", font=(F, 12, "bold"),
                 fg=C["text"], bg=C["panel"]).pack(side=tk.LEFT, padx=16, pady=12)

        self._voice_btn = tk.Button(
            hdr, text="🎙️ Activate", font=(F, 9, "bold"),
            fg=C["bg"], bg=C["accent"],
            activeforeground=C["bg"], activebackground=C["hover"],
            relief=tk.FLAT, cursor="hand2", padx=10, pady=4,
            command=self._manual_wake,
        )
        self._voice_btn.pack(side=tk.RIGHT, padx=8, pady=8)

        tk.Button(
            hdr, text="⊘ Clear", font=(F, 9),
            fg=C["dim"], bg=C["panel"],
            activeforeground=C["red"], activebackground=C["panel"],
            relief=tk.FLAT, cursor="hand2", pady=6, padx=10,
            command=self._clear,
        ).pack(side=tk.RIGHT)

        # Chat panel
        cf = tk.Frame(main, bg=C["bg"])
        cf.grid(row=1, column=0, sticky="nsew")
        cf.columnconfigure(0, weight=1)
        cf.rowconfigure(0, weight=1)

        self._chat = scrolledtext.ScrolledText(
            cf, bg=C["bg"], fg=C["text"], font=(F, 10),
            relief=tk.FLAT, bd=0, wrap=tk.WORD, state=tk.DISABLED,
            padx=16, pady=12, selectbackground=C["accent2"],
        )
        self._chat.grid(row=0, column=0, sticky="nsew")

        # Text tags
        for tag, fg, fnt in [
            ("ts",    C["muted"],   (F, 8)),
            ("you",   C["accent"],  (F, 9, "bold")),
            ("fri",   C["accent2"], (F, 9, "bold")),
            ("rem",   C["yellow"],  (F, 9, "bold")),
            ("sys",   C["muted"],   (F, 8, "italic")),
            ("ok",    C["green"],   (F, 10)),
            ("err",   C["red"],     (F, 10)),
            ("unk",   C["yellow"],  (F, 10)),
            ("plain", C["text"],    (F, 10)),
            ("sep",   C["muted"],   (F, 8)),
        ]:
            self._chat.tag_configure(tag, foreground=fg, font=fnt)

        # Input bar
        inp = tk.Frame(main, bg=C["panel"], pady=10)
        inp.grid(row=2, column=0, sticky="ew")
        inp.columnconfigure(1, weight=1)

        tk.Label(inp, text=">_", font=(F, 12, "bold"), fg=C["accent"],
                 bg=C["panel"]).grid(row=0, column=0, padx=(16, 8))

        self._ivar = tk.StringVar()
        self._ibox = tk.Entry(
            inp, textvariable=self._ivar, font=(F, 11),
            bg=C["inp"], fg=C["text"], insertbackground=C["accent"],
            relief=tk.FLAT, bd=6, selectbackground=C["accent2"],
        )
        self._ibox.grid(row=0, column=1, sticky="ew", ipady=6)
        self._ibox.bind("<Return>", self._on_enter)
        self._ibox.bind("<Up>",     self._hist_up)
        self._ibox.bind("<Down>",   self._hist_down)
        self._ibox.focus()

        tk.Button(
            inp, text="Send ▶", font=(F, 10, "bold"),
            fg=C["bg"], bg=C["accent"],
            activeforeground=C["bg"], activebackground=C["hover"],
            relief=tk.FLAT, cursor="hand2", padx=14, pady=6,
            command=lambda: self._on_enter(None),
        ).grid(row=0, column=2, padx=(4, 16))

        tk.Label(
            inp, text="↵ Enter  |  🎙️ Activate  |  ↑↓ history",
            font=(F, 7), fg=C["muted"], bg=C["panel"],
        ).grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(2, 0))

    # ═══════════════════════════════════════
    # Wiring
    # ═══════════════════════════════════════

    def _wire_assistant(self):
        """
        Wire the legacy response callback — suppressed when ConvMgr is
        active so messages don't appear twice.
        """
        self.assistant.set_response_callback(self._on_result_legacy)
        self.assistant.reminders.set_fire_callback(self._on_reminder)

    def _init_voice_systems(self):
        """
        Build TTS → MessageBus → VoiceListener → WakeWordDetector →
        ConversationManager and start everything.

        This is called once from __init__. Everything starts automatically.
        No button press is needed.
        """
        from voice.tts       import TextToSpeech
        from voice.listener  import VoiceListener
        from voice.wake_word import WakeWordDetector
        from core.conversation import ConversationManager
        from core.message_bus  import MessageBus

        # ── 1. TTS ────────────────────────────────────────────────────────
        self._tts = TextToSpeech(
            rate=self.config.get("tts_rate", 175),
            volume=self.config.get("tts_volume", 0.95),
            voice_gender=self.config.get("tts_voice_gender", "female"),
        )
        # Update TTS indicator
        if self._tts.is_available:
            self.root.after(0, self._tts_lbl.config,
                            {"text": "🔊 Voice Output: ACTIVE", "fg": C["green"]})
        else:
            self.root.after(0, self._tts_lbl.config,
                            {"text": "🔊 Voice Output: Disabled (install pyttsx3)",
                             "fg": C["red"]})

        # ── 2. MessageBus ─────────────────────────────────────────────────
        # gui_callback wraps _on_message in root.after for thread safety
        def gui_callback(source: str, text: str):
            self.root.after(0, self._on_message, source, text)

        self._bus = MessageBus(
            tts=self._tts,
            gui_callback=gui_callback,
        )

        # ── 3. Voice input ────────────────────────────────────────────────
        self._voice_listener = VoiceListener(
            timeout=self.config.get("speech_timeout", 6),
            phrase_limit=self.config.get("speech_phrase_limit", 12),
            language=self.config.get("voice_language", "en-US"),
        )

        # ── 4. Wake word detector ─────────────────────────────────────────
        key     = self.config.get("porcupine_access_key", "")
        kw_path = self.config.get("porcupine_keyword_path", "") or None

        wake_detector = WakeWordDetector(
            access_key=key,
            on_wake=self._on_wake_word,
            on_status=lambda m: self.root.after(0, self._set_status, m),
            keyword_path=kw_path,
        )

        if wake_detector.is_available:
            mode  = wake_detector.mode
            label = ("👂 Wake Word: Porcupine (active)" if mode == "porcupine"
                     else "👂 Wake Word: Software (active)")
            color = C["green"] if mode == "porcupine" else C["yellow"]
        else:
            label = "👂 Wake Word: Unavailable — use Activate button"
            color = C["red"]
        self.root.after(0, self._wake_lbl.config, {"text": label, "fg": color})

        # ── 5. ConversationManager ────────────────────────────────────────
        self._conv_manager = ConversationManager(
            assistant=self.assistant,
            bus=self._bus,
            voice_listener=self._voice_listener,
            wake_detector=wake_detector,
            config=self.config,
            on_state_change=self._on_state_change,
            on_status=lambda m: self.root.after(0, self._set_status, m),
            on_standby=lambda: self.root.after(0, self._enter_background_mode),
            on_reactivate=lambda: self.root.after(0, self._reactivate_window),
        )

        # Start wake detector BEFORE ConvMgr so it's ready when needed
        if wake_detector.is_available:
            wake_detector.start()

        # Start the state machine — enters WAKE_LISTENING immediately
        self._conv_manager.start()

    # ═══════════════════════════════════════
    # Event handlers
    # ═══════════════════════════════════════

    def _on_enter(self, event):
        text = self._ivar.get().strip()
        if not text:
            return
        self._ivar.set("")
        self._cmd_history.insert(0, text)
        self._hist_idx = -1
        self._submit(text)

    def _submit(self, text: str):
        """
        Submit a text command.
        Display it immediately in the GUI (instant feedback), then forward
        to the ConversationManager which routes it through the bus and
        executes it.
        Note: we display the USER message here directly so there's no
        visual delay — the ConvMgr will also dispatch it through the bus
        (which logs it) but the GUI callback will be a no-op since the
        text is already shown.
        """
        self._append_chat("USER", text)
        if self._conv_manager:
            self._conv_manager.submit_text_command(text)

    def _manual_wake(self):
        """Activate button — trigger greeting without a wake word."""
        if self._conv_manager:
            self._conv_manager.trigger_wake()
        self._voice_btn.config(text="🔴 Active…", bg=C["red"], fg=C["text"])
        self.root.after(3000, lambda: self._voice_btn.config(
            text="🎙️ Activate", bg=C["accent"], fg=C["bg"]))

    def _on_wake_word(self):
        """WakeWordDetector fires this on its own thread."""
        if self._conv_manager:
            self._conv_manager.trigger_wake()

    # ── MessageBus callback ──────────────────────────────────────────────

    def _on_message(self, source: str, text: str):
        """
        Called by MessageBus.dispatch_message() for EVERY message.
        Scheduled on the Tk main thread via root.after(0, ...).

        This is the SINGLE ENTRY POINT for all GUI chat updates.
        Every log entry will have a corresponding GUI entry here.
        """
        # Suppress USER messages that the GUI already displayed via _submit()
        # to avoid duplicates when the user types in the text box.
        # Voice-recognised USER messages come only through ConvMgr and
        # should be displayed here.
        if source == "USER":
            # If the text was submitted via text box, _submit() already showed it.
            # We check by looking at the last history entry to avoid duplicate.
            # For voice input there's no history entry so it passes through.
            if self._cmd_history and self._cmd_history[0] == text:
                return   # already shown by _submit()

        self._append_chat(source, text)

    # ── ConversationManager callbacks ────────────────────────────────────

    def _on_state_change(self, state: ConvState):
        self.root.after(0, self._apply_state_ui, state)

    def _on_result_legacy(self, result: CommandResult):
        """
        Legacy callback from FridayAssistant.process_command().
        Suppressed when ConvMgr is active — ConvMgr handles display.
        Only fires for reminders or direct calls outside the conv loop.
        """
        if getattr(self.assistant, "_conv_active", False):
            return
        tag = {"ok": "ok", "error": "err", "unknown": "unk"}.get(result.status, "ok")
        self.root.after(0, self._append_chat_raw, "FRIDAY", result.message, "fri", tag)

    def _on_reminder(self, time_str: str, message: str):
        self.root.after(0, self._fire_reminder, time_str, message)

    def _fire_reminder(self, time_str: str, message: str):
        full = f"Reminder! {message}"
        if self._bus:
            self._bus.reminder(full)
        messagebox.showinfo("Friday Reminder", f"⏰ {message}\nTime: {time_str}")

    # ── History navigation ────────────────────────────────────────────────

    def _hist_up(self, event):
        if self._cmd_history:
            self._hist_idx = min(self._hist_idx + 1, len(self._cmd_history) - 1)
            self._ivar.set(self._cmd_history[self._hist_idx])
            self._ibox.icursor(tk.END)

    def _hist_down(self, event):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._ivar.set(self._cmd_history[self._hist_idx])
        else:
            self._hist_idx = -1
            self._ivar.set("")

    # ═══════════════════════════════════════
    # UI helpers
    # ═══════════════════════════════════════

    def _apply_state_ui(self, state: ConvState):
        self._dot.config(fg=STATE_DOT.get(state, C["dim"]))
        self._state_lbl.config(text=STATE_NAME.get(state, state.name))

    def _append_chat(self, source: str, text: str):
        """Route source to correct tags and display in chat panel."""
        label_tag, text_tag = SOURCE_TAG.get(source, ("fri", "plain"))
        self._append_chat_raw(source, text, label_tag, text_tag)

    def _append_chat_raw(self, role: str, text: str, label_tag: str, text_tag: str):
        """Write one message row to the chat ScrolledText widget."""
        self._chat.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self._chat.insert(tk.END, "\n")
        self._chat.insert(tk.END, f"[{ts}] ", "ts")
        self._chat.insert(tk.END, f"{role}  ›  ", label_tag)
        self._chat.insert(tk.END, f"{text}\n", text_tag)
        self._chat.insert(tk.END, "─" * 60 + "\n", "sep")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _set_status(self, text: str):
        self._status_lbl.config(text=text)

    def _clear(self):
        self._chat.config(state=tk.NORMAL)
        self._chat.delete("1.0", tk.END)
        self._chat.config(state=tk.DISABLED)
        self._show_welcome()

    def _show_welcome(self):
        self._append_chat("FRIDAY", (
            "Friday is running.\n"
            "Say 'Hey Friday' to activate voice mode, "
            "or click 🎙️ Activate / type below.\n"
            "Say 'Friday exit' to hide the window and keep standby listening."
        ))
    
    def _enter_background_mode(self):
        """
        Hide the window but keep Friday running in wake-listening standby.
        Triggered by the voice phrase "Friday exit".
        """
        if self._hidden_standby:
            return
        self._hidden_standby = True
        self.root.withdraw()

    def _reactivate_window(self):
        """Restore the hidden window when wake-word activation happens."""
        if not self._hidden_standby:
            return
        self._hidden_standby = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _divider(self, parent):
        tk.Frame(parent, bg=C["border"], height=1).pack(fill=tk.X, padx=10)

    def _hover(self, widget, hover_bg, normal_bg):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal_bg))

    # ═══════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════

    def _on_close(self):
        self.logger.info("Friday closing")
        if self._conv_manager:
            self._conv_manager.stop()
        if self._tts:
            self._tts.stop()
        self.assistant.shutdown()
        self.root.destroy()

    def run(self):
        self.root.mainloop()