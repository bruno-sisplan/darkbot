// darkbot — interface. Dados carregados uma vez; filtros e ordenação rodam no navegador (instantâneo).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  profiles: [],
  videos: [],
  channels: [],
  vSort: { key: "multiplier", dir: -1 },
  cSort: { key: "best_multiplier", dir: -1 },
  vLimit: 150,
  watching: new Set(),
};

// ---------------------------------------------------------------- utilidades

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erro ${res.status}`);
  return data;
}

const nf = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const fmt = (n) => (n == null ? "—" : nf.format(n));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtAge(days) {
  if (days == null) return "—";
  if (days < 1) return `${Math.max(1, Math.round(days * 24))}h`;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}m`;
  return `${(days / 365).toFixed(1).replace(".", ",")}a`;
}
function fmtDur(s) {
  if (s == null) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function multClass(m) {
  if (m == null) return "l0";
  if (m >= 50) return "l4";
  if (m >= 10) return "l3";
  if (m >= 3) return "l2";
  return "l1";
}
function fmtMult(m) {
  if (m == null) return "—";
  return m >= 100 ? `${Math.round(m)}×` : `${m.toFixed(m < 10 ? 1 : 0).replace(".", ",")}×`;
}
function median(arr) {
  const a = arr.filter((x) => x != null).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "err" ? 6000 : 3500);
}

const FORMAT_LABELS = {
  narracao: "Narração", musica: "Música", compilacao: "Compilação", reupload: "Repostagem",
  animacao: "Animação", comentario: "Youtuber", cortes: "Cortes", com_rosto: "Com rosto", oficial: "Oficial", outro: "Outro",
};
// Explicações curtas (aparecem ao passar o mouse). Linguagem simples, sem termo técnico.
const TIP = {
  viralizou: "Quantas vezes o vídeo teve mais views do que o canal tem de inscritos. Ex.: 10× = 10 vezes mais views que inscritos. Quanto maior, mais o YouTube espalhou o vídeo.",
  nota: "Nota para copiar: quanto o vídeo viralizou, valendo mais se ele for recente. Quanto maior, melhor para fazer um parecido agora.",
};
const viralTip = (m) => m == null ? "Ainda sem número" : `Viralizou ${fmtMult(m)}: o vídeo teve ${String(m).replace(".", ",")} vezes mais views do que o canal tem de inscritos`;
function ageLong(days) {
  if (days == null) return "";
  if (days < 1) return `${Math.max(1, Math.round(days * 24))} horas`;
  if (days < 30) return `${Math.round(days)} dias`;
  if (days < 365) { const m = Math.round(days / 30); return `${m} ${m === 1 ? "mês" : "meses"}`; }
  return `${(days / 365).toFixed(1).replace(".", ",")} anos`;
}
const LANG_NAME = { pt: "Português", en: "Inglês", es: "Espanhol", hi: "Hindi", id: "Indonésio", fr: "Francês", de: "Alemão",
  ja: "Japonês", ko: "Coreano", ru: "Russo", ar: "Árabe", tr: "Turco", it: "Italiano", zh: "Chinês", nl: "Holandês",
  pl: "Polonês", vi: "Vietnamita", th: "Tailandês", fil: "Filipino", uk: "Ucraniano" };
const FORMAT_TIP = {
  narracao: "canal de narração (histórias, curiosidades, mistério…)", musica: "canal de música",
  compilacao: "canal de compilados", reupload: "canal que reposta vídeos de outros", animacao: "canal de animação",
  comentario: "youtuber com personalidade própria", cortes: "canal de cortes de pessoa famosa",
  com_rosto: "a pessoa aparece no vídeo", oficial: "canal oficial (artista, TV, marca)", outro: "outro tipo",
};
const fmtUSD = (x) => `US$ ${(x || 0).toFixed(x >= 0.1 ? 2 : 4).replace(".", ",")}`;

// Marcações do canal: selo de IA do YouTube e formato classificado pela IA.
function channelTags(v) {
  const out = [];
  if (v.channel_ai) out.push(`<span class="tag ai" title="Feito com IA: o próprio canal avisa no YouTube que usa inteligência artificial">IA</span>`);
  if (v.channel_format && v.channel_format !== "outro") {
    const dark = v.is_dark ?? (v.channel_ai || v.channel_dark);
    out.push(`<span class="tag ${dark ? "dark" : "neutral"}" title="Tipo de canal: ${FORMAT_TIP[v.channel_format] || v.channel_format}. ${dark ? "É um canal dark (ninguém aparece)." : "Não é um canal dark."}">${FORMAT_LABELS[v.channel_format] || v.channel_format}</span>`);
  }
  return out;
}

// Botão "pesquisar a partir deste vídeo" (usado nas tabelas).
const seedBtn = (id) => `<button class="icon-btn seed-btn" data-seed="${id}" title="Pesquisar vídeos parecidos com este">
  <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/><path d="M11 8.5v5M8.5 11h5"/></svg></button>`;
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-seed]");
  if (!b) return;
  e.stopPropagation();
  startResearch({ kind: "video", seed: b.dataset.seed, report: true });
}, true);

// Marcações de novidade: canal novo e vídeo recente.
function newTags(v) {
  const t = [];
  if (v.channel_age_days != null && v.channel_age_days <= 180) t.push(`<span class="tag new" title="Canal criado há ${ageLong(v.channel_age_days)} (canal novo indo bem = tem espaço no nicho)">Canal novo · ${fmtAge(v.channel_age_days)}</span>`);
  if (v.age_days != null && v.age_days <= 7) t.push(`<span class="tag fresh" title="Postado há ${ageLong(v.age_days)}">Recente</span>`);
  return t;
}

// Título com a tradução embaixo (vídeos em outros idiomas).
function titleCell(v) {
  const tr = v.title_pt && v.title_pt !== v.title ? `<div class="v-trans" title="Tradução">${esc(v.title_pt)}</div>` : "";
  return `<div class="v-title" title="${esc(v.title)}">${esc(v.title) || "<span class='dim'>(sem título)</span>"}</div>${tr}`;
}
const langTag = (v) => {
  const l = (v.lang || "").split("-")[0].toLowerCase();
  return l && l !== "pt" ? `<span class="tag lang" title="Idioma do vídeo: ${esc(LANG_NAME[l] || l.toUpperCase())}">${esc(l.toUpperCase())}</span>` : "";
};

// Ações da linha: ocultar o vídeo, marcar o canal como não dark, pesquisar a partir dele.
function rowActions(v) {
  return `<div class="row-actions">
    <button class="icon-btn" data-hide="${v.video_id}" title="Esconder este vídeo das listas">
      <svg viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.6 6.1A9.6 9.6 0 0 1 12 6c5 0 8.5 4.2 9.5 6-.4.8-1.3 2-2.6 3.2M6.6 6.6C4.6 8 3.1 10 2.5 12c1 1.8 4.5 6 9.5 6 1.6 0 3-.4 4.3-1"/></svg></button>
    ${v.channel_id ? `<button class="icon-btn" data-dark="${v.channel_id}" data-val="${v.is_dark ? 0 : 1}"
      title="${v.is_dark ? "Marcar: este canal NÃO é dark (sai do filtro e a IA aprende)" : "Marcar: este canal É dark"}">
      ${v.is_dark ? `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/></svg>`
        : `<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`}</button>` : ""}
    ${modeledBtn(v.video_id)}${seedBtn(v.video_id)}</div>`;
}

// Ações globais (tabelas, prévia): ocultar vídeo e corrigir "dark" do canal.
document.addEventListener("click", async (e) => {
  const h = e.target.closest("[data-hide]"), d = e.target.closest("[data-dark]");
  if (!h && !d) return;
  e.stopPropagation();
  try {
    if (h) {
      const hidden = h.dataset.unhide !== "1";
      await api(`/api/videos/${h.dataset.hide}/hide`, { method: "POST", body: { hidden } });
      toast(hidden ? "Vídeo ocultado (dá para mostrar de novo em Configurações)." : "Vídeo de volta nas listas.", "ok");
    } else {
      const val = d.dataset.val === "" ? null : d.dataset.val === "1";
      await api(`/api/channels/${d.dataset.dark}/dark`, { method: "POST", body: { dark: val } });
      toast(val === null ? "Canal volta para a classificação da IA." : val ? "Canal marcado como dark." : "Canal marcado como NÃO dark. A IA vai aprender com isso.", "ok");
    }
    afterCorrection();
  } catch (err) { toast(err.message, "err"); }
}, true);

async function afterCorrection() {
  await loadVideos();
  if ($("#page-research").classList.contains("active") && R.current != null) openResearch(R.current, true);
  if ($("#page-channels").classList.contains("active")) loadChannels();
  if (!$("#pv").hidden && PV.id) openPreview(PV.id, true);
}

const openYT = (path) => api("/api/open-url", { method: "POST", body: { url: `https://www.youtube.com/${path}` } });

// ---------------------------------------------------------------- navegação

$$(".nav-item").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".nav-item").forEach((x) => x.classList.toggle("active", x === b));
    $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${b.dataset.page}`));
    if (b.dataset.page === "profiles") loadProfiles();
    if (b.dataset.page === "channels") loadChannels();
    if (b.dataset.page === "settings") loadSettings();
    if (b.dataset.page === "titles") loadTitles();
    if (b.dataset.page === "research") loadResearch();
    if (b.dataset.page === "next") loadNext();
  })
);

function bindSeg(el, onChange) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $$("button", el).forEach((x) => x.classList.toggle("on", x === b));
    onChange(b.dataset.v);
  });
}
const segValue = (el) => $("button.on", el).dataset.v;

function bindSort(table, sortState, render) {
  $$("th[data-sort]", table).forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortState.dir = sortState.key === key ? -sortState.dir : key === "title" ? 1 : -1;
      sortState.key = key;
      $$("th", table).forEach((x) => x.classList.remove("sorted", "asc", "desc"));
      th.classList.add("sorted", sortState.dir > 0 ? "asc" : "desc");
      render();
    })
  );
}
function sortBy(list, { key, dir }) {
  return list.sort((a, b) => {
    const x = a[key], y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return typeof x === "string" ? x.localeCompare(y) * dir : (x - y) * dir;
  });
}

// ---------------------------------------------------------------- perfis (selects)

// Os filtros de perfil das telas seguem sempre o perfil em uso (ficam escondidos).
function fillProfileSelects() {
  const opts = `<option value="">Todos os perfis</option>` +
    state.profiles.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  for (const id of ["#v-profile", "#c-profile", "#t-profile"]) {
    const sel = $(id);
    sel.innerHTML = opts;
    sel.value = state.profile ? String(state.profile) : "";
  }
  renderActiveProfile();
}

// ---------------------------------------------------------------- perfil em uso

function savedProfile() {
  try { const v = localStorage.getItem("profile"); return v ? +v : null; } catch { return null; }
}
function currentProfile() { return state.profiles.find((p) => p.id === state.profile) || null; }

function renderActiveProfile() {
  const p = currentProfile(), el = $("#active-profile");
  el.innerHTML = p
    ? `<div class="ap-icon ${p.kind}">${p.kind === "coringa" ? ICON_JOKER : ICON_PROFILE}</div>
       <div class="ap-body"><span>Perfil em uso</span><b>${esc(p.name)}</b><small>${esc(p.niche || (p.kind === "coringa" ? "coringa" : "sem nicho"))}</small></div>
       <svg viewBox="0 0 24 24" class="ap-swap"><path d="M7 7h11l-3-3M17 17H6l3 3"/></svg>`
    : `<div class="ap-body"><span>Perfil em uso</span><b>Escolher perfil</b></div>`;
}

function openProfilePicker(force = false) {
  $("#pick-modal").hidden = false;
  $("#pick-modal").dataset.force = force ? "1" : "";
  $("[data-pick-close]").hidden = force;
  $("#pick-list").innerHTML = state.profiles.length ? state.profiles.map((p) => `
    <button class="pick-opt ${p.id === state.profile ? "on" : ""}" data-pick="${p.id}">
      <div class="ap-icon ${p.kind}">${p.kind === "coringa" ? ICON_JOKER : ICON_PROFILE}</div>
      <div class="grow"><b>${esc(p.name)}</b><small>${esc(p.niche || "sem nicho")} · ${p.videos || 0} vídeos · ${p.runs || 0} coletas</small></div>
    </button>`).join("") : `<div class="empty"><b>Nenhum perfil ainda</b>Adicione um perfil para começar.</div>`;
}
const closeProfilePicker = () => { if (!$("#pick-modal").dataset.force) $("#pick-modal").hidden = true; };

async function useProfile(id) {
  state.profile = id;
  try { localStorage.setItem("profile", String(id)); } catch {}
  $("#pick-modal").hidden = true;
  R.current = null;
  $("#v-run").value = "";
  await refreshAll();
  toast(`Usando o perfil ${currentProfile()?.name || ""}.`, "ok");
}

$("#active-profile").addEventListener("click", () => openProfilePicker(false));
$("#pick-list").addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (b) useProfile(+b.dataset.pick); });
$("[data-pick-close]").addEventListener("click", closeProfilePicker);
$("#pick-add").addEventListener("click", () => {
  $("#pick-modal").hidden = true;
  $('.nav-item[data-page="profiles"]').click();
  openModal();
});

// ---------------------------------------------------------------- descobertas

async function loadVideos() {
  const q = new URLSearchParams();
  if ($("#v-profile").value) q.set("profile_id", $("#v-profile").value);
  if ($("#v-run").value) q.set("run_id", $("#v-run").value);
  if ($("#v-source").value) q.set("source", $("#v-source").value);
  state.videos = await api(`/api/videos?${q}`);
  state.vLimit = 150;
  renderVideos();
}

function filteredVideos() {
  const kind = segValue($("#v-ai"));
  const maxAge = +$("#v-age").value, maxSubs = +$("#v-subs").value;
  const maxCh = +$("#v-chage").value, minMult = +$("#v-mult").value;
  const q = $("#v-search").value.trim().toLowerCase();
  return state.videos.filter((v) => {
    if (kind === "ai" && !v.channel_ai) return false;
    if (kind === "dark" && !v.is_dark) return false;
    if (maxAge && (v.age_days == null || v.age_days > maxAge)) return false;
    if (maxSubs && (v.subs == null || v.subs > maxSubs)) return false;
    if (maxCh && (v.channel_age_days == null || v.channel_age_days > maxCh)) return false;
    if (minMult && (v.multiplier == null || v.multiplier < minMult)) return false;
    if (q && !`${v.title} ${v.channel_title}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderVideos() {
  const list = sortBy(filteredVideos(), state.vSort);
  const shown = list.slice(0, state.vLimit);
  const body = $("#v-table tbody");

  body.innerHTML = shown.map((v) => {
    const tags = [];
    tags.push(...channelTags(v));
    if (v.sources && v.sources.includes("history")) tags.push(`<span class="tag via" title="O perfil assistiu esse vídeo (veio do histórico)">Assistido</span>`);
    if (v.sources && v.sources.includes("research")) tags.push(`<span class="tag via" title="Veio de uma pesquisa que você enviou para cá">Pesquisa</span>`);
    tags.push(...newTags(v));
    return `<tr class="clickable" data-id="${v.video_id}">
      <td><div class="thumb"><img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
        ${v.duration_s != null ? `<span class="dur">${fmtDur(v.duration_s)}</span>` : ""}</div></td>
      <td>${titleCell(v)}
        <div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span>${langTag(v)}${tags.join("")}</div></td>
      <td class="num"><span class="mult ${multClass(v.multiplier)}" title="${viralTip(v.multiplier)}">${fmtMult(v.multiplier)}</span></td>
      <td class="num" title="${fmt(v.views)} views no total">${fmt(v.views)}</td>
      <td class="num" title="Faz ${fmt(v.views_day)} views por dia, em média">${fmt(v.views_day)}</td>
      <td class="num ${v.growth_day > 0 ? "up" : "dim"}" title="${v.growth_day != null ? `Ganhou ${fmt(v.growth_day)} views por dia entre as duas últimas coletas` : "Precisa de pelo menos duas coletas para saber"}">${v.growth_day != null ? `+${fmt(v.growth_day)}` : "—"}</td>
      <td class="num" title="O canal tem ${fmt(v.subs)} inscritos">${fmt(v.subs)}</td>
      <td class="num" title="Postado há ${ageLong(v.age_days)}">${fmtAge(v.age_days)}</td>
      <td class="num" title="Apareceu ${v.times_seen} ${v.times_seen === 1 ? "vez" : "vezes"} nos seus perfis">${v.times_seen}×</td>
      <td class="col-act">${rowActions(v)}</td>
    </tr>`;
  }).join("");

  const empty = $("#v-empty");
  if (!state.videos.length) {
    empty.innerHTML = `<b>Nenhuma coleta ainda</b>Vá em <span class="link" data-goto="profiles">Perfis</span>, adicione um perfil treinado e clique em Coletar.`;
    empty.hidden = false;
  } else if (!list.length) {
    empty.innerHTML = `<b>Nenhum vídeo com esses filtros</b>Tire algum filtro para ver mais vídeos.`;
    empty.hidden = false;
  } else empty.hidden = true;

  $("#v-more").hidden = list.length <= state.vLimit;
  $("#v-more").textContent = `Mostrar mais (${list.length - shown.length} restantes)`;
  renderKpis(list);
}

function renderKpis(list) {
  const top = [...list].filter((v) => v.multiplier != null).sort((a, b) => b.multiplier - a.multiplier)[0];
  const newCh = new Set(list.filter((v) => v.channel_age_days != null && v.channel_age_days <= 180).map((v) => v.channel_id));
  $("#v-kpis").innerHTML = `
    <div class="kpi" title="Quantos vídeos estão na lista com os filtros de agora"><div class="k-label">Vídeos na lista</div><div class="k-value">${list.length}</div>
      <div class="k-sub">de ${new Set(list.map((v) => v.channel_id)).size} canais</div></div>
    <div class="kpi" title="Metade dos vídeos da lista viralizou mais do que isso e metade viralizou menos. ${TIP.viralizou}"><div class="k-label">Quanto viralizam, normalmente</div><div class="k-value">${fmtMult(median(list.map((v) => v.multiplier)))}</div>
      <div class="k-sub">vezes mais views que inscritos</div></div>
    <div class="kpi" title="Canais criados há até 6 meses que aparecem na lista. Canal novo indo bem = ainda tem espaço nesse nicho"><div class="k-label">Canais novos</div><div class="k-value">${newCh.size}</div>
      <div class="k-sub">criados há até 6 meses = tem espaço</div></div>
    <div class="kpi hot" title="O vídeo que mais viralizou na lista"><div class="k-label">O que mais viralizou</div><div class="k-value">${top ? fmtMult(top.multiplier) : "—"}</div>
      <div class="k-sub" title="${esc(top?.title)}">${top ? esc(top.title) : "—"}</div></div>`;
}

$("#v-table tbody").addEventListener("click", (e) => {
  if (e.target.closest("[data-seed]")) return;
  const tr = e.target.closest("tr[data-id]");
  if (tr) openPreview(tr.dataset.id);
});
$("#v-source").addEventListener("change", loadVideos);
$("#v-run").addEventListener("change", loadVideos);
$("#v-more").addEventListener("click", () => { state.vLimit += 150; renderVideos(); });
bindSeg($("#v-ai"), renderVideos);
["#v-age", "#v-subs", "#v-chage", "#v-mult"].forEach((s) => $(s).addEventListener("change", renderVideos));
$("#v-search").addEventListener("input", renderVideos);
$("#v-profile").addEventListener("change", loadVideos);
bindSort($("#v-table"), state.vSort, renderVideos);
$("#btn-refresh").addEventListener("click", async () => {
  try { watchJob(await api("/api/refresh", { method: "POST" })); } catch (e) { toast(e.message, "err"); }
});
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) $(`.nav-item[data-page="${g.dataset.goto}"]`).click();
});

// ---------------------------------------------------------------- canais

async function loadChannels() {
  const pid = $("#c-profile").value;
  state.channels = await api(`/api/channels${pid ? `?profile_id=${pid}` : ""}`);
  renderChannels();
}

function renderChannels() {
  const maxAge = +$("#c-age").value, maxSubs = +$("#c-subs").value;
  const q = $("#c-search").value.trim().toLowerCase();
  const list = sortBy(state.channels.filter((c) => {
    if (maxAge && (c.channel_age_days == null || c.channel_age_days > maxAge)) return false;
    if (maxSubs && (c.subs == null || c.subs > maxSubs)) return false;
    if (q && !`${c.title} ${c.handle}`.toLowerCase().includes(q)) return false;
    return true;
  }), state.cSort);

  $("#c-table tbody").innerHTML = list.slice(0, 300).map((c) => `
    <tr>
      <td><div class="ch-cell">${c.thumb ? `<img class="avatar" loading="lazy" src="${esc(c.thumb)}" alt="">` : `<div class="avatar ini">${esc((c.title || "?").trim()[0] || "?").toUpperCase()}</div>`}
        <div><div class="link" data-ch="${esc(c.handle || "channel/" + c.channel_id)}">${esc(c.title)}</div>
        <div class="v-meta">${c.handle ? esc(c.handle) : ""}${channelTags({ channel_ai: c.ai, is_dark: c.dark, channel_format: c.format }).join("")}${c.channel_age_days != null && c.channel_age_days <= 180 ? `<span class="tag new" title="Canal criado há ${ageLong(c.channel_age_days)}">Canal novo</span>` : ""}</div></div></div></td>
      <td class="num"><span class="mult ${multClass(c.best_multiplier)}" title="${viralTip(c.best_multiplier)}">${fmtMult(c.best_multiplier)}</span></td>
      <td class="num">${fmt(c.avg_views_day)}</td>
      <td class="num">${fmt(c.subs)}</td>
      <td class="num">${fmt(c.channel_videos)}</td>
      <td class="num" title="Canal criado há ${ageLong(c.channel_age_days)}">${fmtAge(c.channel_age_days)}</td>
      <td class="num" title="Vídeos desse canal apareceram ${c.times_seen} vezes nos seus perfis">${c.times_seen}×</td>
      <td>${c.top_video ? `<span class="link v-title" data-vid="${c.top_video.video_id}" title="${esc(c.top_video.title)}">${esc(c.top_video.title)}</span>` : "—"}</td>
    </tr>`).join("");

  const empty = $("#c-empty");
  empty.hidden = list.length > 0;
  empty.innerHTML = state.channels.length ? "<b>Nenhum canal com esses filtros</b>" : "<b>Nenhum canal ainda</b>Faça uma coleta em Perfis.";
}

$("#c-table tbody").addEventListener("click", (e) => {
  const ch = e.target.closest("[data-ch]");
  if (ch) return openYT(ch.dataset.ch.startsWith("@") ? ch.dataset.ch : ch.dataset.ch);
  const v = e.target.closest("[data-vid]");
  if (v) openYT(`watch?v=${v.dataset.vid}`);
});
["#c-age", "#c-subs"].forEach((s) => $(s).addEventListener("change", renderChannels));
$("#c-search").addEventListener("input", renderChannels);
$("#c-profile").addEventListener("change", loadChannels);
bindSort($("#c-table"), state.cSort, renderChannels);

// ---------------------------------------------------------------- títulos

async function loadTitles() {
  const q = new URLSearchParams({
    max_age: $("#t-age").value, outlier: segValue($("#t-outlier")),
  });
  if ($("#t-profile").value) q.set("profile_id", $("#t-profile").value);
  const d = await api(`/api/titles?${q}`);
  const body = $("#t-body");
  if (!d.ok) {
    body.innerHTML = `<div class="box"><div class="empty"><b>Sem dados suficientes</b>${esc(d.reason)}</div></div>`;
    return;
  }
  const pct = (x) => `${Math.round(x)}%`;
  const L = d.length;
  const featMax = Math.max(1, ...d.features.map((f) => Math.max(f.pct_top, f.pct_rest)));
  const terms = (list, fmtTerm, badge, tip) => list.length
    ? list.map((w, i) => `<span class="term ${i < 5 && badge === "pct" ? "hot" : ""}" title="${esc(tip(w))}">${esc(fmtTerm(w.term))}<span>${badge === "pct" ? pct(w.pct_top) : `${w.count}×`}</span></span>`).join("")
    : `<span class="dim">Nada relevante ainda.</span>`;
  const tipPct = (w) => `Aparece em ${w.pct_top}% dos títulos que mais viralizaram e em ${w.pct_rest}% dos outros`;
  const nTerm = (t) => t.replace(/#/g, "N");

  body.innerHTML = `
    <div class="kpis">
      <div class="kpi hot" title="Quantos vídeos entraram como 'os que mais viralizaram' para comparar com o resto"><div class="k-label">Vídeos que mais viralizaram</div><div class="k-value">${d.n_top}</div>
        <div class="k-sub">de ${d.total} vídeos · a partir de ${fmtMult(d.cut)}</div></div>
      <div class="kpi" title="${TIP.viralizou}"><div class="k-label">Quanto viralizaram, normalmente</div><div class="k-value">${fmtMult(d.median_mult_top)}</div>
        <div class="k-sub">os outros: ${fmtMult(d.median_mult_rest)}</div></div>
      <div class="kpi" title="Tamanho do título (letras e espaços) dos que mais viralizaram"><div class="k-label">Tamanho do título</div><div class="k-value">${Math.round(L.chars_top)} letras</div>
        <div class="k-sub">os outros: ${Math.round(L.chars_rest)} letras</div></div>
      <div class="kpi" title="Quantas palavras têm os títulos que mais viralizaram"><div class="k-label">Palavras no título</div><div class="k-value">${Math.round(L.words_top)}</div>
        <div class="k-sub">os outros: ${Math.round(L.words_rest)}</div></div>
    </div>

    <div class="grid2">
      <div class="box">
        <div class="box-head"><h3>Jeitos de escrever o título</h3>
          <div class="legend"><span><i class="a"></i>os que viralizaram</span><span><i class="b"></i>os outros</span></div></div>
        ${d.features.map((f) => {
          const diff = f.pct_top - f.pct_rest;
          return `<div class="frow">
            <div class="fl" title="Com isso no título, os vídeos viralizam ${fmtMult(f.mult_with)} (normalmente). Sem, viralizam ${fmtMult(f.mult_without)}.">${esc(f.label)}<small>com: viraliza ${fmtMult(f.mult_with)} · sem: ${fmtMult(f.mult_without)}</small></div>
            <div class="dbar">
              <div class="a"><b style="width:${(f.pct_top / featMax) * 100}%"></b>${pct(f.pct_top)}</div>
              <div class="b"><b style="width:${(f.pct_rest / featMax) * 100}%"></b>${pct(f.pct_rest)}</div>
            </div>
            <div class="delta ${diff > 0 ? "pos" : "neg"}" title="${diff > 0 ? "Os que viralizaram usam mais isso" : "Os que viralizaram usam menos isso"}">${diff > 0 ? "+" : ""}${Math.round(diff)}%</div>
          </div>`;
        }).join("")}
      </div>

      <div class="stack">
        <div class="box">
          <div class="box-head"><h3>Palavras que mais aparecem nos que viralizaram</h3><div class="legend">% dos títulos que usam</div></div>
          <div class="terms">${terms(d.words, (t) => t, "pct", tipPct)}</div>
        </div>
        <div class="box">
          <div class="box-head"><h3>Duplas de palavras que se repetem</h3></div>
          <div class="terms">${terms(d.bigrams, nTerm, "pct", tipPct)}</div>
        </div>
        <div class="box">
          <div class="box-head"><h3>Como os títulos começam</h3><div class="legend">as 2 primeiras palavras</div></div>
          <div class="terms">${terms(d.openings, (t) => `${nTerm(t)}…`, "count", (o) => `Títulos que começam assim viralizam ${fmtMult(o.mult)}, normalmente`)}</div>
        </div>
      </div>
    </div>

    <div class="box">
      <div class="box-head"><h3>Títulos que mais viralizaram</h3><div class="legend">clique para ver o vídeo</div></div>
      <div class="olist">${d.examples.map((v) => `
        <div class="orow" data-id="${v.video_id}">
          <img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
          <span class="otitle" title="${esc(v.title)}">${esc(v.title)}</span>
          <span class="ometa">${esc(v.channel_title || "")} · ${fmt(v.views)} views</span>
          <span class="mult ${multClass(v.multiplier)}" title="${viralTip(v.multiplier)}">${fmtMult(v.multiplier)}</span>
        </div>`).join("")}</div>
    </div>`;
}

$("#t-body").addEventListener("click", (e) => {
  const r = e.target.closest(".orow");
  if (r) openPreview(r.dataset.id);
});
bindSeg($("#t-outlier"), loadTitles);
$("#t-age").addEventListener("change", loadTitles);
$("#t-profile").addEventListener("change", loadTitles);

// ---------------------------------------------------------------- perfis

const ICON_PROFILE = `<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>`;
const ICON_JOKER = `<svg viewBox="0 0 24 24"><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z"/></svg>`;

async function loadProfiles() {
  state.profiles = await api("/api/profiles");
  fillProfileSelects();
  const wrap = $("#profiles");
  if (!state.profiles.length) {
    wrap.innerHTML = `<div class="card" style="grid-column:1/-1"><div class="empty"><b>Nenhum perfil ainda</b>
      Adicione um perfil do Chrome já treinado no nicho, ou um perfil "coringa" que consome vários nichos dark.</div></div>`;
  } else {
    wrap.innerHTML = state.profiles.map((p) => `
      <div class="card" data-pid="${p.id}">
        <div class="card-top">
          <div class="card-icon ${p.kind}">${p.kind === "coringa" ? ICON_JOKER : ICON_PROFILE}</div>
          <div style="flex:1;min-width:0">
            <div class="card-title">${esc(p.name)}</div>
            <div class="card-sub">${p.kind === "coringa" ? "Coringa" : "Nicho"}${p.niche ? ` · ${esc(p.niche)}` : " · sem nicho"}<button class="icon-btn edit-pen" data-act="edit-niche" title="Corrigir nicho e tipo"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg></button></div>
          </div>
          <button class="icon-btn" data-act="delete" title="Excluir perfil"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>
        <div class="card-stats">
          <div><b>${p.runs}</b><span>coletas</span></div>
          <div><b>${fmt(p.videos)}</b><span>vídeos</span></div>
          <div><b>${p.last_run_at ? new Date(p.last_run_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "—"}</b><span>última</span></div>
        </div>
        ${p.in_use ? `<div class="alert warn">Aberto no Chrome agora: feche a janela para coletar.</div>` : ""}
        <div class="card-actions">
          <label class="scrolls" title="Quantas vezes rolar a página inicial do YouTube. Mais = mais vídeos (e mais demora)">Rolar <input class="input" type="number" min="1" max="80" value="15" data-scrolls></label>
          <label class="check" title="Mostra a janela do Chrome enquanto coleta (para acompanhar)"><input type="checkbox" data-show> mostrar o Chrome</label>
          <span class="spacer"></span>
        </div>
        <div class="card-actions">
          <button class="btn primary sm" data-act="collect" title="Entra no perfil, rola a página inicial e anota os vídeos que o YouTube mostrar">Coletar agora</button>
          <button class="btn sm" data-act="open" title="Abre o Chrome nesse perfil para você entrar na conta do YouTube">Entrar na conta</button>
        </div>
        <div class="card-actions">
          <button class="btn sm" data-act="history" title="Anota os vídeos que esse perfil assistiu (o histórico do YouTube)">Coletar o que assistiu</button>
          <button class="btn ghost sm" data-act="train" title="Abre o Chrome do perfil já pesquisando o nicho. Assista alguns vídeos para o YouTube aprender o que mostrar">Treinar o perfil</button>
        </div>
      </div>`).join("");
  }
  loadRuns();
}

async function loadRuns() {
  const runs = await api("/api/runs");
  const label = { done: "Concluída", error: "Erro", running: "Rodando" };
  $("#runs-table tbody").innerHTML = runs.length ? runs.map((r) => `
    <tr><td>${esc(r.profile_name || "—")}</td><td>${fmtDate(r.started_at)}</td>
    <td><span class="status ${r.status}">${label[r.status] || r.status}</span>${r.status === "done" && !r.logged_in ? ` <span class="tag fresh">sem login</span>` : ""}</td>
    <td class="num">${r.videos_found || 0}</td><td class="dim small">${esc(r.error || "")}</td>
    <td class="col-act">${r.status === "running" ? "" : `<button class="icon-btn row-del" data-run="${r.id}" title="Excluir esta coleta e os vídeos que só apareceram nela">
      <svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg></button>`}</td></tr>`).join("")
    : `<tr><td colspan="6" class="dim">Nenhuma coleta ainda.</td></tr>`;
}

$("#runs-table").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-run]");
  if (!b) return;
  if (!confirm("Excluir esta coleta?\n\nOs vídeos que só apareceram nela somem, junto com os números, comentários e canais que só ela trouxe. O que também apareceu em outra coleta ou pesquisa continua.")) return;
  try {
    const r = await api(`/api/runs/${b.dataset.run}`, { method: "DELETE" });
    toast(`Coleta excluída · ${r.videos} vídeos e ${r.channels} canais removidos.`, "ok");
    refreshAll();
    loadProfiles();
  } catch (err) { toast(err.message, "err"); }
});

$("#profiles").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const card = btn.closest("[data-pid]"), pid = card.dataset.pid;
  const p = state.profiles.find((x) => x.id == pid);
  try {
    if (btn.dataset.act === "collect") {
      const scrolls = +$("[data-scrolls]", card).value || 15;
      const show_browser = $("[data-show]", card).checked;
      watchJob(await api(`/api/profiles/${pid}/collect`, { method: "POST", body: { scrolls, show_browser } }));
    } else if (btn.dataset.act === "history") {
      const scrolls = +$("[data-scrolls]", card).value || 15;
      const show_browser = $("[data-show]", card).checked;
      watchJob(await api(`/api/profiles/${pid}/collect`, { method: "POST", body: { scrolls, show_browser, source: "history" } }));
    } else if (btn.dataset.act === "train") {
      const query = prompt("O que treinar neste perfil? (abre a busca do YouTube no Chrome dele)", p.niche || "");
      if (query === null) return;
      await api(`/api/profiles/${pid}/train`, { method: "POST", body: { query } });
      toast("Chrome aberto na busca. Assista vídeos do nicho e feche a janela antes de coletar.");
      setTimeout(loadProfiles, 1500);
    } else if (btn.dataset.act === "open") {
      await api(`/api/profiles/${pid}/open`, { method: "POST" });
      toast("Chrome aberto. Logue/treine e feche a janela antes de coletar.");
      setTimeout(loadProfiles, 1500);
    } else if (btn.dataset.act === "edit-niche") {
      editNiche(card, p);
    } else if (btn.dataset.act === "delete") {
      if (!confirm(`Excluir o perfil "${p.name}"? Os vídeos coletados continuam no banco.`)) return;
      await api(`/api/profiles/${pid}`, { method: "DELETE" });
      toast("Perfil excluído.");
      loadProfiles();
    }
  } catch (err) { toast(err.message, "err"); }
});

// Corrigir o nicho/tipo quando a IA errou (ou para preencher na mão).
function editNiche(card, p) {
  const sub = $(".card-sub", card);
  sub.outerHTML = `<div class="niche-edit">
    <input class="input grow" value="${esc(p.niche || "")}" placeholder="Nicho do perfil">
    <select class="select"><option value="nicho">Nicho</option><option value="coringa">Coringa</option></select></div>`;
  const box = $(".niche-edit", card), input = $("input", box), sel = $("select", box);
  sel.value = p.kind;
  input.focus();
  input.select();
  let done = false;
  const save = async (ok) => {
    if (done) return;
    done = true;
    if (ok) {
      try {
        await api(`/api/profiles/${p.id}`, { method: "PATCH", body: { name: p.name, kind: sel.value, niche: input.value } });
        toast("Nicho atualizado.", "ok");
      } catch (e) { toast(e.message, "err"); }
    }
    state.profiles = await api("/api/profiles");
    loadProfiles();
  };
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") save(true); if (e.key === "Escape") save(false); });
  box.addEventListener("focusout", () => setTimeout(() => { if (!box.contains(document.activeElement)) save(true); }, 0));
}

// ---------------------------------------------------------------- modal: novo perfil

let chromeChoice = null;

async function openModal(keepFields = false) {
  $("#modal").hidden = false;
  if (keepFields !== true) {
    $("#m-name").value = "";
    $("#m-niche").value = "";
  }
  chromeChoice = null;
  nicheReq++;
  $("#m-ai").hidden = true;
  const list = $("#m-chrome");
  list.innerHTML = `<div class="muted small">Procurando perfis do Chrome…</div>`;
  try {
    const d = await api("/api/chrome-profiles");
    if (!d.chrome_found) {
      list.innerHTML = `<div class="alert warn">Google Chrome não encontrado neste PC.</div>`;
      return;
    }
    list.innerHTML = d.profiles.map((p) => `
      <div class="chrome-opt" data-folder="${esc(p.folder)}" data-name="${esc(p.name)}" data-email="${esc(p.email)}">
        <div class="avatar">${esc(p.name[0] || "?").toUpperCase()}</div>
        <div class="grow"><b>${esc(p.name)}</b><small>${esc(p.email || "sem conta Google")} · ${esc(p.folder)}</small></div>
        ${p.open ? `<span class="tag fresh" title="Feche as janelas deste perfil para importar">Aberto agora</span>` : ""}
      </div>`).join("") +
      (d.profiles.some((p) => p.open) ? `<div class="alert warn row-alert"><span>Perfis marcados como <b>Aberto agora</b> precisam ter as janelas fechadas para importar. Os outros podem ser importados com o Chrome aberto.</span>
        <button class="btn sm" id="m-recheck">Verificar de novo</button></div>` : "");
  } catch (e) { list.innerHTML = `<div class="alert warn">${esc(e.message)}</div>`; }
}
const closeModal = () => { $("#modal").hidden = true; };

$("#btn-new-profile").addEventListener("click", () => openModal());
$$("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeResearchModal(); closeRunsModal(); closePreview(); } });
bindSeg($("#m-mode"), (v) => { $("#m-import").hidden = v !== "import"; $("#m-new").hidden = v !== "new"; });
bindSeg($("#m-kind"), () => {});
$("#m-chrome").addEventListener("click", async (e) => {
  if (e.target.closest("#m-recheck")) {
    const keep = chromeChoice;
    await openModal(true);
    if (keep) $(`.chrome-opt[data-folder="${CSS.escape(keep)}"]`)?.click();
    return;
  }
  const opt = e.target.closest(".chrome-opt");
  if (!opt) return;
  $$(".chrome-opt").forEach((x) => x.classList.toggle("on", x === opt));
  const changed = chromeChoice !== opt.dataset.folder;
  chromeChoice = opt.dataset.folder;
  if (!$("#m-name").value || changed) $("#m-name").value = opt.dataset.name;
  if (changed) suggestNiche(opt.dataset.folder, opt.dataset.email);
});

// Sugestão de nicho pela IA a partir do histórico local do perfil (fica em cache: não gasta de novo).
let nicheReq = 0, nicheAuto = "";
async function suggestNiche(folder, email) {
  const req = ++nicheReq, hint = $("#m-ai"), input = $("#m-niche");
  if (input.value && input.value !== nicheAuto) return;  // o usuário já escreveu algo
  input.value = nicheAuto = "";
  hint.hidden = false;
  hint.className = "ai-hint loading";
  hint.textContent = "IA lendo o histórico do perfil…";
  const d = await api(`/api/chrome-profiles/${encodeURIComponent(folder)}/niche?email=${encodeURIComponent(email)}`)
    .catch((e) => ({ ok: false, reason: e.message }));
  if (req !== nicheReq) return;  // escolheram outro perfil nesse meio-tempo
  if (!d.ok) {
    hint.className = "ai-hint";
    hint.textContent = d.reason.startsWith("Poucos títulos")
      ? "Histórico local curto: a IA detecta o nicho na primeira coleta, pela home do perfil."
      : d.reason;
    return;
  }
  input.value = nicheAuto = d.niche;
  $$("#m-kind button").forEach((b) => b.classList.toggle("on", b.dataset.v === d.kind));
  hint.className = "ai-hint ok";
  hint.innerHTML = `<b>Sugerido pela IA</b> · confiança ${esc(d.confidence)} · ${esc(d.reason)}`;
}

$("#m-save").addEventListener("click", async () => {
  const mode = segValue($("#m-mode"));
  const body = { name: $("#m-name").value, niche: $("#m-niche").value, kind: segValue($("#m-kind")) };
  if (!body.name.trim()) return toast("Dê um nome ao perfil.", "err");
  if (mode === "import") {
    if (!chromeChoice) return toast("Escolha um perfil do Chrome.", "err");
    body.chrome_folder = chromeChoice;
  }
  try {
    const res = await api("/api/profiles", { method: "POST", body });
    closeModal();
    if (res.job) watchJob(res.job);
    else toast("Perfil criado. Clique em 'Abrir p/ login' para entrar na conta.", "ok");
    loadProfiles();
  } catch (e) { toast(e.message, "err"); }
});

// ---------------------------------------------------------------- pesquisa de mercado

const R = { list: [], current: null, data: null, filter: "dark", rel: 2, pot: 1, age: 0, sort: { key: "score", dir: -1 } };
const VIA_LABELS = {
  semente: "Seu vídeo", sugerido: "Sugerido", "busca:recente": "Busca: da semana",
  "busca:top-mes": "Busca: mais vistos do mês", "busca:top-ano": "Busca: mais vistos do ano",
  "busca:top-semana": "Busca: mais vistos da semana", "busca:relevante": "Busca",
  "busca:variacao": "Busca: título parecido", "canal:recente": "Vídeo novo de concorrente", historico: "Perfil assistiu",
};
const VIA_TIP = {
  semente: "O vídeo de onde a pesquisa partiu", sugerido: "Apareceu nos vídeos sugeridos do YouTube",
  "busca:variacao": "Achado buscando versões parecidas do título", "canal:recente": "Vídeo recente de um canal concorrente",
  historico: "Vídeo que o perfil assistiu",
};
const REL_TAG = { 3: `<span class="tag good" title="Mesmo assunto e mesmo jeito de vídeo: é um concorrente direto, dá para copiar">Mesmo formato</span>`,
  2: `<span class="tag neutral" title="Mesmo assunto, mas o vídeo é feito de outro jeito">Mesmo assunto</span>`,
  1: `<span class="tag via" title="Assunto parecido, mas não é o mesmo">Parecido</span>` };

async function loadResearch() {
  R.list = await api(`/api/research${state.profile ? `?profile_id=${state.profile}` : ""}`);
  if (R.current == null && R.list.length) R.current = R.list[0].id;
  renderResearchList();
  if (R.current != null) await openResearch(R.current, true);
  else renderResearchEmpty();
}

function renderResearchEmpty() {
  $("#r-detail").innerHTML = `<div class="box"><div class="empty"><b>Nenhuma pesquisa ainda</b>
    Comece por um vídeo de referência (o darkbot navega pelos sugeridos) ou por palavras-chave do nicho.
    <div class="empty-actions"><button class="btn primary sm" data-rnew="video">Partir de um vídeo</button>
    <button class="btn sm" data-rnew="keyword">Palavras-chave</button></div></div></div>`;
}

function renderResearchList() {
  $("#r-list").innerHTML = R.list.length ? R.list.map((r) => `
    <div class="r-item ${r.id === R.current ? "on" : ""}" data-rid="${r.id}">
      ${r.kind === "video" ? `<img src="https://i.ytimg.com/vi/${esc(r.seed)}/mqdefault.jpg" alt="">`
        : `<div class="r-kw-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg></div>`}
      <div class="r-item-body">
        <div class="r-item-title">${esc(r.label)}</div>
        ${r.profile_id == null && state.profile ? `<div class="r-item-legacy" title="Pesquisa antiga, de antes de separar por perfil">sem perfil · <span class="link" data-move="${r.id}">trazer para este perfil</span></div>` : ""}
        <div class="r-item-meta">${fmtDate(r.created_at)} · ${r.status === "running" ? `<span class="up">rodando…</span>`
          : r.status === "error" ? `<span class="err-text">erro</span>`
          : r.status === "cancelled" ? `cancelada · ${r.videos_found} vídeos` : `${r.videos_found} vídeos`}${r.has_report ? ` · <span class="tag ai">relatório</span>` : ""}</div>
      </div>
    </div>`).join("") : `<div class="muted small r-list-empty">As pesquisas ficam guardadas aqui.</div>`;
}

$("#r-list").addEventListener("click", async (e) => {
  const mv = e.target.closest("[data-move]");
  if (mv) {
    e.stopPropagation();
    await api(`/api/research/${mv.dataset.move}/profile`, { method: "POST", body: { profile_id: state.profile } });
    toast("Pesquisa trazida para este perfil.", "ok");
    return loadResearch();
  }
  const it = e.target.closest("[data-rid]");
  if (it) openResearch(+it.dataset.rid);
});

async function openResearch(id, quiet = false) {
  R.current = id;
  renderResearchList();
  if (!quiet) $("#r-detail").innerHTML = `<div class="box"><div class="empty">Carregando…</div></div>`;
  try { R.data = await api(`/api/research/${id}`); } catch (e) { return toast(e.message, "err"); }
  renderResearch();
}

// "[videoId]" no texto da IA vira link para o vídeo.
function linkIds(text) {
  return esc(text).replace(/\[([A-Za-z0-9_-]{11})\]/g, (_, id) => `<span class="vid-ref" data-vref="${id}" title="Abrir vídeo">▶ ${videoTitle(id, 32)}</span>`);
}
function videoTitle(id, max = 60) {
  const v = R.data?.videos.find((x) => x.video_id === id);
  const t = v?.title || id;
  return esc(t.length > max ? t.slice(0, max - 1) + "…" : t);
}

function renderResearch() {
  const { research: r, videos, report, report_meta: meta } = R.data;
  const dark = videos.filter((v) => v.is_dark).length;
  const recent = videos.filter((v) => v.age_days != null && v.age_days <= 30).length;
  const head = `
    <div class="box r-head">
      <div class="r-head-top">
        ${r.kind === "video" ? `<img class="r-seed" data-vref="${esc(r.seed)}" src="https://i.ytimg.com/vi/${esc(r.seed)}/mqdefault.jpg" alt="">` : ""}
        <div class="grow">
          <div class="r-kicker">${r.kind === "video" ? "Partiu do vídeo" : "Palavras-chave"} · ${fmtDate(r.created_at)}</div>
          <h2>${esc(r.label)}</h2>
          ${r.topic ? `<div class="r-topic" title="O que a IA entendeu do seu vídeo"><div><span>Assunto</span>${esc(r.topic.theme)}</div><div><span>Tipo</span>${esc(r.topic.format)}</div>
            <div><span>Gancho</span>${esc(r.topic.angle)}</div></div>` : ""}
          ${(() => {
            const variants = r.topic?.variants || [];
            const queries = r.keywords.filter((k) => !variants.includes(k));
            const chip = (k) => `<span class="term sm" data-kw="${esc(k)}" title="Pesquisar só esta busca">${esc(k)}</span>`;
            return (queries.length ? `<div class="terms r-kws">${queries.map(chip).join("")}</div>` : "") +
              (variants.length ? `<details class="r-variants"><summary title="A IA trocou detalhes do título para achar vídeos parecidos">Títulos parecidos que a IA pesquisou (${variants.length})</summary>
                <div class="terms r-kws">${variants.map(chip).join("")}</div></details>` : "");
          })()}
        </div>
        <div class="r-head-actions">
          ${r.status === "done" || r.status === "cancelled" ? (r.run_id
            ? `<button class="btn ghost sm" id="r-to-disc" data-run="${r.run_id}" title="Já é uma coleta: ver em Descobertas">Ver em Descobertas</button>`
            : `<button class="btn sm" id="r-to-disc" title="Vira uma coleta (marcada como pesquisa) e os vídeos relevantes aparecem em Descobertas">Enviar para Descobertas</button>`) : ""}
          ${r.status === "done" || r.status === "cancelled" ? `<button class="btn ${report ? "" : "primary"} sm" id="r-report-btn">${report ? "Refazer relatório" : "Gerar relatório com IA"}</button>` : ""}
          <button class="icon-btn" id="r-del" title="Excluir pesquisa"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>
      </div>
      ${r.status === "error" ? `<div class="alert warn">${esc(r.error)}</div>` : ""}
      ${r.status === "running" ? `<div class="alert info">Pesquisa rodando… acompanhe no canto da tela (dá para cancelar por lá).</div>` : ""}
      ${r.status === "cancelled" ? `<div class="alert info">Pesquisa cancelada: aqui está o que já tinha sido feito. Dá para gerar o relatório com esses vídeos.</div>` : ""}
      <div class="r-stats">
        <div title="Quantos vídeos a pesquisa achou"><b>${videos.length}</b><span>vídeos achados</span></div>
        <div title="Vídeos de canais dark (ninguém aparece)"><b>${dark}</b><span>de canais dark</span></div>
        <div title="Vídeos postados nos últimos 30 dias"><b>${recent}</b><span>postados no último mês</span></div>
        <div title="Vídeos que tiveram os comentários lidos pela IA"><b>${Object.keys(R.data.comments).length}</b><span>com comentários lidos</span></div>
        ${meta ? `<div title="Quanto custou o relatório da IA"><b>${fmtUSD(meta.cost_usd)}</b><span>custo do relatório</span></div>` : ""}
      </div>
    </div>`;
  const mal = r.kind === "video" ? `<div class="box mal-box"><div class="box-head"><h3>Método Malandro</h3>
    <span class="dim small">em que língua ninguém fez este vídeo ainda</span></div>${renderMalandro(R.data.malandro, r.seed)}</div>` : "";
  const vars = r.kind === "video" ? `<div class="box"><div class="box-head"><h3>Ideias de variações deste vídeo</h3>
    <span class="dim small">com a chance de viralizar</span></div>${renderVariations(R.data.variations, r.seed)}</div>` : "";
  $("#r-detail").innerHTML = head + vars + mal + renderSaturation() + (report ? renderReport(report) : "") + renderResearchVideos() + renderComments();
  bindResearchTable();
}

function renderReport(rep) {
  const lvl = (x) => ({ baixa: "Baixa", media: "Média", alta: "Alta" }[x] || x);
  const strength = { forte: "good", media: "warn", fraca: "neutral" };
  return `
    <div class="box r-summary">
      <div class="box-head"><h3>Resumo do nicho</h3>
        <div class="r-levels"><span class="lvl ${rep.opportunity}" title="Quanta chance um vídeo novo tem de dar certo nesse nicho">Chance de dar certo: ${lvl(rep.opportunity)}</span>
        <span class="lvl sat-${rep.saturation}" title="Quantos canais já estão fazendo isso">Concorrência: ${lvl(rep.saturation)}</span></div></div>
      <p class="r-lead">${linkIds(rep.summary)}</p>
    </div>

    <div class="box"><div class="box-head"><h3>Copie estes agora</h3><span class="dim small">vídeos recentes que viralizaram</span></div>
      <div class="model-list">${rep.to_model.map((m, i) => {
        const v = R.data.videos.find((x) => x.video_id === m.video_id);
        return `<div class="model-row" data-vref="${esc(m.video_id)}">
          <span class="rank">${i + 1}</span>
          <img src="https://i.ytimg.com/vi/${esc(m.video_id)}/mqdefault.jpg" alt="">
          <div class="grow"><div class="otitle">${videoTitle(m.video_id, 90)}</div>
            <div class="model-why">${linkIds(m.why)}</div>
            ${v ? `<div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span><span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span>
              <span>${fmt(v.views)} views</span><span>${fmtAge(v.age_days)}</span></div>` : ""}</div>
          ${seedBtn(m.video_id)}
        </div>`; }).join("")}</div>
    </div>

    <div class="grid2">
      <div class="box"><div class="box-head"><h3>O que está funcionando</h3></div>
        <ul class="r-bullets">${rep.what_works.map((x) => `<li>${linkIds(x)}</li>`).join("")}</ul></div>
      <div class="box"><div class="box-head"><h3>Modelos de título</h3><span class="dim small">troque o que está entre [ ]</span></div>
        <div class="formulas">${rep.title_formulas.map((x) => `<div class="formula" data-copy="${esc(x)}" title="Copiar">${esc(x)}</div>`).join("")}</div></div>
    </div>

    <div class="box"><div class="box-head"><h3>O que o público está pedindo</h3><span class="dim small">tirado dos comentários</span></div>
      <div class="asks">${rep.audience_requests.map((a) => `
        <div class="ask"><div class="ask-top"><b>${esc(a.request)}</b><span class="tag ${strength[a.strength]}">sinal ${a.strength === "media" ? "médio" : a.strength}</span></div>
        <div class="ask-quote">“${linkIds(a.evidence.replace(/^["“”'\s]+|["“”'\s]+$/g, ""))}”</div></div>`).join("")}</div>
    </div>

    <div class="box"><div class="box-head"><h3>Ideias de vídeo prontas</h3><span class="dim small">clique em um texto para copiar</span></div>
      <div class="ideas">${rep.ideas.map((d, i) => `
        <div class="idea">
          <div class="idea-n">Ideia ${i + 1}</div>
          <div class="idea-title" data-copy="${esc(d.title)}">${esc(d.title)}</div>
          <div class="idea-alts">${d.alt_titles.map((t) => `<span data-copy="${esc(t)}">${esc(t)}</span>`).join("")}</div>
          <div class="idea-label">Gancho</div>
          <div class="idea-hook" data-copy="${esc(d.hook)}">${esc(d.hook)}</div>
          <div class="idea-label">Estrutura do roteiro</div>
          <ol class="idea-structure">${d.structure.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
          <div class="idea-label">Descrição</div>
          <div class="idea-desc" data-copy="${esc(d.description)}">${esc(d.description)}</div>
          <div class="idea-label">Tags</div>
          <div class="terms" data-copy="${esc(d.tags.join(", "))}">${d.tags.map((t) => `<span class="term sm">${esc(t)}</span>`).join("")}</div>
          <div class="idea-why"><b>Por que agora:</b> ${linkIds(d.why_now)}</div>
          ${d.based_on.length ? `<div class="idea-refs">${d.based_on.map((id) => `<img data-vref="${esc(id)}" title="${videoTitle(id)}" src="https://i.ytimg.com/vi/${esc(id)}/mqdefault.jpg" alt="">`).join("")}</div>` : ""}
        </div>`).join("")}</div>
    </div>

    <div class="grid2">
      <div class="box"><div class="box-head"><h3>Palavras para pesquisar e usar nas tags</h3><span class="dim small">clique para pesquisar</span></div>
        <div class="terms">${rep.keywords.map((k) => `<span class="term sm clickable" data-kw="${esc(k)}">${esc(k)}</span>`).join("")}</div></div>
      <div class="box"><div class="box-head"><h3>Não faça</h3></div>
        <ul class="r-bullets avoid">${rep.avoid.map((x) => `<li>${linkIds(x)}</li>`).join("")}</ul></div>
    </div>`;
}

// Onde o formato do vídeo de referência já foi modelado (concorrentes diretos por idioma).
function renderSaturation() {
  const sat = R.data.saturation || [];
  if (!sat.length) return "";
  const name = Object.fromEntries((state.langs || []).map((l) => [l.code, l.name]));
  const picked = (R.data.research.langs ? JSON.parse(R.data.research.langs) : []);
  const gaps = picked.filter((l) => !sat.some((s) => s.lang === l && s.recent_channels >= 2));
  const level = (s) => s.recent_channels >= 6 ? ["alta", "lvl sat-alta"] : s.recent_channels >= 2 ? ["média", "lvl media"] : ["baixa", "lvl sat-baixa"];
  return `<div class="box"><div class="box-head"><h3>Em que idiomas já copiaram esse vídeo</h3><span class="dim small">quanto mais canais, mais concorrência</span></div>
    <table class="table compact sat-table"><thead><tr><th>Idioma</th><th class="num">Vídeos</th><th class="num">Canais</th>
      <th class="num" title="Canais que fizeram nos últimos 30 dias">Canais no último mês</th><th class="num" title="${TIP.viralizou}">Viralizam, normalmente</th><th title="Quanta gente já está fazendo">Concorrência</th><th title="O que mais viralizou nesse idioma">O que mais viralizou</th></tr></thead><tbody>
    ${sat.map((s) => { const [lab, cls] = level(s); return `<tr><td><b>${esc(name[s.lang] || s.lang.toUpperCase())}</b></td>
      <td class="num">${s.videos}</td><td class="num">${s.channels}</td><td class="num">${s.recent_channels}</td>
      <td class="num">${s.median_mult != null ? fmtMult(s.median_mult) : "—"}</td><td><span class="${cls}">${lab}</span></td>
      <td class="sat-best">${s.best ? `<span class="dim">${fmtMult(s.best.multiplier)}</span> <span class="vid-ref" data-vref="${s.best.video_id}" title="${esc(s.best.title)}">▶ ${esc(s.best.title)}</span>` : "—"}</td></tr>`; }).join("")}
    </tbody></table>
    ${gaps.length ? `<div class="sat-gap">Espaço livre: quase ninguém fez esse vídeo no último mês em <b>${gaps.map((l) => esc(name[l] || l)).join(", ")}</b>. Dá para fazer nesses idiomas.</div>` : ""}
  </div>`;
}

function researchFiltered() {
  return sortBy(R.data.videos.filter((v) => {
    if (R.filter === "dark" && !v.is_dark) return false;
    if (R.filter === "ai" && !v.channel_ai) return false;
    if (v.relevance != null && v.relevance < R.rel && v.via !== "semente") return false;
    if (R.pot && !v.potential && v.via !== "semente") return false;
    if (R.age && (v.age_days == null || v.age_days > R.age)) return false;
    return true;
  }), R.sort);
}

function renderResearchVideos() {
  const list = researchFiltered();
  const segBtn = (v, label, cur) => `<button data-v="${v}" class="${cur == v ? "on" : ""}">${label}</button>`;
  return `
    <div class="box r-videos">
      <div class="box-head"><h3>Vídeos encontrados</h3>
        <button class="btn ghost sm" id="rv-translate" title="Traduz os títulos em outros idiomas (Haiku, uma vez por vídeo)">Traduzir títulos</button>
        <div class="r-filters">
          <div class="seg sm" id="rv-pot" title="Só os bons: vídeos que tiveram mais views que os inscritos do canal ou que fazem mais de 1.000 views por dia">${segBtn(1, "Só os bons", R.pot)}${segBtn(0, "Mostrar todos", R.pot)}</div>
          <div class="seg sm" id="rv-rel" title="O quanto o vídeo tem a ver com o que você pesquisou (a IA decide)">${segBtn(3, "Mesmo formato", R.rel)}${segBtn(2, "Mesmo assunto", R.rel)}${segBtn(1, "Parecidos", R.rel)}</div>
          <div class="seg sm" id="rv-type" title="Tipo de canal">${segBtn("all", "Qualquer canal", R.filter)}${segBtn("dark", "Só dark", R.filter)}${segBtn("ai", "Feito com IA", R.filter)}</div>
          <div class="seg sm" id="rv-age">${segBtn(0, "Qualquer data", R.age)}${segBtn(30, "30 dias", R.age)}${segBtn(90, "90 dias", R.age)}</div>
        </div></div>
      <table class="table" id="rv-table">
        <thead><tr>
          <th class="col-thumb"></th><th data-sort="title">Vídeo</th>
          <th data-sort="score" class="num" title="${TIP.nota}">Nota</th>
          <th data-sort="multiplier" class="num" title="${TIP.viralizou}">Viralizou</th><th data-sort="views" class="num" title="Total de views">Views</th>
          <th data-sort="views_day" class="num" title="Views por dia, em média">Views por dia</th><th data-sort="subs" class="num" title="Inscritos do canal">Inscritos</th>
          <th data-sort="age_days" class="num" title="Há quanto tempo foi postado">Postado há</th><th class="col-act"></th>
        </tr></thead>
        <tbody>${list.slice(0, 200).map((v) => {
          const tags = [...(REL_TAG[v.relevance] ? [REL_TAG[v.relevance]] : []),
            `<span class="tag via" title="${VIA_TIP[v.via] || "Achado numa busca do YouTube"}">${VIA_LABELS[v.via] || v.via}</span>`, ...channelTags(v), ...newTags(v)];
          return `<tr class="clickable" data-vref="${v.video_id}">
            <td><div class="thumb"><img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
              ${v.duration_s != null ? `<span class="dur">${fmtDur(v.duration_s)}</span>` : ""}</div></td>
            <td>${titleCell(v)}
              <div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span>${langTag(v)}${tags.join("")}</div></td>
            <td class="num" title="${TIP.nota}"><b class="score">${v.score != null ? v.score.toFixed(1).replace(".", ",") : "—"}</b></td>
            <td class="num"><span class="mult ${multClass(v.multiplier)}" title="${viralTip(v.multiplier)}">${fmtMult(v.multiplier)}</span></td>
            <td class="num" title="${fmt(v.views)} views no total">${fmt(v.views)}</td><td class="num" title="Faz ${fmt(v.views_day)} views por dia">${fmt(v.views_day)}</td>
            <td class="num" title="O canal tem ${fmt(v.subs)} inscritos">${fmt(v.subs)}</td><td class="num" title="Postado há ${ageLong(v.age_days)}">${fmtAge(v.age_days)}</td>
            <td class="col-act">${rowActions(v)}</td></tr>`;
        }).join("")}</tbody>
      </table>
      ${list.length ? "" : `<div class="empty"><b>Nada nesse filtro</b>Tente "Todos".</div>`}
    </div>`;
}

function renderComments() {
  const entries = Object.entries(R.data.comments);
  if (!entries.length) return "";
  return `<div class="box"><div class="box-head"><h3>Comentários que a IA leu</h3><span class="dim small">os mais curtidos dos melhores vídeos</span></div>
    ${entries.map(([id, cms]) => `<details class="cm-video"><summary>${videoTitle(id, 90)} <span class="dim">· ${cms.length}</span></summary>
      ${cms.map((c) => `<div class="cm"><span class="cm-likes">♥ ${fmt(c.likes)}</span>${esc(c.text)}</div>`).join("")}</details>`).join("")}
  </div>`;
}

function bindResearchTable() {
  const table = $("#rv-table");
  if (!table) return;
  $$("th[data-sort]", table).forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === R.sort.key);
    th.classList.toggle("asc", th.dataset.sort === R.sort.key && R.sort.dir === 1);
    th.addEventListener("click", () => {
      R.sort = R.sort.key === th.dataset.sort ? { key: th.dataset.sort, dir: -R.sort.dir } : { key: th.dataset.sort, dir: -1 };
      rerenderResearchVideos();
    });
  });
  bindSeg($("#rv-type"), (v) => { R.filter = v; rerenderResearchVideos(); });
  bindSeg($("#rv-age"), (v) => { R.age = +v; rerenderResearchVideos(); });
  bindSeg($("#rv-rel"), (v) => { R.rel = +v; rerenderResearchVideos(); });
  bindSeg($("#rv-pot"), (v) => { R.pot = +v; rerenderResearchVideos(); });
}
function rerenderResearchVideos() {
  const box = $(".r-videos");
  box.outerHTML = renderResearchVideos();
  bindResearchTable();
}

$("#r-detail").addEventListener("click", async (e) => {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    try { await navigator.clipboard.writeText(copy.dataset.copy); toast("Copiado.", "ok"); } catch { toast("Não consegui copiar.", "err"); }
    return;
  }
  const kw = e.target.closest("[data-kw]");
  if (kw) return startResearch({ kind: "keyword", seed: kw.dataset.kw, report: true });
  const vref = e.target.closest("[data-vref]");
  if (vref) return openPreview(vref.dataset.vref);
  if (e.target.closest("#r-report-btn")) {
    const has = !!R.data.report;
    if (has && !confirm("Refazer o relatório gasta tokens de novo (cerca de US$ 0,05 a 0,10). Continuar?")) return;
    try { watchJob(await api(`/api/research/${R.current}/report`, { method: "POST" })); } catch (err) { toast(err.message, "err"); }
    return;
  }
  const td = e.target.closest("#r-to-disc");
  if (td) {
    try {
      const res = td.dataset.run ? { run_id: +td.dataset.run } : await api(`/api/research/${R.current}/to-discoveries`, { method: "POST" });
      if (!td.dataset.run) toast(`${res.videos} vídeos enviados para Descobertas como uma coleta.`, "ok");
      await loadRunOptions();
      $("#v-run").value = String(res.run_id);
      $('.nav-item[data-page="videos"]').click();
      await Promise.all([loadVideos(), loadOverview()]);
    } catch (err) { toast(err.message, "err"); }
    return;
  }
  if (e.target.closest("#r-del")) {
    if (!confirm("Excluir esta pesquisa?\n\nO relatório e os vídeos que só apareceram nela somem. O que também está em outra pesquisa ou coleta continua.")) return;
    try {
      const d = await api(`/api/research/${R.current}`, { method: "DELETE" });
      toast(`Pesquisa excluída · ${d.videos} vídeos removidos.`, "ok");
    } catch (err) { return toast(err.message, "err"); }
    R.current = null;
    loadResearch();
  }
});

async function startResearch(body) {
  body.langs = body.langs || selectedLangs();
  if (!body.profile_id) body.profile_id = state.profile;
  if (body.max_age_days === undefined) body.max_age_days = selectedPeriod();
  try {
    const res = await api("/api/research", { method: "POST", body });
    watchJob(res.job);
    R.current = res.id;
    $('.nav-item[data-page="research"]').click();
    toast(body.kind === "video" ? "Pesquisa iniciada a partir do vídeo." : `Pesquisando "${body.seed}"…`, "ok");
  } catch (e) { toast(e.message, "err"); }
}

// Modal de nova pesquisa
function openResearchModal(mode) {
  $("#rmodal").hidden = false;
  $$("#r-mode button").forEach((b) => b.classList.toggle("on", b.dataset.v === mode));
  showResearchMode(mode);
  $("#r-hist-profile").innerHTML = state.profiles.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  if (state.profile) $("#r-hist-profile").value = String(state.profile);
  renderLangPicker($("#r-langs"));
  const niches = [...new Set(state.profiles.map((p) => p.niche).filter(Boolean))];
  $("#r-niches").innerHTML = niches.length ? `<span class="dim small">Nichos dos seus perfis:</span>` +
    niches.map((n) => `<span class="term sm clickable" data-niche="${esc(n)}">${esc(n)}</span>`).join("") : "";
  setTimeout(() => (mode === "video" ? $("#r-link") : $("#r-kws")).focus(), 50);
}
const closeResearchModal = () => { $("#rmodal").hidden = true; };
$("#r-new-video").addEventListener("click", () => openResearchModal("video"));
$("#r-new-kw").addEventListener("click", () => openResearchModal("keyword"));
$("#r-detail").addEventListener("click", (e) => { const b = e.target.closest("[data-rnew]"); if (b) openResearchModal(b.dataset.rnew); });
$$("[data-rclose]").forEach((b) => b.addEventListener("click", closeResearchModal));
$("#rmodal").addEventListener("click", (e) => { if (e.target.id === "rmodal") closeResearchModal(); });
function showResearchMode(v) {
  $("#r-video-box").hidden = v !== "video";
  $("#r-kw-box").hidden = v !== "keyword";
  $("#r-hist-box").hidden = v !== "history";
}
bindSeg($("#r-mode"), showResearchMode);
$("#r-niches").addEventListener("click", (e) => {
  const n = e.target.closest("[data-niche]");
  if (!n) return;
  const cur = $("#r-kws").value.trim();
  $("#r-kws").value = cur ? `${cur}\n${n.dataset.niche}` : n.dataset.niche;
});
$("#r-link").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#r-start").click(); });
$("#r-start").addEventListener("click", async () => {
  const kind = segValue($("#r-mode"));
  const seed = kind === "video" ? $("#r-link").value.trim() : kind === "keyword" ? $("#r-kws").value.trim() : "";
  if (kind !== "history" && !seed) return toast(kind === "video" ? "Cole o link do vídeo." : "Escreva pelo menos uma palavra-chave.", "err");
  closeResearchModal();
  $("#r-link").value = "";
  $("#r-kws").value = "";
  await startResearch({ kind, seed, report: $("#r-report").checked, langs: pickedLangs($("#r-langs")),
    profile_id: kind === "history" ? +$("#r-hist-profile").value : null });
});

// ---------------------------------------------------------------- idiomas

// Idiomas da busca: a escolha fica lembrada (só neste computador).
// Período da pesquisa: fica lembrado (só neste computador).
function selectedPeriod() {
  try { const v = localStorage.getItem("period"); if (v !== null) return +v; } catch {}
  return 30;
}
document.addEventListener("change", (e) => {
  const sel = e.target.closest(".period-sel");
  if (!sel) return;
  try { localStorage.setItem("period", sel.value); } catch {}
  $$(".period-sel").forEach((s) => { s.value = sel.value; });
});

function selectedLangs() {
  try { const v = JSON.parse(localStorage.getItem("langs") || "null"); if (Array.isArray(v) && v.length) return v; } catch {}
  return ["pt"];
}
function saveLangs(list) { try { localStorage.setItem("langs", JSON.stringify(list)); } catch {} }
function renderLangPicker(el) {
  const sel = new Set(selectedLangs());
  el.innerHTML = state.langs.map((l) => `<button type="button" class="lang ${sel.has(l.code) ? "on" : ""}" data-lang="${l.code}"
    title="${esc(l.name)}">${l.code.toUpperCase()}</button>`).join("");
}
const pickedLangs = (el) => $$(".lang.on", el).map((b) => b.dataset.lang);
document.addEventListener("click", (e) => {
  const b = e.target.closest(".lang-picker .lang");
  if (!b) return;
  b.classList.toggle("on");
  const picker = b.closest(".lang-picker");
  let list = pickedLangs(picker);
  if (!list.length) { b.classList.add("on"); list = [b.dataset.lang]; }
  saveLangs(list);
  $$(".lang-picker").forEach((p) => { if (p !== picker) renderLangPicker(p); });
});

// ---------------------------------------------------------------- barra de pesquisa por nicho (Descobertas)

async function nicheSearch() {
  const q = $("#nb-query").value.trim();
  if (!q) return toast("Escreva um nicho, tema, título ou palavras-chave.", "err");
  $("#nb-query").value = "";
  await startResearch({ kind: "keyword", seed: q, report: true, langs: pickedLangs($("#nb-langs")) });
}
$("#nb-go").addEventListener("click", nicheSearch);
$("#nb-query").addEventListener("keydown", (e) => { if (e.key === "Enter") nicheSearch(); });

// ---------------------------------------------------------------- coletas (filtrar / excluir)

const SRC_LABEL = { home: "Home", history: "Histórico", research: "Pesquisa" };
async function loadRunOptions() {
  const runs = (await api(`/api/runs?limit=200${state.profile ? `&profile_id=${state.profile}` : ""}`)).filter((r) => r.status !== "running");
  state.runs = runs;
  const sel = $("#v-run"), cur = sel.value;
  sel.innerHTML = `<option value="">Todas</option>` + runs.filter((r) => r.status === "done").map((r) =>
    `<option value="${r.id}">${fmtDate(r.started_at)} · ${esc(r.profile_name || "—")} · ${SRC_LABEL[r.source || "home"]}</option>`).join("");
  sel.value = runs.some((r) => String(r.id) === cur) ? cur : "";
}

function openRunsModal() {
  $("#runs-modal").hidden = false;
  const runs = state.runs || [];
  $("#runs-list").innerHTML = runs.length ? runs.map((r) => `
    <label class="run-row">
      <input type="checkbox" data-runsel="${r.id}">
      <div class="grow"><b>${fmtDate(r.started_at)}</b> · ${esc(r.profile_name || "—")}
        <span class="tag ${r.source === "history" ? "via" : "neutral"}">${SRC_LABEL[r.source || "home"]}</span>
        ${r.status === "error" ? `<span class="tag warn">erro</span>` : ""}${r.status === "done" && !r.logged_in ? `<span class="tag fresh">sem login</span>` : ""}
        <div class="dim small">${r.videos_found || 0} vídeos${r.error ? ` · ${esc(r.error)}` : ""}</div></div>
      ${r.status === "done" ? `<button type="button" class="btn ghost sm" data-runview="${r.id}">Ver só esta</button>` : ""}
    </label>`).join("") : `<div class="empty"><b>Nenhuma coleta</b></div>`;
  updateRunsSel();
}
const closeRunsModal = () => { $("#runs-modal").hidden = true; };
function updateRunsSel() {
  const n = $$("[data-runsel]:checked").length;
  $("#runs-sel").textContent = n ? `${n} selecionada(s)` : "";
  $("#runs-del").disabled = !n;
}
$("#btn-runs").addEventListener("click", async () => { await loadRunOptions(); openRunsModal(); });
$$("[data-runs-close]").forEach((b) => b.addEventListener("click", closeRunsModal));
$("#runs-modal").addEventListener("click", (e) => { if (e.target.id === "runs-modal") closeRunsModal(); });
$("#runs-list").addEventListener("change", updateRunsSel);
$("#runs-list").addEventListener("click", (e) => {
  const v = e.target.closest("[data-runview]");
  if (!v) return;
  e.preventDefault();
  $("#v-run").value = v.dataset.runview;
  closeRunsModal();
  loadVideos();
});
$("#runs-del").addEventListener("click", async () => {
  const ids = $$("[data-runsel]:checked").map((c) => c.dataset.runsel);
  if (!confirm(`Excluir ${ids.length} coleta(s)?\n\nOs vídeos, números, comentários e canais que só existiam nelas somem. O que também está em outra coleta ou pesquisa continua.`)) return;
  let videos = 0;
  for (const id of ids) {
    try { videos += (await api(`/api/runs/${id}`, { method: "DELETE" })).videos; } catch (err) { toast(err.message, "err"); }
  }
  toast(`${ids.length} coleta(s) excluída(s) · ${videos} vídeos removidos.`, "ok");
  await refreshAll();
  openRunsModal();
});

// ---------------------------------------------------------------- tradução

async function translateList(list, btn) {
  const ids = list.filter((v) => !v.title_pt).map((v) => v.video_id);
  if (!ids.length) return toast("Nada para traduzir nessa lista.");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Traduzindo…";
  try {
    const r = await api("/api/translate", { method: "POST", body: { ids } });
    for (const v of [...state.videos, ...(R.data?.videos || [])]) if (r.titles[v.video_id]) v.title_pt = r.titles[v.video_id];
    toast(r.translated ? `${r.translated} títulos traduzidos.` : "Os títulos já estão em português.", "ok");
    renderVideos();
    if ($(".r-videos")) rerenderResearchVideos();
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
  btn.textContent = old;
}
$("#v-translate").addEventListener("click", (e) => translateList(filteredVideos().slice(0, state.vLimit), e.currentTarget));
document.addEventListener("click", (e) => {
  const b = e.target.closest("#rv-translate");
  if (b) translateList(researchFiltered().slice(0, 200), b);
});

// ---------------------------------------------------------------- prévia do vídeo

const PV = { id: null, data: null };

async function openPreview(id, quiet = false) {
  PV.id = id;
  $("#pv").hidden = false;
  if (!quiet) $("#pv-body").innerHTML = `<div class="pv-loading">Carregando…</div>`;
  try { PV.data = await api(`/api/videos/${id}`); } catch (e) { $("#pv").hidden = true; return toast(e.message, "err"); }
  if (PV.id !== id) return;
  renderPreview();
  const v = PV.data.video;
  if (v.foreign && !v.title_pt && state.aiEnabled) {
    api("/api/translate", { method: "POST", body: { ids: [id] } }).then((r) => {
      if (PV.id === id && r.titles[id]) { v.title_pt = r.titles[id]; renderPreview(); }
    }).catch(() => {});
  }
}
const closePreview = () => { $("#pv").hidden = true; PV.id = null; $("#pv-body").innerHTML = ""; };
$("#pv").addEventListener("click", (e) => { if (e.target.id === "pv") closePreview(); });

function renderPreview() {
  const { video: v, comments, analysis: a } = PV.data;
  const fmtL = PV.data.format_labels;
  const link = `https://www.youtube.com/watch?v=${v.video_id}`;
  const conf = { alta: "com certeza", media: "provavelmente", baixa: "não tem certeza" };
  const darkState = v.channel_dark_manual != null ? (v.channel_dark_manual ? "É canal dark (você marcou)" : "Não é canal dark (você marcou)")
    : v.channel_format ? `A IA acha que ${v.is_dark ? "é canal dark" : "não é canal dark"} (${FORMAT_TIP[v.channel_format] || v.channel_format}${v.channel_dark_conf ? `; ${conf[v.channel_dark_conf] || v.channel_dark_conf}` : ""})`
    : "A IA ainda não olhou esse canal";
  const stat = (label, value, tip = "") => `<div class="pv-stat" title="${esc(tip)}"><b>${value}</b><span>${label}</span></div>`;
  $("#pv-body").innerHTML = `
    <div class="pv-top">
      <span class="pv-kicker">Prévia do vídeo</span>
      <button class="icon-btn" id="pv-close" title="Fechar (Esc)"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
    <div class="pv-player"><iframe src="https://www.youtube-nocookie.com/embed/${v.video_id}?autoplay=1&mute=1&rel=0&modestbranding=1"
      title="Prévia" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>
    <h2 class="pv-title">${esc(v.title)}</h2>
    ${v.title_pt && v.title_pt !== v.title ? `<div class="pv-trans"><span>Tradução</span>${esc(v.title_pt)}</div>`
      : v.foreign ? `<div class="pv-trans dim"><span>Tradução</span>${state.aiEnabled ? "traduzindo…" : "IA desligada"}</div>` : ""}
    <div class="pv-tags">${langTag(v)}${channelTags(v).join("")}
      ${v.channel_age_days != null && v.channel_age_days <= 180 ? `<span class="tag new">Canal novo · ${fmtAge(v.channel_age_days)}</span>` : ""}
      ${v.age_days != null && v.age_days <= 7 ? `<span class="tag fresh">Recente</span>` : ""}
      ${v.hidden ? `<span class="tag warn">Oculto</span>` : ""}</div>

    <div class="pv-actions">
      <button class="btn primary sm" id="pv-yt">Abrir no YouTube</button>
      <button class="btn sm" data-copy-link="${link}">Copiar link</button>
      <button class="btn sm" data-seed="${v.video_id}" title="Procura vídeos parecidos com este">Achar parecidos</button>
      <button class="btn sm ${state.modeled.has(v.video_id) ? "primary" : ""}" data-modeled="${v.video_id}" title="${state.modeled.has(v.video_id) ? "Já está em Meu canal (clique para tirar)" : "Você já modelou este vídeo: leva para Meu canal"}">${state.modeled.has(v.video_id) ? "✓ Modelado" : "Já modelei"}</button>
      <button class="btn ghost sm" data-hide="${v.video_id}" ${v.hidden ? `data-unhide="1"` : ""} title="${v.hidden ? "Voltar a mostrar nas listas" : "Esconder este vídeo das listas"}">${v.hidden ? "Mostrar de novo" : "Esconder"}</button>
    </div>

    <div class="pv-stats">
      ${stat("viralizou", `<span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span>`, TIP.viralizou)}
      ${stat("nota para copiar", v.score != null ? v.score.toFixed(1).replace(".", ",") : "—", TIP.nota)}
      ${stat("views", fmt(v.views), "Total de views")}${stat("views por dia", fmt(v.views_day), "Views por dia, em média")}
      ${stat("likes", fmt(v.likes), "Curtidas")}${stat("comentários", fmt(v.comments), "Quantidade de comentários")}
      ${stat("interação", v.engagement != null ? `${String(v.engagement).replace(".", ",")}%` : "—", "De cada 100 pessoas que viram, quantas curtiram ou comentaram")}
      ${stat("postado há", ageLong(v.age_days) || "—", "Há quanto tempo o vídeo foi postado")}${stat("duração", v.duration_s ? fmtDur(v.duration_s) : "—", "Duração do vídeo")}
    </div>

    <div class="pv-section pv-channel">
      <div class="pv-ch-head">
        ${v.channel_thumb ? `<img src="${esc(v.channel_thumb)}" alt="">` : `<div class="avatar ini">${esc((v.channel_title || "?")[0])}</div>`}
        <div class="grow"><b>${esc(v.channel_title || "")}</b>
          <div class="dim small">${fmt(v.subs)} inscritos · ${fmt(v.channel_videos)} vídeos · canal com ${fmtAge(v.channel_age_days)}${v.country ? ` · ${esc(v.country)}` : ""}</div></div>
      </div>
      <div class="pv-dark"><span>${esc(darkState)}</span>
        <div class="pv-dark-btns">
          <button class="btn sm ${v.is_dark && v.channel_dark_manual === 1 ? "primary" : ""}" data-dark="${v.channel_id}" data-val="1" title="Marcar: este canal é dark (ninguém aparece)">É dark</button>
          <button class="btn sm ${v.channel_dark_manual === 0 ? "primary" : ""}" data-dark="${v.channel_id}" data-val="0" title="Marcar: este canal não é dark (a IA aprende com isso)">Não é dark</button>
          ${v.channel_dark_manual != null ? `<button class="btn ghost sm" data-dark="${v.channel_id}" data-val="" title="Apaga a sua marcação e volta a valer o que a IA achou">Desfazer</button>` : ""}
        </div></div>
      ${v.channel_description ? `<p class="pv-desc">${esc(v.channel_description)}</p>` : ""}
    </div>

    <div class="pv-section">
      <div class="pv-h"><h3>Ideias de variações</h3><span class="dim small">com a chance de viralizar</span></div>
      ${renderVariations(PV.data.variations, v.video_id)}
    </div>

    <div class="pv-section pv-mal">
      <div class="pv-h"><h3>Método Malandro</h3><span class="dim small">em que língua ninguém fez este vídeo</span></div>
      ${renderMalandro(PV.data.malandro, v.video_id)}
    </div>


    <div class="pv-section">
      <div class="pv-h"><h3>Análise com IA</h3>${a ? `<button class="btn ghost sm" id="pv-reanalyze">Refazer</button>` : ""}</div>
      ${a ? renderAnalysis(a) : `<p class="dim small">Por que funcionou, título, thumbnail, público e como modelar, com 5 títulos prontos no idioma do seu canal. Feita uma vez e guardada.</p>
        <button class="btn primary sm" id="pv-analyze" ${state.aiEnabled ? "" : "disabled"}>Analisar este vídeo <span class="btn-note">· ~US$ 0,02</span></button>`}
    </div>

    <div class="pv-section">
      <div class="pv-h"><h3>Comentários</h3><span class="dim small">${comments.length ? `os ${comments.length} com mais curtidas` : ""}</span></div>
      ${comments.length ? comments.map((c) => `<div class="cm"><span class="cm-likes">♥ ${fmt(c.likes)}</span>${esc(c.text)}</div>`).join("")
        : `<p class="dim small">${v.comments === 0 ? "Sem comentários." : "Comentários indisponíveis (desativados ou sem chave da API)."}</p>`}
    </div>

    ${v.description ? `<details class="pv-section"><summary><h3>Descrição do vídeo</h3></summary><p class="pv-desc">${esc(v.description)}</p></details>` : ""}
    ${v.tags && v.tags.length ? `<div class="pv-section"><div class="pv-h"><h3>Tags</h3></div>
      <div class="terms" data-copy="${esc(v.tags.join(", "))}">${v.tags.map((t) => `<span class="term sm">${esc(t)}</span>`).join("")}</div></div>` : ""}`;
}

function renderAnalysis(a) {
  return `<div class="pv-verdict">${esc(a.verdict)}</div>
    <div class="idea-label">Por que funcionou</div><ul class="r-bullets">${a.why_it_worked.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="idea-label">Por que o título funciona</div><p class="pv-p">${esc(a.title_breakdown)}</p>
    <div class="idea-label">Por que a capa (thumbnail) funciona</div><p class="pv-p">${esc(a.thumbnail)}</p>
    <div class="idea-label">O que o público achou</div><p class="pv-p">${esc(a.audience)}</p>
    <div class="idea-label">Como fazer um parecido</div><ol class="idea-structure">${a.how_to_model.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
    <div class="idea-label">Títulos prontos para o seu vídeo</div>
    <div class="formulas">${a.titles.map((t) => `<div class="formula" data-copy="${esc(t)}" title="Copiar">${esc(t)}</div>`).join("")}</div>
    <div class="idea-label">Cuidado com</div><ul class="r-bullets avoid">${a.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
}

$("#pv-body").addEventListener("click", async (e) => {
  if (e.target.closest("#pv-close")) return closePreview();
  const mv = e.target.closest("[data-vref]");
  if (mv) return openPreview(mv.dataset.vref);
  if (e.target.closest("#pv-yt")) return openYT(`watch?v=${PV.id}`);
  const cl = e.target.closest("[data-copy-link]");
  const cp = cl ? cl.dataset.copyLink : e.target.closest("[data-copy]")?.dataset.copy;
  if (cp) {
    try { await navigator.clipboard.writeText(cp); toast("Copiado.", "ok"); } catch { toast("Não consegui copiar.", "err"); }
    return;
  }
  const an = e.target.closest("#pv-analyze, #pv-reanalyze");
  if (an) {
    const refresh = an.id === "pv-reanalyze";
    if (refresh && !confirm("Refazer a análise gasta tokens de novo (~US$ 0,02). Continuar?")) return;
    an.disabled = true;
    an.innerHTML = "IA analisando… (uns 20 a 40 segundos)";
    const id = PV.id;
    try {
      const r = await api(`/api/videos/${id}/analyze`, { method: "POST", body: { refresh } });
      if (PV.id === id) { PV.data.analysis = r; renderPreview(); }
    } catch (err) { toast(err.message, "err"); an.disabled = false; an.textContent = "Tentar de novo"; }
  }
});

// ---------------------------------------------------------------- ideias de variações (chance de viralizar)

function renderVariations(d, videoId) {
  if (!d) {
    return `<p class="dim small">A IA cria 10 versões deste vídeo trocando os detalhes (quem faz, o objeto, o país, a marca…)
      e diz a <b>chance de cada uma viralizar</b>, olhando os vídeos parecidos que já viralizaram, os idiomas e o que o público pede.</p>
      <button class="btn primary sm" data-variations="${videoId}" ${state.aiEnabled ? "" : "disabled"}>Criar ideias de variações <span class="btn-note">· ~US$ 0,02</span></button>`;
  }
  const list = [...d.variations].sort((a, b) => b.chance - a.chance);
  const lvl = (c) => (c >= 60 ? "hi" : c >= 40 ? "mid" : "lo");
  return `
    ${d.fits ? `<div class="var-template" data-copy="${esc(d.template)}" title="Clique para copiar"><span>Molde do título</span>${esc(d.template)}</div>`
      : `<div class="alert info">Este vídeo não dá muito para variar trocando detalhes.</div>`}
    <p class="var-note">${esc(d.note)}</p>
    <div class="var-list">${list.map((v) => `
      <div class="var ${lvl(v.chance)}">
        <div class="var-chance" title="Chance de viralizar (estimativa da IA com base nos dados do nicho)"><b>${v.chance}%</b><i style="width:${v.chance}%"></i></div>
        <div class="var-body">
          <div class="var-title" data-copy="${esc(v.title)}" title="Clique para copiar">${esc(v.title)}</div>
          <div class="var-meta"><span class="tag neutral" title="O que mudou em relação ao original">${esc(v.changes)}</span></div>
          <div class="var-why">${esc(v.why)}</div>
        </div>
      </div>`).join("")}</div>
    <div class="mal-foot dim small"><span class="link" data-variations="${videoId}" data-refresh="1">refazer (~US$ 0,02)</span></div>`;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-variations]");
  if (!b) return;
  e.stopPropagation();
  const refresh = !!b.dataset.refresh;
  if (refresh && !confirm("Refazer as ideias de variações (~US$ 0,02)?")) return;
  const id = b.dataset.variations;
  b.disabled = true;
  b.innerHTML = "IA criando as variações… (uns 15 segundos)";
  try {
    const r = await api(`/api/videos/${id}/variations`, { method: "POST", body: { refresh } });
    if (PV.id === id && PV.data) { PV.data.variations = r; renderPreview(); }
    if (R.data && R.data.research.seed === id) { R.data.variations = r; renderResearch(); }
  } catch (err) { toast(err.message, "err"); b.disabled = false; b.textContent = "Tentar de novo"; }
}, true);

// ---------------------------------------------------------------- Método Malandro (radar de línguas)

const FLAG = { pt: "br", en: "us", es: "es", hi: "in", id: "id", fr: "fr", de: "de", ja: "jp", ko: "kr", ru: "ru", ar: "sa", tr: "tr", it: "it" };
const flagImg = (code, w = 20) => `<img class="flag" src="https://flagcdn.com/w${w}/${FLAG[code] || "un"}.png" alt="${code}" onerror="this.style.display='none'">`;
const MAL_STATUS = { livre: ["Ninguém fez", "good"], pouca: ["Poucos fizeram", "warn"], saturada: ["Muitos já fizeram", "bad"] };

function malandroRadar(m) {
  const S = 340, C = S / 2, R = 128, PAD = 34;
  const n = m.langs.length;
  // Livre = anel de fora (alternando um pouco para os rótulos não se encostarem); saturada = perto do centro.
  const radius = (l, i) => ({ livre: i % 2 ? 0.93 : 0.8, pouca: 0.55, saturada: 0.3 })[l.status];
  const dots = m.langs.map((l, i) => {
    const ang = (-90 + i * (360 / n)) * Math.PI / 180;
    const r = R * radius(l, i);
    const x = C + r * Math.cos(ang), y = C + r * Math.sin(ang);
    const left = Math.cos(ang) < -0.15;
    const lw = 42, lx = left ? x - 8 - lw : x + 8;
    return `<g class="mdot ${l.status}">
      <circle cx="${x}" cy="${y}" r="9" class="halo" style="animation-delay:${(i * 0.23).toFixed(2)}s"/><circle cx="${x}" cy="${y}" r="4.2" class="core"/>
      <g transform="translate(${lx},${y - 9})"><rect width="${lw}" height="18" rx="9" class="tag-bg"/>
        <image href="https://flagcdn.com/w20/${FLAG[l.code]}.png" x="6" y="4.5" width="13" height="9"/>
        <text x="23" y="12.6">${l.code.toUpperCase()}</text></g></g>`;
  }).join("");
  const rings = [0.3, 0.55, 0.8, 1].map((f) => `<circle cx="${C}" cy="${C}" r="${R * f}" class="ring"/>`).join("");
  return `<svg class="radar" viewBox="${-PAD} ${-6} ${S + 2 * PAD} ${S + 12}" role="img" aria-label="Radar de línguas">
    <defs>
      <radialGradient id="rbg" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="#16161a"/><stop offset="100%" stop-color="#0b0b0d"/></radialGradient>
      <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="rgba(229,57,53,0)"/><stop offset="100%" stop-color="rgba(229,57,53,.5)"/></linearGradient>
    </defs>
    <circle cx="${C}" cy="${C}" r="${R + 30}" fill="url(#rbg)" class="frame"/>
    ${rings}
    <line x1="${C - R}" y1="${C}" x2="${C + R}" y2="${C}" class="axis"/><line x1="${C}" y1="${C - R}" x2="${C}" y2="${C + R}" class="axis"/>
    <g class="sweep" style="transform-origin:${C}px ${C}px">
      <path d="M${C},${C} L${C + R},${C} A${R},${R} 0 0,0 ${C + R * Math.cos(-0.75)},${C + R * Math.sin(-0.75)} Z" fill="url(#sweep)"/>
    </g>
    ${dots}
    <text x="${C}" y="${C + 8}" class="big">${m.free.length}</text>
    <text x="${C}" y="${C + 27}" class="small">línguas livres</text>
  </svg>`;
}

function renderMalandro(m, videoId, open = false) {
  if (!m) {
    return `<div class="mal-empty"><p class="dim small">Em que línguas <b>ninguém fez este vídeo ainda</b>: a IA escreve o título como um nativo
      escreveria em 13 línguas, o darkbot procura no YouTube de cada país e marca onde está livre.</p>
      <button class="btn primary sm" data-malandro-run="${videoId}" ${state.aiEnabled ? "" : "disabled"}>Rodar Método Malandro <span class="btn-note">· ~US$ 0,01</span></button></div>`;
  }
  const free = m.langs.filter((l) => l.status === "livre");
  const order = { livre: 0, pouca: 1, saturada: 2 };
  const langs = [...m.langs].sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
  return `<div class="mal">
    ${malandroRadar(m)}
    ${free.length ? `<div class="mal-free"><span>Ninguém fez em:</span>${free.map((l) => `<b>${flagImg(l.code)} ${esc(l.name)}</b>`).join("")}</div>`
      : `<div class="mal-free bad">Esse vídeo já foi feito em todas as línguas pesquisadas.</div>`}
    <details class="mal-details" ${open ? "open" : ""}><summary class="btn sm mal-btn">Ver os vídeos de cada língua</summary>
      <div class="mal-langs">${langs.map((l) => {
        const [lab, cls] = MAL_STATUS[l.status];
        return `<div class="mal-lang ${l.status}">
          <div class="mal-lang-head">${flagImg(l.code)}<b>${esc(l.name)}</b>${l.original ? `<span class="tag via" title="O idioma do vídeo original">idioma do vídeo</span>` : ""}
            <span class="tag ${cls}">${lab}</span><span class="dim small">${l.channels === 0 ? "nenhum canal fez" : l.channels === 1 ? "1 canal fez" : `${l.channels} canais fizeram`}</span></div>
          ${l.suggested_title ? `<div class="mal-title" data-copy="${esc(l.suggested_title)}" title="Clique para copiar"><span>Título pronto nesse idioma</span>${esc(l.suggested_title)}</div>` : ""}
          ${l.videos.length ? `<div class="mal-videos">${l.videos.map((v) => `<div class="mal-v" data-vref="${v.video_id}">
              <img src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
              <div class="grow"><div class="otitle">${esc(v.title)}</div>
                <div class="dim small">${esc(v.channel_title || "")} · ${fmt(v.views)} views · ${fmtAge(v.age_days)}${v.relevance >= 3 ? " · <b class='up'>fez o mesmo vídeo</b>" : " · mesmo assunto"}</div></div>
              <span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span></div>`).join("")}</div>` : ""}
        </div>`; }).join("")}</div>
      <div class="mal-foot dim small">Feito em ${fmtDate(m.created_at)} · <span class="link" data-malandro-run="${m.video_id}" data-refresh="1">refazer (~US$ 0,01)</span></div>
    </details>
  </div>`;
}

// Rodar/refazer o Método Malandro (prévia ou pesquisa).
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-malandro-run]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.refresh && !confirm("Refazer o Método Malandro (~US$ 0,01)?")) return;
  try { watchJob(await api(`/api/malandro/${b.dataset.malandroRun}`, { method: "POST" })); toast("Método Malandro rodando… (uns 15 segundos)"); }
  catch (err) { toast(err.message, "err"); }
}, true);

// ---------------------------------------------------------------- configurações

async function loadSettings() {
  const s = await api("/api/settings");
  const st = $("#s-status");
  st.className = `hint ${s.youtube_api_key_set ? "ok" : ""}`;
  st.textContent = s.youtube_api_key_set
    ? `Chave salva e funcionando (${s.youtube_api_key_hint}).`
    : "Nenhuma chave ainda. Sem ela o darkbot não vê os números dos vídeos.";
  // IA: provedor escolhido + chaves + modelos
  state.aiEnabled = s.ai_enabled;
  $$("#s-provider button").forEach((b) => b.classList.toggle("on", b.dataset.v === s.ai_provider));
  for (const p of ["anthropic", "openai"]) {
    const set = s[`${p}_key_set`], active = s.ai_provider === p;
    $(`.ai-prov[data-prov="${p}"]`).classList.toggle("active", active);
    const badge = $(`#s-${p}-badge`);
    badge.className = `tag ${active ? "good" : "neutral"}`;
    badge.textContent = active ? "em uso" : "não está em uso";
    const hs = $(`#s-${p}-status`);
    hs.className = `hint ${set ? "ok" : ""}`;
    hs.textContent = set ? `Chave salva e funcionando (${s[`${p}_key_hint`]}).` : "Nenhuma chave salva.";
  }
  for (const p of ["anthropic", "openai"]) {
    $(`#s-${p}-modelbox`).hidden = !s[`${p}_key_set`];
    if (s[`${p}_key_set`]) loadProviderModels(p, s.models[p]);
  }
  const ai = $("#s-ai");
  ai.className = `hint ${s.ai_enabled ? "ok" : ""}`;
  ai.textContent = s.ai_enabled
    ? `IA ativa: ${s.ai_providers[s.ai_provider]} · ${s.ai_usage.analyses} chamadas · US$ ${s.ai_usage.cost_usd.toFixed(4).replace(".", ",")} gastos no total.`
    : `IA desligada: coloque a chave da ${s.ai_provider === "openai" ? "OpenAI" : "Anthropic"} acima.`;
  $("#s-lang").value = s.channel_lang;
  $("#s-class").textContent = s.channels_to_reclassify
    ? `${s.channels_to_reclassify} canais foram classificados pelo critério antigo (menos rigoroso). Reclassificar custa cerca de ${fmtUSD(s.channels_to_reclassify * 0.0002)}. ${s.channels_manual} correções suas são mantidas.`
    : `Todos os canais estão no critério atual. ${s.channels_manual} correções suas.`;
  $("#s-reclass").disabled = !s.channels_to_reclassify || !s.ai_enabled;
  $("#s-hidden").textContent = `${s.hidden_videos} vídeos ocultados.`;
  $("#s-unhide").disabled = !s.hidden_videos;
}
// Modelos da conta (com preço) para escolher, e quanto cada tarefa vai custar com a escolha.
const usd = (x) => x == null ? "?" : `US$ ${x.toFixed(x < 0.1 ? 3 : 2).replace(".", ",")}`;
async function loadProviderModels(p, cur) {
  let models = [];
  try { models = await api(`/api/ai/models?provider=${p}`); }
  catch (e) { $(`#s-${p}-status`).textContent = e.message; return; }
  const n = (x) => String(x).replace(".", ",");
  const label = (m) => m.input != null ? `${m.id} · US$ ${n(m.input)} / ${n(m.output)}` : `${m.id} · preço desconhecido`;
  for (const tier of ["fast", "smart"]) {
    const sel = $(`[data-model="${p}:${tier}"]`);
    let val = cur[tier];
    // A conta pode listar o mesmo modelo com data no nome (ex.: claude-haiku-4-5-20251001).
    if (!models.some((m) => m.id === val)) val = models.find((m) => m.id.startsWith(val + "-"))?.id || val;
    const list = models.some((m) => m.id === val) ? models : [{ id: val, input: null, output: null }, ...models];
    sel.innerHTML = list.map((m) => `<option value="${esc(m.id)}" ${m.id === val ? "selected" : ""}>${esc(label(m))}</option>`).join("");
  }
  updateCost(p);
}
async function updateCost(p) {
  const fast = $(`[data-model="${p}:fast"]`).value, smart = $(`[data-model="${p}:smart"]`).value;
  const est = await api(`/api/ai/estimate?fast=${encodeURIComponent(fast)}&smart=${encodeURIComponent(smart)}`);
  const get = (k) => est.find((e) => e.task === k)?.cost;
  const day = (get("pesquisa") ?? 0) + (get("relatorio") ?? 0);
  $(`#s-${p}-cost`).innerHTML = `<div class="cost-head">Quanto custa com esses modelos <span class="dim">(estimativa)</span></div>
    ${est.map((e) => `<div class="cost-row"><span>${esc(e.label)}</span><b>${usd(e.cost)}</b></div>`).join("")}
    <div class="cost-row total" title="10 pesquisas com relatório por dia, durante 30 dias"><span>10 pesquisas com relatório por dia, por mês</span><b>${usd(day * 10 * 30)}</b></div>`;
}
document.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-model]");
  if (sel) updateCost(sel.dataset.model.split(":")[0]);
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-save-models]");
  if (!b) return;
  const p = b.dataset.saveModels;
  b.disabled = true;
  b.textContent = "Testando na sua conta…";
  try {
    await api("/api/settings", { method: "POST", body: {
      [`${p}_model_fast`]: $(`[data-model="${p}:fast"]`).value, [`${p}_model_smart`]: $(`[data-model="${p}:smart"]`).value } });
    toast("Modelos testados e salvos.", "ok");
  } catch (err) { toast(err.message, "err"); }
  b.disabled = false;
  b.textContent = "Testar e salvar modelos";
});
bindSeg($("#s-provider"), async (v) => {
  try {
    await api("/api/settings", { method: "POST", body: { ai_provider: v } });
    toast(`Agora o darkbot usa ${v === "openai" ? "ChatGPT (OpenAI)" : "Claude (Anthropic)"}.`, "ok");
  } catch (e) { toast(e.message, "err"); }
  loadSettings();
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-save-key]");
  if (!b) return;
  const p = b.dataset.saveKey, input = $(`#s-${p}-key`);
  if (!input.value.trim()) return toast("Cole a chave primeiro.", "err");
  b.disabled = true;
  b.textContent = "Testando…";
  try {
    await api("/api/settings", { method: "POST", body: { [`${p}_api_key`]: input.value } });
    input.value = "";
    toast("Chave testada e salva.", "ok");
    loadSettings();
  } catch (err) {
    $(`#s-${p}-status`).className = "hint err";
    $(`#s-${p}-status`).textContent = err.message;
  }
  b.disabled = false;
  b.textContent = "Salvar";
});

$("#s-lang-save").addEventListener("click", async () => {
  try { await api("/api/settings", { method: "POST", body: { channel_lang: $("#s-lang").value } }); toast("Idioma do canal salvo.", "ok"); }
  catch (e) { toast(e.message, "err"); }
});
$("#s-reclass").addEventListener("click", async () => {
  if (!confirm("Reclassificar os canais com o critério novo? Suas correções manuais ficam.")) return;
  try { watchJob(await api("/api/channels/reclassify", { method: "POST" })); } catch (e) { toast(e.message, "err"); }
});
$("#s-unhide").addEventListener("click", async () => {
  const r = await api("/api/videos/unhide-all", { method: "POST" });
  toast(`${r.videos} vídeos de volta nas listas.`, "ok");
  loadSettings();
  loadVideos();
});
$("#s-save").addEventListener("click", async () => {
  const btn = $("#s-save");
  btn.disabled = true;
  try {
    await api("/api/settings", { method: "POST", body: { youtube_api_key: $("#s-key").value } });
    $("#s-key").value = "";
    toast("Chave validada e salva.", "ok");
    loadSettings();
    loadOverview();
  } catch (e) {
    $("#s-status").className = "hint err";
    $("#s-status").textContent = e.message;
  } finally { btn.disabled = false; }
});

// ---------------------------------------------------------------- tarefas

function renderJob(j) {
  let el = $(`#job-${j.id}`);
  if (!el) {
    el = document.createElement("div");
    el.id = `job-${j.id}`;
    $("#jobs").append(el);
  }
  el.className = `job ${j.status}`;
  const msg = j.status === "error" ? j.error : j.result?.note || j.message;
  const right = j.status === "error"
    ? `<button class="icon-btn job-x" title="Fechar"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`
    : `<span class="job-right">${j.status === "running" && j.cancellable && !j.cancelled
        ? `<button class="job-cancel" data-cancel="${j.id}" title="Para e guarda o que já foi feito">Cancelar</button>` : ""}
        <span class="dim">${Math.round(j.progress * 100)}%</span></span>`;
  el.innerHTML = `<div class="job-top"><span>${esc(j.label)}</span>${right}</div>
    <div class="job-msg">${esc(msg)}</div>${j.status === "error" ? "" : `<div class="bar"><i style="width:${j.progress * 100}%"></i></div>`}`;
  return el;
}

$("#jobs").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cancel]");
  if (!b) return;
  b.disabled = true;
  b.textContent = "Cancelando…";
  try { await api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" }); } catch (err) { toast(err.message, "err"); }
});

function watchJob(j) {
  if (state.watching.has(j.id)) return;
  state.watching.add(j.id);
  renderJob(j);
  const tick = async () => {
    try { j = await api(`/api/jobs/${j.id}`); } catch { return; }
    const el = renderJob(j);
    if (j.status === "running") return setTimeout(tick, 700);
    state.watching.delete(j.id);
    if (j.status === "error") $(".job-x", el).addEventListener("click", () => el.remove());
    // Erro fica mais tempo para dar para ler (o detalhe também fica no histórico de coletas).
    setTimeout(() => el.remove(), j.status === "error" ? 12000 : 4000);
    refreshAll();
    if (j.kind === "malandro" && !$("#pv").hidden && PV.id) openPreview(PV.id, true);
  };
  setTimeout(tick, 500);
}

// ---------------------------------------------------------------- início

async function loadOverview() {
  const o = await api("/api/overview");
  $("#overview").innerHTML = `
    <div><b>${fmt(o.videos || 0)}</b> vídeos · <b>${fmt(o.channels || 0)}</b> canais</div>
    <div><b>${o.runs || 0}</b> coletas · ${o.last_run ? `última ${fmtDate(o.last_run)}` : "nenhuma ainda"}</div>`;
  const s = await api("/api/settings");
  const st = $("#api-status");
  st.classList.toggle("off", !s.youtube_api_key_set);
  st.textContent = s.youtube_api_key_set ? "● API do YouTube conectada" : "○ API do YouTube sem chave";
  $("#version").innerHTML = `darkbot v${s.version}${s.demo ? ` · <span class="demo-pill">DEMO</span>` : ""}`;
}

async function refreshAll() {
  state.profiles = await api("/api/profiles");
  // Perfil em uso apagado, ou primeiro perfil criado: ajusta sozinho.
  if (state.profile && !state.profiles.some((p) => p.id === state.profile)) state.profile = null;
  if (!state.profile && state.profiles.length === 1) {
    state.profile = state.profiles[0].id;
    try { localStorage.setItem("profile", String(state.profile)); } catch {}
  }
  fillProfileSelects();
  await loadModeledIds();
  await loadRunOptions();
  await Promise.all([loadVideos(), loadOverview()]);
  if ($("#page-profiles").classList.contains("active")) loadProfiles();
  if ($("#page-channels").classList.contains("active")) loadChannels();
  if ($("#page-titles").classList.contains("active")) loadTitles();
  if ($("#page-research").classList.contains("active")) loadResearch();
  if ($("#page-next").classList.contains("active")) loadNext();
}

(async () => {
  state.langs = await api("/api/languages");
  renderLangPicker($("#nb-langs"));
  $$(".period-sel").forEach((s) => { s.value = String(selectedPeriod()); });
  state.aiEnabled = (await api("/api/settings")).ai_enabled;
  // Perfil em uso: o último escolhido; se não houver (ou foi apagado), pede para escolher.
  state.profiles = await api("/api/profiles");
  state.profile = savedProfile();
  if (!state.profiles.some((p) => p.id === state.profile)) state.profile = state.profiles.length === 1 ? state.profiles[0].id : null;
  await refreshAll();
  if (!state.profile) openProfilePicker(true);
  (await api("/api/jobs")).filter((j) => j.status === "running").forEach(watchJob);
})();

// ---------------------------------------------------------------- Meu canal (o "após": modelados, DNA, mapa, próximos)

const NX = { runs: [], data: null, queue: [], modeled: [], dna: null, kinds: {}, boldness: {} };
const NX_KIND_TIP = {
  continuacao: "Continuação: uma parte 2, ou outro caso no mesmo formato do que você já fez",
  vizinho: "Tema vizinho: outro assunto que o mesmo público assiste e que está funcionando agora",
  pedido: "Pedido do público: o pessoal pediu isso nos comentários dos vídeos do nicho",
  tendencia: "Tendência agora: explodiu nos últimos dias no nicho (faça logo, perde a validade rápido)",
  angulo: "Ângulo novo: o mesmo assunto, contado de um jeito que ninguém do seu nicho fez",
};
const BOLD_TIP = {
  perto: "Perto: continua o que você já faz e funciona. Pouco risco.",
  equilibrado: "Equilibrado: um pouco de continuação, temas vizinhos e 1 ou 2 ângulos novos.",
  ousado: "Ousado: foca na fronteira, assuntos e ângulos que você nunca fez, mas que estão em alta no nicho. Mesmo público, sem ser aleatório.",
};
const TERR = { seu: ["Seu território", "Assuntos que você já faz e que seguem em alta: continuação segura"],
  fronteira: ["Fronteira", "Vizinhos do que você faz, em alta, e você NUNCA fez: é aqui que está a oportunidade"],
  saturado: ["Saturado", "Muita gente já está fazendo: difícil se destacar"] };
const boldness = () => { try { return localStorage.getItem("boldness") || "equilibrado"; } catch { return "equilibrado"; } };

// Vídeos modelados do perfil em uso (para marcar "Já modelei" em Descobertas e na prévia).
state.modeled = new Map();
async function loadModeledIds() {
  state.modeled = new Map();
  if (!state.profile) return;
  try { (await api(`/api/modeled?profile_id=${state.profile}`)).forEach((m) => m.video_id && state.modeled.set(m.video_id, m.id)); } catch {}
}

async function loadNext(runId = null) {
  if (!state.profile) {
    $("#mc-modeled").innerHTML = `<div class="empty"><b>Escolha o perfil em uso</b>Meu canal é do perfil que você está usando.</div>`;
    ["#mc-run", "#mc-result", "#mc-dna", "#mc-queue"].forEach((s) => ($(s).innerHTML = ""));
    return;
  }
  const pid = state.profile;
  const [d, q, m, dna] = await Promise.all([api(`/api/next?profile_id=${pid}`), api(`/api/queue?profile_id=${pid}`),
    api(`/api/modeled?profile_id=${pid}`), api(`/api/dna?profile_id=${pid}`)]);
  Object.assign(NX, { runs: d.runs, kinds: d.kinds, boldness: d.boldness, queue: q, modeled: m, dna });
  state.modeled = new Map(m.filter((x) => x.video_id).map((x) => [x.video_id, x.id]));
  NX.data = runId ? await api(`/api/next/${runId}`) : d.latest;
  $("#nx-history").hidden = NX.runs.length < 2;
  $("#nx-history").innerHTML = NX.runs.map((r) => `<option value="${r.id}" ${NX.data && NX.data.id === r.id ? "selected" : ""}>
    ${fmtDate(r.created_at)} · ${esc(NX.boldness[r.boldness] || "")}</option>`).join("");
  renderModeled(); renderDNA(); renderRun(); renderNext(); renderQueue();
}

function renderModeled() {
  const card = (m) => `<div class="mc-card">
    ${m.video_id ? `<img loading="lazy" src="https://i.ytimg.com/vi/${m.video_id}/mqdefault.jpg" alt="" data-vref="${m.video_id}" title="Ver o vídeo original">` : `<div class="noimg">SÓ TÍTULO</div>`}
    <div style="min-width:0">
      ${m.title ? `<div class="t" title="Vídeo original: ${esc(m.title)}">${esc(m.title)}</div>` : ""}
      <div class="mine ${m.my_title ? "" : "empty-mine"}" data-my-title="${m.id}" title="Título que você usou (clique para editar)">${m.my_title ? `Seu título: ${esc(m.my_title)}` : "+ título que você usou"}</div>
      ${m.title ? `<div class="m">${esc(m.channel_title || "")}${m.multiplier != null ? ` · viralizou ${fmtMult(m.multiplier)}` : ""}</div>` : ""}
    </div>
    <button class="icon-btn" data-mdel="${m.id}" title="Tirar da lista"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
  </div>`;
  $("#mc-modeled").innerHTML = `
    <div class="box-head"><h3>Vídeos que modelei</h3><span class="dim small" title="A IA trata esta lista como a verdade sobre o seu canal">${NX.modeled.length} vídeo${NX.modeled.length === 1 ? "" : "s"} · a verdade sobre o seu canal</span></div>
    <form class="mc-form" id="mc-add">
      <input class="input" id="mc-link" placeholder="Cole o link do vídeo que você modelou" title="Link do vídeo ORIGINAL que serviu de modelo">
      <input class="input" id="mc-mine" placeholder="Título que você usou (opcional)">
      <button class="btn primary sm" type="submit">Adicionar</button>
    </form>
    ${NX.modeled.length ? `<div class="mc-list">${NX.modeled.map(card).join("")}</div>`
      : `<p class="dim small">Nenhum ainda. Cole o link aqui, ou use o botão <b>Já modelei</b> nas linhas de Descobertas e na prévia de um vídeo.</p>`}`;
}

function renderDNA() {
  const d = NX.dna, x = d.dna;
  const chips = (arr) => `<div class="dna-chips">${arr.map((t) => `<i>${esc(t)}</i>`).join("")}</div>`;
  $("#mc-dna").innerHTML = `
    <div class="box-head"><h3>DNA do canal</h3>${d.stale ? `<span class="tag fresh" title="Você mudou os vídeos modelados ou as correções: atualize">desatualizado</span>` : ""}</div>
    ${x ? `<p class="dna-sum">${esc(x.summary)}</p>
      <div class="dna-row"><span>Temas</span>${chips(x.themes)}</div>
      <div class="dna-row"><span>Formatos</span>${chips(x.formats)}</div>
      <div class="dna-row"><span>Ângulos</span>${chips(x.angles)}</div>
      <div class="dna-row"><span>Público</span><p>${esc(x.audience)}</p></div>
      <div class="dna-row"><span>Estilo dos títulos</span><p>${esc(x.title_style)}</p></div>`
      : `<p class="dim small">É o que a IA entende do seu canal a partir dos vídeos que você modelou. ${d.modeled ? "Clique em Gerar." : "Adicione vídeos modelados primeiro."}</p>`}
    <div class="dna-row"><span title="O que você escrever aqui vale mais do que o que a IA achou">Suas correções (valem como verdade)</span>
      <textarea class="input dna-notes" id="dna-notes" placeholder="Ex.: meu canal NÃO fala de religião; foco em homens de 20 a 35 anos">${esc(d.notes)}</textarea></div>
    <div class="dna-foot">
      <button class="btn ghost sm" id="dna-save-notes">Salvar correções</button>
      <button class="btn sm ${d.stale || !x ? "primary" : ""}" id="dna-build" ${d.modeled && state.aiEnabled ? "" : "disabled"} title="A IA relê os vídeos modelados e as suas correções">${x ? "Atualizar" : "Gerar DNA"} <span class="btn-note">· ~US$ 0,01</span></button>
    </div>`;
}

function renderRun() {
  const b = boldness();
  $("#mc-run").innerHTML = `
    <div class="grow"><h3>Próximos vídeos</h3><p id="mc-bold-tip">${esc(BOLD_TIP[b])}</p></div>
    <div class="field"><span>Ousadia</span>
      <div class="seg" id="mc-bold">${Object.keys(BOLD_TIP).map((k) => `<button data-v="${k}" class="${k === b ? "on" : ""}" title="${esc(BOLD_TIP[k])}">${esc(NX.boldness[k] || k)}</button>`).join("")}</div></div>
    <button class="btn primary" id="nx-run" ${state.aiEnabled ? "" : "disabled"} title="Busca o que está em alta agora no nicho, monta o mapa de território e os próximos vídeos">
      <svg viewBox="0 0 24 24"><path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4z"/></svg>Montar mapa e próximos <span class="btn-note">· ~US$ 0,05</span></button>`;
  bindSeg($("#mc-bold"), (v) => { try { localStorage.setItem("boldness", v); } catch {} $("#mc-bold-tip").textContent = BOLD_TIP[v]; });
}

const inQueue = (title) => NX.queue.find((x) => x.title.toLowerCase() === title.toLowerCase());
const inModeled = (title) => NX.modeled.find((x) => (x.my_title || "").toLowerCase() === title.toLowerCase());
const refThumbs = (refs, n = 3) => refs.slice(0, n).map((r) => `<img loading="lazy" src="https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg" alt="" data-vref="${r.video_id}" title="${esc(r.title)} · viralizou ${fmtMult(r.multiplier)} · há ${ageLong(r.age_days)}">`).join("");

function renderNext() {
  const d = NX.data;
  if (!d) {
    $("#mc-result").innerHTML = `<div class="box"><div class="empty"><b>Nenhuma rodada ainda</b>
      Adicione os vídeos que você já modelou, escolha a ousadia e clique em <b>Montar mapa e próximos</b>.</div></div>`;
    return;
  }
  const lvl = (c) => (c >= 60 ? "hi" : c >= 40 ? "mid" : "lo");
  const col = (st) => {
    const list = d.territories.filter((t) => t.status === st);
    return `<div class="terr-col ${st}"><h4 title="${esc(TERR[st][1])}"><i></i>${TERR[st][0]}</h4>
      ${list.length ? list.map((t) => `<div class="terr-card"><b>${esc(t.name)}<span class="heat ${t.heat}" title="Quanto está em alta">${t.heat === "alta" ? "em alta" : t.heat === "media" ? "morno" : "fraco"}</span></b>
        <p>${esc(t.why)}</p><div class="terr-thumbs">${refThumbs(t.refs, 4)}</div></div>`).join("") : `<div class="terr-empty">Nada aqui agora.</div>`}</div>`;
  };
  $("#mc-result").innerHTML = `
    <div class="nx-strategy"><span>A estratégia agora · ousadia ${esc(NX.boldness[d.boldness] || "")}</span><p>${esc(d.strategy)}</p></div>
    <div class="nx-meta"><span title="Como a IA entendeu o seu nicho">Nicho: ${esc(d.niche)}</span>
      <span>${fmtDate(d.created_at)} · ${d.pool.length} vídeos em alta analisados · ${fmtUSD(d.cost_usd)}</span></div>
    ${d.territories.length ? `<div class="box" style="margin-bottom:12px"><div class="box-head"><h3>Mapa de território</h3><span class="dim small">o que está em alta no nicho, agrupado por assunto</span></div>
      <div class="terr">${col("seu")}${col("fronteira")}${col("saturado")}</div></div>` : ""}
    <div class="var-list">${d.items.map((it, i) => {
      const q = inQueue(it.title), md = inModeled(it.title);
      return `
      <div class="var nx-item ${lvl(it.chance)}">
        <div class="var-chance" title="Chance de viralizar (estimativa da IA com base nos vídeos em alta)"><b>${it.chance}%</b><i style="width:${it.chance}%"></i></div>
        <div class="var-body">
          <div class="var-title" data-copy="${esc(it.title)}" title="Clique para copiar">${i + 1}. ${esc(it.title)}</div>
          <div><span class="tag k-${it.kind}" title="${esc(NX_KIND_TIP[it.kind] || "")}">${esc(NX.kinds[it.kind] || it.kind)}</span>
            ${it.territory ? `<span class="tag terr-tag" title="Território do mapa">${esc(it.territory)}</span>` : ""}</div>
          <div class="var-why">${esc(it.why)}</div>
          ${it.hook ? `<div class="nx-hook" data-copy="${esc(it.hook)}" title="Clique para copiar o gancho">${esc(it.hook)}</div>` : ""}
          ${it.refs.length ? `<div class="nx-refs">${it.refs.map((r) => `
            <div class="nx-ref" data-vref="${r.video_id}" title="${esc(r.title)} · ${esc(r.channel_title || "")} · ${fmt(r.views)} views · postado há ${ageLong(r.age_days)}">
              <img loading="lazy" src="https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg" alt=""><span>${esc(r.title)}</span><b class="${multClass(r.multiplier)}">${fmtMult(r.multiplier)}</b></div>`).join("")}</div>` : ""}
          <div class="nx-actions">${md ? `<span class="tag new">Já fiz</span>` : q ? `<span class="tag neutral">Na sua fila</span>`
            : `<button class="btn sm" data-nx-add="${i}" title="Coloca na sua fila (vou fazer)">+ Vou fazer</button>
               <button class="btn ghost sm" data-nx-add="${i}" data-done="1" title="Marca que você já fez um vídeo assim (entra nos modelados)">Já fiz</button>`}</div>
        </div>
      </div>`;
    }).join("")}</div>`;
}

function renderQueue() {
  $("#mc-queue").innerHTML = `
    <div class="box-head"><h3>Vou fazer</h3><span class="dim small">${NX.queue.length} na fila</span></div>
    <form class="nx-add" id="nx-add"><input class="input" id="nx-add-title" placeholder="Adicionar um vídeo à fila…"><button class="btn sm" type="submit">Adicionar</button></form>
    ${NX.queue.length ? NX.queue.map((x) => `<div class="q-item" data-qid="${x.id}">
      <button class="q-check" data-q-done="${x.id}" title="Fiz! Vai para os vídeos modelados"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg></button>
      <span class="q-title" ${x.video_id ? `data-vref="${x.video_id}" style="cursor:pointer"` : ""} title="${esc(x.note || x.title)}">${esc(x.title)}</span>
      <button class="icon-btn" data-q-del="${x.id}" title="Tirar da fila"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`).join("")
      : `<p class="dim small">Nada na fila. Use "+ Vou fazer" nas sugestões.</p>`}`;
}

async function startNext() {
  if (!state.profile) return toast("Escolha o perfil em uso primeiro.", "err");
  try {
    watchJob(await api("/api/next", { method: "POST", body: { profile_id: state.profile, boldness: boldness() } }));
    toast("Montando o mapa e os próximos vídeos… (cerca de 1 minuto)");
  } catch (e) { toast(e.message, "err"); }
}

$("#nx-history").addEventListener("change", (e) => loadNext(+e.target.value));

$("#page-next").addEventListener("click", async (e) => {
  const t = e.target;
  try {
    if (t.closest("#nx-run")) return startNext();
    const cp = t.closest("[data-copy]");
    if (cp) { await navigator.clipboard.writeText(cp.dataset.copy); return toast("Copiado.", "ok"); }
    const vr = t.closest("[data-vref]");
    if (vr) return openPreview(vr.dataset.vref);
    const add = t.closest("[data-nx-add]");
    if (add) {
      const it = NX.data.items[+add.dataset.nxAdd];
      if (add.dataset.done) {
        await api("/api/modeled", { method: "POST", body: { profile_id: state.profile, video: it.refs[0]?.video_id || null, my_title: it.title } });
        toast("Entrou nos vídeos modelados.", "ok");
      } else {
        await api("/api/queue", { method: "POST", body: { profile_id: state.profile, title: it.title, kind: it.kind, note: it.why, video_id: it.refs[0]?.video_id || null } });
      }
      return loadNext(NX.data.id);
    }
    const qd = t.closest("[data-q-done]");
    if (qd) { await api(`/api/queue/${qd.dataset.qDone}/done`, { method: "POST" }); toast("Feito! Entrou nos vídeos modelados.", "ok"); return loadNext(NX.data?.id); }
    const qx = t.closest("[data-q-del]");
    if (qx) { await api(`/api/queue/${qx.dataset.qDel}`, { method: "DELETE" }); return loadNext(NX.data?.id); }
    const md = t.closest("[data-mdel]");
    if (md) { await api(`/api/modeled/${md.dataset.mdel}`, { method: "DELETE" }); return loadNext(NX.data?.id); }
    const mt = t.closest("[data-my-title]");
    if (mt) {
      const m = NX.modeled.find((x) => x.id === +mt.dataset.myTitle);
      const v = prompt("Título que você usou no seu vídeo:", m.my_title || "");
      if (v === null) return;
      await api(`/api/modeled/${m.id}`, { method: "PATCH", body: { my_title: v } });
      return loadNext(NX.data?.id);
    }
    if (t.closest("#dna-save-notes")) {
      NX.dna = await api(`/api/dna/${state.profile}/notes`, { method: "POST", body: { notes: $("#dna-notes").value } });
      toast("Correções salvas. Clique em Atualizar para a IA usar.", "ok");
      return renderDNA();
    }
    const db_ = t.closest("#dna-build");
    if (db_) {
      db_.disabled = true; db_.textContent = "IA lendo os seus vídeos…";
      NX.dna = await api(`/api/dna/${state.profile}`, { method: "POST" });
      return renderDNA();
    }
  } catch (err) { toast(err.message, "err"); renderDNA(); }
});

$("#page-next").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    if (e.target.id === "mc-add") {
      const link = $("#mc-link").value.trim(), mine = $("#mc-mine").value.trim();
      if (!link && !mine) return;
      const btn = $("button", e.target); btn.disabled = true; btn.textContent = "Buscando…";
      await api("/api/modeled", { method: "POST", body: { profile_id: state.profile, video: link || null, my_title: mine || null } });
      return loadNext(NX.data?.id);
    }
    if (e.target.id === "nx-add") {
      const t = $("#nx-add-title").value.trim();
      if (!t) return;
      await api("/api/queue", { method: "POST", body: { profile_id: state.profile, title: t } });
      return loadNext(NX.data?.id);
    }
  } catch (err) { toast(err.message, "err"); loadNext(NX.data?.id); }
});

// "Já modelei" (linhas de Descobertas e prévia): liga/desliga o vídeo na lista de modelados do perfil em uso.
const modeledBtn = (id) => {
  const on = state.modeled.has(id);
  return `<button class="icon-btn ${on ? "on" : ""}" data-modeled="${id}" title="${on ? "Já modelado (clique para tirar de Meu canal)" : "Já modelei este: leva para Meu canal"}">
    <svg viewBox="0 0 24 24"><path d="M4 18V8l8-5 8 5v10"/><path d="M9 21v-6h6v6"/>${on ? `<path d="M8.5 12l2.5 2.5 4.5-5"/>` : ""}</svg></button>`;
};
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-modeled]");
  if (!b) return;
  e.stopPropagation();
  if (!state.profile) return toast("Escolha o perfil em uso primeiro.", "err");
  const id = b.dataset.modeled;
  try {
    if (state.modeled.has(id)) {
      await api(`/api/modeled/${state.modeled.get(id)}`, { method: "DELETE" });
      state.modeled.delete(id);
      toast("Tirado de Meu canal.", "ok");
    } else {
      const r = await api("/api/modeled", { method: "POST", body: { profile_id: state.profile, video: id } });
      state.modeled.set(id, r.id);
      toast("Levado para Meu canal (vídeos que modelei).", "ok");
    }
    renderVideos();
    if (!$("#pv").hidden && PV.id) renderPreview();
    if ($("#page-next").classList.contains("active")) loadNext(NX.data?.id);
  } catch (err) { toast(err.message, "err"); }
}, true);
