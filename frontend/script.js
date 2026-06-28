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
            
            if(data.status === "error") {
                statusText.innerText = "Failed";
                statusText.style.color = "var(--danger)";
                alert("Error: " + data.message);
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
                <h2>${t.ticker}</h2>
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
            
            let llmHtml = "";
            if(t.has_llm_analysis && t.llm_analysis) {
                const a = t.llm_analysis;
                const themes = a.key_themes ? a.key_themes.map(th => `<span class="theme-pill">${th}</span>`).join("") : "";
                llmHtml = `
                    <div class="llm-section">
                        <div class="llm-header">🤖 Groq LLM Synthesis</div>
                        <div class="llm-grid">
                            <div class="llm-case bull">
                                <h4>Bull Case</h4>
                                <p>${a.bull_case || 'N/A'}</p>
                            </div>
                            <div class="llm-case bear">
                                <h4>Bear Case</h4>
                                <p>${a.bear_case || 'N/A'}</p>
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
                            <h2>${t.ticker}</h2>
                            <span class="price">$${t.current_price.toFixed(2)}</span>
                            <span class="change ${changeClass}">${changeSign}${t.daily_change_pct.toFixed(2)}%</span>
                        </div>
                        <div class="badge" style="background-color: ${color}33; color: ${color}; border: 1px solid ${color}">
                            ${t.risk_tier}
                        </div>
                    </div>
                    
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
