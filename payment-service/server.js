const express = require("express");
const cors = require("cors");
const crypto = require("crypto");
const { Pool } = require("pg");
const {
    Kafka,
    Partitioners,
    logLevel
} = require("kafkajs");

const app = express();
const PORT = process.env.PORT || 3002;

const KAFKA_TOPIC_PAYMENTS =
    process.env.KAFKA_TOPIC_PAYMENTS || "payments";

const KAFKA_BROKERS = (
    process.env.KAFKA_BROKERS || "kafka:19092"
)
    .split(",")
    .map((broker) => broker.trim())
    .filter(Boolean);

const pool = new Pool({
    host: process.env.PGHOST || "postgres",
    port: Number(process.env.PGPORT || 5432),
    database: process.env.PGDATABASE || "kubeshop",
    user: process.env.PGUSER || "kubeshop",
    password:
        process.env.PGPASSWORD ||
        "kubeshop_dev_password",
    connectionTimeoutMillis: 5000
});

const kafka = new Kafka({
    clientId:
        process.env.KAFKA_CLIENT_ID ||
        "kubeshop-payment-service",
    brokers: KAFKA_BROKERS,
    logLevel: logLevel.INFO,
    retry: {
        initialRetryTime: 300,
        retries: 8
    }
});

const producer = kafka.producer({
    createPartitioner: Partitioners.DefaultPartitioner,
    allowAutoTopicCreation: false
});

let kafkaConnected = false;
let server;

pool.on("error", (error) => {
    console.error(
        "Erreur PostgreSQL :",
        error.message
    );
});

app.use(cors());
app.use(express.json());

app.get("/health", async (req, res) => {
    try {
        await pool.query("SELECT 1");

        res.status(200).json({
            status: "healthy",
            service: "kubeshop-payment-service",
            postgres: "connected",
            kafka: kafkaConnected
                ? "connected"
                : "disconnected",
            kafkaTopic: KAFKA_TOPIC_PAYMENTS
        });
    } catch (error) {
        res.status(503).json({
            status: "unhealthy",
            service: "kubeshop-payment-service",
            postgres: "disconnected",
            kafka: kafkaConnected
                ? "connected"
                : "disconnected"
        });
    }
});

app.post("/payments", async (req, res) => {
    const product =
        typeof req.body.product === "string"
            ? req.body.product.trim()
            : "";

    const amount = Number(req.body.amount);

    if (
        !product ||
        !Number.isFinite(amount) ||
        amount <= 0
    ) {
        return res.status(400).json({
            success: false,
            message:
                "Le produit et un montant valide sont requis."
        });
    }

    const transactionId = `PAY-${crypto
        .randomUUID()
        .slice(0, 8)
        .toUpperCase()}`;

    try {
        const result = await pool.query(
            `
                INSERT INTO payments (
                    transaction_id,
                    product,
                    amount,
                    currency,
                    status
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING
                    transaction_id,
                    product,
                    amount::float8 AS amount,
                    currency,
                    status,
                    processed_at
            `,
            [
                transactionId,
                product,
                amount,
                "CAD",
                "approved"
            ]
        );

        const payment = result.rows[0];

        const processedAt =
            payment.processed_at.toISOString();

        const paymentEvent = {
            eventId: crypto.randomUUID(),
            eventType: "payment_completed",
            eventVersion: 1,
            source: "kubeshop-payment-service",
            transactionId:
                payment.transaction_id,
            product: payment.product,
            amount: payment.amount,
            currency: payment.currency.trim(),
            status: payment.status,
            processedAt
        };

        let eventPublished = false;

        try {
            await producer.send({
                topic: KAFKA_TOPIC_PAYMENTS,
                acks: -1,
                messages: [
                    {
                        key: payment.transaction_id,
                        value: JSON.stringify(
                            paymentEvent
                        ),
                        headers: {
                            eventType:
                                "payment_completed",
                            source:
                                "payment-service"
                        }
                    }
                ]
            });

            eventPublished = true;

            console.log(
                `Événement Kafka publié : ${payment.transaction_id}`
            );
        } catch (kafkaError) {
            console.error(
                "Publication Kafka impossible :",
                kafkaError.message
            );
        }

        res.status(201).json({
            success: true,
            transactionId:
                payment.transaction_id,
            product: payment.product,
            amount: payment.amount,
            currency: payment.currency.trim(),
            status: payment.status,
            processedAt,
            eventPublished,
            kafkaTopic: KAFKA_TOPIC_PAYMENTS,
            message:
                `Paiement approuvé pour ${payment.product}.`
        });
    } catch (error) {
        console.error(
            "Enregistrement du paiement impossible :",
            error.message
        );

        res.status(500).json({
            success: false,
            message:
                "Le paiement n’a pas pu être enregistré."
        });
    }
});

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route introuvable."
    });
});

async function initializeDatabase() {
    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        await client.query(
            "SELECT pg_advisory_xact_lock($1, $2)",
            [20260808, 3002]
        );

        await client.query(`
            CREATE TABLE IF NOT EXISTS payments (
                id BIGSERIAL PRIMARY KEY,
                transaction_id VARCHAR(20)
                    UNIQUE NOT NULL,
                product TEXT NOT NULL,
                amount NUMERIC(12, 2)
                    NOT NULL CHECK (amount > 0),
                currency CHAR(3) NOT NULL,
                status VARCHAR(20) NOT NULL,
                processed_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW()
            )
        `);

        await client.query("COMMIT");
    } catch (error) {
        await client.query("ROLLBACK");
        throw error;
    } finally {
        client.release();
    }
}

async function initializeKafka() {
    const admin = kafka.admin();

    await admin.connect();

    try {
        const created = await admin.createTopics({
            waitForLeaders: true,
            topics: [
                {
                    topic: KAFKA_TOPIC_PAYMENTS,
                    numPartitions: 3,
                    replicationFactor: 1
                }
            ]
        });

        console.log(
            created
                ? `Sujet Kafka créé : ${KAFKA_TOPIC_PAYMENTS}`
                : `Sujet Kafka existant : ${KAFKA_TOPIC_PAYMENTS}`
        );
    } finally {
        await admin.disconnect();
    }

    await producer.connect();
    kafkaConnected = true;

    console.log(
        `Connexion Kafka établie : ${KAFKA_BROKERS.join(", ")}`
    );
}

async function startServer() {
    await initializeDatabase();
    await initializeKafka();

    server = app.listen(
        PORT,
        "0.0.0.0",
        () => {
            console.log(
                `Payment service démarré sur le port ${PORT}`
            );
            console.log(
                "Connexion PostgreSQL établie."
            );
        }
    );
}

async function shutdown(signal) {
    console.log(
        `${signal} reçu, arrêt du service...`
    );

    kafkaConnected = false;

    if (server) {
        server.close();
    }

    await Promise.allSettled([
        producer.disconnect(),
        pool.end()
    ]);

    process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

startServer().catch((error) => {
    console.error(
        "Démarrage du service Payment impossible :",
        error
    );

    process.exit(1);
});