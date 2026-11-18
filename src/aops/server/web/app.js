// aops console: every dbx command of the CLI as a screen, on the same /api/v1 the CLI calls.
// No build step and no external libraries. All text goes through textContent (no HTML injection).

const API = "/api/v1";
const state = { me: null, version: null, toApprove: 0, timers: new Set() };

// ── API ────────────────────────────────────────────────────────────────────

class ApiError extends Error {
  constructor(status, problem) {
    super(problem.title || `HTTP ${status}`);
    Object.assign(this, { status, ...problem });
  }
}

async function api(method, path, { json, form, blob } = {}) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (json !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    const raw = await resp.text();  // read once: a body that is not JSON is shown as text
    let problem;
    try { problem = JSON.parse(raw); } catch { problem = { title: raw.slice(0, 200) || `HTTP ${resp.status}` }; }
    throw new ApiError(resp.status, problem);
  }
  if (blob) return resp;
  const text = await resp.text();
  return text ? JSON.parse(text) : null;
}

const get = (p) => api("GET", p);
const post = (p, json) => api("POST", p, { json: json ?? {} });

// ── DOM helpers ────────────────────────────────────────────────────────────

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// replaceChildren without the "null" text a skipped part would leave
const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
const enc = encodeURIComponent;
const short = (sha) => (sha ? sha.slice(0, 12) : "");

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const two = (n) => String(n).padStart(2, "0");
  const today = new Date().toDateString() === d.toDateString();
  return `${today ? "오늘" : `${two(d.getMonth() + 1)}-${two(d.getDate())}`} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

function size(n) {
  if (n === null || n === undefined) return "";
  return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

const LABEL = {
  lifecycle: { registered: ["등록됨", ""], production: ["운영 중", "ok"], archived: ["보관", ""] },
  version: { registered: ["등록됨", ""], production: ["운영", "ok"], retired: ["이전 운영", "plain"] },
  validation: { queued: ["대기", "info run"], running: ["평가 중", "info run"], passed: ["통과", "ok"], failed: ["실패", "bad"], stale: ["무효", "warn"], error: ["오류", "bad"] },
  verdict: { pass: ["적합", "ok"], warn: ["주의", "warn"], fail: ["부적합", "bad"] },
  item: { pass: ["적합", "ok"], warn: ["주의", "warn"], fail: ["부적합", "bad"], na: ["해당 없음", "plain"], unchecked: ["답 없음", "bad"] },
  decision: { validating: ["평가 중", "info run"], pending_approval: ["승인 대기", "warn"], approved: ["승인됨", "ok"], rejected: ["반려", "bad"], canceled: ["취소", "plain"] },
  deployment: { running: ["배포 중", "info run"], succeeded: ["완료", "ok"], failed: ["실패", "bad"] },
  git: { synced: ["Git", "ok"], failed: ["Git 실패", "bad"], skipped: ["Git 건너뜀", "warn"] },
};
const BUILD = { skill: "스킬", code: "코드", no_code: "노코드" };
// One name and one mark per action, everywhere (screens, buttons, steps): the same words as the CLI commands
const ACT = {
  edit: ["✎", "개발"], selfcheck: ["✓", "셀프 체크"], register: ["↑", "등록"], evaluate: ["◆", "평가"],
  deploy: ["▶", "배포 요청"], approve: ["✔", "승인"], promote: ["⚑", "권한"], load: ["↓", "가져오기"],
};
const act = (key, extra = "") => `${ACT[key][0]} ${ACT[key][1]}${extra}`;
const kindTag = (kind) => h("span", { class: `kind k-${kind}` }, BUILD[kind] || kind);
const cli = (command) => h("span", { class: "cli", title: "같은 일을 하는 CLI 명령" }, command);
// One word for the last evaluation: a run that did not pass says so; otherwise its content review decides
function evalBadge(status, verdict) {
  if (!status) return h("span", { class: "muted" }, "–");
  if (["failed", "error", "stale"].includes(status) || !verdict) return badge("validation", status);
  return h("span", { class: `badge ${LABEL.verdict[verdict][1]}` }, { pass: "통과", warn: "주의 있음", fail: "부적합 있음" }[verdict]);
}
const UPGRADE = { initial: "첫 배포", major: "major", minor: "minor", patch: "patch", rollback: "되돌리기" };
const EVENT = {
  create: "만들기", register: "등록", validate: "검사(옛)", evaluate: "평가", gate_requested: "배포 요청", gate_approved: "승인", gate_rejected: "반려",
  gate_canceled: "취소", deploy: "운영 반영", rollback: "되돌리기", promote: "권한", load: "가져오기", git: "Git",
};
const MODE = { mandatory: "필수", optional: "선택", exempt: "면제", required: "사람 승인", auto: "자동 승인" };
const RANK = { fail: 0, unchecked: 1, warn: 2, pass: 3, na: 4 };  // the report lists problems first
const RECOMMEND = { approve: "승인해도 됨", changes: "고친 뒤 다시 요청", reject: "내보내지 말 것" };

function segment(options, value, set) {  // a row of buttons; one is on
  const box = h("div", { class: "seg" });
  options.forEach(([v, label]) => box.append(h("button", { type: "button", class: v === value ? "on" : "", onclick: (e) => {
    box.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); set(v);
  } }, label)));
  return box;
}

function badge(kind, value) {
  if (!value) return h("span", { class: "muted" }, "–");
  const [text, cls] = (LABEL[kind] || {})[value] || [value, ""];
  return h("span", { class: `badge ${cls}` }, text);
}

function toast(message, kind = "", detail = "") {
  const el = h("div", { class: `toast ${kind}` }, message, detail ? h("small", {}, detail) : null);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "bad" ? 9000 : 5000);
}

function fail(error) {
  if (error instanceof ApiError) {
    toast(error.title, "bad", [error.detail, error.command && `CLI: ${error.command}`, `HTTP ${error.status}`].filter(Boolean).join(" · "));
  } else {
    toast(String(error.message || error), "bad");
  }
}

function every(ms, fn) {
  let stopped = false;
  const timer = { stop: () => { stopped = true; state.timers.delete(timer); } };
  state.timers.add(timer);
  const loop = async () => {
    if (stopped) return;
    let again = true;
    try { again = (await fn()) !== false; } catch (e) { fail(e); again = false; }
    if (again && !stopped) setTimeout(loop, ms);
    else timer.stop();
  };
  loop();
  return timer;
}

function modal(title, body, buttons = [], { wide = false } = {}) {
  const close = () => { back.remove(); onClose(); };
  let onClose = () => {};
  const foot = h("footer", {}, buttons.map((b) => b instanceof Node ? b : h("button", { class: `btn ${b.cls || ""}`, onclick: () => b.run(close) }, b.label)));
  const bodyEl = h("div", { class: "body" }, body);
  const back = h("div", { class: "backdrop", onclick: (e) => { if (e.target === back) close(); } },
    h("div", { class: `modal ${wide ? "wide" : ""}` },
      h("header", {}, h("h2", {}, title), h("button", { class: "btn ghost", onclick: close, "aria-label": "닫기" }, "✕")),
      bodyEl,
      buttons.length ? foot : null));
  document.body.append(back);
  return { close, onClose: (fn) => { onClose = fn; }, footer: foot, body: bodyEl };
}

async function download(path, filename) {
  const resp = await api("GET", path, { blob: true });
  const url = URL.createObjectURL(await resp.blob());
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ── layout ─────────────────────────────────────────────────────────────────

const NAV = [
  ["작업", [["agents", "▦", "에이전트"], ["gates", "✔", "배포 요청함"]]],
  ["도구", [["register", "↑", "폴더·zip 등록"], ["genie", "◇", "Genie 점검"]]],
  ["관리", [["policy", "⚙", "정책·평가 프롬프트"]]],
  ["도움말", [["guide", "?", "CLI·Genie Code"]]],
];

function layout(active, crumbs, content) {
  const nav = h("nav", { class: "nav" },
    h("a", { href: "#/new", class: `new-btn ${active === "new" ? "active" : ""}` }, "+ 새 에이전트"),
    NAV.map(([group, items]) => [h("div", { class: "nav-group" }, group), items.map(([key, ico, label]) =>
      h("a", { href: `#/${key}`, class: active === key ? "active" : "" }, h("span", { class: "ico" }, ico), label,
        key === "gates" && state.toApprove ? h("span", { class: "count", title: "내가 승인할 요청" }, state.toApprove) : null))]));
  const me = state.me;
  const side = h("aside", { class: "side" },
    h("div", { class: "brand" }, h("div", { class: "logo" }, "ao"), h("div", {}, "aops", h("small", {}, "AgentOps console"))),
    nav,
    h("div", { class: "side-foot" },
      me ? [h("div", { class: "user" }, me.user), h("div", {}, me.roles.map((r) => ({ developer: "개발자", approver: "승인자", admin: "관리자" })[r]).join(" · "))] : null,
      state.version ? h("div", { style: "margin-top:6px" }, `aops ${state.version.aops} · ${state.version.edition}`) : null));
  const top = h("div", { class: "topbar" }, h("div", { class: "crumbs" }, crumbs), h("div", { class: "spacer" }),
    h("a", { class: "btn small ghost", href: `${API}/docs`, target: "_blank" }, "API 문서 ↗"));
  return h("div", { class: "shell" }, side, h("div", { class: "main" }, top, h("div", { class: "page" }, content)));
}

// Title, one line under it, the CLI command for the same thing, and the page's actions on the right
function pageHead(title, sub, actions = [], command = null) {
  return h("div", { class: "page-head" },
    h("div", { class: "title" }, h("h1", {}, title), sub || command ? h("div", { class: "sub" }, sub || "", command ? cli(command) : null) : null),
    h("div", { class: "actions" }, actions));
}

function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [path, query] = hash.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query || "");
  return { parts, params };
}

async function render() {
  for (const t of [...state.timers]) t.stop();
  document.querySelectorAll(".backdrop").forEach((b) => b.remove());
  const { parts, params } = route();
  const app = document.getElementById("app");
  const show = (active, crumbs, content) => app.replaceChildren(layout(active, crumbs, content));
  const body = h("div", {}, h("div", { class: "loading" }, h("span", { class: "spinner" }), " 불러오는 중…"));
  try {
    switch (parts[0] || "agents") {
      case "agents":
        if (parts[1]) { show("agents", [h("a", { href: "#/agents" }, "에이전트"), "/", h("b", {}, parts[1])], body); await agentPage(body, parts[1], params); }
        else { show("agents", [h("b", {}, "에이전트")], body); await agentsPage(body); }
        break;
      case "gates":
        if (parts[1]) { show("gates", [h("a", { href: "#/gates" }, "배포 요청함"), "/", h("b", { class: "mono" }, parts[1].slice(0, 12))], body); await gatePage(body, parts[1]); }
        else { show("gates", [h("b", {}, "배포 요청함")], body); await gatesPage(body, params); }
        break;
      case "register": show("register", [h("b", {}, "폴더·zip 등록")], body); registerPage(body, params); break;
      case "new": show("new", [h("b", {}, "새 에이전트")], body); newPage(body, params); break;
      case "genie": show("genie", [h("b", {}, "Genie 점검")], body); geniePage(body, params); break;
      case "policy": show("policy", [h("b", {}, "정책·평가 프롬프트")], body); await policyPage(body); break;
      case "guide": show("guide", [h("b", {}, "CLI·Genie Code")], body); await guidePage(body); break;
      default: location.hash = "#/agents";
    }
  } catch (error) {
    body.replaceChildren(h("div", { class: "card pad" }, h("div", { class: "empty" }, h("b", {}, error.title || "불러오지 못했습니다"),
      error.detail || error.message || "", error.command ? h("div", { class: "mt" }, h("code", {}, error.command)) : null)));
  }
}

async function refreshCounts() {
  try {
    const page = await get("/release-gates?to_approve=true");
    state.toApprove = page.items.filter((g) => g.decision === "pending_approval").length;
  } catch { state.toApprove = 0; }
}

// ── 에이전트 목록 (aops list) ────────────────────────────────────────────────

async function agentsPage(root) {
  const [page, mine] = await Promise.all([get("/agents"), get("/release-gates?mine=true").catch(() => ({ items: [] }))]);
  const items = page.items;
  let q = "", type = "", life = "";
  const table = h("div", {});
  const draw = () => {
    const rows = items.filter((a) => (!type || a.build_type === type) && (!life || (life === "fix" ? needsFix(a) : a.lifecycle === life)) &&
      (!q || `${a.agent_id} ${a.name} ${a.description || ""} ${a.owner}`.toLowerCase().includes(q)));
    table.replaceChildren(rows.length ? h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["에이전트", "종류", "운영", "최신", "마지막 평가", "진행 중", "담당"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map((a) => h("tr", { class: "click", onclick: () => { location.hash = `#/agents/${enc(a.agent_id)}`; } },
        h("td", {}, h("div", { class: "cell-main" }, a.name || a.agent_id),
          h("div", { class: "cell-sub" }, [a.name && a.name !== a.agent_id ? a.agent_id : null, a.description].filter(Boolean).join(" · "))),
        h("td", {}, kindTag(a.build_type)),
        h("td", {}, a.production_version ? h("span", { class: "badge ok" }, a.production_version) : h("span", { class: "muted" }, "–")),
        h("td", { class: "mono" }, a.latest_version || "–"),
        h("td", {}, evalBadge(a.last_validation, a.last_review)),
        h("td", {}, a.pending_gates ? h("span", { class: "badge warn" }, `${a.pending_gates}건`) : h("span", { class: "muted" }, "–")),
        h("td", {}, h("div", {}, a.owner), h("div", { class: "cell-sub" }, when(a.updated_at)))))))
      : h("div", { class: "empty" }, h("b", {}, items.length ? "조건에 맞는 에이전트가 없습니다" : "아직 에이전트가 없습니다"),
        items.length ? "" : h("a", { class: "btn primary mt", href: "#/new" }, "+ 새 에이전트")));
  };
  const mineOpen = mine.items.filter((g) => ["validating", "pending_approval"].includes(g.decision)).length;
  const toFix = items.filter(needsFix).length;
  const todo = (n, label, hint, href, cls) => h("a", { class: `todo ${n ? cls : "zero"}`, href }, h("div", { class: "n" }, n), h("div", {}, h("b", {}, label), h("div", { class: "muted" }, hint)));
  root.replaceChildren(
    pageHead("에이전트", "레지스트리에 있는 에이전트", [h("a", { class: "btn primary", href: "#/new" }, "+ 새 에이전트")], "aops list"),
    h("div", { class: "todos" },
      todo(state.toApprove, "승인할 요청", "내가 리포트를 보고 결정할 것", "#/gates?tab=approve", "warn"),
      todo(mineOpen, "진행 중인 내 요청", "평가 중이거나 승인을 기다림", "#/gates?tab=mine", "info"),
      todo(toFix, "고칠 에이전트", "마지막 평가가 실패했거나 부적합", "#/agents?filter=fix", "bad"),
      todo(items.filter((a) => a.production_version).length, "운영 중", `전체 ${items.length}개 중`, "#/agents?filter=production", "ok")),
    h("div", { class: "card mt" },
      h("div", { class: "toolbar", style: "padding:12px 14px 0" },
        h("input", { type: "search", placeholder: "이름·ID·설명·담당으로 찾기", oninput: (e) => { q = e.target.value.toLowerCase(); draw(); } }),
        segment([["", "모든 종류"], ["skill", "스킬"], ["code", "코드"], ["no_code", "노코드"]], type, (v) => { type = v; draw(); }),
        segment([["", "모든 상태"], ["production", "운영 중"], ["registered", "등록됨"], ["fix", "고칠 것"]], life, (v) => { life = v; draw(); })),
      table));
  const filter = route().params.get("filter");
  if (filter) {
    life = filter;
    root.querySelectorAll(".toolbar .seg")[1].querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.textContent === { production: "운영 중", fix: "고칠 것", registered: "등록됨" }[filter]));
  }
  draw();
}

const needsFix = (a) => ["failed", "error", "stale"].includes(a.last_validation) || a.last_review === "fail";

// ── 에이전트 상세 ────────────────────────────────────────────────────────────

async function agentPage(root, id, params) {
  const [agent, versions, gates] = await Promise.all([get(`/agents/${enc(id)}`), get(`/agents/${enc(id)}/versions`),
    get(`/release-gates?agent_id=${enc(id)}`).catch(() => ({ items: [] }))]);
  const latest = versions.items[0];
  const kind = agent.build_type;
  const noCode = kind === "no_code";
  const isOwner = state.me && (state.me.user === agent.owner || (agent.owner_group && state.me.groups.includes(agent.owner_group)));
  const [nc, ws, deploys] = await Promise.all([
    noCode ? get(`/no-code/agents/${enc(id)}`).catch(() => null) : null,
    noCode ? null : get(`/agents/${enc(id)}/workspace`).catch(() => null),
    kind === "code" && agent.production_version ? get(`/agents/${enc(id)}/deployments`).catch(() => ({ items: [] })) : null]);
  const appUrl = deploys ? (deploys.items.find((d) => d.status === "succeeded" && d.app_url) || {}).app_url || null : null;
  const openGate = gates.items.find((g) => ["validating", "pending_approval"].includes(g.decision));
  const lastGate = gates.items[0];
  const link = (url, text) => url ? h("a", { href: url, target: "_blank" }, `${text} ↗`) : h("span", { class: "muted" }, "–");
  const only = isOwner ? "" : "담당자·담당 팀만";

  // the lifecycle at a glance: where this agent is, and the one action of each step
  const stepBtn = (key, onclick, disabled, title) => h("button", { class: "btn small", disabled: !!disabled, title: title || "", onclick }, act(key));
  const evalState = !agent.last_validation ? "wait" : agent.last_review === "fail" || ["failed", "error", "stale"].includes(agent.last_validation) ? "bad"
    : agent.last_review === "warn" ? "warn" : agent.last_validation === "passed" ? "done" : "run";
  const steps = [
    { key: "edit", state: "done", title: "개발", text: noCode ? "개발용 Genie" : ws ? "워크스페이스 폴더 (Genie Code)" : "내 PC 폴더",
      act: noCode ? link(nc && nc.dev_url, "Genie에서 열기") : ws ? [link(ws.folder_url, "폴더"), " ", link(ws.open_url, "편집기")] : null },
    { key: "selfcheck", state: "info", title: "셀프 체크", text: "언제든 · 기록 안 함",
      act: stepBtn("selfcheck", () => openSelfCheck(id, noCode ? {} : ws ? { workspace_path: ws.workspace_path } : { version: latest && latest.version }),
        noCode ? !nc || !nc.dev_space_id || !isOwner : !ws && !latest) },
    { key: "register", state: noCode ? "na" : latest ? "done" : "wait", title: "등록",
      text: noCode ? "배포가 성공할 때 버전이 생김" : latest ? `최신 ${latest.version} · ${when(latest.registered_at || latest.created_at)}` : "아직 버전 없음",
      act: noCode ? null : h("a", { class: "btn small", href: `#/register?agent=${enc(id)}${ws ? `&path=${enc(ws.workspace_path)}` : ""}` }, act("register")) },
    { key: "evaluate", state: evalState, title: "평가",
      text: agent.last_validation ? evalBadge(agent.last_validation, agent.last_review) : "배포 요청 때 돎 (미리 돌려도 됨)",
      act: stepBtn("evaluate", () => openEvaluate(id, noCode ? null : latest && latest.version), noCode ? !nc || !nc.dev_space_id || !isOwner : !latest || !isOwner, only) },
    { key: "approve", state: openGate ? (openGate.decision === "pending_approval" ? "warn" : "run") : lastGate && lastGate.decision === "rejected" ? "bad" : lastGate ? "done" : "wait",
      title: "승인", text: openGate ? [badge("decision", openGate.decision), ` ${openGate.version}`] : lastGate ? [badge("decision", lastGate.decision), ` ${lastGate.version}`]
        : agent.approvers.length ? `승인자 ${agent.approvers.join(", ")}` : "승인자: 정책의 승인 그룹",
      act: openGate || lastGate ? h("a", { class: "btn small", href: `#/gates/${enc((openGate || lastGate).gate_id)}` }, "리포트·승인") : null },
    { key: "deploy", state: agent.production_version ? "done" : "wait", title: "운영",
      text: agent.production_version ? `운영 ${agent.production_version}` : "아직 운영 버전 없음",
      act: kind === "code" ? link(appUrl, "운영 앱") : noCode ? link(nc && nc.prod_url, "운영용 Genie") : agent.production_version ? h("span", { class: "muted" }, "UC Skill") : null },
  ];
  const stepper = h("ol", { class: "lifecycle" }, steps.map((st, n) => h("li", { class: `st ${st.state}` },
    h("div", { class: "dot" }, st.state === "done" ? "✓" : st.state === "bad" ? "!" : n + 1),
    h("div", { class: "body" }, h("div", { class: "t" }, st.title), h("div", { class: "s" }, st.text), st.act ? h("div", { class: "a" }, st.act) : null))));

  const info = h("div", { class: "card pad" },
    h("dl", { class: "kv two-col" },
      h("dt", {}, "담당"), h("dd", {}, agent.owner, agent.owner_group ? h("span", { class: "muted" }, ` · ${agent.owner_group}`) : null),
      h("dt", {}, "지정 승인자"), h("dd", {}, agent.approvers.length ? agent.approvers.join(", ") : h("span", { class: "muted" }, "없음 (정책의 승인 그룹)")),
      h("dt", {}, "중요도 · 민감도"), h("dd", {}, `${agent.service_criticality} · ${agent.data_sensitivity}`),
      h("dt", {}, "보안 등급"), h("dd", {}, agent.security_level),
      noCode ? [
        h("dt", {}, "에이전트 폴더"), h("dd", {}, nc && nc.folder_url ? link(nc.folder_url, nc.folder_path) : (nc && nc.folder_path) || "–"),
        h("dt", {}, "공개 그룹"), h("dd", {}, (nc && nc.consumer_group) || h("span", { class: "muted" }, "없음 (SPEC.md consumer_group)"))]
        : [h("dt", {}, "작업 폴더"), h("dd", {}, ws ? (ws.folder_url ? link(ws.folder_url, ws.workspace_path) : h("span", { class: "mono" }, ws.workspace_path)) : h("span", { class: "muted" }, "PC (폴더·zip으로 등록)"))],
      h("dt", {}, "내 권한"), h("dd", {}, isOwner ? `담당자 (개발·${noCode ? "" : "등록·"}평가·배포 요청·권한)` : "보기 · 운영 버전 가져오기")));

  const tabs = [["versions", "버전", versions.items.length], ["checks", "평가"], ["gates", "배포 요청", gates.items.length], ["deploys", "배포"], ["events", "이력"]];
  let tab = params.get("tab") || "versions";
  const pane = h("div", {});
  const tabBar = h("div", { class: "tabs" });
  const drawTabs = () => tabBar.replaceChildren(...tabs.map(([key, label, n]) => h("button", { class: key === tab ? "on" : "", onclick: () => { tab = key; drawTabs(); loadTab(); } },
    label, n !== undefined ? h("span", { class: "n" }, n) : null)));
  const loadTab = async () => {
    pane.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" })));
    try {
      if (tab === "versions") pane.replaceChildren(versionsTab(agent, versions.items));
      if (tab === "checks") pane.replaceChildren(checksTab(await get(`/agents/${enc(id)}/evaluations`), id));
      if (tab === "gates") pane.replaceChildren(gatesTable(await get(`/release-gates?agent_id=${enc(id)}`), { agent: false }));
      if (tab === "deploys") pane.replaceChildren(deploysTab(await get(`/agents/${enc(id)}/deployments`)));
      if (tab === "events") pane.replaceChildren(eventsTab(await get(`/agents/${enc(id)}/events`)));
    } catch (e) { pane.replaceChildren(h("div", { class: "note bad" }, e.title || String(e))); }
  };
  root.replaceChildren(
    h("div", { class: "page-head" },
      h("div", { class: "title" }, h("div", { class: "row" }, h("h1", {}, agent.name || agent.agent_id), kindTag(kind), badge("lifecycle", agent.lifecycle)),
        h("div", { class: "sub" }, [agent.name && agent.name !== agent.agent_id ? agent.agent_id : null, agent.description].filter(Boolean).join(" · "))),
      h("div", { class: "actions" },
        h("button", { class: "btn", disabled: noCode ? !agent.production_version : !latest, onclick: () => openLoad(agent) }, act("load")),
        h("button", { class: "btn", disabled: !agent.production_version || !isOwner, title: only, onclick: () => openPromote(agent) }, act("promote")),
        h("button", { class: "btn primary", disabled: !isOwner || (!noCode && !latest), title: only || (!noCode && !latest ? "먼저 등록하세요" : ""),
          onclick: () => openDeploy(id, versions.items, agent.production_version, null, kind) }, act("deploy")))),
    h("div", { class: "card pad" }, stepper),
    h("div", { class: "mt" }, info),
    h("div", { class: "card pad mt" }, tabBar, pane));
  drawTabs();
  loadTab();
}

function versionsTab(agent, versions) {
  const noCode = agent.build_type === "no_code";
  if (!versions.length) return h("div", { class: "empty" }, h("b", {}, "버전이 없습니다"),
    noCode ? "노코드는 배포가 성공할 때 버전이 생깁니다 (처음 1.0.0, 데이터 소스가 바뀌면 major, 그 밖은 minor)." : "");
  const prodIndex = versions.findIndex((v) => v.status === "production");
  return h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["버전", "상태", "사유", "등록", "크기·해시", "Git", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, versions.map((v, i) => h("tr", {},
      h("td", {}, h("div", { class: "cell-main mono" }, v.version), h("div", { class: "cell-sub" }, v.harness ? `기본 하네스 ${v.harness}` : "")),
      h("td", {}, badge("version", v.status)),
      h("td", { style: "max-width:280px" }, v.note || h("span", { class: "muted" }, "–")),
      h("td", {}, h("div", {}, v.registered_by || ""), h("div", { class: "cell-sub" }, when(v.registered_at || v.created_at))),
      h("td", {}, h("div", {}, size(v.size_bytes)), h("div", { class: "cell-sub mono" }, short(v.source_sha256))),
      h("td", {}, v.git_url ? h("a", { href: v.git_url, target: "_blank" }, `v${v.version} ↗`) : badge("git", v.git_status)),
      h("td", { class: "num" }, h("div", { class: "row", style: "justify-content:flex-end" },
        h("button", { class: "btn ghost small", onclick: () => openVersion(agent.agent_id, v.version) }, "자세히"),
        noCode ? null : h("button", { class: "btn ghost small", onclick: () => openEvaluate(agent.agent_id, v.version) }, act("evaluate")),
        v.status !== "production" ? h("button", { class: "btn small", onclick: () => openDeploy(agent.agent_id, versions, agent.production_version, v.version, agent.build_type) },
          prodIndex >= 0 && i > prodIndex ? "↺ 되돌리기" : act("deploy")) : null))))));
}

async function openVersion(id, version) {
  const m = modal(`${id} ${version}`, h("div", { class: "loading" }, h("span", { class: "spinner" })), [], { wide: true });
  try {
    const v = await get(`/agents/${enc(id)}/versions/${enc(version)}`);
    m.body.replaceChildren(
      h("dl", { class: "kv" },
        h("dt", {}, "상태"), h("dd", {}, badge("version", v.status)),
        h("dt", {}, "등록"), h("dd", {}, `${v.registered_by || ""} · ${when(v.registered_at || v.created_at)}`),
        h("dt", {}, "버전 zip"), h("dd", { class: "mono" }, v.artifact_path || ""),
        h("dt", {}, "파일 해시"), h("dd", { class: "mono" }, v.source_sha256 || ""),
        h("dt", {}, "스킬 해시"), h("dd", { class: "mono" }, v.skills_sha256 || ""),
        h("dt", {}, "Git"), h("dd", {}, v.git && v.git.url ? h("a", { href: v.git.url, target: "_blank" }, v.git.url) : v.git ? `${v.git.status}: ${v.git.error || ""}` : "–")),
      h("h2", { class: "mt" }, "스킬"),
      v.skills.length ? h("table", { class: "data" }, h("thead", {}, h("tr", {}, ["스킬", "UC Skill", "해시"].map((t) => h("th", {}, t)))),
        h("tbody", {}, v.skills.map((s) => h("tr", {}, h("td", { class: "cell-main" }, s.skill_alias), h("td", { class: "mono" }, s.uc_name || "–"),
          h("td", { class: "mono muted" }, short(s.skill_sha256)))))) : h("p", { class: "muted" }, "스킬이 없습니다"),
      h("h2", { class: "mt" }, "SPEC.md"),
      h("dl", { class: "kv" }, Object.entries(v.spec || {}).flatMap(([k, val]) => [h("dt", {}, k), h("dd", {}, typeof val === "object" ? JSON.stringify(val) : String(val))])),
      h("div", { class: "row mt" },
        h("button", { class: "btn", onclick: () => download(`/agents/${enc(id)}/versions/${enc(version)}/archive`, `${id}-${version}.zip`).catch(fail) }, "버전 zip 받기")));
  } catch (e) { m.close(); fail(e); }
}

function checksTab(page, id) {
  if (!page.items.length) return h("div", { class: "empty" }, h("b", {}, "평가 기록이 없습니다"), "배포를 요청하면 평가(Gate)가 먼저 돕니다. [평가]로 따로 돌릴 수도 있습니다. 셀프 체크는 기록하지 않습니다.");
  return h("div", {}, page.items.map((r) => h("div", { class: "card pad", style: "box-shadow:none" },
    h("div", { class: "row" }, h("b", { class: "mono" }, r.version), badge("validation", r.status), r.review ? badge("verdict", r.review.verdict) : null,
      h("span", { class: "muted" }, `정책 v${r.policy_version}`), h("span", { class: "muted right" }, when(r.started_at)),
      h("button", { class: "btn ghost small", onclick: () => openRun(id, r.validation_run_id) }, "리포트")),
    r.steps.length ? h("ul", { class: "steps mt" }, r.steps.map(stepItem)) : null,
    r.failure_reason ? h("div", { class: "note bad mt" }, r.failure_reason) : null)));
}

function stepItem(step) {
  const ok = step.status === "passed";
  const cls = ok ? "ok" : step.status === "failed" ? "bad" : step.status === "warned" ? "warnm" : step.status === "running" ? "run" : "wait";
  const missed = (step.rules || []).filter((r) => !r.passed);
  return h("li", {}, h("span", { class: `mark ${cls}` }, ok ? "✓" : step.status === "failed" ? "✕" : step.status === "warned" ? "!" : ""),
    h("div", {}, h("div", { class: "name" }, STEP_TITLE[step.name] || step.name, " ", h("span", { class: "mono muted" }, step.name),
      step.advisory ? h("span", { class: "tag" }, "승인자 판단") : null), step.detail ? h("div", { class: "detail" }, step.detail) : null,
      missed.length ? h("ul", { class: "rules" }, missed.map((r) => h("li", {}, h("span", { class: `badge ${r.level === "ERROR" ? "bad" : "warn"} plain` }, r.level), " ",
        h("b", { class: "mono" }, r.id), ` ${r.message}`, h("div", { class: "muted" }, `고치는 곳: ${r.fix}`)))) : null));
}

const STEP_TITLE = { format: "SPEC.md", config: "aops.toml", instructions: "지시", skills: "스킬", evals: "평가셋", project: "Agent Bricks 프로젝트",
  definition: "Genie 정의 규칙", secrets: "비밀값·금지 파일", review: "내용 검토", evaluate: "품질 평가", integrity: "무결성", record: "기록" };

// The self-check as a checklist: every rule of every step, the ones to fix first with where to fix them.
function checklist(steps) {
  const rules = steps.flatMap((s) => s.rules || []);
  const errors = rules.filter((r) => !r.passed && r.level === "ERROR").length;
  const warns = rules.filter((r) => !r.passed && r.level !== "ERROR").length;
  const mark = (r) => r.passed ? h("span", { class: "rmark ok" }, "✓") : h("span", { class: `rmark ${r.level === "ERROR" ? "bad" : "warn"}` }, r.level === "ERROR" ? "✕" : "!");
  return h("div", {},
    h("div", { class: "row" }, h("span", { class: "badge ok plain" }, `통과 ${rules.length - errors - warns}`),
      h("span", { class: `badge ${errors ? "bad" : "plain"} plain` }, `ERROR ${errors}`), h("span", { class: `badge ${warns ? "warn" : "plain"} plain` }, `WARN ${warns}`),
      h("span", { class: "muted" }, "ERROR는 배포 전 평가가 반려합니다. WARN은 막지 않습니다.")),
    steps.map((s) => h("div", { class: "check-step" },
      h("div", { class: "row" }, h("span", { class: `mark-s ${s.status === "failed" ? "bad" : "ok"}` }, s.status === "failed" ? "✕" : "✓"),
        h("b", {}, STEP_TITLE[s.name] || s.name), h("span", { class: "mono muted" }, s.name), s.score != null ? h("span", { class: "muted" }, `준수율 ${Math.round(s.score * 100)}%`) : null),
      (s.rules || []).length ? h("ul", { class: "check-rules" }, [...s.rules].sort((a, b) => a.passed - b.passed).map((r) => h("li", { class: r.passed ? "passed" : "" },
        mark(r), h("div", {}, h("span", { class: "mono" }, r.id), " ", r.message, r.passed ? null : h("div", { class: "muted" }, `고치는 곳: ${r.fix}`)))))
        : h("div", { class: "detail muted" }, s.detail || ""))));
}

function deploysTab(page) {
  if (!page.items.length) return h("div", { class: "empty" }, h("b", {}, "배포 기록이 없습니다"));
  return h("table", { class: "data" }, h("thead", {}, h("tr", {}, ["버전", "결과", "대상", "시작", "끝"].map((t) => h("th", {}, t)))),
    h("tbody", {}, page.items.map((d) => h("tr", {},
      h("td", { class: "mono cell-main" }, d.version), h("td", {}, badge("deployment", d.status), d.error ? h("div", { class: "cell-sub" }, d.error) : null),
      h("td", { class: "mono", style: "max-width:380px" }, d.target || "–"), h("td", { class: "muted" }, when(d.started_at)), h("td", { class: "muted" }, when(d.ended_at))))));
}

function eventsTab(page) {
  if (!page.items.length) return h("div", { class: "empty" }, h("b", {}, "기록이 없습니다"));
  const describe = (e) => {
    const d = e.detail || {};
    if (e.event_type === "git") return `${d.action === "production" ? "production 브랜치" : "커밋·태그"} ${d.status || ""}${d.error ? ` · ${d.error}` : ""}`;
    if (e.event_type === "promote") return `${d.revoke ? "회수" : "부여"} ${(d.principals || []).join(", ")}`;
    if (e.event_type === "gate_rejected") return d.reason || "";
    if (e.event_type === "deploy" || e.event_type === "rollback") return d.previous ? `이전 ${d.previous}` : "첫 운영";
    if (e.event_type === "validate") return d.status || "";
    if (e.event_type === "gate_approved" && d.exception) return "개발 예외 승인 (정책 dev_approvers)";
    return "";
  };
  return h("ul", { class: "timeline" }, page.items.map((e) => h("li", {},
    h("span", { class: "when" }, when(e.at)), h("span", {}, h("span", { class: "tag" }, EVENT[e.event_type] || e.event_type), h("span", { class: "mono" }, e.version || "")),
    h("span", {}, h("span", {}, e.actor), h("span", { class: "muted" }, describe(e) ? ` · ${describe(e)}` : "")))));
}

// ── 셀프 체크 (aops validate) · 평가 (aops evaluate) ─────────────────────────

function resultsTable(results) {
  if (!results || !results.length) return null;
  return h("table", { class: "data mt" }, h("thead", {}, h("tr", {}, ["판정", "문항", "이유", "정답 · 답"].map((t) => h("th", {}, t)))),
    h("tbody", {}, results.map((r) => h("tr", {},
      h("td", {}, h("span", { class: `badge ${r.assessment === "GOOD" ? "ok" : r.assessment === "BAD" ? "bad" : "warn"}` }, r.assessment || "–")),
      h("td", { style: "max-width:260px" }, h("div", { class: "cell-main" }, r.question || r.question_id), h("div", { class: "cell-sub mono" }, r.question_id)),
      h("td", { class: "muted", style: "max-width:260px" }, (r.reasons || []).join(", ") || "–"),
      h("td", { style: "max-width:380px" }, h("div", { class: "cell-sub" }, `정답: ${(r.expected || "–").slice(0, 160)}`),
        h("div", { class: "cell-sub mono" }, `답: ${(r.generated || "–").slice(0, 220)}`))))));
}

async function openSelfCheck(id, fields) {
  const m = modal(`${act("selfcheck")}: ${id}`, h("div", { class: "loading" }, h("span", { class: "spinner" }), " 점검 중…"), [], { wide: true });
  const form = new FormData();
  Object.entries(fields || {}).forEach(([k, v]) => v && form.append(k, v));
  try {
    const r = await api("POST", `/projects/${enc(id)}/validations`, { form });
    m.body.replaceChildren(
      h("div", { class: "row" }, h("b", {}, r.source), badge("validation", r.status)),
      h("div", { class: "mt" }, checklist(r.steps)));
  } catch (e) { m.close(); fail(e); }
}

function openEvaluate(id, version) {
  const list = h("ul", { class: "steps" }, h("li", {}, h("span", { class: "mark run" }), h("div", {}, h("div", { class: "name" }, "평가 요청 중…"))));
  const status = h("div", { class: "row" }, h("b", { class: "mono" }, `${id} ${version || "(지금 개발용 정의)"}`));
  const results = h("div", {});
  const m = modal(`${act("evaluate")}: ${id}`, h("div", {}, status, list, results), [{ label: "닫기", run: (close) => close() }], { wide: true });
  let finished = false;
  post(`/projects/${enc(id)}/evaluations`, { version }).then((run) => {
    const timer = every(4000, async () => {
      const r = await get(`/evaluations/${enc(run.validation_run_id)}`);
      const done = ["passed", "failed", "stale", "error"].includes(r.status);
      const verdict = r.review ? r.review.verdict : null;
      fill(status, h("b", { class: "mono" }, `${id} ${r.version}`), done ? evalBadge(r.status, verdict) : badge("validation", r.status),
        h("span", { class: "muted" }, `정책 v${r.policy_version}`), done ? null : h("span", { class: "spinner" }));
      list.replaceChildren(...(r.steps.length ? r.steps.map(stepItem) : [h("li", {}, h("span", { class: "mark run" }), h("div", {}, h("div", { class: "name" }, "평가 Job 실행 중…"),
        h("div", { class: "detail" }, "보통 2~3분")))]));
      fill(results, r.failure_reason && r.status === "error" ? h("div", { class: "note bad mt" }, r.failure_reason) : null,
        done ? h("div", { class: "mt" }, reportView(r)) : null);
      if (done && !finished) {
        finished = true;
        const word = ["failed", "error", "stale"].includes(r.status) || !verdict ? (LABEL.validation[r.status] || [r.status])[0] : { pass: "통과", warn: "주의 있음", fail: "부적합 있음" }[verdict];
        toast(`평가 끝: ${id} ${r.version} · ${word}`, verdict === "pass" && r.status === "passed" ? "ok" : "bad", "아래 리포트 · 닫으면 에이전트 화면이 바뀝니다");
      }
      return !done;
    });
    m.onClose(() => { timer.stop(); if (finished && location.hash.startsWith(`#/agents/${enc(id)}`)) render(); });
  }).catch((e) => { m.close(); fail(e); });
}

async function openRun(id, runId) {
  try {
    const r = await get(`/evaluations/${enc(runId)}`);
    modal(`평가 리포트 ${id} ${r.version}`, h("div", {}, h("div", { class: "row" }, badge("validation", r.status), h("span", { class: "muted" }, `정책 v${r.policy_version} · ${when(r.started_at)}`)),
      r.failure_reason ? h("div", { class: "note bad mt" }, r.failure_reason) : null, reportView(r)), [], { wide: true });
  } catch (e) { fail(e); }
}

// The approver's report: the content review checklist with reasons and evidence, the quality evaluation, the form checks.
function reportView(run) {
  const rv = run.review;
  const form = run.steps.filter((s) => !["review", "evaluate", "integrity", "record"].includes(s.name));
  const quality = run.steps.find((s) => s.name === "evaluate");
  const rest = run.steps.filter((s) => ["integrity", "record"].includes(s.name));
  const cov = rv ? rv.coverage : null;
  return h("div", { class: "report" },
    rv ? h("div", { class: `verdict v-${rv.verdict}` },
      h("div", { class: "row" }, h("span", { class: "big" }, { pass: "✓", warn: "!", fail: "✕" }[rv.verdict]),
        h("div", {}, h("div", { class: "vt" }, `내용 검토 ${LABEL.verdict[rv.verdict][0]}`, h("span", { class: "muted" }, ` · 검토 모델의 권고: ${RECOMMEND[rv.recommendation] || rv.recommendation}`)),
          h("div", { class: "muted" }, `항목 ${rv.items.length}개 · 부적합 ${rv.items.filter((i) => i.status === "fail").length} · 주의 ${rv.items.filter((i) => i.status === "warn").length}`
            + ` · 파일 ${cov.files_read}/${cov.text_files} 읽음`))),
      h("p", { class: "mt-s" }, rv.summary), h("div", { class: "opinion" }, h("b", {}, "의견 "), rv.opinion))
      : h("div", { class: "note warn" }, run.status === "error" ? "평가가 끝나지 못해 리포트가 없습니다" : "내용 검토 리포트가 없습니다 (형식 검사가 실패했거나 이전 버전의 평가)"),
    rv ? [h("h2", { class: "mt" }, "체크리스트 (내용 검토)"),
      h("table", { class: "data report-items" }, h("thead", {}, h("tr", {}, ["판정", "항목", "사유", "근거"].map((t) => h("th", {}, t)))),
        h("tbody", {}, [...rv.items].sort((a, b) => RANK[a.status] - RANK[b.status]).map((i) => h("tr", { class: `st-${i.status}` },
          h("td", {}, badge("item", i.status)),
          h("td", { style: "max-width:240px" }, h("div", { class: "cell-main" }, i.title), h("div", { class: "cell-sub mono" }, i.id)),
          h("td", { style: "max-width:360px" }, i.reason || "–"),
          h("td", { style: "max-width:360px" }, i.findings.length ? i.findings.map((f) => h("div", { class: "finding" },
            h("span", { class: "mono" }, f.line ? `${f.file}:${f.line}` : f.file), f.issue ? ` ${f.issue}` : "",
            f.excerpt ? h("div", { class: "excerpt mono" }, f.excerpt) : null)) : h("span", { class: "muted" }, "–")))))),
      h("div", { class: "muted mt-s" }, `검토 범위: 텍스트 파일 ${cov.files_read}/${cov.text_files}, 줄 ${cov.lines_read}/${cov.lines_total}`
        + (cov.unread.length ? ` · 안 읽음 ${cov.unread.join(", ")}` : "") + (cov.partial.length ? ` · 일부만 ${cov.partial.join(", ")}` : "")
        + (cov.binary.length ? ` · 텍스트 아님 ${cov.binary.length}개` : "")
        + ` · 프롬프트 ${Object.entries(rv.prompts).map(([k, v]) => `${{ common: "공통", skill: "스킬", code: "코드", no_code: "노코드" }[k] || k} v${v}`).join(", ")}`
        + ` · 모델 ${rv.model} · ${rv.seconds}초`)] : null,
    h("h2", { class: "mt" }, "품질 평가"),
    quality ? h("ul", { class: "steps" }, stepItem(quality)) : h("p", { class: "muted" }, "없음"),
    resultsTable(run.results),
    h("details", { class: "mt" }, h("summary", {}, `형식 검사 (셀프 체크 규칙) · ${form.every((s) => s.status !== "failed") ? "통과" : "실패"}`),
      h("div", { class: "mt-s" }, checklist(form))),
    rest.length ? h("ul", { class: "steps mt" }, rest.map(stepItem)) : null);
}

// ── 배포 (aops deploy) ──────────────────────────────────────────────────────

function openDeploy(id, versions, production, preset, kind) {
  if (kind === "no_code" && !preset) return openNoCodeDeploy(id, production);
  const select = h("select", {}, versions.map((v) => h("option", { value: v.version, selected: v.version === (preset || versions[0].version) },
    `${v.version}${v.status === "production" ? " (운영)" : ""}`)));
  const reason = h("input", { type: "text", placeholder: "선택: 요청 사유 (예: 할인 규정 보강)" });
  const noteOf = (v) => (versions.find((x) => x.version === v) || {}).note || "";
  let typed = false;
  reason.value = noteOf(select.value);
  reason.addEventListener("input", () => { typed = true; });
  select.addEventListener("change", () => { if (!typed) reason.value = noteOf(select.value); });
  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "배포할 버전"), select, h("small", {}, production ? `지금 운영 버전 ${production}. 더 낮은 버전을 고르면 되돌리기입니다.` : "운영 버전이 없습니다 (첫 배포)")),
    h("label", { class: "field" }, h("span", {}, "사유"), reason));
  modal(act("deploy"), body, [
    { label: "닫기", run: (close) => close() },
    { label: act("deploy"), cls: "primary", run: (close) => { close(); followDeploy(id, select.value, reason.value || null, kind); } }]);
}

function openNoCodeDeploy(id, production) {
  const reason = h("input", { type: "text", placeholder: "선택: 요청 사유 (예: 벤치마크 문항 보강)" });
  modal(`${act("deploy")} (노코드)`, h("div", {},
    h("p", {}, "지금 개발용 Genie 정의를 스냅샷으로 평가합니다"),
    h("label", { class: "field" }, h("span", {}, "사유"), reason),
    h("div", { class: "note warn" }, "평가가 끝날 때까지 개발용 Genie를 고치지 마세요"),
    h("div", { class: "note mt" }, production ? `지금 운영 ${production}` : "첫 배포 (1.0.0)")), [
    { label: "닫기", run: (close) => close() },
    { label: act("deploy"), cls: "primary", run: (close) => { close(); followDeploy(id, null, reason.value || null, "no_code"); } }]);
}

function followDeploy(id, version, reason, kind) {
  const head = h("div", { class: "row" }, h("b", { class: "mono" }, `${id} ${version || "(스냅샷)"}`), h("span", { class: "spinner" }));
  const list = h("ul", { class: "steps mt" });
  const outcome = h("div", {});
  let gateId = null;
  const cancelBtn = h("button", { class: "btn danger", disabled: true, onclick: async () => {
    try { await post(`/release-gates/${enc(gateId)}/cancel`); toast("배포 요청을 취소했습니다", "ok"); } catch (e) { fail(e); }
  } }, "요청 취소");
  const m = modal("배포 진행", h("div", {}, head, list, outcome), [cancelBtn, h("button", { class: "btn", onclick: () => m.close() }, "닫기")], { wide: true });
  const item = (cls, name, detail) => h("li", {}, h("span", { class: `mark ${cls}` }, cls === "ok" ? "✓" : cls === "bad" ? "✕" : ""),
    h("div", {}, h("div", { class: "name" }, name), detail ? h("div", { class: "detail" }, detail) : null));
  post(`/projects/${enc(id)}/deploy-requests`, { version, reason }).then((gate) => {
    gateId = gate.gate_id;
    const timer = every(3000, async () => {
      const g = await get(`/release-gates/${enc(gateId)}`);
      const steps = g.evaluation ? g.evaluation.steps : [];
      const open = ["validating", "pending_approval"].includes(g.decision);
      const personDecides = g.decision === "pending_approval" && (g.approval_mode !== "auto" || !!g.decision_reason);
      cancelBtn.disabled = !open;
      fill(head, h("b", { class: "mono" }, `${id} ${g.version}`), badge("decision", g.decision), g.deployment_status ? badge("deployment", g.deployment_status) : null,
        h("span", { class: "muted" }, `${UPGRADE[g.upgrade_type] || g.upgrade_type} · 평가 ${MODE[g.validation_policy_mode]} · 승인 ${MODE[g.approval_mode] || g.approval_mode}`),
        (open && !personDecides) || g.deployment_status === "running" ? h("span", { class: "spinner" }) : null);
      const rows = [item("ok", "배포 요청", `gate ${g.gate_id} · 요청 ${g.requester}${kind === "no_code" && !version ? ` · 제안 버전 ${g.version} (배포가 성공하면 매김)` : ""}`)];
      if (g.decision === "validating") rows.push(item("run", "평가 중", "형식 → 내용 검토 → 품질 (보통 2~3분)"));
      else if (g.evaluation) {
        const verdict = g.evaluation.review ? g.evaluation.review.verdict : null;
        const word = g.evaluation.status !== "passed" || !verdict ? LABEL.validation[g.evaluation.status]?.[0] || g.evaluation.status : { pass: "통과", warn: "주의 있음", fail: "부적합 있음" }[verdict];
        rows.push(item(g.evaluation.status === "passed" && verdict !== "fail" ? "ok" : "bad", `평가 ${word}`,
          steps.map((s) => `${s.status === "passed" ? "✓" : s.status === "skipped" ? "–" : s.status === "warned" ? "!" : "✗"} ${s.name}`).join("  ")));
      }
      else if (g.validation_policy_mode === "exempt") rows.push(item("ok", "평가 면제", "정책"));
      if (g.decision === "pending_approval") rows.push(item(personDecides ? "wait" : "run", personDecides ? "승인자 필요" : "정책 자동 승인 중", g.decision_reason || "승인자가 배포 요청함에서 승인합니다"));
      if (["approved"].includes(g.decision)) rows.push(item("ok", "승인됨", g.approved_by === "policy:auto" ? "정책 자동 승인" : `승인자 ${g.approved_by || ""}`));
      if (g.deployment_status === "running") rows.push(item("run", "운영 반영 중", { no_code: "배포 Job이 운영용 Genie를 만들거나 고치고 공개 그룹에 CAN RUN (1~2분)",
        code: "aops 서버가 운영 앱을 배포 (4~5분)", skill: "배포 Job이 UC Skill 내용을 바꿈 (1~2분)" }[kind] || "배포 Job (1~5분)"));
      if (g.deployment_status === "succeeded") rows.push(item("ok", "운영 반영 완료", `운영 버전 ${g.version}`));
      if (g.deployment_status === "failed") rows.push(item("bad", "배포 실패", "배포 탭의 기록을 확인하세요"));
      if (g.decision === "rejected") rows.push(item("bad", "반려", g.decision_reason || ""));
      if (g.decision === "canceled") rows.push(item("bad", "취소됨", g.decision_reason || ""));
      list.replaceChildren(...rows);
      if (steps.some((s) => s.status === "failed")) outcome.replaceChildren(h("h3", { class: "mt" }, "평가 결과"), h("ul", { class: "steps" }, steps.map(stepItem)), resultsTable(g.evaluation.results));
      const done = ["rejected", "canceled"].includes(g.decision) || ["succeeded", "failed"].includes(g.deployment_status);
      if (done) {
        refreshCounts();
        if (g.deployment_status === "succeeded") {
          toast(`운영 반영 완료: ${id} ${g.version}`, "ok");
          if (kind === "no_code") get(`/no-code/agents/${enc(id)}`).then((nc) => nc.prod_url && outcome.replaceChildren(h("div", { class: "note mt" },
            "운영용 Genie: ", h("a", { href: nc.prod_url, target: "_blank" }, `${nc.prod_url} ↗`), nc.consumer_group ? ` · ${nc.consumer_group} CAN RUN` : ""))).catch(() => {});
        }
      }
      if (personDecides) {
        outcome.replaceChildren(h("div", { class: "note warn mt" }, `승인자${g.approvers && g.approvers.length ? ` (${g.approvers.join(", ")})` : ""}에게 요청됐습니다 `,
          h("a", { href: `#/gates/${enc(g.gate_id)}` }, "리포트 보기 →")));
      }
      return !done && !personDecides;
    });
    m.onClose(() => { timer.stop(); if (location.hash.startsWith(`#/agents/${enc(id)}`)) render(); });
  }).catch((e) => { m.close(); if (e.code === "gate_open" && e.data) openGateConflict(id, version, reason, kind, e.data); else fail(e); });
}

// The agent has a request still moving: show it, and let its requester cancel it for this one.
function openGateConflict(id, version, reason, kind, open) {
  const mine = state.me && open.requester === state.me.user;
  const cancelable = ["validating", "pending_approval"].includes(open.decision);
  const buttons = [{ label: "닫기", run: (close) => close() },
    { label: "그 요청 보기 →", run: (close) => { close(); location.hash = `#/gates/${enc(open.gate_id)}`; } }];
  if (mine && cancelable && version) buttons.push({ label: `${open.version} 요청 취소하고 ${version} 요청`, cls: "primary", run: async (close) => {
    try {
      await post(`/release-gates/${enc(open.gate_id)}/cancel`);
      close();
      toast(`${open.version} 요청을 취소했습니다`, "ok");
      followDeploy(id, version, reason, kind);
    } catch (e) { fail(e); }
  } });
  modal("진행 중인 배포 요청이 있습니다", h("div", {},
    h("div", { class: "row" }, h("b", { class: "mono" }, `${id} ${open.version}`), badge("decision", open.decision),
      open.deployment_status ? badge("deployment", open.deployment_status) : null, h("span", { class: "muted" }, `요청 ${open.requester}`)),
    h("p", { class: "mt" }, "에이전트마다 배포 요청은 하나씩 진행합니다."),
    !cancelable ? h("div", { class: "note warn" }, "운영 반영 중입니다. 끝난 뒤 다시 요청하세요")
      : !mine ? h("div", { class: "note" }, "요청자나 승인자가 끝내야 합니다 (취소·반려)") : null), buttons);
}

// ── 권한 (aops promote) ─────────────────────────────────────────────────────

function openPromote(agent) {
  const input = h("textarea", { placeholder: "group:account users\nuser:someone@example.com" });
  const result = h("div", {});
  const run = async (revoke) => {
    const principals = input.value.split(/\n|,/).map((s) => s.trim()).filter(Boolean);
    if (!principals.length) return toast("대상을 적으세요", "bad");
    try {
      const grants = await post(`/agents/${enc(agent.agent_id)}/promote`, { principals, revoke });
      result.replaceChildren(h("table", { class: "data mt" }, h("thead", {}, h("tr", {}, ["대상", "권한", "객체", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, grants.map((g) => h("tr", {}, h("td", {}, g.principal), h("td", { class: "mono" }, g.permission), h("td", { class: "mono" }, g.securable),
          h("td", {}, g.granted ? h("span", { class: "badge ok" }, "부여") : h("span", { class: "badge plain" }, "회수")))))));
      toast(revoke ? "권한을 회수했습니다" : "권한을 주었습니다", "ok");
    } catch (e) { fail(e); }
  };
  modal(`${act("promote")}: ${agent.agent_id}`, h("div", {},
    h("label", { class: "field" }, h("span", {}, "대상 (한 줄에 하나)"), input,
      h("small", {}, agent.build_type === "code"
        ? "group:<그룹> · user:<이메일> · sp:<application ID>. 코드 기반은 운영 앱에 CAN_USE를 겁니다. 받은 사람은 앱을 열어 씁니다."
        : agent.build_type === "no_code"
          ? "group:<그룹> · user:<이메일> · sp:<application ID>. 노코드는 운영용 Genie에 CAN RUN을 겁니다 (배포 때 SPEC.md의 공개 그룹에는 자동). 받은 사람은 테이블 SELECT와 warehouse 사용 권한도 있어야 답을 받습니다."
          : "group:<계정 그룹> · user:<이메일> · sp:<application ID>. 스킬은 운영 UC Skill에 READ_VOLUME을 겁니다. 받은 사람은 가져오기(load)를 할 수 있습니다.")),
    result), [
    { label: "회수", cls: "danger", run: () => run(true) },
    { label: "권한 주기", cls: "primary", run: () => run(false) }]);
}

// ── 가져오기 (aops load) ────────────────────────────────────────────────────

async function openLoad(agent) {
  // a link (app, Genie) opens in a window made during the click: one opened after the request is often blocked
  const win = agent.build_type === "skill" ? null : window.open("", "_blank");
  try {
    const info = await post(`/agents/${enc(agent.agent_id)}/load`, {});
    if (info.link) {
      const what = agent.build_type === "no_code" ? ["운영용 Genie", "CAN RUN 권한이 있어야 열립니다"] : ["운영 앱", "앱 사용 권한(CAN_USE)이 있어야 열립니다"];
      if (win) { win.location = info.link; return toast(`${what[0]}를 엽니다: ${agent.agent_id} ${info.version}`, "ok", what[1]); }
      return modal(`${what[0]}: ${agent.agent_id} ${info.version}`, h("div", {}, h("p", {}, "브라우저가 새 창을 막았습니다. 아래 링크로 여세요."),
        h("a", { class: "btn primary", href: info.link, target: "_blank" }, `${what[0]} 열기 ↗`), h("p", { class: "muted mt" }, what[1])));
    }
    if (win) win.close();
    if (!info.allowed || !info.archive) return toast("가져올 수 없습니다", "bad", "운영 UC Skill 읽기 권한이 필요합니다 (담당자에게 권한 요청)");
    await download(info.archive.url.replace(API, ""), `${agent.agent_id}-${info.version}.zip`);
    toast(`가져옴: ${agent.agent_id} ${info.version}`, "ok", "풀어서 aops run으로 쓰거나 Genie Code 폴더에 올리세요");
  } catch (e) { if (win) win.close(); fail(e); }
}

// ── 배포 요청함 (aops gates · approve · reject · deploy --cancel) ─────────────

async function gatesPage(root, params) {
  let tab = params.get("tab") || (state.toApprove ? "approve" : "mine");
  const pane = h("div", {});
  const tabBar = h("div", { class: "tabs" });
  const tabs = [["approve", "승인할 요청", "?to_approve=true"], ["mine", "내 요청", "?mine=true"], ["all", "전체", ""]];
  const load = async () => {
    tabBar.replaceChildren(...tabs.map(([key, label]) => h("button", { class: key === tab ? "on" : "", onclick: () => { tab = key; load(); } },
      label, key === "approve" && state.toApprove ? h("span", { class: "n" }, state.toApprove) : null)));
    pane.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" })));
    const page = await get(`/release-gates${tabs.find((t) => t[0] === tab)[2]}`);
    pane.replaceChildren(gatesTable(page, { agent: true, approve: tab === "approve" }));
  };
  root.replaceChildren(pageHead("배포 요청함", "요청마다 평가 리포트를 보고 승인·반려합니다", [], "aops gates · approve · reject"),
    h("div", { class: "card pad" }, tabBar, pane));
  await load();
}

// Deploy requests: each row opens its report page, where the approver decides
function gatesTable(page, { agent, approve }) {
  const rows = page.items;
  if (!rows.length) return h("div", { class: "empty" }, h("b", {}, approve ? "승인할 배포 요청이 없습니다" : "배포 요청이 없습니다"),
    approve ? "내가 지정 승인자(또는 승인 그룹)인 요청만 나옵니다. 내 요청은 내가 승인할 수 없습니다." : "");
  return h("table", { class: "data" },
    h("thead", {}, h("tr", {}, [agent ? "에이전트" : "버전", "상태", "내용 검토", "승인자", "요청", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((g) => h("tr", { class: "click", onclick: () => { location.hash = `#/gates/${enc(g.gate_id)}`; } },
      h("td", {}, agent ? [h("div", { class: "cell-main" }, g.agent_id), h("div", { class: "cell-sub mono" }, `${g.version} · ${UPGRADE[g.upgrade_type] || g.upgrade_type}`)]
        : [h("div", { class: "cell-main mono" }, g.version), h("div", { class: "cell-sub" }, UPGRADE[g.upgrade_type] || g.upgrade_type)]),
      h("td", {}, badge("decision", g.decision), g.deployment_status ? [" ", badge("deployment", g.deployment_status)] : null,
        g.decision_reason ? h("div", { class: "cell-sub", style: "max-width:320px" }, g.decision_reason) : null),
      h("td", {}, g.review_verdict ? badge("verdict", g.review_verdict) : h("span", { class: "muted" }, "–")),
      h("td", { class: "cell-sub" }, g.approvers && g.approvers.length ? g.approvers.join(", ") : "승인 그룹"),
      h("td", {}, h("div", {}, g.requester), h("div", { class: "cell-sub" }, when(g.requested_at))),
      h("td", { class: "num" }, approve && g.decision === "pending_approval" ? h("span", { class: "btn small primary" }, "리포트 보고 결정") : h("span", { class: "muted" }, "열기 →"))))));
}

// A request in three steps: evaluation, approval, production (the same marks as the agent's lifecycle)
function gateProgress(g, run) {
  const ev = g.decision === "validating" ? ["run", "평가 중"] : !run ? ["na", g.validation_policy_mode === "exempt" ? "면제" : "–"]
    : ["failed", "error", "stale"].includes(run.status) ? ["bad", LABEL.validation[run.status][0]]
      : run.review && run.review.verdict === "fail" ? ["warn", "부적합 있음"] : run.review && run.review.verdict === "warn" ? ["warn", "주의 있음"] : ["done", "통과"];
  const ap = g.decision === "pending_approval" ? ["warn", g.approvers.length ? `${g.approvers.join(", ")} 대기` : "승인 대기"]
    : g.decision === "approved" ? ["done", g.approved_by === "policy:auto" ? "정책 자동 승인" : `${g.approved_by || ""} 승인`]
      : g.decision === "rejected" ? ["bad", "반려"] : g.decision === "canceled" ? ["bad", "취소"] : ["wait", "평가 뒤"];
  const dp = g.deployment_status === "succeeded" ? ["done", `운영 ${g.version}`] : g.deployment_status === "running" ? ["run", "운영 반영 중"]
    : g.deployment_status === "failed" ? ["bad", "배포 실패"] : ["wait", "승인 뒤"];
  return h("ol", { class: "lifecycle three" }, [["평가", ev], ["승인", ap], ["운영 반영", dp]].map(([t, [st, text]], n) => h("li", { class: `st ${st}` },
    h("div", { class: "dot" }, st === "done" ? "✓" : st === "bad" ? "!" : n + 1), h("div", { class: "body" }, h("div", { class: "t" }, t), h("div", { class: "s" }, text)))));
}

async function gatePage(root, id) {
  const g = await get(`/release-gates/${enc(id)}`);
  const run = g.evaluation;
  const open = ["validating", "pending_approval"].includes(g.decision);
  const ack = h("input", { type: "checkbox", id: "ack" });
  const text = h("textarea", { placeholder: "의견 (승인) · 반려 사유 (반려는 필수)" });
  const decide = async (action) => {
    if (action === "approve" && !ack.checked) return toast("리포트를 확인했다고 체크하세요", "bad");
    if (action === "reject" && !text.value.trim()) return toast("반려 사유를 적으세요", "bad");
    try {
      await post(`/release-gates/${enc(id)}/${action}`, action === "reject" ? { reason: text.value.trim() }
        : { comment: text.value.trim() || null, validation_run_id: run ? run.validation_run_id : null });
      toast(action === "reject" ? "반려했습니다" : "승인했습니다. 운영 반영이 시작됩니다", "ok");
      await refreshCounts(); render();
    } catch (e) { fail(e); }
  };
  const panel = g.can_approve ? h("div", { class: "card pad decide" },
    h("h2", {}, "승인자 결정"),
    g.approve_as_exception ? h("div", { class: "note warn" }, "개발용 예외로 결정합니다 (정책 dev_approvers): ",
      g.requester === (state.me && state.me.user) ? "내 요청입니다. " : "지정 승인자가 아닙니다. ", "승인은 감사 이력에 예외로 남습니다.") : null,
    h("label", { class: "row ack", for: "ack" }, ack, h("span", {}, `아래 평가 리포트(${run ? run.validation_run_id.slice(0, 12) : "없음"})를 확인했습니다`)),
    h("label", { class: "field mt-s" }, h("span", {}, "의견·사유"), text),
    h("div", { class: "row" }, h("span", { class: "muted" }, "승인하면 운영 반영이 바로 시작됩니다."),
      h("span", { class: "right row" }, h("button", { class: "btn danger", onclick: () => decide("reject") }, "반려"),
        h("button", { class: "btn primary", onclick: () => decide("approve") }, act("approve"))))) : null;
  const waiting = g.decision === "pending_approval" && !g.can_approve
    ? h("div", { class: "note mt-s" }, g.requester === (state.me && state.me.user) ? "내 요청입니다. 지정 승인자가 이 리포트를 보고 결정합니다."
      : `이 요청은 ${g.approvers.length ? `지정 승인자(${g.approvers.join(", ")})` : "승인 그룹"}가 결정합니다.`) : null;
  const request = h("div", { class: "card pad" }, h("h2", {}, "요청"),
    h("dl", { class: `kv ${panel ? "" : "two-col"}` },
      h("dt", {}, "사유"), h("dd", {}, g.reason || "–"),
      h("dt", {}, "지정 승인자"), h("dd", {}, g.approvers.length ? g.approvers.join(", ") : h("span", { class: "muted" }, "없음 (정책의 승인 그룹)")),
      h("dt", {}, "평가·승인 방식"), h("dd", {}, `${MODE[g.validation_policy_mode]} · ${MODE[g.approval_mode] || g.approval_mode} (승인 ${g.approvals}/${g.required_approvals})`),
      h("dt", {}, "결정"), h("dd", {}, g.decision_reason || (g.approved_by ? `승인 ${g.approved_by === "policy:auto" ? "정책 자동" : g.approved_by}` : "–"))),
    waiting, h("div", { class: "muted mt-s mono", style: "font-size:11.5px" }, `gate ${g.gate_id}${run ? ` · 평가 ${run.validation_run_id}` : ""}`));
  root.replaceChildren(
    pageHead(`배포 요청 ${g.agent_id} ${g.version}`, `${UPGRADE[g.upgrade_type] || g.upgrade_type} · 요청 ${g.requester} · ${when(g.requested_at)}`, [
      h("a", { class: "btn", href: `#/agents/${enc(g.agent_id)}` }, "에이전트 보기"),
      open && g.requester === (state.me && state.me.user) ? h("button", { class: "btn danger", onclick: async () => {
        try { await post(`/release-gates/${enc(id)}/cancel`); toast("취소했습니다", "ok"); render(); } catch (e) { fail(e); } } }, "요청 취소") : null]),
    h("div", { class: "card pad" }, gateProgress(g, run)),
    panel ? h("div", { class: "grid two mt" }, request, panel) : h("div", { class: "mt" }, request),
    run ? h("div", { class: "card pad mt" }, h("h2", {}, "평가 리포트"), run.failure_reason ? h("div", { class: "note bad" }, run.failure_reason) : null, reportView(run))
      : h("div", { class: "card pad mt" }, h("p", { class: "muted" }, g.decision === "validating" ? "평가 중입니다 (evaluate Job). 끝나면 리포트가 여기에 나옵니다." : "평가 기록이 없습니다")));
  if (g.decision === "validating") {
    const timer = every(5000, async () => { const now = await get(`/release-gates/${enc(id)}`); if (now.decision !== "validating") { render(); return false; } return true; });
    void timer;
  }
}

// ── 등록 (aops register) ────────────────────────────────────────────────────

const EXCLUDE_DIRS = new Set(["runs", ".aops", ".claude", ".agents", ".codex", ".git", "__pycache__", ".venv", "node_modules"]);
const EXCLUDE_FILES = new Set(["CLAUDE.md", "AGENTS.md", ".DS_Store"]);

function included(rel) {  // preview only; the server applies the same rule (aops.package.included)
  const parts = rel.split("/");
  if (parts.some((p) => EXCLUDE_DIRS.has(p))) return false;
  return !((parts.length === 1 && EXCLUDE_FILES.has(parts[0])) || parts[parts.length - 1] === ".DS_Store");
}

function registerPage(root, params) {
  const expected = params.get("agent");
  let picked = null;  // { kind: "folder" | "zip" | "workspace", name, files: [{rel, file}], zip, path }
  let bump = "minor";
  const info = h("div", {});
  const result = h("div", {});
  const version = h("input", { type: "text", placeholder: "비우면 자동 (처음 1.0.0)", style: "width:200px" });
  const note = h("input", { type: "text", placeholder: "선택: 무엇을 바꿨는지 (예: 사내 주소·고객 정보 제거)", maxlength: 500 });
  const submit = h("button", { class: "btn primary", disabled: true, onclick: () => send() }, act("register"));
  const checkBtn = h("button", { class: "btn", disabled: true, title: "템플릿 구성을 지금 바로 점검 (기록 안 함)", onclick: () => selfCheck() }, act("selfcheck"));
  const folderInput = h("input", { type: "file", webkitdirectory: true, multiple: true, style: "display:none", onchange: (e) => pickFolder([...e.target.files]) });
  const zipInput = h("input", { type: "file", accept: ".zip", style: "display:none", onchange: (e) => e.target.files[0] && pickZip(e.target.files[0]) });
  const drop = h("div", { class: "drop" },
    h("p", {}, h("b", {}, "에이전트 폴더를 고르거나 zip을 놓으세요")),
    h("div", { class: "row", style: "justify-content:center" },
      h("button", { class: "btn", onclick: () => folderInput.click() }, "폴더 고르기"), h("button", { class: "btn", onclick: () => zipInput.click() }, "zip 고르기")),
    folderInput, zipInput);
  const wsPath = h("input", { type: "text", placeholder: "/Workspace/Users/<나>/aops/<이름>", style: "flex:1", value: params.get("path") || "" });
  const wsBox = h("div", { class: "row mt" }, h("span", { class: "muted" }, "또는 워크스페이스 폴더:"), wsPath,
    h("button", { class: "btn", onclick: () => pickWorkspace() }, "이 폴더로"));

  function pickWorkspace() {
    const path = wsPath.value.trim().replace(/\/+$/, "");
    if (!path.startsWith("/Workspace/")) return toast("/Workspace/로 시작하는 폴더를 적으세요", "bad");
    picked = { kind: "workspace", name: expected || path.split("/").pop(), path };
    showPicked();
  }
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".zip")) pickZip(file); else toast("폴더는 '폴더 고르기'로 고르세요 (끌어 놓기는 zip만)", "bad");
  });

  async function pickFolder(files) {
    const entries = files.map((file) => ({ file, rel: file.webkitRelativePath.split("/").slice(1).join("/") }));
    const toml = entries.find((e) => e.rel === "aops.toml");
    if (!toml) return toast("aops.toml이 없는 폴더입니다", "bad", "aops init으로 만든 에이전트 폴더를 고르세요");
    const text = await toml.file.text();
    const name = (text.match(/^\s*name\s*=\s*"([^"]+)"/m) || [])[1];
    const spec = entries.find((e) => e.rel === "SPEC.md");
    const desc = spec ? ((await spec.file.text()).match(/^description:\s*(.*)$/m) || [])[1] : null;
    const kept = entries.filter((e) => included(e.rel));
    picked = { kind: "folder", name, files: kept, skipped: entries.length - kept.length, desc };
    showPicked();
  }

  function pickZip(file) {
    picked = { kind: "zip", name: expected || file.name.replace(/(-\d+\.\d+\.\d+)?\.zip$/, ""), zip: file };
    showPicked();
  }

  function showPicked() {
    const mismatch = expected && picked.name && picked.name !== expected;
    info.replaceChildren(h("div", { class: "card pad mt" },
      h("dl", { class: "kv" },
        h("dt", {}, "에이전트"), h("dd", {}, h("b", {}, picked.name || "(aops.toml에 이름 없음)"), picked.desc ? h("span", { class: "muted" }, ` · ${picked.desc}`) : null),
        h("dt", {}, "보낼 것"), h("dd", {}, picked.kind === "zip" ? `zip ${size(picked.zip.size)}` : picked.kind === "workspace"
          ? h("span", { class: "mono" }, picked.path)
          : `파일 ${picked.files.length}개${picked.skipped ? ` (${picked.skipped}개 제외)` : ""}`)),
      picked.kind === "folder" ? h("div", { class: "files" }, picked.files.map((f) => h("div", {}, f.rel))) : null,
      mismatch ? h("div", { class: "note warn mt" }, `이 폴더는 ${picked.name}입니다 (${expected}의 새 버전이 아닙니다)`) : null));
    submit.disabled = !picked.name;
    checkBtn.disabled = !picked.name;
  }

  function pickedForm() {
    const form = new FormData();
    if (picked.kind === "zip") form.append("archive", picked.zip, picked.zip.name);
    else if (picked.kind === "workspace") form.append("workspace_path", picked.path);
    else picked.files.forEach((f) => form.append("files", f.file, `${picked.name}/${f.rel}`));
    return form;
  }

  async function selfCheck() {
    checkBtn.disabled = true;
    try {
      const r = await api("POST", `/projects/${enc(picked.name)}/validations`, { form: pickedForm() });
      result.replaceChildren(h("div", { class: "card pad mt" }, h("div", { class: "row" }, h("h2", { style: "margin:0" }, `셀프 체크: ${picked.name}`), badge("validation", r.status)),
        h("div", { class: "mt" }, checklist(r.steps))));
    } catch (e) { fail(e); }
    checkBtn.disabled = false;
  }

  async function send() {
    const form = pickedForm();
    if (version.value.trim()) form.append("version", version.value.trim()); else form.append("bump", bump);
    if (note.value.trim()) form.append("note", note.value.trim());
    submit.disabled = true;
    submit.replaceChildren(h("span", { class: "spinner" }), " 등록 중…");
    try {
      const row = await api("POST", `/projects/${enc(picked.name)}/registrations`, { form });
      result.replaceChildren(h("div", { class: "card pad mt" },
        h("div", { class: "row" }, h("h2", { style: "margin:0" }, `등록: ${picked.name} ${row.version}`), badge("version", row.status)),
        h("dl", { class: "kv mt" },
          row.note ? [h("dt", {}, "사유"), h("dd", {}, row.note)] : null,
          h("dt", {}, "버전 zip"), h("dd", { class: "mono" }, row.artifact_path),
          h("dt", {}, "파일 해시"), h("dd", { class: "mono" }, short(row.source_sha256)),
          h("dt", {}, "스킬"), h("dd", {}, row.skills.map((s) => h("div", {}, h("b", {}, s.skill_alias), h("span", { class: "muted" }, ` → 배포하면 UC Skill ${s.uc_name || ""}`)))),
          h("dt", {}, "Git"), h("dd", {}, row.git ? (row.git.status === "synced" ? h("a", { href: row.git.url, target: "_blank" }, row.git.url) : `${row.git.status}: ${row.git.error || ""}`) : "–")),
        h("div", { class: "row mt" },
          h("button", { class: "btn", onclick: () => openEvaluate(picked.name, row.version) }, act("evaluate")),
          h("button", { class: "btn primary", onclick: async (e) => {
            e.target.disabled = true;
            try { const [a, v] = await Promise.all([get(`/agents/${enc(picked.name)}`), get(`/agents/${enc(picked.name)}/versions`)]); openDeploy(picked.name, v.items, a.production_version, row.version, a.build_type); }
            catch (err) { fail(err); }
            e.target.disabled = false;
          } }, act("deploy")),
          h("a", { class: "btn ghost", href: `#/agents/${enc(picked.name)}` }, "에이전트 보기 →"))));
      toast(`등록: ${picked.name} ${row.version}`, "ok");
    } catch (e) { fail(e); }
    submit.disabled = false;
    submit.replaceChildren(act("register"));
  }

  const bumpSeg = h("div", { class: "seg" }, [["fix", "fix (1.0.x)"], ["minor", "minor (1.x.0)"], ["major", "major (x.0.0)"]].map(([v, label]) =>
    h("button", { class: v === bump ? "on" : "", onclick: (e) => { bump = v; bumpSeg.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.target.classList.add("on"); } }, label)));
  if (params.get("path")) pickWorkspace();
  root.replaceChildren(
    pageHead(expected ? `${expected} 새 버전 등록` : "폴더·zip 등록", expected ? "작업 폴더나 PC 폴더·zip으로 새 버전을 저장합니다" : "PC 폴더·zip·워크스페이스 폴더를 버전으로 저장합니다. 처음이면 에이전트가 생깁니다", [], "aops register"),
    h("div", { class: "card pad" }, drop, wsBox, info,
      h("div", { class: "grid two mt" },
        h("div", { class: "field" }, h("span", {}, "버전 올리는 폭"), bumpSeg, h("small", {}, "처음 등록은 1.0.0")),
        h("label", { class: "field" }, h("span", {}, "또는 버전 직접"), version)),
      h("label", { class: "field" }, h("span", {}, "사유"), note, h("small", {}, "버전 기록과 Git 커밋 메시지에 남습니다")),
      h("div", { class: "row" }, h("span", { class: "muted" }, "등록은 버전을 저장할 뿐입니다. 평가와 승인은 배포 요청 때 합니다."),
        h("span", { class: "right row" }, checkBtn, submit))),
    result);
}

// ── 새 에이전트 (aops init) ─────────────────────────────────────────────────

const KINDS = [["skill", "스킬 기반"], ["code", "코드 기반"], ["no_code", "노코드 (Genie)"]];
const MAX_TABLES = 30;
const ACCESS = { ok: ["서비스 주체 읽기 가능", "ok"], missing: ["서비스 주체 SELECT 없음", "warn"], unknown: ["서비스 주체 확인 못함", "plain"] };

function listError(e, what) {  // a list the requester's token could not read: say why, and that typing still works
  return h("div", { class: "note warn" }, `${what}을 불러오지 못했습니다: ${e.title || e.message || e}`,
    h("div", { class: "mt-s" }, "[직접 입력]으로 적을 수도 있습니다."));
}

// Tables the requester may SELECT (Unity Catalog lists only those), picked catalog → schema → table.
function tablePicker() {
  const picked = new Map();  // full_name → {kind, comment}
  const access = new Map();  // full_name → {status, detail}
  let tables = [];
  let manual = false;
  const catSel = h("select", { "aria-label": "카탈로그" }, h("option", { value: "" }, "카탈로그 불러오는 중…"));
  const schSel = h("select", { "aria-label": "스키마", disabled: true }, h("option", { value: "" }, "스키마"));
  const filter = h("input", { type: "search", placeholder: "이 스키마에서 이름·설명으로 찾기", disabled: true, oninput: () => drawList() });
  const list = h("div", { class: "pick-list" }, h("div", { class: "muted pad-s" }, "카탈로그와 스키마를 고르면 내가 SELECT할 수 있는 테이블이 나옵니다."));
  const chips = h("div", { class: "chips" });
  const count = h("span", { class: "muted" });
  const status = h("div", {});
  const typed = h("textarea", { placeholder: "main.sales.orders\nmain.sales.customers", oninput: () => drawChips() });
  const browse = h("div", {}, h("div", { class: "row" }, catSel, schSel), h("div", { class: "row mt-s" }, filter), list);
  const typedBox = h("div", { style: "display:none" }, typed, h("small", { class: "muted" }, "<catalog>.<schema>.<table> 한 줄에 하나. 내게 SELECT가 없으면 Genie를 만들 때 실패합니다"));
  const toggle = h("button", { type: "button", class: "btn ghost small", onclick: () => {
    manual = !manual; browse.style.display = manual ? "none" : ""; typedBox.style.display = manual ? "" : "none";
    toggle.textContent = manual ? "목록에서 고르기" : "직접 입력"; drawChips();
  } }, "직접 입력");

  const names = () => manual ? typed.value.split(/\n|,/).map((t) => t.trim()).filter(Boolean) : [...picked.keys()];
  const values = () => manual ? { tables: names(), metric_views: [] } : {
    tables: [...picked].filter(([, v]) => v.kind !== "metric_view").map(([k]) => k),
    metric_views: [...picked].filter(([, v]) => v.kind === "metric_view").map(([k]) => k) };

  async function checkAccess(list) {
    const fresh = list.filter((n) => !access.has(n));
    if (!fresh.length) return;
    fresh.forEach((n) => access.set(n, null));
    try {
      (await post("/no-code/table-access", { tables: fresh })).forEach((r) => access.set(r.full_name, r));
    } catch { fresh.forEach((n) => access.delete(n)); }
    drawChips();
  }

  function drawChips() {
    const all = names();
    count.textContent = `${all.length}개 골랐습니다 (5개 이하 권장, 최대 ${MAX_TABLES}개)`;
    if (manual) { fill(chips); fill(status); return; }
    fill(chips, all.map((n) => {
      const a = access.get(n);
      const [label, cls] = a ? ACCESS[a.status] : ["확인 중…", "plain"];
      return h("span", { class: "chip", title: a ? a.detail : "" }, h("span", { class: "mono" }, n),
        picked.get(n).kind === "metric_view" ? h("span", { class: "tag" }, "메트릭 뷰") : null,
        h("span", { class: `badge ${cls}` }, label),
        h("button", { type: "button", class: "x", "aria-label": `${n} 빼기`, onclick: () => { picked.delete(n); drawChips(); drawList(); } }, "✕"));
    }));
    const missing = all.filter((n) => (access.get(n) || {}).status === "missing");
    fill(status, missing.length ? h("div", { class: "note warn mt-s" }, `aops 서비스 주체가 ${missing.length}개를 읽지 못합니다: 개발용 Genie는 지금 만들 수 있지만, `
      + "운영용 Genie는 서비스 주체 권한으로 돌기 때문에 첫 배포 전에 데이터 주인이 SELECT(와 USE CATALOG·USE SCHEMA)를 주어야 합니다.") : null);
    checkAccess(all);
  }

  function drawList() {
    const q = filter.value.trim().toLowerCase();
    const rows = tables.filter((t) => !q || `${t.name} ${t.comment || ""}`.toLowerCase().includes(q));
    if (!tables.length) return fill(list, h("div", { class: "muted pad-s" }, schSel.value ? "이 스키마에 내가 SELECT할 수 있는 테이블이 없습니다." : "스키마를 고르세요."));
    fill(list, rows.map((t) => {
      const on = picked.has(t.full_name);
      const box = h("input", { type: "checkbox", checked: on, disabled: !on && picked.size >= MAX_TABLES, onchange: (e) => {
        if (e.target.checked) picked.set(t.full_name, { kind: t.kind, comment: t.comment }); else picked.delete(t.full_name);
        drawChips(); drawList();
      } });
      return h("label", { class: `pick-row ${on ? "on" : ""}` }, box,
        h("div", { class: "grow" }, h("div", {}, h("b", {}, t.name), " ", t.kind === "metric_view" ? h("span", { class: "tag" }, "메트릭 뷰")
          : t.table_type && t.table_type !== "MANAGED" ? h("span", { class: "tag" }, t.table_type.toLowerCase()) : null),
          t.comment ? h("div", { class: "cell-sub" }, t.comment) : null),
        h("button", { type: "button", class: "btn ghost small", title: "컬럼 보기", onclick: (e) => { e.preventDefault(); showColumns(t.full_name); } }, "컬럼"));
    }), rows.length ? null : h("div", { class: "muted pad-s" }, "찾는 테이블이 없습니다."));
  }

  async function showColumns(fullName) {
    const m = modal(fullName, h("div", { class: "loading" }, h("span", { class: "spinner" })), [], { wide: true });
    try {
      const t = await get(`/me/tables/${enc(fullName)}`);
      m.body.replaceChildren(t.comment ? h("p", {}, t.comment) : null, h("p", { class: "muted" }, `${t.table_type || ""} · 소유 ${t.owner || "–"} · 컬럼 ${t.columns.length}개`),
        h("table", { class: "data" }, h("thead", {}, h("tr", {}, ["컬럼", "형식", "설명"].map((x) => h("th", {}, x)))),
          h("tbody", {}, t.columns.map((c) => h("tr", {}, h("td", { class: "mono cell-main" }, c.name), h("td", { class: "mono muted" }, c.type || ""), h("td", { class: "muted" }, c.comment || ""))))));
    } catch (e) { m.close(); fail(e); }
  }

  catSel.addEventListener("change", async () => {
    tables = []; drawList(); schSel.disabled = true; filter.disabled = true;
    if (!catSel.value) return;
    fill(schSel, h("option", { value: "" }, "스키마 불러오는 중…"));
    try {
      const r = await get(`/me/catalogs/${enc(catSel.value)}/schemas`);
      fill(schSel, h("option", { value: "" }, r.items.length ? "스키마 고르기" : "쓸 수 있는 스키마가 없습니다"), r.items.map((s) => h("option", { value: s.name, title: s.comment || "" }, s.name)));
      schSel.disabled = !r.items.length;
    } catch (e) { fill(schSel, h("option", { value: "" }, "불러오지 못함")); fill(list, listError(e, "스키마 목록")); }
  });
  schSel.addEventListener("change", async () => {
    tables = []; filter.value = ""; filter.disabled = true;
    if (!schSel.value) return drawList();
    fill(list, h("div", { class: "loading" }, h("span", { class: "spinner" }), " 테이블 불러오는 중…"));
    try {
      const r = await get(`/me/catalogs/${enc(catSel.value)}/schemas/${enc(schSel.value)}/tables`);
      tables = r.items; filter.disabled = false; drawList();
      if (r.truncated) list.append(h("div", { class: "note mt-s" }, "테이블이 많아 앞 1000개만 보입니다. 위 칸에서 이름으로 찾으세요."));
    } catch (e) { fill(list, listError(e, "테이블 목록")); }
  });
  get("/me/catalogs").then((r) => {
    fill(catSel, h("option", { value: "" }, r.items.length ? "카탈로그 고르기" : "쓸 수 있는 카탈로그가 없습니다"),
      r.items.map((c) => h("option", { value: c.name, title: c.comment || "" }, c.name)));
  }).catch((e) => { fill(catSel, h("option", { value: "" }, "불러오지 못함")); fill(list, listError(e, "카탈로그 목록")); });
  drawChips();
  const el = h("div", { class: "field" }, h("div", { class: "row" }, h("span", { class: "label" }, "데이터 (내가 SELECT할 수 있는 테이블)"), h("span", { class: "right" }, toggle)),
    browse, typedBox, h("div", { class: "row mt-s" }, count), chips, status);
  return { el, values, count: () => names().length };
}

// Approvers: workspace users and groups found by name or email (the aops server looks them up), or typed in.
const EMAIL = /^[^@\s,]+@[^@\s,]+\.[^@\s,]+$/;

function approverPicker(required) {
  const chosen = [];
  let timer = null;
  const input = h("input", { type: "search", placeholder: "이름·이메일로 찾기 (2자 이상). 이메일이나 group:<그룹>을 적고 Enter로도 추가" });
  const results = h("div", { class: "pick-list short", style: "display:none" });
  const chips = h("div", { class: "chips" });
  const warn = h("div", {});
  const me = () => (state.me ? state.me.user.toLowerCase() : "");
  const add = (principal, name) => {
    if (!chosen.some((c) => c.principal.toLowerCase() === principal.toLowerCase())) chosen.push({ principal, name: name || principal });
    input.value = ""; results.style.display = "none"; draw();
  };
  const draw = () => {
    fill(chips, chosen.map((c, i) => h("span", { class: "chip" }, c.name !== c.principal ? [h("b", {}, c.name), h("span", { class: "mono muted" }, c.principal)] : h("span", { class: "mono" }, c.principal),
      c.principal.toLowerCase() === me() ? h("span", { class: "badge warn" }, "나") : null,
      h("button", { type: "button", class: "x", "aria-label": `${c.principal} 빼기`, onclick: () => { chosen.splice(i, 1); draw(); } }, "✕"))));
    const others = chosen.filter((c) => c.principal.toLowerCase() !== me());
    fill(warn, chosen.length && !others.length ? h("div", { class: "note warn mt-s" }, "나만 승인자이면 내 배포 요청을 승인할 사람이 없습니다. 다른 사람이나 그룹을 더하세요.")
      : !chosen.length && required ? h("div", { class: "note warn mt-s" }, "정책이 승인자 지정을 요구합니다. 한 명 이상 고르세요.") : null);
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { results.style.display = "none"; return; }
    timer = setTimeout(async () => {
      try {
        const rows = await get(`/directory?q=${enc(q)}`);
        results.style.display = "";
        fill(results, rows.length ? rows.map((r) => h("button", { type: "button", class: "pick-row", onclick: () => add(r.principal, r.name) },
          h("div", { class: "grow" }, h("b", {}, r.name), h("div", { class: "cell-sub mono" }, r.principal)), h("span", { class: "tag" }, r.kind === "group" ? "그룹" : "사용자")))
          : h("div", { class: "muted pad-s" }, "찾는 사람·그룹이 없습니다. 이메일이나 group:<그룹>을 적고 Enter"));
      } catch (e) { results.style.display = ""; fill(results, h("div", { class: "muted pad-s" }, `${e.title || e}. 이메일이나 group:<그룹>을 적고 Enter`)); }
    }, 300);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const v = input.value.trim();
    if (EMAIL.test(v) || /^group:\S/.test(v)) add(v);
    else toast("이메일이나 group:<그룹> 형태로 적으세요", "bad");
  });
  draw();
  return {
    el: h("div", { class: "field" }, h("span", {}, `배포 요청을 승인할 사람${required ? " · 필수" : ""}`), input, results, chips, warn,
      h("small", {}, "비우면 정책의 승인 그룹이 승인합니다")),
    values: () => chosen.map((c) => c.principal),
  };
}

// SQL warehouses the requester can see; the aops server's one first. Typing an ID still works.
function warehousePicker(note) {
  const sel = h("select", {}, h("option", { value: "" }, "불러오는 중…"));
  const typed = h("input", { type: "text", placeholder: "warehouse ID", style: "display:none" });
  get("/me/warehouses").then((r) => {
    const listed = r.items.some((w) => w.default);  // the server's one is first when I can see it
    fill(sel, listed ? null : h("option", { value: "" }, `aops 기본 (${r.default || "서버 설정"})`), r.items.map((w) => h("option", { value: w.default ? "" : w.id, selected: w.default },
      `${w.name}${w.default ? " (aops 기본)" : ""} · ${[w.serverless ? "serverless" : null, w.size, w.state && w.state.toLowerCase()].filter(Boolean).join(" · ")}`)));
  }).catch(() => { sel.style.display = "none"; typed.style.display = ""; typed.placeholder = "목록을 못 불러왔습니다. warehouse ID (비우면 aops 기본)"; });
  return { el: h("label", { class: "field" }, h("span", {}, "SQL warehouse"), sel, typed, h("small", {}, note)), value: () => (sel.style.display === "none" ? typed.value : sel.value).trim() };
}

// Genie spaces the requester can open (to copy or move), with a search; a URL or ID can be pasted instead.
function spacePicker() {
  let chosen = null;
  let all = [];
  const search = h("input", { type: "search", placeholder: "제목·설명으로 찾기, 또는 Genie 주소·ID 붙여넣기", oninput: () => draw() });
  const list = h("div", { class: "pick-list short" }, h("div", { class: "loading" }, h("span", { class: "spinner" })));
  const picked = h("div", { class: "muted" }, "고른 스페이스 없음");
  const draw = () => {
    const pasted = (search.value.match(/[0-9a-f]{32}/) || [""])[0];
    if (pasted) { chosen = { space_id: pasted, title: (all.find((s) => s.space_id === pasted) || {}).title || "붙여넣은 스페이스" }; showChosen(); }
    const q = search.value.trim().toLowerCase();
    const rows = all.filter((s) => !q || pasted || `${s.title} ${s.description || ""}`.toLowerCase().includes(q));
    fill(list, rows.length ? rows.map((s) => h("button", { type: "button", class: `pick-row ${chosen && chosen.space_id === s.space_id ? "on" : ""}`,
      onclick: () => { chosen = s; showChosen(); draw(); } }, h("div", { class: "grow" }, h("b", {}, s.title), s.description ? h("div", { class: "cell-sub" }, s.description) : null),
      h("span", { class: "mono muted" }, s.space_id.slice(0, 8)))) : h("div", { class: "muted pad-s" }, all.length ? "찾는 스페이스가 없습니다." : "열 수 있는 Genie 스페이스가 없습니다."));
  };
  const showChosen = () => fill(picked, chosen ? [h("b", {}, chosen.title), h("span", { class: "mono muted" }, ` ${chosen.space_id}`)] : "고른 스페이스 없음");
  get("/genie/spaces").then((r) => { all = r.items; draw(); }).catch((e) => fill(list, listError(e, "Genie 스페이스 목록")));
  return { el: h("div", { class: "field" }, h("span", {}, "Genie 스페이스"), search, list, h("div", { class: "row" }, h("span", { class: "muted" }, "고른 것:"), picked)),
    value: () => (chosen ? chosen.space_id : (search.value.match(/[0-9a-f]{32}/) || [""])[0]) };
}

function newPage(root, params) {
  let kind = params.get("type") || "skill";
  let genieMode = "new";
  const input = (placeholder, width) => h("input", { type: "text", placeholder, style: width ? `width:${width}` : "" });
  const choose = (options, value) => h("select", {}, options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
  const f = {
    name: input("sales-genie"), display: input("비우면 이름"), description: input("이 에이전트가 하는 일을 한 줄로"), group: input("선택: 계정 그룹"),
    crit: choose([["low", "low"], ["medium", "medium"], ["high", "high"]], "medium"),
    sens: choose([["public", "public"], ["internal", "internal"], ["confidential", "confidential"], ["personal", "personal"]], "internal"),
    sec: choose((state.securityLevels || ["general", "important", "secret"]).map((x) => [x, x]), "general"),
    harness: choose([["claude", "claude"], ["codex", "codex"]], "claude"),
    framework: choose([["langgraph", "LangGraph"], ["openai", "OpenAI Agents SDK"]], "langgraph"),
    consumer: input("선택: 운영 Genie를 쓸 계정 그룹"),
    location: input("비우면 /Workspace/Users/<나>/aops/<이름>"),
  };
  const approvers = approverPicker(!!(state.policy && state.policy.approvers_required));
  let pick = null;  // the no-code pickers, made the first time no-code is chosen (they call the lists)
  const pickers = () => pick || (pick = { tables: tablePicker(), space: spacePicker(),
    warehouse: warehousePicker("Genie 질문을 돌릴 warehouse. 내가 쓸 수 있어야 합니다. 비우면 aops 기본 (복사는 원본의 것)") });
  const result = h("div", {});
  const kindBox = h("div", {});
  const help = h("div", {});
  const genieBox = h("div", {});
  const submit = h("button", { class: "btn primary", onclick: () => make() });
  const zipBtn = h("button", { class: "btn", onclick: () => downloadZip() }, "폴더 받기 (zip)");

  const drawGenie = () => {
    if (kind !== "no_code") return;
    const p = pickers();
    fill(genieBox,
      h("div", { class: "field" }, h("span", {}, "개발용 Genie"), segment([["new", "테이블로 새로 만들기"], ["copy", "기존 스페이스 복사"], ["move", "기존 스페이스 옮기기"]], genieMode,
        (v) => { genieMode = v; drawGenie(); }),
        h("small", {}, { new: "고른 테이블과 표준 지침으로 시작합니다",
          copy: "원본은 그대로 두고 정의를 복사해 에이전트 폴더에 새로 만듭니다. 원본에 편집 권한이 필요합니다.",
          move: "그 스페이스를 에이전트 폴더로 옮깁니다 (ID·대화 이력 유지). 내가 CAN MANAGE여야 합니다." }[genieMode])),
      genieMode === "new" ? p.tables.el : p.space.el,
      genieMode === "move" ? null : p.warehouse.el,
      h("label", { class: "field" }, h("span", {}, "공개 그룹 (consumer_group)"), f.consumer, h("small", {}, "배포 때 운영용 Genie에 CAN RUN")));
  };

  const drawKind = () => {
    drawGenie();
    fill(kindBox, kind === "no_code" ? genieBox : [
      kind === "skill" ? h("label", { class: "field" }, h("span", {}, "기본 하네스 (PC에서 aops run)"), f.harness) : null,
      kind === "code" ? h("label", { class: "field" }, h("span", {}, "프레임워크 (Agent Bricks)"), f.framework) : null,
      h("label", { class: "field" }, h("span", {}, "워크스페이스 위치"), f.location, h("small", {}, "이미 있는 폴더에는 만들지 않습니다"))]);
    submit.textContent = kind === "no_code" ? "만들기" : "내 워크스페이스에 만들기";
    zipBtn.style.display = kind === "no_code" ? "none" : "";
    f.description.placeholder = kind === "no_code" ? "필수: 이 Genie가 답하는 질문 (운영 Genie 설명이 됩니다)" : "이 에이전트가 하는 일을 한 줄로";
    const flow = {
      skill: [["개발", "워크스페이스 폴더(Genie Code) 또는 PC"], ["셀프 체크", "템플릿 구성 체크리스트"], ["등록", "폴더를 버전으로"],
        ["평가", "형식 → 내용 검토 → 평가셋"], ["승인", "승인자가 리포트를 보고"], ["운영", "UC Skill"]],
      code: [["개발", "워크스페이스 폴더(Genie Code) 또는 PC"], ["셀프 체크", "Agent Bricks 형식 체크리스트"], ["등록", "폴더를 버전으로"],
        ["평가", "형식 → 내용 검토"], ["승인", "승인자가 리포트를 보고"], ["운영", "운영 앱 agent-bricks-<이름>"]],
      no_code: [["개발", "개발용 Genie"], ["셀프 체크", "Genie 정의 규칙"], ["등록", "없음 (배포 때 버전)"],
        ["평가", "형식 → 내용 검토 → 벤치마크"], ["승인", "승인자가 리포트를 보고"], ["운영", "운영용 Genie"]],
    }[kind];
    fill(help, h("h2", {}, "만든 뒤 흐름"), h("ol", { class: "flow" }, flow.map(([t, d], n) => h("li", {}, h("span", { class: "dot" }, n + 1),
      h("div", {}, h("b", {}, t), h("div", { class: "muted" }, d))))),
      kind === "code" ? h("div", { class: "note mt" }, "처음 한 번은 30초쯤 걸립니다") : null);
  };

  const body = () => ({ name: f.name.value.trim(), type: kind, harness: f.harness.value, framework: f.framework.value, display_name: f.display.value.trim() || null,
    description: f.description.value.trim() || null, owner_group: f.group.value.trim() || null, service_criticality: f.crit.value,
    data_sensitivity: f.sens.value, security_level: f.sec.value, approvers: approvers.values() });
  const approversReady = (b) => {
    const others = b.approvers.filter((a) => !state.me || a.toLowerCase() !== state.me.user.toLowerCase());
    if (state.policy && state.policy.approvers_required && !b.approvers.length) { toast("승인자를 한 명 이상 고르세요 (정책)", "bad"); return false; }
    if (b.approvers.length && !others.length) { toast("나 말고 다른 승인자를 더하세요", "bad"); return false; }
    return true;
  };

  async function downloadZip() {
    const b = body();
    if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(b.name)) return toast("이름은 영문 소문자·숫자·하이픈 63자 이하", "bad");
    try {
      const resp = await fetch(`${API}/projects/template`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
      if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => ({})));
      const url = URL.createObjectURL(await resp.blob());
      const a = h("a", { href: url, download: `${b.name}.zip` }); document.body.append(a); a.click(); a.remove();
      toast(`${b.name}.zip을 받았습니다`, "ok");
    } catch (e) { fail(e); }
  }

  async function makeInWorkspace(b) {
    submit.disabled = true;
    submit.replaceChildren(h("span", { class: "spinner" }), " 만드는 중…");
    try {
      const row = await post("/projects", { ...b, location: f.location.value.trim() || null });
      result.replaceChildren(workspaceCard(row));
      toast(`만들었습니다: ${row.agent_id}`, "ok", "편집기에서 열어 Genie Code로 고친 뒤 이 폴더에서 등록");
    } catch (e) { fail(e); }
    submit.disabled = false;
    submit.textContent = "내 워크스페이스에 만들기";
  }

  async function make() {
    const b = body();
    if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(b.name)) return toast("이름은 영문 소문자·숫자·하이픈 63자 이하", "bad");
    if (!approversReady(b)) return;
    if (kind !== "no_code") return makeInWorkspace(b);
    if (!b.description) return toast("설명을 적으세요 (운영 Genie의 설명이 됩니다)", "bad");
    const p = pickers();
    const space = p.space.value();
    const data = p.tables.values();
    const picked = data.tables.length + data.metric_views.length;
    if (genieMode === "new" && !picked) return toast("데이터로 쓸 테이블을 하나 이상 고르세요", "bad");
    if (genieMode === "new" && picked > MAX_TABLES) return toast(`테이블은 ${MAX_TABLES}개까지입니다`, "bad");
    if (genieMode !== "new" && !space) return toast("복사하거나 옮길 Genie 스페이스를 고르세요", "bad");
    submit.disabled = true;
    submit.replaceChildren(h("span", { class: "spinner" }), " 만드는 중…");
    try {
      const row = await post("/projects", { ...b, genie_mode: genieMode, ...(genieMode === "new" ? data : {}), genie_space_id: genieMode === "new" ? null : space,
        warehouse_id: genieMode === "move" ? null : p.warehouse.value() || null, consumer_group: f.consumer.value.trim() || null });
      result.replaceChildren(h("div", { class: "card pad mt" },
        h("div", { class: "row" }, h("h2", { style: "margin:0" }, `만들었습니다: ${row.agent_id}`), h("span", { class: "tag" }, "노코드")),
        h("dl", { class: "kv mt" },
          h("dt", {}, "에이전트 폴더"), h("dd", { class: "mono" }, row.location),
          h("dt", {}, "개발용 Genie"), h("dd", { class: "mono" }, row.dev_space_id),
          h("dt", {}, "warehouse"), h("dd", { class: "mono" }, row.warehouse_id || "–")),
        row.warnings.map((w) => h("div", { class: "note warn mt" }, w)),
        h("div", { class: "row mt" }, row.links.map((l, i) => h("a", { class: `btn ${i === 0 ? "primary" : ""}`, href: l.url, target: "_blank" }, `${l.label} ↗`)),
          h("a", { class: "btn ghost", href: `#/agents/${enc(row.agent_id)}` }, "에이전트 보기 →"))));
      toast(`만들었습니다: ${row.agent_id}`, "ok", "Genie에서 고친 뒤 에이전트 화면에서 점검·배포 요청");
    } catch (e) { fail(e); }
    submit.disabled = false;
    submit.textContent = "만들기";
  }

  drawKind();
  const sec = (n, title, ...kids) => h("section", { class: "form-sec" }, h("div", { class: "sec-t" }, h("span", { class: "sec-n" }, n), title), kids);
  root.replaceChildren(
    pageHead("새 에이전트", "종류를 고르고 SPEC 항목을 적으면 에이전트의 SPEC.md가 됩니다", [], "aops init"),
    h("div", { class: "grid new-grid" },
      h("div", { class: "card pad" },
        sec(1, "종류", segment(KINDS, kind, (v) => { kind = v; drawKind(); })),
        sec(2, "기본 정보",
          h("div", { class: "grid two" },
            h("label", { class: "field" }, h("span", {}, "이름 (agent_id)"), f.name, h("small", {}, "영문 소문자·숫자·하이픈")),
            h("label", { class: "field" }, h("span", {}, "표시 이름"), f.display)),
          h("label", { class: "field" }, h("span", {}, "설명"), f.description)),
        sec(3, "분류",
          h("div", { class: "grid four" },
            h("label", { class: "field" }, h("span", {}, "중요도"), f.crit),
            h("label", { class: "field" }, h("span", {}, "데이터 민감도"), f.sens),
            h("label", { class: "field" }, h("span", {}, "보안 등급"), f.sec),
            h("label", { class: "field" }, h("span", {}, "담당 팀"), f.group))),
        sec(4, "승인자", approvers.el),
        sec(5, "만들 곳", kindBox),
        h("div", { class: "form-foot row" }, h("span", { class: "muted" }, `담당자(owner)는 나입니다${state.me ? ` (${state.me.user})` : ""}.`), h("span", { class: "right row" }, zipBtn, submit))),
      h("div", { class: "card pad help" }, help)),
    result);
}

function workspaceCard(row) {
  const prompt = row.type === "code" ? "agent/agent.py를 <하고 싶은 일>을 하도록 고쳐줘. 다 되면 이 폴더를 aops에 등록해줘"
    : "agent/skills/my-skill을 <스킬 이름>으로 바꾸고 <규칙>을 적어줘. 다 되면 이 폴더를 aops에 등록해줘";
  return h("div", { class: "card pad mt" },
    h("div", { class: "row" }, h("h2", { style: "margin:0" }, `만들었습니다: ${row.agent_id}`), h("span", { class: "tag" }, BUILD[row.type] || row.type)),
    h("dl", { class: "kv mt" },
      h("dt", {}, "폴더"), h("dd", { class: "mono" }, row.location),
      h("dt", {}, "파일"), h("dd", {}, `${row.files.length}개`, row.open_file ? h("span", { class: "muted" }, ` · 처음 열 파일 ${row.open_file}`) : null)),
    h("div", { class: "note mt" }, "Genie Code에 이렇게 말해 보세요: ", h("code", {}, prompt)),
    h("div", { class: "row mt" }, row.links.map((l, i) => h("a", { class: `btn ${i === 0 ? "primary" : ""}`, href: l.url, target: "_blank" }, `${l.label} ↗`)),
      h("a", { class: "btn", href: `#/register?agent=${enc(row.agent_id)}&path=${enc(row.location)}` }, "이 폴더에서 등록"),
      h("a", { class: "btn ghost", href: `#/agents/${enc(row.agent_id)}` }, "에이전트 보기 →")));
}

// ── 노코드 점검 (Genie 정의 규칙, 참고용) ─────────────────────────────────────

function genieResult(r) {
  const failed = r.rules.filter((x) => !x.passed);
  return h("div", {},
    h("div", { class: "row" }, h("h2", { style: "margin:0" }, r.title || r.space_id), badge("validation", r.status),
      h("span", { class: "muted" }, `준수율 ${Math.round(r.score * 100)}%`)),
    h("dl", { class: "kv mt" },
      h("dt", {}, "데이터 소스"), h("dd", { class: "mono" }, r.tables.join(", ") || "–"),
      h("dt", {}, "정의 해시"), h("dd", { class: "mono" }, short(r.definition_sha256))),
    h("table", { class: "data mt" }, h("thead", {}, h("tr", {}, ["규칙", "수준", "결과", "고치는 곳"].map((t) => h("th", {}, t)))),
      h("tbody", {}, [...failed, ...r.rules.filter((x) => x.passed)].map((x) => h("tr", {},
        h("td", {}, h("div", { class: "cell-main mono" }, x.id), h("div", { class: "cell-sub" }, x.message)),
        h("td", {}, h("span", { class: `badge ${x.level === "ERROR" ? "bad" : "warn"} plain` }, x.level)),
        h("td", {}, x.passed ? h("span", { class: "badge ok" }, "통과") : h("span", { class: "badge bad" }, "미달")),
        h("td", { class: "muted" }, x.passed ? "" : x.fix))))));
}

function geniePage(root, params) {
  const input = h("input", { type: "text", placeholder: "Genie 스페이스 주소나 ID (32자리)", style: "width:420px", value: params.get("space") || "" });
  const result = h("div", {});
  const run = async () => {
    const id = (input.value.match(/[0-9a-f]{32}/) || [""])[0];
    if (!id) return toast("Genie 스페이스 ID(32자리 16진수)를 넣으세요", "bad");
    result.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" }), " 정의를 읽고 규칙을 돌리는 중…"));
    try {
      result.replaceChildren(h("div", { class: "card pad mt" }, genieResult(await post("/no-code/checks", { space_id: id }))));
    } catch (e) { result.replaceChildren(); fail(e); }
  };
  root.replaceChildren(
    pageHead("Genie 점검", "아무 Genie 스페이스나 노코드 정의 규칙으로 지금 점검합니다 (기록하지 않음)", [], "aops validate --agent"),
    h("div", { class: "card pad" },
      h("div", { class: "row" }, input, h("button", { class: "btn primary", onclick: run }, "점검")),
      h("div", { class: "note mt" }, "aops 서비스 주체가 읽을 수 있는 스페이스만 됩니다")),
    result);
  if (input.value) run();
}

// ── 정책 (aops admin setup --only policy) ───────────────────────────────────

async function policyPage(root) {
  const page = await get("/admin/policies");
  const current = page.items.find((p) => p.status === "active");
  const isAdmin = state.me && state.me.roles.includes("admin");
  const pol = current ? current.policy : {};
  const pick = { validation_mode: pol.validation_mode, approval_mode: pol.approval_mode };
  const required = h("input", { type: "checkbox", checked: !!pol.approvers_required, disabled: !isAdmin });
  const devApprovers = h("input", { type: "text", value: (pol.dev_approvers || []).join(", "), placeholder: "비움 (운영)", disabled: !isAdmin });
  const segFor = (key, options) => {
    const box = h("div", { class: "seg" });
    options.forEach(([v, label]) => box.append(h("button", { class: pick[key] === v ? "on" : "", disabled: !isAdmin, onclick: (e) => {
      pick[key] = v; box.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.target.classList.add("on");
    } }, label)));
    return box;
  };
  const group = h("input", { type: "text", value: pol.approver_group || "", placeholder: "비우면 요청자가 아닌 누구나", disabled: !isAdmin });
  const save = async () => {
    try {
      const saved = await post("/admin/policies", { ...pick, approver_group: group.value.trim(), approvers_required: required.checked,
        dev_approvers: devApprovers.value.split(",").map((x) => x.trim()).filter(Boolean) });
      toast(`정책 버전 ${saved.policy_version} 적용`, "ok"); render();
    } catch (e) { fail(e); }
  };
  const git = pol.git;
  root.replaceChildren(
    pageHead("정책·평가 프롬프트", current ? `지금 정책 v${current.policy_version} · ${current.created_by} · ${when(current.created_at)}` : "적용된 정책이 없습니다", [], "aops admin setup --only policy"),
    h("div", { class: "grid two", style: "align-items:start" },
      h("div", { class: "card pad" }, h("h2", {}, "평가·승인 규칙"),
        h("div", { class: "field" }, h("span", {}, "평가 방식"), segFor("validation_mode", [["mandatory", "필수"], ["optional", "선택"], ["exempt", "면제"]]),
          h("small", {}, "필수: 실패하면 반려 · 선택: 실패해도 승인자에게 · 면제: 평가 없이")),
        h("div", { class: "field" }, h("span", {}, "승인 방식"), segFor("approval_mode", [["required", "사람 승인"], ["optional", "선택"], ["auto", "자동 승인"]]),
          h("small", {}, "선택: SPEC 중요도 low이고 민감도 public·internal이면 자동, 아니면 승인자")),
        h("label", { class: "field" }, h("span", {}, "승인 그룹"), group, h("small", {}, "지정 승인자가 없을 때 승인")),
        h("label", { class: "row toggle" }, required, h("b", {}, "에이전트마다 지정 승인자 필수"),
          h("small", { class: "muted" }, "없으면 셀프 체크·평가 ERROR")),
        h("label", { class: "field" }, h("span", {}, "개발용 예외 승인자 (본인 요청도 승인)"), devApprovers,
          h("small", { class: (pol.dev_approvers || []).length ? "warn-text" : "" }, "혼자 시험할 때만. 승인마다 예외로 기록, 운영에서는 비웁니다")),
        isAdmin ? h("button", { class: "btn primary", onclick: save }, "새 정책 버전으로 적용")
          : h("div", { class: "note" }, "관리자만 바꿉니다")),
      h("div", { class: "card pad" }, h("h2", {}, "그 밖의 설정"),
        h("dl", { class: "kv" },
          h("dt", {}, "필요 승인 수"), h("dd", {}, pol.required_approvals ?? 1),
          h("dt", {}, "보안 등급"), h("dd", {}, (pol.security_levels || []).join(" · ")),
          h("dt", {}, "Git 사본"), h("dd", {}, git ? `${git.provider} · ${git.owner} · 연결 ${git.connection} · ${git.mode} (저장소 ${git.repo_prefix}<agent_id>)` : "꺼짐")),
        )),
    await reviewPromptsCard(isAdmin),
    h("div", { class: "card mt" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["버전", "상태", "평가", "승인", "승인 그룹", "올린 사람", "시각"].map((t) => h("th", {}, t)))),
      h("tbody", {}, page.items.map((p) => h("tr", {},
        h("td", { class: "mono cell-main" }, `v${p.policy_version}`), h("td", {}, p.status === "active" ? h("span", { class: "badge ok" }, "적용 중") : h("span", { class: "badge plain" }, "이전")),
        h("td", {}, MODE[p.policy.validation_mode] || p.policy.validation_mode), h("td", {}, MODE[p.policy.approval_mode] || p.policy.approval_mode),
        h("td", {}, p.policy.approver_group || "–"), h("td", {}, p.created_by), h("td", { class: "muted" }, when(p.created_at))))))));
}

const PROMPT_KIND = [["common", "공통"], ["skill", "스킬 기반"], ["code", "코드 기반"], ["no_code", "노코드"]];

// The four prompts of the Gate's content review: edit one, save it as a new version (admins); the evaluations record which they used.
async function reviewPromptsCard(isAdmin) {
  const data = await get("/admin/review-prompts");
  let kind = "common";
  const box = h("div", {});
  const draw = () => {
    const p = data.active[kind];
    const text = h("textarea", { class: "mono prompt", disabled: !isAdmin }, p.body);
    const note = h("input", { type: "text", placeholder: "바꾼 이유 (선택)", disabled: !isAdmin, style: "flex:1" });
    const items = h("ul", { class: "check-rules" });
    const preview = () => {
      const found = [];
      let inside = false;
      for (const line of text.value.split("\n")) {
        if (/^#{2,3}\s*체크리스트\s*$/.test(line.trim())) { inside = true; continue; }
        if (inside && line.startsWith("#")) break;
        const m = inside && line.match(/^\s*[-*]\s*`?([a-z][a-z0-9_.-]{1,63})`?\s*[:：]\s*(.+?)\s*$/);
        if (m) found.push([m[1], m[2]]);
      }
      fill(items, found.length ? found.map(([id, t]) => h("li", {}, h("span", { class: "rmark ok" }, "•"), h("div", {}, h("span", { class: "mono" }, id), ` ${t}`)))
        : h("li", {}, h("span", { class: "rmark bad" }, "✕"), h("div", {}, "'## 체크리스트' 아래에 '- <id>: <통과 조건>' 줄이 없습니다")));
    };
    text.addEventListener("input", preview);
    preview();
    const history = data.history.filter((r) => r.kind === kind);
    fill(box,
      h("div", { class: "row" }, h("b", {}, `${PROMPT_KIND.find((k) => k[0] === kind)[1]} · 지금 버전 v${p.version}`),
        h("span", { class: "muted" }, p.version ? `${p.created_by} · ${when(p.created_at)}${p.note ? ` · ${p.note}` : ""}` : "기본 프롬프트")),
      h("div", { class: "grid two mt-s" }, h("div", {}, text), h("div", {}, h("h3", {}, "체크리스트 미리 보기 (리포트 항목)"), items,
        h("p", { class: "muted mt" }, kind === "common" ? "모든 에이전트에 들어갑니다" : "공통 항목 뒤에 붙습니다 (ID는 공통과 달라야 함)"))),
      isAdmin ? h("div", { class: "row mt-s" }, note, h("button", { class: "btn primary", onclick: async () => {
        try {
          const saved = await post("/admin/review-prompts", { kind, body: text.value, note: note.value.trim() || null });
          toast(`평가 프롬프트 ${PROMPT_KIND.find((k) => k[0] === kind)[1]} v${saved.version} 저장`, "ok"); render();
        } catch (e) { fail(e); }
      } }, "새 버전으로 저장")) : h("div", { class: "note mt-s" }, "관리자만 바꿉니다"),
      history.length ? h("table", { class: "data mt" }, h("thead", {}, h("tr", {}, ["버전", "상태", "바꾼 이유", "올린 사람", "시각"].map((t) => h("th", {}, t)))),
        h("tbody", {}, history.map((r) => h("tr", {}, h("td", { class: "mono" }, `v${r.prompt_version}`), h("td", {}, r.status === "active" ? h("span", { class: "badge ok" }, "적용 중") : h("span", { class: "badge plain" }, "이전")),
          h("td", {}, r.note || "–"), h("td", {}, r.created_by), h("td", { class: "muted" }, when(r.created_at)))))) : null);
  };
  const tabs = h("div", { class: "tabs" });
  const drawTabs = () => fill(tabs, PROMPT_KIND.map(([k, label]) => h("button", { class: k === kind ? "on" : "", onclick: () => { kind = k; drawTabs(); draw(); } },
    label, h("span", { class: "n" }, `v${data.active[k].version}`))));
  drawTabs();
  draw();
  return h("div", { class: "card pad mt" }, h("h2", {}, "평가 프롬프트 (배포 전 내용 검토)"),
    h("p", { class: "muted" }, "공통 + 종류별 체크리스트로 모든 파일을 검토합니다. 저장하면 새 버전"),
    tabs, box);
}

// ── 안내: CLI ↔ 화면 ↔ Genie Code ───────────────────────────────────────────

const SCREEN = {
  "aops init": "+ 새 에이전트", "aops list": "에이전트", "aops load": `에이전트 → ${act("load")}`, "aops validate": `에이전트 → ${act("selfcheck")} · Genie 점검`,
  "aops evaluate": `에이전트 → ${act("evaluate")}`, "aops register": `에이전트 → ${act("register")} · 폴더·zip 등록`, "aops deploy": `에이전트 → ${act("deploy")}`,
  "aops deploy --cancel": "배포 요청 → 요청 취소", "aops gates": "배포 요청함", "aops approve": "배포 요청 → 승인", "aops reject": "배포 요청 → 반려",
  "aops promote": `에이전트 → ${act("promote")}`, "aops admin setup": "정책·평가 프롬프트 (정책만, 나머지는 CLI)",
};

// the routes this console uses where a command also has design-only routes
const SCREEN_ROUTES = {
  "aops init": ["POST /api/v1/projects/template"],
  "aops admin setup": ["GET /api/v1/admin/policies", "POST /api/v1/admin/policies"],
};

async function guidePage(root) {
  const rows = await get("/meta/commands");
  const working = rows.filter((r) => SCREEN[r.command]);
  const pcOnly = ["aops run \"<질문>\"", "aops session list", "aops session switch --harness", "aops session show"];
  root.replaceChildren(
    pageHead("CLI·Genie Code", "화면·PC CLI·Genie Code가 같은 aops 서버 API를 부릅니다. 어디서 하든 같은 기록이 남습니다", [], "aops --help"),
    h("div", { class: "grid three" },
      h("div", { class: "card pad" }, h("h2", {}, "이 화면"), h("p", { class: "muted" }, "브라우저에서 만들기·셀프 체크·등록·평가·배포·승인·권한·정책. Databricks 로그인 그대로 씁니다.")),
      h("div", { class: "card pad" }, h("h2", {}, "PC CLI"), h("p", { class: "muted" }, "aops run으로 Claude·Codex 하네스를 바꿔 가며 개발하고 같은 명령으로 등록·배포합니다."),
        h("div", { class: "cmd" }, "aops register --bump fix\naops deploy")),
      h("div", { class: "card pad" }, h("h2", {}, "Genie Code"), h("p", { class: "muted" }, "워크스페이스 스킬 aops: \"이 에이전트 등록해줘\", \"배포해줘\". 노트북에서 같은 CLI 코드가 내 신원으로 돕니다."),
        h("div", { class: "cmd" }, "에이전트 폴더 …/price-helper 를\nfix 버전으로 등록하고 배포해줘"))),
    h("div", { class: "card mt" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["CLI 명령", "이 화면", "API"].map((t) => h("th", {}, t)))),
      h("tbody", {}, working.map((r) => h("tr", {}, h("td", { class: "mono cell-main" }, r.command), h("td", {}, SCREEN[r.command]),
        h("td", { class: "mono muted", style: "font-size:12px" }, (SCREEN_ROUTES[r.command] || r.routes).map((x) => h("div", {}, x)))))))),
    h("div", { class: "card pad mt" }, h("h2", {}, "PC에서만 하는 것"),
      h("p", { class: "muted" }, "하네스(Claude·Codex) 실행은 PC에서만"),
      h("div", {}, pcOnly.map((c) => h("span", { class: "tag mono" }, c)))));
}

// ── start ──────────────────────────────────────────────────────────────────

async function start() {
  try {
    [state.version, state.me] = await Promise.all([get("/meta/version").catch(() => null), get("/meta/me")]);
    state.policy = await get("/admin/policies/current").then((p) => p.policy).catch(() => null);
  } catch (error) {
    document.getElementById("app").replaceChildren(h("div", { class: "page" }, h("div", { class: "card pad" },
      h("div", { class: "empty" }, h("b", {}, "aops 서버에 연결하지 못했습니다"), error.title || String(error), error.detail ? h("div", { class: "mt" }, error.detail) : null))));
    return;
  }
  await refreshCounts();
  window.addEventListener("hashchange", render);
  render();
}

start();
