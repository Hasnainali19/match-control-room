/* Match Control Room – vanilla JS client. Consumes the SSE stream from /api/stream. */
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const AGENTS = ["ingest", "stats", "tactics", "narrator", "control", "root_cause", "pundit.tactician", "pundit.analyst",
  "pundit.expro", "pundit.superfan", "referee", "personalizer", "producer"];
const FLOW = ["ingest", "stats", "tactics", "narrator", "control", "root_cause", "pundits", "referee", "personalizer", "producer"];
const S = {
  cfg: null, meta: null, es: null, persona: "casual", metric: "possession", chartTeam: "HAR",
  charts: {}, signals: [], goals: [], spans: Object.fromEntries(AGENTS.map((a) => [a, []])), counts: {},
  ticker: [], voted: null, debug: {}, session: null, opsDirty: false, chartDirty: false, ltTimer: null, alertTimer: null,
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const club = (c) => S.cfg?.clubs[c]?.name ?? c;
const color = (c) => S.cfg?.clubs[c]?.color ?? "#fff";

async function init() {
  S.cfg = await (await fetch("/api/config")).json();
  $("seed").value = S.cfg.default_seed;
  for (const [k, v] of Object.entries(S.cfg.languages)) {
    const off = S.cfg.offline_languages.includes(k);
    $("lang").add(new Option(`${v}${off ? "" : " (AI model)"}`, k));
  }
  for (const [k, v] of Object.entries(S.cfg.clubs)) $("club").add(new Option(v.name, k));
  for (const [k, v] of Object.entries(S.cfg.pundits)) $("pundit").add(new Option(`${v.name} – ${v.title}`, k));
  $("langHint").textContent = S.cfg.llm_online ? `AI provider: ${S.cfg.llm_provider}. Any language works.` :
    "Offline mode: EN/ES/FR/DE/PT templates. Other languages need an AI provider (Azure OpenAI or GitHub Models).";
  await loadMeta(S.cfg.default_seed);
  buildMetricTabs(); buildLanes(); buildFlow(); renderPundits([], null); drawChart();
  bindUI();
  const q = new URLSearchParams(location.search);
  if (q.get("persona")) setPersona(q.get("persona"));
  for (const k of ["club", "player", "lang", "pundit"]) if (q.get(k)) $(k).value = q.get(k);
  if (q.get("chaos")) { $("fault").value = Math.round(+q.get("chaos") * 100); $("faultOut").textContent = $("fault").value + "%"; $("chaosToggle").checked = +q.get("chaos") > 0; }
  if (q.get("autoplay")) start(q.get("autoplay") === "demo", +(q.get("speed") || 0) || undefined);
  else if (!localStorage.getItem("mcr_seen") || q.get("welcome")) $("welcome").hidden = false;
}

async function loadMeta(seed) {
  S.meta = await (await fetch(`/api/meta?seed=${seed}`)).json();
  $("homeName").textContent = S.meta.clubs.HAR; $("awayName").textContent = S.meta.clubs.MIL;
  $("homeChip").style.background = S.meta.colors.HAR; $("awayChip").style.background = S.meta.colors.MIL;
  $("lgHome").innerHTML = `<i class="lg" style="background:${S.meta.colors.HAR}"></i>${S.meta.clubs.HAR}`;
  $("lgAway").innerHTML = `<i class="lg" style="background:${S.meta.colors.MIL}"></i>${S.meta.clubs.MIL}`;
  $("dirHome").textContent = `${S.meta.shorts.HAR} attack →`;
  const sel = $("player"); sel.length = 1;
  for (const t of ["HAR", "MIL"]) for (const p of S.meta.players[t]) sel.add(new Option(`${p.name} · ${p.role} · ${S.meta.shorts[t]}`, p.id));
  const seg = $("teamSeg"); seg.innerHTML = "";
  for (const t of ["HAR", "MIL"]) {
    const b = document.createElement("button"); b.textContent = S.meta.shorts[t]; b.dataset.team = t;
    b.className = t === S.chartTeam ? "on" : ""; b.onclick = () => { S.chartTeam = t; [...seg.children].forEach((c) => c.classList.toggle("on", c === b)); drawChart(); };
    seg.appendChild(b);
  }
}

function bindUI() {
  document.querySelectorAll("[data-persona]").forEach((b) => (b.onclick = () => { setPersona(b.dataset.persona); if (S.es) restart(); }));
  $("demoBtn").onclick = () => start(true); $("liveBtn").onclick = () => start(false);
  $("wDemo").onclick = () => { closeWelcome(); start(true); }; $("wSkip").onclick = closeWelcome;
  $("dbgBtn").onclick = toggleDebugger; $("dbgClose").onclick = toggleDebugger;
  $("helpBtn").onclick = showShortcuts;
  document.addEventListener("keydown", onKey);
  $("settingsBtn").onclick = openDrawer; $("closeDrawer").onclick = closeDrawer; $("scrim").onclick = closeDrawer;
  $("speed").oninput = () => ($("speedOut").textContent = $("speed").value + "×");
  $("fault").oninput = () => { $("faultOut").textContent = $("fault").value + "%"; $("chaosToggle").checked = +$("fault").value > 0; };
  $("persona").onchange = () => setPersona($("persona").value);
  $("chaosToggle").onchange = () => { $("fault").value = $("chaosToggle").checked ? 30 : 0; $("faultOut").textContent = $("fault").value + "%"; if (S.es) restart(); };
  $("applyBtn").onclick = async () => { closeDrawer(); await loadMeta(+$("seed").value || S.cfg.default_seed); start(S.lastDemo ?? true); };
  window.addEventListener("resize", () => drawChart());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}
function setPersona(p) {
  S.persona = p; $("persona").value = p; document.body.className = p;
  document.querySelectorAll("[data-persona]").forEach((b) => b.classList.toggle("on", b.dataset.persona === p));
  drawChart();
}
function closeWelcome() { $("welcome").hidden = true; localStorage.setItem("mcr_seen", "1"); }
function toast(html, ms = 3500) { const t = $("toast"); t.innerHTML = html; t.hidden = false; clearTimeout(S.toastT); S.toastT = setTimeout(() => (t.hidden = true), ms); }
function showShortcuts() {
  toast(`<b>Keyboard shortcuts</b><table>${[["D", "Start the demo"], ["L", "Live replay"], ["A", "Switch Casual / Analyst"], ["S", "Settings"],
    ["X", "Toggle chaos (failure injection)"], ["B", "Debugger panel"], ["?", "This help"], ["Esc", "Close panels"]]
    .map(([k, v]) => `<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`).join("")}</table>`, 6000);
}
function onKey(e) {
  if (e.target.matches("input,select,textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "escape") { closeWelcome(); $("dbgPanel").hidden = true; $("toast").hidden = true; return; }
  if (!$("welcome").hidden) return;
  const act = { d: () => start(true), l: () => start(false), a: () => { setPersona(S.persona === "casual" ? "analyst" : "casual"); if (S.es) restart(); },
    s: openDrawer, b: toggleDebugger, "?": showShortcuts, x: () => { $("chaosToggle").checked = !$("chaosToggle").checked; $("chaosToggle").onchange(); toast($("chaosToggle").checked ? "Chaos on: 30% of agent calls will fail. Watch them recover!" : "Chaos off"); } }[k];
  if (act) { e.preventDefault(); act(); }
}
function openDrawer() { $("drawer").classList.add("open"); $("scrim").hidden = false; }
function closeDrawer() { $("drawer").classList.remove("open"); $("scrim").hidden = true; }
function restart() { start(S.lastDemo ?? false); }

function reset() {
  S.charts = {}; S.signals = []; S.goals = []; S.ticker = []; S.counts = {};
  for (const a of AGENTS) S.spans[a] = [];
  $("trail").innerHTML = ""; $("laneLayer").innerHTML = ""; $("incidents").innerHTML = ""; $("tickerInner").innerHTML = "";
  $("homeScore").textContent = "0"; $("awayScore").textContent = "0"; $("clock").textContent = "00:00";
  $("lowerThird").hidden = true; $("alert").hidden = true; $("focusChip").hidden = true;
  $("whys").innerHTML = '<li class="empty">Waiting for the control charts to flag a momentum swing…</li>'; $("countermeasure").hidden = true;
  renderPundits([], null); $("panelTrigger").textContent = "Waiting for a goal or momentum swing…";
  S.debug = {}; renderDebugger();
  document.querySelectorAll("#metricTabs button").forEach((b) => b.classList.remove("flag"));
  drawChart(); renderOps();
}

function start(demo, speedOverride) {
  if (S.es) S.es.close();
  reset(); S.lastDemo = demo;
  const fault = +$("fault").value / 100;
  const q = new URLSearchParams({ seed: $("seed").value || S.cfg.default_seed, persona: S.persona, club: $("club").value,
    player: $("player").value, lang: $("lang").value, pundit: $("pundit").value, speed: speedOverride || $("speed").value,
    fault_rate: fault, demo: demo ? "true" : "false", start_min: new URLSearchParams(location.search).get("start") || 0 });
  S.es = new EventSource("/api/stream?" + q);
  $("liveDot").classList.add("on"); $("demoBtn").classList.remove("pulse"); closeWelcome();
  $("phaseLbl").innerHTML = '<span class="spinner"></span>Connecting to the match feed…';
  S.connecting = demo ? "★ Demo: jumping to the key moments" : "▶ Live replay";
  const on = (k, f) => S.es.addEventListener(k, (ev) => f(JSON.parse(ev.data)));
  on("tick", onTick); on("chart", onChart); on("signal", onSignal); on("alert", onAlert); on("lower_third", onLowerThird);
  on("ticker", onTicker); on("whys", onWhys); on("panel", onPanel); on("trace", onTrace); on("focus", onFocus);
  on("phase", (d) => { $("phaseLbl").textContent = d.phase === "half_time" ? "SECOND HALF" : d.phase.replace("_", " ").toUpperCase(); });
  on("session", (d) => { S.highlights = d.highlights; S.session = d.session; });
  on("debug", onDebug);
  on("end", (d) => { $("liveDot").classList.remove("on"); $("phaseLbl").textContent = `Full time! ${d.signals} momentum signals · ${d.errors} agent faults absorbed · press ★ Demo to watch again`;
    $("demoBtn").classList.add("pulse"); S.es.close(); S.es = null; });
  S.es.onerror = () => { $("liveDot").classList.remove("on"); };
}

/* ---------------- pitch ---------------- */
function svg(tag, attrs, parent = $("trail")) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  parent.appendChild(el); return el;
}
function onTick(d) {
  if (S.connecting) { $("phaseLbl").textContent = S.connecting; S.connecting = null; }
  $("clock").textContent = d.clock;
  setScore(d.score);
  const ph = d.possession_pct?.HAR; if (ph != null) $("possHome").style.width = ph + "%";
  if (d.x == null) return;
  const bx = d.end_x ?? d.x, by = d.end_y ?? d.y;
  for (const id of ["ball", "ballGlow"]) { $(id).setAttribute("cx", bx); $(id).setAttribute("cy", by); }
  const c = color(d.team);
  if (d.type === "pass") {
    const l = svg("line", { x1: d.x, y1: d.y, x2: d.end_x, y2: d.end_y, class: "trail-pass", stroke: c, "stroke-dasharray": d.outcome === "complete" ? "" : "1 .8", "marker-end": "url(#arrow)" });
    setTimeout(() => l.remove(), 4000);
  } else if (d.type === "shot") {
    const l = svg("line", { x1: d.x, y1: d.y, x2: d.end_x, y2: d.end_y, class: "trail-shot" }); setTimeout(() => l.remove(), 5000);
  } else if (d.type === "pressure" || d.type === "tackle") {
    const r = svg("circle", { cx: d.x, cy: d.y, r: 1, class: "ring", stroke: c }); setTimeout(() => r.remove(), 1700);
  }
  if ($("player").value && [d.player, d.target].includes($("player").value)) {
    const r = svg("circle", { cx: d.x, cy: d.y, r: 1, class: "focus-ring" }); setTimeout(() => r.remove(), 2100);
  }
  if (d.tags?.includes("goal")) S.goals.push({ t: d.t, team: d.team });
  while ($("trail").childNodes.length > 40) $("trail").firstChild.remove();
}
function setScore(s) {
  for (const [t, id] of [["HAR", "homeScore"], ["MIL", "awayScore"]]) {
    const v = String(s?.[t] ?? 0);
    if ($(id).textContent !== v) { $(id).textContent = v; $(id).classList.remove("bump"); void $(id).offsetWidth; $(id).classList.add("bump"); }
  }
}
function laneRect(team, lane) {
  // lane from the perspective of `team` (home attacks +x, its left flank is low y)
  if (lane === "C") return [22.7, 22.6];
  const low = team === "HAR" ? lane === "L" : lane === "R";
  return low ? [0, 22.7] : [45.3, 22.7];
}

/* ---------------- overlays ---------------- */
function onLowerThird(d) {
  const lt = $("lowerThird");
  const goal = d.tags?.includes("goal");
  lt.className = "lower-third" + (goal ? " goal" : "") + (d.highlight ? " hl" : "");
  $("ltTag").textContent = goal ? "GOAL" : d.highlight === "focus" ? "FOCUS" : d.kind === "narration" ? "LIVE" : d.kind.toUpperCase();
  $("ltText").textContent = d.text || "";
  const m = d.metrics || {};
  const bits = [];
  if (m.shot_speed_kmh) bits.push(`Shot ${m.shot_speed_kmh} km/h`); if (m.xg != null) bits.push(`xG ${m.xg}`);
  if (m.player_speed_kmh) bits.push(`${m.player_speed_kmh} km/h`); if (m.distance_m && S.persona === "analyst") bits.push(`${m.distance_m} m`);
  if (m.difficulty != null && S.persona === "analyst") bits.push(`difficulty ${m.difficulty}`);
  if (S.persona === "analyst" && d.tactics) bits.push(`${d.tactics.phase} · chaos ${d.tactics.chaos_index}`);
  if (d.text_source === "llm") bits.push("✦ AI");
  $("ltSub").textContent = [d.clock, ...bits].join("  ·  ");
  lt.hidden = false; lt.style.animation = "none"; void lt.offsetWidth; lt.style.animation = "";
  clearTimeout(S.ltTimer); S.ltTimer = setTimeout(() => (lt.hidden = true), goal ? 7000 : 4500);
}
function onAlert(d) {
  $("alertTitle").textContent = d.title || "Momentum shift";
  $("alertSub").textContent = d.subtitle || "";
  const a = $("alert"); a.hidden = false; a.style.animation = "none"; void a.offsetWidth; a.style.animation = "";
  clearTimeout(S.alertTimer); S.alertTimer = setTimeout(() => (a.hidden = true), 5000);
}
function onTicker(d) {
  if (!d.text) return;
  S.ticker.unshift(`<span><b>${esc(d.clock)}</b> ${esc(d.text)}</span>`); S.ticker.length = Math.min(S.ticker.length, 8);
  $("tickerInner").innerHTML = S.ticker.join("");
}
function onFocus(d) {
  if (!d) return;
  const f = $("focusChip"); f.hidden = false;
  const fat = d.early_kmh && d.recent_kmh ? Math.round(100 * (d.recent_kmh - d.early_kmh) / d.early_kmh) : null;
  f.innerHTML = `<b>◎ ${esc(d.name)}</b> · ${esc(d.role)}<br>${d.touches} touches · ${d.pass_acc ?? "–"}% passing<br>` +
    `${d.dist_m} m carried · top ${d.top_kmh} km/h` + (fat != null ? `<br>speed vs early: <b>${fat > 0 ? "+" : ""}${fat}%</b>` : "") +
    `<br>pressed ${d.pressed} · lost ${d.lost}`;
}
function onWhys(d) {
  const a = d.analysis;
  $("whysMeta").textContent = `${d.clock} · ${club(a.team_in_control)} in control`;
  $("whys").innerHTML = a.whys.map((w, i) => `<li style="animation-delay:${i * 0.25}s"><div class="q">${esc(w.q)}</div><div class="a">${esc(w.a)}</div></li>`).join("");
  const cm = $("countermeasure");
  if (a.countermeasure) { cm.hidden = false; cm.innerHTML = `<b>Countermeasure:</b> ${esc(a.countermeasure)}`; } else cm.hidden = true;
  $("laneLayer").innerHTML = "";
  if (a.team_under_stress) {
    const [y, h] = laneRect(a.team_under_stress, a.lane);
    svg("rect", { x: 0, y, width: 105, height: h, class: "lane-hi" }, $("laneLayer"));
    setTimeout(() => ($("laneLayer").innerHTML = ""), 12000);
  }
}
function renderPundits(takes, featured) {
  const list = takes.length ? takes : Object.entries(S.cfg?.pundits || {}).map(([k, v]) => ({ pundit: k, ...v, text: `<span class="empty-hint">${v.style}. Speaks up on goals and momentum swings.</span>`, verdict: null, raw: true }));
  $("pundits").innerHTML = list.map((t) => {
    let text = t.raw ? t.text : esc(t.text);
    for (const c of t.checks || []) if (c.status === "corrected") text = text.replace(esc(String(c.true)), `<del>${esc(c.shown)}</del> <ins>${esc(String(c.true))}</ins>`);
    const badge = t.verdict ? `<span class="badge ${t.verdict}" title="${esc((t.checks || []).map((c) => `${c.key}: ${c.status}`).join("\n"))}">${{ verified: "✓ VERIFIED", corrected: "✎ CORRECTED", rejected: "✕ REJECTED", flagged: "⚠ UNBACKED", unchecked: "… UNCHECKED" }[t.verdict]}</span>` : "";
    return `<div class="pundit ${t.pundit === featured ? "featured" : ""} ${takes.length ? "new" : ""}" data-k="${t.pundit}">
      <div class="avatar">${esc(t.initials)}</div>
      <div><div><span class="p-name">${esc(t.name)}</span><span class="p-title">${esc(t.title)}${t.pundit === featured ? " · ON AIR" : ""}${t.source === "llm" ? " · ✦ AI" : ""}</span></div><div class="p-text">${text}</div></div>
      <div class="p-side">${badge}<button class="vote ${S.voted === t.pundit ? "on" : ""}" data-v="${t.pundit}">♥ ${S.voted === t.pundit ? "Voted" : "Vote"}</button></div></div>`;
  }).join("");
  document.querySelectorAll(".vote").forEach((b) => (b.onclick = async () => {
    S.voted = b.dataset.v;
    await fetch("/api/vote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pundit: S.voted }) });
    document.querySelectorAll(".vote").forEach((x) => { x.classList.toggle("on", x.dataset.v === S.voted); x.textContent = x.dataset.v === S.voted ? "♥ Voted" : "♥ Vote"; });
  }));
}
function onPanel(d) {
  $("panelTrigger").textContent = `${d.clock} · ${d.trigger.kind === "goal" ? "Goal" : "Momentum swing"} · ${club(d.trigger.team)}`;
  renderPundits(d.takes, d.featured);
}

/* ---------------- control chart ---------------- */
function buildMetricTabs() {
  const box = $("metricTabs"); box.innerHTML = "";
  for (const [k, v] of Object.entries(S.cfg.metrics)) {
    const b = document.createElement("button"); b.textContent = v.label; b.dataset.m = k; b.className = k === S.metric ? "on" : "";
    b.onclick = () => { S.metric = k; [...box.children].forEach((c) => c.classList.toggle("on", c === b)); drawChart(); };
    box.appendChild(b);
  }
}
function onChart(d) {
  for (const p of d.points) ((S.charts[p.team] ??= {})[p.metric] ??= []).push(p);
  scheduleChart();
}
function onSignal(s) {
  S.signals.push(s);
  const b = document.querySelector(`#metricTabs button[data-m="${s.metric}"]`); if (b) b.classList.add("flag");
  scheduleChart();
}
function scheduleChart() { if (!S.chartDirty) { S.chartDirty = true; requestAnimationFrame(() => { S.chartDirty = false; drawChart(); }); } }
function drawChart() {
  const cv = $("chart"); const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 600, H = 230; cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
  const g = cv.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, W, H);
  const P = { l: 42, r: 12, t: 12, b: 24 }; const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const casual = S.persona === "casual";
  let series = [], lo = Infinity, hi = -Infinity;
  if (casual) {
    for (const t of ["HAR", "MIL"]) series.push({ team: t, pts: S.charts[t]?.momentum || [] });
    lo = -3; hi = 3;
  } else {
    const pts = S.charts[S.chartTeam]?.[S.metric] || [];
    series.push({ team: S.chartTeam, pts });
    for (const p of pts) for (const v of [p.x, p.ucl, p.lcl, p.ewma]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (!isFinite(lo)) { lo = 0; hi = 1; } const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
  }
  const X = (m) => P.l + (m / 90) * iw, Y = (v) => P.t + ih - ((v - lo) / (hi - lo)) * ih;
  g.font = "11px Inter, system-ui"; g.fillStyle = "#9d97c7"; g.strokeStyle = "#2c2560"; g.lineWidth = 1;
  for (let m = 0; m <= 90; m += 15) { g.beginPath(); g.moveTo(X(m), P.t); g.lineTo(X(m), P.t + ih); g.stroke(); g.fillText(m + "'", X(m) - 6, H - 6); }
  for (let i = 0; i <= 4; i++) { const v = lo + (i / 4) * (hi - lo); g.fillText(casual ? v.toFixed(1) + "σ" : (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(0)), 4, Y(v) + 4); }
  for (const gl of S.goals) { g.strokeStyle = "#ffb020"; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(X(gl.t / 60), P.t); g.lineTo(X(gl.t / 60), P.t + ih); g.stroke(); g.setLineDash([]); g.fillStyle = color(gl.team); g.beginPath(); g.arc(X(gl.t / 60), P.t + 5, 4, 0, 7); g.fill(); }
  if (casual) {
    g.fillStyle = "rgba(0,224,198,.06)"; g.fillRect(P.l, Y(1.5), iw, Y(-1.5) - Y(1.5));
    g.strokeStyle = "#8a83c0"; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(P.l, Y(0)); g.lineTo(P.l + iw, Y(0)); g.stroke(); g.setLineDash([]);
    for (const s of series) {
      g.strokeStyle = color(s.team); g.lineWidth = 2.5; g.beginPath();
      s.pts.forEach((p, i) => (i ? g.lineTo(X(p.minute), Y(p.x)) : g.moveTo(X(p.minute), Y(p.x)))); g.stroke();
    }
    for (const sg of S.signals.filter((x) => x.swing)) { g.fillStyle = color(sg.momentum_to); diamond(g, X(sg.t / 60), P.t + ih - 6, 5); }
    if (!series.some((s) => s.pts.length)) emptyChart(g, W, H);
    return;
  }
  const pts = series[0].pts.filter((p) => p.x != null);
  if (!pts.length) return emptyChart(g, W, H);
  const step = (key, col, dash) => { g.strokeStyle = col; g.setLineDash(dash); g.lineWidth = 1.4; g.beginPath(); let st = false;
    for (const p of pts) { if (p[key] == null) continue; const x = X(p.minute), y = Y(p[key]); if (!st) { g.moveTo(x, y); st = true; } else g.lineTo(x, y); } g.stroke(); g.setLineDash([]); };
  step("ucl", "#ff4d5e", [5, 4]); step("lcl", "#ff4d5e", [5, 4]); step("cl", "#8a83c0", [2, 3]);
  step("ewma", "#00e0c6", []);
  g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 1; g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.minute), Y(p.x)) : g.moveTo(X(p.minute), Y(p.x)))); g.stroke();
  for (const p of pts) { g.fillStyle = p.z != null && Math.abs(p.z) > 2 ? "#ffb020" : "#fff"; g.beginPath(); g.arc(X(p.minute), Y(p.x), 2.6, 0, 7); g.fill(); }
  for (const sg of S.signals.filter((x) => x.metric === S.metric && x.team === S.chartTeam)) {
    g.fillStyle = "#ff2d87"; diamond(g, X(sg.t / 60), Y(sg.x), 6);
    g.fillStyle = "#fff"; g.fillText(sg.rule, X(sg.t / 60) + 7, Y(sg.x) - 6);
  }
  const unit = S.cfg.metrics[S.metric].unit; g.fillStyle = "#cfc8ff"; g.fillText(`${S.cfg.metrics[S.metric].label}${unit ? " (" + unit + ")" : ""} · ${club(S.chartTeam)}`, P.l + 6, P.t + 12);
}
function emptyChart(g, W, H) {
  g.fillStyle = "rgba(11,8,32,.55)"; g.fillRect(0, 0, W, H);
  g.fillStyle = "#dcd7ff"; g.font = "600 14px Inter, system-ui"; g.textAlign = "center";
  g.fillText(S.es ? "Learning each team's normal rhythm…" : "Press ★ Demo to see momentum charts come alive", W / 2, H / 2 - 6);
  g.font = "12px Inter, system-ui"; g.fillStyle = "#b4aee0";
  g.fillText(S.es ? "Control limits appear after about 8 minutes of play" : "Each dot = 90 seconds of play · diamonds = momentum swings", W / 2, H / 2 + 14);
  g.textAlign = "start";
}
function diamond(g, x, y, r) { g.beginPath(); g.moveTo(x, y - r); g.lineTo(x + r, y); g.lineTo(x, y + r); g.lineTo(x - r, y); g.closePath(); g.fill(); }

/* ---------------- agent ops ---------------- */
function buildFlow() {
  $("flow").innerHTML = FLOW.map((n, i) => `<span class="node" id="node-${n}">${n.replace("_", "-")}</span>${i < FLOW.length - 1 ? '<span class="arr">→</span>' : ""}`).join("");
}
function buildLanes() {
  $("lanes").innerHTML = AGENTS.map((a) => `<div class="lane-l" title="${a}">${a.replace("pundit.", "🎙 ")}</div><div class="lane-t" id="lane-${a.replace(".", "_")}"></div>`).join("");
}
function onTrace(spans) {
  for (const s of spans) {
    S.counts[s.status] = (S.counts[s.status] || 0) + 1;
    if (S.spans[s.agent]) { S.spans[s.agent].push(s.status); if (S.spans[s.agent].length > 60) S.spans[s.agent].shift(); }
    const node = $("node-" + (s.agent.startsWith("pundit") ? "pundits" : s.agent));
    if (node) { node.className = "node " + s.status; clearTimeout(node._t); node._t = setTimeout(() => (node.className = "node"), 700); }
    if (!["ok"].includes(s.status)) {
      const li = document.createElement("li");
      const m = Math.floor(s.t / 60), sec = String(Math.floor(s.t % 60)).padStart(2, "0");
      li.innerHTML = `<span class="st ${s.status}">${s.status.toUpperCase()}</span>${m}:${sec} · <b>${esc(s.agent)}</b> after ${s.attempts} attempt(s) — ${esc(s.note || "")}`;
      $("incidents").prepend(li); while ($("incidents").children.length > 30) $("incidents").lastChild.remove();
    }
  }
  if (!S.opsDirty) { S.opsDirty = true; setTimeout(() => { S.opsDirty = false; renderOps(); }, 200); }
}
function renderOps() {
  for (const a of AGENTS) { const el = $("lane-" + a.replace(".", "_")); if (el) el.innerHTML = S.spans[a].slice(-40).map((s) => `<i class="${s}"></i>`).join(""); }
  const c = S.counts, total = Object.values(c).reduce((x, y) => x + y, 0);
  $("opsStats").innerHTML = `<span><b>${total}</b>agent calls</span><span><b>${c.ok || 0}</b>ok</span><span><b style="color:var(--amber)">${c.recovered || 0}</b>recovered by retry</span>` +
    `<span><b style="color:var(--red)">${(c.fallback || 0) + (c.deferred || 0)}</b>fallback / deferred</span><span><b>${c.rejected || 0}</b>bad events rejected</span>`;
}
/* ---------------- debugger ---------------- */
const SEV = ["info", "warning", "error", "critical"];
function onDebug(f) {
  S.debug[f.key] = f;
  const b = $("dbgBtn"); b.classList.remove("bump"); void b.offsetWidth; b.classList.add("bump");
  if (!S.dbgDirty) { S.dbgDirty = true; setTimeout(() => { S.dbgDirty = false; renderDebugger(); }, 250); }
}
function renderDebugger() {
  const items = Object.values(S.debug).sort((a, b) => SEV.indexOf(b.severity) - SEV.indexOf(a.severity) || b.last_t - a.last_t);
  const by = Object.fromEntries(SEV.map((s) => [s, items.filter((i) => i.severity === s).length]));
  const worst = [...SEV].reverse().find((s) => by[s]) || "";
  const health = by.critical ? "critical" : by.error ? "degraded" : by.warning ? "warning" : items.length ? "healthy" : (S.es ? "healthy" : "idle");
  $("dbgCount").textContent = items.length; $("dbgBtn").className = "btn icon dbg-btn " + (worst === "info" ? "" : worst);
  $("dbgHealth").textContent = health; $("dbgHealth").className = "health " + health;
  $("dbgSev").innerHTML = SEV.map((s) => `<span><b>${by[s]}</b>${s}</span>`).join("");
  $("dbgList").innerHTML = items.length ? items.slice(0, 40).map((f) => `<li class="sev-${f.severity}" data-agent="${esc(f.agent)}" data-min="${f.minute}" title="Click to highlight this agent">
      <div class="d-t"><span class="sev sev-${f.severity}">${f.severity}</span>${esc(f.title)}</div>
      <div class="d-m">${esc(f.agent)} · ${f.minute}' · seen ${f.count}× · ${esc(f.detail || "")}</div>
      <div class="d-fix"><b>Likely cause:</b> ${esc(f.cause)}<br><b>Fix:</b> ${esc(f.fix)}</div></li>`).join("")
    : `<li class="empty">${S.es ? "All quiet. No anomalies so far." : "All quiet. The Debugger watches every agent call, data check and AI request, and will list anything odd here."}</li>`;
  document.querySelectorAll("#dbgList li[data-agent]").forEach((li) => (li.onclick = () => focusAgent(li.dataset.agent, li.dataset.min)));
}
function focusAgent(agent, min) {
  const lane = $("lane-" + agent.replace(".", "_"));
  document.querySelector(".ops-card").scrollIntoView({ behavior: "smooth", block: "center" });
  if (lane) { lane.classList.add("flash"); lane.previousElementSibling.classList.add("flash"); setTimeout(() => { lane.classList.remove("flash"); lane.previousElementSibling.classList.remove("flash"); }, 2500); }
  toast(`<b>${esc(agent)}</b> · around minute ${min}'`, 2000);
}
function toggleDebugger() { const p = $("dbgPanel"); p.hidden = !p.hidden; if (!p.hidden) renderDebugger(); }
init();
