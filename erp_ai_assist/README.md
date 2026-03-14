# ERP AI Assistant — POC Setup Guide

Quick POC to demonstrate Grok-powered AI analysis on an existing ERPNext site.
The widget floats in the bottom-right corner of the ERPNext desk and answers
natural-language questions about stock, sales, orders, and more.

---

## File Structure

```
erp_ai_assist/
├── hooks.py                        ← registers JS with desk
├── erp_ai_assist/
│   └── chat.py                     ← API endpoint + tool logic
└── public/
    └── js/
        └── chat_widget.js          ← floating chat UI
```

---

## Installation (on the client's bench)

### 1. Create the custom app

```bash
cd /path/to/frappe-bench
bench new-app erp_ai_assist
# Fill in prompts — app title, description etc.
bench --site your-site.com install-app erp_ai_assist
```

### 2. Replace the generated files with these files

Copy:
- `hooks.py` → `apps/erp_ai_assist/erp_ai_assist/hooks.py`  (replace existing)
- `chat.py`  → `apps/erp_ai_assist/erp_ai_assist/chat.py`   (new file)
- `chat_widget.js` → `apps/erp_ai_assist/erp_ai_assist/public/js/chat_widget.js` (new file — create the public/js/ dirs)

### 3. Ensure Python dependencies are available

No extra SDK install is required if your bench already has `requests` (default in Frappe benches).

### 4. Set the API key

**Option A — site config (easiest for POC):**
```bash
bench --site your-site.com set-config xai_api_key "xai-..."
```

**Option B — via Frappe System Settings (single doctype):**
Create a simple single DocType called "AI Assistant Settings" with a Password field
`xai_api_key` (optionally `xai_model` as Data), then read it in `chat.py` (already coded for this).

### 5. Build assets and restart

```bash
bench build --app erp_ai_assist
bench --site your-site.com clear-cache
bench restart
```

---

## How It Works

1. **JS widget** injects a floating chat button into every desk page via `app_include_js`.
2. User types a question → `frappe.call('erp_ai_assist.chat.send_message')` fires.
3. **Python backend** sends the message + conversation history to Grok with tool schemas.
4. **Grok** decides which tool(s) to call (e.g. `get_stock_balance`, `get_sales_summary`).
5. Backend executes the tool against the live ERPNext DB (`frappe.db.*`).
6. Tool result goes back to Grok → Grok writes a plain-English answer.
7. Answer is returned to the browser and displayed in the chat panel.

---

## Tools Available (out of the box)

| Tool | What it answers |
|------|----------------|
| `get_stock_balance` | "How many [item] do we have at [warehouse]?" |
| `get_sales_summary` | "What were total sales this month / last month?" |
| `get_top_selling_items` | "What are our best selling products?" |
| `get_pending_orders` | "Show me open sales orders" / "Any pending orders for [customer]?" |
| `get_low_stock_items` | "What items are running low?" / "What needs reordering?" |

---

## Adding More Tools

1. Write a plain Python function in `chat.py`:
```python
def tool_get_overdue_invoices(days: int = 30):
    """Find unpaid invoices overdue by N days."""
    ...
    return {"invoices": rows}
```

2. Add its schema to the `TOOLS` list:
```python
{
    "name": "get_overdue_invoices",
    "description": "Find unpaid invoices that are overdue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Overdue by this many days."}
        },
        "required": []
    }
}
```

3. Register it in `TOOL_FN_MAP`:
```python
"get_overdue_invoices": tool_get_overdue_invoices,
```

That's it. Grok will automatically start using the new tool when it's relevant.

---

## Permissions Note

The chat API runs as the logged-in user. If that user doesn't have permission to read
`Sales Invoice` or `Bin`, the queries will fail. Ensure the test user has the appropriate
ERPNext roles (e.g. Stock User, Accounts User, or System Manager for demo purposes).

---

## Estimated POC Setup Time

| Step | Time |
|------|------|
| Create app + copy files | 10 min |
| Configure xAI key | 2 min |
| Set API key + bench build | 5 min |
| Test queries | 5 min |
| **Total** | **~22 minutes** |
