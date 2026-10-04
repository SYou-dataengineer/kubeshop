import argparse
import csv
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

from cassandra.cluster import Cluster
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "kubeshop_analytics")


ORDER_SCHEMA = T.StructType(
    [
        T.StructField("order_id", T.StringType(), False),
        T.StructField("order_date", T.DateType(), False),
        T.StructField("customer_id", T.StringType(), False),
        T.StructField("product_id", T.StringType(), False),
        T.StructField("quantity", T.IntegerType(), False),
        T.StructField("unit_price", T.DoubleType(), False),
        T.StructField("status", T.StringType(), False),
    ]
)


def parse_args():
    parser = argparse.ArgumentParser(description="Batch analytique KubeShop")
    parser.add_argument("--orders", required=True)
    parser.add_argument("--products", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-date", required=True)
    return parser.parse_args()


def connect_cassandra(max_attempts=20, delay_seconds=5):
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
            session = cluster.connect()
            return cluster, session
        except Exception as error:
            last_error = error
            print(
                f"Cassandra indisponible, tentative {attempt}/{max_attempts}: "
                f"{error}"
            )
            time.sleep(delay_seconds)

    raise RuntimeError("Connexion Cassandra impossible") from last_error


def initialize_cassandra(session):
    session.execute(
        f"""
        CREATE KEYSPACE IF NOT EXISTS {CASSANDRA_KEYSPACE}
        WITH replication = {{
            'class': 'SimpleStrategy',
            'replication_factor': 1
        }}
        """
    )
    session.set_keyspace(CASSANDRA_KEYSPACE)

    session.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_product_metrics (
            product text PRIMARY KEY,
            product_id text,
            category text,
            orders_count bigint,
            units_sold bigint,
            total_revenue decimal,
            run_date date,
            updated_at timestamp
        )
        """
    )

    session.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_daily_sales (
            sales_date date PRIMARY KEY,
            orders_count bigint,
            units_sold bigint,
            total_revenue decimal,
            run_date date,
            updated_at timestamp
        )
        """
    )


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()

    spark = (
        SparkSession.builder.appName("KubeShopBatchAnalytics")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    orders = (
        spark.read.option("header", True)
        .schema(ORDER_SCHEMA)
        .csv(args.orders)
    )

    products = spark.read.option("multiline", True).json(args.products)

    valid_orders = (
        orders.filter(F.col("order_id").isNotNull())
        .filter(F.col("order_date").isNotNull())
        .filter(F.col("quantity") > 0)
        .filter(F.col("unit_price") > 0)
        .filter(F.lower(F.col("status")) == "approved")
        .dropDuplicates(["order_id"])
        .withColumn(
            "line_revenue",
            F.round(F.col("quantity") * F.col("unit_price"), 2),
        )
    )

    enriched = valid_orders.join(products, "product_id", "inner")

    product_metrics_df = (
        enriched.groupBy("product_id", "product", "category")
        .agg(
            F.countDistinct("order_id").alias("orders_count"),
            F.sum("quantity").cast("long").alias("units_sold"),
            F.round(F.sum("line_revenue"), 2).alias("total_revenue"),
        )
        .orderBy(F.desc("total_revenue"))
    )

    daily_sales_df = (
        enriched.groupBy("order_date")
        .agg(
            F.countDistinct("order_id").alias("orders_count"),
            F.sum("quantity").cast("long").alias("units_sold"),
            F.round(F.sum("line_revenue"), 2).alias("total_revenue"),
        )
        .orderBy("order_date")
    )

    product_rows = [row.asDict() for row in product_metrics_df.collect()]
    daily_rows = [row.asDict() for row in daily_sales_df.collect()]

    if not product_rows or not daily_rows:
        raise RuntimeError("Aucune donnée valide produite par le traitement batch")

    cluster, session = connect_cassandra()
    run_date = datetime.strptime(args.run_date, "%Y-%m-%d").date()
    updated_at = datetime.now(timezone.utc)

    try:
        initialize_cassandra(session)

        insert_product = session.prepare(
            """
            INSERT INTO batch_product_metrics (
                product,
                product_id,
                category,
                orders_count,
                units_sold,
                total_revenue,
                run_date,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        )

        insert_daily = session.prepare(
            """
            INSERT INTO batch_daily_sales (
                sales_date,
                orders_count,
                units_sold,
                total_revenue,
                run_date,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """
        )

        for row in product_rows:
            session.execute(
                insert_product,
                (
                    row["product"],
                    row["product_id"],
                    row["category"],
                    int(row["orders_count"]),
                    int(row["units_sold"]),
                    Decimal(str(row["total_revenue"])),
                    run_date,
                    updated_at,
                ),
            )

        for row in daily_rows:
            session.execute(
                insert_daily,
                (
                    row["order_date"],
                    int(row["orders_count"]),
                    int(row["units_sold"]),
                    Decimal(str(row["total_revenue"])),
                    run_date,
                    updated_at,
                ),
            )
    finally:
        cluster.shutdown()
        spark.stop()

    write_csv(
        os.path.join(args.output, "product_metrics.csv"),
        [
            "product_id",
            "product",
            "category",
            "orders_count",
            "units_sold",
            "total_revenue",
        ],
        product_rows,
    )

    write_csv(
        os.path.join(args.output, "daily_sales.csv"),
        ["order_date", "orders_count", "units_sold", "total_revenue"],
        daily_rows,
    )

    print(
        f"Batch terminé: {len(product_rows)} produit(s), "
        f"{len(daily_rows)} jour(s), résultats écrits dans {args.output}"
    )


if __name__ == "__main__":
    main()
