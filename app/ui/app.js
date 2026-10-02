// darkbot — interface. Dados carregados uma vez; filtros e ordenação rodam no navegador (instantâneo).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  profiles: [],
  videos: [],
  channels: [],
  vSort: { key: null, dir: -1 },   // null = a ordem dos parâmetros de viral
  viral: null, viralInfo: null,
  cSort: { key: "best_multiplier", dir: -1 },
  vLimit: 150,
  watching: new Set(),
  malandroRunning: new Set(),   // vídeos com o Método Malandro rodando (o botão mostra "Rodando…")
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

// Meus parâmetros de viral (Configurações): a régua do app inteiro. Mesma conta do servidor (app/viral.py).
const SORT_KEY = { vph: "views_hour", views: "views", mult: "multiplier" };
const viralSortKey = () => SORT_KEY[state.viral?.sort] || "views_hour";
function passesViral(v, p = state.viral) {
  if (!p) return true;
  const age = v.age_days ?? (v.age_hours != null ? v.age_hours / 24 : null);
  if (age == null || age > p.max_days) return false;
  if ((v.views || 0) < p.min_views) return false;
  if (p.min_vph && (v.views_hour || 0) < p.min_vph) return false;
  if (p.min_mult && (v.multiplier || 0) < p.min_mult) return false;
  if (p.max_subs && (v.subs == null || v.subs > p.max_subs)) return false;
  if (p.only_dark && v.is_dark === false) return false;
  return true;
}
async function loadViral() {
  state.viralInfo = await api("/api/viral");
  state.viral = state.viralInfo.params;
  renderParamsChip();
}
function renderParamsChip() {
  const i = state.viralInfo;
  $("#params-chip").innerHTML = `<span class="pc-label">Seus parâmetros</span>
    <span class="pc-text">${esc(i.text)} · ordem: ${esc((i.sorts[i.params.sort] || "").split(" (")[0].toLowerCase())}</span>
    <span class="link" data-goto="settings" title="Mudar o que conta como viralizando agora">editar</span>`;
}

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

// "Achar parecidos" (prévia): pesquisa a partir do vídeo.
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-seed]");
  if (!b) return;
  e.stopPropagation();
  startResearch({ kind: "video", seed: b.dataset.seed });
}, true);

// Marcações de novidade: canal novo e vídeo recente.
function newTags(v) {
  const t = [];
  if (v.channel_age_days != null && v.channel_age_days <= 180) t.push(`<span class="tag new" title="Canal criado há ${ageLong(v.channel_age_days)} (canal novo indo bem = tem espaço no nicho)">Canal novo · ${fmtAge(v.channel_age_days)}</span>`);
  if (v.age_days != null && v.age_days <= 2) t.push(`<span class="tag fresh" title="Postado há ${ageLong(v.age_days)}">Recente</span>`);
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
    ${modeledBtn(v.video_id)}</div>`;
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
  if (!$("#pv").hidden && PV.id) openPreview(PV.id, true);
}

const openYT = (path) => api("/api/open-url", { method: "POST", body: { url: `https://www.youtube.com/${path}` } });

// ---------------------------------------------------------------- navegação

function go(page) {
  $$(".nav-item").forEach((x) => x.classList.toggle("active", x.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${page}`));
  if (page === "profiles") loadProfiles();
  if (page === "settings") loadSettings();
  if (page === "next") loadNext();
}
$$(".nav-item").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));

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
  for (const id of ["#v-profile"]) {
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
  $("#v-run").value = "";
  await refreshAll();
  toast(`Usando o perfil ${currentProfile()?.name || ""}.`, "ok");
}

$("#active-profile").addEventListener("click", () => openProfilePicker(false));
$("#pick-list").addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (b) useProfile(+b.dataset.pick); });
$("[data-pick-close]").addEventListener("click", closeProfilePicker);
$("#pick-add").addEventListener("click", () => {
  $("#pick-modal").hidden = true;
  go("profiles");
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

// Perfil com nicho definido: em "Só o que viraliza agora", só entra o que a IA confirmou como do nicho (nota 2 ou 3).
const nicheOn = () => { const p = currentProfile(); return !!(p && p.kind !== "coringa" && p.niche); };
// Nicho pequeno: se os parâmetros trazem pouca coisa, a lista amplia o período (30, depois 90 dias) e marca o que
// é mais velho que os parâmetros como "fora do período". A ordem continua a dos parâmetros (views por hora).
const WIDEN_DAYS = [30, 90], MIN_LIST = 10;
function filteredVideos() {
  const onlyParams = segValue($("#v-mode")) === "params";
  const q = $("#v-search").value.trim().toLowerCase();
  const niche = nicheOn();
  const pick = (p) => state.videos.filter((v) => {
    if (onlyParams && !passesViral(v, p)) return false;
    if (onlyParams && niche && !(v.niche_fit >= 2)) return false;
    if (q && !`${v.title} ${v.channel_title}`.toLowerCase().includes(q)) return false;
    return true;
  });
  let list = pick(state.viral);
  state.widenedDays = null;
  if (onlyParams && list.length < MIN_LIST && state.viral) {
    for (const wd of WIDEN_DAYS) {
      if (wd <= state.viral.max_days) continue;
      const wider = pick({ ...state.viral, max_days: wd });
      if (wider.length > list.length) { list = wider; state.widenedDays = wd; }
      if (list.length >= MIN_LIST) break;
    }
  }
  return list;
}
const outOfPeriod = (v) => state.widenedDays && (v.age_days ?? (v.age_hours != null ? v.age_hours / 24 : 0)) > state.viral.max_days;
const vSortNow = () => state.vSort.key ? state.vSort : { key: viralSortKey(), dir: -1 };

function renderVideos() {
  const vs = vSortNow();
  const list = sortBy(filteredVideos(), vs);
  const shown = list.slice(0, state.vLimit);
  $$("#v-table th[data-sort]").forEach((th) => {
    const on = th.dataset.sort === vs.key;
    th.classList.toggle("sorted", on); th.classList.toggle("asc", on && vs.dir > 0); th.classList.toggle("desc", on && vs.dir < 0);
  });
  const body = $("#v-table tbody");

  body.innerHTML = shown.map((v) => {
    const tags = [];
    if (outOfPeriod(v)) tags.push(`<span class="tag fresh" title="Mais velho que os ${state.viral.max_days} dias dos seus parâmetros: entrou porque no seu período veio pouca coisa">fora do período</span>`);
    tags.push(...channelTags(v));
    if (v.sources && v.sources.includes("history")) tags.push(`<span class="tag via" title="O perfil assistiu esse vídeo (veio do histórico)">Assistido</span>`);
    if (v.sources && v.sources.includes("research")) tags.push(`<span class="tag via" title="Veio de uma pesquisa">Pesquisa</span>`);
    if (v.sources && v.sources.includes("garimpo")) tags.push(`<span class="tag via" title="Achado no garimpo: o darkbot assistiu no perfil e entrou nos sugeridos e nos canais do nicho">Garimpo</span>`);
    tags.push(...newTags(v));
    if (v.niche_fit != null && v.niche_fit < 2 && nicheOn()) tags.unshift(`<span class="tag warn" title="A IA conferiu: não é do nicho do perfil (${esc(currentProfile()?.niche || "")})">Fora do nicho</span>`);
    return `<tr class="clickable" data-id="${v.video_id}">
      <td><div class="thumb"><img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
        ${v.duration_s != null ? `<span class="dur">${fmtDur(v.duration_s)}</span>` : ""}</div></td>
      <td>${titleCell(v)}
        <div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span>${langTag(v)}${tags.join("")}</div></td>
      <td class="num" title="Faz ${fmt(v.views_hour)} views por hora desde que foi postado"><b class="vph">${fmt(v.views_hour)}</b></td>
      <td class="num"><span class="mult ${multClass(v.multiplier)}" title="${viralTip(v.multiplier)}">${fmtMult(v.multiplier)}</span></td>
      <td class="num" title="${fmt(v.views)} views no total">${fmt(v.views)}</td>
      <td class="num ${v.growth_hour == null ? "dim" : v.growth_hour > (v.views_hour || 0) ? "up" : ""}" title="${v.growth_hour != null
        ? `${fmt(v.growth_hour)} views por hora entre as duas últimas coletas (a média desde a postagem é ${fmt(v.views_hour)}/h): ${v.growth_hour > (v.views_hour || 0) ? "está ACELERANDO" : "está desacelerando"}`
        : "Precisa de pelo menos duas coletas com 1 hora ou mais de diferença"}">${v.growth_hour != null ? `${fmt(v.growth_hour)}/h${v.growth_hour > (v.views_hour || 0) ? " ↑" : ""}` : "—"}</td>
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
    empty.innerHTML = segValue($("#v-mode")) === "params"
      ? `<b>Nenhum vídeo do nicho bate os seus parâmetros agora</b>Pesquise um assunto (ou cole um vídeo) na barra acima, veja <span class="link" data-vmode="all">Tudo</span> ou afrouxe os parâmetros em <span class="link" data-goto="settings">Configurações</span>.`
      : `<b>Nenhum vídeo com esses filtros</b>Apague a busca para ver mais vídeos.`;
    empty.hidden = false;
  } else empty.hidden = true;
  let widen = $("#v-widen");
  if (!widen) {
    widen = document.createElement("div");
    widen.id = "v-widen";
    widen.className = "alert info v-widen";
    $("#v-table").closest(".table-wrap").before(widen);
  }
  widen.hidden = !state.widenedDays;
  if (state.widenedDays) widen.innerHTML = `Nos seus ${state.viral.max_days} dias veio pouca coisa do nicho: mostrando também os vídeos de até <b>${state.widenedDays} dias</b> (marcados "fora do período"), do mais recente e mais visto para o menos.`;

  // Vídeos que batem a régua mas ainda não foram conferidos com o nicho do perfil (coletas antigas).
  const unchecked = nicheOn() ? state.videos.filter((v) => v.niche_fit == null && passesViral(v)).length : 0;
  const nb = $("#v-niche");
  nb.hidden = !unchecked;
  if (unchecked) nb.innerHTML = `<span><b>${unchecked}</b> vídeos que viralizam ainda não foram conferidos com o nicho do perfil
    (<b>${esc(currentProfile().niche)}</b>) e estão escondidos.</span>
    <button class="btn sm" id="v-niche-go" ${state.aiEnabled ? "" : "disabled"}>Conferir com o nicho <span class="btn-note">· ~US$ ${Math.max(0.01, unchecked * 0.00006).toFixed(2).replace(".", ",")}</span></button>`;
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
bindSeg($("#v-mode"), renderVideos);
document.addEventListener("click", async (e) => {
  const b = e.target.closest("#v-niche-go");
  if (!b || !state.profile) return;
  b.disabled = true;
  try { watchJob(await api(`/api/profiles/${state.profile}/niche-check`, { method: "POST" })); toast("Conferindo o nicho… (uns 20 segundos)"); }
  catch (err) { toast(err.message, "err"); b.disabled = false; }
});
document.addEventListener("click", (e) => { if (e.target.closest("[data-vmode]")) $('#v-mode [data-v="all"]').click(); });
$("#v-search").addEventListener("input", renderVideos);
$("#v-profile").addEventListener("change", loadVideos);
bindSort($("#v-table"), state.vSort, renderVideos);
$("#btn-refresh").addEventListener("click", async () => {
  try { watchJob(await api("/api/refresh", { method: "POST" })); } catch (e) { toast(e.message, "err"); }
});
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) go(g.dataset.goto);
});

// ---------------------------------------------------------------- perfis

const ICON_PROFILE = `<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>`;
const ICON_JOKER = `<svg viewBox="0 0 24 24"><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z"/></svg>`;

async function loadProfiles() {
  const [profiles, runs] = await Promise.all([api("/api/profiles"), api("/api/runs?limit=200")]);
  state.profiles = profiles;
  fillProfileSelects();
  // Última atividade de cada perfil (coleta, histórico ou garimpo; as pesquisas ficam de fora).
  const last = {}, count = {};
  for (const r of runs) {
    if (!r.profile_id || r.research_id) continue;
    if (!last[r.profile_id]) last[r.profile_id] = r;
    count[r.profile_id] = (count[r.profile_id] || 0) + 1;
  }
  const wrap = $("#profiles");
  if (!state.profiles.length) {
    wrap.innerHTML = `<div class="card" style="grid-column:1/-1"><div class="empty"><b>Nenhum perfil ainda</b>
      Adicione um perfil do Chrome já treinado no nicho, ou um perfil "coringa" que consome vários nichos dark.</div></div>`;
    return;
  }
  const what = { home: "Coleta da home", history: "Coleta do que assistiu", garimpo: "Garimpo" };
  wrap.innerHTML = state.profiles.map((p) => {
    const r = last[p.id], using = p.id === state.profile;
    const lastLine = !r ? `<span class="dim">Nenhuma coleta nem garimpo ainda.</span>`
      : r.status === "running" ? `<span class="up">${what[r.source] || "Coleta"} rodando agora…</span>`
      : r.status === "error" ? `<span class="err-text" title="${esc(r.error || "")}">${what[r.source] || "Coleta"} deu erro em ${fmtDate(r.started_at)}: ${esc((r.error || "").slice(0, 90))}</span>`
      : `${what[r.source] || "Coleta"} em ${fmtDate(r.started_at)} · ${r.videos_found || 0} vídeos${!r.logged_in && r.source === "home" ? " · sem login" : ""}`;
    return `
      <div class="card ${using ? "using" : ""}" data-pid="${p.id}">
        <div class="card-top">
          <div class="card-icon ${p.kind}">${p.kind === "coringa" ? ICON_JOKER : ICON_PROFILE}</div>
          <div style="flex:1;min-width:0">
            <div class="card-title">${esc(p.name)} ${using ? `<span class="tag good" title="É o perfil que o app está usando agora">Em uso</span>` : ""}</div>
            <div class="card-sub"><span class="card-niche" title="${esc(p.niche || "")}">${p.kind === "coringa" ? "Coringa" : "Nicho"}${p.niche ? ` · ${esc(p.niche)}` : " · sem nicho"}</span><button class="icon-btn edit-pen" data-act="edit-niche" title="Corrigir nicho e tipo"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg></button></div>
          </div>
          <button class="icon-btn" data-act="delete" title="Excluir perfil"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>
        <div class="card-stats">
          <div><b>${fmt(p.videos)}</b><span>vídeos</span></div>
          <div title="Coletas da home, do histórico e garimpos deste perfil"><b>${count[p.id] || 0}</b><span>coletas</span></div>
          <div><b>${p.last_run_at ? new Date(p.last_run_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "—"}</b><span>última</span></div>
        </div>
        <div class="card-last" title="O que foi feito por último neste perfil">${lastLine}</div>
        ${p.in_use ? `<div class="alert warn">Aberto no Chrome agora: feche a janela para coletar ou garimpar.</div>` : ""}
        <div class="card-actions">
          ${using ? "" : `<button class="btn sm" data-act="use" title="Passa a usar este perfil no app inteiro">Usar este</button>`}
          <button class="btn primary sm" data-act="collect" title="Abre o perfil, rola a página inicial e anota os vídeos que o YouTube mostrar">Coletar a home</button>
          <button class="btn sm" data-act="garimpo" title="Assiste vídeos do nicho, entra nos sugeridos e nos canais, aquece o perfil e traz o que achar">Garimpar</button>
        </div>
        <details class="card-more"><summary>Mais opções</summary>
          <div class="card-actions">
            <label class="scrolls" title="Quantas vezes rolar a página inicial do YouTube. Mais = mais vídeos (e mais demora)">Rolar <input class="input" type="number" min="1" max="80" value="15" data-scrolls></label>
            <label class="check" title="Mostra a janela do Chrome enquanto coleta (para acompanhar)"><input type="checkbox" data-show> mostrar o Chrome</label>
          </div>
          <div class="card-actions">
            <button class="btn ghost sm" data-act="open" title="Abre o Chrome nesse perfil para você entrar na conta do YouTube">Entrar na conta</button>
            <button class="btn ghost sm" data-act="train" title="Abre o Chrome do perfil já pesquisando o nicho, para você assistir à mão">Abrir o Chrome no nicho</button>
            <button class="btn ghost sm" data-act="history" title="Anota os vídeos que esse perfil assistiu (o histórico do YouTube; precisa estar logado)">Coletar o que assistiu</button>
          </div>
        </details>
      </div>`;
  }).join("");
}

$("#profiles").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const card = btn.closest("[data-pid]"), pid = card.dataset.pid;
  const p = state.profiles.find((x) => x.id == pid);
  try {
    if (btn.dataset.act === "use") {
      return useProfile(p.id).then(loadProfiles);
    } else if (btn.dataset.act === "garimpo") {
      return openGarimpo(p.id);
    } else if (btn.dataset.act === "collect") {
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

// ---------------------------------------------------------------- pesquisa (sob demanda) e relatório do nicho

// A pesquisa busca em vários idiomas e entra nos sugeridos; o que acha cai em Viralizando agora. Sem relatório
// automático (economia): o relatório é pedido na prévia do vídeo ou em Coletas e abre no painel da direita.
const R = { data: null };   // pesquisa do relatório aberto (para os títulos dos vídeos citados)

// "[videoId]" no texto da IA vira link para o vídeo.
function linkIds(text) {
  return esc(text).replace(/\[([A-Za-z0-9_-]{11})\]/g, (_, id) => `<span class="vid-ref" data-vref="${id}" title="Abrir vídeo">▶ ${videoTitle(id, 32)}</span>`);
}
function videoTitle(id, max = 60) {
  const v = R.data?.videos.find((x) => x.video_id === id);
  const t = v?.title || id;
  return esc(t.length > max ? t.slice(0, max - 1) + "…" : t);
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

    <div class="box"><div class="box-head"><h3>Modele estes agora</h3><span class="dim small">vídeos reais que estão viralizando</span></div>
      <div class="model-list">${rep.to_model.map((m, i) => {
        const v = R.data.videos.find((x) => x.video_id === m.video_id);
        return `<div class="model-row" data-vref="${esc(m.video_id)}">
          <span class="rank">${i + 1}</span>
          <img src="https://i.ytimg.com/vi/${esc(m.video_id)}/mqdefault.jpg" alt="">
          <div class="grow"><div class="otitle">${videoTitle(m.video_id, 90)}</div>
            <div class="model-why">${linkIds(m.why)}</div>
            ${v ? `<div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span><span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span>
              <span title="Views por hora">${fmt(v.views_hour)}/h</span><span>${fmt(v.views)} views</span><span>${fmtAge(v.age_days)}</span></div>` : ""}</div>
          ${modeledBtn(m.video_id)}
        </div>`; }).join("")}</div>
    </div>

    <div class="${rep.gaps?.length ? "grid2" : ""}">
      <div class="box"><div class="box-head"><h3>O que está funcionando</h3></div>
        <ul class="r-bullets">${rep.what_works.map((x) => `<li>${linkIds(x)}</li>`).join("")}</ul></div>
      ${rep.gaps?.length ? `<div class="box"><div class="box-head"><h3>Brechas</h3><span class="dim small" title="O que o público pede ou está crescendo e quase ninguém entregou ainda">espaço livre agora</span></div>
        <ul class="r-bullets gaps">${rep.gaps.map((x) => `<li>${linkIds(x)}</li>`).join("")}</ul></div>` : ""}
    </div>

    <div class="box"><div class="box-head"><h3>O que o público está pedindo</h3><span class="dim small">tirado dos comentários</span></div>
      <div class="asks">${rep.audience_requests.map((a) => `
        <div class="ask"><div class="ask-top"><b>${esc(a.request)}</b><span class="tag ${strength[a.strength]}">sinal ${a.strength === "media" ? "médio" : a.strength}</span></div>
        <div class="ask-quote">“${linkIds(a.evidence.replace(/^["“”'\s]+|["“”'\s]+$/g, ""))}”</div></div>`).join("")}</div>
    </div>

    <div class="grid2">
      <div class="box"><div class="box-head"><h3>Palavras para pesquisar e usar nas tags</h3><span class="dim small">clique para pesquisar</span></div>
        <div class="terms">${rep.keywords.map((k) => `<span class="term sm clickable" data-kw="${esc(k)}">${esc(k)}</span>`).join("")}</div></div>
      <div class="box"><div class="box-head"><h3>Não faça</h3></div>
        <ul class="r-bullets avoid">${rep.avoid.map((x) => `<li>${linkIds(x)}</li>`).join("")}</ul></div>
    </div>`;
}

async function startResearch(body) {
  body.langs = body.langs || selectedLangs();
  if (!body.profile_id) body.profile_id = state.profile;
  body.report = false;
  try {
    const res = await api("/api/research", { method: "POST", body });
    watchJob(res.job, () => researchDone(res.id));
    toast(body.kind === "video" ? "Procurando vídeos parecidos… (uns 2 minutos, acompanhe no canto da tela)"
      : `Pesquisando "${body.seed}"… (uns 2 minutos, acompanhe no canto da tela)`, "ok");
    if (!$("#pv").hidden && PV.id && body.seed === PV.id) openPreview(PV.id, true);
  } catch (e) { toast(e.message, "err"); }
}

// Fim da pesquisa: a lista mostra só o que ela achou (Coleta → Todas volta para tudo).
async function researchDone(rid) {
  try {
    const d = await api(`/api/research/${rid}`);
    if (!d.research.run_id) return;
    await loadRunOptions();
    $("#v-run").value = String(d.research.run_id);
    go("videos");
    await loadVideos();
    toast(`Pesquisa pronta: a lista mostra só os ${d.videos.length} vídeos que ela achou (Coleta → Todas volta para tudo).`, "ok");
    if (!$("#pv").hidden && PV.id && !PV.report) openPreview(PV.id, true);
  } catch {}
}

// Relatório do nicho (sob demanda), no painel da direita.
async function openReport(rid, back = null) {
  $("#pv").hidden = false;
  $("#pv-body").innerHTML = `<div class="pv-loading">Carregando…</div>`;
  try { R.data = await api(`/api/research/${rid}`); } catch (e) { return toast(e.message, "err"); }
  PV.report = { rid, back };
  const { research: r, report, report_meta: meta } = R.data;
  $("#pv-body").innerHTML = `
    <div class="pv-top">
      <span class="pv-kicker">${back ? `<span class="link" data-pv-back="${esc(back)}">← voltar ao vídeo</span> · ` : ""}Relatório do nicho</span>
      <button class="icon-btn" id="pv-close" title="Fechar (Esc)"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
    <h2 class="pv-title">${esc(r.label)}</h2>
    <div class="dim small">${R.data.videos.length} vídeos na pesquisa · ${fmtDate(r.created_at)}${meta ? ` · relatório custou ${fmtUSD(meta.cost_usd)}` : ""}</div>
    ${report ? `<div class="pv-report">${renderReport(report)}</div>
      <div class="mal-foot dim small"><span class="link" data-report-make="${rid}" data-refresh="1">refazer o relatório (~US$ 0,06)</span></div>`
      : `<div class="pv-section"><p class="dim small">A IA lê os vídeos e os comentários desta pesquisa e diz o que está funcionando, as brechas,
        o que o público pede e os 8 melhores vídeos para modelar agora.</p>
        <button class="btn primary sm" data-report-make="${rid}" ${state.aiEnabled ? "" : "disabled"}>Gerar relatório <span class="btn-note">· ~US$ 0,06</span></button></div>`}`;
}
document.addEventListener("click", async (e) => {
  const mk = e.target.closest("[data-report-make]");
  if (mk) {
    e.stopPropagation();
    if (mk.dataset.refresh && !confirm("Refazer o relatório gasta tokens de novo (~US$ 0,06). Continuar?")) return;
    const rid = +mk.dataset.reportMake, back = PV.report?.back || null;
    mk.disabled = true;
    try {
      watchJob(await api(`/api/research/${rid}/report`, { method: "POST" }), () => { if (!$("#pv").hidden && PV.report?.rid === rid) openReport(rid, back); });
      toast("IA escrevendo o relatório (1 a 2 minutos)…");
    } catch (err) { toast(err.message, "err"); mk.disabled = false; }
    return;
  }
  const op = e.target.closest("[data-report-open]");
  if (op) { e.stopPropagation(); closeRunsModal(); return openReport(+op.dataset.reportOpen, op.dataset.back || null); }
  const rr = e.target.closest("[data-research-run]");
  if (rr) {
    e.stopPropagation();
    await loadRunOptions();
    $("#v-run").value = rr.dataset.researchRun;
    closePreview();
    go("videos");
    loadVideos();
  }
}, true);

// ---------------------------------------------------------------- idiomas

// Idiomas da busca: a escolha fica lembrada (só neste computador).
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

// ---------------------------------------------------------------- barra de pesquisa por nicho (Descobrir)

// Link do YouTube = pesquisa a partir do vídeo; qualquer outro texto = pesquisa por assunto.
const YT_LINK = /(youtube\.com\/(watch|shorts\/|live\/)|youtu\.be\/)/i;
async function nicheSearch() {
  const q = $("#nb-query").value.trim();
  if (!q) return toast("Cole o link de um vídeo ou escreva um assunto.", "err");
  $("#nb-query").value = "";
  await startResearch({ kind: YT_LINK.test(q) ? "video" : "keyword", seed: q, langs: pickedLangs($("#nb-langs")) });
}
$("#nb-go").addEventListener("click", nicheSearch);

// Garimpo no perfil: o darkbot faz no Chrome do perfil o caminho que o editor faz à mão.
// O ponto de partida é obrigatório em perfil coringa ou sem nicho (o nicho dele não serve de busca).
function openGarimpo(pid) {
  const p = state.profiles.find((x) => x.id === pid);
  if (!p) return;
  state.gPid = pid;
  state.gNeedSeed = p.kind === "coringa" || !p.niche;
  $("#g-profile").textContent = p.name;
  $("#g-seed").value = $("#nb-query").value.trim();
  $("#g-seed").placeholder = `Link de um vídeo dark do nicho, ou o tema / um título${state.gNeedSeed ? " (obrigatório neste perfil)" : ` (vazio = ${p.niche})`}`;
  $("#gmodal").hidden = false;
  setTimeout(() => $("#g-seed").focus(), 50);
}
$("#nb-garimpo").addEventListener("click", () => (state.profile ? openGarimpo(state.profile) : openProfilePicker(false)));
bindSeg($("#g-mode"), () => {});
$$("[data-gclose]").forEach((b) => b.addEventListener("click", () => { $("#gmodal").hidden = true; }));
$("#g-start").addEventListener("click", async () => {
  if (state.gNeedSeed && !$("#g-seed").value.trim())
    return toast("Este perfil é coringa (ou sem nicho): cole o link de um vídeo dark ou escreva o tema para garimpar.", "err");
  try {
    const j = await api(`/api/profiles/${state.gPid}/garimpo`, { method: "POST",
      body: { seed: $("#g-seed").value.trim(), mode: segValue($("#g-mode")), show_browser: $("#g-show").checked } });
    $("#gmodal").hidden = true;
    $("#nb-query").value = "";
    watchJob(j);
    toast("Garimpo começou: acompanhe no canto da tela (dá para cancelar por lá).", "ok");
  } catch (e) { toast(e.message, "err"); }
});
$("#nb-query").addEventListener("keydown", (e) => { if (e.key === "Enter") nicheSearch(); });

// ---------------------------------------------------------------- coletas (filtrar / excluir)

const SRC_LABEL = { home: "Home", history: "Histórico", research: "Pesquisa", garimpo: "Garimpo" };
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
      ${r.research_id && r.status === "done" ? `<button type="button" class="btn ghost sm" data-report-open="${r.research_id}" title="Relatório do nicho desta pesquisa (sob demanda)">Relatório</button>` : ""}
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
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
  btn.textContent = old;
}
$("#v-translate").addEventListener("click", (e) => translateList(filteredVideos().slice(0, state.vLimit), e.currentTarget));

// ---------------------------------------------------------------- prévia do vídeo

const PV = { id: null, data: null, report: null };   // report: o painel está mostrando um relatório

async function openPreview(id, quiet = false) {
  PV.id = id;
  PV.report = null;
  $("#pv").hidden = false;
  if (!quiet) $("#pv-body").innerHTML = `<div class="pv-loading">Carregando…</div>`;
  try { PV.data = await api(`/api/videos/${id}`); } catch (e) { $("#pv").hidden = true; return toast(e.message, "err"); }
  if (PV.id !== id) return;
  renderPreview();
  const v = PV.data.video;
  if (v.foreign && !v.title_pt && state.aiEnabled) {
    api("/api/translate", { method: "POST", body: { ids: [id] } }).then((r) => {
      if (r.titles[id]) v.title_pt = r.titles[id];
      if (PV.id === id && !PV.report && r.titles[id]) renderPreview();
    }).catch(() => {});
  }
}
const closePreview = () => { $("#pv").hidden = true; PV.id = null; PV.report = null; $("#pv-body").innerHTML = ""; };
$("#pv").addEventListener("click", (e) => { if (e.target.id === "pv") closePreview(); });

function renderPreview() {
  const { video: v, comments, analysis: a, research: rs } = PV.data;
  const link = `https://www.youtube.com/watch?v=${v.video_id}`;
  const conf = { alta: "com certeza", media: "provavelmente", baixa: "não tem certeza" };
  const darkState = v.channel_dark_manual != null ? (v.channel_dark_manual ? "dark (você marcou)" : "não é dark (você marcou)")
    : v.channel_format ? `${v.is_dark ? "dark" : "não é dark"} para a IA (${FORMAT_TIP[v.channel_format] || v.channel_format}${v.channel_dark_conf ? `; ${conf[v.channel_dark_conf] || v.channel_dark_conf}` : ""})`
    : "a IA ainda não olhou esse canal";
  const stat = (label, value, tip = "") => `<div class="pv-stat" title="${esc(tip)}"><b>${value}</b><span>${label}</span></div>`;
  const accel = v.growth_hour != null && v.growth_hour > (v.views_hour || 0);
  const ok = passesViral(v);
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
    <div class="pv-tags">
      <span class="tag ${ok ? "good" : "neutral"}" title="Seus parâmetros de viral: ${esc(state.viralInfo?.text || "")}">${ok ? "Viralizando agora" : "Fora dos seus parâmetros"}</span>
      ${langTag(v)}${channelTags(v).join("")}
      ${v.channel_age_days != null && v.channel_age_days <= 180 ? `<span class="tag new">Canal novo · ${fmtAge(v.channel_age_days)}</span>` : ""}
      ${v.hidden ? `<span class="tag warn">Oculto</span>` : ""}</div>

    <div class="pv-stats">
      ${stat("views por hora", fmt(v.views_hour), "Média de views por hora desde a postagem")}
      ${stat("ritmo agora", v.growth_hour != null ? `${fmt(v.growth_hour)}/h${accel ? " ↑" : ""}` : "—",
        v.growth_hour != null ? `Views por hora entre as duas últimas coletas: ${accel ? "está ACELERANDO" : "está desacelerando"}` : "Precisa de duas coletas com 1 hora ou mais de diferença")}
      ${stat("viralizou", `<span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span>`, TIP.viralizou)}
      ${stat("views", fmt(v.views), "Total de views")}
      ${stat("postado há", ageLong(v.age_days) || "—", "Há quanto tempo o vídeo foi postado")}
      ${stat("duração", v.duration_s ? fmtDur(v.duration_s) : "—", "Duração do vídeo")}
    </div>

    <div class="pv-actions">
      <button class="btn primary sm" id="pv-yt">Abrir no YouTube</button>
      <button class="btn sm" data-copy-link="${link}">Copiar link</button>
      <button class="btn sm ${state.modeled.has(v.video_id) ? "primary" : ""}" data-modeled="${v.video_id}" title="${state.modeled.has(v.video_id) ? "Já está nos vídeos que modelei (clique para tirar)" : "Você já modelou este vídeo: entra nos vídeos que modelei (Próximos vídeos)"}">${state.modeled.has(v.video_id) ? "✓ Modelado" : "Já modelei"}</button>
      <button class="btn ghost sm" data-hide="${v.video_id}" ${v.hidden ? `data-unhide="1"` : ""} title="${v.hidden ? "Voltar a mostrar nas listas" : "Esconder este vídeo das listas"}">${v.hidden ? "Mostrar de novo" : "Esconder"}</button>
    </div>

    <div class="pv-ch">
      ${v.channel_thumb ? `<img src="${esc(v.channel_thumb)}" alt="">` : `<div class="avatar ini">${esc((v.channel_title || "?")[0])}</div>`}
      <div class="grow"><b>${esc(v.channel_title || "")}</b>
        <div class="dim small">${fmt(v.subs)} inscritos · canal com ${fmtAge(v.channel_age_days)} · ${esc(darkState)}</div></div>
      <div class="pv-dark-btns">
        <button class="btn sm ${v.channel_dark_manual === 1 ? "primary" : "ghost"}" data-dark="${v.channel_id}" data-val="1" title="Marcar: este canal é dark (ninguém aparece)">É dark</button>
        <button class="btn sm ${v.channel_dark_manual === 0 ? "primary" : "ghost"}" data-dark="${v.channel_id}" data-val="0" title="Marcar: este canal não é dark (a IA aprende com isso)">Não é</button>
        ${v.channel_dark_manual != null ? `<button class="btn ghost sm" data-dark="${v.channel_id}" data-val="" title="Volta a valer o que a IA achou">Desfazer</button>` : ""}
      </div>
    </div>

    <div class="pv-section pv-mal">
      <div class="pv-h"><h3>Método Malandro</h3><span class="dim small">em que língua ninguém fez este vídeo</span></div>
      ${renderMalandro(PV.data.malandro, v.video_id)}
    </div>

    <div class="pv-section">
      <div class="pv-h"><h3>Vídeos parecidos</h3><span class="dim small">pesquisa sob demanda</span></div>
      ${researchBox(rs, v.video_id)}
    </div>

    <div class="pv-section">
      <div class="pv-h"><h3>Análise com IA</h3>${a ? `<button class="btn ghost sm" id="pv-reanalyze">Refazer</button>` : ""}</div>
      ${a ? renderAnalysis(a) : `<p class="dim small">Por que funcionou, título, thumbnail, público e como modelar este vídeo. Feita uma vez e guardada.</p>
        <button class="btn sm" id="pv-analyze" ${state.aiEnabled ? "" : "disabled"}>Analisar este vídeo <span class="btn-note">· ~US$ 0,02</span></button>`}
    </div>

    <details class="pv-section pv-more"><summary><h3>Mais detalhes</h3><span class="dim small">curtidas, comentários, descrição, tags</span></summary>
      <div class="pv-mini">
        <span><b>${fmt(v.likes)}</b> curtidas</span><span><b>${fmt(v.comments)}</b> comentários</span>
        <span title="De cada 100 pessoas que viram, quantas curtiram ou comentaram"><b>${v.engagement != null ? `${String(v.engagement).replace(".", ",")}%` : "—"}</b> interação</span>
        <span><b>${fmt(v.views_day)}</b> views por dia</span>
      </div>
      <div class="idea-label">Comentários com mais curtidas</div>
      ${comments.length ? comments.slice(0, 12).map((c) => `<div class="cm"><span class="cm-likes">♥ ${fmt(c.likes)}</span>${esc(c.text)}</div>`).join("")
        : `<p class="dim small">${v.comments === 0 ? "Sem comentários." : "Comentários indisponíveis (desativados ou sem chave da API)."}</p>`}
      ${v.description ? `<div class="idea-label">Descrição do vídeo</div><p class="pv-desc">${esc(v.description)}</p>` : ""}
      ${v.tags && v.tags.length ? `<div class="idea-label">Tags (clique para copiar)</div>
        <div class="terms" data-copy="${esc(v.tags.join(", "))}">${v.tags.map((t) => `<span class="term sm">${esc(t)}</span>`).join("")}</div>` : ""}
      ${v.channel_description ? `<div class="idea-label">Sobre o canal</div><p class="pv-desc">${esc(v.channel_description)}</p>` : ""}
    </details>`;
}

// Pesquisa de parecidos a partir do vídeo: sob demanda (economia); depois, ver na lista e o relatório do nicho.
function researchBox(rs, id) {
  if (!rs) return `<p class="dim small">O darkbot procura vídeos parecidos com este: busca em vários idiomas, entra nos sugeridos
    e traz os que viralizam para a sua lista. Uns 2 minutos.</p>
    <button class="btn primary sm" data-seed="${id}" ${state.aiEnabled ? "" : "disabled"}>Achar parecidos <span class="btn-note">· ~US$ 0,04</span></button>`;
  if (rs.status === "running") return `<p class="dim small">Procurando parecidos… acompanhe no canto da tela.</p>`;
  return `<div class="pv-rs">
    <span><b>${rs.videos_found || 0}</b> parecidos achados em ${fmtDate(rs.created_at)}</span>
    ${rs.run_id ? `<button class="btn sm" data-research-run="${rs.run_id}" title="A lista de Viralizando agora mostra só eles">Ver na lista</button>` : ""}
    <button class="btn ${rs.has_report ? "" : "ghost"} sm" data-report-open="${rs.id}" data-back="${id}" title="O que funciona, brechas, o que o público pede e os melhores para modelar">${rs.has_report ? "Ver relatório do nicho" : "Relatório do nicho"}</button>
    <span class="link small" data-seed="${id}" title="Faz a pesquisa de novo (~US$ 0,04)">procurar de novo</span>
  </div>`;
}

function renderAnalysis(a) {
  return `<div class="pv-verdict">${esc(a.verdict)}</div>
    <div class="idea-label">Por que funcionou</div><ul class="r-bullets">${a.why_it_worked.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="idea-label">Por que o título funciona</div><p class="pv-p">${esc(a.title_breakdown)}</p>
    <div class="idea-label">Por que a capa (thumbnail) funciona</div><p class="pv-p">${esc(a.thumbnail)}</p>
    <div class="idea-label">O que o público achou</div><p class="pv-p">${esc(a.audience)}</p>
    <div class="idea-label">Como fazer um parecido</div><ol class="idea-structure">${a.how_to_model.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
    <div class="idea-label">Cuidado com</div><ul class="r-bullets avoid">${a.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
}

$("#pv-body").addEventListener("click", async (e) => {
  if (e.target.closest("#pv-close")) return closePreview();
  const bk = e.target.closest("[data-pv-back]");
  if (bk) return openPreview(bk.dataset.pvBack);
  const kw = e.target.closest("[data-kw]");
  if (kw) return startResearch({ kind: "keyword", seed: kw.dataset.kw });
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

const langName = (c) => LANG_NAME[c] || c.toUpperCase();
function renderMalandro(m, videoId, open = false) {
  if (!m) {
    return `<div class="mal-empty"><p class="dim small">Em que línguas <b>ninguém fez este vídeo ainda</b>: a IA escreve o título como um nativo
      escreveria em 13 línguas, o darkbot procura no YouTube de cada país e marca onde está livre.</p>
      ${state.malandroRunning.has(videoId)
        ? `<button class="btn primary sm" disabled>Rodando… a IA está procurando nos 13 países (uns 15 a 30 s)</button>`
        : `<button class="btn primary sm" data-malandro-run="${videoId}" ${state.aiEnabled ? "" : "disabled"}>Rodar Método Malandro <span class="btn-note">· ~US$ 0,01</span></button>`}</div>`;
  }
  const free = m.langs.filter((l) => l.status === "livre");
  const order = { livre: 0, pouca: 1, saturada: 2 };
  const langs = [...m.langs].sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
  return `<div class="mal">
    ${malandroRadar(m)}
    ${m.original_dubs?.length ? `<div class="alert info mal-dub" title="Recurso de áudio em vários idiomas do YouTube: o mesmo vídeo toca dublado para quem fala outra língua">
      O vídeo original tem <b>dublagem automática</b> do YouTube em ${m.original_dubs.map((c) => `${flagImg(c)} ${esc(langName(c))}`).join(", ")}
      (por isso o título aparece traduzido lá). <b>Não conta como "já feito"</b>: só vale quem fez o vídeo nativo na língua.</div>` : ""}
    ${m.original_titles?.length ? `<div class="dim small mal-dub">O canal também traduziu o título para ${m.original_titles.map((c) => esc(langName(c))).join(", ")} (o áudio continua no original).</div>` : ""}
    ${free.length ? `<div class="mal-free"><span>Ninguém fez em:</span>${free.map((l) => `<b>${flagImg(l.code)} ${esc(l.name)}</b>`).join("")}</div>`
      : `<div class="mal-free bad">Esse vídeo já foi feito em todas as línguas pesquisadas.</div>`}
    ${m.paises ? renderPaises(m.paises, m.video_id) : `<div class="paises-cta">
      <p class="dim small"><b>E em que países esse conteúdo venderia?</b> O darkbot mede a <b>procura</b> em 24 países (o que as pessoas
        buscam no YouTube de lá e como os vídeos do tema estão indo no último mês) e cruza com <b>quem já fez</b> esse vídeo em cada idioma.</p>
      <button class="btn sm" data-paises-run="${m.video_id}" ${state.aiEnabled ? "" : "disabled"}>Ver países com procura e sem oferta <span class="btn-note">· ~US$ 0,03</span></button></div>`}
    <details class="mal-details" ${open ? "open" : ""}><summary class="btn sm mal-btn">Ver os vídeos de cada língua</summary>
      <div class="mal-langs">${langs.map((l) => {
        const [lab, cls] = MAL_STATUS[l.status];
        return `<div class="mal-lang ${l.status}">
          <div class="mal-lang-head">${flagImg(l.code)}<b>${esc(l.name)}</b>${l.original ? `<span class="tag via" title="O idioma do vídeo original">idioma do vídeo</span>` : ""}
            ${l.original_dub ? `<span class="tag neutral" title="O original toca com dublagem automática nesse idioma. Não conta como já feito (só vale vídeo nativo).">original tem dublagem</span>` : ""}
            ${l.original_title ? `<span class="tag neutral" title="O canal traduziu o título para esse idioma, mas o áudio continua no original">título traduzido</span>` : ""}
            <span class="tag ${cls}">${lab}</span><span class="dim small">${l.channels === 0 ? "nenhum canal fez" : l.channels === 1 ? "1 canal fez" : `${l.channels} canais fizeram`}</span></div>
          ${l.suggested_title ? `<div class="mal-title" data-copy="${esc(l.suggested_title)}" title="Clique para copiar"><span>Título pronto nesse idioma</span>${esc(l.suggested_title)}</div>` : ""}
          ${l.videos.length ? `<div class="mal-videos">${l.videos.map((v) => `<div class="mal-v" data-vref="${v.video_id}">
              <img src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
              <div class="grow"><div class="otitle">${esc(v.title)}</div>
                <div class="dim small">${esc(v.channel_title || "")} · ${fmt(v.views)} views · ${fmtAge(v.age_days)}${v.relevance >= 3 ? " · <b class='up'>fez o mesmo vídeo</b>" : " · mesmo assunto"}${v.dubs?.length ? ` · dublado em ${v.dubs.map((c) => esc(langName(c))).join(", ")}` : ""}</div></div>
              <span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span></div>`).join("")}</div>` : ""}
        </div>`; }).join("")}</div>
      <div class="mal-foot dim small">Feito em ${fmtDate(m.created_at)} · <span class="link" data-malandro-run="${m.video_id}" data-refresh="1">refazer (~US$ 0,01)</span></div>
    </details>
  </div>`;
}

// Países: procura (buscas e vídeos do tema no país) x oferta (quem já fez esse vídeo no idioma).
const DEMAND = { alta: ["Procura alta", "good"], media: ["Procura média", "warn"], baixa: ["Procura baixa", "neutral"] };
const flagCountry = (cc) => `<img class="flag" src="https://flagcdn.com/w20/${cc.toLowerCase()}.png" alt="${cc}" onerror="this.style.display='none'">`;
function renderPaises(p, videoId) {
  if (!p.markets) return `<div class="paises-cta"><p class="dim small">Medição antiga: refaça para ver por mercado.</p>
    <button class="btn sm" data-paises-run="${videoId}">Medir de novo <span class="btn-note">· ~US$ 0,03</span></button></div>`;
  const card = (c, i) => {
    const [dl, dc] = DEMAND[c.level], [sl, sc] = MAL_STATUS[c.status];
    return `<div class="pais">
      <div class="pais-head"><span class="pais-rank">${i + 1}</span>${flagImg(c.lang)}<b>${esc(c.lang_name)}</b>
        <span class="tag ${dc}" title="Procura medida: buscas que o YouTube completa lá, vídeos do tema com tração no último mês e views por hora típicas">${dl}</span>
        <span class="tag ${sc}" title="Quem já fez ESTE vídeo nesse idioma (Método Malandro)">${sl}</span>
        ${c.original ? `<span class="tag via" title="O idioma do vídeo original">idioma do vídeo</span>` : ""}
        <span class="pais-bar" title="Nota de oportunidade: procura × oferta"><i style="width:${Math.round(Math.min(c.score, 1) * 100)}%"></i></span></div>
      <div class="pais-countries">${c.countries.map((x) =>
        `<span class="${x.auto ? "" : "dim"}" title="${x.auto ? "O YouTube desse país completa buscas sobre o tema" : "O YouTube desse país não completa nada sobre o tema"}">${flagCountry(x.country)} ${esc(x.name)}</span>`).join("")}</div>
      <div class="pais-nums"><span title="Vídeos do tema, nesse idioma, postados no último mês que estão ganhando 30+ views por hora">${c.traction} ${c.traction === 1 ? "vídeo" : "vídeos"} do tema ganhando views no último mês</span> · ${fmt(c.vph_typical)}/h típico</div>
      ${c.why ? `<div class="pais-why">${esc(c.why)}</div>` : ""}
      ${c.adapt ? `<div class="pais-adapt"><span>Adaptar</span>${esc(c.adapt)}</div>` : ""}
      ${c.countries[0]?.suggestions.length ? `<div class="pais-sugg"><span title="O que as pessoas começam a digitar e o YouTube completa, em ${esc(c.countries[0].name)}">Buscam em ${esc(c.countries[0].name)}:</span>${c.countries[0].suggestions.slice(0, 5).map((s) => `<i>${esc(s)}</i>`).join("")}</div>` : ""}
      ${c.title ? `<div class="mal-title" data-copy="${esc(c.title)}" title="Clique para copiar"><span>Título pronto nesse idioma</span>${esc(c.title)}</div>` : ""}
      ${c.best ? `<div class="pais-best dim small" data-vref="${c.best.video_id}" title="O vídeo do tema que mais está ganhando views lá">Mais forte do tema lá: <span class="link">${esc(c.best.title)}</span> · ${fmt(c.best.vph)}/h</div>` : ""}
    </div>`;
  };
  const top = p.markets.filter((c) => c.score > 0 && c.level !== "baixa").slice(0, 6);
  const orig = p.markets.find((c) => c.original);
  const dubbed = p.markets.filter((c) => c.original_dub);
  const nCountries = p.markets.reduce((n, mk) => n + mk.countries.length, 0);
  return `<div class="paises">
    <div class="paises-h"><h4>Onde há procura e ninguém faz</h4><span class="dim small">${nCountries} países, ${p.markets.length} idiomas</span></div>
    ${top.length ? `<p class="paises-sum">${esc(p.summary)}</p>` : ""}
    ${top.length ? top.map(card).join("") : `<div class="paises-none"><b>Nenhum mercado com procura e livre agora.</b>
      Onde há procura, o vídeo já existe; onde está livre, quase ninguém assiste esse tema no último mês.</div>`}
    ${orig ? `<div class="dim small paises-orig">${flagImg(orig.lang)} ${esc(orig.lang_name)} é o idioma do vídeo original: já existe lá, não entra como oportunidade.</div>` : ""}
    ${dubbed.length ? `<div class="dim small paises-orig">${dubbed.map((c) => `${flagImg(c.lang)} ${esc(c.lang_name)}`).join(", ")}: o original tem dublagem automática ${dubbed.length === 1 ? "nesse idioma" : "nesses idiomas"} (não conta como já feito).</div>` : ""}
    <details class="paises-all"><summary class="btn sm mal-btn">Ver todos os ${p.markets.length} idiomas</summary>
      <div class="paises-table">${p.markets.map((c) => `<div class="pt-row">
        ${flagImg(c.lang)}<span class="pt-name">${esc(c.lang_name)}</span><span class="tag ${DEMAND[c.level][1]}">${DEMAND[c.level][0]}</span>
        <span class="tag ${MAL_STATUS[c.status][1]}">${MAL_STATUS[c.status][0]}</span>
        <span class="dim small">${c.countries.map((x) => `${esc(x.name)} ${x.auto}`).join(" · ")} · ${c.traction} com tração</span></div>`).join("")}</div>
    </details>
    <div class="mal-foot dim small">${p.comment_signals ? `Nos comentários: ${esc(p.comment_signals)}<br>` : ""}Feito em ${fmtDate(p.created_at)}${p.cost_usd != null ? ` · ${fmtUSD(p.cost_usd)}` : ""} · <span class="link" data-paises-run="${videoId}" data-refresh="1">refazer</span></div>
  </div>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-paises-run]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.refresh && !confirm("Medir os países de novo (~US$ 0,03)?")) return;
  try { watchJob(await api(`/api/malandro/${b.dataset.paisesRun}/paises`, { method: "POST" })); toast("Medindo a procura em 24 países… (uns 30 segundos)"); }
  catch (err) { toast(err.message, "err"); }
}, true);

// Rodar/refazer o Método Malandro (prévia ou pesquisa).
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-malandro-run]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.refresh && !confirm("Refazer o Método Malandro (~US$ 0,01)?")) return;
  const id = b.dataset.malandroRun;
  // Mostra "Rodando…" no próprio botão (o painel da prévia cobre parte da tela).
  state.malandroRunning.add(id);
  b.disabled = true;
  b.textContent = "Rodando… a IA está procurando nos 13 países (uns 15 a 30 s)";
  try {
    watchJob(await api(`/api/malandro/${id}`, { method: "POST" }), null, (j) => {
      state.malandroRunning.delete(id);
      if (j.status === "error") toast(`Método Malandro: ${j.error}`, "err");
    });
  } catch (err) {
    state.malandroRunning.delete(id);
    b.disabled = false;
    b.textContent = "Rodar Método Malandro";
    toast(err.message, "err");
  }
}, true);

// ---------------------------------------------------------------- configurações

function renderViralForm() {
  const p = state.viral, i = state.viralInfo;
  for (const k of ["max_days", "min_views", "min_vph", "min_mult", "max_subs"]) $(`#vp-${k}`).value = p[k];
  $("#vp-only_dark").checked = p.only_dark;
  $("#vp-sort").innerHTML = Object.entries(i.sorts).map(([k, l]) => `<option value="${k}" ${k === p.sort ? "selected" : ""}>${esc(l)}</option>`).join("");
  $("#vp-text").textContent = `Valendo agora: ${i.text}.`;
}
async function saveViral(body) {
  try {
    state.viralInfo = await api("/api/viral", { method: "POST", body });
    state.viral = state.viralInfo.params;
    renderViralForm(); renderParamsChip(); renderVideos();
    toast("Parâmetros salvos. Valem para o app inteiro.", "ok");
  } catch (e) { toast(e.message, "err"); }
}
$("#vp-save").addEventListener("click", () => saveViral({
  max_days: +$("#vp-max_days").value || 1, min_views: +$("#vp-min_views").value || 0, min_vph: +$("#vp-min_vph").value || 0,
  min_mult: +$("#vp-min_mult").value || 0, max_subs: +$("#vp-max_subs").value || 0,
  only_dark: $("#vp-only_dark").checked, sort: $("#vp-sort").value }));
$("#vp-reset").addEventListener("click", () => saveViral(state.viralInfo.defaults));

async function loadSettings() {
  renderViralForm();
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

function watchJob(j, onDone = null, onEnd = null) {
  if (state.watching.has(j.id)) return;
  state.watching.add(j.id);
  renderJob(j);
  const tick = async () => {
    try { j = await api(`/api/jobs/${j.id}`); } catch { return; }
    const el = renderJob(j);
    if (j.status === "running") return setTimeout(tick, 700);
    state.watching.delete(j.id);
    if (onEnd) onEnd(j);
    if (j.status === "error") $(".job-x", el).addEventListener("click", () => el.remove());
    // Erro fica mais tempo para dar para ler (o detalhe também fica no histórico de coletas).
    setTimeout(() => el.remove(), j.status === "error" ? 12000 : 4000);
    await refreshAll();
    if (j.status === "done" && onDone) onDone(j);
    if (j.kind === "malandro" && !$("#pv").hidden && PV.id && !PV.report) openPreview(PV.id, true);
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
  if ($("#page-next").classList.contains("active")) loadNext();
}

(async () => {
  state.langs = await api("/api/languages");
  renderLangPicker($("#nb-langs"));
  await loadViral();
  state.aiEnabled = (await api("/api/settings")).ai_enabled;
  // Perfil em uso: o último escolhido; se não houver (ou foi apagado), pede para escolher.
  state.profiles = await api("/api/profiles");
  state.profile = savedProfile();
  if (!state.profiles.some((p) => p.id === state.profile)) state.profile = state.profiles.length === 1 ? state.profiles[0].id : null;
  await refreshAll();
  if (!state.profile) openProfilePicker(true);
  (await api("/api/jobs")).filter((j) => j.status === "running").forEach(watchJob);
})();

// ---------------------------------------------------------------- Próximos vídeos (modelados, DNA, mapa e os vídeos reais para modelar)

const NX = { runs: [], data: null, queue: [], modeled: [], dna: null, kinds: {}, boldness: {} };
const NX_VIA = { origem: "o canal de origem postou", a_seguir: "recomendado depois do seu vídeo",
  mesmo: "quem fez o mesmo vídeo postou", assunto: "busca do assunto" };
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

// Vídeos modelados do perfil em uso (para marcar "Já modelei" em Descobrir e na prévia).
state.modeled = new Map();
async function loadModeledIds() {
  state.modeled = new Map();
  if (!state.profile) return;
  try { (await api(`/api/modeled?profile_id=${state.profile}`)).forEach((m) => m.video_id && state.modeled.set(m.video_id, m.id)); } catch {}
}

async function loadNext(runId = null) {
  if (!state.profile) {
    $("#mc-modeled").innerHTML = `<div class="empty"><b>Escolha o perfil em uso</b>Próximos vídeos é do perfil que você está usando.</div>`;
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
      : `<p class="dim small">Nenhum ainda. Cole o link aqui, ou use o botão <b>Já modelei</b> nas linhas de Descobrir e na prévia de um vídeo.</p>`}`;
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
    <div class="grow"><h3>Achar os próximos vídeos</h3><p id="mc-bold-tip">${esc(BOLD_TIP[b])}</p></div>
    <div class="field"><span>Ousadia</span>
      <div class="seg" id="mc-bold">${Object.keys(BOLD_TIP).map((k) => `<button data-v="${k}" class="${k === b ? "on" : ""}" title="${esc(BOLD_TIP[k])}">${esc(NX.boldness[k] || k)}</button>`).join("")}</div></div>
    <button class="btn primary" id="nx-run" ${state.aiEnabled ? "" : "disabled"} title="Busca o que está viralizando agora no seu nicho (pelos seus parâmetros), escolhe os vídeos reais para você modelar e monta o mapa">
      <svg viewBox="0 0 24 24"><path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4z"/></svg>Achar os próximos <span class="btn-note">· ~US$ 0,05</span></button>`;
  bindSeg($("#mc-bold"), (v) => { try { localStorage.setItem("boldness", v); } catch {} $("#mc-bold-tip").textContent = BOLD_TIP[v]; });
}

const refThumbs = (refs, n = 3) => refs.slice(0, n).map((r) => `<img loading="lazy" src="https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg" alt="" data-vref="${r.video_id}" title="${esc(r.title)} · viralizou ${fmtMult(r.multiplier)} · há ${ageLong(r.age_days)}">`).join("");

function renderNext() {
  const d = NX.data;
  if (!d || d.version < 4) {
    $("#mc-result").innerHTML = `<div class="box"><div class="empty"><b>${d ? "Esta rodada é do jeito antigo" : "Nenhuma rodada ainda"}</b>
      ${d ? "Clique em \"Achar os próximos\": agora o darkbot parte do vídeo que você modelou (o que o canal de origem postou, o que o público assiste em seguida e o que viraliza no assunto)." :
      "Adicione os vídeos que você já modelou, escolha a ousadia e clique em \"Achar os próximos\": o darkbot busca o que está viralizando agora no seu nicho (pelos seus parâmetros) e escolhe os vídeos reais que você deve modelar."}</div></div>`;
    return;
  }
  const col = (st) => {
    const list = d.territories.filter((t) => t.status === st);
    return `<div class="terr-col ${st}"><h4 title="${esc(TERR[st][1])}"><i></i>${TERR[st][0]}</h4>
      ${list.length ? list.map((t) => `<div class="terr-card"><b>${esc(t.name)}<span class="heat ${t.heat}" title="Quanto está em alta">${t.heat === "alta" ? "em alta" : t.heat === "media" ? "morno" : "fraco"}</span></b>
        <p>${esc(t.why)}</p><div class="terr-thumbs">${refThumbs(t.refs, 4)}</div></div>`).join("") : `<div class="terr-empty">Nada aqui agora.</div>`}</div>`;
  };
  $("#mc-result").innerHTML = `
    <div class="nx-strategy"><span>A estratégia agora · ousadia ${esc(NX.boldness[d.boldness] || "")}</span><p>${esc(d.strategy)}</p></div>
    <div class="nx-meta">${d.anchors?.length ? `<span>A partir de: ${d.anchors.map((a) => `<span class="link" data-vref="${a.video_id}">${esc(a.title)}</span>`).join(" · ")}</span>` : ""}
      <span title="Quantos vídeos o darkbot olhou e quantos sobraram depois de cada filtro">${d.funnel ? `${fmt(d.funnel.candidates)} vídeos olhados → ${d.funnel.niche} do nicho (sem o mesmo vídeo) → ${d.funnel.final} viralizando · ` : ""}${fmtDate(d.created_at)} · ${fmtUSD(d.cost_usd)}</span></div>
    <div class="nx-params" title="Só entram vídeos que batem os seus parâmetros (Configurações)">Seus parâmetros: ${esc(d.params || "")}${d.widened ? ` · <b class="warn-txt">nos seus ${esc(String(d.params || "").match(/\d+/)?.[0] || "")} dias veio pouca coisa: ampliei para ${d.days_used} dias</b>` : ""}</div>
    <div class="box" style="margin-bottom:12px"><div class="box-head"><h3>Modele estes, nesta ordem</h3><span class="dim small">vídeos reais viralizando agora no seu nicho</span></div>
    <div class="nx-list">${d.items.map((it, i) => {
      const q = NX.queue.find((x) => x.video_id === it.video_id), md = state.modeled.has(it.video_id);
      return `<div class="nx-card">
        <span class="rank">${i + 1}</span>
        <div class="thumb nx-thumb" data-vref="${it.video_id}" title="Ver a prévia"><img loading="lazy" src="https://i.ytimg.com/vi/${it.video_id}/mqdefault.jpg" alt=""></div>
        <div class="nx-body">
          <div class="otitle" data-vref="${it.video_id}" title="${esc(it.title)}">${esc(it.title)}</div>
          <div class="v-meta"><span class="ch">${esc(it.channel_title || "")}</span>${langTag(it)}
            <span class="tag k-${it.kind}" title="${esc(NX_KIND_TIP[it.kind] || "")}">${esc(NX.kinds[it.kind] || it.kind)}</span>
            ${it.territory ? `<span class="tag terr-tag" title="Território do mapa">${esc(it.territory)}</span>` : ""}
            ${(it.via || []).map((x) => `<span class="tag via" title="De onde veio este vídeo">${esc(NX_VIA[x] || x)}</span>`).join("")}
            ${it.widened ? `<span class="tag fresh" title="Postado antes do período dos seus parâmetros (o período foi ampliado porque veio pouca coisa)">fora do período</span>` : ""}</div>
          <div class="nx-nums">
            <span title="Views por hora desde que foi postado"><b class="vph">${fmt(it.views_hour)}</b> views/hora</span>
            <span title="Total de views"><b>${fmt(it.views)}</b> views</span>
            <span class="mult ${multClass(it.multiplier)}" title="${viralTip(it.multiplier)}">${fmtMult(it.multiplier)}</span>
            <span>postado há ${ageLong(it.age_days ?? (it.age_hours != null ? it.age_hours / 24 : null)) || "?"}</span>
          </div>
          <div class="var-why">${esc(it.why)}</div>
        </div>
        <div class="nx-actions">
          <button class="btn ghost sm" data-vref="${it.video_id}">Prévia</button>
          ${md ? `<span class="tag new">Já modelei</span>` : q ? `<span class="tag neutral">Na sua fila</span>`
            : `<button class="btn primary sm" data-nx-add="${i}" title="Coloca na sua fila (Vou fazer)">+ Vou fazer</button>
               <button class="btn ghost sm" data-modeled="${it.video_id}" title="Você já modelou este vídeo">Já modelei</button>`}
        </div>
      </div>`;
    }).join("")}</div></div>
    ${d.territories.length ? `<div class="box"><div class="box-head"><h3>Mapa de território</h3><span class="dim small">o que está viralizando no nicho, agrupado por assunto</span></div>
      <div class="terr">${col("seu")}${col("fronteira")}${col("saturado")}</div></div>` : ""}`;
}

function renderQueue() {
  $("#mc-queue").innerHTML = `
    <div class="box-head"><h3>Vou fazer</h3><span class="dim small">${NX.queue.length} na fila</span></div>
    <form class="nx-add" id="nx-add"><input class="input" id="nx-add-title" placeholder="Adicionar um vídeo à fila…"><button class="btn sm" type="submit">Adicionar</button></form>
    ${NX.queue.length ? NX.queue.map((x) => `<div class="q-item" data-qid="${x.id}">
      <button class="q-check" data-q-done="${x.id}" title="Fiz! Vai para os vídeos modelados"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg></button>
      <span class="q-title" ${x.video_id ? `data-vref="${x.video_id}" style="cursor:pointer"` : ""} title="${esc(x.note || x.title)}">${esc(x.title)}</span>
      <button class="icon-btn" data-q-del="${x.id}" title="Tirar da fila"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`).join("")
      : `<p class="dim small">Nada na fila. Use "+ Vou fazer" nos vídeos sugeridos.</p>`}`;
}

async function startNext() {
  if (!state.profile) return toast("Escolha o perfil em uso primeiro.", "err");
  try {
    watchJob(await api("/api/next", { method: "POST", body: { profile_id: state.profile, boldness: boldness() } }));
    toast("Buscando o que está viralizando agora no seu nicho… (cerca de 1 minuto)");
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
      await api("/api/queue", { method: "POST", body: { profile_id: state.profile, title: it.title, kind: it.kind, note: it.why, video_id: it.video_id } });
      toast("Na sua fila (Vou fazer).", "ok");
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

// "Já modelei" (linhas de Descobrir e prévia): liga/desliga o vídeo na lista de modelados do perfil em uso.
const modeledBtn = (id) => {
  const on = state.modeled.has(id);
  return `<button class="icon-btn ${on ? "on" : ""}" data-modeled="${id}" title="${on ? "Já modelado (clique para tirar)" : "Já modelei este: entra nos vídeos que modelei (Próximos vídeos)"}">
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
      toast("Tirado dos vídeos que modelei.", "ok");
    } else {
      const r = await api("/api/modeled", { method: "POST", body: { profile_id: state.profile, video: id } });
      state.modeled.set(id, r.id);
      toast("Entrou nos vídeos que modelei (Próximos vídeos).", "ok");
    }
    renderVideos();
    if (!$("#pv").hidden && PV.id && !PV.report) renderPreview();
    if ($("#page-next").classList.contains("active")) loadNext(NX.data?.id);
  } catch (err) { toast(err.message, "err"); }
}, true);

// ---------------------------------------------------------------- Radar do zero (achar nichos com oportunidade fresca)

const RADAR = { runs: [], data: null };
const COMP = { baixa: ["Pouca concorrência", "good"], media: ["Concorrência média", "warn"], alta: ["Muita concorrência", "neutral"] };
const ENTRY = { facil: "Fácil de fazer", medio: "Médio de fazer", dificil: "Difícil de fazer" };

async function openRadar(id = null) {
  $("#pv").hidden = false;
  PV.id = null; PV.report = null;
  $("#pv-body").innerHTML = `<div class="pv-loading">Carregando…</div>`;
  try {
    const d = await api("/api/radar");
    RADAR.runs = d.runs;
    RADAR.data = id ? await api(`/api/radar/${id}`) : d.latest;
  } catch (e) { return toast(e.message, "err"); }
  renderRadar();
}

function renderRadar() {
  const d = RADAR.data;
  const head = `<div class="pv-top"><span class="pv-kicker">Radar do zero</span>
      <button class="icon-btn" id="pv-close" title="Fechar (Esc)"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
    <h2 class="pv-title">Nichos com oportunidade agora</h2>
    <p class="dim small">Para quem está decidindo o nicho (ou usa perfil coringa): o darkbot varre o que está viralizando <b>agora</b>
      entre canais <b>dark</b> de qualquer tema (português, inglês e espanhol), pela régua dos seus parâmetros, e agrupa em nichos.
      Escolha um e crie o perfil para afunilar.</p>`;
  const runBtn = (again) => `<button class="btn ${again ? "" : "primary"} sm" data-radar-run ${state.aiEnabled ? "" : "disabled"}>
    ${again ? "Varrer de novo" : "Varrer agora"} <span class="btn-note">· ~US$ 0,15 · 2 a 4 min</span></button>`;
  if (!d) {
    $("#pv-body").innerHTML = head + `<div class="pv-section">${runBtn(false)}</div>`;
    return;
  }
  const f = d.funnel || {};
  const card = (n, i) => {
    const [cl, cc] = COMP[n.competition];
    return `<div class="radar-n">
      <div class="radar-h"><span class="pais-rank">${i + 1}</span><b>${esc(n.name)}</b>
        ${(n.langs || []).map((l) => flagImg(l)).join("")}
        <span class="tag ${cc}" title="Quantos canais (e de que tamanho) já fazem esse nicho">${cl}</span>
        <span class="tag neutral" title="Quanto trabalho um canal dark novo tem para fazer esse tipo de vídeo">${ENTRY[n.entry]}</span></div>
      <p class="radar-what">${esc(n.what)}</p>
      <div class="radar-nums">
        <span title="Vídeos dark desse nicho viralizando agora"><b>${n.count}</b> vídeos</span>
        <span title="Views por hora típicas (mediana) dos vídeos do nicho"><b class="vph">${fmt(n.vph_median)}</b> views/hora típico</span>
        <span title="Canais diferentes fazendo"><b>${n.channels}</b> canais</span>
        <span title="Canais criados há até 6 meses indo bem = tem espaço para entrar"><b class="${n.new_channels ? "up" : ""}">${n.new_channels}</b> canais novos</span>
      </div>
      <div class="radar-why">${esc(n.why_now)}</div>
      <div class="radar-vids">${n.videos.slice(0, 4).map((v) => `<div class="radar-v" data-vref="${v.video_id}" title="${esc(v.title)} · ${esc(v.channel_title || "")} · ${fmt(v.views_hour)} views/h · postado há ${ageLong(v.age_days)}">
        <img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt=""><span>${fmt(v.views_hour)}/h</span></div>`).join("")}</div>
      <div class="radar-foot">
        <div class="radar-searches" title="Buscas para treinar o perfil nesse nicho (clique para copiar)">${n.searches.map((s) => `<i data-copy="${esc(s)}">${esc(s)}</i>`).join("")}</div>
        <button class="btn primary sm" data-radar-profile="${i}" title="Cria um perfil com esse nicho já preenchido (depois é só treinar ou garimpar nele)">Criar perfil com este nicho</button>
      </div>
    </div>`;
  };
  $("#pv-body").innerHTML = head + `
    <div class="radar-meta dim small">
      ${RADAR.runs.length > 1 ? `<select class="select sm" id="radar-hist">${RADAR.runs.map((r) => `<option value="${r.id}" ${r.id === d.id ? "selected" : ""}>${fmtDate(r.created_at)} · ${r.niches} nichos</option>`).join("")}</select>` : ""}
      <span title="Quantos vídeos foram olhados e quantos sobraram em cada filtro">${fmt(f.found)} vídeos olhados → ${fmt(f.in_rule)} na sua régua → ${f.dark} de canais dark → ${f.pool} agrupados</span>
      <span>${fmtDate(d.created_at)} · ${fmtUSD(d.cost_usd)}</span>
    </div>
    <div class="nx-params">Seus parâmetros: ${esc(d.params || "")}</div>
    ${d.niches.length ? d.niches.map(card).join("") : `<div class="paises-none"><b>Nenhum nicho se formou.</b>Poucos vídeos dark viralizando juntos no mesmo assunto agora.</div>`}
    <div class="mal-foot">${runBtn(true)}</div>`;
}

$("#nb-radar")?.addEventListener("click", () => openRadar());

$("#pv-body").addEventListener("click", async (e) => {
  if (e.target.closest("[data-radar-run]")) {
    if (RADAR.data && !confirm("Varrer de novo gasta uns US$ 0,15 e leva de 2 a 4 minutos. Continuar?")) return;
    try {
      watchJob(await api("/api/radar", { method: "POST" }), (j) => { if (!$("#pv").hidden && !PV.id) openRadar(j.result?.radar_id); });
      toast("Radar do zero rodando… (2 a 4 minutos). Pode fechar o painel: ele abre sozinho quando terminar.");
    } catch (err) { toast(err.message, "err"); }
    return;
  }
  const pb = e.target.closest("[data-radar-profile]");
  if (pb) {
    const n = RADAR.data.niches[+pb.dataset.radarProfile];
    const name = prompt("Nome do perfil:", n.name);
    if (!name) return;
    try {
      await api("/api/profiles", { method: "POST", body: { name, kind: "nicho", niche: n.profile_niche } });
      toast(`Perfil "${name}" criado com o nicho "${n.profile_niche}". Em Perfis: treine ou garimpe nele.`, "ok");
      pb.disabled = true; pb.textContent = "Perfil criado";
      refreshAll();
    } catch (err) { toast(err.message, "err"); }
  }
});
$("#pv-body").addEventListener("change", (e) => {
  if (e.target.id === "radar-hist") openRadar(+e.target.value);
});
