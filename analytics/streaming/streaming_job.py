import os
import time
import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from cassandra.cluster import Cluster
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka:19092"
)
KAFKA_TOPIC_PAYMENTS = os.getenv("KAFKA_TOPIC_PAYMENTS", "payments")
KAFKA_TOPIC_CLICKS = os.getenv("KAFKA_TOPIC_CLICKS", "clicks")
KAFKA_TOPIC_CART = os.getenv("KAFKA_TOPIC_CART", "cart-events")
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "kubeshop_analytics")
PAYMENTS_CHECKPOINT_LOCATION = os.getenv(
    "PAYMENTS_CHECKPOINT_LOCATION",
    os.getenv("CHECKPOINT_LOCATION", "/checkpoints/payments"),
)
CLICKS_CHECKPOINT_LOCATION = os.getenv(
    "CLICKS_CHECKPOINT_LOCATION", "/checkpoints/clicks"
)
CART_CHECKPOINT_LOCATION = os.getenv(
    "CART_CHECKPOINT_LOCATION", "/checkpoints/cart"
)

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


PAYMENT_SCHEMA = T.StructType(
    [
        T.StructField("eventId", T.StringType(), False),
        T.StructField("eventType", T.StringType(), False),
        T.StructField("eventVersion", T.IntegerType(), True),
        T.StructField("source", T.StringType(), True),
        T.StructField("transactionId", T.StringType(), False),
        T.StructField("product", T.StringType(), False),
        T.StructField("amount", T.DoubleType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("status", T.StringType(), False),
        T.StructField("processedAt", T.StringType(), False),
    ]
)

CLICK_SCHEMA = T.StructType(
    [
        T.StructField("eventId", T.StringType(), False),
        T.StructField("eventType", T.StringType(), False),
        T.StructField("eventVersion", T.IntegerType(), True),
        T.StructField("source", T.StringType(), True),
        T.StructField("product", T.StringType(), False),
        T.StructField("price", T.DoubleType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("sessionId", T.StringType(), True),
        T.StructField("occurredAt", T.StringType(), False),
    ]
)

CART_SCHEMA = T.StructType(
    [
        T.StructField("eventId", T.StringType(), False),
        T.StructField("eventType", T.StringType(), False),
        T.StructField("eventVersion", T.IntegerType(), True),
        T.StructField("source", T.StringType(), True),
        T.StructField("product", T.StringType(), False),
        T.StructField("price", T.DoubleType(), False),
        T.StructField("quantity", T.IntegerType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("sessionId", T.StringType(), True),
        T.StructField("occurredAt", T.StringType(), False),
    ]
)


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


def initialize_cassandra():
    cluster, session = connect_cassandra()

    try:
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
            CREATE TABLE IF NOT EXISTS payment_events (
                event_id uuid PRIMARY KEY,
                transaction_id text,
                product text,
                amount decimal,
                currency text,
                status text,
                processed_at timestamp,
                kafka_timestamp timestamp
            )
            """
        )

        session.execute(
            """
            CREATE TABLE IF NOT EXISTS product_metrics (
                product text PRIMARY KEY,
                sales_count counter,
                total_revenue_cents counter
            )
            """
        )

        session.execute(
            """
            CREATE TABLE IF NOT EXISTS click_events (
                event_id uuid PRIMARY KEY,
                product text,
                price decimal,
                currency text,
                session_id text,
                occurred_at timestamp,
                kafka_timestamp timestamp
            )
            """
        )

        session.execute(
            """
            CREATE TABLE IF NOT EXISTS product_click_metrics (
                product text PRIMARY KEY,
                clicks_count counter
            )
            """
        )

        session.execute(
            """
            CREATE TABLE IF NOT EXISTS cart_events (
                event_id uuid PRIMARY KEY,
                product text,
                price decimal,
                quantity int,
                currency text,
                session_id text,
                occurred_at timestamp,
                kafka_timestamp timestamp
            )
            """
        )

        session.execute(
            """
            CREATE TABLE IF NOT EXISTS product_cart_metrics (
                product text PRIMARY KEY,
                cart_additions_count counter,
                cart_items_count counter,
                total_cart_value_cents counter
            )
            """
        )

        print(
            f"Cassandra initialisé: tables paiements, clics et paniers dans "
            f"{CASSANDRA_KEYSPACE}"
        )
    finally:
        cluster.shutdown()


def process_payment_batch(batch_df, batch_id):
    clean_batch = (
        batch_df.filter(F.col("event_id").isNotNull())
        .filter(F.col("transaction_id").isNotNull())
        .filter(F.col("product").isNotNull())
        .filter(F.col("amount") > 0)
        .dropDuplicates(["event_id"])
    )

    rows = clean_batch.collect()

    if not rows:
        print(f"Paiements PySpark {batch_id}: aucun événement valide")
        return

    cluster, session = connect_cassandra()

    try:
        session.set_keyspace(CASSANDRA_KEYSPACE)

        insert_event = session.prepare(
            """
            INSERT INTO payment_events (
                event_id,
                transaction_id,
                product,
                amount,
                currency,
                status,
                processed_at,
                kafka_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            IF NOT EXISTS
            """
        )

        update_metrics = session.prepare(
            """
            UPDATE product_metrics
            SET sales_count = sales_count + ?,
                total_revenue_cents = total_revenue_cents + ?
            WHERE product = ?
            """
        )

        metrics = defaultdict(lambda: {"count": 0, "revenue_cents": 0})
        inserted_count = 0

        for row in rows:
            result = session.execute(
                insert_event,
                (
                    uuid.UUID(row.event_id),
                    row.transaction_id,
                    row.product,
                    Decimal(str(row.amount)),
                    row.currency,
                    row.status,
                    row.processed_at,
                    row.kafka_timestamp,
                ),
            ).one()

            if result.applied:
                inserted_count += 1
                metrics[row.product]["count"] += 1
                metrics[row.product]["revenue_cents"] += int(
                    round(row.amount * 100)
                )

        for product, values in metrics.items():
            session.execute(
                update_metrics,
                (
                    values["count"],
                    values["revenue_cents"],
                    product,
                ),
            )

        print(
            f"Paiements PySpark {batch_id}: {inserted_count} événement(s), "
            f"{len(metrics)} KPI produit(s) mis à jour"
        )
    finally:
        cluster.shutdown()


def process_click_batch(batch_df, batch_id):
    clean_batch = (
        batch_df.filter(F.col("event_id").isNotNull())
        .filter(F.col("product").isNotNull())
        .filter(F.col("price") > 0)
        .dropDuplicates(["event_id"])
    )

    rows = clean_batch.collect()

    if not rows:
        print(f"Clics PySpark {batch_id}: aucun événement valide")
        return

    cluster, session = connect_cassandra()

    try:
        session.set_keyspace(CASSANDRA_KEYSPACE)

        insert_event = session.prepare(
            """
            INSERT INTO click_events (
                event_id,
                product,
                price,
                currency,
                session_id,
                occurred_at,
                kafka_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            IF NOT EXISTS
            """
        )

        update_metrics = session.prepare(
            """
            UPDATE product_click_metrics
            SET clicks_count = clicks_count + ?
            WHERE product = ?
            """
        )

        clicks_by_product = defaultdict(int)
        inserted_count = 0

        for row in rows:
            result = session.execute(
                insert_event,
                (
                    uuid.UUID(row.event_id),
                    row.product,
                    Decimal(str(row.price)),
                    row.currency,
                    row.session_id,
                    row.occurred_at,
                    row.kafka_timestamp,
                ),
            ).one()

            if result.applied:
                inserted_count += 1
                clicks_by_product[row.product] += 1

        for product, count in clicks_by_product.items():
            session.execute(update_metrics, (count, product))

        print(
            f"Clics PySpark {batch_id}: {inserted_count} événement(s), "
            f"{len(clicks_by_product)} KPI produit(s) mis à jour"
        )
    finally:
        cluster.shutdown()


def process_cart_batch(batch_df, batch_id):
    clean_batch = (
        batch_df.filter(F.col("event_id").rlike(UUID_PATTERN))
        .filter(F.length(F.trim(F.col("product"))) > 0)
        .filter(F.col("price").isNotNull())
        .filter(~F.isnan("price"))
        .filter((F.col("price") > 0) & (F.col("price") < float("inf")))
        .filter(F.col("quantity").between(1, 100))
        .filter(F.col("currency").isNotNull())
        .filter(F.col("occurred_at").isNotNull())
        .dropDuplicates(["event_id"])
    )

    rows = clean_batch.collect()

    if not rows:
        print(f"Paniers PySpark {batch_id}: aucun événement valide")
        return

    cluster, session = connect_cassandra()

    try:
        session.set_keyspace(CASSANDRA_KEYSPACE)

        insert_event = session.prepare(
            """
            INSERT INTO cart_events (
                event_id,
                product,
                price,
                quantity,
                currency,
                session_id,
                occurred_at,
                kafka_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            IF NOT EXISTS
            """
        )

        update_metrics = session.prepare(
            """
            UPDATE product_cart_metrics
            SET cart_additions_count = cart_additions_count + ?,
                cart_items_count = cart_items_count + ?,
                total_cart_value_cents = total_cart_value_cents + ?
            WHERE product = ?
            """
        )

        metrics = defaultdict(
            lambda: {"additions": 0, "items": 0, "value_cents": 0}
        )
        inserted_count = 0

        for row in rows:
            price = Decimal(str(row.price))
            result = session.execute(
                insert_event,
                (
                    uuid.UUID(row.event_id),
                    row.product,
                    price,
                    row.quantity,
                    row.currency,
                    row.session_id,
                    row.occurred_at,
                    row.kafka_timestamp,
                ),
            ).one()

            if result.applied:
                value_cents = int(
                    (
                        price * Decimal(row.quantity) * Decimal("100")
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                inserted_count += 1
                metrics[row.product]["additions"] += 1
                metrics[row.product]["items"] += row.quantity
                metrics[row.product]["value_cents"] += value_cents

        for product, values in metrics.items():
            session.execute(
                update_metrics,
                (
                    values["additions"],
                    values["items"],
                    values["value_cents"],
                    product,
                ),
            )

        print(
            f"Paniers PySpark {batch_id}: {inserted_count} événement(s), "
            f"{len(metrics)} KPI produit(s) mis à jour"
        )
    finally:
        cluster.shutdown()


def read_kafka_topic(spark, topic):
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
    )


def main():
    initialize_cassandra()

    spark = (
        SparkSession.builder.appName("KubeShopRealtimeAnalytics")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )

    spark.sparkContext.setLogLevel("WARN")

    payments = (
        read_kafka_topic(spark, KAFKA_TOPIC_PAYMENTS)
        .select(
            F.from_json(F.col("value").cast("string"), PAYMENT_SCHEMA).alias(
                "event"
            ),
            F.col("timestamp").alias("kafka_timestamp"),
        )
        .select("event.*", "kafka_timestamp")
        .filter(F.col("eventType") == "payment_completed")
        .select(
            F.col("eventId").alias("event_id"),
            F.col("transactionId").alias("transaction_id"),
            F.col("product"),
            F.col("amount"),
            F.col("currency"),
            F.col("status"),
            F.to_timestamp("processedAt").alias("processed_at"),
            F.col("kafka_timestamp"),
        )
    )

    clicks = (
        read_kafka_topic(spark, KAFKA_TOPIC_CLICKS)
        .select(
            F.from_json(F.col("value").cast("string"), CLICK_SCHEMA).alias(
                "event"
            ),
            F.col("timestamp").alias("kafka_timestamp"),
        )
        .select("event.*", "kafka_timestamp")
        .filter(F.col("eventType") == "product_clicked")
        .select(
            F.col("eventId").alias("event_id"),
            F.col("product"),
            F.col("price"),
            F.col("currency"),
            F.col("sessionId").alias("session_id"),
            F.to_timestamp("occurredAt").alias("occurred_at"),
            F.col("kafka_timestamp"),
        )
    )

    carts = (
        read_kafka_topic(spark, KAFKA_TOPIC_CART)
        .select(
            F.from_json(F.col("value").cast("string"), CART_SCHEMA).alias(
                "event"
            ),
            F.col("timestamp").alias("kafka_timestamp"),
        )
        .select("event.*", "kafka_timestamp")
        .filter(F.col("eventType") == "product_added_to_cart")
        .select(
            F.col("eventId").alias("event_id"),
            F.col("product"),
            F.col("price"),
            F.col("quantity"),
            F.col("currency"),
            F.col("sessionId").alias("session_id"),
            F.to_timestamp("occurredAt").alias("occurred_at"),
            F.col("kafka_timestamp"),
        )
    )

    payments.writeStream.foreachBatch(process_payment_batch).option(
        "checkpointLocation", PAYMENTS_CHECKPOINT_LOCATION
    ).trigger(processingTime="10 seconds").start()

    clicks.writeStream.foreachBatch(process_click_batch).option(
        "checkpointLocation", CLICKS_CHECKPOINT_LOCATION
    ).trigger(processingTime="10 seconds").start()

    carts.writeStream.foreachBatch(process_cart_batch).option(
        "checkpointLocation", CART_CHECKPOINT_LOCATION
    ).trigger(processingTime="10 seconds").start()

    print(
        f"PySpark écoute {KAFKA_TOPIC_PAYMENTS}, {KAFKA_TOPIC_CLICKS} "
        f"et {KAFKA_TOPIC_CART} "
        f"sur {KAFKA_BOOTSTRAP_SERVERS}"
    )

    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
