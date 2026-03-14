/**
 * erp_ai_assist/public/js/chat_widget.js
 * Floating AI Assistant widget for ERPNext Desk
 * Injected via hooks.py → app_include_js
 */

(function () {
  "use strict";

  // ── Wait for Frappe desk to fully load ──────────────────────────────────────
  frappe.after_ajax(function () {
    setTimeout(initAssistant, 800);
  });

  // ── State ───────────────────────────────────────────────────────────────────
  let chatHistory = [];
  let isOpen = false;
  let isLoading = false;

  // ── Init ────────────────────────────────────────────────────────────────────
  function initAssistant() {
    if (document.getElementById("erp-ai-widget")) return; // already mounted
    injectStyles();
    buildWidget();
    attachEvents();
  }

  // ── Build DOM ────────────────────────────────────────────────────────────────
  function buildWidget() {
    const wrapper = document.createElement("div");
    wrapper.id = "erp-ai-widget";
    wrapper.innerHTML = `
      <!-- Floating toggle button -->
      <button id="ai-toggle-btn" title="AI Assistant">
        <svg id="ai-icon-chat" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <svg id="ai-icon-close" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        <span id="ai-badge"></span>
      </button>

      <!-- Chat panel -->
      <div id="ai-panel">
        <!-- Header -->
        <div id="ai-header">
          <div id="ai-header-left">
            <div id="ai-avatar">✦</div>
            <div>
              <div id="ai-name">ERP Assistant</div>
              <div id="ai-status">Powered by Grok</div>
            </div>
          </div>
          <button id="ai-clear-btn" title="Clear conversation">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>

        <!-- Messages area -->
        <div id="ai-messages">
          <div class="ai-welcome">
            <div class="ai-welcome-icon">✦</div>
            <p>Hello! I can help you quickly check stock levels, review sales performance, spot pending orders, and more.</p>
            <p>Try asking:</p>
            <div class="ai-suggestions">
              <button class="ai-suggestion">How much stock do we have of [item]?</button>
              <button class="ai-suggestion">Show me this month's sales summary</button>
              <button class="ai-suggestion">What are our top selling items?</button>
              <button class="ai-suggestion">Any items running low on stock?</button>
              <button class="ai-suggestion">Show pending orders</button>
            </div>
          </div>
        </div>

        <!-- Input area -->
        <div id="ai-input-area">
          <textarea
            id="ai-input"
            placeholder="Ask anything about your business data…"
            rows="1"
            maxlength="500"
          ></textarea>
          <button id="ai-send-btn" disabled>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(wrapper);
  }

  // ── Events ───────────────────────────────────────────────────────────────────
  function attachEvents() {
    // Toggle open/close
    document.getElementById("ai-toggle-btn").addEventListener("click", togglePanel);

    // Send on button click
    document.getElementById("ai-send-btn").addEventListener("click", handleSend);

    // Send on Enter (Shift+Enter = newline)
    document.getElementById("ai-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!isLoading) handleSend();
      }
    });

    // Enable/disable send button based on input
    document.getElementById("ai-input").addEventListener("input", function () {
      const hasText = this.value.trim().length > 0;
      document.getElementById("ai-send-btn").disabled = !hasText || isLoading;
      // Auto-grow textarea
      this.style.height = "auto";
      this.style.height = Math.min(this.scrollHeight, 120) + "px";
    });

    // Suggestion chips
    document.querySelectorAll(".ai-suggestion").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const input = document.getElementById("ai-input");
        input.value = this.textContent;
        input.dispatchEvent(new Event("input"));
        handleSend();
      });
    });

    // Clear button
    document.getElementById("ai-clear-btn").addEventListener("click", clearChat);
  }

  // ── Toggle panel ─────────────────────────────────────────────────────────────
  function togglePanel() {
    isOpen = !isOpen;
    const panel = document.getElementById("ai-panel");
    const iconChat = document.getElementById("ai-icon-chat");
    const iconClose = document.getElementById("ai-icon-close");
    const badge = document.getElementById("ai-badge");

    panel.classList.toggle("open", isOpen);
    iconChat.style.display = isOpen ? "none" : "block";
    iconClose.style.display = isOpen ? "block" : "none";

    if (isOpen) {
      badge.style.display = "none";
      setTimeout(() => document.getElementById("ai-input").focus(), 300);
    }
  }

  // ── Send message ─────────────────────────────────────────────────────────────
  function handleSend() {
    const input = document.getElementById("ai-input");
    const message = input.value.trim();
    if (!message || isLoading) return;

    input.value = "";
    input.style.height = "auto";
    document.getElementById("ai-send-btn").disabled = true;

    // Remove welcome screen if present
    const welcome = document.querySelector(".ai-welcome");
    if (welcome) welcome.remove();

    appendMessage("user", message);
    setLoading(true);

    frappe.call({
      method: "erp_ai_assist.chat.send_message",
      args: {
        message: message,
        history: JSON.stringify(chatHistory)
      },
      callback: function (r) {
        setLoading(false);
        if (r.message && r.message.response) {
          appendMessage("assistant", r.message.response);
          // Store full history for context continuity
          chatHistory = r.message.history || chatHistory;
          // Show badge if panel is closed
          if (!isOpen) {
            const badge = document.getElementById("ai-badge");
            badge.style.display = "block";
          }
        } else {
          appendMessage("assistant", "Sorry, something went wrong. Please try again.");
        }
      },
      error: function (err) {
        setLoading(false);
        const errMsg = (err && err.message) ? err.message : "Connection error. Please try again.";
        appendMessage("assistant", "⚠ " + errMsg, true);
      }
    });
  }

  // ── Render a message bubble ───────────────────────────────────────────────────
  function appendMessage(role, text, isError) {
    const messages = document.getElementById("ai-messages");

    const bubble = document.createElement("div");
    bubble.className = "ai-message " + role + (isError ? " error" : "");

    if (role === "assistant") {
      bubble.innerHTML = `
        <div class="ai-msg-avatar">✦</div>
        <div class="ai-msg-content">${formatMarkdown(text)}</div>
      `;
    } else {
      bubble.innerHTML = `<div class="ai-msg-content">${escapeHtml(text)}</div>`;
    }

    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
  }

  // ── Loading indicator ─────────────────────────────────────────────────────────
  function setLoading(loading) {
    isLoading = loading;
    const messages = document.getElementById("ai-messages");

    if (loading) {
      const indicator = document.createElement("div");
      indicator.id = "ai-loading";
      indicator.className = "ai-message assistant";
      indicator.innerHTML = `
        <div class="ai-msg-avatar">✦</div>
        <div class="ai-msg-content ai-typing">
          <span></span><span></span><span></span>
        </div>
      `;
      messages.appendChild(indicator);
      messages.scrollTop = messages.scrollHeight;
    } else {
      const indicator = document.getElementById("ai-loading");
      if (indicator) indicator.remove();
    }
  }

  // ── Clear chat ────────────────────────────────────────────────────────────────
  function clearChat() {
    chatHistory = [];
    const messages = document.getElementById("ai-messages");
    messages.innerHTML = `
      <div class="ai-welcome">
        <div class="ai-welcome-icon">✦</div>
        <p>Conversation cleared. How can I help you?</p>
        <div class="ai-suggestions">
          <button class="ai-suggestion">How much stock do we have of [item]?</button>
          <button class="ai-suggestion">Show me this month's sales summary</button>
          <button class="ai-suggestion">What are our top selling items?</button>
          <button class="ai-suggestion">Any items running low on stock?</button>
        </div>
      </div>
    `;
    // Re-attach suggestion events
    document.querySelectorAll(".ai-suggestion").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const input = document.getElementById("ai-input");
        input.value = this.textContent;
        input.dispatchEvent(new Event("input"));
        handleSend();
      });
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────
  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatMarkdown(text) {
    // Very lightweight markdown: bold, italic, code, lists, line breaks
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/^[-•]\s+(.+)$/gm, "<li>$1</li>")
      .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
      .replace(/\n/g, "<br>");
  }

  // ── Styles ────────────────────────────────────────────────────────────────────
  function injectStyles() {
    const style = document.createElement("style");
    style.textContent = `
      /* ── Widget wrapper ── */
      #erp-ai-widget {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      /* ── Toggle button ── */
      #ai-toggle-btn {
        width: 52px;
        height: 52px;
        border-radius: 50%;
        background: #2490ef;
        border: none;
        color: #fff;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 16px rgba(36,144,239,0.4);
        transition: transform 0.2s, box-shadow 0.2s;
        position: relative;
        margin-left: auto;
      }
      #ai-toggle-btn:hover {
        transform: scale(1.08);
        box-shadow: 0 6px 20px rgba(36,144,239,0.5);
      }
      #ai-toggle-btn svg {
        width: 22px;
        height: 22px;
        pointer-events: none;
      }
      #ai-icon-close { display: none; }

      /* Notification badge */
      #ai-badge {
        display: none;
        position: absolute;
        top: 4px;
        right: 4px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #f04b3e;
        border: 2px solid #fff;
      }

      /* ── Panel ── */
      #ai-panel {
        position: absolute;
        bottom: 64px;
        right: 0;
        width: 380px;
        height: 540px;
        background: #fff;
        border-radius: 16px;
        box-shadow: 0 8px 40px rgba(0,0,0,0.16), 0 2px 8px rgba(0,0,0,0.08);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transform: scale(0.92) translateY(10px);
        transform-origin: bottom right;
        opacity: 0;
        pointer-events: none;
        transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1), opacity 0.18s ease;
      }
      #ai-panel.open {
        transform: scale(1) translateY(0);
        opacity: 1;
        pointer-events: all;
      }

      /* ── Header ── */
      #ai-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 16px;
        background: linear-gradient(135deg, #1a7fd4, #2490ef);
        flex-shrink: 0;
      }
      #ai-header-left {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      #ai-avatar {
        width: 34px;
        height: 34px;
        background: rgba(255,255,255,0.2);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        color: #fff;
      }
      #ai-name {
        font-size: 14px;
        font-weight: 600;
        color: #fff;
        line-height: 1.2;
      }
      #ai-status {
        font-size: 11px;
        color: rgba(255,255,255,0.75);
        margin-top: 1px;
      }
      #ai-clear-btn {
        background: none;
        border: none;
        color: rgba(255,255,255,0.7);
        cursor: pointer;
        padding: 4px;
        border-radius: 6px;
        display: flex;
        transition: color 0.15s, background 0.15s;
      }
      #ai-clear-btn:hover {
        color: #fff;
        background: rgba(255,255,255,0.15);
      }
      #ai-clear-btn svg { width: 16px; height: 16px; }

      /* ── Messages ── */
      #ai-messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        scroll-behavior: smooth;
      }
      #ai-messages::-webkit-scrollbar { width: 4px; }
      #ai-messages::-webkit-scrollbar-thumb { background: #e0e0e0; border-radius: 2px; }

      /* Welcome screen */
      .ai-welcome {
        text-align: center;
        padding: 8px 4px;
        color: #6c7680;
        font-size: 13px;
        line-height: 1.6;
      }
      .ai-welcome-icon {
        font-size: 28px;
        margin-bottom: 10px;
        color: #2490ef;
      }
      .ai-welcome p { margin: 0 0 8px; }
      .ai-suggestions {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-top: 10px;
        text-align: left;
      }
      .ai-suggestion {
        background: #f5f7fa;
        border: 1px solid #e8ecf0;
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 12px;
        color: #3d5066;
        cursor: pointer;
        text-align: left;
        transition: background 0.15s, border-color 0.15s;
        line-height: 1.4;
      }
      .ai-suggestion:hover {
        background: #ebf4fd;
        border-color: #2490ef;
        color: #2490ef;
      }

      /* Message bubbles */
      .ai-message {
        display: flex;
        gap: 8px;
        max-width: 100%;
        animation: ai-fadein 0.2s ease;
      }
      @keyframes ai-fadein {
        from { opacity: 0; transform: translateY(4px); }
        to   { opacity: 1; transform: translateY(0); }
      }
      .ai-message.user {
        flex-direction: row-reverse;
      }
      .ai-msg-avatar {
        width: 28px;
        height: 28px;
        background: #ebf4fd;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        color: #2490ef;
        flex-shrink: 0;
        margin-top: 2px;
      }
      .ai-msg-content {
        background: #f5f7fa;
        border-radius: 12px 12px 12px 2px;
        padding: 9px 12px;
        font-size: 13px;
        line-height: 1.55;
        color: #2d3748;
        max-width: calc(100% - 44px);
        word-break: break-word;
      }
      .ai-message.user .ai-msg-content {
        background: #2490ef;
        color: #fff;
        border-radius: 12px 12px 2px 12px;
      }
      .ai-message.error .ai-msg-content {
        background: #fff5f5;
        color: #c53030;
        border: 1px solid #fed7d7;
      }
      .ai-msg-content code {
        background: rgba(0,0,0,0.07);
        padding: 1px 5px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 12px;
      }
      .ai-message.user .ai-msg-content code {
        background: rgba(255,255,255,0.2);
      }
      .ai-msg-content ul {
        margin: 4px 0;
        padding-left: 18px;
      }
      .ai-msg-content li { margin-bottom: 2px; }
      .ai-msg-content strong { font-weight: 600; }

      /* Typing dots */
      .ai-typing {
        display: flex;
        gap: 4px;
        align-items: center;
        padding: 12px 14px !important;
      }
      .ai-typing span {
        width: 6px;
        height: 6px;
        background: #9baec8;
        border-radius: 50%;
        animation: ai-bounce 1.3s infinite;
      }
      .ai-typing span:nth-child(2) { animation-delay: 0.16s; }
      .ai-typing span:nth-child(3) { animation-delay: 0.32s; }
      @keyframes ai-bounce {
        0%, 60%, 100% { transform: translateY(0); }
        30% { transform: translateY(-6px); }
      }

      /* ── Input area ── */
      #ai-input-area {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        padding: 10px 12px 14px;
        border-top: 1px solid #eef0f3;
        background: #fff;
        flex-shrink: 0;
      }
      #ai-input {
        flex: 1;
        border: 1.5px solid #e2e8f0;
        border-radius: 10px;
        padding: 8px 12px;
        font-size: 13px;
        resize: none;
        outline: none;
        font-family: inherit;
        color: #2d3748;
        background: #f8fafc;
        line-height: 1.45;
        transition: border-color 0.15s;
        max-height: 120px;
        overflow-y: auto;
      }
      #ai-input:focus {
        border-color: #2490ef;
        background: #fff;
      }
      #ai-input::placeholder { color: #a0aec0; }

      #ai-send-btn {
        width: 36px;
        height: 36px;
        border-radius: 10px;
        background: #2490ef;
        border: none;
        color: #fff;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: background 0.15s, transform 0.1s;
      }
      #ai-send-btn:hover:not(:disabled) {
        background: #1a7fd4;
        transform: scale(1.05);
      }
      #ai-send-btn:disabled {
        background: #cbd5e0;
        cursor: not-allowed;
        transform: none;
      }
      #ai-send-btn svg { width: 16px; height: 16px; }

      /* Dark mode support */
      @media (prefers-color-scheme: dark) {
        #ai-panel { background: #1a202c; box-shadow: 0 8px 40px rgba(0,0,0,0.4); }
        .ai-msg-content { background: #2d3748; color: #e2e8f0; }
        .ai-suggestion { background: #2d3748; border-color: #4a5568; color: #e2e8f0; }
        .ai-suggestion:hover { background: #2c4a6e; border-color: #2490ef; color: #63b3ed; }
        .ai-welcome { color: #a0aec0; }
        #ai-input { background: #2d3748; border-color: #4a5568; color: #e2e8f0; }
        #ai-input:focus { background: #2d3748; border-color: #2490ef; }
        #ai-input::placeholder { color: #718096; }
        #ai-input-area { background: #1a202c; border-color: #2d3748; }
        #ai-messages::-webkit-scrollbar-thumb { background: #4a5568; }
        .ai-msg-avatar { background: #2c4a6e; }
        .ai-msg-content code { background: rgba(255,255,255,0.1); }
      }
    `;
    document.head.appendChild(style);
  }
})();
