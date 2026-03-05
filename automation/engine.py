"""
automation/engine.py
Handles all OS-level automation: launching apps, system commands,
volume control, screenshots, web browsing, system info.
"""

import os
import sys
import subprocess
import logging
import webbrowser
import platform
import shutil
from datetime import datetime
from typing import Optional

from utils.config import Config
from utils.text_utils import clean_app_name
from models.command import Command, CommandResult


class AutomationEngine:
    """
    Windows-focused automation engine.
    Uses subprocess, os, shutil, and standard library tools.
    Falls back gracefully when optional dependencies are missing.
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("Friday.Automation")
        self._screenshots_dir = os.path.join(
            os.path.expanduser("~"), "Pictures", "Friday Screenshots"
        )
        os.makedirs(self._screenshots_dir, exist_ok=True)

    # ================================================================== #
    # Application launching
    # ================================================================== #

    def open_app(self, cmd: Command, app_name: str) -> CommandResult:
        """Launch an application by name or executable."""
        app = clean_app_name(app_name).strip()
        self.logger.info("Launching app: %s", app)

        # Handle ms-settings: / protocol URIs
        if app.endswith(":") or app.startswith("ms-"):
            try:
                os.startfile(app)
                return CommandResult.ok(cmd, f"Opening {app}…")
            except Exception as e:
                return CommandResult.err(cmd, f"Could not open {app}: {e}")

        # Try os.startfile first (finds .exe via PATH / associations)
        try:
            os.startfile(app)
            return CommandResult.ok(cmd, f"Opening {app}…")
        except Exception:
            pass

        # Try subprocess
        try:
            subprocess.Popen(
                [app],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return CommandResult.ok(cmd, f"Launching {app}…")
        except FileNotFoundError:
            pass

        # Try with shell=True (finds things in PATH that aren't .exe)
        try:
            subprocess.Popen(
                app,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return CommandResult.ok(cmd, f"Trying to launch {app}…")
        except Exception as e:
            return CommandResult.err(cmd, f"Couldn't open '{app}'. Is it installed? ({e})")

    # ================================================================== #
    # Power management
    # ================================================================== #

    def shutdown_system(self, cmd: Command) -> CommandResult:
        self.logger.warning("System shutdown requested")
        try:
            subprocess.Popen(["shutdown", "/s", "/t", "30"], shell=True)
            return CommandResult.ok(cmd, "⚠️ System will shut down in 30 seconds. Run 'shutdown /a' to cancel.")
        except Exception as e:
            return CommandResult.err(cmd, f"Shutdown failed: {e}")

    def restart_system(self, cmd: Command) -> CommandResult:
        self.logger.warning("System restart requested")
        try:
            subprocess.Popen(["shutdown", "/r", "/t", "30"], shell=True)
            return CommandResult.ok(cmd, "⚠️ System will restart in 30 seconds. Run 'shutdown /a' to cancel.")
        except Exception as e:
            return CommandResult.err(cmd, f"Restart failed: {e}")

    def lock_screen(self, cmd: Command) -> CommandResult:
        try:
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            return CommandResult.ok(cmd, "🔒 Screen locked.")
        except Exception as e:
            return CommandResult.err(cmd, f"Lock failed: {e}")

    def sleep_system(self, cmd: Command) -> CommandResult:
        try:
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            return CommandResult.ok(cmd, "💤 Going to sleep…")
        except Exception as e:
            return CommandResult.err(cmd, f"Sleep failed: {e}")

    # ================================================================== #
    # Volume control
    # ================================================================== #

    def volume_up(self, cmd: Command) -> CommandResult:
        return self._send_media_key(cmd, 0xAF, "Volume increased 🔊")

    def volume_down(self, cmd: Command) -> CommandResult:
        return self._send_media_key(cmd, 0xAE, "Volume decreased 🔉")

    def toggle_mute(self, cmd: Command) -> CommandResult:
        return self._send_media_key(cmd, 0xAD, "Mute toggled 🔇")

    def _send_media_key(self, cmd: Command, vk_code: int, message: str) -> CommandResult:
        """Send a virtual key press using ctypes (Windows only)."""
        try:
            import ctypes
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            return CommandResult.ok(cmd, message)
        except Exception as e:
            return CommandResult.err(cmd, f"Key event failed: {e}")

    # ================================================================== #
    # System information
    # ================================================================== #

    def get_system_info(self, cmd: Command) -> CommandResult:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            info = (
                f"💻 System Information\n"
                f"  OS       : {platform.system()} {platform.release()}\n"
                f"  CPU      : {cpu:.1f}% used\n"
                f"  RAM      : {mem.used / 1e9:.1f} GB used / {mem.total / 1e9:.1f} GB total ({mem.percent:.0f}%)\n"
                f"  Python   : {sys.version.split()[0]}"
            )
            return CommandResult.ok(cmd, info)
        except ImportError:
            # Fallback without psutil
            info = (
                f"💻 System Information\n"
                f"  OS     : {platform.system()} {platform.release()}\n"
                f"  Python : {sys.version.split()[0]}\n"
                f"  (Install psutil for CPU/RAM stats)"
            )
            return CommandResult.ok(cmd, info)

    def get_battery(self, cmd: Command) -> CommandResult:
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt is None:
                return CommandResult.ok(cmd, "🔌 No battery detected (desktop system).")
            plug = "⚡ Plugged in" if batt.power_plugged else "🔋 On battery"
            return CommandResult.ok(cmd, f"Battery: {batt.percent:.0f}% – {plug}")
        except ImportError:
            return CommandResult.err(cmd, "psutil not installed. Run: pip install psutil")

    def get_disk_info(self, cmd: Command) -> CommandResult:
        try:
            import psutil
            parts = psutil.disk_partitions()
            lines = ["💾 Disk Usage:"]
            for p in parts:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    lines.append(
                        f"  {p.device} → {usage.used/1e9:.1f} GB used / {usage.total/1e9:.1f} GB ({usage.percent:.0f}%)"
                    )
                except PermissionError:
                    pass
            return CommandResult.ok(cmd, "\n".join(lines))
        except ImportError:
            total, used, free = shutil.disk_usage(os.path.expanduser("~"))
            info = (
                f"💾 Disk (home drive):\n"
                f"  Total : {total/1e9:.1f} GB\n"
                f"  Used  : {used/1e9:.1f} GB\n"
                f"  Free  : {free/1e9:.1f} GB"
            )
            return CommandResult.ok(cmd, info)

    def get_network_info(self, cmd: Command) -> CommandResult:
        import socket
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            return CommandResult.ok(cmd, f"🌐 Hostname: {hostname}\n   Local IP : {ip}")
        except Exception as e:
            return CommandResult.err(cmd, f"Network info failed: {e}")

    # ================================================================== #
    # Screenshot
    # ================================================================== #

    def take_screenshot(self, cmd: Command) -> CommandResult:
        try:
            from PIL import ImageGrab
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self._screenshots_dir, f"friday_screenshot_{ts}.png")
            img = ImageGrab.grab()
            img.save(path)
            return CommandResult.ok(cmd, f"📸 Screenshot saved to:\n{path}")
        except ImportError:
            # Fallback: use Windows Snipping Tool
            subprocess.Popen(["snippingtool"], shell=True)
            return CommandResult.ok(cmd, "Opening Snipping Tool (install Pillow for auto-screenshots: pip install Pillow)")
        except Exception as e:
            return CommandResult.err(cmd, f"Screenshot failed: {e}")

    # ================================================================== #
    # Web
    # ================================================================== #

    def web_search(self, cmd: Command, query: str) -> CommandResult:
        if not query:
            return CommandResult.err(cmd, "Please provide a search query.")
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return CommandResult.ok(cmd, f"🔍 Searching Google for: \"{query}\"")

    def open_url(self, cmd: Command, url: str) -> CommandResult:
        if not url:
            return CommandResult.err(cmd, "Please provide a URL.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return CommandResult.ok(cmd, f"🌐 Opening: {url}")

    # ================================================================== #
    # Clipboard
    # ================================================================== #

    def clear_clipboard(self, cmd: Command) -> CommandResult:
        try:
            import subprocess
            subprocess.run("echo.|clip", shell=True, check=True)
            return CommandResult.ok(cmd, "📋 Clipboard cleared.")
        except Exception as e:
            return CommandResult.err(cmd, f"Clipboard clear failed: {e}")
