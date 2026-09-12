document.addEventListener("DOMContentLoaded", () => {
    const runBtn = document.getElementById("run-btn");
    const statusText = document.getElementById("pipeline-status");
    const timeText = document.getElementById("run-time");
    
    const trendingGrid = document.getElementById("trending-grid");
    const trendingSection = document.getElementById("trending-section");
    
    const tickerList = document.getElementById("ticker-list");
    const tickerSubtitle = document.getElementById("ticker-subtitle");
    
    const riskSlider = document.getElementById("risk-slider");
    const riskLabel = document.getElementById("risk-label");
    
    let globalData = null;

    // Ticker cards render LLM-generated bull/bear case text, which is
    // ultimately derived from scraped Reddit/StockTwits post bodies — an
    // attacker-influenced string could ride that path into the DOM via
    // innerHTML. Escape every value we interpolate.
    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    const TIER_ORDER = ["Conservative", "Moderate", "Aggressive", "Speculative"];
    const TIER_LABELS = {
        1: "🛡️ Conservative",
        2: "⚖️ Moderate",
        3: "⚡ Aggressive",
        4: "🎲 All (incl. Speculative)"
    };
    
    riskSlider.addEventListener("input", (e) => {
        const val = parseInt(e.target.value);
        riskLabel.innerText = `Showing: ${TIER_LABELS[val]}`;
        if(globalData) renderTickers(globalData.classified, val);
    });

    runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        runBtn.innerText = "⏳ Running Pipeline...";
        statusText.innerText = "Processing...";
        statusText.style.color = "var(--warning)";
        
        try {
            const response = await fetch("http://127.0.0.1:8000/api/run_pipeline");
            const data = await response.json();

            if(!response.ok) {
                statusText.innerText = "Failed";
                statusText.style.color = "var(--danger)";
                alert("Error: " + (data.detail || `Request failed (${response.status})`));
                return;
            }

            globalData = data;
            
            statusText.innerText = "Complete";
            statusText.style.color = "var(--success)";
            timeText.innerText = data.run_time;
            
            renderTrending(data.trending);
            renderTickers(data.classified, parseInt(riskSlider.value));
            
        } catch (err) {
            statusText.innerText = "Failed";
            statusText.style.color = "var(--danger)";
            alert("Network Error: " + err.message);
        } finally {
            runBtn.disabled = false;
            runBtn.innerText = "🚀 Run Pipeline";
        }
    });
    
    function renderTrending(trending) {
        if(!trending || trending.length === 0) {
            trendingSection.classList.add("hidden");
            return;
        }
        trendingSection.classList.remove("hidden");
        
        trendingGrid.innerHTML = trending.map(t => `
            <div class="trending-card">
                <h2>${escapeHtml(t.ticker)}</h2>
                <p style="color: #cbd5e1;">Top Momentum</p>
                <div class="metric">StockTwits Bull: ${(t.st_bull_ratio * 100).toFixed(0)}%</div>
                <div class="metric">Price: $${t.current_price.toFixed(2)}</div>
            </div>
        `).join("");
    }
    
    function renderTickers(classified, maxRiskLevel) {
        let visibleTickers = [];
        const allowedTiers = TIER_ORDER.slice(0, maxRiskLevel);
        
        allowedTiers.forEach(tier => {
            if(classified[tier]) {
                visibleTickers = visibleTickers.concat(classified[tier]);
            }
        });
        
        visibleTickers.sort((a, b) => b.composite_score - a.composite_score);
        
        tickerSubtitle.innerText = `Displaying ${visibleTickers.length} stocks across selected risk tiers.`;
        
        tickerList.innerHTML = visibleTickers.map(t => {
            const changeClass = t.daily_change_pct >= 0 ? "pos" : "neg";
            const changeSign = t.daily_change_pct >= 0 ? "+" : "";
            const color = getTierColor(t.risk_tier);
            
            const sparkline = buildSparkline(t.price_chart, t.daily_change_pct >= 0);

            let llmHtml = "";
            if(t.has_llm_analysis && t.llm_analysis) {
                const a = t.llm_analysis;
                const themes = a.key_themes ? a.key_themes.map(th => `<span class="theme-pill">${escapeHtml(th)}</span>`).join("") : "";
                llmHtml = `
                    <div class="llm-section">
                        <div class="llm-header">🤖 Groq LLM Synthesis</div>
                        <div class="llm-grid">
                            <div class="llm-case bull">
                                <h4>Bull Case</h4>
                                <p>${escapeHtml(a.bull_case || 'N/A')}</p>
                            </div>
                            <div class="llm-case bear">
                                <h4>Bear Case</h4>
                                <p>${escapeHtml(a.bear_case || 'N/A')}</p>
                            </div>
                        </div>
                        <div class="llm-themes">
                            <strong>Themes:</strong> ${themes}
                        </div>
                    </div>
                `;
            }

            return `
                <div class="ticker-card" style="border-left-color: ${color}">
                    <div class="card-header">
                        <div class="ticker-title">
                            <h2>${escapeHtml(t.ticker)}</h2>
                            <span class="price">$${t.current_price.toFixed(2)}</span>
                            <span class="change ${changeClass}">${changeSign}${t.daily_change_pct.toFixed(2)}%</span>
                        </div>
                        <div class="badge" style="background-color: ${color}33; color: ${color}; border: 1px solid ${color}">
                            ${escapeHtml(t.risk_tier)}
                        </div>
                    </div>

                    ${sparkline ? `
                    <div class="chart-row">
                        <span class="chart-label">30D</span>
                        ${sparkline}
                    </div>
                    ` : ""}

                    <div class="grid-metrics">
                        <div class="metric-box">
                            <div class="metric-label">Composite Score</div>
                            <div class="metric-val" style="color: var(--primary)">${t.composite_score.toFixed(1)}/100</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Fundamentals</div>
                            <div class="metric-val">${t.fundamental_score.toFixed(0)}/100</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">StockTwits Bull</div>
                            <div class="metric-val">${(t.st_bull_ratio * 100).toFixed(0)}%</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">RSI</div>
                            <div class="metric-val">${t.rsi.toFixed(1)}</div>
                        </div>
                    </div>
                    
                    ${llmHtml}
                </div>
            `;
        }).join("");
    }
    
    // fundamentals.py computes a 30-day close-price series per ticker
    // (price_chart) specifically for the UI to chart, but until now nothing
    // rendered it. Build a minimal dependency-free SVG sparkline instead of
    // pulling in a charting library for a single line per card.
    // Every interpolated value here is a number we computed (toFixed
    // output), not raw ticker data, so no escaping is needed.
    function buildSparkline(priceChart, isPositive) {
        if (!priceChart || priceChart.length < 2) return "";

        const prices = priceChart.map(p => p.price);
        const min = Math.min(...prices);
        const max = Math.max(...prices);
        const range = max - min || 1;   // avoid /0 on a flat line

        const width = 120;
        const height = 36;
        const step = width / (prices.length - 1);

        const points = prices.map((price, i) => {
            const x = (i * step).toFixed(1);
            const y = (height - ((price - min) / range) * height).toFixed(1);
            return `${x},${y}`;
        }).join(" ");

        const color = isPositive ? "var(--success)" : "var(--danger)";

        return `
            <svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="30-day price trend">
                <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
            </svg>
        `;
    }

    function getTierColor(tier) {
        switch(tier) {
            case "Conservative": return "#3B82F6"; // Blue
            case "Moderate": return "#10B981"; // Green
            case "Aggressive": return "#F59E0B"; // Yellow
            case "Speculative": return "#EF4444"; // Red
            default: return "#94A3B8";
        }
    }
});
