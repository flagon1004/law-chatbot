const API_URL = "/api/chat";
const ADMIN_VERIFY_URL = "/api/admin/verify";
const STORAGE_KEY = "law_chat_history";
const MODEL_STORAGE_KEY = "law_chat_model";
const ADMIN_PW_STORAGE_KEY = "law_chat_admin_pw";
const MAX_SESSIONS = 20;

// ── 모델 선택 ──
function getSelectedModel() {
  return localStorage.getItem(MODEL_STORAGE_KEY) || "nvidia";
}

function getAdminPassword() {
  return sessionStorage.getItem(ADMIN_PW_STORAGE_KEY) || "";
}

async function verifyAdminPassword(password) {
  try {
    const res = await fetch(ADMIN_VERIFY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.ok;
  } catch (e) {
    return false;
  }
}

async function onModelChange(value) {
  const select = document.getElementById("model-select");

  if (value !== "gemini") {
    localStorage.setItem(MODEL_STORAGE_KEY, value);
    return;
  }

  const password = window.prompt("관리자 비밀번호를 입력하세요 (Gemini 모델 전용):");
  if (!password) {
    select.value = "nvidia";
    localStorage.setItem(MODEL_STORAGE_KEY, "nvidia");
    return;
  }

  const ok = await verifyAdminPassword(password);
  if (!ok) {
    alert("비밀번호가 올바르지 않습니다.");
    select.value = "nvidia";
    localStorage.setItem(MODEL_STORAGE_KEY, "nvidia");
    return;
  }

  sessionStorage.setItem(ADMIN_PW_STORAGE_KEY, password);
  localStorage.setItem(MODEL_STORAGE_KEY, "gemini");
}

// ── localStorage 저장/불러오기 ──
function saveToStorage(sessions) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch (e) {
    console.warn("localStorage 저장 실패:", e);
  }
}

function loadFromStorage() {
  try {
    const data = localStorage.getItem(STORAGE_KEY);
    return data ? JSON.parse(data) : [];
  } catch (e) {
    return [];
  }
}

// ── 세션 관리 ──
let sessions = loadFromStorage();       // 전체 세션 목록
let currentSession = null;              // 현재 세션
let history = [];                       // 현재 대화 히스토리

function createSession() {
  const session = {
    id: Date.now().toString(),
    title: "새 대화",
    date: new Date().toLocaleDateString("ko-KR"),
    messages: []
  };
  sessions.unshift(session);
  if (sessions.length > MAX_SESSIONS) sessions.pop();
  currentSession = session;
  history = [];
  saveToStorage(sessions);
  renderSidebar();
  return session;
}

function loadSession(id) {
  const session = sessions.find(s => s.id === id);
  if (!session) return;
  currentSession = session;
  history = session.messages
    .filter(m => m.role !== "bot" || true)
    .map(m => ({ role: m.role === "bot" ? "assistant" : "user", content: m.text }));

  const messages = document.getElementById("messages");
  messages.innerHTML = "";
  session.messages.forEach(m => {
    appendBubble(m.role, m.text, m.lawUsed || false, false);
  });
  highlightActive(id);
}

function addMessageToSession(role, text, lawUsed = false) {
  if (!currentSession) createSession();
  currentSession.messages.push({ role, text, lawUsed });

  // 첫 사용자 메시지를 제목으로
  if (role === "user" && currentSession.title === "새 대화") {
    currentSession.title = text.length > 18 ? text.slice(0, 18) + "…" : text;
  }
  saveToStorage(sessions);
  renderSidebar();
}

// ── 사이드바 렌더링 ──
function deleteSession(id, e) {
  e.stopPropagation();  // 세션 불러오기 클릭 방지
  if (!confirm("이 대화를 삭제할까요?")) return;

  sessions = sessions.filter(s => s.id !== id);
  saveToStorage(sessions);

  if (currentSession?.id === id) {
    if (sessions.length > 0) {
      loadSession(sessions[0].id);
    } else {
      currentSession = null;
      history = [];
      newChat();
    }
  }
  renderSidebar();
}

function renderSidebar() {
  const container = document.getElementById("session-list");
  if (!container) return;
  container.innerHTML = "";

  sessions.forEach(session => {
    const btn = document.createElement("button");
    btn.className = "session-btn" + (currentSession?.id === session.id ? " active" : "");
    btn.dataset.id = session.id;
    btn.innerHTML = `
      <span class="session-title">${session.title}</span>
      <span class="session-date">${session.date}</span>
      <span class="session-delete" onclick="deleteSession('${session.id}', event)">✕</span>`;
    btn.onclick = () => loadSession(session.id);
    container.appendChild(btn);
  });
}

function highlightActive(id) {
  document.querySelectorAll(".session-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.id === id);
  });
}

// ── 메시지 출력 ──
function getTime() {
  return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function clearWelcome() {
  const welcome = document.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function appendBubble(role, text, lawUsed = false, save = true) {
  clearWelcome();
  const messages = document.getElementById("messages");

  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = getTime();

  wrap.appendChild(bubble);

  if (role === "bot" && lawUsed) {
    const badge = document.createElement("span");
    badge.className = "law-badge";
    badge.textContent = "법제처 데이터 참조";
    wrap.appendChild(badge);
  }

  wrap.appendChild(meta);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;

  if (save) addMessageToSession(role, text, lawUsed);
}

function appendMessage(role, text, lawUsed = false) {
  appendBubble(role, text, lawUsed, true);
}

function showTyping() {
  clearWelcome();
  const messages = document.getElementById("messages");
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  wrap.id = "typing-indicator";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const typing = document.createElement("div");
  typing.className = "typing";
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("div");
    dot.className = "dot";
    typing.appendChild(dot);
  }
  bubble.appendChild(typing);
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
}

function hideTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

// ── 메시지 전송 ──
async function sendMessage() {
  const input = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");
  const text = input.value.trim();
  if (!text) return;

  if (!currentSession) createSession();

  input.value = "";
  input.style.height = "auto";
  sendBtn.disabled = true;

  appendMessage("user", text);
  showTyping();

  try {
    const selectedModel = getSelectedModel();
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history,
        model: selectedModel,
        admin_password: selectedModel === "gemini" ? getAdminPassword() : null,
      }),
    });

    if (!res.ok) throw new Error(`서버 오류: ${res.status}`);
    const data = await res.json();

    hideTyping();
    appendMessage("bot", data.reply, data.law_context_used);

    if (data.denied) {
      sessionStorage.removeItem(ADMIN_PW_STORAGE_KEY);
      localStorage.setItem(MODEL_STORAGE_KEY, "nvidia");
      const select = document.getElementById("model-select");
      if (select) select.value = "nvidia";
    }

    history.push({ role: "user", content: text });
    history.push({ role: "assistant", content: data.reply });
    if (history.length > 20) history = history.slice(-20);

  } catch (err) {
    hideTyping();
    appendMessage("bot", `오류가 발생했습니다: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

// ── 유틸 ──
function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

function useHint(btn) {
  const input = document.getElementById("user-input");
  input.value = btn.textContent.trim();
  input.focus();
  autoResize(input);
}

function newChat() {
  createSession();
  const messages = document.getElementById("messages");
  messages.innerHTML = `
    <div class="welcome">
      <img src="/static/logo.jpg" class="welcome-icon" alt="로고">
      <h2>법적 근거를 알고 싶으신가요?</h2>
      <p>하고 계신 업무에 대해 질문해 주세요.<br>
         법제처 데이터를 기반으로 정확한 답변을 제공합니다.<br>
         Designed by Han Sang Hoon</p>
    </div>`;
}

// ── 초기화 ──
window.onload = () => {
  renderSidebar();
  if (getSelectedModel() === "gemini" && !getAdminPassword()) {
    localStorage.setItem(MODEL_STORAGE_KEY, "nvidia");
  }
  const modelSelect = document.getElementById("model-select");
  if (modelSelect) modelSelect.value = getSelectedModel();
  if (sessions.length > 0) {
    loadSession(sessions[0].id);
  } else {
    createSession();
  }
};

function toggleSidebar() {
  const sidebar = document.querySelector(".sidebar");
  sidebar.classList.toggle("open");
}

// 메시지 전송 시 모바일 사이드바 자동 닫기
document.addEventListener("click", function (e) {
  const sidebar = document.querySelector(".sidebar");
  const menuBtn = document.querySelector(".menu-btn");
  if (sidebar && menuBtn &&
      !sidebar.contains(e.target) &&
      !menuBtn.contains(e.target)) {
    sidebar.classList.remove("open");
  }
});