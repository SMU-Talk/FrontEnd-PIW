const authModal = document.querySelector("#authModal");
const guestNote = document.querySelector("#guestNote");
const statusPill = document.querySelector("#statusPill");
const messages = document.querySelector("#messages");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const toast = document.querySelector("#toast");
const sendButton = document.querySelector(".send-button");
const openAuthButtons = [...document.querySelectorAll("[data-open-auth]")];

let sessionReady = false;
let currentMode = "guest";

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "요청을 처리하지 못했습니다.");
  }
  return data;
}

function setSessionState(me) {
  sessionReady = Boolean(me.authenticated);
  currentMode = me.mode || "guest";
  messageInput.disabled = !sessionReady;
  sendButton.disabled = !sessionReady;
  messageInput.placeholder = sessionReady ? "상명대학교에 대해 질문해 보세요" : "게스트 모드를 준비하고 있습니다";

  const isGuest = currentMode === "guest";
  guestNote.textContent = isGuest ? "게스트 모드로 이용 중" : `${me.name || "사용자"}님 로그인 중`;
  statusPill.textContent = isGuest ? "게스트 모드" : "로그인 모드";
  openAuthButtons.forEach((button) => {
    button.textContent = isGuest ? "로그인" : "계정 전환";
  });
}

function openAuthModal() {
  authModal.classList.remove("is-hidden");
  authModal.setAttribute("aria-hidden", "false");
  const firstInput = authModal.querySelector("input");
  window.setTimeout(() => firstInput?.focus(), 80);
}

function closeAuthModal() {
  authModal.classList.add("is-hidden");
  authModal.setAttribute("aria-hidden", "true");
}

function addMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";

  if (role === "assistant") {
    const image = document.createElement("img");
    image.src = "/assets/SMU.png";
    image.alt = "";
    avatar.append(image);
  } else {
    avatar.textContent = "나";
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  article.append(avatar, bubble);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
}

function resetMessages() {
  messages.innerHTML = "";
  addMessage(
    "assistant",
    "안녕하세요. SMU Talk입니다. 현재 게스트 모드로 이용 중입니다. 입학, 학사, 장학금, 캠퍼스, 도서관, 포털 관련 질문을 입력해 주세요.",
  );
}

async function refreshHistory() {
  const data = await api("/api/history");
  resetMessages();
  for (const message of data.messages) {
    addMessage(message.role, message.content);
  }
}

async function startGuestSession() {
  const data = await api("/api/guest", {
    method: "POST",
    body: JSON.stringify({ guestName: "게스트" }),
  });
  setSessionState({ authenticated: true, mode: data.mode, name: data.name });
  resetMessages();
}

async function refreshMe() {
  const me = await api("/api/me");
  if (!me.authenticated) {
    await startGuestSession();
    return;
  }
  setSessionState(me);
  await refreshHistory();
}

document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-auth-tab]").forEach((item) => item.classList.remove("is-active"));
    document.querySelectorAll(".auth-form").forEach((form) => form.classList.remove("is-active"));
    tab.classList.add("is-active");
    document.querySelector(`#${tab.dataset.authTab}Form`).classList.add("is-active");
    document.querySelector("#authTitle").textContent = tab.dataset.authTab === "login" ? "로그인" : "회원가입";
  });
});

openAuthButtons.forEach((button) => button.addEventListener("click", openAuthModal));
document.querySelectorAll("[data-close-auth]").forEach((button) => button.addEventListener("click", closeAuthModal));

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !authModal.classList.contains("is-hidden")) {
    closeAuthModal();
  }
});

document.querySelector("#guestModeButton").addEventListener("click", async () => {
  try {
    if (currentMode !== "guest") {
      await api("/api/logout", { method: "POST", body: "{}" });
      await startGuestSession();
      showToast("게스트 모드로 전환했습니다.");
    }
    closeAuthModal();
  } catch (error) {
    showToast(error.message);
  }
});

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(formData)),
    });
    setSessionState({ authenticated: true, mode: data.mode, name: data.name });
    await refreshHistory();
    closeAuthModal();
    showToast("로그인되었습니다.");
  } catch (error) {
    showToast(error.message);
  }
});

document.querySelector("#registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  try {
    const data = await api("/api/register", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(formData)),
    });
    setSessionState({ authenticated: true, mode: data.mode, name: data.name });
    await refreshHistory();
    closeAuthModal();
    showToast("계정이 생성되었습니다.");
  } catch (error) {
    showToast(error.message);
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || !sessionReady) {
    return;
  }

  addMessage("user", message);
  messageInput.value = "";
  messageInput.style.height = "auto";
  sendButton.disabled = true;

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    addMessage("assistant", data.reply);
  } catch (error) {
    showToast(error.message);
  } finally {
    sendButton.disabled = false;
    messageInput.focus();
  }
});

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 160)}px`;
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelector("#clearButton").addEventListener("click", async () => {
  await api("/api/clear", { method: "POST", body: "{}" });
  resetMessages();
  showToast("대화를 지웠습니다.");
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.prompt;
    messageInput.focus();
  });
});

refreshMe().catch(() => {
  setSessionState({ authenticated: false });
  showToast("게스트 모드를 시작하지 못했습니다. 서버 상태를 확인해 주세요.");
});
