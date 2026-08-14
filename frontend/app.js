// app.js — 全局共享工具（API 客户端 / HTML 转义 / Toast / 导航高亮）
// 所有面板共用，避免重复定义。

// ── API 客户端 ─────────────────────────────────────────────
const API = {
  async get(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
  async post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
};

// ── HTML 转义 ──────────────────────────────────────────────
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ── Toast ──────────────────────────────────────────────────
function toast(msg, type = "success") {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = "toast toast-" + type;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// ── 顶栏导航高亮 ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  document.querySelectorAll(".nav a[data-nav]").forEach(function (a) {
    const key = a.getAttribute("data-nav");
    const match = key === "index" ? path === "/" : path === "/" + key;
    if (match) a.classList.add("active");
  });
});
