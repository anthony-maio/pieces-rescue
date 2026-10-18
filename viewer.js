"use strict";
const $ = (selector) => document.querySelector(selector);
const E = (tag, cls, text) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
};
const button = (text, cls, action) => {
  const b = E("button", cls, text);
  b.type = "button";
  b.onclick = action;
  return b;
};
const kindNames = {
  workstreamSummaries: "Session summary",
  conversations: "Conversation",
  conversationMessages: "Message",
  workstreamEvents: "Capture",
  annotations: "Note",
  persons: "Person",
  tags: "Tag",
  websites: "Website",
  unindexed: "Not indexed",
};
const kindName = (kind) => kindNames[kind] || kind;
const excerpt = (value, length = 250) =>
  (value || "").slice(0, length).replace(/\s+/g, " ").trim();
const plain = (value) =>
  (value || "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[#*`_]/g, "");
const recordTitle = (r) =>
  r.title && !/^[0-9a-f-]{36}$/i.test(r.title)
    ? r.title
    : excerpt(plain(r.excerpt || r.body), 95) || kindName(r.kind) + " record";
const date = (value) => {
  if (!value) return "Undated";
  const d = new Date(value);
  return isNaN(d)
    ? value
    : d.toLocaleString("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }) + " UTC";
};
const dateOnly = (value) =>
  new Date(value + "T12:00:00Z").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
const addDays = (value, n) => {
  const d = new Date(value + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const state = {
  view: "atlas",
  data: null,
  from: "",
  to: "",
  first: "",
  last: "",
  selection: {},
  query: "",
  page: 0,
  items: [],
  more: false,
  total: 0,
  node: null,
  tab: "read",
  trail: [],
  trailIndex: -1,
  returnView: "browse",
  ticket: 0,
  nodeTicket: 0,
  atlasTicket: 0,
  graph: null,
  graphRequest: null,
  graphError: "",
  graphFilter: "",
  graphKind: "",
  graphDirection: "",
  preview: null,
  graphExpanded: new Set(),
  graphCollapsed: new Set(),
};
function message(text, error = false) {
  $("#status").textContent = text;
  $("#status").className = error ? "alert" : "";
}
async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  const d = await r.json();
  if (!r.ok) throw Error(d.error || "Request failed");
  return d;
}
function setView(view) {
  state.view = view;
  if (view !== "read") {
    state.nodeTicket++;
    history.replaceState(null, "", location.pathname + location.search);
  }
  $(".work").classList.toggle("reading", view === "read");
  for (const [id, name] of [
    ["atlas-view", "atlas"],
    ["browse-view", "browse"],
    ["reader-view", "read"],
    ["archive-view", "archive"],
  ])
    $("#" + id).hidden = !(
      view === name ||
      (name === "browse" && view === "search")
    );
  for (const b of document.querySelectorAll(".rail nav button")) {
    const active =
      b.id ===
      "nav-" +
        (view === "archive"
          ? "archive"
          : view === "search"
            ? "search"
            : "atlas");
    b.classList.toggle("active", active);
    b.setAttribute("aria-current", active ? "page" : "false");
  }
  $("#heading").textContent = {
    atlas: "Your memory, over time.",
    browse: "The memories behind the pattern.",
    search: "Find a memory.",
    read: "Memory reader",
    archive: "Your archive.",
  }[view];
  $("#subtitle").textContent = {
    atlas:
      "Explore a day, a topic, or a project. Then open the memories behind it.",
    browse: "Sessions and conversations from your selected dates.",
    search: "Search complete summaries, conversations, and original records.",
    read: "The recovered text, with its original records available.",
    archive: "The export receipt and indexed collections.",
  }[view];
}
function scale(value, max) {
  return value
    ? Math.max(1, Math.min(4, Math.ceil(Math.sqrt(value / max) * 4)))
    : 0;
}
function table(root, head, rows, action = null) {
  root.replaceChildren();
  const t = E("table", "");
  const h = E("thead", ""),
    hr = E("tr", "");
  for (const label of head) hr.append(E("th", "", label));
  h.append(hr);
  t.append(h);
  const body = E("tbody", "");
  for (const [index, row] of rows.entries()) {
    const tr = E("tr", "");
    for (const [column, value] of row.entries()) {
      const cell = E("td", "");
      if (column === 0 && action)
        cell.append(
          button(String(value), "table-link", () => action(row, index)),
        );
      else cell.textContent = String(value);
      tr.append(cell);
    }
    body.append(tr);
  }
  t.append(body);
  root.append(t);
}
async function loadAtlas(from = "", to = "") {
  const ticket = ++state.atlasTicket;
  message("Loading your memory atlas...");
  try {
    const data = await api("/api/atlas?" + new URLSearchParams({ from, to }));
    if (ticket !== state.atlasTicket) return;
    state.data = data;
    state.from = data.from;
    state.to = data.to;
    state.first = data.first;
    state.last = data.last;
    $("#range-from").value = data.from;
    $("#range-to").value = data.to;
    for (const id of ["range-from", "range-to"]) {
      $("#" + id).min = data.first;
      $("#" + id).max = data.last;
    }
    renderAtlas();
    message("");
  } catch (error) {
    if (ticket === state.atlasTicket) {
      message("Could not load the overview: " + error.message, true);
      $("#atlas-stats").replaceChildren(
        button("Retry", "back", () => loadAtlas(from, to)),
      );
    }
  }
}
function renderAtlas() {
  const d = state.data;
  const stats = $("#atlas-stats");
  stats.replaceChildren();
  for (const [label, value, note] of [
    ["Sessions", d.sessions, "Summaries and conversations"],
    ["Days remembered", d.days.length, "Days with a dated session"],
    ["Tagged sessions", d.tagged_sessions || 0, "With recorded summary tags"],
  ]) {
    const box = E("div", "atlas-stat");
    box.append(
      E("span", "", label),
      E("strong", "", value.toLocaleString()),
      E("small", "", note),
    );
    stats.append(box);
  }
  $("#atlas-note").textContent =
    "Dates use UTC. " +
    (d.undated
      ? `${d.undated.toLocaleString()} undated sessions are outside the date charts. `
      : "") +
    "Subject groups are detected from titles; topic tags come from the archive.";
  $("#browse-all").disabled = !d.sessions;
  renderCalendar(d);
  renderTopics(d);
  renderProjectMap(d);
}
function choose(selection) {
  state.selection = selection;
  state.query = "";
  state.page = 0;
  $("#query").value = "";
  $("#search-scope").value = "sessions";
  $("#kind").hidden = true;
  setView("browse");
  describeSelection();
  loadSessions();
  scrollTo({ top: 0, behavior: "instant" });
}
function describeSelection() {
  if ($("#search-scope").value === "raw") {
    $("#browse-title").textContent = "Search original records";
    $("#browse-description").textContent =
      "All indexed records, without date or topic filters.";
    $("#clear-selection").hidden = true;
    return;
  }
  const s = state.selection;
  $("#browse-title").textContent = s.day
    ? dateOnly(s.day)
    : s.topic || s.project || "Sessions in this range";
  $("#browse-description").textContent = [
    s.project ? "Detected title group" : s.topic ? "Recorded topic tag" : "",
    s.week ? "Week of " + dateOnly(s.week) : "",
    state.from && state.to
      ? dateOnly(state.from) + " to " + dateOnly(state.to)
      : "",
  ]
    .filter(Boolean)
    .join(" | ");
  $("#clear-selection").hidden = !Object.keys(s).length;
}
function renderCalendar(data) {
  const root = $("#calendar");
  root.replaceChildren();
  if (!data.first) {
    root.append(
      E(
        "p",
        "empty",
        "No dated sessions are available. Search the original records to explore this export.",
      ),
    );
    $("#calendar-caption").textContent = "";
    return;
  }
  const counts = new Map(data.days.map((row) => [row.day, row.sessions]));
  const max = Math.max(1, ...counts.values());
  const start = new Date(data.from + "T00:00:00Z");
  const offset = (start.getUTCDay() + 6) % 7;
  const first = addDays(data.from, -offset);
  const total =
    Math.round(
      (new Date(data.to + "T00:00:00Z") - new Date(first + "T00:00:00Z")) /
        86400000,
    ) + 1;
  const columns = Math.ceil(total / 7);
  const axis = E("div", "calendar-axis");
  for (const label of ["Mon", "", "Wed", "", "Fri", "", ""])
    axis.append(E("span", "", label));
  const grid = E("div", "calendar-grid");
  grid.style.gridTemplateColumns = `repeat(${columns},16px)`;
  grid.style.gridTemplateRows = "repeat(7,16px)";
  for (let i = 0; i < columns * 7; i++) {
    const day = addDays(first, i),
      count = counts.get(day) || 0;
    const b = button("", "day-cell level-" + scale(count, max), () =>
      choose({ day }),
    );
    b.disabled = !count;
    b.title = `${dateOnly(day)}: ${count} sessions`;
    b.setAttribute("aria-label", b.title);
    if (day < data.from || day > data.to) b.classList.add("outside");
    grid.append(b);
  }
  const labels = E("div", "calendar-months");
  labels.style.width = columns * 20 + "px";
  let previous = "";
  for (let week = 0; week < columns; week++) {
    const day = addDays(first, week * 7 + 3);
    const month = day.slice(0, 7);
    if (month !== previous) {
      const label = E(
        "span",
        "",
        new Date(day + "T12:00:00Z").toLocaleDateString("en-US", {
          month: "short",
          year: "numeric",
          timeZone: "UTC",
        }),
      );
      label.style.left = week * 20 + "px";
      labels.append(label);
      previous = month;
    }
  }
  const chart = E("div", "calendar-chart");
  chart.append(labels);
  const cells = E("div", "calendar-cells");
  cells.append(axis, grid);
  chart.append(cells);
  root.append(chart);
  $("#calendar-caption").textContent =
    dateOnly(data.from) +
    " to " +
    dateOnly(data.to) +
    " | Scroll for more dates when needed.";
  table(
    $("#calendar-table"),
    ["Day", "Sessions"],
    data.days.map((row) => [dateOnly(row.day), row.sessions]),
    (_, index) => choose({ day: data.days[index].day }),
  );
}
function renderTopics(data) {
  const root = $("#topic-chart");
  root.replaceChildren();
  if (!data.topics.length) {
    root.append(E("p", "empty", "No recorded topic tags in this date range."));
    table($("#topics-table"), ["Topic", "Sessions"], []);
    $("#topic-caption").textContent = "";
    return;
  }
  const max = Math.max(1, ...data.topics.flatMap((topic) => topic.weeks));
  const grid = E("div", "topic-grid");
  grid.style.gridTemplateColumns = `180px repeat(${data.weeks.length},22px) 50px`;
  grid.style.setProperty(
    "--topic-columns",
    `repeat(${data.weeks.length},22px)`,
  );
  grid.append(E("span", "heat-axis", "Topic"));
  for (let i = 0; i < data.weeks.length; i++) {
    const label = E(
      "span",
      "week-label",
      i % 4 === 0
        ? new Date(data.weeks[i] + "T12:00:00Z").toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            timeZone: "UTC",
          })
        : "",
    );
    label.title = "Week of " + dateOnly(data.weeks[i]);
    grid.append(label);
  }
  grid.append(E("span", "heat-total", "Total"));
  for (const topic of data.topics) {
    const name = button(topic.name, "topic-name", () =>
      choose({ topic: topic.name }),
    );
    name.title = topic.name;
    grid.append(name);
    topic.weeks.forEach((count, i) => {
      const b = button("", "heat-cell level-" + scale(count, max), () =>
        choose({ topic: topic.name, week: data.weeks[i] }),
      );
      b.disabled = !count;
      b.title = `${topic.name}, week of ${dateOnly(data.weeks[i])}: ${count} sessions`;
      b.setAttribute("aria-label", b.title);
      grid.append(b);
    });
    grid.append(E("span", "heat-total", topic.sessions.toLocaleString()));
  }
  root.append(grid);
  $("#topic-caption").textContent =
    "Top " +
    data.topics.length +
    " recorded tags in this range. A session can have several tags.";
  table(
    $("#topics-table"),
    ["Topic", "Sessions"],
    data.topics.map((topic) => [topic.name, topic.sessions]),
    (row) => choose({ topic: row[0] }),
  );
}
function renderProjectMap(data) {
  const root = $("#project-map");
  root.replaceChildren();
  const project = data.map_kind === "project";
  $("#map-title").textContent = project
    ? "Subjects seen together"
    : "Topics seen together";
  $("#map-description").textContent = project
    ? "Suggested groups from repeated phrases in session titles."
    : "Recorded tags that occur on the same summary.";
  const nodes = data.map_nodes || [];
  if (!nodes.length) {
    root.append(E("p", "empty", "Not enough grouped sessions to draw a map."));
    table(
      $("#map-table"),
      ["Group", "Also appears with", "Shared sessions"],
      [],
    );
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  const S = (tag, attrs = {}) => {
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  };
  const svg = S("svg", {
    viewBox: "0 0 660 430",
    role: "group",
    "aria-label": project ? "Detected title group map" : "Recorded topic map",
  });
  const positions = new Map(
    nodes.map((node, i) => {
      const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
      return [
        node.name,
        { x: 330 + 225 * Math.cos(angle), y: 210 + 145 * Math.sin(angle) },
      ];
    }),
  );
  const max = Math.max(1, ...data.connections.map((edge) => edge.sessions));
  for (const edge of data.connections) {
    const a = positions.get(edge.source),
      b = positions.get(edge.target);
    if (!a || !b) continue;
    const line = S("line", {
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      stroke: "#bccac1",
      "stroke-width": 1 + (4 * edge.sessions) / max,
    });
    const title = S("title");
    title.textContent = `${edge.source} and ${edge.target}: ${edge.sessions} shared sessions`;
    line.append(title);
    svg.append(line);
  }
  for (const node of nodes) {
    const pos = positions.get(node.name);
    const group = S("g", {
      class: "map-node",
      role: "button",
      tabindex: 0,
      "aria-label": `Browse ${project ? "project" : "topic"} ${node.name}: ${node.sessions} sessions`,
    });
    group.append(
      S("rect", {
        x: pos.x - 75,
        y: pos.y - 32,
        width: 150,
        height: 64,
        rx: 7,
      }),
    );
    const title = S("title");
    title.textContent = node.name;
    group.append(title);
    const label = S("text", {
      x: pos.x,
      y: pos.y - 8,
      "text-anchor": "middle",
    });
    let words = node.name.split(" "),
      lines = [""];
    for (const word of words) {
      const i = lines.length - 1;
      if ((lines[i] + " " + word).trim().length > 24 && lines[i])
        lines.push(word);
      else lines[i] = (lines[i] + " " + word).trim();
    }
    for (const [i, text] of lines.slice(0, 2).entries()) {
      const span = S("tspan", { x: pos.x, dy: i ? 14 : 0 });
      span.textContent = text.length > 24 ? text.slice(0, 21) + "..." : text;
      label.append(span);
    }
    group.append(label);
    const count = S("text", {
      x: pos.x,
      y: pos.y + 23,
      "text-anchor": "middle",
      class: "map-count",
    });
    count.textContent = node.sessions.toLocaleString() + " sessions";
    group.append(count);
    const action = () => choose({ [project ? "project" : "topic"]: node.name });
    group.onclick = action;
    group.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        action();
      }
    };
    svg.append(group);
  }
  root.append(svg);
  const list = E("div", "map-node-list");
  for (const node of nodes) {
    const b = button("", "map-list-row", () =>
      choose({ [project ? "project" : "topic"]: node.name }),
    );
    b.append(
      E("span", "", node.name),
      E("small", "", node.sessions.toLocaleString() + " sessions"),
    );
    list.append(b);
  }
  root.append(list);
  table(
    $("#map-table"),
    ["Group", "Also appears with", "Shared sessions"],
    data.connections.map((edge) => [edge.source, edge.target, edge.sessions]),
  );
}
function effectiveRange() {
  const s = state.selection;
  let from = state.view === "search" ? state.first : state.from,
    to = state.view === "search" ? state.last : state.to;
  if (s.week) {
    from = s.week > from ? s.week : from;
    const end = addDays(s.week, 6);
    to = end < to ? end : to;
  }
  return { from, to };
}
async function loadSessions(page = 0) {
  const ticket = ++state.ticket;
  state.page = page;
  message("Loading sessions...");
  const raw = $("#search-scope").value === "raw";
  try {
    let data;
    if (raw) {
      data = await api(
        "/api/search?" +
          new URLSearchParams({
            q: state.query,
            kind: $("#kind").value,
            page: String(page),
          }),
      );
      data.total = null;
    } else {
      const range = effectiveRange();
      data = await api(
        "/api/sessions?" +
          new URLSearchParams({
            ...range,
            ...state.selection,
            q: state.query,
            page: String(page),
          }),
      );
    }
    if (ticket !== state.ticket) return;
    state.items = data.items;
    state.more = data.more;
    state.total = data.total;
    renderResults();
    message(data.items.length ? "" : "No matching memories in this selection.");
  } catch (error) {
    if (ticket === state.ticket) {
      state.items = [];
      state.more = false;
      renderResults();
      message("Could not load memories: " + error.message, true);
    }
  }
}
function renderResults() {
  const root = $("#results");
  root.replaceChildren();
  $("#result-title").textContent =
    $("#search-scope").value === "raw"
      ? "Indexed records"
      : "Sessions and conversations";
  $("#result-count").textContent =
    state.total === null ? "" : state.total.toLocaleString() + " matches";
  $("#previous").disabled = state.page === 0;
  $("#next").disabled = !state.more;
  $("#page-number").textContent = "Page " + (state.page + 1);
  if (!state.items.length) {
    root.append(
      E("p", "empty", "No sessions to show. Try another date range or search."),
    );
    return;
  }
  for (const row of state.items) {
    const b = button("", "result", () => openNode(row.id));
    b.append(
      E("span", "kind", kindName(row.kind)),
      E("strong", "", recordTitle(row)),
      E("p", "", excerpt(plain(row.excerpt), 240)),
      E("time", "", date(row.created)),
    );
    root.append(b);
  }
}
async function openNode(id, index = null) {
  const ticket = ++state.nodeTicket;
  message("Opening memory...");
  try {
    const node = await api("/api/node?id=" + encodeURIComponent(id));
    if (ticket !== state.nodeTicket) return;
    if (state.view !== "read")
      state.returnView = state.view === "search" ? "search" : "browse";
    if (index === null) {
      if (state.trail[state.trailIndex]?.id !== id) {
        state.trail = state.trail.slice(0, state.trailIndex + 1);
        state.trail.push({ id, title: recordTitle(node) });
        state.trailIndex = state.trail.length - 1;
      }
    } else state.trailIndex = index;
    state.node = node;
    state.graph = null;
    state.graphError = "";
    state.preview = null;
    state.graphExpanded.clear();
    state.graphCollapsed.clear();
    state.graphFilter = "";
    state.graphKind = "";
    state.graphDirection = "";
    setView("read");
    setTab("read");
    history.replaceState(null, "", "#" + encodeURIComponent(id));
    renderNode();
    message("");
    scrollTo({ top: 0, behavior: "instant" });
  } catch (error) {
    if (ticket === state.nodeTicket)
      message("Could not open memory: " + error.message, true);
  }
}
function renderNode() {
  const node = state.node;
  const head = $("#detail-head");
  head.replaceChildren();
  head.append(
    E("span", "kind", kindName(node.kind)),
    E("h2", "", recordTitle(node)),
    E("div", "meta", date(node.created)),
  );
  const trail = $("#trail");
  trail.replaceChildren();
  const back = button("Previous memory", "back", () =>
    openNode(state.trail[state.trailIndex - 1].id, state.trailIndex - 1),
  );
  back.disabled = state.trailIndex <= 0;
  const forward = button("Next memory", "back", () =>
    openNode(state.trail[state.trailIndex + 1].id, state.trailIndex + 1),
  );
  forward.disabled = state.trailIndex >= state.trail.length - 1;
  trail.append(back, forward);
  renderPane();
}
function setTab(tab) {
  state.tab = tab;
  $("#reader-view").classList.toggle("mapping", tab === "map");
  for (const b of document.querySelectorAll("[data-tab]")) {
    b.classList.toggle("active", b.dataset.tab === tab);
    b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
  }
  renderPane();
}
// Source text never becomes HTML. Formatting creates only allowed DOM elements.
function inline(root, text) {
  const regex =
    /(\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*([^*\n]+)\*)/g;
  let start = 0;
  for (const match of text.matchAll(regex)) {
    root.append(document.createTextNode(text.slice(start, match.index)));
    let el;
    if (match[2]) el = E("strong", "", match[2]);
    else if (match[3]) el = E("code", "", match[3]);
    else if (match[4]) {
      let safe = false;
      try {
        safe = ["http:", "https:", "mailto:"].includes(
          new URL(match[5]).protocol,
        );
      } catch {}
      el = E(safe ? "a" : "span", "", match[4]);
      if (safe) {
        el.href = match[5];
        el.target = "_blank";
        el.rel = "noopener noreferrer";
      }
    } else el = E("em", "", match[6]);
    root.append(el);
    start = match.index + match[0].length;
  }
  root.append(document.createTextNode(text.slice(start)));
}
function markdown(root, text) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let paragraph = [],
    list = null,
    code = null;
  const flush = () => {
    if (paragraph.length) {
      const p = E("p", "");
      inline(p, paragraph.join("\n"));
      root.append(p);
      paragraph = [];
    }
    list = null;
  };
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flush();
      if (code) {
        root.append(E("pre", "code-block", code.join("\n")));
        code = null;
      } else code = [];
      continue;
    }
    if (code) {
      code.push(line);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    const bullet = /^\s*(?:[-*+]\s+|\d+\.\s+)(.+)$/.exec(line);
    if (heading) {
      flush();
      const h = E("h" + Math.min(4, heading[1].length + 1), "");
      inline(h, heading[2]);
      root.append(h);
    } else if (bullet) {
      if (paragraph.length) flush();
      if (!list) {
        list = E(/^\s*\d+\./.test(line) ? "ol" : "ul", "");
        root.append(list);
      }
      const item = E("li", "");
      inline(item, bullet[1]);
      list.append(item);
    } else if (!line.trim()) {
      flush();
    } else {
      if (list) list = null;
      paragraph.push(line);
    }
  }
  flush();
  if (code) root.append(E("pre", "code-block", code.join("\n")));
}
function renderPane() {
  const pane = $("#pane");
  pane.replaceChildren();
  const node = state.node;
  if (!node) return;
  if (state.tab === "read") {
    const body = E("div", "reading-body");
    markdown(
      body,
      (node.kind === "workstreamSummaries" &&
      !node.content_sources?.length &&
      node.body === node.title
        ? "This summary has a title but no readable annotation text in this export. Its original record and references are available above."
        : node.body) ||
        "No extracted text is available for this record. Open Original record to inspect it.",
    );
    pane.append(body);
    if (node.content_sources?.length)
      pane.append(
        E(
          "p",
          "content-receipt",
          `Recovered from ${node.content_sources.length} linked ${node.kind === "conversations" ? "messages" : "annotations"}.`,
        ),
      );
    if (node.missing_content)
      pane.append(
        E(
          "p",
          "alert",
          `${node.missing_content} referenced text records are missing from this export.`,
        ),
      );
  } else if (state.tab === "original") {
    pane.append(
      E("p", "meta", "Original decoded source record | " + node.id),
      E("pre", "raw", JSON.stringify(node.document, null, 2)),
    );
    if (node.content_sources?.length) {
      pane.append(E("h3", "", "Text source records"));
      for (const source of node.content_sources)
        pane.append(
          button(
            kindName(source.kind) + " | " + source.id,
            "source-record",
            () => openNode(source.id),
          ),
        );
    }
  } else if (state.graph) renderGraph(pane);
  else if (state.graphError)
    pane.append(
      E("p", "alert", state.graphError),
      button("Retry", "back", () => {
        state.graphError = "";
        renderPane();
      }),
    );
  else {
    pane.append(E("p", "empty", "Loading original references..."));
    loadGraph(node.id);
  }
}
async function loadGraph(id) {
  if (state.graphRequest?.id === id) return;
  const request = { id, ticket: state.nodeTicket };
  state.graphRequest = request;
  try {
    const graph = await api("/api/neighborhood?id=" + encodeURIComponent(id));
    if (state.node?.id === id && state.nodeTicket === request.ticket)
      state.graph = graph;
  } catch (error) {
    if (state.node?.id === id)
      state.graphError = "Could not load references: " + error.message;
  } finally {
    if (state.graphRequest === request) state.graphRequest = null;
    if (state.node?.id === id && state.tab === "map" && state.view === "read")
      renderPane();
  }
}
async function init() {
  try {
    const receipt = await api("/api/overview");
    $("#source").textContent = receipt.source;
    $("#receipt").textContent = "Export receipt: " + receipt.status;
    for (const row of receipt.collections) {
      const opt = E("option", "", kindName(row.collection));
      opt.value = row.collection;
      $("#kind").append(opt);
      const item = E("div", "archive-count");
      item.append(
        E("strong", "", row.indexed.toLocaleString()),
        E("span", "", kindName(row.collection)),
        E("small", "", row.collection),
      );
      $("#overview").append(item);
    }
  } catch (error) {
    message("Export metadata unavailable: " + error.message, true);
  }
  await loadAtlas();
  if (/^#[0-9a-f-]{36}$/i.test(location.hash)) openNode(location.hash.slice(1));
}
$("#nav-atlas").onclick = () => {
  setView("atlas");
  scrollTo(0, 0);
};
$("#nav-search").onclick = async () => {
  if (!state.data) await ready;
  if (!state.first) $("#search-scope").value = "raw";
  state.selection = {};
  state.query = "";
  $("#query").value = "";
  setView("search");
  describeSelection();
  loadSessions();
  $("#query").focus();
};
$("#nav-archive").onclick = () => setView("archive");
$("#browse-all").onclick = () => choose({});
$("#back-overview").onclick = () => {
  setView("atlas");
  state.from = state.data.from;
  state.to = state.data.to;
};
$("#back-results").onclick = () => {
  setView(state.returnView);
  describeSelection();
  if (!state.items.length) loadSessions();
};
$("#clear-selection").onclick = () => choose({});
$("#form").onsubmit = (event) => {
  event.preventDefault();
  state.query = $("#query").value.trim();
  loadSessions();
};
$("#search-scope").onchange = () => {
  if ($("#search-scope").value === "raw") {
    state.selection = {};
    setView("search");
  }
  $("#kind").hidden = $("#search-scope").value !== "raw";
  describeSelection();
  loadSessions();
};
$("#kind").onchange = () => loadSessions();
$("#previous").onclick = () => loadSessions(state.page - 1);
$("#next").onclick = () => loadSessions(state.page + 1);
for (const b of document.querySelectorAll("[data-tab]"))
  b.onclick = () => setTab(b.dataset.tab);
for (const b of document.querySelectorAll("[data-range]"))
  b.onclick = () => {
    if (!state.last) return;
    const from =
      b.dataset.range === "all"
        ? state.first
        : [state.first, addDays(state.last, 1 - Number(b.dataset.range))]
            .sort()
            .pop();
    for (const other of document.querySelectorAll("[data-range]"))
      other.setAttribute("aria-pressed", String(other === b));
    loadAtlas(from, state.last);
  };
$("#apply-range").onclick = () => {
  for (const b of document.querySelectorAll("[data-range]"))
    b.setAttribute("aria-pressed", "false");
  loadAtlas($("#range-from").value, $("#range-to").value);
};
for (const b of document.querySelectorAll("[data-table]"))
  b.onclick = () => {
    const root = $("#" + b.dataset.table + "-table");
    root.hidden = !root.hidden;
    b.textContent = root.hidden ? "Show table" : "Hide table";
    b.setAttribute("aria-expanded", String(!root.hidden));
  };
window.addEventListener("hashchange", () => {
  if (!location.hash) {
    setView("atlas");
    message("");
  } else if (
    /^#[0-9a-f-]{36}$/i.test(location.hash) &&
    (state.node?.id !== location.hash.slice(1) || state.view !== "read")
  ) {
    openNode(location.hash.slice(1));
  }
});
const ready = init();

function renderGraph(pane) {
  const graph = state.graph;
  const toolbar = E("div", "connection-toolbar");
  const filter = E("input", "connection-filter");
  filter.type = "search";
  filter.placeholder = "Filter titles, text, or relationships";
  filter.setAttribute("aria-label", "Filter connections");
  filter.value = state.graphFilter;
  const types = E("select", "");
  types.setAttribute("aria-label", "Connection record type");
  types.append(new Option("All connection types", ""));
  for (const kind of [
    ...new Set(graph.relationships.map((row) => row.kind)),
  ].sort())
    types.append(new Option(kindName(kind), kind));
  types.value = state.graphKind;
  const direction = E("select", "");
  direction.setAttribute("aria-label", "Reference direction");
  for (const [value, label] of [
    ["", "Both directions"],
    ["in", "Refers to this record"],
    ["out", "Referenced by this record"],
  ])
    direction.append(new Option(label, value));
  direction.value = state.graphDirection;
  toolbar.append(filter, types, direction);
  pane.append(toolbar);
  const summary = E("p", "connection-summary");
  summary.setAttribute("role", "status");
  pane.append(summary);
  const board = E("div", "connection-board");
  pane.append(board);
  function update() {
    const query = state.graphFilter.toLocaleLowerCase();
    const visible = graph.relationships.filter(
      (row) =>
        (!state.graphKind || row.kind === state.graphKind) &&
        (!state.graphDirection || row.direction === state.graphDirection) &&
        (!query ||
          [row.title, row.excerpt, row.predicate, row.id, kindName(row.kind)]
            .join(" ")
            .toLocaleLowerCase()
            .includes(query)),
    );
    const unique = new Set(graph.relationships.map((row) => row.id)).size;
    summary.textContent = `${visible.length} of ${graph.relationships.length} loaded references | ${unique} connected records`;
    board.replaceChildren();
    board.append(
      connectionColumn("in", visible),
      focusCard(),
      connectionColumn("out", visible),
    );
  }
  filter.oninput = () => {
    state.graphFilter = filter.value;
    update();
  };
  types.onchange = () => {
    state.graphKind = types.value;
    update();
  };
  direction.onchange = () => {
    state.graphDirection = direction.value;
    update();
  };
  function focusCard() {
    const root = E("aside", "focus-card");
    root.setAttribute("aria-label", "Focused record and connection preview");
    const record = state.node;
    root.append(
      E("div", "focus-label", "RECORD IN FOCUS"),
      E("span", "kind", kindName(record.kind)),
      E("h3", "", recordTitle(record)),
    );
    if (record.created) root.append(E("time", "meta", date(record.created)));
    root.append(
      E(
        "p",
        "focus-excerpt",
        excerpt(record.body, 600) ||
          "No extracted text. The original document is available.",
      ),
    );
    root.append(button("Read full record", "primary", () => setTab("read")));
    const preview = E("div", "preview-box");
    preview.tabIndex = -1;
    if (state.preview) {
      const row = state.preview;
      preview.append(
        E("div", "focus-label", "CONNECTION PREVIEW"),
        E("span", "kind", kindName(row.kind)),
        E("h4", "", recordTitle(row)),
      );
      preview.append(
        E(
          "p",
          "relation-path",
          row.direction === "in"
            ? "This record refers to the focused record."
            : "The focused record refers to this record.",
        ),
        E("code", "predicate", row.predicate),
      );
      if (row.created) preview.append(E("p", "meta", date(row.created)));
      preview.append(
        E("p", "preview-excerpt", row.excerpt || "No extracted preview text."),
      );
      if (row.kind === "unindexed")
        preview.append(
          E(
            "p",
            "meta",
            "The reference is preserved, but its target is not in this index.",
          ),
        );
      else
        preview.append(
          button("Follow this record", "primary", () => openNode(row.id)),
        );
      preview.append(
        button("Close preview", "text-button", () => {
          state.preview = null;
          update();
        }),
      );
    } else
      preview.append(
        E("div", "focus-label", "PREVIEW A CONNECTION"),
        E(
          "p",
          "meta",
          "Select a card to read its preview here. Follow a record to make it the new focus; Back returns to the previous one.",
        ),
      );
    root.append(preview);
    return root;
  }
  function connectionColumn(dir, rows) {
    const all = graph.relationships.filter((row) => row.direction === dir);
    const column = E(
      "section",
      "connection-column " + (dir === "in" ? "incoming" : "outgoing"),
    );
    column.setAttribute(
      "aria-label",
      dir === "in" ? "Incoming references" : "Outgoing references",
    );
    const head = E("div", "column-heading");
    head.append(
      E("span", "direction-label", dir === "in" ? "INCOMING" : "OUTGOING"),
      E(
        "h3",
        "",
        dir === "in" ? "Refers to this record" : "This record refers to",
      ),
      E("p", "meta", `${all.length} loaded references`),
    );
    column.append(head);
    const set = rows.filter((row) => row.direction === dir);
    if (!set.length) {
      column.append(
        E(
          "p",
          "column-empty",
          all.length
            ? "No connections match these filters."
            : "No recorded references in this direction.",
        ),
      );
      return column;
    }
    const groups = new Map();
    for (const row of set) {
      if (!groups.has(row.kind)) groups.set(row.kind, []);
      groups.get(row.kind).push(row);
    }
    for (const [kind, records] of groups) {
      const group = E("details", "connection-group");
      const groupKey = dir + ":" + kind;
      group.open = !state.graphCollapsed.has(groupKey);
      group.ontoggle = () => {
        if (group.isConnected) {
          if (group.open) state.graphCollapsed.delete(groupKey);
          else state.graphCollapsed.add(groupKey);
        }
      };
      const label = E("summary", "");
      label.append(
        E("span", "", kindName(kind)),
        E("span", "group-count", String(records.length)),
      );
      group.append(label);
      const list = E("div", "connection-cards");
      group.append(list);
      let limit = state.graphExpanded.has(groupKey) ? records.length : 3;
      function draw() {
        list.replaceChildren();
        for (const row of records.slice(0, limit)) {
          const card = button("", "connection-card", () => {
            state.preview = row;
            update();
            const target = board.querySelector(".preview-box");
            target.focus({ preventScroll: true });
            target.scrollIntoView({ block: "nearest", behavior: "instant" });
          });
          card.classList.toggle("selected", state.preview === row);
          card.setAttribute("aria-pressed", String(state.preview === row));
          card.setAttribute("aria-label", "Preview " + recordTitle(row));
          card.append(E("strong", "", recordTitle(row)));
          if (row.created) card.append(E("time", "", date(row.created)));
          card.append(
            E(
              "p",
              "",
              excerpt(row.excerpt, 145) || "No extracted preview text.",
            ),
            E("code", "predicate", row.predicate),
          );
          if (row.kind === "unindexed")
            card.append(
              E("span", "unavailable", "Referenced record is not indexed"),
            );
          list.append(card);
        }
        if (records.length > 3)
          list.append(
            button(
              limit < records.length
                ? `Show ${records.length - limit} more`
                : "Show fewer",
              "show-more",
              () => {
                limit = limit < records.length ? records.length : 3;
                if (limit > 3) state.graphExpanded.add(groupKey);
                else state.graphExpanded.delete(groupKey);
                draw();
              },
            ),
          );
      }
      draw();
      column.append(group);
    }
    return column;
  }
  update();
  const note = graph.truncated
    ? "This neighborhood loads up to 60 references per direction, sorted by predicate and ID. More references may exist."
    : "All references returned for this neighborhood are available in the groups above.";
  pane.append(
    E(
      "p",
      "legend",
      note + " Connections are UUID references stored in the archive.",
    ),
  );
}
