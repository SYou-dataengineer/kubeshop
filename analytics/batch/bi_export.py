import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "kubeshop_analytics")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Exports BI et recommandations KubeShop"
    )
    parser.add_argument("--product-metrics", required=True)
    parser.add_argument("--daily-sales", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--skip-cassandra", action="store_true")
    return parser.parse_args()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as input_file:
        return list(csv.DictReader(input_file))


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def connect_cassandra(max_attempts=12, delay_seconds=5):
    from cassandra.cluster import Cluster

    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
            session = cluster.connect(CASSANDRA_KEYSPACE)
            return cluster, session
        except Exception as error:
            last_error = error
            print(
                f"Cassandra indisponible, tentative {attempt}/{max_attempts}: "
                f"{error}"
            )
            time.sleep(delay_seconds)

    raise RuntimeError("Connexion Cassandra impossible") from last_error


def read_realtime_metrics(skip_cassandra=False):
    if skip_cassandra:
        return {}, {}

    cluster, session = connect_cassandra()

    try:
        payment_rows = session.execute(
            """
            SELECT product, sales_count, total_revenue_cents
            FROM product_metrics
            """
        )
        click_rows = session.execute(
            """
            SELECT product, clicks_count
            FROM product_click_metrics
            """
        )

        payments = {
            row.product: {
                "sales": int(row.sales_count or 0),
                "revenue": Decimal(int(row.total_revenue_cents or 0))
                / Decimal("100"),
            }
            for row in payment_rows
        }
        clicks = {
            row.product: int(row.clicks_count or 0) for row in click_rows
        }
        return payments, clicks
    finally:
        cluster.shutdown()


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def build_product_rows(batch_rows, payments, clicks):
    products = {}

    for row in batch_rows:
        product = row["product"]
        products[product] = {
            "product_id": row["product_id"],
            "product": product,
            "category": row["category"],
            "batch_orders": int(row["orders_count"]),
            "batch_units": int(row["units_sold"]),
            "batch_revenue": Decimal(row["total_revenue"]),
            "realtime_sales": 0,
            "realtime_revenue": Decimal("0"),
            "clicks": 0,
        }

    realtime_products = set(payments) | set(clicks)

    for product in realtime_products:
        products.setdefault(
            product,
            {
                "product_id": "REALTIME",
                "product": product,
                "category": "Temps réel",
                "batch_orders": 0,
                "batch_units": 0,
                "batch_revenue": Decimal("0"),
                "realtime_sales": 0,
                "realtime_revenue": Decimal("0"),
                "clicks": 0,
            },
        )
        products[product]["realtime_sales"] = payments.get(
            product, {}
        ).get("sales", 0)
        products[product]["realtime_revenue"] = payments.get(
            product, {}
        ).get("revenue", Decimal("0"))
        products[product]["clicks"] = clicks.get(product, 0)

    rows = []

    for product in products.values():
        total_revenue = (
            product["batch_revenue"] + product["realtime_revenue"]
        )
        realtime_sales = product["realtime_sales"]
        product_clicks = product["clicks"]
        conversion_rate = (
            min(Decimal("100"), Decimal(realtime_sales * 100) / product_clicks)
            if product_clicks
            else Decimal("0")
        )

        rows.append(
            {
                **product,
                "total_revenue": total_revenue,
                "conversion_rate_pct": conversion_rate,
            }
        )

    max_revenue = max(
        (row["total_revenue"] for row in rows), default=Decimal("1")
    )
    max_units = max((row["batch_units"] for row in rows), default=1)
    max_clicks = max((row["clicks"] for row in rows), default=1)

    for row in rows:
        revenue_score = row["total_revenue"] / (max_revenue or Decimal("1"))
        units_score = Decimal(row["batch_units"]) / Decimal(max_units or 1)
        clicks_score = Decimal(row["clicks"]) / Decimal(max_clicks or 1)
        row["recommendation_score"] = (
            Decimal("0.50") * revenue_score
            + Decimal("0.30") * units_score
            + Decimal("0.20") * clicks_score
        )

    rows.sort(
        key=lambda row: (row["recommendation_score"], row["total_revenue"]),
        reverse=True,
    )

    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

        if rank == 1:
            action = "Mettre en avant - meilleur potentiel global"
        elif row["clicks"] > row["realtime_sales"] * 2:
            action = "Campagne de conversion - intérêt élevé"
        elif row["batch_units"] >= max(1, max_units // 2):
            action = "Maintenir le stock - demande solide"
        else:
            action = "Visibilité ciblée - potentiel à développer"

        row["recommended_action"] = action

    return rows


def serializable_product_row(row):
    return {
        "rank": row["rank"],
        "product_id": row["product_id"],
        "product": row["product"],
        "category": row["category"],
        "batch_orders": row["batch_orders"],
        "batch_units": row["batch_units"],
        "batch_revenue": rounded(row["batch_revenue"]),
        "realtime_sales": row["realtime_sales"],
        "realtime_revenue": rounded(row["realtime_revenue"]),
        "clicks": row["clicks"],
        "conversion_rate_pct": rounded(row["conversion_rate_pct"]),
        "total_revenue": rounded(row["total_revenue"]),
        "recommendation_score": rounded(row["recommendation_score"] * 100),
        "recommended_action": row["recommended_action"],
    }


def main():
    args = parse_args()
    batch_rows = read_csv(args.product_metrics)
    daily_rows = read_csv(args.daily_sales)

    if not batch_rows or not daily_rows:
        raise RuntimeError("Les fichiers Batch sont vides")

    payments, clicks = read_realtime_metrics(args.skip_cassandra)
    product_rows = build_product_rows(batch_rows, payments, clicks)
    exported_products = [
        serializable_product_row(row) for row in product_rows
    ]

    batch_orders = sum(int(row["orders_count"]) for row in daily_rows)
    batch_units = sum(int(row["units_sold"]) for row in daily_rows)
    batch_revenue = sum(
        (Decimal(row["total_revenue"]) for row in daily_rows), Decimal("0")
    )
    realtime_sales = sum(row["sales"] for row in payments.values())
    realtime_revenue = sum(
        (row["revenue"] for row in payments.values()), Decimal("0")
    )
    total_clicks = sum(clicks.values())
    conversion_rate = (
        min(Decimal("100"), Decimal(realtime_sales * 100) / total_clicks)
        if total_clicks
        else Decimal("0")
    )
    top_product = exported_products[0]["product"] if exported_products else "N/A"
    generated_at = datetime.now(timezone.utc).isoformat()

    kpis = {
        "run_date": args.run_date,
        "generated_at": generated_at,
        "batch_orders": batch_orders,
        "batch_units": batch_units,
        "batch_revenue": rounded(batch_revenue),
        "realtime_sales": realtime_sales,
        "realtime_revenue": rounded(realtime_revenue),
        "total_clicks": total_clicks,
        "conversion_rate_pct": rounded(conversion_rate),
        "combined_revenue": rounded(batch_revenue + realtime_revenue),
        "top_product": top_product,
    }

    os.makedirs(args.output, exist_ok=True)

    write_csv(
        os.path.join(args.output, "dashboard_kpis.csv"),
        list(kpis.keys()),
        [kpis],
    )

    product_fields = list(exported_products[0].keys())
    write_csv(
        os.path.join(args.output, "product_analytics.csv"),
        product_fields,
        exported_products,
    )

    recommendation_fields = [
        "rank",
        "product",
        "category",
        "recommendation_score",
        "total_revenue",
        "batch_units",
        "realtime_sales",
        "clicks",
        "conversion_rate_pct",
        "recommended_action",
    ]
    write_csv(
        os.path.join(args.output, "recommendations.csv"),
        recommendation_fields,
        [
            {field: row[field] for field in recommendation_fields}
            for row in exported_products
        ],
    )

    dashboard_payload = {
        "generatedAt": generated_at,
        "runDate": args.run_date,
        "kpis": kpis,
        "products": exported_products,
        "dailySales": [
            {
                "order_date": row["order_date"],
                "orders_count": int(row["orders_count"]),
                "units_sold": int(row["units_sold"]),
                "total_revenue": rounded(row["total_revenue"]),
            }
            for row in daily_rows
        ],
    }

    with open(
        os.path.join(args.output, "dashboard_summary.json"),
        "w",
        encoding="utf-8",
    ) as output_file:
        json.dump(dashboard_payload, output_file, ensure_ascii=False, indent=2)

    print(
        f"Exports BI terminés: {len(exported_products)} produit(s), "
        f"revenu combiné {kpis['combined_revenue']:.2f} CAD"
    )


if __name__ == "__main__":
    main()
