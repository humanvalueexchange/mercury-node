"""Typed tool registration and permission enforcement for Mercury."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Optional


class Permission(str, Enum):
    """Execution policy assigned to every registered tool."""

    READ_ONLY = "read_only"
    PREPARE_ONLY = "prepare_only"
    EXPLICIT_CONFIRMATION = "explicit_confirmation"


class ToolPermissionError(PermissionError):
    """Raised when a tool is invoked without the required approval."""


@dataclass(frozen=True)
class ToolSpec:
    """Metadata and handler for one CLI/agent tool."""

    name: str
    description: str
    permission: Permission
    handler: Callable[[Any], Any]
    input_schema: Optional[Mapping[str, Any]] = None
    prepare_handler: Optional[Callable[[Any], Any]] = None


class ToolRegistry:
    """Central registry shared by CLI commands and future agent skills."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown Mercury tool: {name}") from exc

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def execute(self, name: str, args: Any, *, confirmed: bool = False) -> Any:
        tool = self.get(name)
        if tool.permission is not Permission.READ_ONLY and not confirmed:
            raise ToolPermissionError(
                f"Tool requires approval: {tool.name} ({tool.permission.value})"
            )
        return tool.handler(args)

    def prepare(self, name: str, args: Any) -> Any:
        """Build a validated operation plan without executing the tool."""
        tool = self.get(name)
        if tool.prepare_handler is None:
            return args
        return tool.prepare_handler(args)
