const API_BASE = "/admin-api";
const TOKEN_KEY = "flipai_admin_access_token";

const $ = (id) => document.getElementById(id);
const loginView = $("loginView");
const dashboardView = $("dashboardView");
const loginForm = $("loginForm");
const loginBtn = $("loginBtn");
const loginError = $("loginError");
const logoutBtn = $("logoutBtn");

function getToken(){ return sessionStorage.getItem(TOKEN_KEY) || ""; }
function setToken(token){ sessionStorage.setItem(TOKEN_KEY, token); }
function clearToken(){ sessionStorage.removeItem(TOKEN_KEY); }

async function api(path, options = {}){
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if(token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE}${path}`, {...options, headers});
}

function showLogin(){
  dashboardView.classList.add("hidden");
  loginView.classList.remove("hidden");
}

function showDashboard(email){
  loginView.classList.add("hidden");
  dashboardView.classList.remove("hidden");
  $("adminEmail").textContent = email;
  $("accountEmail").textContent = email;
}

async function loadSession(){
  const token = getToken();
  if(!token){ showLogin(); return; }
  try{
    const response = await api("/v1/admin/auth/me");
    if(!response.ok) throw new Error();
    const data = await response.json();
    showDashboard(data.email || "Administrator");
    await checkHealth();
  }catch{
    clearToken();
    showLogin();
  }
}

async function checkHealth(){
  try{
    const response = await fetch(`${API_BASE}/health`);
    const data = await response.json();
    $("apiStatus").textContent = response.ok && data.status === "ok" ? "Online" : "Degraded";
  }catch{
    $("apiStatus").textContent = "Offline";
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  loginBtn.disabled = true;
  loginBtn.textContent = "Signing in…";
  try{
    const response = await fetch(`${API_BASE}/v1/admin/auth/login`, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        email: $("email").value.trim(),
        password: $("password").value
      })
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail || "Sign in failed");
    setToken(data.access_token);
    $("password").value = "";
    await loadSession();
  }catch(error){
    loginError.textContent = error.message;
  }finally{
    loginBtn.disabled = false;
    loginBtn.textContent = "Sign in";
  }
});

logoutBtn.addEventListener("click", () => {
  clearToken();
  showLogin();
});

loadSession();
