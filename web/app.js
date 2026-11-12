/* CFB Engagement Tracker UI. Attendance comes from /api/season and /api/school.
   Business headlines load separately from /api/school/{slug}/business-news.
   Power valuations load from /api/valuations.
   Marketing approaches load from /api/marketing.
   Football revenue loads from /api/revenue/{slug} when a school page opens.
   Football campaigns load from /api/campaigns/{slug}?year= when that tab is open.
   Bowl games and the projected CFP bracket load from /api/bowls. */

const view = document.querySelector("#view");
const banner = document.querySelector("#banner");
const seasonLabel = document.querySelector("#season-label");

let payload = null;
let schoolsBySlug = {};
let charts = [];
let historyToken = 0;
let newsToken = 0;
let growthToken = 0;
const businessNewsBySlug = new Map();
const seasonPayloads = new Map();
const filters = { query: "", tier: "all", sort: "ap", span: 1 };
const valuationView = { sort: "valuation", conference: "all" };
let valuationsPayload = null;
let valuationsToken = 0;
const marketingPayloads = new Map();
let marketingYear = 2025;
let marketingToken = 0;
const revenueBySlug = new Map();
const revenueInflight = new Set();
const campaignsByKey = new Map();
let campaignToken = 0;
let bowlsPayload = null;
let bowlsToken = 0;

const motionApi = window.Motion || null;
const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
const countedStats = new Set();
let motionFromRender = false;
let lastMotionKey = "";
let lastShellKey = "";
let valuationReorder = false;
const scrollByPage = new Map();
let lastPage = "";
let traversing = false;

// A new page opens at the top; back/forward returns to where that page was left.
// Browsers without the Navigation API open every page at the top.
history.scrollRestoration = "manual";
if (window.navigation) {
  window.navigation.addEventListener("navigate", (event) => {
    traversing = event.navigationType === "traverse";
  });
}

const VALUATION_CONFERENCES = [
  ["all", "All"],
  ["SEC", "SEC"],
  ["Big Ten", "Big Ten"],
  ["Big 12", "Big 12"],
  ["ACC", "ACC"],
  ["Independent", "Independent"],
];

const RANGE_LAST = "last";
const RANGE_OPTIONS = [
  [1, "This season"],
  [RANGE_LAST, "Last season"],
  [5, "Last 5 seasons"],
  [10, "Last 10 seasons"],
];

// One chart look on every page: Plex type, muted axis text, hairline grid, ink tooltips.
// The hex values mirror the --ink-soft, --line, --line-strong and --ink tokens in styles.css.
if (window.Chart) {
  Object.assign(Chart.defaults, { color: "#5b616b", borderColor: "#e1e2dd" });
  Object.assign(Chart.defaults.font, { family: '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif', size: 12 });
  Chart.defaults.scale.border.color = "#b9bbb5";
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: "#111418",
    padding: 10,
    cornerRadius: 2,
    displayColors: false,
    titleFont: { weight: "600" },
  });
}
const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact" });

document.addEventListener("DOMContentLoaded", boot);
window.addEventListener("hashchange", render);

async function boot() {
  try {
    const response = await fetch("/api/season");
    const body = await response.json();
    if (!response.ok || body.error) {
      renderError(body.message || "The season could not be loaded.");
      return;
    }
    payload = body;
    schoolsBySlug = Object.fromEntries(payload.schools.map((school) => [school.slug, school]));
    applyChrome();
    render();
  } catch (_error) {
    renderError("The season could not be loaded. If you are serving the site, check that it is still running.");
  }
}

function pollLabel(meta) {
  if (meta.public_poll === "CFP") {
    const week = meta.public_week ? `week ${meta.public_week}` : "latest release";
    return `CFP rankings, ${week}`;
  }
  if (meta.ap_week) {
    return `AP Top 25, week ${meta.ap_week}${meta.ap_season_type === "postseason" ? " postseason" : ""}`;
  }
  return meta.rank_note || "AP poll not in this cache";
}

function publicRankLabel(school) {
  if (!school) return null;
  if (school.public_poll === "CFP") {
    return school.public_rank != null ? `CFP ${school.public_rank}` : null;
  }
  const rank = school.public_rank != null ? school.public_rank : school.ap_rank;
  return rank != null ? `AP ${rank}` : null;
}

function rankPill(school, withId) {
  const label = publicRankLabel(school);
  const props = {
    class: label ? "pill rank" : "pill unranked",
    text: label || "Unranked",
  };
  if (withId) props.id = "public-rank-pill";
  return h("span", props);
}

function applyChrome() {
  const meta = payload.meta;
  const poll = pollLabel(meta);
  const source = meta.synthetic ? "Sample data" : "College Football Data";
  seasonLabel.textContent = `${meta.season} season · ${poll} · ${source}`;
  document.title = `CFB Engagement Tracker · ${meta.season}`;
  if (meta.banner) {
    banner.hidden = false;
    fill(banner,
      h("strong", { text: "Sample data. " }),
      document.createTextNode(meta.banner)
    );
  } else {
    banner.hidden = true;
    banner.replaceChildren();
  }
}

function render() {
  if (!payload) return;
  destroyCharts();
  const route = currentRoute();
  setNav(route.name === "school" ? "home" : route.name);
  const page = route.name === "school" ? `school:${route.slug}` : route.name;
  const pageChanged = lastPage && page !== lastPage;
  if (pageChanged) scrollByPage.set(lastPage, window.scrollY);
  lastPage = page;
  const shellKey = motionShellKey(route);
  const motionKey = motionViewKey(route);
  const shellChanged = shellKey !== lastShellKey;
  const viewChanged = motionKey !== lastMotionKey;
  lastShellKey = shellKey;
  lastMotionKey = motionKey;
  motionFromRender = true;
  try {
    if (route.name === "analysis") renderAnalysis();
    else if (route.name === "valuations") renderValuations();
    else if (route.name === "marketing") renderMarketing();
    else if (route.name === "bowls") renderBowls();
    else if (route.name === "school") renderSchool(route.slug, route.view, route.year);
    else renderHome();
  } finally {
    motionFromRender = false;
  }
  if (pageChanged) window.scrollTo({ top: traversing ? scrollByPage.get(page) || 0 : 0, behavior: "instant" });
  if (shellChanged) motionSwap(view);
  else if (viewChanged) {
    motionSwap(document.getElementById("school-body"));
    motionSwap(document.getElementById("season-pins"));
  }
  if (shellChanged || viewChanged || route.name === "home") motionLists(view, !(shellChanged || viewChanged));
  motionCounts(view);
  view.focus({ preventScroll: true });
}

function currentRoute() {
  const hash = decodeURIComponent((location.hash || "#/").replace(/^#/, ""));
  if (hash === "/analysis") return { name: "analysis" };
  if (hash === "/valuations") return { name: "valuations" };
  if (hash === "/marketing") return { name: "marketing" };
  if (hash === "/bowls") return { name: "bowls" };
  const match = hash.match(/^\/schools\/([^/]+)/);
  if (match) {
    const rest = hash.slice(match[0].length).replace(/\/+$/, "");
    let pageView = "attendance";
    let year = 2026;
    if (rest === "/revenue") pageView = "revenue";
    else if (rest === "/campaigns" || rest === "/campaigns/2026") pageView = "campaigns";
    else if (rest === "/campaigns/2025") {
      pageView = "campaigns";
      year = 2025;
    }
    return {
      name: "school",
      slug: match[1],
      view: pageView,
      year,
    };
  }
  return { name: "home" };
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.dataset.nav === name) {
      link.setAttribute("aria-current", "page");
      // On phones the tab strip scrolls sideways; keep the current tab in view.
      link.parentElement.scrollLeft = link.offsetLeft - 16;
    } else link.removeAttribute("aria-current");
  });
}

function renderHome() {
  const meta = payload.meta;
  const sections = payload.orders[filters.sort] || payload.orders.ap;
  const query = filters.query.trim().toLowerCase();
  const visibleSections = sections
    .map((section) => {
      const schools = section.slugs
        .map((slug) => schoolsBySlug[slug])
        .filter(Boolean)
        .filter((school) => filters.tier === "all" || school.tier === filters.tier)
        .filter((school) => !query || schoolMatches(school, query));
      return { ...section, schools };
    })
    .filter((section) => section.schools.length);

  const rankName = meta.public_poll === "CFP" ? "CFP" : "AP";
  const intro = filters.sort === "record"
    ? `Sorted by season record. Ties break toward the latest ${rankName} rank, and unranked schools follow ranked schools when the record is the same.`
    : `Sorted by the latest ${rankName === "CFP" ? "CFP rankings" : "AP Top 25"}. Unranked schools follow the ranked ones. Record breaks ties.`;

  const tierSeen = new Set();
  const blocks = [];
  visibleSections.forEach((section) => {
    if (!tierSeen.has(section.tier)) {
      tierSeen.add(section.tier);
      const note = section.tier === "Power 4"
        ? "SEC, Big Ten, Big 12, and ACC."
        : "Every other FBS conference, including independents when the feed lists them.";
      const title = section.tier === "Power 4" ? "Power 4" : "Group of 5 and other FBS";
      blocks.push(h("div", { class: "tier-block" }, [
        h("h2", { text: title }),
        h("p", { class: "tier-note", text: note }),
      ]));
    }
    const anchor = "conf-" + slugify(section.conference);
    blocks.push(h("section", { class: "conference", id: anchor }, [
      h("h3", {}, [
        document.createTextNode(section.conference),
        h("span", { text: `${section.schools.length} schools` }),
      ]),
      h("div", { class: "grid" }, section.schools.map(schoolCard)),
    ]));
  });

  const jumpLinks = visibleSections.map((section) => {
    const anchor = "conf-" + slugify(section.conference);
    return h("button", {
      type: "button",
      text: section.conference,
      onclick: () => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }),
    });
  });

  fill(view,
    kicker("Schools"),
    h("h1", { class: "lede", text: "Home crowds for every FBS program, grouped by conference." }),
    h("p", { class: "sublede", text: `${intro} Each card pins the season average and the last home game. A dash means that figure is not in the feed.` }),
    h("div", { class: "toolbar" }, [
      h("input", {
        class: "search",
        type: "search",
        placeholder: "Search schools",
        value: filters.query,
        "aria-label": "Search schools",
        oninput: (event) => {
          filters.query = event.target.value;
          renderHome();
          const field = view.querySelector(".search");
          if (field) {
            field.focus();
            const end = field.value.length;
            field.setSelectionRange(end, end);
          }
        },
      }),
      segment("Tier", [
        ["all", "All FBS"],
        ["Power 4", "Power 4"],
        ["Group of 5", "Group of 5"],
      ], filters.tier, (value) => {
        filters.tier = value;
        render();
      }),
      segment("Sort", [
        ["ap", meta.public_poll === "CFP" ? "CFP rank" : "AP rank"],
        ["record", "Record"],
      ], filters.sort, (value) => {
        filters.sort = value;
        render();
      }),
    ]),
    jumpLinks.length ? h("nav", { class: "jumps", "aria-label": "Conferences" }, jumpLinks) : null,
    blocks.length
      ? h("div", {}, blocks)
      : h("p", { class: "empty", text: "No schools match that search." }),
    h("p", { class: "muted", text: `${meta.team_count} schools in the ${meta.season} cache.` })
  );
  if (!motionFromRender) {
    motionLists(view, true);
    motionCounts(view);
  }
}

function schoolCard(school) {
  const rank = rankPill(school);
  const missing = school.missing_attendance_games
    ? h("span", { class: "pill warn", text: `${school.missing_attendance_games} attendance missing` })
    : null;
  return h("a", {
    class: "card",
    href: `#/schools/${encodeURIComponent(school.slug)}`,
    style: `--rail:${school.color}`,
  }, [
    h("div", { class: "card-head" }, [
      mark(school, 48),
      h("div", {}, [
        h("h3", { text: school.school }),
        h("p", { class: "mascot", text: [school.mascot, school.conference].filter(Boolean).join(" · ") }),
      ]),
    ]),
    h("div", { class: "pills" }, [
      h("span", { class: "pill", text: school.record || "Record unavailable" }),
      rank,
      school.pro_shared_stadium ? h("span", { class: "pill pro", text: "NFL stadium" }) : null,
      missing,
    ]),
    h("p", { class: "capacity", text: capacityLine(school) }),
    attendancePins(school),
  ]);
}

function attendancePins(school, scope) {
  const id = `${scope || (payload && payload.meta ? payload.meta.season : "season")}:${school.slug || school.school}`;
  const avgText = seasonAvgValue(school);
  const meta = seasonAvgMeta(school);
  const avgCount = avgText === "—" || school.avg_home_attendance == null
    ? null
    : { key: `${id}:avg`, value: Number(school.avg_home_attendance), kind: "int" };
  const fillCount = school.avg_capacity_pct == null || !String(meta).endsWith("% full")
    ? null
    : { key: `${id}:fill`, value: Number(school.avg_capacity_pct), kind: "pct-full" };
  const lastText = lastHomeValue(school);
  const lastCount = lastText === "—" || school.last_home_attendance == null
    ? null
    : { key: `${id}:last`, value: Number(school.last_home_attendance), kind: "int" };
  return h("div", { class: "pins" }, [
    pin("Season avg", avgText, meta, { value: avgCount, meta: fillCount }),
    pin("Last home", lastText, lastHomeMeta(school), { value: lastCount }),
  ]);
}

function pin(label, value, meta, counts) {
  const strong = { text: value };
  const metaProps = { class: "pin-m", text: meta };
  if (counts) {
    applyCount(strong, counts.value);
    applyCount(metaProps, counts.meta);
  }
  return h("div", { class: "pin" }, [
    h("span", { class: "pin-k", text: label }),
    h("strong", strong),
    h("span", metaProps),
  ]);
}

function seasonAvgValue(school) {
  if (isCovidOmitted(school)) return "—";
  if (school.avg_home_attendance == null) return "—";
  return formatInt(Math.round(school.avg_home_attendance));
}

function seasonAvgMeta(school) {
  if (isCovidOmitted(school)) return "Omitted · COVID";
  if (!school.reported_home_games) {
    if (school.last_home_attendance_status === "not_reported" || school.missing_attendance_games) {
      return "Not reported";
    }
    return "Awaiting attendance";
  }
  if (school.avg_capacity_pct == null) return `${school.reported_home_games} reported`;
  return `${formatPct(school.avg_capacity_pct)} full`;
}

function lastHomeValue(school) {
  if (school.last_home_attendance_status !== "reported" || school.last_home_attendance == null) return "—";
  return formatInt(school.last_home_attendance);
}

function lastHomeMeta(school) {
  const status = school.last_home_attendance_status;
  const opponent = school.last_home_opponent ? `vs ${school.last_home_opponent}` : "";
  const when = formatDate(school.last_home_date);
  if (status === "reported") return [opponent, when].filter(Boolean).join(" · ") || "Reported";
  if (status === "not_reported") return ["Not reported", opponent].filter(Boolean).join(" · ");
  return "Awaiting attendance";
}

function renderSchool(slug, pageView, campaignYear) {
  const school = schoolsBySlug[slug];
  if (!school) {
    fill(view,
      h("a", { class: "back", href: "#/", text: "All schools" }),
      h("div", { class: "error" }, [
        h("h2", { text: "School not in this cache" }),
        h("p", { text: "That program is not in the loaded season." }),
      ])
    );
    return;
  }
  const showRevenue = revenuePageRequested(slug, pageView);
  if (showRevenue) {
    renderRevenue(school, slug);
    return;
  }
  if (pageView === "campaigns") {
    renderCampaigns(school, slug, campaignYear || 2026);
    return;
  }
  const token = ++historyToken;
  const endYear = Number(payload.meta.season);
  const nodes = [
    h("a", { class: "back", href: "#/", text: "All schools" }),
    schoolIdentity(school),
    schoolViewToggle(slug, "attendance"),
    h("div", { class: "range-bar" }, [
      segment("Attendance range", RANGE_OPTIONS, filters.span, (value) => {
        filters.span = value === RANGE_LAST ? RANGE_LAST : Number(value);
        render();
      }),
      h("p", { class: "muted range-hint", text: rangeHint(endYear, filters.span) }),
    ]),
    h("div", { id: "school-body", "aria-live": "polite" }),
    businessNewsSection(slug),
  ];
  fill(view, ...nodes);
  if (!revenueBySlug.has(slug)) ensureRevenue(slug);
  if (filters.span === 1) {
    fillSeasonBody(school, endYear);
    return;
  }
  if (filters.span === RANGE_LAST) {
    const year = previousSeasonYear(endYear);
    const body = document.getElementById("school-body");
    body.replaceChildren(h("p", { class: "loading", text: `Loading ${year} home attendance…` }));
    loadPriorSeason(school, year, token);
    return;
  }
  const bounds = historyBounds(filters.span, endYear);
  const body = document.getElementById("school-body");
  body.replaceChildren(h("p", { class: "loading", text: `Loading ${bounds.start}–${bounds.end} home attendance…` }));
  loadHistory(slug, school, bounds, token);
}

function schoolIdentity(school) {
  return h("div", { class: "school-head", style: `--rail:${school.color}` }, [
      mark(school, 84),
      h("div", {}, [
        h("p", { class: "school-conf", text: `${school.conference} · ${school.tier}` }),
        h("h2", { text: school.school }),
        h("div", { class: "pills" }, [
          h("span", { class: "pill", text: school.record || "Record unavailable" }),
          school.pro_shared_stadium ? h("span", { class: "pill pro", text: "NFL stadium" }) : null,
          filters.span === RANGE_LAST
            ? h("span", { id: "public-rank-pill", class: "pill quiet", text: "Rank" })
            : rankPill(school, true),
          school.recent_record
            ? h("span", { class: "pill quiet", text: `Last ${school.recent_form.games}: ${school.recent_record}` })
            : null,
        ]),
        h("p", { id: "public-rank-note", class: "muted", text: filters.span === RANGE_LAST ? "" : (payload.meta.rank_note || "") }),
        h("p", { class: "capacity", text: stadiumLine(school) }),
        school.pro_shared_stadium
          ? h("p", { class: "pro-note", text: school.pro_stadium_note || "NFL stadium. Official capacity fill is not compared with on-campus stadiums." })
          : null,
        h("div", { id: "season-pins" }, [
          filters.span === RANGE_LAST ? null : attendancePins(school),
        ]),
      ]),
    ]);
}

function revenuePageRequested(slug, pageView) {
  if (pageView !== "revenue") return false;
  if (revenueBySlug.has(slug) && !revenueBySlug.get(slug)) {
    const next = `#/schools/${encodeURIComponent(slug)}`;
    if (location.hash !== next) history.replaceState(null, "", next);
    return false;
  }
  return true;
}

function renderRevenue(school, slug) {
  const data = revenueBySlug.get(slug);
  const nodes = [
    h("a", { class: "back", href: "#/", text: "All schools" }),
    schoolIdentity(school),
    schoolViewToggle(slug, "revenue"),
  ];
  if (!data) {
    nodes.push(h("p", { class: "loading", text: "Loading football revenue…" }));
    fill(view, ...nodes);
    ensureRevenue(slug);
    return;
  }
  nodes.push(
    h("section", { class: "panel", id: "football-revenue" }, [
      h("h3", { text: "Football revenue" }),
      h("p", { class: "muted", text: "Reported football revenue by fiscal year. A blank year was not in the filing and is not estimated. The 2020 bar is the COVID season: its change is omitted, and 2021 is compared with 2019." }),
      revenueStats(data),
      h("div", { class: "chart-wrap" }, [h("canvas", { id: "revenue-chart" })]),
      revenueFootnotes(data),
    ]),
    h("section", { class: "panel" }, [
      h("h3", { text: "Year by year" }),
      h("div", { class: "table-wrap" }, [revenueTable(data.years || [])]),
    ])
  );
  fill(view, ...nodes);
  drawRevenueChart(school, data);
}

function schoolViewOptions(slug) {
  const options = [["attendance", "Home Attendance"]];
  if (revenueBySlug.get(slug)) options.push(["revenue", "Revenue"]);
  options.push(["campaigns", "Campaigns"]);
  return options;
}

function schoolViewToggle(slug, pageView) {
  const current = pageView === "revenue" || pageView === "campaigns" ? pageView : "attendance";
  return h("div", { class: "view-toggle", id: "school-view-toggle" }, [
    segment("School view", schoolViewOptions(slug), current, (value) => {
      const base = `#/schools/${encodeURIComponent(slug)}`;
      if (value === "revenue") location.hash = `${base}/revenue`;
      else if (value === "campaigns") location.hash = `${base}/campaigns`;
      else location.hash = base;
    }),
  ]);
}

function renderCampaigns(school, slug, year) {
  const selected = year === 2025 ? 2025 : 2026;
  fill(view,
    h("a", { class: "back", href: "#/", text: "All schools" }),
    schoolIdentity(school),
    schoolViewToggle(slug, "campaigns"),
    h("section", { class: "panel", id: "football-campaigns" }, [
      h("div", { class: "range-bar" }, [
        segment("Campaign season", [[2026, "2026"], [2025, "2025"]], selected, (value) => {
          const base = `#/schools/${encodeURIComponent(slug)}/campaigns`;
          location.hash = Number(value) === 2025 ? `${base}/2025` : base;
        }),
        h("p", { class: "muted range-hint", text: "Football marketing and fan campaigns. Game previews and facility news are not listed." }),
      ]),
      h("div", { id: "school-body", "aria-live": "polite" }, [
        h("p", { class: "loading", text: `Loading ${selected} football campaigns…` }),
      ]),
    ])
  );
  if (!revenueBySlug.has(slug)) ensureRevenue(slug);
  const cached = campaignsByKey.get(`${slug}:${selected}`);
  if (cached) fillCampaigns(selected, cached);
  else loadCampaigns(slug, selected);
}

function fillCampaigns(year, data) {
  const body = document.getElementById("school-body");
  if (!body) return;
  const items = Array.isArray(data.items) ? data.items : [];
  if (!items.length) {
    body.replaceChildren(h("p", { class: "promo-missing", text: data.empty_message || "Not yet reviewed" }));
  } else {
    body.replaceChildren(h("div", { class: "campaign-list" }, items.map(campaignCard)));
  }
  afterPartial(body);
}

async function loadCampaigns(slug, year) {
  const token = ++campaignToken;
  let data = { items: [], empty_message: "Not yet reviewed", year };
  try {
    const response = await fetch(`/api/campaigns/${encodeURIComponent(slug)}?year=${year}`);
    const body = await response.json();
    if (response.ok && body && !body.error) data = body;
    else data = { items: [], empty_message: "Campaigns could not be loaded.", year };
  } catch (_error) {
    data = { items: [], empty_message: "Campaigns could not be loaded.", year };
  }
  campaignsByKey.set(`${slug}:${year}`, data);
  const route = currentRoute();
  if (token !== campaignToken || route.name !== "school" || route.slug !== slug || route.view !== "campaigns") return;
  if ((route.year || 2026) !== year) return;
  fillCampaigns(year, data);
}

function campaignCard(item) {
  const pills = [h("span", { class: "pill", text: campaignTypeLabel(item.type) })];
  if (item.type === "theme_night") pills.push(h("span", { class: "pill announced", text: "Announced" }));
  return h("article", { class: "campaign" }, [
    h("div", { class: "pills" }, pills),
    h("h3", { text: item.title || "Football campaign" }),
    campaignGame(item.game),
    h("p", { text: item.description || "" }),
    h("p", { class: "promo-source" }, [
      item.source_url
        ? h("a", {
          href: item.source_url,
          target: "_blank",
          rel: "noopener noreferrer",
          text: item.source_name || "Source",
        })
        : h("span", { text: item.source_name || "Source" }),
      document.createTextNode(item.date ? ` · ${formatIsoDate(item.date)}` : ""),
    ]),
  ]);
}

function campaignGame(game) {
  if (!game || !game.opponent) return null;
  const where = game.home ? `Home vs ${game.opponent}` : `At ${game.opponent}`;
  return h("p", { class: "muted campaign-game", text: where });
}

function campaignTypeLabel(type) {
  const labels = {
    theme_night: "Theme night",
    giveaway: "Giveaway",
    ticket_deal: "Ticket deal",
    student_promo: "Student promo",
    community: "Community",
    sponsor_activation: "Sponsor",
    digital: "Digital",
    fan_experience: "Fan experience",
  };
  return labels[type] || "Campaign";
}

function ensureRevenue(slug) {
  if (revenueBySlug.has(slug) || revenueInflight.has(slug)) return;
  revenueInflight.add(slug);
  loadSchoolRevenue(slug);
}

async function loadSchoolRevenue(slug) {
  let data = null;
  try {
    const response = await fetch(`/api/revenue/${encodeURIComponent(slug)}`);
    const body = await response.json();
    if (response.ok && body && !body.error && Array.isArray(body.years)) data = body;
  } catch (_error) {
    data = null;
  }
  revenueInflight.delete(slug);
  revenueBySlug.set(slug, data);
  const route = currentRoute();
  if (route.name !== "school" || route.slug !== slug) return;
  if (route.view !== "revenue") {
    if (data) mountSchoolViewToggle(slug, route.view === "campaigns" ? "campaigns" : "attendance");
    return;
  }
  render();
}

function mountSchoolViewToggle(slug, pageView) {
  const existing = document.getElementById("school-view-toggle");
  const next = schoolViewToggle(slug, pageView);
  if (existing) {
    existing.replaceWith(next);
    return;
  }
  const head = view.querySelector(".school-head");
  if (!head) return;
  head.insertAdjacentElement("afterend", next);
}

function revenueStats(data) {
  const latest = data.latest || {};
  const nodes = [
    stat(formatDollars(latest.revenue_usd), `FY${latest.year} football revenue`),
  ];
  if (latest.yoy_usd != null) {
    const versus = latest.yoy_base_year && latest.yoy_base_year !== latest.year - 1
      ? `vs ${latest.yoy_base_year}`
      : `vs FY${latest.yoy_base_year}`;
    nodes.push(revenueMoveStat(latest.yoy_usd, latest.yoy_pct, versus));
  } else if (latest.year === 2020) {
    nodes.push(stat("—", "Change omitted · COVID"));
  }
  if (data.growth_10y) nodes.push(revenueGrowthStat(data.growth_10y));
  return h("div", { class: "stats rev-stats" }, nodes);
}

function revenueMoveStat(usd, pct, label) {
  const tone = usd > 0 ? "rev-up" : usd < 0 ? "rev-down" : "";
  return h("div", { class: "stat" }, [
    h("b", { class: tone }, [
      usd === 0 ? null : arrowSvg(usd > 0),
      document.createTextNode(`${formatSignedDollars(usd)} · ${formatSignedPercentPoints(pct)}`),
    ]),
    h("span", { text: label }),
  ]);
}

function revenueGrowthStat(growth) {
  return revenueMoveStat(
    growth.delta_usd,
    growth.pct,
    `10-year growth, ${growth.from_year} → ${growth.to_year}`
  );
}

function revenueFootnotes(data) {
  const seen = new Set();
  const notes = [];
  (data.years || []).forEach((row) => {
    if (!row.footnote || seen.has(row.footnote)) return;
    seen.add(row.footnote);
    notes.push(row.footnote);
  });
  return h("div", { class: "rev-footnotes" }, [
    h("p", { class: "muted", text: data.display_footnote || "" }),
    ...notes.map((text) => h("p", { class: "muted", text: `* ${text}` })),
  ]);
}

function revenueTable(rows) {
  return h("table", { class: "rev-table" }, [
    h("thead", {}, [h("tr", {}, [
      h("th", { text: "Year" }),
      h("th", { class: "num", text: "Revenue" }),
      h("th", { class: "num", text: "YoY $" }),
      h("th", { class: "num", text: "YoY %" }),
    ])]),
    h("tbody", {}, rows.map((row) => h("tr", { class: row.covid ? "rev-covid-row" : "" }, [
      h("td", {}, [
        document.createTextNode(String(row.year)),
        row.covid ? h("span", { class: "pill quiet rev-covid", text: "COVID" }) : null,
      ]),
      h("td", { class: "num", text: revenueAmount(row) }),
      yoyDollarCell(row),
      yoyPercentCell(row),
    ]))),
  ]);
}

function revenueAmount(row) {
  if (row.revenue_usd == null) return "—";
  return `${formatDollars(row.revenue_usd)}${row.footnote ? "*" : ""}`;
}

function yoyDollarCell(row) {
  if (row.covid) {
    return h("td", { class: "num" }, [
      document.createTextNode("—"),
      h("span", { class: "rev-note", text: "Omitted · COVID" }),
    ]);
  }
  if (row.yoy_usd == null) return h("td", { class: "num", text: "—" });
  return h("td", { class: `num ${yoyTone(row.yoy_usd)}` }, [
    document.createTextNode(formatSignedDollars(row.yoy_usd)),
    yoyCompareNote(row),
  ]);
}

function yoyPercentCell(row) {
  if (row.covid || row.yoy_pct == null) return h("td", { class: "num", text: "—" });
  return h("td", { class: `num ${yoyTone(row.yoy_pct)}` }, [
    document.createTextNode(formatSignedPercentPoints(row.yoy_pct)),
    yoyCompareNote(row),
  ]);
}

function yoyCompareNote(row) {
  if (row.yoy_base_year == null || row.yoy_base_year === row.year - 1) return null;
  return h("span", { class: "rev-note", text: `vs ${row.yoy_base_year}` });
}

function yoyTone(value) {
  if (value > 0) return "rev-up";
  if (value < 0) return "rev-down";
  return "";
}

function drawRevenueChart(school, data) {
  const canvas = document.getElementById("revenue-chart");
  const rows = data.years || [];
  if (!canvas || typeof Chart === "undefined") {
    canvas?.replaceWith(h("p", { text: "The chart library did not load. The table below still lists every fiscal year." }));
    return;
  }
  if (!rows.some((row) => row.revenue_usd != null)) {
    canvas.replaceWith(h("p", { text: "No reported football revenue to plot." }));
    return;
  }
  const color = school.color || "#111418";
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((row) => (row.covid ? [String(row.year), "COVID"] : String(row.year))),
      datasets: [{
        label: "Football revenue",
        data: rows.map((row) => (row.revenue_usd == null ? null : row.revenue_usd)),
        // The COVID year is drawn in neutral gray: shown, but set apart from the comparable years.
        backgroundColor: rows.map((row) => (row.covid ? "#b9bbb5" : color)),
        borderRadius: 4,
        maxBarThickness: 28,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: chartAnimation(),
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items) {
              const row = rows[items[0].dataIndex];
              return row.covid ? `${row.year} · COVID` : String(row.year);
            },
            label(context) {
              const row = rows[context.dataIndex];
              if (row.revenue_usd == null) return "Not reported";
              const star = row.footnote ? "*" : "";
              return `${formatDollars(row.revenue_usd)}${star}`;
            },
            afterLabel(context) {
              const row = rows[context.dataIndex];
              if (row.covid) return "YoY omitted · COVID";
              if (row.yoy_usd == null) return row.revenue_usd == null ? "" : "No prior year to compare";
              const versus = row.yoy_base_year && row.yoy_base_year !== row.year - 1
                ? ` vs ${row.yoy_base_year}`
                : "";
              return `${formatSignedDollars(row.yoy_usd)} (${formatSignedPercentPoints(row.yoy_pct)})${versus}`;
            },
            footer(items) {
              const row = rows[items[0].dataIndex];
              return row.footnote ? `* ${row.footnote}` : "";
            },
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          border: { display: false },
          ticks: { callback: (value) => formatRevenueAxis(value) },
        },
        x: {
          grid: { display: false },
          ticks: { autoSkip: false, maxRotation: 0 },
        },
      },
    },
  });
  charts.push(chart);
}

function formatDollars(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function formatSignedDollars(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  const text = formatDollars(Math.abs(number));
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

function formatSignedPercentPoints(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  const text = `${Math.abs(number).toFixed(2)}%`;
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

function formatRevenueAxis(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  const abs = Math.abs(number);
  if (abs >= 1000000) {
    const millions = number / 1000000;
    const digits = abs >= 100000000 || Number.isInteger(millions) ? 0 : 1;
    return `$${millions.toFixed(digits)}M`;
  }
  return formatDollars(number);
}

function previousSeasonYear(endYear) {
  return Number(endYear) - 1;
}

function rangeHint(endYear, span) {
  if (span === RANGE_LAST) {
    return singleSeasonHint(previousSeasonYear(endYear));
  }
  if (span === 1) {
    return singleSeasonHint(endYear);
  }
  const start = endYear - span + 1;
  const base = `${start}–${endYear}: average reported home attendance by season. Missing years stay blank.`;
  if (windowIncludesCovid(start, endYear)) {
    return `${base} 2020 is omitted as the COVID season, so this window uses the other seasons only.`;
  }
  return base;
}

function singleSeasonHint(year) {
  if (Number(year) === 2020) {
    return "2020 is omitted as the COVID season. The season average is not shown. Individual games stay in the cache and are not averaged.";
  }
  return `${year} home games, one bar or point per opponent. Gaps are unreported or not yet played.`;
}

function windowIncludesCovid(start, end) {
  return Number(start) <= 2020 && Number(end) >= 2020;
}

function isCovidOmitted(row) {
  if (!row) return false;
  if (row.attendance_omitted === "covid") return true;
  const year = row.year != null ? row.year : row.season;
  return Number(year) === 2020;
}

function historyBounds(span, endYear) {
  return { start: endYear - span + 1, end: endYear };
}

function businessNewsSection(slug) {
  const token = ++newsToken;
  const section = h("section", { class: "panel", id: "business-news" }, [
    h("h3", { text: "Business & athletics news" }),
    h("p", { class: "muted", text: "NIL, media rights, sponsorships, stadium work, and department money for this program. Headline and link only." }),
    h("div", { id: "business-news-body", "aria-live": "polite" }),
  ]);
  queueMicrotask(() => loadBusinessNews(slug, token));
  return section;
}

async function loadBusinessNews(slug, token) {
  const node = document.getElementById("business-news-body");
  if (!node) return;
  const remembered = businessNewsBySlug.get(slug);
  if (remembered) {
    renderBusinessNews(node, remembered);
    return;
  }
  node.replaceChildren(h("p", { class: "loading", text: "Loading athletics business headlines…" }));
  let body;
  try {
    const response = await fetch(`/api/school/${encodeURIComponent(slug)}/business-news`);
    body = await response.json();
    if (token !== newsToken) return;
    if (!response.ok || body.error) {
      renderBusinessNews(node, {
        items: [],
        note: body.message || "Business headlines could not be loaded.",
        attribution: body.attribution,
      });
      return;
    }
  } catch (_error) {
    if (token !== newsToken) return;
    renderBusinessNews(node, { items: [], note: "Business headlines could not be loaded." });
    return;
  }
  if (token !== newsToken) return;
  businessNewsBySlug.set(slug, body);
  const current = document.getElementById("business-news-body");
  if (current) renderBusinessNews(current, body);
}

function renderBusinessNews(node, body) {
  const items = body.items || [];
  const list = items.length
    ? h("ul", { class: "news-list" }, items.map(newsRow))
    : h("p", { text: body.note || "No recent athletics-business headlines turned up for this program." });
  fill(node,
    list,
    h("p", {
      class: "muted news-attr",
      text: body.attribution || "Headlines, publisher, and date only, with a link to the original story. This portfolio app aggregates public feeds and does not copy article text. Google News RSS is a prototype source, not a commercial redistribution license.",
    })
  );
}

function newsRow(item) {
  const meta = [item.source, formatNewsDate(item.published_at)].filter(Boolean).join(" · ");
  return h("li", {}, [
    h("a", { href: item.url, target: "_blank", rel: "noopener noreferrer" }, [
      h("strong", { text: item.title }),
      meta ? h("span", { text: meta }) : null,
    ]),
  ]);
}

function formatNewsDate(value) {
  if (!value) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return formatDate(value);
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

async function loadPriorSeason(school, year, token) {
  let seasonBody;
  try {
    seasonBody = await loadSeasonPayload(year);
  } catch (error) {
    if (token !== historyToken) return;
    renderHistoryError(error.message || `${year} could not be loaded.`);
    return;
  }
  if (token !== historyToken) return;
  const prior = findPriorSchool(seasonBody, school);
  if (!prior) {
    renderHistoryError(`${school.school} is not in the ${year} cache. Attendance was not fabricated.`);
    return;
  }
  const rankNode = document.getElementById("public-rank-pill");
  if (rankNode) {
    const label = publicRankLabel(prior);
    rankNode.className = label ? "pill rank" : "pill unranked";
    rankNode.textContent = label || "Unranked";
  }
  const rankNote = document.getElementById("public-rank-note");
  if (rankNote) rankNote.textContent = (seasonBody.meta && seasonBody.meta.rank_note) || "";
  const pins = document.getElementById("season-pins");
  if (pins) {
    pins.replaceChildren(attendancePins(prior, year));
    if (!motionFromRender) {
      motionSwap(pins);
      motionCounts(pins);
    }
  }
  fillSeasonBody(prior, year);
}

async function loadSeasonPayload(year) {
  if (seasonPayloads.has(year)) return seasonPayloads.get(year);
  const response = await fetch(`/api/season?year=${encodeURIComponent(year)}`);
  const body = await response.json();
  if (!response.ok || body.error) {
    throw new Error(body.message || "That season could not be loaded.");
  }
  seasonPayloads.set(year, body);
  return body;
}

function findPriorSchool(seasonBody, school) {
  const schools = seasonBody.schools || [];
  return schools.find((row) => row.id != null && row.id === school.id)
    || schools.find((row) => row.slug === school.slug)
    || null;
}

function fillSeasonBody(school, seasonYear) {
  const year = seasonYear == null ? Number(payload.meta.season) : Number(seasonYear);
  const games = school.home_games || [];
  const gaps = games.filter((game) => game.attendance_status !== "reported");
  const body = document.getElementById("school-body");
  if (!body) return;
  const covid = isCovidOmitted(school) || year === 2020;
  fill(body,
    h("section", { class: "panel" }, [
      h("h3", { text: "Home attendance by opponent" }),
      h("p", { class: "muted", text: covid
        ? "2020 is omitted as the COVID season. The season average is not shown. Game rows stay in the cache and are not averaged. Missing values are not drawn as zero."
        : "Non-neutral home games only. A gap is a game with no reported attendance, or a game that has not been played. Missing values are not drawn as zero." }),
      h("div", { class: "chart-wrap" }, [h("canvas", { id: "attendance-chart" })]),
      gaps.length
        ? h("ul", { class: "badge-list" }, gaps.map((game) => h("li", {}, [
            h("span", {
              class: game.attendance_status === "not_reported" ? "pill warn" : "pill quiet",
              text: `${game.label} · ${statusLabel(game.attendance_status)}`,
            }),
          ])))
        : h("p", { class: "muted", text: "Every home game in this cache has a reported attendance." }),
    ]),
    h("section", { class: "panel" }, [
      h("h3", { text: "Home games" }),
      games.length
        ? h("div", { class: "table-wrap" }, [gameTable(games)])
        : h("p", { text: "No on-campus home games are in this cache." }),
      h("p", { class: "muted", text: "Capacity percentage uses that game's venue capacity. If the venue has none and the game is at the school's own stadium, the home stadium capacity is used. Another venue never inherits that number." }),
    ])
  );
  drawAttendanceChart(school, games);
  afterPartial(body);
}

async function loadHistory(slug, school, bounds, token) {
  let body;
  try {
    const response = await fetch(
      `/api/school/${encodeURIComponent(slug)}?from=${bounds.start}&to=${bounds.end}`
    );
    body = await response.json();
    if (token !== historyToken) return;
    if (!response.ok || body.error) {
      renderHistoryError(body.message || "The history could not be loaded.");
      return;
    }
  } catch (_error) {
    if (token !== historyToken) return;
    renderHistoryError("The history could not be loaded. If you are serving the site, check that it is still running.");
    return;
  }
  if (token !== historyToken) return;
  renderHistory(school, body);
}

function renderHistoryError(message) {
  const node = document.getElementById("school-body");
  if (!node) return;
  node.replaceChildren(h("div", { class: "error" }, [
    h("h2", { text: "That range is not available" }),
    h("p", { text: message }),
  ]));
}

function renderHistory(school, history) {
  const node = document.getElementById("school-body");
  if (!node) return;
  const rows = windowRows(history);
  const reported = reportedSeasons(history.school.seasons);
  const delta = reported.length >= 2 ? attendanceDelta(reported) : null;
  const plottable = rows.some((row) => historyAverage(row) != null);
  fill(node,
    h("section", { class: "panel" }, [
      h("h3", { text: "Average home attendance by season" }),
      h("p", { class: "muted", text: historyChartIntro(history) }),
      delta ? h("div", { class: "stats" }, [
        stat(signedCrowd(delta.delta), `Change, ${delta.from} to ${delta.to}`),
        stat(formatMaybeInt(delta.last), `${delta.to} average`),
        stat(String(reported.length), "Seasons with a reported average"),
      ]) : h("p", { class: "muted", text: reported.length
        ? "One season in this window has a reported average, so there is no change to compare yet."
        : "No reported home attendance in this window." }),
      plottable
        ? h("div", { class: "chart-wrap" }, [h("canvas", { id: "history-chart" })])
        : h("p", { text: "Nothing to plot yet. The table lists every year in the window." }),
      h("p", { class: "muted", text: historyNotes(history) }),
    ]),
    h("section", { class: "panel" }, [
      h("h3", { text: "Seasons in this window" }),
      h("div", { class: "table-wrap" }, [historyTable(rows)]),
    ])
  );
  if (plottable) drawHistoryChart(school, rows);
  afterPartial(node);
}

function windowRows(history) {
  const byYear = new Map((history.school.seasons || []).map((season) => [season.year, season]));
  const missing = new Set(history.missing_years || []);
  const rows = [];
  for (let year = history.from; year <= history.to; year += 1) {
    if (byYear.has(year)) rows.push({ year, season: byYear.get(year), kind: "cached" });
    else if (missing.has(year)) rows.push({ year, season: null, kind: "missing" });
    else rows.push({ year, season: null, kind: "absent" });
  }
  return rows;
}

function historyChartIntro(history) {
  const base = "Each bar is the average of reported non-neutral home games that season. A blank year was not cached, the school was not in that file, or no attendance was reported. Those years are not estimated.";
  if (history.attendance_note || windowIncludesCovid(history.from, history.to)) {
    return `${base} 2020 is omitted as the COVID season and is not included in the average or the change between seasons.`;
  }
  return base;
}

function reportedSeasons(seasons) {
  return (seasons || []).filter((season) => season && !isCovidOmitted(season) && season.avg_home_attendance != null);
}

function historyAverage(row) {
  if (!row || !row.season || isCovidOmitted(row.season) || Number(row.year) === 2020) return null;
  return row.season.avg_home_attendance != null ? row.season.avg_home_attendance : null;
}

function historyNotes(history) {
  const parts = [];
  if (history.missing_years && history.missing_years.length) {
    const years = formatYearList(history.missing_years);
    const verb = history.missing_years.length === 1 ? "is" : "are";
    parts.push(`${years} ${verb} not in the local cache, so ${history.missing_years.length === 1 ? "that year is" : "those years are"} blank.`);
  }
  if (history.sample_years && history.sample_years.length) {
    const years = formatYearList(history.sample_years);
    const verb = history.sample_years.length === 1 ? "is" : "are";
    parts.push(`${years} ${verb} the labeled sample, not a live College Football Data cache.`);
  }
  if (history.attendance_note) parts.push(history.attendance_note);
  else if (windowIncludesCovid(history.from, history.to)) {
    parts.push("2020 is omitted as the COVID season. That year is left out of averages even when the cache has a crowd. A last-10 window that includes 2020 uses the other seasons only.");
  }
  if (!parts.length) return "Every year in this window has a cache file. Averages still skip games with no reported attendance.";
  return parts.join(" ");
}

function historyTable(rows) {
  return h("table", {}, [
    h("thead", {}, [h("tr", {}, [
      h("th", { text: "Year" }),
      h("th", { text: "Conference" }),
      h("th", { class: "num", text: "Avg home" }),
      h("th", { class: "num", text: "Reported" }),
      h("th", { text: "Last home" }),
    ])]),
    h("tbody", {}, rows.map((row) => h("tr", {}, [
      h("td", { text: String(row.year) }),
      h("td", { text: row.season ? (row.season.conference || "—") : "—" }),
      h("td", { class: "num", text: historyAvgText(row) }),
      h("td", { class: "num", text: historyReportedText(row) }),
      h("td", { text: historyLastText(row) }),
    ]))),
  ]);
}

function historyAvgText(row) {
  if (row.kind === "cached" && (isCovidOmitted(row.season) || Number(row.year) === 2020)) return "Omitted · COVID";
  if (row.kind === "missing") return "Not in cache";
  if (row.kind === "absent") return "Not in that season";
  if (row.season.avg_home_attendance == null) return "—";
  return formatInt(Math.round(row.season.avg_home_attendance));
}

function historyReportedText(row) {
  if (!row.season || isCovidOmitted(row.season) || Number(row.year) === 2020) return "—";
  return String(row.season.reported_home_games || 0);
}

function historyLastText(row) {
  if (row.season && (isCovidOmitted(row.season) || Number(row.year) === 2020)) return "Omitted · COVID";
  if (!row.season) return "—";
  if (row.season.last_home_attendance_status === "reported" && row.season.last_home_attendance != null) {
    const opponent = row.season.last_home_opponent ? ` vs ${row.season.last_home_opponent}` : "";
    return `${formatInt(row.season.last_home_attendance)}${opponent}`;
  }
  if (row.season.last_home_attendance_status === "not_reported") return "Not reported";
  return "Awaiting attendance";
}

function attendanceDelta(reported) {
  const first = reported[0];
  const last = reported[reported.length - 1];
  return {
    from: first.year,
    to: last.year,
    last: last.avg_home_attendance,
    delta: last.avg_home_attendance - first.avg_home_attendance,
  };
}

function drawHistoryChart(school, rows) {
  const canvas = document.getElementById("history-chart");
  if (!canvas || typeof Chart === "undefined") {
    canvas?.replaceWith(h("p", { text: "The chart library did not load. The table below still lists every season." }));
    return;
  }
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((row) => String(row.year)),
      datasets: [{
        label: "Average home attendance",
        data: rows.map((row) => historyAverage(row)),
        backgroundColor: school.color || "#111418",
        borderRadius: 4,
        maxBarThickness: 36,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: chartAnimation(),
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context) {
              const row = rows[context.dataIndex];
              if (!row.season) {
                return row.kind === "missing" ? "Not in cache" : "School not in that season's cache";
              }
              if (isCovidOmitted(row.season) || Number(row.year) === 2020) {
                return "Omitted, COVID season. Not included in averages.";
              }
              if (row.season.avg_home_attendance == null) return "No reported attendance";
              const games = row.season.reported_home_games || 0;
              return `${formatInt(Math.round(row.season.avg_home_attendance))} · ${games} reported`;
            },
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          border: { display: false },
          ticks: { callback: (value) => compactNumber.format(value) },
        },
        x: { grid: { display: false } },
      },
    },
  });
  charts.push(chart);
}

function renderAnalysis() {
  const analysis = payload.analysis;
  const meta = payload.meta;
  fill(view,
    kicker("Analysis"),
    h("h1", { class: "lede", text: "Does a weaker record come with a thinner crowd?" }),
    h("p", { class: "sublede", text: analysis.relationship }),
    meta.synthetic
      ? h("p", { class: "muted", text: "These figures are computed from the sample fixture. They are not a finding about the 2026 season." })
      : null,
    h("div", { class: "stats" }, [
      stat(formatStat(analysis.pearson_r), "Pearson r, win % vs capacity %"),
      stat(String(analysis.n_teams), "Teams in the fit"),
      stat(formatStat(analysis.recent_form_pearson_r), `Recent form r (last ${analysis.methodology.recent_form_window})`),
      stat(formatStat(analysis.pregame.pearson_r), `Pregame form r (${analysis.pregame.n_games} games)`),
    ]),
    analysis.slope_capacity_points_per_10_win_points
      ? h("p", { text: analysis.slope_capacity_points_per_10_win_points })
      : null,
    h("p", { class: "muted", text: analysis.raw_attendance_pearson_r == null
      ? "Raw attendance correlation is not estimated."
      : `Secondary check against raw crowd size: Pearson r ${formatStat(analysis.raw_attendance_pearson_r)} across ${analysis.raw_attendance_n} teams. Stadium size dominates that number, so capacity percentage stays the primary measure.` }),
    loyaltySection(),
    proStadiumSection(analysis),
    growthSection(meta.season),
    scatterSection(),
    h("section", { class: "panel" }, [
      h("h3", { text: "Outliers" }),
      analysis.outliers.length
        ? h("div", { class: "outlier-grid" }, analysis.outliers.map(outlierCard))
        : h("p", { text: analysis.outlier_note }),
    ]),
    h("section", { class: "panel method" }, [
      h("h3", { text: "Methodology" }),
      ...analysis.methodology.paragraphs.map((paragraph) => h("p", { text: paragraph })),
      h("p", { class: "muted", text: analysis.pregame.note }),
    ]),
    h("section", { class: "panel" }, [
      h("h3", { text: "Teams in the fit" }),
      analysis.points.length
        ? h("div", { class: "fit-table table-wrap" }, [fitTable(analysis.points)])
        : h("p", { text: "No teams qualified for the fit." }),
      analysis.omitted.length
        ? h("p", { class: "muted", text: `${analysis.n_omitted} teams were left out. ${omittedSummary(analysis.omitted)}` })
        : null,
    ])
  );
  paintLoyalty();
  paintScatter();
}

let scatterRange = "this";
let scatterToken = 0;

function scatterSection() {
  const endYear = Number(payload.meta.season);
  return h("section", { class: "panel", id: "scatter-section" }, [
    h("div", { class: "range-bar" }, [
      segment("Scatter season", [
        ["this", "This season"],
        [RANGE_LAST, "Last season"],
      ], scatterRange, (value) => {
        scatterRange = value;
        document.querySelectorAll("#scatter-section .segment button").forEach((button) => {
          const selected = value === RANGE_LAST ? "Last season" : "This season";
          button.setAttribute("aria-pressed", button.textContent.trim() === selected ? "true" : "false");
        });
        paintScatter();
      }),
      h("p", { class: "muted range-hint", id: "scatter-hint", text: scatterHint(endYear, payload) }),
    ]),
    h("h3", { text: "Capacity filled vs season record" }),
    h("div", { id: "scatter-body", "aria-live": "polite" }, [
      h("div", { class: "chart-wrap" }, [h("canvas", { id: "scatter-chart" })]),
    ]),
    h("p", { class: "muted", id: "scatter-note", text: payload.analysis.outlier_note }),
  ]);
}

function paintScatter() {
  const token = ++scatterToken;
  const endYear = Number(payload.meta.season);
  if (scatterRange !== RANGE_LAST) {
    renderScatter(payload, endYear);
    return;
  }
  const year = previousSeasonYear(endYear);
  const hint = document.getElementById("scatter-hint");
  if (hint) hint.textContent = `Loading ${year}…`;
  loadSeasonPayload(year).then((seasonBody) => {
    if (token !== scatterToken) return;
    renderScatter(seasonBody, year);
  }).catch((error) => {
    if (token !== scatterToken) return;
    const hintNode = document.getElementById("scatter-hint");
    if (hintNode) hintNode.textContent = `${year} is not in the cache.`;
    destroyScatter();
    const body = document.getElementById("scatter-body");
    if (!body) return;
    body.replaceChildren(h("div", { class: "error" }, [
      h("h2", { text: "That season is not available" }),
      h("p", { text: error.message || `${year} could not be loaded.` }),
    ]));
  });
}

function renderScatter(seasonBody, year) {
  const hint = document.getElementById("scatter-hint");
  if (hint) hint.textContent = scatterHint(year, seasonBody);
  const note = document.getElementById("scatter-note");
  const analysis = (seasonBody && seasonBody.analysis) || { points: [], outlier_note: "" };
  const covid = seasonIsCovid(year, seasonBody);
  if (note) {
    note.textContent = covid
      ? "2020 is omitted as the COVID season. This chart is not drawn from that year's crowds."
      : (analysis.outlier_note || "");
  }
  destroyScatter();
  const body = document.getElementById("scatter-body");
  if (!body) return;
  if (covid) {
    body.replaceChildren(h("p", { text: "Omitted · COVID" }));
    afterPartial(body);
    return;
  }
  body.replaceChildren(h("div", { class: "chart-wrap" }, [h("canvas", { id: "scatter-chart" })]));
  drawScatter(analysis);
  afterPartial(body);
}

function scatterHint(year, seasonBody) {
  if (seasonIsCovid(year, seasonBody)) {
    return "2020 is omitted as the COVID season. This chart is not drawn from that year's crowds.";
  }
  return `${year} season. The fit uses this year only.`;
}

function destroyScatter() {
  const kept = [];
  charts.forEach((chart) => {
    if (chart.canvas && chart.canvas.id === "scatter-chart") chart.destroy();
    else kept.push(chart);
  });
  charts = kept;
}

let loyaltyRange = "this";
let loyaltyToken = 0;

function loyaltySection() {
  const endYear = Number(payload.meta.season);
  return h("div", { id: "loyalty-section" }, [
    h("div", { class: "range-bar loyalty-range" }, [
      segment("Loyalty lists", [
        ["this", "This season"],
        [RANGE_LAST, "Last season"],
      ], loyaltyRange, (value) => {
        loyaltyRange = value;
        document.querySelectorAll("#loyalty-section .segment button").forEach((button) => {
          const selected = value === RANGE_LAST ? "Last season" : "This season";
          button.setAttribute("aria-pressed", button.textContent.trim() === selected ? "true" : "false");
        });
        paintLoyalty();
      }),
      h("p", { class: "muted range-hint", id: "loyalty-hint", text: loyaltyHint(endYear, payload) }),
    ]),
    h("div", { id: "loyalty-body", "aria-live": "polite" }),
  ]);
}

function paintLoyalty() {
  const token = ++loyaltyToken;
  const endYear = Number(payload.meta.season);
  const node = document.getElementById("loyalty-body");
  if (!node) return;
  if (loyaltyRange !== RANGE_LAST) {
    renderLoyalty(node, payload, endYear);
    return;
  }
  const year = previousSeasonYear(endYear);
  const hint = document.getElementById("loyalty-hint");
  if (hint) hint.textContent = `Loading ${year}…`;
  node.replaceChildren(h("p", { class: "loading", text: `Loading ${year} loyalty lists…` }));
  loadSeasonPayload(year).then((seasonBody) => {
    if (token !== loyaltyToken) return;
    const current = document.getElementById("loyalty-body");
    if (current) renderLoyalty(current, seasonBody, year);
  }).catch((error) => {
    if (token !== loyaltyToken) return;
    const current = document.getElementById("loyalty-body");
    if (!current) return;
    const hintNode = document.getElementById("loyalty-hint");
    if (hintNode) hintNode.textContent = `${year} is not in the cache.`;
    current.replaceChildren(h("div", { class: "error" }, [
      h("h2", { text: "That season is not available" }),
      h("p", { text: error.message || `${year} could not be loaded.` }),
    ]));
  });
}

function renderLoyalty(node, seasonBody, year) {
  const hint = document.getElementById("loyalty-hint");
  if (hint) hint.textContent = loyaltyHint(year, seasonBody);
  const covid = seasonIsCovid(year, seasonBody);
  const loyalty = seasonBody.analysis ? seasonBody.analysis.loyalty : null;
  const partial = !covid && Boolean(seasonBody.meta && seasonBody.meta.season_partial);
  fill(node,
    loyaltyIntro(loyalty, year, covid),
    h("div", { class: "loyalty-grid" }, [
      loyaltyPanel(
        "most-loyal",
        "Most loyal fans",
        "A record at or below the median, and the stadium is still full. Ordered from the highest share of seats filled.",
        covid ? null : (loyalty && loyalty.most_loyal),
        covid,
        partial
      ),
      loyaltyPanel(
        "soft-support",
        "Softest home support",
        "The same below-median records, ordered from the lowest share of seats filled. Empty here means empty relative to that stadium, not a smaller headcount.",
        covid ? null : (loyalty && loyalty.softest_support),
        covid,
        partial
      ),
    ])
  );
  afterPartial(node);
}

function seasonIsCovid(year, seasonBody) {
  if (Number(year) === 2020) return true;
  return Boolean(seasonBody && seasonBody.meta && seasonBody.meta.attendance_omitted === "covid");
}

function loyaltyHint(year, seasonBody) {
  if (seasonIsCovid(year, seasonBody)) {
    return "2020 is omitted as the COVID season. These lists are not ranked from that year's crowds.";
  }
  if (seasonBody && seasonBody.meta && seasonBody.meta.season_partial) {
    return `${year} is still in progress. The count beside each school is games played.`;
  }
  return `${year} season. Both lists use that year only.`;
}

function loyaltyIntro(loyalty, year, covid) {
  if (covid) {
    return h("p", { class: "sublede", text: "2020 is omitted as the COVID season. Crowds from that year stay in the cache and are not used in these lists." });
  }
  if (!loyalty || loyalty.win_pct_median == null) {
    return h("p", { class: "sublede", text: "Most loyal fans and softest home support need the same teams as the fit: two reported home crowds with a capacity percentage, and two decided games. None qualify in this cache." });
  }
  return h("p", { class: "sublede", text: `A bad record is a win percentage at or below ${formatPct(loyalty.win_pct_median)}, the median of the ${loyalty.n_qualifying} teams in the ${year} fit. ${loyalty.n_bad_record} teams are in that group. Both lists rank them by average home capacity filled, never by raw attendance.` });
}

function loyaltyPanel(id, title, blurb, rows, covid, partial) {
  let body;
  if (covid) body = h("p", { text: "Omitted · COVID" });
  else if (rows && rows.length) body = h("div", { class: "loyal-list" }, rows.map((row) => loyaltyRow(row, partial)));
  else body = h("p", { text: "No qualifying team has a below-median record in this cache." });
  return h("section", { class: "panel", id }, [
    h("h3", { text: title }),
      h("p", { class: "muted", text: blurb }),
    body,
  ]);
}

function loyaltyRow(row, partial) {
  const games = row.reported_home_games == null ? "" : `${row.reported_home_games} reported`;
  const meta = [row.record || "Record unavailable", `${formatPct(row.win_pct)} wins`, games].filter(Boolean).join(" · ");
  const crowd = row.avg_home_attendance == null ? null : `Avg crowd ${formatMaybeInt(row.avg_home_attendance)}`;
  const played = partial && row.games_played != null
    ? h("span", { class: "loyal-played", text: `${row.games_played} played` })
    : null;
  return h("a", { class: "loyal-row", href: `#/schools/${encodeURIComponent(row.slug)}` }, [
    h("span", { class: "loyal-rank", text: String(row.rank) }),
    mark(row, 42),
    h("div", { class: "loyal-name" }, [
      h("strong", {}, [document.createTextNode(row.school), played]),
      h("p", { text: meta }),
    ]),
    h("div", { class: "loyal-fill" }, [
      h("strong", { text: formatPct(row.avg_capacity_pct) }),
      h("span", { text: "full" }),
      crowd ? h("span", { text: crowd }) : null,
    ]),
  ]);
}

function growthSection(season) {
  const token = ++growthToken;
  const section = h("section", { id: "attendance-growth" }, [
    h("div", { id: "attendance-growth-body", "aria-live": "polite" }, [
      h("p", { class: "loading", text: "Loading attendance growth…" }),
    ]),
  ]);
  const endYear = Number(season);
  queueMicrotask(() => loadGrowth(endYear, token));
  return section;
}

async function loadGrowth(endYear, token) {
  const node = document.getElementById("attendance-growth-body");
  if (!node || !endYear) return;
  const start = endYear - 9;
  let body;
  try {
    const response = await fetch(`/api/history?from=${start}&to=${endYear}`);
    body = await response.json();
    if (token !== growthToken) return;
    if (!response.ok || body.error) {
      node.replaceChildren(h("section", { class: "panel" }, [
        h("h3", { text: "Attendance growth" }),
        h("p", { text: body.message || "Attendance growth could not be loaded." }),
      ]));
      return;
    }
  } catch (_error) {
    if (token !== growthToken) return;
    node.replaceChildren(h("section", { class: "panel" }, [
      h("h3", { text: "Attendance growth" }),
      h("p", { text: "Attendance growth could not be loaded." }),
    ]));
    return;
  }
  if (token !== growthToken) return;
  const current = document.getElementById("attendance-growth-body");
  if (current) renderGrowth(current, body.attendance_growth, body.from, body.to);
}

function renderGrowth(node, growth, yearFrom, yearTo) {
  const data = growth || {};
  const growing = data.fastest_growing || [];
  const falling = data.softest_growth || [];
  const windowLabel = yearFrom && yearTo ? `${yearFrom}–${yearTo}` : "the last 10 seasons";
  const fallingTitle = data.basis === "weakest_growth" ? "Weakest attendance growth" : "Fastest-falling crowds";
  const fallingBlurb = data.basis === "weakest_growth"
    ? "No qualifying school declined. These are the smallest growth rates in the window, still ordered by the rate rather than by crowd size."
    : "The steepest drops in average home attendance. A negative rate means the reported crowd got smaller. This is not the softest-fill list.";
  const empty = !growing.length && !falling.length;
  fill(node,
    h("p", { class: "sublede", text: data.methodology || "Attendance growth uses reported home averages only." }),
    empty
      ? h("section", { class: "panel" }, [
          h("h3", { text: "Attendance growth" }),
          h("p", { text: `Not enough cached seasons in ${windowLabel}. A school needs at least ${data.min_seasons || 5} seasons with a reported home average. Missing years are not filled in. 2020 is omitted as the COVID season and does not count toward that minimum.` }),
        ])
      : h("div", { class: "loyalty-grid" }, [
          growthPanel(
            "fastest-growing",
            "Fastest-growing fanbases",
            "Compound annual change in average home attendance. Ordered from the strongest rate, not from the biggest crowd.",
            growing
          ),
          growthPanel(fallingTitle.toLowerCase().replace(/\s+/g, "-"), fallingTitle, fallingBlurb, falling),
        ])
  );
  afterPartial(node);
}

function growthPanel(id, title, blurb, rows) {
  return h("section", { class: "panel", id }, [
    h("h3", { text: title }),
    h("p", { class: "muted", text: blurb }),
    rows && rows.length
      ? h("div", { class: "loyal-list" }, rows.map(growthRow))
      : h("p", { text: "No school qualified for this list." }),
  ]);
}

function growthRow(row) {
  const span = `${row.start_year}–${row.end_year} · ${row.seasons_with_average} seasons`;
  const crowds = `${formatMaybeInt(row.start_avg)} → ${formatMaybeInt(row.end_avg)}`;
  const total = row.pct_change == null ? "" : `${formatSignedPct(row.pct_change)} over the window`;
  return h("a", { class: "loyal-row", href: `#/schools/${encodeURIComponent(row.slug)}` }, [
    h("span", { class: "loyal-rank", text: String(row.rank) }),
    mark(row, 42),
    h("div", { class: "loyal-name" }, [
      h("strong", { text: row.school }),
      h("p", { text: [span, crowds, total].filter(Boolean).join(" · ") }),
    ]),
    h("div", { class: "loyal-fill" }, [
      h("strong", { class: row.cagr < 0 ? "growth-down" : "growth-up", text: `${formatSignedPct(row.cagr)}/yr` }),
      h("span", { text: "per year" }),
      h("span", { text: `Latest avg ${formatMaybeInt(row.end_avg)}` }),
    ]),
  ]);
}

function formatSignedPct(fraction) {
  if (fraction == null) return "—";
  const text = formatPct(Math.abs(fraction));
  if (fraction > 0) return `+${text}`;
  if (fraction < 0) return `−${text}`;
  return text;
}

function proStadiumSection(analysis) {
  const rows = analysis.pro_stadiums || [];
  return h("section", { class: "panel", id: "pro-stadiums" }, [
    h("h3", { text: "NFL home stadiums" }),
    h("p", { class: "muted", text: "These schools list an NFL stadium as home. Capacity and percent full are the official figures for that building, so they are not compared with on-campus college stadiums. They are left out of the fit and both ranked lists. This section is ordered by average reported crowd, not by how full the building looks." }),
    rows.length
      ? h("div", { class: "loyal-list" }, rows.map(proStadiumRow))
      : h("p", { text: "No team in this cache lists an NFL stadium as its home." }),
  ]);
}

function proStadiumRow(row) {
  const games = row.reported_home_games == null ? "" : `${row.reported_home_games} reported`;
  const meta = [row.record || "Record unavailable", games, row.pro_stadium_note].filter(Boolean).join(" · ");
  const capacity = row.capacity == null ? "Official capacity —" : `Official capacity ${formatInt(row.capacity)}`;
  const fill = row.avg_capacity_pct == null
    ? "Official fill —"
    : `Official fill ${formatPct(row.avg_capacity_pct)} · not comparable`;
  return h("a", { class: "loyal-row pro-row", href: `#/schools/${encodeURIComponent(row.slug)}` }, [
    mark(row, 42),
    h("div", { class: "loyal-name" }, [
      h("strong", { text: row.school }),
      h("p", { text: meta }),
    ]),
    h("div", { class: "loyal-fill" }, [
      h("strong", { text: formatMaybeInt(row.avg_home_attendance) }),
      h("span", { text: "avg crowd" }),
      h("span", { text: capacity }),
      h("span", { text: fill }),
    ]),
  ]);
}

function outlierCard(point) {
  const high = point.kind === "draws_above_record";
  const residual = point.residual == null ? "" : ` That is ${signedPoints(point.residual)} versus the fitted line.`;
  const story = high
    ? `${point.record}, averaging ${formatPct(point.avg_capacity_pct)} full.${residual}`
    : `${point.record}, averaging ${formatPct(point.avg_capacity_pct)} full.${residual}`;
  return h("a", { class: `outlier ${high ? "high" : "low"}`, href: `#/schools/${encodeURIComponent(point.slug)}` }, [
    h("div", {}, [
      h("strong", { text: point.school }),
      h("p", { class: "muted", text: high ? "Draws above the record" : "Soft crowd for the record" }),
      h("p", { text: story }),
      h("p", { class: "muted", text: `${point.conference} · recent form ${point.recent_record || "n/a"} · avg crowd ${formatMaybeInt(point.avg_home_attendance)}` }),
    ]),
  ]);
}

function gameTable(games) {
  const table = h("table", {}, [
    h("thead", {}, [h("tr", {}, [
      h("th", { text: "Week" }),
      h("th", { text: "Date" }),
      h("th", { text: "Opponent" }),
      h("th", { text: "Result" }),
      h("th", { class: "num", text: "Attendance" }),
      h("th", { class: "num", text: "Capacity" }),
      h("th", { text: "Status" }),
    ])]),
    h("tbody", {}, games.map((game) => h("tr", {}, [
      h("td", { text: game.week == null ? "" : String(game.week) }),
      h("td", { text: formatDate(game.start_date) }),
      h("td", { text: game.opponent }),
      h("td", { text: resultText(game) }),
      h("td", { class: "num", text: game.attendance_status === "reported" ? formatInt(game.attendance) : "—" }),
      h("td", { class: "num", text: game.capacity_pct == null ? "—" : formatPct(game.capacity_pct) }),
      h("td", {}, [h("span", {
        class: game.attendance_status === "not_reported" ? "pill warn" : game.attendance_status === "reported" ? "pill" : "pill quiet",
        text: statusLabel(game.attendance_status),
      })]),
    ]))),
  ]);
  return table;
}

function fitTable(points) {
  return h("table", {}, [
    h("thead", {}, [h("tr", {}, [
      "School", "Conference", "Record", "Recent", "Avg crowd", "Capacity", "Vs line", "Flag",
    ].map((label, index) => h("th", { class: index >= 4 && index <= 6 ? "num" : "", text: label })))]),
    h("tbody", {}, points.map((point) => h("tr", {}, [
      h("td", {}, [h("a", { href: `#/schools/${encodeURIComponent(point.slug)}`, text: point.school })]),
      h("td", { text: point.conference }),
      h("td", { text: point.record || "—" }),
      h("td", { text: point.recent_record || "—" }),
      h("td", { class: "num", text: formatMaybeInt(point.avg_home_attendance) }),
      h("td", { class: "num", text: formatPct(point.avg_capacity_pct) }),
      h("td", { class: "num", text: point.residual == null ? "—" : signedPoints(point.residual) }),
      h("td", { text: flagLabel(point.kind), class: point.kind === "draws_above_record" ? "flag-high" : point.kind === "soft_crowd_for_record" ? "flag-low" : "" }),
    ]))),
  ]);
}

function drawAttendanceChart(school, games) {
  const canvas = document.getElementById("attendance-chart");
  if (!canvas || typeof Chart === "undefined") {
    canvas?.replaceWith(h("p", { text: "The chart library did not load. The table below still lists every home game." }));
    return;
  }
  const reported = games.some((game) => game.attendance_status === "reported");
  if (!games.length || !reported) {
    canvas.replaceWith(h("p", { text: games.length ? "No reported attendance to plot. Missing games are badged above and listed below." : "No home games to plot." }));
    return;
  }
  const chart = new Chart(canvas, {
    type: "line",
    data: {
      // "Wk 1 · Opponent" sets on two lines so the axis can stay level.
      labels: games.map((game) => String(game.label || "").split(" · ")),
      datasets: [{
        label: "Attendance",
        data: games.map((game) => (game.attendance_status === "reported" ? game.attendance : null)),
        borderColor: school.color,
        backgroundColor: school.color,
        borderWidth: 2,
        pointBackgroundColor: school.color,
        pointBorderColor: "#f6f6f3",
        pointBorderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 7,
        spanGaps: false,
        tension: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: chartAnimation(),
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context) {
              const game = games[context.dataIndex];
              if (game.attendance_status !== "reported") return statusLabel(game.attendance_status);
              const pct = game.capacity_pct == null ? "" : ` · ${formatPct(game.capacity_pct)} of capacity`;
              return `${formatInt(game.attendance)}${pct}`;
            },
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          border: { display: false },
          ticks: { callback: (value) => compactNumber.format(value) },
        },
        x: { grid: { display: false }, ticks: { maxRotation: 50, autoSkip: false } },
      },
    },
  });
  charts.push(chart);
}

function drawScatter(analysis) {
  const canvas = document.getElementById("scatter-chart");
  if (!canvas || typeof Chart === "undefined") return;
  if (!analysis.points.length) {
    canvas.replaceWith(h("p", { text: "Not enough teams to draw the fit." }));
    return;
  }
  const groups = {
    draws_above_record: [],
    soft_crowd_for_record: [],
    other: [],
  };
  analysis.points.forEach((point) => {
    const bucket = groups[point.kind] ? point.kind : "other";
    groups[bucket].push(pointToXY(point));
  });
  // Gray context, then the two flags in --above / --below (the pair passes the colorblind check on --paper).
  // The triangles point the way each flagged team sits against the line, so the flags never rely on color alone.
  const datasets = [
    scatterSet("Teams in the fit", groups.other, "#8b9097", "circle", 0, 4.5),
    scatterSet("Draws above the record", groups.draws_above_record, "#1f5fa8", "triangle", 0, 7),
    scatterSet("Soft crowd for the record", groups.soft_crowd_for_record, "#b3261e", "triangle", 180, 7),
  ];
  if (analysis.line) {
    datasets.push({
      type: "line",
      label: "Fitted line",
      data: [
        { x: analysis.line.x1 * 100, y: analysis.line.y1 * 100 },
        { x: analysis.line.x2 * 100, y: analysis.line.y2 * 100 },
      ],
      borderColor: "#111418",
      borderWidth: 1.5,
      borderDash: [6, 4],
      pointStyle: "line",
      pointRadius: 0,
      tension: 0,
    });
  }
  const yScale = scatterDomain(scatterPercents(analysis.points, "avg_capacity_pct"), 20, 110);
  const xScale = scatterDomain(scatterPercents(analysis.points, "win_pct"), 0, 100);
  const chart = new Chart(canvas, {
    type: "scatter",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: chartAnimation(),
      onClick(_event, elements) {
        if (!elements.length) return;
        const item = chart.data.datasets[elements[0].datasetIndex].data[elements[0].index];
        if (item && item.slug) location.hash = `#/schools/${encodeURIComponent(item.slug)}`;
      },
      plugins: {
        legend: { align: "start", labels: { usePointStyle: true, boxWidth: 10, boxHeight: 10, padding: 18 } },
        tooltip: {
          callbacks: {
            label(context) {
              const raw = context.raw || {};
              if (!raw.school) return context.dataset.label;
              return `${raw.school}: ${raw.record}, ${Math.round(raw.y)}% full`;
            },
          },
        },
      },
      scales: {
        // includeBounds: false keeps the padded axis ends (e.g. -3% or 110.07%) from printing as ticks.
        x: { title: { display: true, text: "Season win percentage" }, min: xScale.min, max: xScale.max, ticks: { includeBounds: false, callback: (value) => `${value}%` } },
        y: { title: { display: true, text: "Average capacity filled" }, min: yScale.min, max: yScale.max, border: { display: false }, ticks: { includeBounds: false, callback: (value) => `${value}%` } },
      },
    },
  });
  charts.push(chart);
}

function scatterPercents(points, key) {
  return points
    .map((point) => point[key])
    .filter((value) => Number.isFinite(value))
    .map((value) => value * 100);
}

function scatterDomain(values, floor, ceiling) {
  // Default window, extended when a point plus marker padding would be clipped.
  const pad = 3;
  let min = floor;
  let max = ceiling;
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) return { min, max };
  const low = Math.min(...finite);
  const high = Math.max(...finite);
  if (low - pad < min) min = low - pad;
  if (high + pad > max) max = high + pad;
  return { min, max };
}

function scatterSet(label, points, color, pointStyle, rotation, radius) {
  return {
    type: "scatter",
    label,
    data: points,
    backgroundColor: color,
    pointStyle,
    pointRotation: rotation,
    pointBorderColor: "#f6f6f3",
    pointBorderWidth: 1.5,
    pointRadius: radius,
    pointHoverRadius: radius + 2,
    pointHitRadius: 6,
  };
}

function pointToXY(point) {
  return {
    x: point.win_pct * 100,
    y: point.avg_capacity_pct * 100,
    school: point.school,
    slug: point.slug,
    record: point.record,
  };
}

function renderValuations() {
  if (valuationsPayload) {
    paintValuations();
    return;
  }
  const token = ++valuationsToken;
  fill(view,
    kicker("Valuations"),
    h("h1", { class: "lede", text: "What each Power football program is worth." }),
    h("p", { class: "loading", text: "Loading valuations…" })
  );
  loadValuations(token);
}

async function loadValuations(token) {
  let body;
  try {
    const response = await fetch("/api/valuations");
    body = await response.json();
    if (token !== valuationsToken || currentRoute().name !== "valuations") return;
    if (!response.ok || body.error) {
      view.replaceChildren(h("div", { class: "error" }, [
        h("h2", { text: "No valuations to show" }),
        h("p", { text: body.message || "Valuations could not be loaded. Figures were not filled in." }),
      ]));
      return;
    }
  } catch (_error) {
    if (token !== valuationsToken || currentRoute().name !== "valuations") return;
    view.replaceChildren(h("div", { class: "error" }, [
      h("h2", { text: "No valuations to show" }),
      h("p", { text: "Valuations could not be loaded. Figures were not filled in." }),
    ]));
    return;
  }
  valuationsPayload = body;
  if (currentRoute().name === "valuations") paintValuations();
}

function paintValuations() {
  const data = valuationsPayload;
  const schools = Array.isArray(data.schools) ? data.schools : [];
  const sort = valuationView.sort === "nil" ? "nil" : "valuation";
  const conference = valuationView.conference;
  const reorder = valuationReorder;
  valuationReorder = false;
  const previous = reorder ? captureValuationTops() : null;
  const ordered = sortedValuations(schools, sort)
    .filter((row) => conference === "all" || row.conference === conference);
  const sublede = sort === "nil"
    ? "Sorted by estimated football roster cost. Movement arrows stay with the valuation sort, where they compare The Athletic's July 2025 ranks."
    : "Sorted by The Athletic's July 2026 valuation. Arrows show how many spots a school moved from their July 2025 ranking.";

  fill(view,
    kicker("Valuations"),
    h("h1", { class: "lede", text: "What each Power football program is worth." }),
    h("p", { class: "sublede", text: sublede }),
    h("div", { class: "toolbar val-toolbar" }, [
      segment("Sort", [
        ["valuation", "Valuation"],
        ["nil", "NIL budget"],
      ], sort, (value) => {
        valuationView.sort = value;
        valuationReorder = true;
        paintValuations();
      }),
      chips("Conference", VALUATION_CONFERENCES, conference, (value) => {
        valuationView.conference = value;
        valuationReorder = true;
        paintValuations();
      }),
    ]),
    h("p", { class: "muted val-count", "aria-live": "polite", text: valuationCount(ordered, conference) }),
    ordered.length
      ? h("div", { class: "val-board", "data-sort": sort }, [
          valuationHead(),
          ...ordered.map((row, index) => valuationRow(row, index, sort)),
        ])
      : h("p", { class: "empty", text: "No schools in that conference." }),
    valuationFootnote(data.sources || {})
  );
  if (reorder) {
    if (previous && previous.size) flipValuationRows(previous);
    motionCounts(view);
    return;
  }
  if (!motionFromRender) {
    motionSwap(view);
    motionLists(view, false);
    motionCounts(view);
  }
}

function renderMarketing() {
  const cached = marketingPayloads.get(marketingYear);
  if (cached) {
    paintMarketing(cached);
    return;
  }
  const token = ++marketingToken;
  fill(view,
    kicker("Marketing Approaches"),
    h("h1", { class: "lede", text: "Winning teams that still do not fill the building, and the smaller schools that do." }),
    h("p", { class: "loading", text: `Loading the ${marketingYear} marketing lists…` })
  );
  loadMarketing(marketingYear, token);
}

async function loadMarketing(year, token) {
  let body;
  try {
    const response = await fetch(`/api/marketing?year=${encodeURIComponent(year)}`);
    body = await response.json();
    if (token !== marketingToken || currentRoute().name !== "marketing") return;
    if (!response.ok || body.error) {
      view.replaceChildren(h("div", { class: "error" }, [
        h("h2", { text: "No marketing list for that season" }),
        h("p", { text: body.message || "The marketing lists could not be loaded." }),
      ]));
      return;
    }
  } catch (_error) {
    if (token !== marketingToken || currentRoute().name !== "marketing") return;
    view.replaceChildren(h("div", { class: "error" }, [
      h("h2", { text: "No marketing list for that season" }),
      h("p", { text: "The marketing lists could not be loaded." }),
    ]));
    return;
  }
  marketingPayloads.set(year, body);
  if (currentRoute().name === "marketing" && marketingYear === year) paintMarketing(body);
}

function paintMarketing(data) {
  const years = Array.isArray(data.years) && data.years.length ? data.years : [data.year];
  const approaches = Array.isArray(data.approaches) ? data.approaches : [];
  const worked = Array.isArray(data.what_has_worked) ? data.what_has_worked : [];
  const partial = data.season_partial
    ? `${data.year} is still in progress, so the record and the fill can move.`
    : `${data.year} is a complete season.`;
  fill(view,
    kicker("Marketing Approaches"),
    h("h1", { class: "lede", text: "Winning teams that still do not fill the building, and the smaller schools that do." }),
    h("p", { class: "sublede", text: data.threshold && data.threshold.summary ? data.threshold.summary : "" }),
    h("div", { class: "range-bar" }, [
      segment("Marketing season", years.map((year) => [year, marketingYearLabel(year, data)]), marketingYear, (value) => {
        marketingYear = value;
        renderMarketing();
      }),
      h("p", { class: "muted range-hint", text: partial }),
    ]),
    h("div", { class: "stats" }, [
      stat(String(data.year), data.season_partial ? "Season, in progress" : "Season"),
      stat(String(data.n_teams ?? "—"), "Teams in the fit"),
      stat(formatStat(data.pearson_r), "Pearson r, win % vs fill"),
    ]),
    h("div", { class: "jumps", role: "navigation", "aria-label": "On this page" }, [
      jumpButton("Marketing Approaches", "marketing-approaches"),
      jumpButton("What Has Worked", "what-has-worked"),
    ]),
    marketingSection(data, approaches),
    workedSection(data, worked)
  );
  lastShellKey = `marketing:${marketingYear}`;
  lastMotionKey = lastShellKey;
  if (!motionFromRender) {
    motionSwap(view);
    motionLists(view, false);
    motionCounts(view);
  }
}

function jumpButton(label, id) {
  return h("button", {
    type: "button",
    text: label,
    onclick: () => {
      const target = document.getElementById(id);
      if (!target) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    },
  });
}

function marketingYearLabel(year, data) {
  if (year === data.complete_season) return `${year} · Complete`;
  return `${year} · In progress`;
}

function marketingSection(data, approaches) {
  return h("section", { class: "panel approach-section", id: "marketing-approaches" }, [
    h("h2", { text: "Marketing Approaches" }),
    h("p", { class: "tier-note", text: "These teams won more games than they lost and still filled meaningfully less of the stadium than the fitted line expects. The note under each card is yours to write in data/marketing_approaches.json." }),
    approaches.length
      ? h("div", { class: "approach-grid" }, approaches.map((row) => approachCard(row, data)))
      : h("p", { text: `No winning team sits below the line in ${data.year}.` }),
  ]);
}

function workedSection(data, worked) {
  return h("section", { class: "panel approach-section", id: "what-has-worked" }, [
    h("h2", { text: "What Has Worked" }),
    h("p", { class: "tier-note", text: "Group of 5 and other non-Power 4 schools at .500 or worse, filling more of the stadium than the same line expects. Each note is a published promotion with a date. It is not a claim that the promotion caused that season's crowd. If a dated source was not found, the card says so." }),
    worked.length
      ? h("div", { class: "approach-grid" }, worked.map((row) => workedCard(row, data)))
      : h("p", { text: `No Group of 5 school with a losing or .500 record sits above the line in ${data.year}.` }),
  ]);
}

function approachCard(row, data) {
  const empty = row.strategy_is_empty !== false && !String(row.strategy || "").trim();
  return h("article", { class: "approach-card", style: `--rail:${row.color || "#1e3a5f"}` }, [
    approachIdentity(row),
    approachPins(row, "below"),
    h("div", { class: empty ? "take is-empty" : "take" }, [
      h("span", { class: "take-k", text: "Luke's take" }),
      h("p", { text: empty ? (data.placeholder || "Luke's take: coming soon") : row.strategy }),
    ]),
  ]);
}

function workedCard(row, data) {
  const promotions = Array.isArray(row.promotions) ? row.promotions : [];
  return h("article", { class: "approach-card", style: `--rail:${row.color || "#1e3a5f"}` }, [
    approachIdentity(row),
    approachPins(row, "above"),
    promotions.length
      ? h("div", { class: "promo-list" }, promotions.map(promotionItem))
      : h("p", { class: "promo-missing", text: data.no_promotion || "No documented promotion found" }),
  ]);
}

function approachIdentity(row) {
  const body = [
    mark({
      school: row.school,
      logo: row.logo,
      color: row.color || "#1e3a5f",
      abbreviation: row.abbreviation,
    }),
    h("div", {}, [
      h("h3", { text: row.school }),
      h("p", { text: [row.conference, row.tier].filter(Boolean).join(" · ") }),
    ]),
  ];
  if (!row.slug) return h("div", { class: "approach-id" }, body);
  return h("a", { class: "approach-id", href: `#/schools/${encodeURIComponent(row.slug)}` }, body);
}

function approachPins(row, direction) {
  const fill = row.fill_pct == null ? null : {
    key: `fill:${marketingYear}:${row.slug || row.school}`,
    value: Number(row.fill_pct),
    kind: "pct",
  };
  return h("div", { class: "pins approach-pins" }, [
    pin("Record", row.record || "—", winLine(row.win_pct)),
    pin("Fill", formatPct(row.fill_pct), "Average capacity filled", fill ? { value: fill } : null),
    pin("Vs the line", gapAmount(row.residual), direction === "below" ? "Below the fit" : "Above the fit"),
  ]);
}

function winLine(winPct) {
  if (winPct == null) return "";
  return `${formatPct(winPct)} of decided games`;
}

function gapAmount(residual) {
  if (residual == null) return "—";
  const points = Math.abs(residual) * 100;
  return `${(Math.round(points * 10) / 10).toFixed(1)} pts`;
}

function promotionItem(item) {
  return h("div", { class: "promo" }, [
    h("p", { text: item.summary }),
    h("p", { class: "promo-source" }, [
      item.source_url
        ? h("a", { href: item.source_url, target: "_blank", rel: "noopener noreferrer", text: item.source_name || "Source" })
        : h("span", { text: item.source_name || "Source" }),
      document.createTextNode(item.date ? ` · ${formatIsoDate(item.date)}` : ""),
    ]),
  ]);
}

function formatIsoDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!match) return iso || "";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function valuationHead() {
  return h("div", { class: "val-head" }, [
    h("span", { text: "Rank" }),
    h("span", { text: "" }),
    h("span", { text: "School" }),
    h("span", { text: "Valuation" }),
    h("span", { text: "NIL budget" }),
  ]);
}

function valuationRow(row, index, sort) {
  const known = lookupSchool(row.school);
  const logoSchool = {
    school: row.school,
    logo: known && known.logo,
    color: (known && known.color) || "#1e3a5f",
    abbreviation: known && known.abbreviation,
  };
  const rankText = sort === "valuation" && Number.isFinite(row.valuation_rank)
    ? String(row.valuation_rank)
    : String(index + 1);
  const showMove = sort === "valuation";
  const inner = [
    h("div", { class: "val-rank" }, [
      h("span", { class: "val-rank-num", text: rankText }),
      showMove ? movementNode(rankChangeSpots(row)) : null,
    ]),
    mark(logoSchool, 44),
    h("div", { class: "val-school" }, [
      h("strong", { text: row.school }),
      h("p", { text: row.conference || "—" }),
    ]),
    h("div", { class: "val-money val-valuation" }, [
      h("span", { class: "val-k", text: "Valuation" }),
      h("strong", countProps(formatValuation(row.valuation_usd), Number.isFinite(row.valuation_usd) ? {
        key: `val:${row.school}`,
        value: row.valuation_usd,
        kind: "usd",
      } : null)),
    ]),
    h("div", { class: "val-money val-nil" }, [
      h("span", { class: "val-k", text: "NIL" }),
      h("strong", countProps(formatNil(row.nil_budget_usd), Number.isFinite(row.nil_budget_usd) ? {
        key: `nil:${row.school}`,
        value: row.nil_budget_usd,
        kind: "nil",
      } : null)),
      row.nil_is_estimate ? h("span", { class: "val-est", text: "est." }) : null,
    ]),
  ];
  const props = {
    class: "val-row",
    "data-school": row.school || "",
  };
  if (known && known.slug) {
    props.href = `#/schools/${encodeURIComponent(known.slug)}/revenue`;
    return h("a", props, inner);
  }
  return h("div", props, inner);
}

function valuationFootnote(sources) {
  const valuation = sources.valuation || {};
  const prior = sources.prior_valuation || {};
  const nil = sources.nil || {};
  return h("p", { class: "val-footnote" }, [
    document.createTextNode("Valuations are "),
    sourceLink(valuation.url, "The Athletic's July 2026"),
    document.createTextNode(" estimated football program values (hypothetical sale prices), movement is against their "),
    sourceLink(prior.url, "July 2025 list"),
    document.createTextNode(", and NIL is "),
    sourceLink(nil.url, "nil-ncaa.com"),
    document.createTextNode("'s estimated football roster cost for 2026-27, not school-audited."),
    nil.methodology_url
      ? document.createTextNode(" ")
      : null,
    nil.methodology_url ? sourceLink(nil.methodology_url, "NIL methodology") : null,
    nil.methodology_url ? document.createTextNode(".") : null,
  ]);
}

function sourceLink(href, text) {
  if (!href) return document.createTextNode(text);
  return h("a", {
    href,
    target: "_blank",
    rel: "noopener noreferrer",
    text,
  });
}

function sortedValuations(schools, sort) {
  const rows = schools.slice();
  if (sort === "nil") {
    rows.sort((a, b) => {
      const aMissing = !Number.isFinite(a.nil_budget_usd);
      const bMissing = !Number.isFinite(b.nil_budget_usd);
      if (aMissing !== bMissing) return aMissing ? 1 : -1;
      if (a.nil_budget_usd !== b.nil_budget_usd) return b.nil_budget_usd - a.nil_budget_usd;
      return String(a.school || "").localeCompare(String(b.school || ""));
    });
    return rows;
  }
  rows.sort((a, b) => {
    const ar = Number.isFinite(a.valuation_rank) ? a.valuation_rank : 1e9;
    const br = Number.isFinite(b.valuation_rank) ? b.valuation_rank : 1e9;
    if (ar !== br) return ar - br;
    const av = Number.isFinite(a.valuation_usd) ? a.valuation_usd : -1;
    const bv = Number.isFinite(b.valuation_usd) ? b.valuation_usd : -1;
    if (av !== bv) return bv - av;
    return String(a.school || "").localeCompare(String(b.school || ""));
  });
  return rows;
}

function rankChangeSpots(row) {
  if (Number.isFinite(row.rank_change_spots)) return row.rank_change_spots;
  if (Number.isFinite(row.prior_valuation_rank) && Number.isFinite(row.valuation_rank)) {
    return row.prior_valuation_rank - row.valuation_rank;
  }
  return null;
}

function movementNode(spots) {
  if (spots == null) {
    return h("span", {
      class: "val-move flat",
      text: "—",
      "aria-label": "Valuation rank change is not in the file",
    });
  }
  if (spots === 0) {
    return h("span", {
      class: "val-move flat",
      "aria-label": "No change from the 2025 valuation ranking",
    }, [
      h("span", { class: "val-dash" }),
    ]);
  }
  const up = spots > 0;
  const spotsMoved = Math.abs(spots);
  const unit = spotsMoved === 1 ? "spot" : "spots";
  const label = up
    ? `Up ${spotsMoved} ${unit} from the 2025 valuation ranking`
    : `Down ${spotsMoved} ${unit} from the 2025 valuation ranking`;
  return h("span", { class: up ? "val-move up" : "val-move down", "aria-label": label }, [
    arrowSvg(up),
    document.createTextNode(String(spotsMoved)),
  ]);
}

function arrowSvg(up) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "12");
  svg.setAttribute("height", "12");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute("d", up
    ? "M8 2.2 12.4 7.4H9.5V13.8H6.5V7.4H3.6Z"
    : "M8 13.8 3.6 8.6H6.5V2.2H9.5V8.6H12.4Z");
  svg.append(path);
  return svg;
}

function valuationCount(rows, conference) {
  const noun = rows.length === 1 ? "school" : "schools";
  if (conference === "all") return `${rows.length} ${noun}`;
  return `${rows.length} ${conference} ${noun}`;
}

function lookupSchool(name) {
  const key = String(name || "").toLowerCase();
  return payload.schools.find((school) => school.school.toLowerCase() === key) || null;
}

function formatValuation(usd) {
  if (!Number.isFinite(usd)) return "—";
  const n = Math.round(usd);
  if (Math.abs(n) >= 1000000000) {
    const tenths = Math.round(n / 10000000);
    const sign = tenths < 0 ? "−" : "";
    const abs = Math.abs(tenths);
    const whole = Math.floor(abs / 100);
    const frac = String(abs % 100).padStart(2, "0");
    return `${sign}$${whole}.${frac}B`;
  }
  const millions = Math.round(n / 1000000);
  const sign = millions < 0 ? "−" : "";
  return `${sign}$${Math.abs(millions)}M`;
}

function formatNil(usd) {
  if (!Number.isFinite(usd)) return "—";
  const tenths = Math.round(usd / 100000);
  const sign = tenths < 0 ? "−" : "";
  const abs = Math.abs(tenths);
  const whole = Math.floor(abs / 10);
  const frac = abs % 10;
  return `${sign}$${whole}.${frac}M`;
}

function chips(label, options, current, onPick) {
  return h("div", { class: "chips", role: "group", "aria-label": label }, options.map(([value, text]) =>
    h("button", {
      type: "button",
      text,
      "aria-pressed": current === value ? "true" : "false",
      onclick: () => onPick(value),
    })
  ));
}

function renderError(message) {
  banner.hidden = true;
  view.replaceChildren(h("div", { class: "error" }, [
    h("h2", { text: "No attendance data to show" }),
    h("p", { text: message }),
  ]));
}

function destroyCharts() {
  charts.forEach((chart) => chart.destroy());
  charts = [];
}

function chartAnimation() {
  if (reduceMotionQuery.matches) return false;
  return { duration: 380, easing: "easeOutQuart" };
}

function segment(label, options, current, onPick) {
  return h("div", { class: "segment", role: "group", "aria-label": label }, options.map(([value, text]) =>
    h("button", {
      type: "button",
      text,
      "aria-pressed": current === value ? "true" : "false",
      onclick: () => onPick(value),
    })
  ));
}

function stat(value, label) {
  return h("div", { class: "stat" }, [h("b", { text: value }), h("span", { text: label })]);
}

const PLATE_LIGHT = [255, 255, 255];
const PLATE_INK = [17, 20, 24];
const logoPlates = new Map();
const logoPlateLoads = new Map();

function mark(school, _size) {
  const node = h("div", { class: "mark" });
  if (!school.logo) {
    paintMonogram(node, school);
    return node;
  }
  node.classList.add("mark-logo");
  if (logoPlates.get(school.logo) === "dark") node.classList.add("on-dark");
  const image = h("img", { alt: "", src: school.logo });
  image.addEventListener("error", () => {
    image.remove();
    paintMonogram(node, school);
  });
  node.append(image);
  const plateReady = () => {
    if (!node.classList.contains("mark-logo")) return;
    if (!node.isConnected) {
      if (node.dataset.plateWait === "1") return;
      node.dataset.plateWait = "1";
      queueMicrotask(() => {
        delete node.dataset.plateWait;
        if (node.isConnected) plateReady();
      });
      return;
    }
    revealLogo(node, image);
  };
  if (logoPlates.has(school.logo)) plateReady();
  else {
    settleLogoPlate(school.logo).then((plate) => {
      if (!node.classList.contains("mark-logo")) return;
      node.classList.toggle("on-dark", plate === "dark");
      plateReady();
    });
  }
  return node;
}

const logoQueue = [];
let logoFlush = false;

function revealLogo(node, image) {
  const start = () => {
    if (!node.isConnected) {
      if (node.dataset.logoWait === "1") return;
      node.dataset.logoWait = "1";
      queueMicrotask(() => {
        delete node.dataset.logoWait;
        if (node.isConnected) start();
      });
      return;
    }
    if (!node.classList.contains("mark-logo") || node.dataset.logoIn === "1") return;
    logoQueue.push({ node, image });
    if (logoFlush) return;
    logoFlush = true;
    queueMicrotask(flushLogos);
  };
  if (image.complete && image.naturalWidth > 0) start();
  else if (!image.complete) image.addEventListener("load", start, { once: true });
}

function flushLogos() {
  logoFlush = false;
  const batch = logoQueue.splice(0);
  const visible = [];
  const hidden = [];
  const viewport = window.innerHeight;
  for (let i = 0; i < batch.length; i += 1) {
    const item = batch[i];
    if (!item.node.isConnected || !item.node.classList.contains("mark-logo") || item.node.dataset.logoIn === "1") continue;
    const rect = item.node.getBoundingClientRect();
    if (rect.bottom > 0 && rect.top < viewport) visible.push(item);
    else hidden.push(item);
  }
  for (let i = 0; i < visible.length; i += 1) fadeLogo(visible[i]);
  if (!hidden.length) return;
  if (reduceMotion() || !motionApi) {
    for (let i = 0; i < hidden.length; i += 1) fadeLogo(hidden[i]);
    return;
  }
  motionApi.inView(hidden.map((item) => item.node), (node) => {
    for (let i = 0; i < hidden.length; i += 1) {
      if (hidden[i].node === node) fadeLogo(hidden[i]);
    }
  });
}

function fadeLogo(item) {
  const node = item.node;
  const image = item.image;
  if (!node.isConnected || !node.classList.contains("mark-logo") || node.dataset.logoIn === "1") return;
  node.dataset.logoIn = "1";
  node.classList.add("plate-ready");
  if (reduceMotion() || !motionApi) {
    image.style.opacity = "";
    return;
  }
  motionApi.animate(image, { opacity: [0, 1] }, { duration: 0.24, ease: "easeOut" });
}

function paintMonogram(node, school) {
  node.classList.remove("mark-logo", "on-dark", "plate-ready");
  node.style.background = school.color || "#1e3a5f";
  node.style.color = textOn(school.color);
  node.textContent = initials(school);
}

function settleLogoPlate(url) {
  if (logoPlates.has(url)) return Promise.resolve(logoPlates.get(url));
  if (!logoPlateLoads.has(url)) {
    logoPlateLoads.set(url, measureLogoPlate(url).then((plate) => {
      logoPlates.set(url, plate);
      return plate;
    }));
  }
  return logoPlateLoads.get(url);
}

function measureLogoPlate(url) {
  return loadProbe(probeLogoUrl(url)).then((img) => {
    try {
      const pixels = opaquePixels(img);
      if (!pixels.length) return "light";
      const light = plateScore(pixels, PLATE_LIGHT);
      const ink = plateScore(pixels, PLATE_INK);
      return choosePlate(light, ink);
    } catch (_error) {
      return "light";
    }
  }).catch(() => "light");
}

function probeLogoUrl(url) {
  const match = /\/(\d+)\.png(?:[?#].*)?$/i.exec(url || "");
  if (!match) return url;
  return `https://a.espncdn.com/i/teamlogos/ncaa/500/${match[1]}.png`;
}

function loadProbe(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const timer = setTimeout(() => {
      img.onload = null;
      img.onerror = null;
      reject(new Error("timeout"));
    }, 4000);
    img.onload = () => {
      clearTimeout(timer);
      resolve(img);
    };
    img.onerror = () => {
      clearTimeout(timer);
      reject(new Error("load"));
    };
    img.crossOrigin = "anonymous";
    img.src = src;
  });
}

function opaquePixels(img) {
  const size = 48;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, size, size);
  const data = ctx.getImageData(0, 0, size, size).data;
  const pixels = [];
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 80) continue;
    pixels.push([data[i], data[i + 1], data[i + 2]]);
  }
  return pixels;
}

function plateScore(pixels, plate) {
  const ratios = pixels.map((pixel) => contrastRatio(pixel, plate)).sort((a, b) => a - b);
  const readable = ratios.filter((ratio) => ratio >= 3).length / ratios.length;
  return { readable, median: ratios[Math.floor(ratios.length / 2)] };
}

function choosePlate(light, ink) {
  if (Math.abs(light.median - ink.median) <= 0.35) {
    if (Math.abs(light.readable - ink.readable) <= 0.05) return "light";
    return light.readable >= ink.readable ? "light" : "dark";
  }
  return light.median > ink.median ? "light" : "dark";
}

function contrastRatio(rgb, plate) {
  const left = relativeLum(rgb);
  const right = relativeLum(plate);
  const lighter = Math.max(left, right);
  const darker = Math.min(left, right);
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLum(rgb) {
  return (0.2126 * channelLum(rgb[0])) + (0.7152 * channelLum(rgb[1])) + (0.0722 * channelLum(rgb[2]));
}

function channelLum(value) {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function initials(school) {
  if (school.abbreviation) return school.abbreviation.slice(0, 4);
  return school.school.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function textOn(hex) {
  const raw = (hex || "").replace("#", "");
  if (raw.length < 6) return "#f8fafc";
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  const luminance = (0.299 * r) + (0.587 * g) + (0.114 * b);
  return luminance > 160 ? "#1c1915" : "#f8fafc";
}

function capacityLine(school) {
  if (school.capacity == null) return "Max capacity not reported";
  const place = [school.stadium, school.city, school.state].filter(Boolean).join(", ");
  return `Max capacity ${formatInt(school.capacity)}${place ? ` · ${school.stadium}` : ""}`;
}

function stadiumLine(school) {
  const place = [school.city, school.state].filter(Boolean).join(", ");
  if (school.capacity == null) {
    return `${school.stadium || "Home stadium"} · max capacity not reported${place ? ` · ${place}` : ""}`;
  }
  return `${school.stadium || "Home stadium"} · max capacity ${formatInt(school.capacity)}${place ? ` · ${place}` : ""}`;
}

function statusLabel(status) {
  if (status === "reported") return "Reported";
  if (status === "not_played") return "Not yet played";
  return "Attendance not reported";
}

function resultText(game) {
  if (!game.result) return game.attendance_status === "not_played" ? "Scheduled" : "—";
  const entered = game.entered_record ? ` · entered ${game.entered_record}` : "";
  if (game.home_points == null || game.away_points == null) return `${game.result}${entered}`;
  return `${game.result} ${game.home_points}-${game.away_points}${entered}`;
}

function flagLabel(kind) {
  if (kind === "draws_above_record") return "Draws above record";
  if (kind === "soft_crowd_for_record") return "Soft crowd";
  return "";
}

function omittedSummary(omitted) {
  return omitted.slice(0, 8).map((row) => `${row.school} (${row.reasons[0]})`).join("; ")
    + (omitted.length > 8 ? "…" : ".");
}

function schoolMatches(school, query) {
  return [school.school, school.mascot, school.conference, school.abbreviation]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(query));
}

function formatInt(value) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatMaybeInt(value) {
  if (value == null) return "—";
  return formatInt(Math.round(value));
}

function signedCrowd(value) {
  const rounded = Math.round(value);
  const text = formatInt(Math.abs(rounded));
  if (rounded > 0) return `+${text}`;
  if (rounded < 0) return `−${text}`;
  return text;
}

function formatYearList(years) {
  const labels = years.map(String);
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

function formatPct(fraction) {
  if (fraction == null) return "—";
  const value = Math.round(fraction * 1000) / 10;
  return Number.isInteger(value) ? `${value}%` : `${value.toFixed(1)}%`;
}

function formatStat(value) {
  if (value == null) return "—";
  return Number(value).toFixed(2);
}

function signedPoints(residual) {
  const points = residual * 100;
  const rounded = Math.round(points * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${rounded > 0 ? "+" : ""}${text} pts`;
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "America/New_York",
  }).format(date);
}

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function reduceMotion() {
  return reduceMotionQuery.matches;
}

function renderBowls() {
  if (bowlsPayload) {
    paintBowls(bowlsPayload);
    return;
  }
  const token = ++bowlsToken;
  view.replaceChildren(h("p", { class: "loading", text: "Loading bowl games…" }));
  loadBowls(token);
}

async function loadBowls(token) {
  try {
    const response = await fetch("/api/bowls");
    const body = await response.json();
    if (token !== bowlsToken) return;
    if (!response.ok || body.error) {
      view.replaceChildren(h("div", { class: "error" }, [
        h("h2", { text: "Bowl games are not available" }),
        h("p", { text: body.message || "The bowl file could not be loaded. Matchups were not invented." }),
      ]));
      return;
    }
    bowlsPayload = body;
    if (currentRoute().name === "bowls") paintBowls(body);
  } catch (_error) {
    if (token !== bowlsToken) return;
    view.replaceChildren(h("div", { class: "error" }, [
      h("h2", { text: "Bowl games are not available" }),
      h("p", { text: "The bowl file could not be loaded." }),
    ]));
  }
}

function paintBowls(data) {
  const bracket = data.bracket;
  const nodes = [
    kicker("Postseason"),
    h("h1", { class: "lede", text: "Bowl Games" }),
    h("p", { class: "sublede", text: "The bracket is computed from the latest CFP rankings. The cards below use ESPN’s weekly bowl projections until official matchups replace them on Selection Day." }),
    data.status_note ? h("p", { class: "muted", text: data.status_note }) : null,
    bracket ? bracketPanel(data) : h("p", { text: "The projected bracket is not in this cache." }),
    explainerPanel(data.explainers && data.explainers.bracket),
    bracket ? firstFourOut(bracket) : null,
    unassignedQuarterfinals(data.unassigned_quarterfinal_projections),
    h("h2", { text: "The 2026–27 slate" }),
    projectionNote(data.projection),
    omittedNote(data.omitted),
    explainerPanel(data.explainers && data.explainers.selection),
    explainerPanel(data.explainers && data.explainers.money),
    h("div", { class: "bowl-grid" }, (data.games || []).map(bowlCard)),
  ].filter((node) => node != null);
  fill(view, ...nodes);
  if (!motionFromRender) {
    motionSwap(view);
    motionLists(view, false);
    motionCounts(view);
  }
}

function bracketPanel(data) {
  const bracket = data.bracket;
  const projected = (data.label || bracket.label || "Projected") !== "Official";
  return h("section", { class: "panel cfp-panel" }, [
    h("div", { class: "pills" }, [
      h("span", { class: "pill rank", text: data.label || bracket.label || "Projected" }),
      bracket.as_of ? h("span", { class: "pill quiet", text: `As of ${formatNewsDate(bracket.as_of)}` }) : null,
    ]),
    h("h2", { text: "College Football Playoff" }),
    h("p", { class: "muted", text: bracket.note || "" }),
    h("div", { class: "cfp-scroll" }, [
      h("p", { class: "cfp-scroll-hint", text: "Swipe to follow the bracket." }),
      h("div", { class: "cfp-heads", "aria-hidden": "true" }, [
        h("span", { text: "First round" }),
        h("span", {}),
        h("span", { text: "Quarterfinals" }),
        h("span", {}),
        h("span", { text: "Semifinals" }),
        h("span", {}),
        h("span", { text: "Championship" }),
      ]),
      cfpBoard(bracket, projected),
    ]),
    h("p", { class: "muted cfp-hosts", text: hostLine(bracket) }),
  ]);
}

function cfpBoard(bracket, projected) {
  const first = {};
  (bracket.first_round || []).forEach((game) => {
    first[game.higher_seed] = game;
  });
  const quarters = {};
  (bracket.quarterfinals || []).forEach((game) => {
    quarters[game.bye_seed] = game;
  });
  const semis = bracket.semifinals || [];
  const tree = [
    { row: 1, fr: 8, bye: 1, semi: 0 },
    { row: 2, fr: 5, bye: 4, semi: 0 },
    { row: 3, fr: 7, bye: 2, semi: 1 },
    { row: 4, fr: 6, bye: 3, semi: 1 },
  ];
  const nodes = [];
  tree.forEach((pod) => {
    nodes.push(placed(firstRoundMatch(first[pod.fr], projected), 1, pod.row));
    nodes.push(placed(h("div", { class: "cfp-link", "aria-hidden": "true" }), 2, pod.row));
    nodes.push(placed(quarterMatch(quarters[pod.bye], pod.fr, projected), 3, pod.row));
  });
  nodes.push(mergeJoin(4, 1));
  nodes.push(placed(semiMatch(semis[0], "1 vs 8/9", "4 vs 5/12", projected), 5, 1, 2));
  nodes.push(mergeJoin(4, 3));
  nodes.push(placed(semiMatch(semis[1], "2 vs 7/10", "3 vs 6/11", projected), 5, 3, 2));
  nodes.push(mergeJoin(6, 1, 4));
  nodes.push(placed(titleMatch(bracket.championship, projected), 7, 1, 4));
  return h("div", {
    class: "cfp-board",
    role: "group",
    "aria-label": "Projected College Football Playoff bracket",
  }, nodes);
}

function placed(node, column, row, span) {
  const cell = node.classList && node.classList.contains("cfp-match")
    ? h("div", { class: "cfp-cell" }, [node])
    : node;
  cell.style.gridColumn = String(column);
  cell.style.gridRow = span > 1 ? `${row} / span ${span}` : String(row);
  return cell;
}

function mergeJoin(column, row, span) {
  return placed(h("div", { class: "cfp-join", "aria-hidden": "true" }, [
    h("span", { class: "cfp-elbow cfp-elbow-top" }),
    h("span", { class: "cfp-elbow cfp-elbow-bot" }),
  ]), column, row, span || 2);
}

function firstRoundMatch(game, projected) {
  const home = game && game.home;
  const away = game && game.away;
  const when = game ? [shortBracketDate(game.date), game.time_et].filter(Boolean).join(" · ") : "";
  const site = [game && game.tv, (game && game.site) || "Campus of the higher seed"].filter(Boolean).join(" · ");
  return cfpMatch([cfpSlot(home), cfpSlot(away)], when, site, projected);
}

function quarterMatch(game, higherSeed, projected) {
  const pair = game && Array.isArray(game.first_round_seeds) ? game.first_round_seeds.join(" vs ") : `${higherSeed}`;
  return cfpMatch(
    [cfpSlot(game && game.bye), cfpWinnerSlot(pair)],
    "",
    (game && game.site) || "Chosen by seeds 1–3 on Dec 6",
    projected
  );
}

function semiMatch(game, top, bottom, projected) {
  return cfpMatch(
    [cfpWinnerSlot(top), cfpWinnerSlot(bottom)],
    "",
    (game && game.site) || "Chosen by seeds 1–3 on Dec 6",
    projected
  );
}

function titleMatch(game, projected) {
  const when = game ? [shortBracketDate(game.date), game.time_et].filter(Boolean).join(" · ") : "";
  const place = game ? [game.venue, game.city].filter(Boolean).join(", ") : "Allegiant Stadium, Las Vegas";
  const site = [game && game.tv, place || (game && game.site) || "Allegiant Stadium, Las Vegas"].filter(Boolean).join(" · ");
  return cfpMatch(
    [cfpWinnerSlot("1 vs 4"), cfpWinnerSlot("2 vs 3")],
    when,
    site,
    projected
  );
}

function cfpMatch(slots, when, site, projected) {
  return h("article", { class: "cfp-match" }, [
    h("div", { class: "cfp-slots" }, slots),
    h("p", { class: "cfp-meta" }, [
      h("span", { class: "cfp-when" }, [
        projected ? h("span", { class: "cfp-projected", text: "Projected" }) : null,
        when ? document.createTextNode(`${projected ? " · " : ""}${when}`) : null,
      ]),
      site ? h("span", { class: "cfp-site", text: site }) : null,
    ]),
  ]);
}

function cfpSlot(team) {
  if (!team) {
    return h("div", { class: "cfp-slot cfp-slot-open" }, [
      h("span", { class: "cfp-seed", text: "—" }),
      h("span", { class: "cfp-name", text: "TBD" }),
      h("span", { class: "cfp-rec", text: "" }),
    ]);
  }
  return h("div", { class: "cfp-slot" }, [
    h("span", { class: "cfp-seed", text: String(team.seed) }),
    h("span", { class: "cfp-name", text: team.school || "TBD" }),
    h("span", { class: "cfp-rec", text: team.record || "" }),
  ]);
}

function cfpWinnerSlot(label) {
  return h("div", { class: "cfp-slot cfp-slot-open" }, [
    h("span", { class: "cfp-seed", text: "W" }),
    h("span", { class: "cfp-name", text: label }),
    h("span", { class: "cfp-rec", text: "Winner" }),
  ]);
}

function shortBracketDate(iso) {
  return formatNewsDate(iso).replace(/, \d{4}$/, "");
}

function hostLine(bracket) {
  const assignment = (bracket.quarterfinals && bracket.quarterfinals[0] && bracket.quarterfinals[0].site)
    || "Chosen by seeds 1–3 on Dec 6";
  const names = (pool) => ((pool && pool.bowls) || []).map((bowl) => bowl.bowl).filter(Boolean);
  const quarters = names(bracket.quarterfinal_sites);
  const semis = names(bracket.semifinal_sites);
  const bits = [`Quarterfinal and semifinal sites: ${assignment}.`];
  if (quarters.length) bits.push(`Quarterfinal hosts not yet assigned: ${quarters.join(", ")}.`);
  if (semis.length) bits.push(`Semifinal hosts not yet assigned: ${semis.join(", ")}.`);
  return bits.join(" ");
}

function firstFourOut(bracket) {
  const teams = bracket.first_four_out || [];
  if (!teams.length) return null;
  return h("section", { class: "panel" }, [
    h("h3", { text: "First four out" }),
    h("p", { class: "muted", text: "The next teams in the CFP rankings who are not in this projected field." }),
    h("ol", { class: "out-list" }, teams.map((team) => h("li", {
      text: `${team.school} · CFP ${team.rank}${team.record ? ` · ${team.record}` : ""}`,
    }))),
  ]);
}

function unassignedQuarterfinals(block) {
  if (!block || !Array.isArray(block.projections) || !block.projections.length) return null;
  return h("section", { class: "panel" }, [
    h("h3", { text: "ESPN quarterfinals without a bowl" }),
    h("p", { class: "muted", text: block.note || "" }),
    h("ul", { class: "out-list" }, block.projections.map((row) => h("li", {
      text: `${row.analyst}: ${row.teams.join(" vs ")}${row.window ? ` · ${row.window}` : ""}`,
    }))),
    block.url ? h("p", {}, [h("a", { href: block.url, target: "_blank", rel: "noopener noreferrer", text: "ESPN projection" })]) : null,
  ]);
}

function explainerPanel(explainer) {
  if (!explainer || !explainer.text) return null;
  const links = (explainer.source_urls || []).map((url) => h("a", {
    href: url,
    target: "_blank",
    rel: "noopener noreferrer",
    text: linkLabel(url),
  }));
  return h("section", { class: "panel" }, [
    h("h3", { text: explainer.title || "Notes" }),
    h("p", { text: explainer.text }),
    links.length ? h("p", { class: "source-links" }, links) : null,
  ]);
}

function projectionNote(projection) {
  if (!projection) return null;
  const authors = (projection.authors || []).join(" and ");
  return h("p", { class: "muted", text: `${projection.newer_week_note || ""} Team slots are ${authors ? `${authors}, ` : ""}${projection.week_label || "the latest ESPN projection"}, ${formatNewsDate(projection.date)}. Each team is marked Projected.` });
}

function omittedNote(omitted) {
  const rows = omitted || [];
  if (!rows.length) return null;
  return h("p", { class: "muted", text: rows.map((row) => `${row.name} is ${row.division || "omitted"}. ${row.reason || ""}`).join(" ") });
}

function bowlCard(game) {
  const when = [formatNewsDate(game.date), game.time_et, game.tv].filter(Boolean).join(" · ");
  const place = [game.venue, game.city].filter(Boolean).join(", ") || "Site not assigned";
  return h("article", { class: "bowl-card" }, [
    h("div", { class: "pills" }, [
      game.cfp_round ? h("span", { class: "pill rank", text: cfpRoundLabel(game.cfp_round) }) : h("span", { class: "pill quiet", text: "Bowl" }),
      h("span", { class: "pill quiet", text: "FBS" }),
    ]),
    h("h3", { text: game.name }),
    h("p", { text: when || game.time_note || "Time TBA" }),
    h("p", { text: place }),
    game.venue_note ? h("p", { class: "muted", text: game.venue_note }) : null,
    game.time_note ? h("p", { class: "muted", text: game.time_note }) : null,
    game.tv_note ? h("p", { class: "muted", text: game.tv_note }) : null,
    game.name_note ? h("p", { class: "muted", text: game.name_note }) : null,
    game.site_note ? h("p", { class: "muted", text: game.site_note }) : null,
    h("p", { class: "muted", text: `Tie-in: ${game.tie_ins || "Unknown"}` }),
    teamSlots(game),
    businessDetails(game),
  ]);
}

function cfpRoundLabel(round) {
  if (round === "first") return "CFP first round";
  if (round === "quarterfinal") return "CFP quarterfinal";
  if (round === "semifinal") return "CFP semifinal";
  if (round === "championship") return "CFP championship";
  return "CFP";
}

function teamSlots(game) {
  if (game.projection_agreement && Array.isArray(game.projected_teams) && game.projected_teams.length) {
    return h("div", { class: "bowl-teams" }, [
      h("div", { class: "bowl-slot-row" }, game.projected_teams.map(teamSlot)),
      projectionCredit(game),
    ]);
  }
  const rows = game.projections || [];
  if (!rows.length) {
    return h("div", { class: "bowl-teams" }, [
      h("p", { text: "TBD" }),
      h("p", { class: "muted", text: "No projected teams in the latest ESPN file." }),
    ]);
  }
  return h("div", { class: "bowl-teams" }, [
    ...rows.map((row) => h("div", {}, [
      h("p", { class: "muted", text: row.analyst }),
      h("div", { class: "bowl-slot-row" }, (row.teams || []).map((school) => teamSlot({ school, status: row.status || "Projected" }))),
    ])),
    projectionCredit(game),
  ]);
}

function teamSlot(team) {
  return h("div", { class: "bowl-slot" }, [
    h("strong", { text: team.school || "TBD" }),
    h("span", { text: team.status || "Projected" }),
  ]);
}

function projectionCredit(game) {
  if (!game.projection_url) return null;
  const when = game.projection_date ? formatNewsDate(game.projection_date) : "";
  return h("p", { class: "source-links" }, [
    h("a", {
      href: game.projection_url,
      target: "_blank",
      rel: "noopener noreferrer",
      text: `ESPN projection${when ? `, ${when}` : ""}`,
    }),
  ]);
}

function businessDetails(game) {
  const business = game.business || {};
  const sponsor = business.title_sponsor || {};
  const payout = business.payout || {};
  const impact = business.economic_impact || {};
  const prior = payout.distribution_2025_26;
  const links = sourceLinks(business);
  return h("details", { class: "bowl-business" }, [
    h("summary", { text: "Business" }),
    h("p", {}, [
      h("strong", { text: "Title sponsor. " }),
      document.createTextNode(sponsor.name || "Unknown"),
      document.createTextNode(sponsor.since_year ? ` since ${sponsor.since_year}` : sponsor.name ? ". Start year unknown." : ""),
    ]),
    sponsor.note ? h("p", { class: "muted", text: sponsor.note }) : null,
    h("p", {}, [
      h("strong", { text: "Payout. " }),
      document.createTextNode(payoutLine(payout)),
    ]),
    payout.note ? h("p", { class: "muted", text: payout.note }) : null,
    prior ? h("p", { class: "muted", text: priorLine(prior) }) : null,
    h("p", {}, [
      h("strong", { text: "Economic impact. " }),
      document.createTextNode(impactLine(impact)),
    ]),
    impact.includes ? h("p", { class: "muted", text: impact.includes }) : null,
    h("p", {}, [
      h("strong", { text: "Attendance. " }),
      document.createTextNode(business.attendance && business.attendance.text ? business.attendance.text : "Unknown"),
    ]),
    links.length ? h("p", { class: "source-links" }, links) : null,
  ]);
}

function payoutLine(payout) {
  const parts = [];
  if (payout.per_team != null) parts.push(`${formatDollars(payout.per_team)} per team`);
  else parts.push("Per team unknown");
  if (payout.total != null) parts.push(`${formatDollars(payout.total)} total`);
  if (payout.expense_stipend_per_conference_per_round != null) {
    parts.push(`${formatDollars(payout.expense_stipend_per_conference_per_round)} expense stipend per conference per round (${payout.expense_stipend_year || "year unknown"})`);
  }
  return parts.join(". ") + ".";
}

function priorLine(prior) {
  return `2025-26 distribution, not the 2026-27 payout: ${formatDollars(prior.apr_payment)} APR payment per qualifying school; ${formatDollars(prior.per_cfp_team)} per CFP team; ${formatDollars(prior.per_quarterfinal_advance)} more for a quarterfinal; ${formatDollars(prior.per_semifinal_advance)} for a semifinal; ${formatDollars(prior.per_championship_advance)} for the championship game; ${formatDollars(prior.expense_stipend_per_conference_per_round)} expense stipend per conference per round.`;
}

function impactLine(impact) {
  if (impact.amount_text) {
    const bits = [impact.amount_text];
    if (impact.year) bits.push(String(impact.year));
    if (impact.author) bits.push(impact.author);
    if (impact.geography) bits.push(impact.geography);
    return bits.join(" · ");
  }
  if (impact.amount == null) return "Unknown";
  const bits = [formatDollars(impact.amount)];
  if (impact.year) bits.push(String(impact.year));
  if (impact.author) bits.push(impact.author);
  if (impact.geography) bits.push(impact.geography);
  return bits.join(" · ");
}

function sourceLinks(business) {
  const seen = new Set();
  const urls = [];
  const collect = (node) => {
    if (!node || typeof node !== "object") return;
    const list = node.source_urls;
    if (Array.isArray(list)) {
      list.forEach((url) => {
        if (typeof url === "string" && url.startsWith("http") && !seen.has(url)) {
          seen.add(url);
          urls.push(url);
        }
      });
    }
    Object.values(node).forEach((value) => {
      if (value && typeof value === "object") collect(value);
    });
  };
  collect(business);
  return urls.map((url) => h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: linkLabel(url) }));
}

function linkLabel(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_error) {
    return "Source";
  }
}

function formatDollars(value) {
  if (value == null || Number.isNaN(Number(value))) return "Unknown";
  const number = Number(value);
  if (Math.abs(number) >= 1000000) {
    const millions = number / 1000000;
    const text = Number.isInteger(millions) ? String(millions) : String(Math.round(millions * 100) / 100);
    return `$${text} million`;
  }
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(number);
}

function motionShellKey(route) {
  if (route.name === "school") return `school:${route.slug}:${route.view || "attendance"}`;
  if (route.name === "marketing") return `marketing:${marketingYear}`;
  return route.name;
}

function motionViewKey(route) {
  if (route.name === "school" && route.view === "campaigns") {
    return `${motionShellKey(route)}:${route.year || 2026}`;
  }
  if (route.name === "school") return `${motionShellKey(route)}:${filters.span}`;
  return motionShellKey(route);
}

function motionSwap(node) {
  if (!node || reduceMotion() || !motionApi) return;
  motionApi.animate(node, {
    opacity: [0, 1],
    transform: ["translateY(8px)", "translateY(0px)"],
  }, { duration: 0.3, ease: "easeOut" });
}

function motionLists(root, withOpacity) {
  if (!root || reduceMotion() || !motionApi) return;
  const cards = root.querySelectorAll(".grid > .card, .bowl-grid > .bowl-card");
  if (cards.length) staggerNodes(cards, withOpacity);
  const lists = root.querySelectorAll(".loyal-list, .approach-grid, .outlier-grid, .val-board, .campaign-list");
  for (let i = 0; i < lists.length; i += 1) {
    const kids = lists[i].querySelectorAll(":scope > .loyal-row, :scope > .approach-card, :scope > .outlier, :scope > .val-row, :scope > .campaign");
    if (kids.length) staggerNodes(kids, withOpacity);
  }
  const boards = root.querySelectorAll(".cfp-board");
  for (let i = 0; i < boards.length; i += 1) {
    const matches = boards[i].querySelectorAll(".cfp-match");
    if (matches.length) staggerNodes(matches, withOpacity);
  }
  const bodies = root.querySelectorAll(".table-wrap:not(.fit-table) > table > tbody");
  for (let i = 0; i < bodies.length; i += 1) {
    const rows = bodies[i].querySelectorAll(":scope > tr");
    if (rows.length) staggerNodes(rows, withOpacity);
  }
}

function staggerNodes(nodes, withOpacity) {
  const batch = [];
  const cap = 8;
  if (nodes.length <= 12) {
    const count = Math.min(nodes.length, 12);
    for (let i = 0; i < count; i += 1) batch.push(nodes[i]);
  } else {
    const viewport = window.innerHeight;
    for (let i = 0; i < nodes.length && batch.length < cap; i += 1) {
      const rect = nodes[i].getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < viewport) batch.push(nodes[i]);
    }
    if (!batch.length) {
      for (let i = 0; i < cap && i < nodes.length; i += 1) batch.push(nodes[i]);
    }
  }
  if (!batch.length) return;
  const values = withOpacity
    ? { opacity: [0, 1], transform: ["translateY(8px)", "translateY(0px)"] }
    : { transform: ["translateY(6px)", "translateY(0px)"] };
  motionApi.animate(batch, values, {
    duration: 0.26,
    ease: "easeOut",
    delay: motionApi.stagger(0.018),
  });
}

function afterPartial(node) {
  if (motionFromRender || !node) return;
  motionSwap(node);
  motionLists(node, false);
  motionCounts(node);
}

function applyCount(props, spec) {
  if (!spec || !Number.isFinite(Number(spec.value))) return;
  props["data-count"] = spec.key;
  props["data-count-value"] = String(spec.value);
  props["data-count-kind"] = spec.kind || "int";
}

function countProps(text, spec) {
  const props = { text };
  applyCount(props, spec);
  return props;
}

function motionCounts(root) {
  if (!root) return;
  const nodes = root.querySelectorAll("[data-count]");
  const jobs = [];
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i];
    const key = node.getAttribute("data-count");
    const kind = node.getAttribute("data-count-kind") || "int";
    const target = Number(node.getAttribute("data-count-value"));
    node.removeAttribute("data-count");
    node.removeAttribute("data-count-kind");
    node.removeAttribute("data-count-value");
    if (!key || countedStats.has(key) || !Number.isFinite(target) || target === 0) continue;
    if (node.closest("[aria-live]")) continue;
    jobs.push({ node, key, kind, target, finalText: node.textContent });
  }
  if (!jobs.length) return;
  if (reduceMotion() || !motionApi) {
    for (let i = 0; i < jobs.length; i += 1) countedStats.add(jobs[i].key);
    return;
  }
  const viewport = window.innerHeight;
  const hidden = [];
  for (let i = 0; i < jobs.length; i += 1) {
    const rect = jobs[i].node.getBoundingClientRect();
    if (rect.bottom > 0 && rect.top < viewport) playCount(jobs[i]);
    else hidden.push(jobs[i]);
  }
  if (!hidden.length) return;
  motionApi.inView(hidden.map((job) => job.node), (node) => {
    for (let i = 0; i < hidden.length; i += 1) {
      if (hidden[i].node === node) playCount(hidden[i]);
    }
  });
}

function playCount(job) {
  if (!job.node.isConnected || countedStats.has(job.key)) return;
  countedStats.add(job.key);
  const renderValue = (value) => renderCount(job.kind, value);
  job.node.textContent = renderValue(0);
  const controls = motionApi.animate(0, job.target, {
    duration: 0.4,
    ease: "easeOut",
    onUpdate: (latest) => {
      job.node.textContent = renderValue(latest);
    },
  });
  const finish = () => {
    if (job.node.isConnected) job.node.textContent = job.finalText;
  };
  if (controls && controls.finished && typeof controls.finished.then === "function") controls.finished.then(finish);
  else window.setTimeout(finish, 420);
}

function renderCount(kind, value) {
  if (kind === "pct") return formatPct(value);
  if (kind === "pct-full") return `${formatPct(value)} full`;
  if (kind === "usd") return formatValuation(value);
  if (kind === "nil") return formatNil(value);
  return formatInt(Math.round(value));
}

function captureValuationTops() {
  const map = new Map();
  const rows = view.querySelectorAll(".val-row");
  for (let i = 0; i < rows.length; i += 1) {
    const id = rows[i].getAttribute("data-school");
    if (id) map.set(id, rows[i].getBoundingClientRect().top);
  }
  return map;
}

function flipValuationRows(previous) {
  if (reduceMotion() || !motionApi) return;
  const rows = view.querySelectorAll(".val-row");
  const animated = [];
  const fresh = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i];
    const id = row.getAttribute("data-school");
    if (!id || !previous.has(id)) {
      fresh.push(row);
      continue;
    }
    const delta = previous.get(id) - row.getBoundingClientRect().top;
    if (delta > 0.5 || delta < -0.5) animated.push({ row, delta });
  }
  for (let i = 0; i < animated.length; i += 1) {
    const item = animated[i];
    const controls = motionApi.animate(item.row, {
      transform: [`translateY(${item.delta}px)`, "translateY(0px)"],
    }, { duration: 0.34, ease: "easeOut" });
    const clear = () => {
      if (item.row.isConnected) item.row.style.transform = "";
    };
    if (controls && controls.finished && typeof controls.finished.then === "function") {
      controls.finished.then(() => requestAnimationFrame(clear));
    } else {
      window.setTimeout(clear, 380);
    }
  }
  if (fresh.length) staggerNodes(fresh, true);
}

function fill(node, ...children) {
  node.replaceChildren(...children.filter((child) => child != null));
}

function kicker(text) {
  return h("p", { class: "kicker", "aria-hidden": "true", text });
}

function h(tag, props, children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value == null) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  });
  (children || []).filter((child) => child != null).forEach((child) => node.append(child));
  return node;
}
