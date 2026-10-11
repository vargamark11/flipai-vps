const API_BASE = "/api";

const state = {
  accessToken: sessionStorage.getItem("flipai_access_token") || "",
  refreshToken: localStorage.getItem("flipai_refresh_token") || "",
  currentConversationId: null,
  conversations: [],
  user: null,
  generating: false,
};

const $ = (id) => document.getElementById(id);
const authView = $("authView");
const chatView = $("chatView");
const loginForm = $("loginForm");
const registerForm = $("registerForm");
const loginTab = $("loginTab");
const registerTab = $("registerTab");
const authError = $("authError");
const conversationList = $("conversationList");
const messages = $("messages");
const composerForm = $("composerForm");
const messageInput = $("messageInput");
const sendBtn = $("sendBtn");
const newChatBtn = $("newChatBtn");
const logoutBtn = $("logoutBtn");
const creditsValue = $("creditsValue");
const userBox = $("userBox");
const userName = $("userName");
const userEmail = $("userEmail");
const chatTitle = $("chatTitle");
const statusText = $("statusText");
const sidebar = $("sidebar");
const sidebarBackdrop = $("sidebarBackdrop");
const menuBtn = $("menuBtn");
const closeSidebarBtn = $("closeSidebarBtn");

function setAuthMode(mode) {
  const isLogin = mode === "login";
  loginForm.classList.toggle("hidden", !isLogin);
  registerForm.classList.toggle("hidden", isLogin);
  loginTab.classList.toggle("active", isLogin);
  registerTab.classList.toggle("active", !isLogin);
  authError.textContent = "";
}

function setTokens(data) {
  state.accessToken = data.access_token || "";
  state.refreshToken = data.refresh_token || state.refreshToken;
  if (state.accessToken) sessionStorage.setItem("flipai_access_token", state.accessToken);
  if (state.refreshToken) localStorage.setItem("flipai_refresh_token", state.refreshToken);
}

function clearTokens() {
  state.accessToken = "";
  state.refreshToken = "";
  sessionStorage.removeItem("flipai_access_token");
  localStorage.removeItem("flipai_refresh_token");
}

async function rawFetch(path, options = {}) {
  return fetch(`${API_BASE}${path}`, options);
}

async function refreshAccessToken() {
  if (!state.refreshToken) return false;
  const response = await rawFetch("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refreshToken }),
  });
  if (!response.ok) {
    clearTokens();
    return false;
  }
  setTokens(await response.json());
  return true;
}

async function apiFetch(path, options = {}, retry = true) {
  const headers = new Headers(options.headers || {});
  if (state.accessToken) headers.set("Authorization", `Bearer ${state.accessToken}`);
  const response = await rawFetch(path, { ...options, headers });
  if (response.status === 401 && retry && state.refreshToken) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return apiFetch(path, options, false);
  }
  return response;
}

function openSidebar() {
  sidebar.classList.add("open");
  sidebarBackdrop.classList.remove("hidden");
}

function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarBackdrop.classList.add("hidden");
}

function showAuth() {
  authView.classList.remove("hidden");
  chatView.classList.add("hidden");
  userBox.classList.add("hidden");
  creditsValue.textContent = "—";
  conversationList.innerHTML = "";
  chatTitle.textContent = "FlipAI";
  statusText.textContent = "Sign in to continue";
  closeSidebar();
}

function showChat() {
  authView.classList.add("hidden");
  chatView.classList.remove("hidden");
  userBox.classList.remove("hidden");
  statusText.textContent = "Ready";
}

async function loadMe() {
  const response = await apiFetch("/v1/account/me");
  if (!response.ok) throw new Error("Session expired");
  state.user = await response.json();
  userName.textContent = state.user.name || "User";
  userEmail.textContent = state.user.email || "";
  creditsValue.textContent = Number(state.user.credits || 0).toLocaleString();
}

async function loadCredits() {
  const response = await apiFetch("/v1/account/credits");
  if (!response.ok) return;
  const data = await response.json();
  creditsValue.textContent = Number(data.credits || 0).toLocaleString();
}

async function loadConversations() {
  const response = await apiFetch("/v1/conversations");
  if (!response.ok) return;
  const data = await response.json();
  state.conversations = data.data || [];
  renderConversations();
}

function renderConversations() {
  conversationList.innerHTML = "";
  for (const conversation of state.conversations) {
    const button = document.createElement("button");
    button.className = `conversation-item${conversation.id === state.currentConversationId ? " active" : ""}`;
    const label = document.createElement("span");
    label.textContent = conversation.title || "New chat";
    button.appendChild(label);
    button.addEventListener("click", async () => {
      await openConversation(conversation.id);
      if (window.innerWidth <= 820) closeSidebar();
    });
    conversationList.appendChild(button);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(text) {
  let safe = escapeHtml(text);
  safe = safe.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  safe = safe.replace(/(^|\s)\*([^*\n]+)\*/g, "$1<em>$2</em>");
  safe = safe.replace(/(^|\s)_([^_\n]+)_/g, "$1<em>$2</em>");
  return safe;
}

function markdownToHtml(markdown) {
  const source = String(markdown || "").replace(/\r\n/g, "\n");
  const codeBlocks = [];
  let protectedText = source.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, (_, language, code) => {
    const index = codeBlocks.length;
    codeBlocks.push({ language: language.trim(), code });
    return `\n@@FLIPAI_CODE_${index}@@\n`;
  });

  const lines = protectedText.split("\n");
  let html = "";
  let paragraph = [];
  let listType = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html += `<p>${inlineMarkdown(paragraph.join("\n")).replaceAll("\n", "<br>")}</p>`;
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) return;
    html += `</${listType}>`;
    listType = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const codeMatch = line.trim().match(/^@@FLIPAI_CODE_(\d+)@@$/);
    if (codeMatch) {
      flushParagraph();
      closeList();
      const item = codeBlocks[Number(codeMatch[1])];
      const lang = escapeHtml(item.language || "code");
      html += `<pre><div class="code-header"><span>${lang}</span><button class="copy-btn" type="button">Copy</button></div><code>${escapeHtml(item.code.replace(/\n$/, ""))}</code></pre>`;
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      html += `<blockquote>${inlineMarkdown(quote[1])}</blockquote>`;
      continue;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const wanted = unordered ? "ul" : "ol";
      if (listType !== wanted) {
        closeList();
        listType = wanted;
        html += `<${wanted}>`;
      }
      html += `<li>${inlineMarkdown((unordered || ordered)[1])}</li>`;
      continue;
    }
    closeList();
    paragraph.push(line);
  }

  flushParagraph();
  closeList();
  return html;
}

function bindCopyButtons(container) {
  container.querySelectorAll(".copy-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const code = button.closest("pre")?.querySelector("code")?.textContent || "";
      try {
        await navigator.clipboard.writeText(code);
        const original = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => (button.textContent = original), 1200);
      } catch {
        button.textContent = "Failed";
      }
    });
  });
}

function setAssistantContent(bubble, content, streaming = false) {
  bubble.classList.toggle("streaming-cursor", streaming);
  if (streaming) {
    bubble.textContent = content;
  } else {
    bubble.innerHTML = markdownToHtml(content);
    bindCopyButtons(bubble);
  }
}

function renderMessages(items = []) {
  messages.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<div><h2>How can I help?</h2><p>Ask anything and FlipAI will answer from your own VPS.</p></div>";
    messages.appendChild(empty);
    return;
  }
  for (const item of items) appendMessage(item.role, item.content);
  messages.scrollTop = messages.scrollHeight;
}

function appendMessage(role, content) {
  const empty = messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const row = document.createElement("div");
  row.className = `message-row ${role === "user" ? "user" : "assistant"}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  if (role === "assistant") setAssistantContent(bubble, content, false);
  else bubble.textContent = content;
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function openConversation(id) {
  if (state.generating) return;
  state.currentConversationId = id;
  renderConversations();
  const response = await apiFetch(`/v1/conversations/${id}`);
  if (!response.ok) return;
  const data = await response.json();
  chatTitle.textContent = data.title || "FlipAI";
  renderMessages(data.messages || []);
}

async function createConversation() {
  const response = await apiFetch("/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" }),
  });
  if (!response.ok) throw new Error("Could not create conversation");
  const data = await response.json();
  state.currentConversationId = data.id;
  chatTitle.textContent = data.title || "New chat";
  renderMessages([]);
  await loadConversations();
  return data.id;
}

async function login(email, password) {
  const response = await rawFetch("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Login failed");
  setTokens(data);
  await enterApp();
}

async function register(name, email, password) {
  const response = await rawFetch("/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Registration failed");
  setTokens(data);
  await enterApp();
}

async function enterApp() {
  try {
    await loadMe();
    showChat();
    await loadConversations();
    if (state.conversations.length) await openConversation(state.conversations[0].id);
    else renderMessages([]);
  } catch {
    clearTokens();
    showAuth();
  }
}

async function logout() {
  const refreshToken = state.refreshToken;
  clearTokens();
  state.currentConversationId = null;
  state.conversations = [];
  state.user = null;
  if (refreshToken) {
    try {
      await rawFetch("/v1/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {}
  }
  showAuth();
}

async function streamChat(text, assistantBubble) {
  const response = await apiFetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "flipai-v1",
      conversation_id: state.currentConversationId,
      messages: [{ role: "user", content: text }],
      stream: true,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    try {
      const parsed = JSON.parse(errorText);
      throw new Error(parsed.detail || "Request failed");
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(errorText || "Request failed");
      throw error;
    }
  }
  if (!response.body) throw new Error("Streaming is not supported by this browser");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantText = "";
  setAssistantContent(assistantBubble, "", true);

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const lines = part.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const event = JSON.parse(payload);
          const delta = event?.choices?.[0]?.delta?.content;
          if (delta) {
            assistantText += delta;
            setAssistantContent(assistantBubble, assistantText, true);
            messages.scrollTop = messages.scrollHeight;
          }
        } catch {}
      }
    }
  }

  setAssistantContent(assistantBubble, assistantText || "No response.", false);
  return assistantText;
}

loginTab.addEventListener("click", () => setAuthMode("login"));
registerTab.addEventListener("click", () => setAuthMode("register"));
menuBtn.addEventListener("click", openSidebar);
closeSidebarBtn.addEventListener("click", closeSidebar);
sidebarBackdrop.addEventListener("click", closeSidebar);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";
  try {
    await login($("loginEmail").value.trim(), $("loginPassword").value);
  } catch (error) {
    authError.textContent = error.message;
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";
  try {
    await register($("registerName").value.trim(), $("registerEmail").value.trim(), $("registerPassword").value);
  } catch (error) {
    authError.textContent = error.message;
  }
});

newChatBtn.addEventListener("click", async () => {
  if (state.generating) return;
  try {
    await createConversation();
    if (window.innerWidth <= 820) closeSidebar();
  } catch (error) {
    statusText.textContent = error.message;
  }
});

logoutBtn.addEventListener("click", logout);

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composerForm.requestSubmit();
  }
});

composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.generating) return;
  const text = messageInput.value.trim();
  if (!text) return;
  if (!state.currentConversationId) await createConversation();

  appendMessage("user", text);
  messageInput.value = "";
  messageInput.style.height = "auto";
  state.generating = true;
  sendBtn.disabled = true;
  newChatBtn.disabled = true;
  statusText.textContent = "Generating…";

  const assistantBubble = appendMessage("assistant", "");
  try {
    await streamChat(text, assistantBubble);
    await Promise.all([loadCredits(), loadConversations()]);
    const selected = state.conversations.find((c) => c.id === state.currentConversationId);
    if (selected) chatTitle.textContent = selected.title || "FlipAI";
  } catch (error) {
    setAssistantContent(assistantBubble, `Error: ${error.message}`, false);
  } finally {
    state.generating = false;
    sendBtn.disabled = false;
    newChatBtn.disabled = false;
    statusText.textContent = "Ready";
    messages.scrollTop = messages.scrollHeight;
  }
});

(async function boot() {
  setAuthMode("login");
  if (state.accessToken || state.refreshToken) {
    if (!state.accessToken) await refreshAccessToken();
    if (state.accessToken) return enterApp();
  }
  showAuth();
})();
