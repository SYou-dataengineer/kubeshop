const currencyFormatter = new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD"
});

const numberFormatter = new Intl.NumberFormat("fr-CA");

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function renderKpis(data) {
    const kpis = data.kpis;

    document.getElementById("combined-revenue").textContent =
        currencyFormatter.format(kpis.combined_revenue);
    document.getElementById("batch-orders").textContent =
        numberFormatter.format(kpis.batch_orders);
    document.getElementById("batch-units").textContent =
        `${numberFormatter.format(kpis.batch_units)} unités`;
    document.getElementById("total-clicks").textContent =
        numberFormatter.format(kpis.total_clicks);
    document.getElementById("conversion-rate").textContent =
        `${numberFormatter.format(kpis.conversion_rate_pct)} % de conversion`;
    document.getElementById("top-product").textContent = kpis.top_product;
    document.getElementById("run-date").textContent =
        `Traitement ${data.runDate}`;
    document.getElementById("updated-at").textContent =
        `Mis à jour : ${new Date(data.generatedAt).toLocaleString("fr-CA")}`;
}

function renderDailyChart(rows) {
    const chart = document.getElementById("daily-chart");
    const maximum = Math.max(...rows.map((row) => row.total_revenue), 1);

    chart.innerHTML = rows.map((row) => {
        const height = Math.max(4, (row.total_revenue / maximum) * 150);
        const date = new Date(`${row.order_date}T12:00:00`)
            .toLocaleDateString("fr-CA", { month: "short", day: "numeric" });

        return `
            <div class="bar-column" title="${escapeHtml(row.order_date)}">
                <span class="bar-value">${currencyFormatter.format(row.total_revenue)}</span>
                <div class="bar" style="height:${height}px"></div>
                <span class="bar-label">${escapeHtml(date)}</span>
            </div>
        `;
    }).join("");
}

function renderRecommendations(products) {
    document.getElementById("recommendations").innerHTML = products
        .slice(0, 3)
        .map((product) => `
            <div class="recommendation">
                <span class="rank">${product.rank}</span>
                <div>
                    <strong>${escapeHtml(product.product)}</strong>
                    <small>${escapeHtml(product.recommended_action)}</small>
                </div>
                <span class="score">${numberFormatter.format(product.recommendation_score)} / 100</span>
            </div>
        `)
        .join("");
}

function renderProductTable(products) {
    document.getElementById("product-table").innerHTML = products
        .map((product) => `
            <tr>
                <td>#${product.rank}</td>
                <td>${escapeHtml(product.product)}</td>
                <td>${numberFormatter.format(product.batch_units)}</td>
                <td>${numberFormatter.format(product.realtime_sales)}</td>
                <td>${numberFormatter.format(product.clicks)}</td>
                <td>${currencyFormatter.format(product.total_revenue)}</td>
                <td>${numberFormatter.format(product.recommendation_score)}</td>
            </tr>
        `)
        .join("");
}

async function loadDashboard() {
    const message = document.getElementById("message");
    const dashboard = document.getElementById("dashboard");

    try {
        const response = await fetch("data/dashboard_summary.json", {
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error("Lancez le DAG Airflow pour générer les exports BI.");
        }

        const data = await response.json();
        renderKpis(data);
        renderDailyChart(data.dailySales);
        renderRecommendations(data.products);
        renderProductTable(data.products);

        message.hidden = true;
        dashboard.hidden = false;
    } catch (error) {
        message.textContent = `Données indisponibles : ${error.message}`;
        message.classList.add("error");
    }
}

loadDashboard();
