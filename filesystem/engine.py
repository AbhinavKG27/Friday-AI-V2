"""
filesystem/engine.py
Handles file search, directory listing, folder creation/deletion,
and folder opening via Windows Explorer.
"""

import os
import logging
import glob
import fnmatch
import subprocess
from typing import List

from utils.config import Config
from models.command import Command, CommandResult


class FileSystemEngine:
    """
    Provides file system operations:
    - Recursive file search
    - Directory listing
    - Folder creation / deletion
    - Open folder in Explorer
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("Friday.FileSystem")
        self.search_roots: List[str] = [
            os.path.expanduser(p) for p in config.get("search_root_dirs", [os.path.expanduser("~")])
        ]
        self.max_results = 15
        self.max_depth = 6   # keep search fast on low-RAM systems

    # ================================================================== #
    # Public API
    # ================================================================== #

    def search_files(self, cmd: Command, query: str) -> CommandResult:
        """
        Search for files/folders matching query across all search roots.
        Supports partial name matching and extension filtering.
        """
        query = query.strip().lower()
        self.logger.info("Searching for: %s", query)

        # Determine if there's an extension hint
        ext_filter = None
        if " " in query:
            parts = query.rsplit(" ", 1)
            if parts[-1].startswith(".") or parts[-1] in (
                "pdf", "docx", "doc", "xlsx", "xls", "txt", "py", "mp3",
                "mp4", "jpg", "jpeg", "png", "zip", "exe", "pptx",
            ):
                ext_filter = parts[-1] if parts[-1].startswith(".") else "." + parts[-1]
                query = parts[0]

        matches = []
        for root in self.search_roots:
            if not os.path.exists(root):
                continue
            found = self._walk_search(root, query, ext_filter, self.max_depth)
            matches.extend(found)
            if len(matches) >= self.max_results:
                break

        matches = matches[:self.max_results]

        if not matches:
            return CommandResult.err(
                cmd,
                f"No files found matching \"{query}\"{' (' + ext_filter + ')' if ext_filter else ''}.\n"
                "Try a different keyword or extension."
            )

        lines = [f"📁 Found {len(matches)} result(s) for \"{query}\":"]
        for path in matches:
            lines.append(f"  • {path}")

        return CommandResult.ok(cmd, "\n".join(lines), data=matches)

    def open_folder(self, cmd: Command, path: str) -> CommandResult:
        """Open a folder in Windows Explorer."""
        expanded = os.path.expandvars(os.path.expanduser(path))
        if not os.path.exists(expanded):
            return CommandResult.err(cmd, f"Folder not found: {expanded}")
        try:
            subprocess.Popen(["explorer", expanded])
            return CommandResult.ok(cmd, f"📂 Opening folder: {expanded}")
        except Exception as e:
            return CommandResult.err(cmd, f"Couldn't open folder: {e}")

    def list_directory(self, cmd: Command, path: str) -> CommandResult:
        """List contents of a directory."""
        expanded = os.path.expandvars(os.path.expanduser(path))
        if not os.path.exists(expanded):
            return CommandResult.err(cmd, f"Directory not found: {expanded}")
        try:
            entries = sorted(os.listdir(expanded))
            if not entries:
                return CommandResult.ok(cmd, f"📂 {expanded} is empty.")
            dirs = [e for e in entries if os.path.isdir(os.path.join(expanded, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(expanded, e))]
            lines = [f"📂 Contents of {expanded} ({len(entries)} items):"]
            if dirs:
                lines.append(f"\n  Folders ({len(dirs)}):")
                for d in dirs[:20]:
                    lines.append(f"    📁 {d}")
            if files:
                lines.append(f"\n  Files ({len(files)}):")
                for f in files[:20]:
                    lines.append(f"    📄 {f}")
            if len(entries) > 40:
                lines.append(f"\n  … and {len(entries) - 40} more items.")
            return CommandResult.ok(cmd, "\n".join(lines))
        except PermissionError:
            return CommandResult.err(cmd, f"Permission denied: {expanded}")
        except Exception as e:
            return CommandResult.err(cmd, f"Could not list directory: {e}")

    def create_folder(self, cmd: Command, name: str) -> CommandResult:
        """Create a new folder on the Desktop or given path."""
        # If absolute path given, use it; otherwise create on Desktop
        if os.path.isabs(name):
            path = name
        else:
            desktop = os.path.expanduser("~\\Desktop")
            path = os.path.join(desktop, name)
        try:
            os.makedirs(path, exist_ok=False)
            return CommandResult.ok(cmd, f"✅ Folder created: {path}")
        except FileExistsError:
            return CommandResult.err(cmd, f"Folder already exists: {path}")
        except Exception as e:
            return CommandResult.err(cmd, f"Could not create folder: {e}")

    def delete_item(self, cmd: Command, name: str) -> CommandResult:
        """Delete a file or empty folder (DOES NOT use recycle bin for safety)."""
        # First try to find the item
        if os.path.exists(name):
            target = name
        else:
            # Search for it
            for root in self.search_roots:
                found = self._walk_search(root, name, None, 4)
                if found:
                    target = found[0]
                    break
            else:
                return CommandResult.err(cmd, f"Could not find '{name}' to delete.")

        try:
            if os.path.isfile(target):
                os.remove(target)
                return CommandResult.ok(cmd, f"🗑️ Deleted file: {target}")
            elif os.path.isdir(target):
                os.rmdir(target)   # only empty dirs for safety
                return CommandResult.ok(cmd, f"🗑️ Deleted folder: {target}")
        except OSError as e:
            return CommandResult.err(cmd, f"Delete failed: {e}")

    # ================================================================== #
    # Internal helpers
    # ================================================================== #

    def _walk_search(
        self,
        root: str,
        query: str,
        ext_filter: str | None,
        max_depth: int,
        _depth: int = 0,
    ) -> List[str]:
        results = []
        if _depth > max_depth:
            return results
        try:
            with os.scandir(root) as it:
                for entry in it:
                    name_lower = entry.name.lower()
                    # Skip hidden / system dirs for performance
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.startswith(".") or entry.name in (
                            "Windows", "System32", "$Recycle.Bin",
                            "node_modules", "__pycache__",
                        ):
                            continue
                        if query in name_lower:
                            if ext_filter is None:
                                results.append(entry.path)
                        sub = self._walk_search(entry.path, query, ext_filter, max_depth, _depth + 1)
                        results.extend(sub)
                    elif entry.is_file(follow_symlinks=False):
                        if ext_filter:
                            if query in name_lower and name_lower.endswith(ext_filter):
                                results.append(entry.path)
                        else:
                            if query in name_lower:
                                results.append(entry.path)
                    if len(results) >= self.max_results:
                        break
        except PermissionError:
            pass
        except Exception as e:
            self.logger.debug("Walk error at %s: %s", root, e)
        return results
