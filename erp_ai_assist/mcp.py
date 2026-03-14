"""
erp_ai_assist/mcp.py

Lightweight MCP-compatible tool registry for ERP AI Assist.

Uses only frappe_mcp.server.tools.tool_schema (pure Python, zero pydantic)
for schema generation — safe inside Frappe's gevent WSGI workers.

The full pydantic-dependent frappe_mcp stack is imported lazily inside
handle_mcp() so it only runs when an actual MCP HTTP request arrives,
never during normal chat widget usage.
"""

from collections import OrderedDict
from inspect import cleandoc

# Local copy of frappe_mcp's tool_schema — pure Python stdlib, zero pydantic.
# Importing anything from the frappe_mcp package (even a sub-module) triggers
# frappe_mcp/__init__.py which chains into pydantic and crashes under gevent.
from erp_ai_assist.tools.tool_schema import get_descriptions, get_input_schema


class _MCP:
    """Minimal MCP-compatible tool registry with the same @mcp.tool() API."""

    def __init__(self, name: str):
        self._name = name
        self._tool_registry: OrderedDict = OrderedDict()

    def tool(
        self,
        *,
        name: str = None,
        description: str = None,
        input_schema: dict = None,
        annotations: dict = None,
        use_entire_docstring: bool = False,
    ):
        """Decorator: registers a function as a named tool with auto-generated schema."""
        def decorator(fn):
            _name = name or fn.__name__
            _description = description or cleandoc(fn.__doc__ or "")

            desc_text, arg_descriptions = get_descriptions(_description)
            if not use_entire_docstring and _description:
                _description = desc_text

            _input_schema = input_schema or get_input_schema(fn)
            for key, prop in _input_schema.get("properties", {}).items():
                if key in arg_descriptions:
                    prop["description"] = arg_descriptions[key]

            self._tool_registry[_name] = {
                "name": _name,
                "description": _description,
                "input_schema": _input_schema,
                "output_schema": None,
                "annotations": annotations,
                "fn": fn,
            }
            return fn

        return decorator


mcp = _MCP("erp-ai-assist")


def _load_tools():
    """Import all tool modules so @mcp.tool() decorators fire and register tools."""
    import erp_ai_assist.tools.inventory  # noqa
    import erp_ai_assist.tools.sales      # noqa
    import erp_ai_assist.tools.purchase   # noqa
    import erp_ai_assist.tools.accounts   # noqa
    import erp_ai_assist.tools.hr         # noqa


# ─── MCP HTTP endpoint ────────────────────────────────────────────────────────
# Importing frappe_mcp.MCP (pydantic-heavy) is deferred to request time so it
# never runs during normal chat widget usage or app initialisation.

import frappe  # noqa — available at module load inside a Frappe process


@frappe.whitelist(methods=["GET", "POST"])
def handle_mcp():
    """
    MCP HTTP endpoint compatible with Claude Desktop and any MCP client.

    Connect via:
      POST /api/method/erp_ai_assist.mcp.handle_mcp
    """
    from frappe_mcp import MCP as _FullMCP
    from werkzeug.wrappers import Response

    _load_tools()

    # Materialise a full frappe_mcp instance and mirror our registry into it
    full_mcp = _FullMCP(mcp._name)
    for tool in mcp._tool_registry.values():
        full_mcp.add_tool(tool)

    return full_mcp.handle(frappe.request, Response())
