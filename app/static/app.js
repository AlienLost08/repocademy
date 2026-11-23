/* Repocademy front end: vanilla JS, no build step. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LANG_COLORS = { python: "#3572A5", javascript: "#f1e05a", typescript: "#3178c6", Python: "#3572A5", JavaScript: "#f1e05a", TypeScript: "#3178c6", HTML: "#e34c26", CSS: "#563d7c", Shell: "#89e051", Go: "#00ADD8", Rust: "#dea584" };
const XP = { mcq: 10, bug: 20, order: 15, line: 15, ex: 15 };
let COURSE = null, SLUG = null, CUR = 1, LLM = null;

/* ---------- tiny markdown (escaped first, so model text can't inject HTML) ---------- */
function inline(s) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return t;
}
function md(s) {
  const blocks = String(s || "").trim().split(/\n\s*\n/);
  return blocks.map((b) => {
    const lines = b.split("\n");
    if (lines.every((l) => /^\s*[-*] /.test(l))) return "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*[-*] /, "")) + "</li>").join("") + "</ul>";
    return "<p>" + lines.map(inline).join("<br>") + "</p>";
  }).join("");
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2200); }
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

/* ---------- progress (localStorage only; nothing leaves the browser) ---------- */
const P = {
  key: (slug) => "repocademy:" + slug,
  get(slug) { try { return JSON.parse(localStorage.getItem(this.key(slug))) || { done: {}, ans: {}, ex: {}, xp: 0 }; } catch { return { done: {}, ans: {}, ex: {}, xp: 0 }; } },
  set(slug, v) { localStorage.setItem(this.key(slug), JSON.stringify(v)); },
};
function progressPct(course, prog) {
  const n = course ? course.chapters.length : (prog.total || 1);
  return Math.round(100 * Object.keys(prog.done || {}).length / Math.max(1, n));
}

/* ---------- code rendering ---------- */
function hl(text, lang) {
  try { return hljs.highlight(text, { language: lang === "typescript" ? "typescript" : lang === "javascript" ? "javascript" : "python", ignoreIllegals: true }).value; } catch { return esc(text); }
}
function codeTable(rows, lang, { focus = null, pick = null, marks = {} } = {}) {
  return `<div class="code"><table>${rows.map(([n, t]) => {
    if (n === null || n === undefined) return `<tr class="gap"><td class="ln">⋮</td><td class="src">${esc(t)}</td></tr>`;
    const cls = [n === focus ? "focus" : "", marks[n] || "", pick && pick.includes(n) ? "pickable" : ""].join(" ").trim();
    return `<tr data-ln="${n}" class="${cls}"><td class="ln">${n}</td><td class="src">${hl(t, lang) || " "}</td></tr>`;
  }).join("")}</table></div>`;
}

/* ---------- routing ---------- */
function go(path, push = true) { if (push) history.pushState({}, "", path); route(); }
window.addEventListener("popstate", route);
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (a && a.origin === location.origin) { e.preventDefault(); const u = new URL(a.href); if (u.pathname === location.pathname && u.hash) { history.pushState({}, "", u.pathname + u.hash); route(); } else go(u.pathname + u.hash); }
});
async function route() {
  closeChat(); $("#mapPanel").classList.add("hidden");
  const m = location.pathname.match(/^\/c\/([\w.\-]+)/);
  if (m) { await openCourse(m[1]); return; }
  await home();
  if (location.hash === "#how") $("#how")?.scrollIntoView({ behavior: "smooth" });
}

/* ---------- home ---------- */
async function home() {
  COURSE = null; SLUG = null; $("#fab")?.remove();
  const v = $("#view");
  v.innerHTML = `
  <section class="hero">
    <span class="badge"><i></i> Free &amp; open · runs on a laptop · no API keys needed</span>
    <h1>Turn any GitHub repo<br>into a <span class="grad">guided course</span>.</h1>
    <p class="lede">Paste a link. Repocademy maps the architecture with real static analysis, then builds chapters tied to real code, an interactive map, quizzes that grade instantly, and a chat that cites <code>file:line</code>.</p>
    <form class="urlbox" id="urlForm">
      <span class="gh"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></span>
      <input id="urlInput" placeholder="https://github.com/owner/repo" spellcheck="false" autocomplete="off" aria-label="GitHub repository URL">
      <button class="btn primary" type="submit">Generate course →</button>
    </form>
    <div class="form-err" id="formErr"></div>
    <div class="chips" id="tryChips"></div>
  </section>
  <section class="section"><h2>Ready-made courses</h2><p class="sub">Pre-generated so they open instantly. Your progress is saved in this browser.</p><div class="cards" id="cards"><div class="card"><div class="skeleton" style="width:40%"></div><br><div class="skeleton"></div></div></div></section>
  <section class="section" id="how"><h2>How it works</h2><p class="sub">The structure comes from deterministic static analysis, so a small local model can't make it wrong.</p>
    <div class="steps">
      <div class="step glass"><div class="n">01 · clone</div><h4>Shallow, read-only clone</h4><p>Only public github.com repos. Symlinks, hooks and LFS are disabled. Repo code is never executed on the server.</p></div>
      <div class="step glass"><div class="n">02 · map</div><h4>Real static analysis</h4><p>Python <code>ast</code> and tree-sitter for JS/TS find every function, class, import and call, then rank them with PageRank.</p></div>
      <div class="step glass"><div class="n">03 · plan</div><h4>A course, not a summary</h4><p>Front door → a real call traced hop by hop → core modules → tests. Quizzes and "find the bug" are generated from the code itself.</p></div>
      <div class="step glass"><div class="n">04 · learn</div><h4>Learn by doing</h4><p>Instant grading, runnable snippets in your browser, and an "Ask the repo" chat whose citations are checked against the code.</p></div>
    </div></section>
  <div class="footer">Repocademy · MIT licensed · works offline with local models via Ollama, or with free-tier APIs if you set one</div>`;
  $("#urlForm").addEventListener("submit", (e) => { e.preventDefault(); startBuild($("#urlInput").value); });
  ["psf/requests", "pallets/flask", "expressjs/express", "pallets/click", "sindresorhus/ky"].forEach((r) => {
    const c = document.createElement("span"); c.className = "chip"; c.textContent = r; c.onclick = () => { $("#urlInput").value = "https://github.com/" + r; $("#urlInput").focus(); }; $("#tryChips").appendChild(c);
  });
  try {
    const list = await api("/api/courses");
    $("#cards").innerHTML = list.map(cardHTML).join("") || `<div class="muted">No courses yet. Paste a repo above.</div>`;
    $$("#cards .card").forEach((el) => el.addEventListener("click", () => go("/c/" + el.dataset.slug)));
  } catch (e) { $("#cards").innerHTML = `<div class="muted">Couldn't load courses: ${esc(e.message)}</div>`; }
}
function cardHTML(c) {
  const prog = P.get(c.slug); const pct = Math.round(100 * Object.keys(prog.done || {}).length / Math.max(1, c.chapters));
  const lang = c.main_lang || "python";
  const ai = c.narration && c.narration.status === "done" && c.narration.accepted ? `<span class="tag ai">✨ AI-narrated</span>` : "";
  return `<div class="card" data-slug="${esc(c.slug)}" tabindex="0">
    <div class="owner">${esc(c.repo.owner)} /</div><h3>${esc(c.repo.name)}${c.showcase ? '<span class="tag">showcase</span>' : ""}${ai}</h3>
    <div class="desc">${esc(c.repo.description || "")}</div>
    <div class="meta"><span><span class="langdot" style="background:${LANG_COLORS[lang] || "#888"}"></span>${esc(lang)}</span><span><b>${c.chapters}</b> chapters</span><span><b>${c.questions}</b> questions</span><span><b>${c.exercises}</b> try-its</span><span>~<b>${c.minutes}</b> min</span></div>
    <div class="bar"><i style="width:${pct}%"></i></div><div class="cta">${pct ? (pct === 100 ? "Completed ✓ · review" : `Continue · ${pct}% done`) : "Start learning →"}</div></div>`;
}

/* ---------- build flow ---------- */
const STAGES = [["clone", "Shallow clone"], ["scan", "Read files"], ["parse", "Parse with ast / tree-sitter"], ["map", "Map imports, calls & entry points"], ["plan", "Plan chapters, quizzes & exercises"], ["done", "Course ready"]];
function countUp(el, to) {
  const from = +el.dataset.v || 0; if (from === to) return; el.dataset.v = to;
  const t0 = performance.now(), d = 700;
  (function tick(t) { const k = Math.min(1, (t - t0) / d), e = 1 - Math.pow(1 - k, 3); el.textContent = Math.round(from + (to - from) * e).toLocaleString(); if (k < 1) requestAnimationFrame(tick); })(t0);
}
async function startBuild(url) {
  $("#formErr").textContent = "";
  if (!url.trim()) { $("#formErr").textContent = "Paste a GitHub URL first."; return; }
  let res;
  try { res = await api("/api/build", { method: "POST", body: JSON.stringify({ url }) }); } catch (e) { $("#formErr").textContent = e.message; return; }
  if (res.cached) { go("/c/" + res.slug); return; }
  const ov = $("#buildOverlay"); ov.classList.remove("hidden");
  $("#buildTitle").textContent = res.slug.replace("__", "/"); $("#buildMsg").textContent = ""; $("#buildMsg").className = "build-msg";
  $("#buildSpin").className = "spinner"; $("#buildSpin").textContent = "";
  $$("#buildCounts b").forEach((b) => { b.textContent = "0"; b.dataset.v = 0; });
  $("#pipeline").innerHTML = STAGES.map(([k, l], i) => `<li data-k="${k}" style="--i:${i}"><span class="dot"></span><div><div>${l}</div><div class="m"></div></div><span class="t"></span></li>`).join("");
  const bar = $("#buildBar"); bar.className = ""; bar.style.width = "0%";
  // smooth bar: each stage owns a slice; inside the active slice the bar eases toward (never reaches) its end
  let stageIdx = 0, stageT = performance.now(), shown = 0, finished = false, stop = false;
  const span = 100 / (STAGES.length - 1);
  (function anim(t) {
    if (stop) return;
    const creep = finished ? 0 : span * 0.92 * (1 - Math.exp(-(t - stageT) / 2500));
    const target = finished ? 100 : Math.min(99, stageIdx * span + creep);
    shown += (target - shown) * 0.12; bar.style.width = shown.toFixed(2) + "%";
    if (!(finished && shown > 99.6)) requestAnimationFrame(anim); else bar.style.width = "100%";
  })(performance.now());
  const t0 = performance.now(); const timer = setInterval(() => $("#buildTime").textContent = ((performance.now() - t0) / 1000).toFixed(1) + "s", 100);
  $("#buildCancel").onclick = () => { stop = true; clearInterval(timer); ov.classList.add("hidden"); };
  while (!stop) {
    await new Promise((r) => setTimeout(r, 300));
    let j; try { j = await api("/api/jobs/" + res.job); } catch { continue; }
    const seen = new Set(j.stages.map((s) => s.stage));
    const idx = Math.max(0, ...STAGES.map(([k], i) => (seen.has(k) ? i : 0)));
    if (idx !== stageIdx) { stageIdx = idx; stageT = performance.now(); }
    STAGES.forEach(([k], i) => {
      const li = $(`#pipeline li[data-k="${k}"]`); const st = j.stages.filter((s) => s.stage === k).pop();
      const laterSeen = STAGES.slice(i + 1).some(([k2]) => seen.has(k2));
      const cls = st && (laterSeen || k === "done") ? "done" : st ? "active" : "";
      if (li.className !== cls) { li.className = cls; if (cls === "done") li.querySelector(".dot").textContent = "✓"; }
      if (st) { li.querySelector(".m").textContent = st.msg; li.querySelector(".t").textContent = st.t.toFixed(1) + "s"; }
    });
    j.stages.forEach((st) => Object.entries(st.data || {}).forEach(([k, v]) => { const el = $(`#buildCounts b[data-c="${k}"]`); if (el && typeof v === "number") countUp(el, v); }));
    if (j.status === "done") {
      finished = true; clearInterval(timer); bar.className = "ok"; $("#buildSpin").className = "spinner done"; $("#buildSpin").textContent = "✓";
      await new Promise((r) => setTimeout(r, 900)); stop = true; ov.classList.add("hidden"); go("/c/" + j.slug); return;
    }
    if (j.status === "error") { stop = true; clearInterval(timer); bar.className = "err"; $("#buildSpin").className = "spinner err"; $("#buildMsg").textContent = j.error; $("#buildMsg").className = "build-msg err"; return; }
  }
}

/* ---------- course ---------- */
async function openCourse(slug) {
  if (!COURSE || SLUG !== slug) {
    $("#view").innerHTML = `<div class="main" style="margin:40px auto"><div class="skeleton" style="width:30%"></div><br><div class="skeleton" style="width:70%"></div></div>`;
    try { COURSE = await api("/api/courses/" + slug); SLUG = slug; } catch (e) { $("#view").innerHTML = `<div class="section"><h2>Course not found</h2><p class="muted">${esc(e.message)}</p><a href="/" data-link>← Back home</a></div>`; return; }
    pollNarration();
  }
  const m = location.hash.match(/^#ch(\d+)/); CUR = m ? Math.min(+m[1], COURSE.chapters.length) : (firstUnfinished() || 1);
  renderCourse();
}
function firstUnfinished() { const p = P.get(SLUG); const c = COURSE.chapters.find((c) => !p.done[c.id]); return c ? c.num : 1; }
let narrTimer = null;
function pollNarration() {
  clearTimeout(narrTimer);
  if (!COURSE || !COURSE.narration || COURSE.narration.status !== "running") return;
  narrTimer = setTimeout(async () => {
    try { const c = await api("/api/courses/" + SLUG); const changed = JSON.stringify(c.chapters.map((x) => x.narrative)) !== JSON.stringify(COURSE.chapters.map((x) => x.narrative)); COURSE.narration = c.narration; COURSE.chapters.forEach((ch, i) => ch.narrative = c.chapters[i].narrative); if (changed) { const y = scrollY; renderCourse(false); scrollTo(0, y); } } catch {}
    pollNarration();
  }, 8000);
}

function ringSVG(pct) {
  const r = 26, c = 2 * Math.PI * r;
  return `<svg class="ring" viewBox="0 0 62 62"><defs><linearGradient id="rg" x1="0" x2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs><circle class="trk" cx="31" cy="31" r="${r}"/><circle class="val" cx="31" cy="31" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct / 100)}" transform="rotate(-90 31 31)"/><text x="31" y="36" text-anchor="middle">${pct}%</text></svg>`;
}
function renderCourse(scroll = true) {
  const c = COURSE, prog = P.get(SLUG), ch = c.chapters[CUR - 1];
  const pct = progressPct(c, prog);
  $("#view").innerHTML = `<div class="course">
    <aside class="side">
      <div class="repo"><span class="o">${esc(c.repo.owner)} /</span><h2>${esc(c.repo.name)}</h2><a href="${esc(c.repo.url)}/tree/${esc(c.repo.sha)}" target="_blank" rel="noopener">@ ${esc(c.repo.sha.slice(0, 7))} ↗</a></div>
      <div class="ringrow glass">${ringSVG(pct)}<div class="xp"><b>${prog.xp || 0} XP</b>${Object.keys(prog.done).length}/${c.chapters.length} chapters · ${Object.values(prog.ans).filter((a) => a.ok).length} correct answers</div></div>
      <div class="side-actions"><button class="btn sm" id="openMap">🗺️ Map</button><button class="btn sm" id="openChat">💬 Ask</button></div>
      <button class="btn sm chtoggle" id="chToggle" aria-expanded="false">☰ Chapters · ${CUR}/${c.chapters.length} <span class="dim">${inline(ch.title)}</span></button>
      <ol class="chlist">${c.chapters.map((x) => `<li class="${prog.done[x.id] ? "done" : ""}"><a href="#ch${x.num}" data-link class="${x.num === CUR ? "cur" : ""}"><span class="num">${prog.done[x.id] ? "✓" : x.num}</span><span class="ttl">${inline(x.title)}</span><span class="min">${x.minutes}m</span></a></li>`).join("")}</ol>
      <div style="margin-top:18px;font-size:.75rem" class="dim">Built in ${c.build_seconds}s from ${c.stats.parsed} files · ${c.stats.symbols} symbols · ${c.stats.calls} call edges.<br><a href="/" data-link>← All courses</a></div>
    </aside>
    <div class="main" id="chMain">${chapterHTML(ch, prog)}</div></div>`;
  if (!$("#fab")) { const f = document.createElement("button"); f.id = "fab"; f.className = "btn primary fab"; f.innerHTML = "💬 Ask the repo"; f.onclick = () => openChat(); document.body.appendChild(f); }
  $("#openMap").onclick = openMap; $("#openChat").onclick = () => openChat();
  $("#chToggle").onclick = () => { const s = $(".side"); s.classList.toggle("open"); $("#chToggle").setAttribute("aria-expanded", s.classList.contains("open")); };
  wireChapter(ch);
  if (scroll) window.scrollTo({ top: 0 });
}

function introHTML(ch) {
  const n = ch.narrative;
  if (n && n.text) return `<div class="intro glass ai"><p>${inline(n.text)}</p><div class="src">✨ AI narration by <code>${esc(n.model)}</code>, every code name checked against the repo</div><details class="alt"><summary class="dim" style="cursor:pointer">Show the template version</summary>${md(ch.intro)}</details></div>`;
  const running = COURSE.narration && COURSE.narration.status === "running" ? `<div class="src"><span class="typing"><i></i><i></i><i></i></span> an AI narration is being written; this template text is shown until it's ready</div>` : "";
  return `<div class="intro glass">${md(ch.intro)}${running}</div>`;
}

function chapterHTML(ch, prog) {
  let h = `<div class="ch-head"><div class="kicker">Chapter ${ch.num} of ${COURSE.chapters.length} <span class="dim">· ~${ch.minutes} min${ch.quiz.length ? ` · ${ch.quiz.length} questions` : ""}</span></div><h1>${inline(ch.title)}</h1><p class="subtitle">${inline(ch.subtitle)}</p></div>`;
  if (ch.intro) h += introHTML(ch);
  if (ch.kind === "overview") h += overviewHTML(ch);
  if (ch.kind === "trace") h += `<div class="trace glass">${[ch.trace[0].caller, ...ch.trace.map((s) => s.callee)].map((n, i) => `${i ? '<span class="arrow">→</span>' : ""}<span class="hop" data-sec="${i}">${esc(n)}<small>${i === 0 ? "start" : "step " + i}</small></span>`).join("")}</div>`;
  if (ch.usage) h += `<div class="h3">How people use it (from the README)</div><div class="sec glass"><div class="sec-head"><h3>Usage example</h3><a class="loc" href="${esc(ch.usage.github)}" target="_blank" rel="noopener">${esc(ch.usage.file)}:${ch.usage.line} ↗</a></div>${codeTable(ch.usage.code.split("\n").map((t, i) => [ch.usage.line + i + 1, t]), COURSE.main_lang)}</div>`;
  if (ch.sections.length) {
    h += `<div class="h3">${ch.kind === "trace" ? "Hop by hop" : "Read the code"}</div>`;
    h += ch.sections.map((s, i) => sectionHTML(s, i)).join("");
  }
  if (ch.diagram && ch.diagram.nodes && ch.diagram.nodes.length > 1) h += `<div class="h3">How these pieces connect</div><div class="mini glass" id="mini"><div class="hint">Calls between the functions in this chapter (highlighted) and their neighbours. Drag nodes around.</div></div>`;
  if (ch.kind === "next") h += nextHTML(ch);
  if (ch.exercises.length) h += `<div class="h3">Try it</div>` + ch.exercises.map((e, i) => exerciseHTML(e, i, ch)).join("");
  if (ch.quiz.length) h += `<div class="h3">${ch.kind === "next" ? "Final exam" : "Check your understanding"}</div><div class="quiz">${ch.quiz.map((q, i) => quizHTML(q, i, ch, prog)).join("")}</div><div class="scorebar glass" id="scorebar"></div>`;
  const prev = COURSE.chapters[ch.num - 2], next = COURSE.chapters[ch.num];
  h += `<div class="navbtns">${prev ? `<a class="btn ghost" href="#ch${prev.num}" data-link>← ${inline(prev.title)}</a>` : "<span></span>"}<button class="btn primary" id="completeBtn">${next ? "Complete & continue →" : "Finish course 🎓"}</button></div>`;
  return h;
}

function overviewHTML(ch) {
  const s = ch.stats || {};
  let h = `<div class="tiles"><div class="tile glass"><b>${s.source_files ?? "–"}</b><span>source files</span></div><div class="tile glass"><b>${s.symbols ?? "–"}</b><span>functions & classes</span></div><div class="tile glass"><b>${s.calls ?? "–"}</b><span>resolved call edges</span></div><div class="tile glass"><b>${s.test_files ?? "–"}</b><span>test files</span></div></div>`;
  if (ch.languages?.length) h += `<div class="h3">Languages</div><div class="langbar">${ch.languages.map((l) => `<i style="width:${l.pct}%;background:${LANG_COLORS[l.name] || "#777"}" title="${esc(l.name)} ${l.pct}%"></i>`).join("")}</div><div class="langs">${ch.languages.map((l) => `<span><span class="langdot" style="background:${LANG_COLORS[l.name] || "#777"}"></span>${esc(l.name)} ${l.pct}%</span>`).join("")}</div>`;
  if (ch.dependencies?.length) h += `<div class="h3">Leans on these libraries</div><div class="deps">${ch.dependencies.map((d) => `<span class="dep">${esc(d.name)}<i>×${d.uses}</i></span>`).join("")}</div>`;
  if (ch.layout?.length) h += `<div class="h3">How the repo is laid out</div><div class="glass" style="border-radius:16px;overflow:hidden"><table class="layout">${ch.layout.slice(0, 10).map((t) => `<tr><td>${esc(t.path)}${t.path.startsWith("(") ? "" : "/"}</td><td>${esc(t.hint)}<span class="rolechip">${esc(t.role)}</span></td><td class="n">${t.files} files</td><td class="n">${t.lines.toLocaleString()} lines</td></tr>`).join("")}</table></div>`;
  if (ch.commands?.length) h += `<div class="h3">Get it running (from the README)</div><div class="cmds">${ch.commands.map((c) => `<div>${esc(c)}</div>`).join("")}</div>`;
  return h;
}

function sectionHTML(s, i) {
  return `<article class="sec glass" id="sec${i}">
    <div class="sec-head"><h3>${inline(s.title)}</h3><a class="loc" href="${esc(s.github)}" target="_blank" rel="noopener" title="Open these exact lines on GitHub">${esc(s.file)}:${s.start}${s.end && s.end !== s.start ? "–" + s.end : ""} ↗</a></div>
    <p class="lead">${inline(s.lead)}</p>${s.importance ? `<p class="imp">★ ${inline(s.importance)}</p>` : ""}
    ${s.facts?.length ? `<details class="facts"><summary>Facts from the code</summary><ul>${s.facts.map((f) => `<li>${inline(f)}</li>`).join("")}</ul></details>` : ""}
    ${codeTable(s.code, s.lang, { focus: s.focus })}
    <div class="sec-foot"><button class="btn sm ask-about" data-q="${esc(`Explain how ${s.symbol} works and what it's used for.`)}">💬 Ask about this</button><a class="btn sm ghost" href="${esc(s.github)}" target="_blank" rel="noopener">Open on GitHub ↗</a></div></article>`;
}

function nextHTML(ch) {
  let h = "";
  if (ch.todos?.length) h += `<div class="h3">Open TODOs left by the maintainers</div><div class="lst">${ch.todos.map((t) => `<a class="row" href="${esc(t.github)}" target="_blank" rel="noopener"><span>📝 ${inline(t.text)}</span><span class="f">${esc(t.file)}:${t.line}</span></a>`).join("")}</div>`;
  if (ch.big?.length) h += `<div class="h3">Boss fights: the biggest functions</div><div class="lst">${ch.big.map((b) => `<a class="row" href="${esc(b.github)}" target="_blank" rel="noopener"><span>🐉 <code>${esc(b.symbol)}</code> · ${b.lines} lines</span><span class="f">${esc(b.file)}:${b.start}</span></a>`).join("")}</div>`;
  if (ch.undocumented?.length) h += `<div class="h3">A first contribution: important code with no docstring</div><div class="lst">${ch.undocumented.map((b) => `<a class="row" href="${esc(b.github)}" target="_blank" rel="noopener"><span>✍️ <code>${esc(b.symbol)}</code></span><span class="f">${esc(b.file)}:${b.start}</span></a>`).join("")}</div>`;
  if (ch.further?.length) h += `<div class="h3">Further reading: files this course didn't cover</div><div class="lst">${ch.further.map((f) => `<a class="row" href="${esc(f.github)}" target="_blank" rel="noopener"><span><code>${esc(f.file)}</code> ${f.summary ? "· " + inline(f.summary) : ""}</span><span class="f">${f.lines} lines</span></a>`).join("")}</div>`;
  return h;
}

/* ---------- quizzes ---------- */
function qKey(ch, i) { return ch.id + ":" + i; }
function quizHTML(q, i, ch, prog) {
  const a = prog.ans[qKey(ch, i)];
  const label = { mcq: "Quiz", bug: "Find the bug", order: "Put in order", line: "Find the line" }[q.type];
  let body = "";
  if (q.type === "mcq" || q.type === "bug") {
    if (q.type === "bug") {
      const lines = q.options.map((o) => +o.replace(/\D/g, ""));
      body += `<div class="qcode">${codeTable(q.code, q.lang, { pick: lines })}</div>`;
    }
    body += `<div class="opts">${q.options.map((o, j) => `<button class="opt" data-j="${j}"><span class="k">${"ABCD"[j]}</span><span>${inline(q.type === "mcq" && /^[\w./@-]+\.\w+$/.test(o) ? "`" + o + "`" : o.includes("`") || q.type === "bug" ? o : (/^[\w.]+$/.test(o) ? "`" + o + "`" : o))}</span></button>`).join("")}</div>`;
  } else if (q.type === "order") {
    body += `<ol class="order-list">${q.items.map((it, j) => `<li data-j="${j}"><span class="pos">${j + 1}.</span><span>${esc(it)}</span><span class="mv"><button class="icon-btn up" aria-label="Move up">↑</button><button class="icon-btn down" aria-label="Move down">↓</button></span></li>`).join("")}</ol><button class="btn sm primary check-order">Check order</button>`;
  } else if (q.type === "line") {
    body += `<div class="line-in"><input type="number" min="1" placeholder="line #" aria-label="Line number"><button class="btn sm primary check-line">Check</button><a class="btn sm ghost" href="${esc(COURSE.repo.url)}/blob/${esc(COURSE.repo.sha)}/${esc(q.file)}" target="_blank" rel="noopener">Open the file ↗</a></div>`;
  }
  return `<div class="q glass" data-i="${i}"><div class="qhead"><span class="qtype ${q.type}">${label}</span><span class="xpv">+${XP[q.type]} XP</span></div><p class="prompt">${inline(q.prompt)}</p>${body}<div class="feedback ${a ? "show " + (a.ok ? "ok" : "no") : ""}">${a ? feedbackText(q, a.ok) : ""}</div></div>`;
}
function feedbackText(q, ok) { return (ok ? "<b>✓ Correct.</b> " : "<b>✗ Not quite.</b> ") + inline(q.explain) + (q.github ? ` <a href="${esc(q.github)}" target="_blank" rel="noopener">See the real code ↗</a>` : ""); }

function answer(ch, i, ok, el) {
  const prog = P.get(SLUG); const k = qKey(ch, i);
  if (!prog.ans[k]) { prog.ans[k] = { ok }; if (ok) prog.xp = (prog.xp || 0) + XP[ch.quiz[i].type]; P.set(SLUG, prog); if (ok) toast(`+${XP[ch.quiz[i].type]} XP`); }
  const fb = el.querySelector(".feedback"); fb.className = "feedback show " + (ok ? "ok" : "no"); fb.innerHTML = feedbackText(ch.quiz[i], ok);
  updateScore(ch); refreshSide();
  if (ch.quiz.every((_, j) => P.get(SLUG).ans[qKey(ch, j)])) markDone(ch, false);
}
function updateScore(ch) {
  const sb = $("#scorebar"); if (!sb) return; const prog = P.get(SLUG);
  const answered = ch.quiz.filter((_, j) => prog.ans[qKey(ch, j)]); const right = answered.filter((_, j) => true).filter((q) => prog.ans[qKey(ch, ch.quiz.indexOf(q))].ok).length;
  sb.innerHTML = answered.length ? `<b>${right}/${ch.quiz.length}</b><span class="muted">${answered.length < ch.quiz.length ? `answered ${answered.length} of ${ch.quiz.length}` : right === ch.quiz.length ? "Perfect score. 🔥" : "Wrong answers show the real code. Review and move on."}</span>` : `<span class="muted">Answer the questions to finish the chapter. Everything is graded instantly in your browser.</span>`;
}
function lockOpts(qel, q, j) {
  $$(".opt", qel).forEach((b, k) => { b.disabled = true; if (k === q.answer) b.classList.add("right"); if (k === j && j !== q.answer) b.classList.add("wrong"); });
  if (q.type === "bug") {
    const right = +q.options[q.answer].replace(/\D/g, ""); const tr = $(`tr[data-ln="${right}"]`, qel);
    if (tr) { tr.classList.add("bad"); tr.querySelector(".src").innerHTML = hl(q.mutated, q.lang) + ` <span style="color:var(--green)">  ← real: ${esc(q.original)}</span>`; }
    $$("tr.pickable", qel).forEach((t) => t.classList.remove("pickable"));
  }
}
function wireQuiz(ch) {
  const prog = P.get(SLUG);
  $$(".q").forEach((qel) => {
    const i = +qel.dataset.i, q = ch.quiz[i], prev = prog.ans[qKey(ch, i)];
    if (q.type === "mcq" || q.type === "bug") {
      if (prev) lockOpts(qel, q, prev.ok ? q.answer : -1);
      $$(".opt", qel).forEach((b) => b.onclick = () => { const j = +b.dataset.j; lockOpts(qel, q, j); answer(ch, i, j === q.answer, qel); });
      if (q.type === "bug") $$("tr.pickable", qel).forEach((tr) => tr.onclick = () => { const n = +tr.dataset.ln; const j = q.options.findIndex((o) => +o.replace(/\D/g, "") === n); if (j >= 0 && !$(".opt", qel).disabled) $$(".opt", qel)[j].click(); });
    } else if (q.type === "order") {
      const list = $(".order-list", qel);
      const renum = () => $$("li", list).forEach((li, k) => li.querySelector(".pos").textContent = k + 1 + ".");
      $$("li", list).forEach((li) => { li.querySelector(".up").onclick = () => { if (li.previousElementSibling) list.insertBefore(li, li.previousElementSibling); renum(); }; li.querySelector(".down").onclick = () => { if (li.nextElementSibling) list.insertBefore(li.nextElementSibling, li); renum(); }; });
      $(".check-order", qel).onclick = () => {
        const order = $$("li", list).map((li) => +li.dataset.j); const ok = order.every((v, k) => v === q.answer[k]);
        $$("li", list).forEach((li, k) => li.classList.add(+li.dataset.j === q.answer[k] ? "right" : "wrong"));
        answer(ch, i, ok, qel);
      };
    } else if (q.type === "line") {
      const inp = $("input", qel);
      const check = () => { const v = +inp.value; if (!v) return; answer(ch, i, Math.abs(v - q.answer) <= (q.tolerance || 0), qel); };
      $(".check-line", qel).onclick = check; inp.onkeydown = (e) => { if (e.key === "Enter") check(); };
    }
  });
  updateScore(ch);
}

/* ---------- exercises: run in the learner's browser, never on the server ---------- */
function exerciseHTML(e, i, ch) {
  if (e.type === "local") return `<div class="ex glass"><div class="ex-head"><div class="kicker">On your machine</div><h3>${inline(e.title)}</h3></div><ol class="steps-list">${e.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>`;
  const done = P.get(SLUG).ex[ch.id + ":" + i];
  return `<div class="ex glass" data-i="${i}"><div class="ex-head"><div class="kicker">Predict, then run ${done ? "· ✓ done" : ""}</div><h3>${inline(e.title)}</h3><div class="muted">The code below is copied verbatim from <a href="${esc(e.github)}" target="_blank" rel="noopener">${esc(e.file)}:${e.start}</a>. Example calls come from the repo's own tests. It runs in <b>your browser</b> (${e.lang === "python" ? "Pyodide" : "a sandboxed Web Worker"}).</div></div>
    <details><summary class="dim" style="padding:0 18px 10px;cursor:pointer">Show the code (${e.code.split("\n").length} lines)</summary>${codeTable(e.code.split("\n").map((t, k) => [k + 1, t]), e.lang)}</details>
    <div class="ex-row"><select aria-label="Example call">${e.calls.map((c, k) => `<option value="${k}">${esc(c.call)}</option>`).join("")}</select></div>
    <div class="ex-row"><input class="pred" placeholder="Your prediction, e.g. ${e.lang === "python" ? "['a', 'b']" : '"text/html"'}" aria-label="Your prediction"><button class="btn sm primary run">▶ Run in browser</button></div>
    <div class="ex-out"></div></div>`;
}
let pyodideP = null;
function loadPyodide_() {
  if (!pyodideP) pyodideP = new Promise((res, rej) => { const s = document.createElement("script"); s.src = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js"; s.onload = () => window.loadPyodide().then(res, rej); s.onerror = () => rej(new Error("Couldn't load Pyodide (needs internet the first time).")); document.head.appendChild(s); });
  return pyodideP;
}
async function runPython(code, call) {
  const py = await loadPyodide_();
  py.globals.set("__src", code); py.globals.set("__call", call);
  return py.runPython(`
ns = {}
try:
    exec(__src, ns)
    __r = repr(eval(__call, ns))
except Exception as e:
    __r = "raises " + type(e).__name__ + ": " + str(e)
__r`);
}
function runJS(code, call) {
  return new Promise((res) => {
    const src = `onmessage=()=>{try{const f=new Function(${JSON.stringify(code + "\nreturn (" + call + ");")});const v=f();const j=typeof v==="function"?undefined:JSON.stringify(v);postMessage(j===undefined?String(v):j)}catch(e){postMessage("throws "+e.name+": "+e.message)}}`;
    const w = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    const t = setTimeout(() => { w.terminate(); res("timed out after 3s"); }, 3000);
    w.onmessage = (m) => { clearTimeout(t); w.terminate(); res(m.data); }; w.postMessage(0);
  });
}
const norm = (s) => String(s).replace(/\s+/g, "").replace(/"/g, "'").replace(/^OrderedDict\((.*)\)$/, "$1");
function wireExercises(ch) {
  $$(".ex[data-i]").forEach((el) => {
    const i = +el.dataset.i, e = ch.exercises[i]; const out = $(".ex-out", el);
    $(".run", el).onclick = async () => {
      const call = e.calls[+$("select", el).value].call; out.className = "ex-out show"; out.textContent = e.lang === "python" ? "Loading Python in your browser… (first run takes a few seconds)" : "Running…";
      try {
        const r = e.lang === "python" ? await runPython(e.code, call) : await runJS(e.code, call);
        const pred = $(".pred", el).value.trim();
        let verdict = "";
        if (pred) verdict = norm(pred) === norm(r) ? "\n\n✓ Your prediction was right!" : `\n\n✗ You predicted ${pred}.`;
        out.className = "ex-out show " + (r.startsWith("raises") || r.startsWith("throws") ? "err" : "ok");
        out.textContent = `>>> ${call}\n${r}${verdict}`;
        const prog = P.get(SLUG); const k = ch.id + ":" + i;
        if (!prog.ex[k]) { prog.ex[k] = true; prog.xp = (prog.xp || 0) + XP.ex; P.set(SLUG, prog); toast(`+${XP.ex} XP`); refreshSide(); }
      } catch (err) { out.className = "ex-out show err"; out.textContent = err.message; }
    };
  });
}

/* ---------- wiring ---------- */
function wireChapter(ch) {
  wireQuiz(ch); wireExercises(ch);
  $$(".ask-about").forEach((b) => b.onclick = () => openChat(b.dataset.q));
  $$(".trace .hop").forEach((h) => h.onclick = () => { const i = +h.dataset.sec; const el = $("#sec" + Math.min(i, ch.sections.length - 1)); el?.scrollIntoView({ behavior: "smooth", block: "start" }); });
  $("#completeBtn").onclick = () => { markDone(ch, true); const next = COURSE.chapters[ch.num]; if (next) go(`/c/${SLUG}#ch${next.num}`); else celebrate(); };
  if ($("#mini")) miniGraph($("#mini"), ch.diagram);
}
function markDone(ch, explicit) {
  const prog = P.get(SLUG); if (prog.done[ch.id]) return; prog.done[ch.id] = true; prog.xp = (prog.xp || 0) + 25; P.set(SLUG, prog);
  toast(`Chapter ${ch.num} complete · +25 XP`); refreshSide();
  if (Object.keys(prog.done).length === COURSE.chapters.length) celebrate();
}
function refreshSide() {
  const prog = P.get(SLUG), pct = progressPct(COURSE, prog);
  const rr = $(".ringrow"); if (rr) rr.innerHTML = `${ringSVG(pct)}<div class="xp"><b>${prog.xp || 0} XP</b>${Object.keys(prog.done).length}/${COURSE.chapters.length} chapters · ${Object.values(prog.ans).filter((a) => a.ok).length} correct answers</div>`;
  $$(".chlist li").forEach((li, k) => { const c = COURSE.chapters[k]; if (prog.done[c.id]) { li.classList.add("done"); li.querySelector(".num").textContent = "✓"; } });
}
function celebrate() {
  const prog = P.get(SLUG); const right = Object.values(prog.ans).filter((a) => a.ok).length; const total = COURSE.chapters.reduce((n, c) => n + c.quiz.length, 0);
  const m = $("#chMain"); if (m && !$(".done-banner")) m.insertAdjacentHTML("afterbegin", `<div class="done-banner"><h2>🎓 You finished ${esc(COURSE.repo.name)}!</h2><div class="muted">${right}/${total} questions right · ${prog.xp} XP. You now know your way around a real codebase.</div></div>`);
  confetti(); window.scrollTo({ top: 0, behavior: "smooth" });
}
function confetti() {
  const cv = $("#confetti"), ctx = cv.getContext("2d"); cv.width = innerWidth; cv.height = innerHeight;
  const cols = ["#a78bfa", "#22d3ee", "#f472b6", "#34d399", "#fbbf24"]; const ps = Array.from({ length: 160 }, () => ({ x: innerWidth / 2, y: innerHeight / 3, vx: (Math.random() - .5) * 14, vy: Math.random() * -12 - 4, r: Math.random() * 6 + 3, c: cols[Math.random() * 5 | 0], a: Math.random() * 6 }));
  let f = 0; (function tick() { ctx.clearRect(0, 0, cv.width, cv.height); ps.forEach((p) => { p.x += p.vx; p.y += p.vy; p.vy += .35; p.a += .2; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * .6); ctx.restore(); }); if (++f < 160) requestAnimationFrame(tick); else ctx.clearRect(0, 0, cv.width, cv.height); })();
}

/* ---------- graphs ---------- */
function miniGraph(el, data) {
  const w = el.clientWidth, h = el.clientHeight;
  const nodes = data.nodes.map((d) => ({ ...d })), links = data.edges.map((d) => ({ ...d }));
  const svg = d3.select(el).append("svg").attr("viewBox", [0, 0, w, h]);
  svg.append("defs").html(`<marker id="arr" viewBox="0 -4 8 8" refX="15" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,-4L8,0L0,4" fill="rgba(167,139,250,.6)"/></marker>`);
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(nodes.length > 8 ? 70 : 110)).force("charge", d3.forceManyBody().strength(nodes.length > 8 ? -300 : -520)).force("center", d3.forceCenter(w / 2 - 50, h / 2)).force("collide", d3.forceCollide(46)).force("x", d3.forceX(w / 2 - 50).strength(.05)).force("y", d3.forceY(h / 2).strength(.12));
  const link = svg.append("g").selectAll("line").data(links).join("line").attr("class", "link").attr("marker-end", "url(#arr)");
  const node = svg.append("g").selectAll("g").data(nodes).join("g").attr("class", "node").call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y; }).on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = d.fy = null; }));
  node.append("circle").attr("r", (d) => d.main ? 9 : 5.5).attr("fill", (d) => d.main ? "url(#ng)" : "rgba(154,161,195,.5)").attr("stroke", (d) => d.main ? "#fff" : "none").attr("stroke-width", 1.2);
  svg.select("defs").append("radialGradient").attr("id", "ng").html('<stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#7c5cff"/>');
  node.append("text").attr("x", 12).attr("y", 4).text((d) => d.label.length > 34 ? d.label.slice(0, 33) + "…" : d.label).style("opacity", (d) => d.main ? 1 : .7);
  node.append("title").text((d) => `${d.label}\n${d.file}`);
  sim.on("tick", () => { nodes.forEach((d) => { d.x = Math.max(12, Math.min(w - 120, d.x)); d.y = Math.max(12, Math.min(h - 12, d.y)); }); link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y); node.attr("transform", (d) => `translate(${d.x},${d.y})`); });
}

function openMap() {
  const panel = $("#mapPanel"); panel.classList.remove("hidden");
  $("#mapTitle").textContent = `${COURSE.repo.owner}/${COURSE.repo.name}: ${COURSE.graph.nodes.length} source files`;
  const svgEl = $("#mapSvg"); svgEl.innerHTML = "";
  const w = svgEl.clientWidth, h = svgEl.clientHeight;
  const nodes = COURSE.graph.nodes.map((d) => ({ ...d })); const all = COURSE.graph.edges.map((d) => ({ ...d }));
  const chs = COURSE.chapters; const palette = ["#a78bfa", "#22d3ee", "#f472b6", "#34d399", "#fbbf24", "#60a5fa", "#fb923c", "#e879f9", "#4ade80", "#f87171"];
  const color = (d) => d.chapter ? palette[(d.chapter - 1) % palette.length] : "#4b5175";
  const traceFiles = []; const tr = chs.find((c) => c.kind === "trace"); if (tr) { traceFiles.push(tr.trace[0].file); tr.trace.forEach((s) => traceFiles.push(COURSE.symbols.find((x) => x.id === s.callee_id)?.file || s.file)); }
  const tpairs = new Set(); for (let i = 1; i < traceFiles.length; i++) if (traceFiles[i] !== traceFiles[i - 1]) tpairs.add(traceFiles[i - 1] + "→" + traceFiles[i]);
  const maxLines = d3.max(nodes, (d) => d.lines) || 1; const rad = d3.scaleSqrt().domain([0, maxLines]).range([5, 30]);
  const svg = d3.select(svgEl).attr("viewBox", [0, 0, w, h]); const g = svg.append("g");
  svg.call(d3.zoom().scaleExtent([.2, 4]).on("zoom", (e) => g.attr("transform", e.transform)));
  svg.append("defs").html(`<marker id="marr" viewBox="0 -4 8 8" refX="8" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,-4L8,0L0,4" fill="rgba(34,211,238,.5)"/></marker>`);
  let linkSel, nodeSel, sim;
  function draw() {
    const show = all.filter((e) => (e.kind === "calls" && $("#mapCalls").checked) || (e.kind === "imports" && $("#mapImports").checked));
    g.selectAll("*").remove();
    sim?.stop();
    sim = d3.forceSimulation(nodes).force("link", d3.forceLink(show).id((d) => d.id).distance((e) => 70 + 40 / Math.sqrt(e.weight || 1)).strength(.4)).force("charge", d3.forceManyBody().strength(-Math.max(420, 16000 / Math.max(1, nodes.length)))).force("center", d3.forceCenter(w / 2 - 120, h / 2)).force("collide", d3.forceCollide((d) => rad(d.lines) + (nodes.length < 40 ? 26 : 14))).force("x", d3.forceX(w / 2 - 120).strength(.04)).force("y", d3.forceY(h / 2).strength(.05));
    linkSel = g.append("g").selectAll("path").data(show).join("path").attr("class", (e) => "mlink " + e.kind + ($("#mapTrace").checked && tpairs.has((e.source.id || e.source) + "→" + (e.target.id || e.target)) ? " trace" : "")).attr("stroke-width", (e) => Math.min(4, .8 + Math.log2(1 + e.weight))).attr("marker-end", (e) => e.kind === "calls" ? "url(#marr)" : null);
    nodeSel = g.append("g").selectAll("g").data(nodes).join("g").attr("class", "mnode").call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y; }).on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = d.fy = null; }));
    nodeSel.append("circle").attr("r", (d) => rad(d.lines)).attr("fill", color).attr("fill-opacity", .85);
    nodeSel.append("text").attr("x", (d) => rad(d.lines) + 5).attr("y", 4).text((d) => d.label);
    nodeSel.on("click", (e, d) => select(d)).on("mouseenter", (e, d) => focusN(d)).on("mouseleave", () => focusN(null));
    sim.on("tick", () => {
      linkSel.attr("d", (e) => { const dx = e.target.x - e.source.x, dy = e.target.y - e.source.y, dist = Math.hypot(dx, dy) || 1, r = rad(e.target.lines) + 3; const tx = e.target.x - dx / dist * r, ty = e.target.y - dy / dist * r; return `M${e.source.x},${e.source.y}Q${(e.source.x + tx) / 2 + dy * .12},${(e.source.y + ty) / 2 - dx * .12} ${tx},${ty}`; });
      nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });
  }
  function focusN(d) {
    if (!d) { nodeSel.classed("dimmed", false); linkSel.classed("dimmed", false); return; }
    const nb = new Set([d.id]); linkSel.each((e) => { if (e.source.id === d.id) nb.add(e.target.id); if (e.target.id === d.id) nb.add(e.source.id); });
    nodeSel.classed("dimmed", (n) => !nb.has(n.id)); linkSel.classed("dimmed", (e) => e.source.id !== d.id && e.target.id !== d.id);
  }
  function select(d) {
    nodeSel.classed("sel", (n) => n.id === d.id);
    const ins = all.filter((e) => (e.target.id || e.target) === d.id).map((e) => e.source.id || e.source), outs = all.filter((e) => (e.source.id || e.source) === d.id).map((e) => e.target.id || e.target);
    const ch = d.chapter ? chs[d.chapter - 1] : null;
    $("#mapSide").innerHTML = `<h4>${esc(d.id)}</h4><div class="muted" style="font-size:.85rem">${d.lines} lines · ${d.symbols} functions/classes</div>${d.summary ? `<p>${inline(d.summary)}</p>` : ""}
      ${outs.length ? `<div class="kicker" style="margin-top:12px">uses</div><div style="font-family:var(--mono);font-size:.8rem">${[...new Set(outs)].map((x) => esc(x.split("/").pop())).join(", ")}</div>` : ""}
      ${ins.length ? `<div class="kicker" style="margin-top:12px">used by</div><div style="font-family:var(--mono);font-size:.8rem">${[...new Set(ins)].map((x) => esc(x.split("/").pop())).join(", ")}</div>` : ""}
      <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">${ch ? `<button class="btn sm primary" id="mapGo">Go to chapter ${ch.num} →</button>` : ""}<a class="btn sm ghost" href="${esc(COURSE.repo.url)}/blob/${esc(COURSE.repo.sha)}/${esc(d.id)}" target="_blank" rel="noopener">GitHub ↗</a></div>`;
    if (ch) $("#mapGo").onclick = () => { $("#mapPanel").classList.add("hidden"); go(`/c/${SLUG}#ch${ch.num}`); };
  }
  $("#mapLegend").innerHTML = chs.filter((c) => c.kind === "module" || c.kind === "frontdoor").map((c) => `<span><span class="langdot" style="background:${palette[(c.num - 1) % palette.length]}"></span>Ch ${c.num}: ${inline(c.title)}</span>`).join("") + `<span><span class="langdot" style="background:#4b5175"></span>not covered</span><span style="color:#f472b6">━ call trace</span><span style="color:#22d3ee">→ calls</span><span style="color:#a78bfa">┄ imports</span>`;
  ["#mapCalls", "#mapImports", "#mapTrace"].forEach((s) => $(s).onchange = draw);
  draw();
}
$("#mapClose").onclick = () => $("#mapPanel").classList.add("hidden");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#mapPanel").classList.add("hidden"); closeChat(); } });

/* ---------- chat ---------- */
let HISTORY = [];
function openChat(prefill) {
  if (!COURSE) return;
  $("#chat").classList.add("open"); $("#chatTitle").textContent = `${COURSE.repo.owner}/${COURSE.repo.name}`;
  if (!$("#chatLog").children.length) {
    $("#chatLog").innerHTML = `<div class="msg bot"><p>Ask me anything about <b>${esc(COURSE.repo.name)}</b>. I search the real code first and cite <code>file:line</code> for every answer.${LLM ? "" : " <span class='dim'>(No language model is running, so I'll show the best-matching code instead of writing an answer.)</span>"}</p></div>`;
    const tr = COURSE.chapters.find((c) => c.kind === "trace"); const mods = COURSE.chapters.filter((c) => c.kind === "module");
    const sugg = [tr ? `What happens when I call ${tr.trace[0].caller}?` : null, mods[0] ? `What does ${mods[0].files[0].split("/").pop()} do?` : null, "Where are errors handled?", "How is this tested?"].filter(Boolean);
    $("#chatSuggest").innerHTML = sugg.map((s) => `<span class="chip">${esc(s)}</span>`).join("");
    $$("#chatSuggest .chip").forEach((c) => c.onclick = () => sendChat(c.textContent));
  }
  if (prefill) sendChat(prefill); else setTimeout(() => $("#chatInput").focus(), 300);
}
function closeChat() { $("#chat").classList.remove("open"); }
$("#chatClose").onclick = closeChat;
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#chatInput").value.trim(); if (q) sendChat(q); });
function renderAnswer(text, cites) {
  let html = md(text);
  html = html.replace(/\[([\w./@+\-]+\.\w+|README[\w.]*):(\d+)(?:-(\d+))?\]/g, (m, f, a, b) => {
    const url = `${COURSE.repo.url}/blob/${COURSE.repo.sha}/${f}#L${a}${b ? "-L" + b : ""}`;
    return `<a class="cite" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(f)} line ${a}${b ? "–" + b : ""}">${esc(f.split("/").pop())}:${a}</a>`;
  });
  return html;
}
let chatBusy = false;
function langOf(file) { return /\.tsx?$/.test(file) ? "typescript" : /\.[cm]?jsx?$/.test(file) ? "javascript" : "python"; }
function sourceCards(sources) {
  return `<div class="srcs"><span class="lbl">Found in the code</span>${sources.slice(0, 3).map((s, i) => `
    <details class="src-card"${i === 0 ? " open" : ""}><summary><span class="sc-t">${esc(s.title)}</span><a class="cite" href="${esc(s.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(s.file.split("/").pop())}:${s.start}</a></summary>
    ${s.rows ? codeTable(s.rows, langOf(s.file)) : ""}</details>`).join("")}
    ${sources.length > 3 ? `<div class="more">${sources.slice(3, 6).map((s) => `<a class="cite" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(s.file.split("/").pop())}:${s.start}</a>`).join("")}</div>` : ""}</div>`;
}
const secs = (ms) => (ms / 1000).toFixed(1) + "s";
async function sendChat(q) {
  if (chatBusy) return; chatBusy = true;
  $("#chatInput").value = ""; $("#chatSuggest").innerHTML = "";
  const log = $("#chatLog");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(q)}</div>`);
  const bot = document.createElement("div"); bot.className = "msg bot";
  bot.innerHTML = `<div class="ans"><span class="typing"><i></i><i></i><i></i></span> <span class="dim">searching the code…</span></div><div class="src-slot"></div><div class="meta"></div>`;
  log.appendChild(bot); log.scrollTop = log.scrollHeight;
  const ans = $(".ans", bot), slot = $(".src-slot", bot), meta = $(".meta", bot);
  let raw = "", sources = [];
  const t0 = performance.now();
  try {
    const r = await fetch(`/api/courses/${SLUG}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, history: HISTORY.slice(-4) }) });
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, idx); buf = buf.slice(idx + 2); if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "sources") {
          sources = ev.sources;
          slot.innerHTML = sources.length ? sourceCards(sources) : "";
          ans.innerHTML = `<span class="typing"><i></i><i></i><i></i></span> <span class="dim">${sources.length ? `found ${sources.length} matching pieces of code in ${secs(performance.now() - t0)}, ` : ""}${LLM ? "writing an answer…" : ""}</span>`;
        } else if (ev.type === "status") { ans.innerHTML = `<span class="typing"><i></i><i></i><i></i></span> <span class="dim">${esc(ev.text)}</span>`; }
        else if (ev.type === "token") { raw += ev.text; ans.innerHTML = md(raw) + `<span class="typing"><i></i><i></i><i></i></span>`; }
        else if (ev.type === "final") {
          raw = ev.text;
          ans.innerHTML = renderAnswer(ev.text, ev.citations); ans.classList.add("fin");
          const fixes = (ev.corrections || []).length;
          const bits = [ev.model ? "Written by " + esc(ev.model.replace("ollama:", "")) : "Search only (no model)",
            `${ev.citations.length} verified citation${ev.citations.length === 1 ? "" : "s"}`];
          if (ev.model) bits.push(`<span class="gc" title="${esc((ev.corrections || []).join("\n") || "Every caller/callee claim matched the static call graph")}">${fixes ? `⚑ graph-checked · ${fixes} claim${fixes > 1 ? "s" : ""} corrected` : "✓ graph-checked"}</span>`);
          if (ev.removed) bits.push(`${ev.removed} unverifiable citation${ev.removed > 1 ? "s" : ""} removed`);
          bits.push(ev.cached ? "⚡ cached" : ev.total_ms ? `first word ${secs(ev.first_token_ms || ev.total_ms)} · done ${secs(ev.total_ms)}` : secs(performance.now() - t0));
          meta.innerHTML = bits.join(" · ");
        }
        log.scrollTop = log.scrollHeight;
      }
    }
    HISTORY.push({ role: "user", content: q }, { role: "assistant", content: raw });
  } catch (e) { ans.innerHTML = `<span style="color:var(--red)">Something went wrong: ${esc(e.message)}</span>`; }
  chatBusy = false;
}

/* ---------- theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t; localStorage.setItem("repocademy:theme", t);
  const b = $("#themeBtn"); if (b) { b.textContent = t === "light" ? "☾" : "☀"; b.title = t === "light" ? "Switch to dark mode" : "Switch to light mode"; }
}
$("#themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
setTheme(document.documentElement.dataset.theme || "dark");

/* ---------- boot ---------- */
(async function boot() {
  try { const h = await api("/api/health"); LLM = h.llm; const p = $("#llmPill"); p.textContent = h.llm ? "● " + h.llm.replace("ollama:", "") : "templates only"; p.classList.toggle("on", !!h.llm); p.title = h.llm ? "Local / free model used for chat and narration" : "No model running; everything still works with templates"; } catch {}
  route();
})();
