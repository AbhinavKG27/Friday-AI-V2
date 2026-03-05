"""
models/command.py
Data classes for representing commands and their results.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
import uuid


@dataclass
class Command:
    raw_text: str
    normalized: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self):
        return self.raw_text


class CommandStatus:
    OK = "ok"
    ERROR = "error"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


@dataclass
class CommandResult:
    command: Command
    status: str
    message: str
    data: Optional[Any] = None

    # ------------------------------------------------------------------ #
    # Factories
    # ------------------------------------------------------------------ #

    @staticmethod
    def ok(cmd: Command, message: str, data: Any = None) -> "CommandResult":
        return CommandResult(command=cmd, status=CommandStatus.OK, message=message, data=data)

    @staticmethod
    def err(cmd: Command, message: str, data: Any = None) -> "CommandResult":
        return CommandResult(command=cmd, status=CommandStatus.ERROR, message=message, data=data)

    @staticmethod
    def unknown(cmd: Command) -> "CommandResult":
        return CommandResult(
            command=cmd,
            status=CommandStatus.UNKNOWN,
            message=(
                f"I'm not sure how to handle: \"{cmd.raw_text}\".\n"
                "Type 'what can you do' to see available commands."
            ),
        )

    # ------------------------------------------------------------------ #

    @property
    def is_ok(self) -> bool:
        return self.status == CommandStatus.OK

    def __str__(self):
        return f"[{self.status.upper()}] {self.message}"
