"""Tool definitions the model sees, and the dispatcher that runs them.

The mechanism is kept from the instructor's code: `TOOLS` holds the JSON schemas
the model sees, `HANDLERS` maps a tool name to a plain function over the database,
and `execute()` runs one tool and returns a JSON string. There are no domain tools
yet; the first read-only tools arrive with the Copilot issue (M2).

A tool is added in two places that must agree:

    TOOLS.append({"name": "x", "description": "...", "input_schema": {...,
                  "additionalProperties": False}})
    HANDLERS["x"] = lambda db, tool_input, user_id: {"...": "..."}
"""
from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session

ToolHandler = Callable[[Session, dict[str, Any], "int | None"], Any]

TOOLS: list[dict[str, Any]] = []
HANDLERS: dict[str, ToolHandler] = {}

MAX_RESULT_CHARS = 12000


def tool_names() -> set[str]:
    return {t["name"] for t in TOOLS}


def execute(name: str, tool_input: dict[str, Any], db: Session, *, user_id: int | None = None) -> str:
    """Run one tool and return its result as a JSON string for the model."""
    try:
        handler = HANDLERS.get(name)
        result = handler(db, _clean(tool_input), user_id) if handler else {"error": f"unknown tool '{name}'"}
    except Exception as exc:  # the loop must survive a bad input; the model sees the error
        result = {"error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... (truncated)"}'
    return text


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
