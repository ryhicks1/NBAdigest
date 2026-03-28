const DATA_URL = "data/anomalies.json";

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
    document.getElementById("updated-at").textContent =
      "Failed to load data. Run the pipeline first: python src/main.py";
    console.error("Failed to load anomalies.json:", err);
  }
}

function renderMeta() {
  if (!allData) return;
  const dt = new Date(allData.generated_at);
  document.getElementById("updated-at").textContent =
    `Last updated: ${dt.toLocaleDateString("en-AU", { weekday: "long", year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Australia/Sydney" })}`;

  const m = allData.meta;
  document.getElementById("meta-info").textContent =
    `${m.players_with_sportsbet_markets} players with Sportsbet markets | ${m.events_count} events | ${m.total_teams_analyzed} teams`;
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
  // Match player anomalies by their tagged game
  if (anomaly.game) return anomaly.game === filters.game;
  // Match team anomalies by team name appearing in the game filter
  if (anomaly.team_name) {
    return filters.game.includes(anomaly.team_name.split(" ").pop());
  }
  if (anomaly.team) {
    // Check if team abbreviation appears in any part of the game
    return filters.game.includes(anomaly.team);
  }
  return false;
}

function renderAll() {
  renderPlayerAnomalies();
  renderTeamAnomalies();
  checkNoResults();
}

function renderPlayerAnomalies() {
  const container = document.getElementById("player-anomalies");
  const section = document.getElementById("player-section");

  if (filters.type === "teams") {
    section.style.display = "none";
    return;
  }
  section.style.display = "";

  let anomalies = [
    ...(allData.player_anomalies.hot || []),
    ...(allData.player_anomalies.cold || []),
  ];

  if (filters.direction !== "all") {
    anomalies = anomalies.filter((a) => a.direction === filters.direction);
  }
  if (filters.stat !== "all") {
    anomalies = anomalies.filter((a) => a.stat === filters.stat);
  }
  if (filters.game !== "all") {
    anomalies = anomalies.filter(matchesGameFilter);
  }

  // Sort by deviation magnitude
  anomalies.sort(
    (a, b) =>
      Math.max(Math.abs(b.pct_diff_season), Math.abs(b.pct_diff_l10)) -
      Math.max(Math.abs(a.pct_diff_season), Math.abs(a.pct_diff_l10))
  );

  container.innerHTML = anomalies.map(renderPlayerCard).join("");
}

function renderPlayerCard(a) {
  const sbUrl = a.sportsbet_url || "";
  const lineHTML = a.betting_line ? renderBettingLine(a.betting_line, a.stat, sbUrl) : "";
  const devMax = Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10) ? a.pct_diff_season : a.pct_diff_l10;
  const devClass = devMax > 0 ? "positive" : "negative";
  const devLabel = devMax > 0 ? `+${devMax}%` : `${devMax}%`;
  const compLabel = Math.abs(a.pct_diff_season) > Math.abs(a.pct_diff_l10) ? "vs season" : "vs L10";
  const gameTag = a.game ? `<span class="game-tag">${a.game}</span>` : "";

  // % vs line calculation
  let vsLineHTML = "";
  if (a.betting_line && a.betting_line.line != null) {
    const line = a.betting_line.line;
    const pctVsLine = ((a.last_3_avg - line) / line * 100).toFixed(1);
    const vsLineClass = Number(pctVsLine) > 0 ? "positive" : "negative";
    const vsLineLabel = Number(pctVsLine) > 0 ? `+${pctVsLine}%` : `${pctVsLine}%`;
    vsLineHTML = `<span class="deviation ${vsLineClass}">${vsLineLabel} vs line</span>`;
  }

  return `
    <div class="anomaly-card ${a.direction}" data-stat="${a.stat}" data-direction="${a.direction}">
      <div class="card-header">
        <div class="player-info">
          <h3>${a.player_name}</h3>
          <span class="team">${a.team} | ${a.games_played} GP</span>
        </div>
        <span class="direction-badge ${a.direction}">${a.direction === "hot" ? "HOT" : "COLD"}</span>
      </div>
      ${gameTag}
      <span class="stat-badge">${a.stat_label}</span>
      <div class="last-3-games">
        ${a.last_3.map((v) => `<span class="game-value">${v}</span>`).join("")}
      </div>
      <div class="averages">
        <span>Season: <strong>${a.season_avg}</strong></span>
        <span>L10: <strong>${a.l10_avg}</strong></span>
        <span>L3: <strong>${a.last_3_avg}</strong></span>
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
  const linkOpen = sbUrl ? `<a href="${sbUrl}" target="_blank" rel="noopener" class="betting-line-link">` : "";
  const linkClose = sbUrl ? "</a>" : "";

  if (line.market_type === "over_under" || line.line != null) {
    const over = line.over_price != null ? line.over_price : "—";
    const under = line.under_price != null ? line.under_price : "—";
    return `${linkOpen}<div class="betting-line">Sportsbet: ${line.line} (O ${over} / U ${under})</div>${linkClose}`;
  }
  if (line.market_type === "threshold" && line.thresholds) {
    const entries = Object.entries(line.thresholds)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([t, d]) => `${t}+ @ ${d.price}`)
      .join(", ");
    return `${linkOpen}<div class="betting-line">Sportsbet: ${entries}</div>${linkClose}`;
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

  let anomalies = [
    ...(allData.team_anomalies.hot || []),
    ...(allData.team_anomalies.cold || []),
  ];

  if (filters.direction !== "all") {
    anomalies = anomalies.filter((a) => a.direction === filters.direction);
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
  const gameTag = a.game ? `<span class="game-tag">${a.game}</span>` : "";

  let vsLineHTML = "";
  if (a.betting_line && a.betting_line.line != null) {
    const pctVsLine = ((a.last_3_avg - a.betting_line.line) / a.betting_line.line * 100).toFixed(1);
    const vsLineClass = Number(pctVsLine) > 0 ? "positive" : "negative";
    const vsLineLabel = Number(pctVsLine) > 0 ? `+${pctVsLine}%` : `${pctVsLine}%`;
    vsLineHTML = `<span class="deviation ${vsLineClass}">${vsLineLabel} vs line</span>`;
  }

  return `
    <div class="anomaly-card ${a.direction}">
      <div class="card-header">
        <div class="player-info">
          <h3>${a.team_name}</h3>
          <span class="team">${a.team_abbr} | ${a.games_played} GP</span>
        </div>
        <span class="direction-badge ${a.direction}">${a.direction === "hot" ? "HOT" : "COLD"}</span>
      </div>
      ${gameTag}
      <span class="stat-badge">${a.stat_label}</span>
      <div class="last-3-games">
        ${a.last_3.map((v) => `<span class="game-value">${v}</span>`).join("")}
      </div>
      <div class="averages">
        <span>Season: <strong>${a.season_avg}</strong></span>
        <span>L10: <strong>${a.l10_avg}</strong></span>
        <span>L3: <strong>${a.last_3_avg}</strong></span>
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
  const playerCards = document.querySelectorAll("#player-anomalies .anomaly-card");
  const teamCards = document.querySelectorAll("#team-anomalies .anomaly-card");
  const noResults = document.getElementById("no-results");
  const playerVisible = document.getElementById("player-section").style.display !== "none";
  const teamVisible = document.getElementById("team-section").style.display !== "none";

  const hasResults = (playerVisible && playerCards.length > 0) || (teamVisible && teamCards.length > 0);
  noResults.style.display = hasResults ? "none" : "";
}

// Filter event listeners
document.querySelectorAll("[data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-filter]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    filters.direction = btn.dataset.filter;
    renderAll();
  });
});

document.querySelectorAll("[data-type]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-type]").forEach((b) => b.classList.remove("active"));
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

// Load on page ready
loadData();
