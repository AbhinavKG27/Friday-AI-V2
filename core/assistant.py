"""
core/assistant.py
Central orchestrator for Friday.  Routes commands to the appropriate engine.
"""

import logging
import threading
from typing import Callable, Optional

from utils.text_utils import normalize, contains_any, extract_after
from utils.config import Config

from automation.engine import AutomationEngine
from filesystem.engine import FileSystemEngine
from scheduler.reminder import ReminderEngine
from models.command import Command, CommandResult


class FridayAssistant:
    """
    The brain of Friday.
    - Receives raw text commands
    - Classifies and dispatches them
    - Returns structured results
    - Manages cross-module state
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("Friday.Assistant")

        # Sub-engines
        self.automation = AutomationEngine(config)
        self.filesystem = FileSystemEngine(config)
        self.reminders = ReminderEngine(config)

        # Callback for GUI updates (set by GUI layer)
        self._response_callback: Optional[Callable[[CommandResult], None]] = None
        self._status_callback: Optional[Callable[[str], None]] = None

        # Flag set by ConversationManager during active execution
        # to suppress the legacy GUI response callback (prevents duplicate display)
        self._conv_active: bool = False

        # Start reminder background thread
        self.reminders.start()

        self.logger.info("FridayAssistant initialised")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_response_callback(self, cb: Callable[[CommandResult], None]):
        self._response_callback = cb

    def set_status_callback(self, cb: Callable[[str], None]):
        self._status_callback = cb

    def process_command(self, raw_text: str) -> CommandResult:
        """Parse, route and execute a command. Returns a CommandResult."""
        self.logger.info("Processing command: %s", raw_text)
        cmd = self._parse(raw_text)
        result = self._dispatch(cmd)
        self.logger.info("Result [%s]: %s", result.status, result.message)

        # Notify GUI
        if self._response_callback:
            self._response_callback(result)

        return result

    def process_command_async(self, raw_text: str):
        """Run process_command in a background thread (non-blocking)."""
        t = threading.Thread(target=self.process_command, args=(raw_text,), daemon=True)
        t.start()

    def shutdown(self):
        """Clean shutdown of all engines."""
        self.logger.info("Shutting down engines…")
        self.reminders.stop()

    # ------------------------------------------------------------------ #
    # Internal routing
    # ------------------------------------------------------------------ #

    def _parse(self, raw: str) -> Command:
        """Build a Command object from raw text."""
        return Command(raw_text=raw, normalized=normalize(raw))

    def _dispatch(self, cmd: Command) -> CommandResult:
        """Route command to the correct engine."""
        n = cmd.normalized

        # ---- Greetings / meta ----
        if contains_any(n, ["hello", "hi friday", "hey", "good morning", "good evening"]):
            return CommandResult.ok(cmd, "Hello! How can I help you?")

        if contains_any(n, ["who are you", "what are you", "what can you do"]):
            return CommandResult.ok(cmd, self._capabilities_text())

        if contains_any(n, ["thank you", "thanks"]):
            return CommandResult.ok(cmd, "You're welcome! Let me know if you need anything else.")

        # ---- Shutdown / restart ----
        if contains_any(n, ["shutdown system", "shut down system", "power off", "turn off computer"]):
            return self.automation.shutdown_system(cmd)

        if contains_any(n, ["restart system", "reboot system", "reboot computer"]):
            return self.automation.restart_system(cmd)

        if contains_any(n, ["lock screen", "lock computer", "lock workstation"]):
            return self.automation.lock_screen(cmd)

        if contains_any(n, ["sleep", "hibernate"]):
            return self.automation.sleep_system(cmd)

        # ---- Volume / brightness ----
        if contains_any(n, ["volume up", "increase volume", "louder"]):
            return self.automation.volume_up(cmd)

        if contains_any(n, ["volume down", "decrease volume", "quieter", "lower volume"]):
            return self.automation.volume_down(cmd)

        if contains_any(n, ["mute", "unmute"]):
            return self.automation.toggle_mute(cmd)

        # ---- Open application ----
        if contains_any(n, ["open ", "launch ", "start ", "run "]):
            return self._route_open(cmd)

        # ---- File search ----
        if contains_any(n, ["find ", "search for ", "locate ", "where is "]):
            return self._route_find(cmd)

        # ---- File operations ----
        if contains_any(n, ["create folder", "make folder", "new folder"]):
            return self._route_create_folder(cmd)

        if contains_any(n, ["delete file", "remove file", "delete folder"]):
            return self._route_delete(cmd)

        if contains_any(n, ["list files", "show files", "list folder", "show folder"]):
            return self._route_list(cmd)

        # ---- Reminders ----
        if contains_any(n, ["reminder", "remind me", "set alarm", "set reminder"]):
            return self._route_reminder(cmd)

        if contains_any(n, ["show reminders", "list reminders", "my reminders"]):
            reminders = self.reminders.list_reminders()
            if not reminders:
                return CommandResult.ok(cmd, "You have no reminders set.")
            lines = [f"• [{r['time']}] {r['message']}" for r in reminders]
            return CommandResult.ok(cmd, "Your reminders:\n" + "\n".join(lines))

        if contains_any(n, ["clear reminders", "delete all reminders", "remove all reminders"]):
            self.reminders.clear_all()
            return CommandResult.ok(cmd, "All reminders cleared.")

        # ---- System info ----
        if contains_any(n, ["system info", "computer info", "cpu usage", "ram usage", "memory usage"]):
            return self.automation.get_system_info(cmd)

        if contains_any(n, ["battery", "battery level", "battery status"]):
            return self.automation.get_battery(cmd)

        if contains_any(n, ["ip address", "my ip", "network info"]):
            return self.automation.get_network_info(cmd)

        if contains_any(n, ["disk space", "disk usage", "storage"]):
            return self.automation.get_disk_info(cmd)

        # ---- Clipboard ----
        if contains_any(n, ["clear clipboard", "empty clipboard"]):
            return self.automation.clear_clipboard(cmd)

        # ---- Screenshot ----
        if contains_any(n, ["take screenshot", "screenshot", "capture screen"]):
            return self.automation.take_screenshot(cmd)

        # ---- Web ----
        if contains_any(n, ["search web", "search google", "google ", "search online"]):
            query = extract_after(cmd.raw_text, "search") or extract_after(cmd.raw_text, "google")
            return self.automation.web_search(cmd, query or "")

        if contains_any(n, ["open website", "go to website", "open url", "visit "]):
            url = extract_after(cmd.raw_text, "visit") or extract_after(cmd.raw_text, "open website")
            return self.automation.open_url(cmd, url or "")

        # ---- Notepad / write ----
        if contains_any(n, ["open notepad", "open text editor", "open editor"]):
            return self.automation.open_app(cmd, "notepad")

        # ---- Unknown ----
        return CommandResult.ok(
            cmd,
            "I don't know how to do that yet. Try saying 'what can you do' for a list of commands."
        )

    # ------------------------------------------------------------------ #
    # Sub-routers
    # ------------------------------------------------------------------ #

    def _route_open(self, cmd: Command) -> CommandResult:
        n = cmd.normalized

        # Folder shortcuts
        folder_map = {
            "downloads": "~\\Downloads",
            "documents": "~\\Documents",
            "desktop": "~\\Desktop",
            "pictures": "~\\Pictures",
            "music": "~\\Music",
            "videos": "~\\Videos",
            "appdata": "~\\AppData",
            "temp": "%TEMP%",
        }
        for key, path in folder_map.items():
            if key in n:
                return self.filesystem.open_folder(cmd, path)

        # Specific apps
        app_aliases = {
            "chrome": "chrome",
            "google chrome": "chrome",
            "firefox": "firefox",
            "edge": "msedge",
            "microsoft edge": "msedge",
            "vscode": "code",
            "vs code": "code",
            "visual studio code": "code",
            "notepad": "notepad",
            "notepad++": "notepad++",
            "word": "winword",
            "excel": "excel",
            "powerpoint": "powerpnt",
            "outlook": "outlook",
            "teams": "teams",
            "slack": "slack",
            "discord": "discord",
            "spotify": "spotify",
            "vlc": "vlc",
            "paint": "mspaint",
            "calculator": "calc",
            "task manager": "taskmgr",
            "control panel": "control",
            "settings": "ms-settings:",
            "file explorer": "explorer",
            "explorer": "explorer",
            "cmd": "cmd",
            "command prompt": "cmd",
            "powershell": "powershell",
            "terminal": "wt",
            "windows terminal": "wt",
            "snipping tool": "snippingtool",
            "camera": "microsoft.windows.camera:",
            "webcam": "microsoft.windows.camera:",
            "mail": "outlookmail:",
            "email": "outlookmail:",
            "weather": "bingweather:",
            "news": "bingnews:",
            "feedback": "windows-feedback:",
            "paint 3d": "paint3d",
            "photos": "ms-photos:",
            "calendar": "outlookcal:",
            "clock": "ms-clock:",
            "maps": "bingmaps:",
            "store": "ms-windows-store:",
        }
        for alias, exe in app_aliases.items():
            if alias in n:
                return self.automation.open_app(cmd, exe)

        # Generic: grab whatever follows "open/launch/start/run"
        for trigger in ["open", "launch", "start", "run"]:
            remainder = extract_after(cmd.raw_text, trigger)
            if remainder:
                return self.automation.open_app(cmd, remainder.strip())

        return CommandResult.err(cmd, "I'm not sure what you want me to open.")

    def _route_find(self, cmd: Command) -> CommandResult:
        for trigger in ["find", "search for", "locate", "where is"]:
            remainder = extract_after(cmd.raw_text, trigger)
            if remainder:
                return self.filesystem.search_files(cmd, remainder.strip())
        return CommandResult.err(cmd, "Please tell me what to search for.")

    def _route_create_folder(self, cmd: Command) -> CommandResult:
        for trigger in ["create folder", "make folder", "new folder"]:
            remainder = extract_after(cmd.raw_text, trigger)
            if remainder:
                return self.filesystem.create_folder(cmd, remainder.strip())
        return CommandResult.err(cmd, "Please specify the folder name.")

    def _route_delete(self, cmd: Command) -> CommandResult:
        for trigger in ["delete file", "remove file", "delete folder"]:
            remainder = extract_after(cmd.raw_text, trigger)
            if remainder:
                return self.filesystem.delete_item(cmd, remainder.strip())
        return CommandResult.err(cmd, "Please specify what to delete.")

    def _route_list(self, cmd: Command) -> CommandResult:
        for trigger in ["list files in", "show files in", "list folder", "show folder"]:
            remainder = extract_after(cmd.raw_text, trigger)
            if remainder:
                return self.filesystem.list_directory(cmd, remainder.strip())
        return self.filesystem.list_directory(cmd, "~")

    def _route_reminder(self, cmd: Command) -> CommandResult:
        from utils.text_utils import extract_time, parse_time_to_hhmm
        raw = cmd.raw_text
        time_str = extract_time(raw)
        if not time_str:
            return CommandResult.err(cmd, "I couldn't find a time in your reminder. Try: 'remind me at 7 pm to call John'.")

        hhmm = parse_time_to_hhmm(time_str)
        if not hhmm:
            return CommandResult.err(cmd, f"Couldn't parse the time '{time_str}'. Try formats like '7 pm' or '14:30'.")

        # Extract message part
        message = raw.lower()
        for word in ["remind me", "reminder", "set reminder", "set alarm"]:
            message = message.replace(word, "")
        import re
        message = re.sub(r"at\s+\d{1,2}(:\d{2})?\s*(am|pm)?", "", message, flags=re.IGNORECASE)
        message = message.strip(" to ,.")
        if not message:
            message = "Reminder"

        self.reminders.add_reminder(hhmm, message)
        return CommandResult.ok(cmd, f"✅ Reminder set for {time_str}: \"{message}\"")

    # ------------------------------------------------------------------ #

    def _capabilities_text(self) -> str:
        return (
            "I'm Friday, your offline AI desktop assistant! Here's what I can do:\n\n"
            "🖥️  Open apps: 'open chrome', 'launch VS Code', 'open calculator'\n"
            "📁  File system: 'find resume pdf', 'open downloads folder', 'list files in documents'\n"
            "⏰  Reminders: 'remind me at 7 pm to call John'\n"
            "🔊  Volume: 'volume up', 'mute', 'volume down'\n"
            "💻  System: 'system info', 'battery level', 'disk space', 'take screenshot'\n"
            "🌐  Web: 'search google for Python tutorials', 'visit github.com'\n"
            "🔒  Power: 'lock screen', 'shutdown system', 'restart system'\n"
            "📋  And much more — just ask!"
        )