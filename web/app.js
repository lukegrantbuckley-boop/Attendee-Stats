/* Attendee Tracker UI. Attendance comes from /api/season and /api/school.
   Business headlines load separately from /api/school/{slug}/business-news. */

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
const filters = { query: "", tier: "all", sort: "ap", span: 1 };

const RANGE_OPTIONS = [
  [1, "This season"],
  [5, "Last 5 seasons"],
  [10, "Last 10 seasons"],
];

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

function applyChrome() {
  const meta = payload.meta;
  const poll = meta.ap_week
    ? `AP Top 25, week ${meta.ap_week}${meta.ap_season_type === "postseason" ? " postseason" : ""}`
    : "AP poll not in this cache";
  const source = meta.synthetic ? "Sample data" : "College Football Data";
  seasonLabel.textContent = `${meta.season} season · ${poll} · ${source}`;
  document.title = `Attendee Tracker · ${meta.season}`;
  if (meta.banner) {
    banner.hidden = false;
    banner.replaceChildren(
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
  if (route.name === "analysis") renderAnalysis();
  else if (route.name === "school") renderSchool(route.slug);
  else renderHome();
  view.focus({ preventScroll: true });
}

function currentRoute() {
  const hash = decodeURIComponent((location.hash || "#/").replace(/^#/, ""));
  if (hash === "/analysis") return { name: "analysis" };
  const match = hash.match(/^\/schools\/([^/]+)/);
  if (match) return { name: "school", slug: match[1] };
  return { name: "home" };
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.dataset.nav === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
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

  const intro = filters.sort === "record"
    ? "Sorted by season record. Ties break toward the latest AP rank, and unranked schools follow ranked schools when the record is the same."
    : "Sorted by the latest AP Top 25. Unranked schools follow the ranked ones. Record breaks ties.";

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

  view.replaceChildren(
    h("p", { class: "lede", text: "Home crowds for every FBS program, grouped by conference." }),
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
        ["ap", "AP rank"],
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
}

function schoolCard(school) {
  const rank = school.ap_rank
    ? h("span", { class: "pill rank", text: `AP ${school.ap_rank}` })
    : h("span", { class: "pill unranked", text: "Unranked" });
  const missing = school.missing_attendance_games
    ? h("span", { class: "pill warn", text: `${school.missing_attendance_games} attendance missing` })
    : null;
  return h("a", {
    class: "card",
    href: `#/schools/${encodeURIComponent(school.slug)}`,
    style: `--rail:${school.color}`,
  }, [
    mark(school, 58),
    h("div", {}, [
      h("h3", { text: school.school }),
      h("p", { class: "mascot", text: [school.mascot, school.conference].filter(Boolean).join(" · ") }),
      h("div", { class: "pills" }, [
        h("span", { class: "pill", text: school.record || "Record unavailable" }),
        rank,
        school.pro_shared_stadium ? h("span", { class: "pill pro", text: "NFL stadium" }) : null,
        missing,
      ]),
      h("p", { class: "capacity", text: capacityLine(school) }),
      attendancePins(school),
    ]),
  ]);
}

function attendancePins(school) {
  return h("div", { class: "pins" }, [
    pin("Season avg", seasonAvgValue(school), seasonAvgMeta(school)),
    pin("Last home", lastHomeValue(school), lastHomeMeta(school)),
  ]);
}

function pin(label, value, meta) {
  return h("div", { class: "pin" }, [
    h("span", { class: "pin-k", text: label }),
    h("strong", { text: value }),
    h("span", { class: "pin-m", text: meta }),
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

function renderSchool(slug) {
  const school = schoolsBySlug[slug];
  if (!school) {
    view.replaceChildren(
      h("a", { class: "back", href: "#/", text: "All schools" }),
      h("div", { class: "error" }, [
        h("h2", { text: "School not in this cache" }),
        h("p", { text: "That program is not in the loaded season." }),
      ])
    );
    return;
  }
  const token = ++historyToken;
  const endYear = Number(payload.meta.season);
  view.replaceChildren(
    h("a", { class: "back", href: "#/", text: "All schools" }),
    h("div", { class: "school-head" }, [
      mark(school, 84),
      h("div", {}, [
        h("p", { class: "muted", text: `${school.conference} · ${school.tier}` }),
        h("h2", { text: school.school }),
        h("div", { class: "pills" }, [
          h("span", { class: "pill", text: school.record || "Record unavailable" }),
          school.pro_shared_stadium ? h("span", { class: "pill pro", text: "NFL stadium" }) : null,
          school.ap_rank
            ? h("span", { class: "pill rank", text: `AP ${school.ap_rank}` })
            : h("span", { class: "pill unranked", text: "Unranked" }),
          school.recent_record
            ? h("span", { class: "pill quiet", text: `Last ${school.recent_form.games}: ${school.recent_record}` })
            : null,
        ]),
        h("p", { class: "capacity", text: stadiumLine(school) }),
        school.pro_shared_stadium
          ? h("p", { class: "pro-note", text: school.pro_stadium_note || "NFL stadium. Official capacity fill is not compared with on-campus stadiums." })
          : null,
        attendancePins(school),
      ]),
    ]),
    h("div", { class: "range-bar" }, [
      segment("Attendance range", RANGE_OPTIONS, filters.span, (value) => {
        filters.span = Number(value);
        render();
      }),
      h("p", { class: "muted range-hint", text: rangeHint(endYear, filters.span) }),
    ]),
    h("div", { id: "school-body", "aria-live": "polite" }),
    businessNewsSection(slug)
  );
  if (filters.span === 1) {
    fillSeasonBody(school);
    return;
  }
  const bounds = historyBounds(filters.span, endYear);
  const body = document.getElementById("school-body");
  body.replaceChildren(h("p", { class: "loading", text: `Loading ${bounds.start}–${bounds.end} home attendance…` }));
  loadHistory(slug, school, bounds, token);
}

function rangeHint(endYear, span) {
  if (span === 1) {
    if (Number(endYear) === 2020) {
      return "2020 is omitted as the COVID season. The season average is not shown. Individual games stay in the cache and are not averaged.";
    }
    return `${endYear} home games, one bar or point per opponent. Gaps are unreported or not yet played.`;
  }
  const start = endYear - span + 1;
  const base = `${start}–${endYear}: average reported home attendance by season. Missing years stay blank.`;
  if (windowIncludesCovid(start, endYear)) {
    return `${base} 2020 is omitted as the COVID season, so this window uses the other seasons only.`;
  }
  return base;
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
  node.replaceChildren(
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

function fillSeasonBody(school) {
  const games = school.home_games || [];
  const gaps = games.filter((game) => game.attendance_status !== "reported");
  const body = document.getElementById("school-body");
  if (!body) return;
  body.replaceChildren(
    h("section", { class: "panel" }, [
      h("h3", { text: "Home attendance by opponent" }),
      h("p", { class: "muted", text: isCovidOmitted(school) || Number(payload.meta.season) === 2020
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
  node.replaceChildren(
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
        backgroundColor: school.color || "#1e3a5f",
        borderRadius: 6,
        maxBarThickness: 56,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
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
          ticks: { callback: (value) => formatInt(value) },
        },
      },
    },
  });
  charts.push(chart);
}

function renderAnalysis() {
  const analysis = payload.analysis;
  const meta = payload.meta;
  view.replaceChildren(
    h("p", { class: "lede", text: "Does a weaker record come with a thinner crowd?" }),
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
    loyaltyIntro(analysis.loyalty),
    h("div", { class: "loyalty-grid" }, [
      loyaltyPanel(
        "most-loyal",
        "Most loyal fans",
        "A record at or below the median, and the stadium is still full. Ordered from the highest share of seats filled.",
        analysis.loyalty.most_loyal
      ),
      loyaltyPanel(
        "soft-support",
        "Softest home support",
        "The same below-median records, ordered from the lowest share of seats filled. Empty here means empty relative to that stadium, not a smaller headcount.",
        analysis.loyalty.softest_support
      ),
    ]),
    proStadiumSection(analysis),
    growthSection(meta.season),
    h("section", { class: "panel" }, [
      h("h3", { text: "Capacity filled vs season record" }),
      h("div", { class: "chart-wrap" }, [h("canvas", { id: "scatter-chart" })]),
      h("p", { class: "muted", text: analysis.outlier_note }),
    ]),
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
  drawScatter(analysis);
}

function loyaltyIntro(loyalty) {
  if (!loyalty || loyalty.win_pct_median == null) {
    return h("p", { class: "sublede", text: "Most loyal fans and softest home support need the same teams as the fit: two reported home crowds with a capacity percentage, and two decided games. None qualify in this cache." });
  }
  return h("p", { class: "sublede", text: `A bad record is a win percentage at or below ${formatPct(loyalty.win_pct_median)}, the median of the ${loyalty.n_qualifying} teams in the fit. ${loyalty.n_bad_record} teams are in that group. Both lists rank them by average home capacity filled, never by raw attendance.` });
}

function loyaltyPanel(id, title, blurb, rows) {
  return h("section", { class: "panel", id }, [
    h("h3", { text: title }),
    h("p", { class: "muted", text: blurb }),
    rows && rows.length
      ? h("div", { class: "loyal-list" }, rows.map(loyaltyRow))
      : h("p", { text: "No qualifying team has a below-median record in this cache." }),
  ]);
}

function loyaltyRow(row) {
  const games = row.reported_home_games == null ? "" : `${row.reported_home_games} reported`;
  const meta = [row.record || "Record unavailable", `${formatPct(row.win_pct)} wins`, games].filter(Boolean).join(" · ");
  const crowd = row.avg_home_attendance == null ? null : `Avg crowd ${formatMaybeInt(row.avg_home_attendance)}`;
  return h("a", { class: "loyal-row", href: `#/schools/${encodeURIComponent(row.slug)}` }, [
    h("span", { class: "loyal-rank", text: String(row.rank) }),
    mark(row, 42),
    h("div", { class: "loyal-name" }, [
      h("strong", { text: row.school }),
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
  node.replaceChildren(
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
      labels: games.map((game) => game.label),
      datasets: [{
        label: "Attendance",
        data: games.map((game) => (game.attendance_status === "reported" ? game.attendance : null)),
        borderColor: school.color,
        backgroundColor: school.color,
        pointBackgroundColor: school.color,
        pointRadius: 5,
        spanGaps: false,
        tension: 0.15,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
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
          ticks: { callback: (value) => formatInt(value) },
        },
        x: { ticks: { maxRotation: 50, minRotation: 30, autoSkip: false } },
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
  const datasets = [
    scatterSet("Teams in the fit", groups.other, "#1e3a5f"),
    scatterSet("Draws above the record", groups.draws_above_record, "#c2410c"),
    scatterSet("Soft crowd for the record", groups.soft_crowd_for_record, "#0f766e"),
  ];
  if (analysis.line) {
    datasets.push({
      type: "line",
      label: "Fitted line",
      data: [
        { x: analysis.line.x1 * 100, y: analysis.line.y1 * 100 },
        { x: analysis.line.x2 * 100, y: analysis.line.y2 * 100 },
      ],
      borderColor: "#9a3412",
      borderDash: [6, 4],
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
      onClick(_event, elements) {
        if (!elements.length) return;
        const item = chart.data.datasets[elements[0].datasetIndex].data[elements[0].index];
        if (item && item.slug) location.hash = `#/schools/${encodeURIComponent(item.slug)}`;
      },
      plugins: {
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
        x: { title: { display: true, text: "Season win percentage" }, min: xScale.min, max: xScale.max, ticks: { callback: (value) => `${value}%` } },
        y: { title: { display: true, text: "Average capacity filled" }, min: yScale.min, max: yScale.max, ticks: { callback: (value) => `${value}%` } },
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

function scatterSet(label, points, color) {
  return {
    type: "scatter",
    label,
    data: points,
    backgroundColor: color,
    pointRadius: label === "Teams in the fit" ? 5 : 7,
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

function mark(school, _size) {
  const node = h("div", { class: "mark", style: `background:${school.color};color:${textOn(school.color)}` });
  if (school.logo) {
    const image = h("img", { alt: "", src: school.logo });
    image.addEventListener("error", () => {
      image.remove();
      node.textContent = initials(school);
    });
    node.append(image);
  } else {
    node.textContent = initials(school);
  }
  return node;
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
