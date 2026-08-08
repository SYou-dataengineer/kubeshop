const express = require("express");
const cors = require("cors");
const crypto = require("crypto");
const { Pool } = require("pg");

const app = express();
const PORT = process.env.PORT || 3002;

const pool = new Pool({
    host: process.env.PGHOST || "postgres",
    port: Number(process.env.PGPORT || 5432),
    database: process.env.PGDATABASE || "kubeshop",
    user: process.env.PGUSER || "kubeshop",
    password: process.env.PGPASSWORD || "kubeshop_dev_password",
    connectionTimeoutMillis: 5000
});

pool.on("error", (error) => {
    console.error("Erreur PostgreSQL :", error.message);
});

app.use(cors());
app.use(express.json());

app.get("/health", async (req, res) => {
    try {
        await pool.query("SELECT 1");

        res.status(200).json({
            status: "healthy",
            service: "kubeshop-payment-service",
            postgres: "connected"
        });
    } catch (error) {
        res.status(503).json({
            status: "unhealthy",
            service: "kubeshop-payment-service",
            postgres: "disconnected"
        });
    }
});

app.post("/payments", async (req, res) => {
    const product =
        typeof req.body.product === "string"
            ? req.body.product.trim()
            : "";

    const amount = Number(req.body.amount);

    if (!product || !Number.isFinite(amount) || amount <= 0) {
        return res.status(400).json({
            success: false,
            message: "Le produit et un montant valide sont requis."
        });
    }

    const transactionId = `PAY-${crypto.randomUUID()
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

        res.status(201).json({
            success: true,
            transactionId: payment.transaction_id,
            product: payment.product,
            amount: payment.amount,
            currency: payment.currency.trim(),
            status: payment.status,
            processedAt: payment.processed_at.toISOString(),
            message: `Paiement approuvé pour ${payment.product}.`
        });
    } catch (error) {
        console.error("Enregistrement du paiement impossible :", error.message);

        res.status(500).json({
            success: false,
            message: "Le paiement n’a pas pu être enregistré."
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
    await pool.query(`
        CREATE TABLE IF NOT EXISTS payments (
            id BIGSERIAL PRIMARY KEY,
            transaction_id VARCHAR(20) UNIQUE NOT NULL,
            product TEXT NOT NULL,
            amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
            currency CHAR(3) NOT NULL,
            status VARCHAR(20) NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    `);
}

async function startServer() {
    await initializeDatabase();

    app.listen(PORT, "0.0.0.0", () => {
        console.log(`Payment service démarré sur le port ${PORT}`);
        console.log("Connexion PostgreSQL établie.");
    });
}

startServer().catch((error) => {
    console.error("Démarrage du service Payment impossible :", error);
    process.exit(1);
});