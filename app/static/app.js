const $ = (s) => document.querySelector(s);
const STATUS = {
  queued: "В очереди", converting: "Конвертация в mp3", uploading: "Отправка в AssemblyAI",
  transcribing: "Распознавание", done: "Готово", error: "Ошибка",
};
const ACTIVE = new Set(["queued", "converting", "uploading", "transcribing"]);
const open = new Set();            // раскрытые карточки
const texts = new Map();           // id -> полная запись с текстом
let timer = null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2200);
}
function size(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(b / 1024)) + " КБ"; }
function dur(s) { if (!s) return ""; s = Math.round(s); const m = Math.floor(s / 60); return m + ":" + String(s % 60).padStart(2, "0"); }
function when(ts) { return new Date(ts * 1000).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }); }

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401 && !url.includes("login")) { showLogin(); throw new Error("auth"); }
  if (!r.ok) {
    let d = r.statusText; try { d = (await r.json()).detail || d; } catch {}
    throw new Error(d);
  }
  return r.json();
}

function showLogin() { $("#main").hidden = true; $("#login").hidden = false; $("#password").focus(); }
function showMain() { $("#login").hidden = true; $("#main").hidden = false; refresh(); }

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("#password").value }) });
    $("#password").value = ""; showMain();
  } catch (err) { $("#login-error").textContent = err.message; }
});
$("#logout").addEventListener("click", async () => { await fetch("/api/logout", { method: "POST" }); showLogin(); });

/* ---------- загрузка ---------- */
const drop = $("#drop"), fileInput = $("#file");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload([...e.dataTransfer.files]));
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
fileInput.addEventListener("change", () => { upload([...fileInput.files]); fileInput.value = ""; });

// файлы грузим по одному, чтобы был прогресс по каждому и не упереться в лимиты прокси
async function upload(files) {
  for (const f of files) {
    const row = document.createElement("div");
    row.className = "card";
    row.innerHTML = `<div class="row"><span class="title">${esc(f.name)}</span><span class="meta">0%</span></div>
      <div class="progress"><div style="width:0"></div></div>`;
    $("#uploads").prepend(row);
    try {
      await sendOne(f, (p) => {
        row.querySelector(".meta").textContent = p < 1 ? Math.round(p * 100) + "%" : "обработка…";
        row.querySelector(".progress > div").style.width = p * 100 + "%";
      });
      row.remove();
    } catch (err) {
      row.querySelector(".meta").textContent = err.message;
      row.querySelector(".meta").classList.add("error");
      setTimeout(() => row.remove(), 8000);
    }
    refresh();
  }
}
function sendOne(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData(); fd.append("files", file);
    const x = new XMLHttpRequest();
    x.open("POST", "/api/upload");
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let body = {}; try { body = JSON.parse(x.responseText); } catch {}
      if (x.status === 401) { showLogin(); return reject(new Error("Требуется вход")); }
      if (x.status >= 400) return reject(new Error(body.detail || "Ошибка " + x.status));
      const bad = (body.files || []).find((f) => f.error);
      bad ? reject(new Error(bad.error)) : resolve();
    };
    x.onerror = () => reject(new Error("Сеть недоступна"));
    x.send(fd);
  });
}

/* ---------- список ---------- */
async function refresh() {
  clearTimeout(timer);
  let items;
  try { items = await api("/api/recordings"); } catch { return; }
  render(items);
  if (items.some((r) => ACTIVE.has(r.status))) timer = setTimeout(refresh, 2500);
}

function render(items) {
  const list = $("#list");
  if (!items.length) { list.innerHTML = '<p class="muted">Пока пусто</p>'; return; }
  list.innerHTML = items.map(card).join("");
  items.forEach((r) => { if (open.has(r.id) && r.status === "done") fillTranscript(r.id); });
}

function card(r) {
  const meta = [when(r.created_at), dur(r.duration), r.language && r.language.toUpperCase(),
    size(r.original_size) + (r.mp3_size ? " → " + size(r.mp3_size) : "")].filter(Boolean).join(" · ");
  const active = ACTIVE.has(r.status);
  return `<div class="card" data-id="${r.id}">
    <div class="row"><div><div class="title">${esc(r.name)}</div><div class="meta">${esc(meta)}</div></div>
    <span class="badge ${r.status}">${STATUS[r.status] || r.status}</span></div>
    ${active ? '<div class="progress indeterminate"><div></div></div>' : ""}
    ${r.status === "error" ? `<p class="error">${esc(r.error)}</p>` : ""}
    <div class="transcript" ${open.has(r.id) && r.status === "done" ? "" : "hidden"}></div>
    <div class="actions">
      ${r.status === "done" ? `<button data-act="toggle">${open.has(r.id) ? "Скрыть текст" : "Показать текст"}</button>
        <button data-act="copy">Копировать</button>
        <a href="/download/${r.id}/txt">.txt</a><a href="/download/${r.id}/srt">.srt</a>` : ""}
      ${r.mp3_size ? `<a href="/download/${r.id}/mp3">mp3</a>` : ""}
      <a href="/download/${r.id}/original">оригинал</a>
      ${r.status === "error" ? '<button data-act="retry">Повторить</button>' : ""}
      <button class="danger" data-act="delete">Удалить</button>
    </div></div>`;
}

async function fullRec(id) {
  if (!texts.has(id)) texts.set(id, await api("/api/recordings/" + id));
  return texts.get(id);
}
function plain(rec) {
  const u = rec.utterances;
  if (u && new Set(u.map((x) => x.speaker)).size > 1) return u.map((x) => `Спикер ${x.speaker}: ${x.text}`).join("\n\n");
  return rec.text || "";
}
async function fillTranscript(id) {
  const box = document.querySelector(`.card[data-id="${id}"] .transcript`);
  if (!box) return;
  const rec = await fullRec(id);
  const u = rec.utterances;
  const multi = u && new Set(u.map((x) => x.speaker)).size > 1;
  box.innerHTML = (multi ? u.map((x) => `<p class="utt"><b>Спикер ${esc(x.speaker)}:</b> ${esc(x.text)}</p>`).join("")
    : `<p class="utt">${esc(rec.text) || '<span class="muted">Речь не обнаружена</span>'}</p>`)
    + `<audio controls preload="none" src="/audio/${id}"></audio>`;
  box.hidden = false;
}

$("#list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]"); if (!btn) return;
  const id = btn.closest(".card").dataset.id;
  try {
    switch (btn.dataset.act) {
      case "toggle":
        open.has(id) ? open.delete(id) : open.add(id);
        const box = btn.closest(".card").querySelector(".transcript");
        if (open.has(id)) await fillTranscript(id); else box.hidden = true;
        btn.textContent = open.has(id) ? "Скрыть текст" : "Показать текст";
        break;
      case "copy": {
        const text = plain(await fullRec(id));
        try { await navigator.clipboard.writeText(text); }
        catch { const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
        toast("Скопировано"); break;
      }
      case "retry": await api(`/api/recordings/${id}/retry`, { method: "POST" }); refresh(); break;
      case "delete":
        if (!confirm("Удалить запись вместе с файлами?")) return;
        await api("/api/recordings/" + id, { method: "DELETE" });
        open.delete(id); texts.delete(id); refresh(); break;
    }
  } catch (err) { if (err.message !== "auth") toast(err.message); }
});

/* ---------- старт ---------- */
fetch("/api/me").then((r) => r.json()).then((m) => (m.authenticated ? showMain() : showLogin())).catch(showLogin);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
