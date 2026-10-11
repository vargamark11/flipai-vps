const API_BASE = "https://api.flipai.cc";

const state = {
  accessToken: sessionStorage.getItem("flipai_access_token") || "",
  refreshToken: localStorage.getItem("flipai_refresh_token") || "",
  currentConversationId: null,
  conversations: [],
  user: null,
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

function showAuth() {
  authView.classList.remove("hidden");
  chatView.classList.add("hidden");
  userBox.classList.add("hidden");
  creditsValue.textContent = "—";
  conversationList.innerHTML = "";
  chatTitle.textContent = "FlipAI";
  statusText.textContent = "Sign in to continue";
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
    button.addEventListener("click", () => openConversation(conversation.id));
    conversationList.appendChild(button);
  }
}

function renderMessages(items = []) {
  messages.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<div><h2>How can I help?</h2><p>Start a conversation with FlipAI.</p></div>";
    messages.appendChild(empty);
    return;
  }
  for (const item of items) appendMessage(item.role, item.content);
  messages.scrollTop = messages.scrollHeight;
}

function appendMessage(role, content) {
  const row = document.createElement("div");
  row.className = `message-row ${role === "user" ? "user" : "assistant"}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = content;
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function openConversation(id) {
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
    if (state.conversations.length) {
      await openConversation(state.conversations[0].id);
    } else {
      renderMessages([]);
    }
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

loginTab.addEventListener("click", () => setAuthMode("login"));
registerTab.addEventListener("click", () => setAuthMode("register"));

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
  try {
    await createConversation();
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
  const text = messageInput.value.trim();
  if (!text) return;
  if (!state.currentConversationId) await createConversation();

  appendMessage("user", text);
  messageInput.value = "";
  messageInput.style.height = "auto";
  sendBtn.disabled = true;
  statusText.textContent = "Thinking…";

  const assistantBubble = appendMessage("assistant", "");
  try {
    const response = await apiFetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "flipai-v1",
        conversation_id: state.currentConversationId,
        messages: [{ role: "user", content: text }],
        stream: false,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    assistantBubble.textContent = data?.choices?.[0]?.message?.content || "No response.";
    await Promise.all([loadCredits(), loadConversations()]);
    const selected = state.conversations.find((c) => c.id === state.currentConversationId);
    if (selected) chatTitle.textContent = selected.title || "FlipAI";
  } catch (error) {
    assistantBubble.textContent = `Error: ${error.message}`;
  } finally {
    sendBtn.disabled = false;
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
