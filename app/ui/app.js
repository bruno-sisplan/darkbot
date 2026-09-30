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

function fillProfileSelects() {
  const opts = `<option value="">Todos os perfis</option>` +
    state.profiles.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  for (const id of ["#v-profile", "#c-profile", "#t-profile"]) {
    const sel = $(id), cur = sel.value;
    sel.innerHTML = opts;
    sel.value = cur;
  }
}

// ---------------------------------------------------------------- descobertas

async function loadVideos() {
  const pid = $("#v-profile").value;
  state.videos = await api(`/api/videos${pid ? `?profile_id=${pid}` : ""}`);
  state.vLimit = 150;
  renderVideos();
}

function filteredVideos() {
  const type = segValue($("#v-type"));
  const maxAge = +$("#v-age").value, maxSubs = +$("#v-subs").value;
  const maxCh = +$("#v-chage").value, minMult = +$("#v-mult").value;
  const q = $("#v-search").value.trim().toLowerCase();
  return state.videos.filter((v) => {
    if (type === "long" && v.is_short) return false;
    if (type === "short" && !v.is_short) return false;
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
    if (v.is_short) tags.push(`<span class="tag short">Short</span>`);
    if (v.channel_age_days != null && v.channel_age_days <= 180) tags.push(`<span class="tag new">Canal novo · ${fmtAge(v.channel_age_days)}</span>`);
    if (v.age_days != null && v.age_days <= 7) tags.push(`<span class="tag fresh">Recente</span>`);
    return `<tr class="clickable" data-id="${v.video_id}" data-short="${v.is_short}">
      <td><div class="thumb ${v.is_short ? "short" : ""}"><img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
        ${v.duration_s != null ? `<span class="dur">${fmtDur(v.duration_s)}</span>` : ""}</div></td>
      <td><div class="v-title" title="${esc(v.title)}">${esc(v.title) || "<span class='dim'>(sem título)</span>"}</div>
        <div class="v-meta"><span class="ch">${esc(v.channel_title || "")}</span>${tags.join("")}</div></td>
      <td class="num"><span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span></td>
      <td class="num">${fmt(v.views)}</td>
      <td class="num">${fmt(v.views_day)}</td>
      <td class="num ${v.growth_day > 0 ? "up" : "dim"}">${v.growth_day != null ? `+${fmt(v.growth_day)}` : "—"}</td>
      <td class="num">${fmt(v.subs)}</td>
      <td class="num">${fmtAge(v.age_days)}</td>
      <td class="num">${v.times_seen}×</td>
    </tr>`;
  }).join("");

  const empty = $("#v-empty");
  if (!state.videos.length) {
    empty.innerHTML = `<b>Nenhuma coleta ainda</b>Vá em <span class="link" data-goto="profiles">Perfis</span>, adicione um perfil treinado e clique em Coletar.`;
    empty.hidden = false;
  } else if (!list.length) {
    empty.innerHTML = `<b>Nada com esses filtros</b>Afrouxe os filtros para ver mais vídeos.`;
    empty.hidden = false;
  } else empty.hidden = true;

  $("#v-more").hidden = list.length <= state.vLimit;
  $("#v-more").textContent = `Mostrar mais (${list.length - shown.length} restantes)`;
  renderKpis(list);
}

function renderKpis(list) {
  const top = [...list].filter((v) => v.multiplier != null).sort((a, b) => b.multiplier - a.multiplier)[0];
  const newCh = new Set(list.filter((v) => v.channel_age_days != null && v.channel_age_days <= 180).map((v) => v.channel_id));
  const shorts = list.filter((v) => v.is_short).length;
  $("#v-kpis").innerHTML = `
    <div class="kpi"><div class="k-label">Vídeos no filtro</div><div class="k-value">${list.length}</div>
      <div class="k-sub">${shorts} shorts · ${list.length - shorts} longos</div></div>
    <div class="kpi"><div class="k-label">Multiplicador mediano</div><div class="k-value">${fmtMult(median(list.map((v) => v.multiplier)))}</div>
      <div class="k-sub">views ÷ inscritos</div></div>
    <div class="kpi"><div class="k-label">Canais novos (≤ 6 meses)</div><div class="k-value">${newCh.size}</div>
      <div class="k-sub">sinal de nicho com espaço</div></div>
    <div class="kpi hot"><div class="k-label">Maior outlier</div><div class="k-value">${top ? fmtMult(top.multiplier) : "—"}</div>
      <div class="k-sub" title="${esc(top?.title)}">${top ? esc(top.title) : "—"}</div></div>`;
}

$("#v-table tbody").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) openYT(tr.dataset.short === "1" ? `shorts/${tr.dataset.id}` : `watch?v=${tr.dataset.id}`);
});
$("#v-more").addEventListener("click", () => { state.vLimit += 150; renderVideos(); });
bindSeg($("#v-type"), renderVideos);
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
        <div class="v-meta">${c.handle ? esc(c.handle) : ""}${c.channel_age_days != null && c.channel_age_days <= 180 ? `<span class="tag new">Novo</span>` : ""}${c.shorts ? `<span class="tag neutral">${c.shorts} shorts</span>` : ""}</div></div></div></td>
      <td class="num"><span class="mult ${multClass(c.best_multiplier)}">${fmtMult(c.best_multiplier)}</span></td>
      <td class="num">${fmt(c.avg_views_day)}</td>
      <td class="num">${fmt(c.subs)}</td>
      <td class="num">${fmt(c.channel_videos)}</td>
      <td class="num">${fmtAge(c.channel_age_days)}</td>
      <td class="num">${c.times_seen}×</td>
      <td>${c.top_video ? `<span class="link v-title" data-vid="${c.top_video.video_id}" title="${esc(c.top_video.title)}">${esc(c.top_video.title)}</span>` : "—"}</td>
    </tr>`).join("");

  const empty = $("#c-empty");
  empty.hidden = list.length > 0;
  empty.innerHTML = state.channels.length ? "<b>Nada com esses filtros</b>" : "<b>Sem canais ainda</b>Faça uma coleta com a chave da API configurada.";
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
    type: segValue($("#t-type")), max_age: $("#t-age").value, outlier: segValue($("#t-outlier")),
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
  const tipPct = (w) => `${w.pct_top}% dos outliers · ${w.pct_rest}% dos demais`;
  const nTerm = (t) => t.replace(/#/g, "N");

  body.innerHTML = `
    <div class="kpis">
      <div class="kpi hot"><div class="k-label">Outliers analisados</div><div class="k-value">${d.n_top}</div>
        <div class="k-sub">de ${d.total} vídeos · corte ${fmtMult(d.cut)}</div></div>
      <div class="kpi"><div class="k-label">Multiplicador mediano</div><div class="k-value">${fmtMult(d.median_mult_top)}</div>
        <div class="k-sub">vs ${fmtMult(d.median_mult_rest)} nos demais</div></div>
      <div class="kpi"><div class="k-label">Caracteres no título</div><div class="k-value">${Math.round(L.chars_top)}</div>
        <div class="k-sub">vs ${Math.round(L.chars_rest)} nos demais</div></div>
      <div class="kpi"><div class="k-label">Palavras por título</div><div class="k-value">${Math.round(L.words_top)}</div>
        <div class="k-sub">vs ${Math.round(L.words_rest)} nos demais</div></div>
    </div>

    <div class="grid2">
      <div class="box">
        <div class="box-head"><h3>Formatos</h3>
          <div class="legend"><span><i class="a"></i>outliers</span><span><i class="b"></i>demais</span></div></div>
        ${d.features.map((f) => {
          const diff = f.pct_top - f.pct_rest;
          return `<div class="frow">
            <div class="fl">${esc(f.label)}<small>mult. ${fmtMult(f.mult_with)} com · ${fmtMult(f.mult_without)} sem</small></div>
            <div class="dbar">
              <div class="a"><b style="width:${(f.pct_top / featMax) * 100}%"></b>${pct(f.pct_top)}</div>
              <div class="b"><b style="width:${(f.pct_rest / featMax) * 100}%"></b>${pct(f.pct_rest)}</div>
            </div>
            <div class="delta ${diff > 0 ? "pos" : "neg"}">${diff > 0 ? "+" : ""}${Math.round(diff)} p.p.</div>
          </div>`;
        }).join("")}
      </div>

      <div class="stack">
        <div class="box">
          <div class="box-head"><h3>Palavras que puxam</h3><div class="legend">% dos outliers que usam</div></div>
          <div class="terms">${terms(d.words, (t) => t, "pct", tipPct)}</div>
        </div>
        <div class="box">
          <div class="box-head"><h3>Pares de palavras</h3></div>
          <div class="terms">${terms(d.bigrams, nTerm, "pct", tipPct)}</div>
        </div>
        <div class="box">
          <div class="box-head"><h3>Aberturas mais usadas</h3><div class="legend">primeiras 2 palavras</div></div>
          <div class="terms">${terms(d.openings, (t) => `${nTerm(t)}…`, "count", (o) => `multiplicador mediano ${fmtMult(o.mult)}`)}</div>
        </div>
      </div>
    </div>

    <div class="box">
      <div class="box-head"><h3>Títulos dos outliers</h3><div class="legend">clique para abrir</div></div>
      <div class="olist">${d.examples.map((v) => `
        <div class="orow" data-id="${v.video_id}" data-short="${v.is_short}">
          <img loading="lazy" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="">
          <span class="otitle" title="${esc(v.title)}">${esc(v.title)}</span>
          <span class="ometa">${esc(v.channel_title || "")} · ${fmt(v.views)} views</span>
          <span class="mult ${multClass(v.multiplier)}">${fmtMult(v.multiplier)}</span>
        </div>`).join("")}</div>
    </div>`;
}

$("#t-body").addEventListener("click", (e) => {
  const r = e.target.closest(".orow");
  if (r) openYT(r.dataset.short === "1" ? `shorts/${r.dataset.id}` : `watch?v=${r.dataset.id}`);
});
bindSeg($("#t-type"), loadTitles);
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
            <div class="card-sub">${p.kind === "coringa" ? "Coringa" : "Nicho"}${p.niche ? ` · ${esc(p.niche)}` : ""}</div>
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
          <label class="scrolls" title="Quantas vezes rolar a home (mais = mais vídeos)">Scrolls <input class="input" type="number" min="1" max="80" value="15" data-scrolls></label>
          <label class="check"><input type="checkbox" data-show> ver navegador</label>
          <span class="spacer"></span>
        </div>
        <div class="card-actions">
          <button class="btn primary sm" data-act="collect">Coletar agora</button>
          <button class="btn sm" data-act="open" title="Abre o Chrome nesse perfil para logar ou treinar">Abrir p/ login</button>
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
    <td class="num">${r.videos_found || 0}</td><td class="dim small">${esc(r.error || "")}</td></tr>`).join("")
    : `<tr><td colspan="5" class="dim">Nenhuma coleta ainda.</td></tr>`;
}

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
    } else if (btn.dataset.act === "open") {
      await api(`/api/profiles/${pid}/open`, { method: "POST" });
      toast("Chrome aberto. Logue/treine e feche a janela antes de coletar.");
      setTimeout(loadProfiles, 1500);
    } else if (btn.dataset.act === "delete") {
      if (!confirm(`Excluir o perfil "${p.name}"? Os vídeos coletados continuam no banco.`)) return;
      await api(`/api/profiles/${pid}`, { method: "DELETE" });
      toast("Perfil excluído.");
      loadProfiles();
    }
  } catch (err) { toast(err.message, "err"); }
});

// ---------------------------------------------------------------- modal: novo perfil

let chromeChoice = null;

async function openModal(keepFields = false) {
  $("#modal").hidden = false;
  if (keepFields !== true) {
    $("#m-name").value = "";
    $("#m-niche").value = "";
  }
  chromeChoice = null;
  const list = $("#m-chrome");
  list.innerHTML = `<div class="muted small">Procurando perfis do Chrome…</div>`;
  try {
    const d = await api("/api/chrome-profiles");
    if (!d.chrome_found) {
      list.innerHTML = `<div class="alert warn">Google Chrome não encontrado neste PC.</div>`;
      return;
    }
    list.innerHTML = d.profiles.map((p) => `
      <div class="chrome-opt" data-folder="${esc(p.folder)}" data-name="${esc(p.name)}">
        <div class="avatar">${esc(p.name[0] || "?").toUpperCase()}</div>
        <div><b>${esc(p.name)}</b><small>${esc(p.email || "sem conta Google")} · ${esc(p.folder)}</small></div>
      </div>`).join("") +
      (d.chrome_running ? `<div class="alert warn row-alert"><span>O Chrome está aberto. Ele precisa estar fechado para copiar a sessão.</span>
        <button class="btn sm" id="m-close-chrome">Fechar o Chrome</button></div>` : "");
  } catch (e) { list.innerHTML = `<div class="alert warn">${esc(e.message)}</div>`; }
}
const closeModal = () => { $("#modal").hidden = true; };

$("#btn-new-profile").addEventListener("click", () => openModal());
$$("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
bindSeg($("#m-mode"), (v) => { $("#m-import").hidden = v !== "import"; $("#m-new").hidden = v !== "new"; });
bindSeg($("#m-kind"), () => {});
$("#m-chrome").addEventListener("click", async (e) => {
  const closeBtn = e.target.closest("#m-close-chrome");
  if (closeBtn) {
    closeBtn.disabled = true;
    closeBtn.textContent = "Fechando…";
    try {
      await api("/api/chrome/close", { method: "POST" });
      const keep = chromeChoice;
      await openModal(true);
      if (keep) $(`.chrome-opt[data-folder="${CSS.escape(keep)}"]`)?.click();
      toast("Chrome fechado. Ao reabrir, ele restaura suas abas.", "ok");
    } catch (err) { toast(err.message, "err"); closeBtn.disabled = false; closeBtn.textContent = "Fechar o Chrome"; }
    return;
  }
  const opt = e.target.closest(".chrome-opt");
  if (!opt) return;
  $$(".chrome-opt").forEach((x) => x.classList.toggle("on", x === opt));
  chromeChoice = opt.dataset.folder;
  if (!$("#m-name").value) $("#m-name").value = opt.dataset.name;
});

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

// ---------------------------------------------------------------- configurações

async function loadSettings() {
  const s = await api("/api/settings");
  const st = $("#s-status");
  st.className = `hint ${s.youtube_api_key_set ? "ok" : ""}`;
  st.textContent = s.youtube_api_key_set
    ? `Chave ${s.youtube_api_key_source} ativa (${s.youtube_api_key_hint}).`
    : "Nenhuma chave configurada (nem embutida em config.py).";
}
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
    : `<span class="dim">${Math.round(j.progress * 100)}%</span>`;
  el.innerHTML = `<div class="job-top"><span>${esc(j.label)}</span>${right}</div>
    <div class="job-msg">${esc(msg)}</div><div class="bar"><i style="width:${j.progress * 100}%"></i></div>`;
  return el;
}

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
    else setTimeout(() => el.remove(), 4000);
    refreshAll();
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
  fillProfileSelects();
  await Promise.all([loadVideos(), loadOverview()]);
  if ($("#page-profiles").classList.contains("active")) loadProfiles();
  if ($("#page-channels").classList.contains("active")) loadChannels();
  if ($("#page-titles").classList.contains("active")) loadTitles();
}

(async () => {
  await refreshAll();
  (await api("/api/jobs")).filter((j) => j.status === "running").forEach(watchJob);
})();
