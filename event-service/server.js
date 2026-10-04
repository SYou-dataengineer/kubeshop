const express = require("express");
const crypto = require("crypto");
const { Kafka, logLevel } = require("kafkajs");

const app = express();
const PORT = Number(process.env.PORT || 3003);
const KAFKA_TOPIC_CLICKS = process.env.KAFKA_TOPIC_CLICKS || "clicks";

const kafka = new Kafka({
    clientId: process.env.KAFKA_CLIENT_ID || "kubeshop-event-service",
    brokers: (process.env.KAFKA_BROKERS || "kafka:19092").split(","),
    logLevel: logLevel.WARN
});

const producer = kafka.producer();
let kafkaConnected = false;

app.use(express.json({ limit: "32kb" }));

app.get("/health", (req, res) => {
    res.status(kafkaConnected ? 200 : 503).json({
        status: kafkaConnected ? "healthy" : "unhealthy",
        service: "kubeshop-event-service",
        kafka: kafkaConnected ? "connected" : "disconnected",
        kafkaTopic: KAFKA_TOPIC_CLICKS
    });
});

app.post("/events/clicks", async (req, res) => {
    const product =
        typeof req.body.product === "string" ? req.body.product.trim() : "";
    const price = Number(req.body.price);
    const sessionId =
        typeof req.body.sessionId === "string" && req.body.sessionId.trim()
            ? req.body.sessionId.trim().slice(0, 100)
            : "anonymous";

    if (!product || !Number.isFinite(price) || price <= 0) {
        return res.status(400).json({
            success: false,
            message: "Le produit et un prix valide sont requis."
        });
    }

    const event = {
        eventId: crypto.randomUUID(),
        eventType: "product_clicked",
        eventVersion: 1,
        source: "kubeshop-frontend",
        product,
        price,
        currency: "CAD",
        sessionId,
        occurredAt: new Date().toISOString()
    };

    try {
        await producer.send({
            topic: KAFKA_TOPIC_CLICKS,
            messages: [
                {
                    key: product,
                    value: JSON.stringify(event)
                }
            ]
        });

        return res.status(202).json({
            success: true,
            eventPublished: true,
            kafkaTopic: KAFKA_TOPIC_CLICKS,
            event
        });
    } catch (error) {
        console.error("Publication du clic impossible :", error.message);

        return res.status(503).json({
            success: false,
            eventPublished: false,
            message: "L’événement de clic n’a pas pu être publié."
        });
    }
});

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route introuvable."
    });
});

async function initializeKafka() {
    const admin = kafka.admin();

    await admin.connect();

    try {
        await admin.createTopics({
            waitForLeaders: true,
            topics: [
                {
                    topic: KAFKA_TOPIC_CLICKS,
                    numPartitions: 3,
                    replicationFactor: 1
                }
            ]
        });
    } finally {
        await admin.disconnect();
    }

    await producer.connect();
    kafkaConnected = true;
}

async function startServer() {
    await initializeKafka();

    app.listen(PORT, "0.0.0.0", () => {
        console.log(`Event service démarré sur le port ${PORT}`);
        console.log(`Kafka connecté, topic ${KAFKA_TOPIC_CLICKS} prêt.`);
    });
}

async function shutdown(signal) {
    console.log(`${signal} reçu, arrêt du service Event...`);
    kafkaConnected = false;
    await producer.disconnect();
    process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

startServer().catch((error) => {
    console.error("Démarrage du service Event impossible :", error);
    process.exit(1);
});
