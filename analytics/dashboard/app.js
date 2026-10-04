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
    document.getElementById("total-cart-additions").textContent =
        numberFormatter.format(kpis.total_cart_additions || 0);
    document.getElementById("click-to-cart-rate").textContent =
        `${numberFormatter.format(kpis.click_to_cart_rate_pct || 0)} % clic → panier`;
    document.getElementById("conversion-rate").textContent =
        `${numberFormatter.format(kpis.conversion_rate_pct)} % de conversion`;
    document.getElementById("top-product").textContent = kpis.top_product;
    document.getElementById("run-date").textContent =
        `Traitement ${data.runDate}`;
    document.getElementById("updated-at").textContent =
        `Mis à jour : ${new Date(data.generatedAt).toLocaleString("fr-CA")}`;
}

function parseLocalDate(value) {
    return new Date(`${value}T12:00:00`);
}

const periodConfigs = {
    daily: {
        dataKey: "dailySales",
        dateKey: "order_date",
        title: "Revenus par jour",
        label: (row) => parseLocalDate(row.order_date)
            .toLocaleDateString("fr-CA", { month: "short", day: "numeric" })
    },
    weekly: {
        dataKey: "weeklySales",
        dateKey: "week_start",
        title: "Revenus par semaine",
        label: (row) => `Semaine du ${parseLocalDate(row.week_start)
            .toLocaleDateString("fr-CA", { month: "short", day: "numeric" })}`
    },
    monthly: {
        dataKey: "monthlySales",
        dateKey: "month_start",
        title: "Revenus par mois",
        label: (row) => parseLocalDate(row.month_start)
            .toLocaleDateString("fr-CA", { month: "short", year: "numeric" })
    }
};

function renderSalesChart(data, period = "daily") {
    const config = periodConfigs[period];
    const rows = Array.isArray(data[config.dataKey])
        ? data[config.dataKey]
        : [];
    const chart = document.getElementById("daily-chart");

    document.getElementById("sales-chart-title").textContent = config.title;
    document.querySelectorAll(".period-button").forEach((button) => {
        const isActive = button.dataset.period === period;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });

    if (!rows.length) {
        chart.innerHTML =
            '<p class="chart-empty">Aucune donnée pour cette période.</p>';
        return;
    }

    const maximum = Math.max(...rows.map((row) => row.total_revenue), 1);

    chart.innerHTML = rows.map((row) => {
        const height = Math.max(4, (row.total_revenue / maximum) * 150);
        const periodLabel = config.label(row);

        return `
            <div class="bar-column" title="${escapeHtml(row[config.dateKey])}">
                <span class="bar-value">${currencyFormatter.format(row.total_revenue)}</span>
                <div class="bar" style="height:${height}px"></div>
                <span class="bar-label">${escapeHtml(periodLabel)}</span>
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
                <td>${numberFormatter.format(product.cart_additions || 0)}</td>
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
        renderSalesChart(data);
        renderRecommendations(data.products);
        renderProductTable(data.products);

        document.querySelectorAll(".period-button").forEach((button) => {
            button.addEventListener("click", () => {
                renderSalesChart(data, button.dataset.period);
            });
        });

        message.hidden = true;
        dashboard.hidden = false;
    } catch (error) {
        message.textContent = `Données indisponibles : ${error.message}`;
        message.classList.add("error");
    }
}

loadDashboard();
