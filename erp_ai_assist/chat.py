"""
erp_ai_assist/chat.py
ERPNext AI Assistant — Backend
Agentic loop between Grok (xAI) and ERPNext data via frappe_mcp tools.
"""

import json
import frappe
import requests
from frappe import _
from datetime import date


# ─── Tool registry (via MCP) ──────────────────────────────────────────────────

def _load_tools():
    """Import all tool modules so @mcp.tool() decorators register them."""
    from erp_ai_assist.mcp import mcp  # noqa — import triggers registration
    import erp_ai_assist.tools.inventory  # noqa
    import erp_ai_assist.tools.sales      # noqa
    import erp_ai_assist.tools.purchase   # noqa
    import erp_ai_assist.tools.accounts   # noqa
    import erp_ai_assist.tools.hr         # noqa
    return mcp


def _format_tools_for_grok():
    """Build the OpenAI-compatible tools list from the MCP registry."""
    mcp = _load_tools()
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in mcp._tool_registry.values()
    ]


def execute_tool(tool_name: str, tool_input: dict):
    mcp = _load_tools()
    tool = mcp._tool_registry.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return tool["fn"](**tool_input)
    except Exception as e:
        return {"error": str(e)}


# ─── API key / model helpers ──────────────────────────────────────────────────

_AI_SETTINGS_DOCTYPE = "AI Assistant Settings"


def _ai_settings_exist():
    """Return True only if the AI Assistant Settings DocType is installed."""
    return frappe.db.exists("DocType", _AI_SETTINGS_DOCTYPE)


def _get_grok_api_key():
    """Resolve API key from AI Assistant Settings first, then site config."""
    key_candidates = ["xai_api_key", "grok_api_key", "anthropic_api_key"]

    if _ai_settings_exist():
        for key in key_candidates:
            value = frappe.db.get_single_value(_AI_SETTINGS_DOCTYPE, key)
            if value:
                return value

    for key in key_candidates:
        value = frappe.conf.get(key)
        if value:
            return value

    return None


def _get_grok_model():
    """Allow model override from settings/config with a safe default."""
    if _ai_settings_exist():
        model = frappe.db.get_single_value(_AI_SETTINGS_DOCTYPE, "xai_model")
        if model:
            return model

    return frappe.conf.get("xai_model") or frappe.conf.get("grok_model") or "grok-3-latest"


# ─── Grok API call ────────────────────────────────────────────────────────────

def _normalize_history(history_list):
    """Keep only OpenAI-compatible messages from previously stored history."""
    normalized = []
    if not isinstance(history_list, list):
        return normalized

    allowed_roles = {"user", "assistant", "tool", "system"}
    for msg in history_list:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in allowed_roles:
            continue

        cleaned = {"role": role}
        for key in ["content", "tool_calls", "tool_call_id", "name"]:
            if key in msg:
                cleaned[key] = msg[key]

        if "content" not in cleaned:
            cleaned["content"] = ""
        normalized.append(cleaned)

    return normalized


def _call_grok_chat(api_key: str, model: str, system_prompt: str, messages: list):
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "tools": _format_tools_for_grok(),
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": 1024,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code >= 400:
        try:
            details = resp.json()
        except Exception:
            details = resp.text
        frappe.throw(_("Grok API request failed: {0}").format(details))

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        frappe.throw("Grok API returned no choices.")

    return choices[0].get("message", {})


# ─── Main whitelisted API method ──────────────────────────────────────────────

@frappe.whitelist()
def send_message(message: str, history: str = "[]"):
    """
    Receives a user chat message + conversation history.
    Runs the agentic Grok loop and returns the final text response.
    Called via frappe.call() from the frontend widget.
    """
    api_key = _get_grok_api_key()
    if not api_key:
        frappe.throw(
            "Grok API key not configured. Set xai_api_key in AI Assistant Settings or site config."
        )

    model = _get_grok_model()

    history_list = json.loads(history) if history else []
    messages = _normalize_history(history_list)
    messages.append({"role": "user", "content": message})

    system_prompt = (
        "You are an intelligent ERP assistant embedded in an ERPNext system. "
        "You help the user quickly analyse their business data — stock levels, "
        "sales performance, purchases, accounts receivable/payable, HR data, and more. "
        "Always be concise and business-focused. "
        "When you have tool results, summarise them clearly in plain language. "
        "Format numbers nicely (use commas for thousands, 2 decimal places for currency). "
        "If a question is ambiguous, make a reasonable assumption and state it briefly. "
        f"Today's date is {date.today().strftime('%d %B %Y')}."
    )

    # Agentic loop — max 8 iterations to handle multi-tool workflows
    for _ in range(8):
        ai_message = _call_grok_chat(
            api_key=api_key, model=model,
            system_prompt=system_prompt, messages=messages,
        )

        assistant_msg = {
            "role": "assistant",
            "content": ai_message.get("content") or "",
        }
        tool_calls = ai_message.get("tool_calls") or []
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls

        messages.append(assistant_msg)

        if tool_calls:
            for call in tool_calls:
                fn_payload = call.get("function", {})
                fn_name = fn_payload.get("name")
                raw_args = fn_payload.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}

                result = execute_tool(fn_name, parsed_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": fn_name,
                    "content": json.dumps(result),
                })
            continue

        return {"response": assistant_msg["content"] or "", "history": messages}

    return {
        "response": "I wasn't able to complete that request. Please try again.",
        "history": messages,
    }
