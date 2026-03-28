const DATA_URL = "data/anomalies.json";

/* Stat → icon + data-attribute for CSS colouring */
const STAT_META = {
  PTS:          { icon: "\u{1F3C0}", label: "Points" },        // 🏀
  REB:          { icon: "\u{1F4CA}", label: "Rebounds" },       // 📊
  AST:          { icon: "\u{1F3AF}", label: "Assists" },        // 🎯
  STL:          { icon: "\u{1F440}", label: "Steals" },         // 👀
  BLK:          { icon: "\u{1F6E1}\uFE0F", label: "Blocks" },  // 🛡️
  FG3M:         { icon: "\u{1F3C0}", label: "Threes" },         // 🏀
  total_points: { icon: "\u{1F3C6}", label: "Total Points" },   // 🏆
};

function statBadge(stat, label) {
  const m = STAT_META[stat] || { icon: "", label: label || stat };
  const displayLabel = label || m.label;
  return `<span class="stat-badge" data-stat="${stat}"><span class="stat-icon">${m.icon}</span>${displayLabel}</span>`;
}

function directionIcon(dir) {
  return dir === "hot" ? "\u{1F525}" : "\u{2744}\uFE0F";  // 🔥 or ❄️
}

let allData = null;
let filters = { direction: "all", stat: "all", type: "all", game: "all" };

async function loadData() {
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    allData = await resp.json();
    renderMeta();
    populateGameFilter();
    renderAll();
  } catch (err) {
    const el = document.getElementById("updated-at");
    el.classList.remove("loading-shimmer");
    el.textContent = "Data unavailable";
    console.error("Failed to load anomalies.json:", err);
  }
}

function renderMeta() {
  if (!allData) return;
  const dt = new Date(allData.generated_at);
  const el = document.getElementById("updated-at");
  el.classList.remove("loading-shimmer");
  el.textContent = dt.toLocaleDateString("en-AU", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Australia/Sydney",
  });

  const m = allData.meta;
  document.getElementById("meta-info").textContent =
    `${m.players_with_sportsbet_markets} markets \u00b7 ${m.events_count} games`;
}

function populateGameFilter() {
  const select = document.getElementById("game-filter");
  const games = allData.games || [];
  games.forEach((game) => {
    const opt = document.createElement("option");
    opt.value = game;
    opt.textContent = game;
    select.appendChild(opt);
  });
}

function matchesGameFilter(anomaly) {
  if (filters.game === "all") return true;
  if (anomaly.game) return anomaly.game === filters.game;
  if (anomaly.team_name) {
    return filters.game.includes(anomaly.team_name.split(" ").pop());
  }
  if (anomaly.team) {
    return filters.game.includes(anomaly.team);
  }
  return false;
}

function renderAll() {
  renderFeaturedBets();
  renderPlayerAnomalies();
  renderTeamAnomalies();
  checkNoResults();
}

function renderFeaturedBets() {
  const container = document.getElementById("featured-bets");
  const section = document.getElementById("featured-section");
  const featured = allData.featured_bets || [];

  if (
    filters.game !== "all" ||
    filters.stat !== "all" ||
    filters.direction !== "all" ||
    filters.type !== "all"
  ) {
    section.style.display = "none";
    return;
  }
  section.style.display = "";

  container.innerHTML = featured
    .slice(0, 10)
    .map((a, i) => {
      const rank = i + 1;
      const sbUrl = a.sportsbet_url || "";
      const linkOpen = sbUrl
        ? `<a href="${sbUrl}" target="_blank" rel="noopener" class="betting-line-link">`
        : "";
      const linkClose = sbUrl ? "</a>" : "";

      const isTeam = a.is_team;
      const name = isTeam ? a.team_name : a.player_name;
      const subtitle = isTeam
        ? a.team_abbr || ""
        : `${a.team || ""} \u00b7 ${a.games_played} GP`;
      const gameTag = a.game
        ? `<span class="game-tag">${a.game}</span>`
        : "";

      const bl = a.betting_line || {};
      const line = bl.line;
      let lineText = "";
      if (bl.market_type === "over_under" || line != null) {
        const over = bl.over_price != null ? bl.over_price : "\u2014";
        const under = bl.under_price != null ? bl.under_price : "\u2014";
        lineText = `${line} (O ${over} / U ${under})`;
      } else if (bl.market_type === "threshold" && bl.thresholds) {
        lineText = Object.entries(bl.thresholds)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([t, d]) => `${t}+ @ ${d.price}`)
          .join(", ");
      }

      let vsLineHTML = "";
      if (line != null) {
        const pct = (((a.last_3_avg - line) / line) * 100).toFixed(1);
        const cls = Number(pct) > 0 ? "positive" : "negative";
        const lbl = Number(pct) > 0 ? `+${pct}%` : `${pct}%`;
        vsLineHTML = `<span class="deviation ${cls}">${lbl} vs line</span>`;
      }

      const seasonDev = isTeam
        ? a.pct_diff
        : Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10)
          ? a.pct_diff_season
          : a.pct_diff_l10;
      const devClass = seasonDev > 0 ? "positive" : "negative";
      const devLabel = seasonDev > 0 ? `+${seasonDev}%` : `${seasonDev}%`;
      const devComp = isTeam
        ? "vs season"
        : Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10)
          ? "vs season"
          : "vs L10";

      return `
      <div class="featured-card ${a.direction}">
        <div class="featured-rank">${rank}</div>
        <div class="featured-content">
          <div class="featured-header">
            <div>
              <span class="featured-action ${a.bet_action.toLowerCase()}">${a.bet_action}</span>
              <strong>${name}</strong>
              ${statBadge(a.stat || "total_points", a.stat_label || "Total Points")}
            </div>
            <span class="featured-score">Score ${a.score}</span>
          </div>
          ${gameTag}
          <div class="last-3-games">
            ${a.last_3.map((v) => `<span class="game-value">${v}</span>`).join("")}
          </div>
          <div class="averages">
            <span>Season <strong>${a.season_avg}</strong></span>
            <span>L10 <strong>${a.l10_avg}</strong></span>
            <span>L3 <strong>${a.last_3_avg}</strong></span>
          </div>
          ${lineText ? `${linkOpen}<div class="betting-line">${lineText}</div>${linkClose}` : ""}
          <div class="deviations">
            <span class="deviation ${devClass}">${devLabel} ${devComp}</span>
            ${vsLineHTML}
          </div>
        </div>
      </div>
    `;
    })
    .join("");
}

function renderPlayerAnomalies() {
  const container = document.getElementById("player-anomalies");
  const section = document.getElementById("player-section");

  if (filters.type === "teams") {
    section.style.display = "none";
    return;
  }
  section.style.display = "";

  const pa = allData.player_anomalies || {};
  let anomalies = [...(pa.hot || []), ...(pa.cold || [])];

  if (filters.direction !== "all") {
    anomalies = anomalies.filter((a) => a.direction === filters.direction);
  }
  if (filters.stat !== "all") {
    anomalies = anomalies.filter((a) => a.stat === filters.stat);
  }
  if (filters.game !== "all") {
    anomalies = anomalies.filter(matchesGameFilter);
  }

  function maxDeviation(a) {
    let max = Math.max(Math.abs(a.pct_diff_season), Math.abs(a.pct_diff_l10));
    if (a.betting_line && a.betting_line.line != null) {
      const vsLine = Math.abs(
        ((a.last_3_avg - a.betting_line.line) / a.betting_line.line) * 100
      );
      max = Math.max(max, vsLine);
    }
    return max;
  }
  anomalies.sort((a, b) => maxDeviation(b) - maxDeviation(a));

  container.innerHTML = anomalies.map(renderPlayerCard).join("");
}

function renderPlayerCard(a) {
  const sbUrl = a.sportsbet_url || "";
  const lineHTML = a.betting_line
    ? renderBettingLine(a.betting_line, a.stat, sbUrl)
    : "";
  const devMax =
    Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10)
      ? a.pct_diff_season
      : a.pct_diff_l10;
  const devClass = devMax > 0 ? "positive" : "negative";
  const devLabel = devMax > 0 ? `+${devMax}%` : `${devMax}%`;
  const compLabel =
    Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10)
      ? "vs season"
      : "vs L10";
  const gameTag = a.game
    ? `<span class="game-tag">${a.game}</span>`
    : "";

  let vsLineHTML = "";
  if (a.betting_line && a.betting_line.line != null) {
    const line = a.betting_line.line;
    const pctVsLine = (((a.last_3_avg - line) / line) * 100).toFixed(1);
    const vsLineClass = Number(pctVsLine) > 0 ? "positive" : "negative";
    const vsLineLabel =
      Number(pctVsLine) > 0 ? `+${pctVsLine}%` : `${pctVsLine}%`;
    vsLineHTML = `<span class="deviation ${vsLineClass}">${vsLineLabel} vs line</span>`;
  }

  return `
    <div class="anomaly-card ${a.direction}" data-stat="${a.stat}" data-direction="${a.direction}">
      <div class="card-header">
        <div class="player-info">
          <h3>${a.player_name}</h3>
          <span class="team">${a.team} \u00b7 ${a.games_played} GP</span>
        </div>
        <span class="direction-badge">${directionIcon(a.direction)}</span>
      </div>
      ${gameTag}
      ${statBadge(a.stat, a.stat_label)}
      <div class="last-3-games">
        ${a.last_3.map((v) => `<span class="game-value">${v}</span>`).join("")}
      </div>
      <div class="averages">
        <span>Season <strong>${a.season_avg}</strong></span>
        <span>L10 <strong>${a.l10_avg}</strong></span>
        <span>L3 <strong>${a.last_3_avg}</strong></span>
      </div>
      ${lineHTML}
      <div class="deviations">
        <span class="deviation ${devClass}">${devLabel} ${compLabel}</span>
        ${vsLineHTML}
      </div>
    </div>
  `;
}

function renderBettingLine(line, stat, sbUrl) {
  const linkOpen = sbUrl
    ? `<a href="${sbUrl}" target="_blank" rel="noopener" class="betting-line-link">`
    : "";
  const linkClose = sbUrl ? "</a>" : "";

  if (line.market_type === "over_under" || line.line != null) {
    const over = line.over_price != null ? line.over_price : "\u2014";
    const under = line.under_price != null ? line.under_price : "\u2014";
    return `${linkOpen}<div class="betting-line">${line.line} (O ${over} / U ${under})</div>${linkClose}`;
  }
  if (line.market_type === "threshold" && line.thresholds) {
    const entries = Object.entries(line.thresholds)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([t, d]) => `${t}+ @ ${d.price}`)
      .join(", ");
    return `${linkOpen}<div class="betting-line">${entries}</div>${linkClose}`;
  }
  return "";
}

function renderTeamAnomalies() {
  const container = document.getElementById("team-anomalies");
  const section = document.getElementById("team-section");

  if (filters.type === "players") {
    section.style.display = "none";
    return;
  }
  section.style.display = "";

  const ta = allData.team_anomalies || {};
  let anomalies = [...(ta.hot || []), ...(ta.cold || [])];

  if (filters.direction !== "all") {
    anomalies = anomalies.filter((a) => a.direction === filters.direction);
  }
  if (filters.stat !== "all") {
    anomalies = anomalies.filter((a) => a.stat === filters.stat);
  }
  if (filters.game !== "all") {
    anomalies = anomalies.filter(matchesGameFilter);
  }

  anomalies.sort((a, b) => Math.abs(b.pct_diff) - Math.abs(a.pct_diff));
  container.innerHTML = anomalies.map(renderTeamCard).join("");
}

function renderTeamCard(a) {
  const sbUrl = a.sportsbet_url || "";
  const lineHTML = a.betting_line
    ? renderBettingLine(a.betting_line, "total_points", sbUrl)
    : "";
  const devClass = a.pct_diff > 0 ? "positive" : "negative";
  const devLabel = a.pct_diff > 0 ? `+${a.pct_diff}%` : `${a.pct_diff}%`;
  const gameTag = a.game
    ? `<span class="game-tag">${a.game}</span>`
    : "";

  let vsLineHTML = "";
  if (a.betting_line && a.betting_line.line != null) {
    const pctVsLine = (
      ((a.last_3_avg - a.betting_line.line) / a.betting_line.line) *
      100
    ).toFixed(1);
    const vsLineClass = Number(pctVsLine) > 0 ? "positive" : "negative";
    const vsLineLabel =
      Number(pctVsLine) > 0 ? `+${pctVsLine}%` : `${pctVsLine}%`;
    vsLineHTML = `<span class="deviation ${vsLineClass}">${vsLineLabel} vs line</span>`;
  }

  return `
    <div class="anomaly-card ${a.direction}">
      <div class="card-header">
        <div class="player-info">
          <h3>${a.team_name}</h3>
          <span class="team">${a.team_abbr} \u00b7 ${a.games_played} GP</span>
        </div>
        <span class="direction-badge">${directionIcon(a.direction)}</span>
      </div>
      ${gameTag}
      ${statBadge(a.stat, a.stat_label)}
      <div class="last-3-games">
        ${a.last_3.map((v) => `<span class="game-value">${v}</span>`).join("")}
      </div>
      <div class="averages">
        <span>Season <strong>${a.season_avg}</strong></span>
        <span>L10 <strong>${a.l10_avg}</strong></span>
        <span>L3 <strong>${a.last_3_avg}</strong></span>
      </div>
      ${lineHTML}
      <div class="deviations">
        <span class="deviation ${devClass}">${devLabel} vs season</span>
        ${vsLineHTML}
      </div>
    </div>
  `;
}

function checkNoResults() {
  const playerCards = document.querySelectorAll(
    "#player-anomalies .anomaly-card"
  );
  const teamCards = document.querySelectorAll("#team-anomalies .anomaly-card");
  const featuredCards = document.querySelectorAll(
    "#featured-bets .featured-card"
  );
  const noResults = document.getElementById("no-results");
  const playerVisible =
    document.getElementById("player-section").style.display !== "none";
  const teamVisible =
    document.getElementById("team-section").style.display !== "none";
  const featuredVisible =
    document.getElementById("featured-section").style.display !== "none";

  const hasResults =
    (featuredVisible && featuredCards.length > 0) ||
    (playerVisible && playerCards.length > 0) ||
    (teamVisible && teamCards.length > 0);
  noResults.style.display = hasResults ? "none" : "";
}

// Filter event listeners
document.querySelectorAll("[data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll("[data-filter]")
      .forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    filters.direction = btn.dataset.filter;
    renderAll();
  });
});

document.querySelectorAll("[data-type]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll("[data-type]")
      .forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    filters.type = btn.dataset.type;
    renderAll();
  });
});

document.getElementById("stat-filter").addEventListener("change", (e) => {
  filters.stat = e.target.value;
  renderAll();
});

document.getElementById("game-filter").addEventListener("change", (e) => {
  filters.game = e.target.value;
  renderAll();
});

// Contact form — uses Web3Forms (free, no backend, key is public-safe)
// To set up: go to https://web3forms.com, click "Create your Form",
// enter ryhicks1@gmail.com, verify email, paste key below.
const WEB3FORMS_KEY = "YOUR_ACCESS_KEY_HERE"; // TODO: replace after signup

const contactForm = document.getElementById("contact-form");
if (contactForm) {
  contactForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (contactForm._honey && contactForm._honey.value) return;

    const btn = document.getElementById("contact-submit");
    const orig = btn.textContent;
    btn.textContent = "Sending\u2026";
    btn.disabled = true;

    const reset = (label) => {
      btn.textContent = label;
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
    };

    // Fallback: if Web3Forms key not set, use mailto
    if (WEB3FORMS_KEY === "YOUR_ACCESS_KEY_HERE") {
      const email = contactForm.email.value;
      const msg = contactForm.message.value;
      const subject = encodeURIComponent("BetStreak.ai Contact");
      const body = encodeURIComponent(`From: ${email}\n\n${msg}`);
      window.location.href =
        `mailto:contact@betstreak.ai?subject=${subject}&body=${body}`;
      reset("Sent!");
      contactForm.reset();
      return;
    }

    const fd = new FormData(contactForm);
    fd.append("access_key", WEB3FORMS_KEY);
    fd.append("subject", "BetStreak.ai Contact Form");
    fd.append("from_name", "BetStreak.ai");

    try {
      const resp = await fetch("https://api.web3forms.com/submit", {
        method: "POST",
        body: fd,
      });
      const result = await resp.json();
      if (result.success) { reset("Sent!"); contactForm.reset(); }
      else { reset("Error"); }
    } catch { reset("Error"); }
  });
}

loadData();
