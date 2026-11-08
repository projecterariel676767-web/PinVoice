const $ = (selector) => document.querySelector(selector);
const form = $("#upload-form");
const fileInput = $("#audio-file");
const consent = $("#consent");
const button = $("#analyze-button");
const dropzone = $("#dropzone");
const notice = $("#notice");
let selectedFile = null;

function showNotice(message, isError = false) {
  notice.textContent = message;
  notice.hidden = false;
  notice.classList.toggle("error", isError);
}
function formatBytes(bytes) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function updateButton() { button.disabled = !selectedFile || !consent.checked; }
function chooseFile(file) {
  if (!file) return;
  if (!file.type.startsWith("audio/") && !/\.(wav|mp3|m4a|ogg|flac|webm)$/i.test(file.name)) {
    showNotice("Выберите аудиофайл поддерживаемого формата.", true); return;
  }
  if (file.size > 30 * 1024 * 1024) { showNotice("Файл превышает лимит 30 МБ.", true); return; }
  selectedFile = file;
  $("#file-name").textContent = file.name;
  $("#file-size").textContent = formatBytes(file.size);
  $("#file-row").hidden = false;
  dropzone.hidden = true;
  notice.hidden = true;
  updateButton();
}
fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
$("#remove-file").addEventListener("click", () => {
  selectedFile = null; fileInput.value = ""; $("#file-row").hidden = true; dropzone.hidden = false; updateButton();
});
consent.addEventListener("change", updateButton);
["dragenter", "dragover"].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", e => chooseFile(e.dataTransfer.files[0]));

function metric(label, value, unit) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong><small>${unit}</small></div>`;
}
function drawWaveform(values) {
  const canvas = $("#waveform");
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * ratio;
  canvas.height = 110 * ratio;
  ctx.scale(ratio, ratio);
  const width = canvas.clientWidth, height = 110;
  ctx.clearRect(0, 0, width, height);
  const mid = height / 2;
  ctx.strokeStyle = "#6de2d7";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = index / Math.max(1, values.length - 1) * width;
    const y = mid - value * 43;
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.strokeStyle = "#a99bff";
  ctx.globalAlpha = .45;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = index / Math.max(1, values.length - 1) * width;
    const y = mid + value * 43;
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.globalAlpha = 1;
}
function renderProfile(profile) {
  const a = profile.analysis;
  $("#metrics").innerHTML = [
    metric("ДЛИТЕЛЬНОСТЬ", a.duration_seconds, "секунд"),
    metric("ЧАСТОТА ДИСКРЕТИЗАЦИИ", (a.sample_rate_hz / 1000).toFixed(1), "кГц"),
    metric("СРЕДНИЙ PITCH", a.estimated_pitch_hz ?? "—", "Гц · оценка"),
    metric("SPECTRAL CENTROID", Math.round(a.spectral_centroid_hz), "Гц · тембр")
  ].join("");
  drawWaveform(a.waveform || []);
  const notes = (a.quality_notes || []).join(" ");
  $("#dna-status").textContent = profile.phoneme_dna.description + (notes ? " " + notes : "");
  const t = profile.transcription || {};
  $("#transcript-state").textContent = t.status === "completed" ? "ГОТОВО" : t.status === "error" ? "ОШИБКА" : "НЕ ВКЛЮЧЕНО";
  $("#transcript-text").textContent = t.text || (t.status === "error" ? t.message : "Транскрипция отключена. Для активации задайте PINVOICE_ENABLE_WHISPER=true в настройках Render.");
  $("#results").hidden = false;
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedFile || !consent.checked) return;
  button.disabled = true;
  button.querySelector("span").textContent = "Анализируем запись…";
  showNotice("Загружаем аудио и измеряем акустические характеристики.");
  try {
    const data = new FormData();
    data.append("file", selectedFile);
    data.append("consent", "true");
    data.append("display_name", $("#display-name").value || "Мой голос");
    const response = await fetch("/api/voices", { method: "POST", body: data });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Не удалось обработать запись.");
    showNotice("Анализ завершён. Профиль сохранён.");
    renderProfile(result);
    await loadVoices();
  } catch (error) {
    showNotice(error.message || "Ошибка сети. Попробуйте ещё раз.", true);
  } finally {
    button.querySelector("span").textContent = "Анализировать голос";
    updateButton();
  }
});

async function loadVoices() {
  try {
    const response = await fetch("/api/voices");
    const data = await response.json();
    const items = data.items || [];
    $("#voice-count").textContent = `${items.length} ПРОФИЛЕЙ`;
    $("#voice-list").innerHTML = items.length ? items.map(item => `
      <div class="voice-item">
        <div class="voice-symbol">♫</div>
        <div class="voice-info"><strong>${escapeHtml(item.display_name)}</strong><small>${new Date(item.created_at).toLocaleString("ru-RU")} · ${item.analysis?.duration_seconds ?? "—"} сек · Русский</small></div>
        <button class="delete-voice" data-id="${item.id}">Удалить</button>
      </div>`).join("") : '<div class="empty-state">Здесь появятся ваши проанализированные голосовые профили.</div>';
    document.querySelectorAll(".delete-voice").forEach(btn => btn.addEventListener("click", async () => {
      if (!confirm("Удалить профиль и исходную аудиозапись?")) return;
      const response = await fetch(`/api/voices/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
      if (response.ok) loadVoices(); else showNotice("Не удалось удалить профиль.", true);
    }));
  } catch { /* The health endpoint and API errors are shown during interaction. */ }
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}
loadVoices();
