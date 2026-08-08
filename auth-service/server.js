const express = require("express");
const cors = require("cors");
const crypto = require("crypto");
const { createClient } = require("redis");

const app = express();
const PORT = process.env.PORT || 3001;
const REDIS_URL = process.env.REDIS_URL || "redis://redis:6379";

const configuredTtl = Number.parseInt(
    process.env.SESSION_TTL_SECONDS || "3600",
    10
);

const SESSION_TTL_SECONDS =
    Number.isInteger(configuredTtl) && configuredTtl > 0
        ? configuredTtl
        : 3600;

const redisClient = createClient({
    url: REDIS_URL
});

redisClient.on("error", (error) => {
    console.error("Erreur Redis :", error.message);
});

app.use(cors());
app.use(express.json());

app.get("/health", async (req, res) => {
    try {
        await redisClient.ping();

        res.status(200).json({
            status: "healthy",
            service: "kubeshop-auth-service",
            redis: "connected"
        });
    } catch (error) {
        res.status(503).json({
            status: "unhealthy",
            service: "kubeshop-auth-service",
            redis: "disconnected"
        });
    }
});

app.post("/login", async (req, res) => {
    const username =
        typeof req.body.username === "string"
            ? req.body.username.trim()
            : "";

    const password =
        typeof req.body.password === "string"
            ? req.body.password
            : "";

    if (!username || !password) {
        return res.status(400).json({
            success: false,
            message: "Le nom d’utilisateur et le mot de passe sont requis."
        });
    }

    try {
        const sessionToken = crypto.randomUUID();
        const createdAt = new Date().toISOString();

        await redisClient.set(
            `session:${sessionToken}`,
            JSON.stringify({
                username,
                createdAt
            }),
            {
                EX: SESSION_TTL_SECONDS
            }
        );

        res.status(200).json({
            success: true,
            username,
            sessionToken,
            expiresIn: SESSION_TTL_SECONDS,
            message: `Bienvenue ${username} ! Connexion réussie.`
        });
    } catch (error) {
        console.error("Création de session impossible :", error.message);

        res.status(503).json({
            success: false,
            message: "Le service de session est temporairement indisponible."
        });
    }
});

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route introuvable."
    });
});

async function startServer() {
    await redisClient.connect();

    app.listen(PORT, "0.0.0.0", () => {
        console.log(`Auth service démarré sur le port ${PORT}`);
        console.log("Connexion Redis établie.");
    });
}

startServer().catch((error) => {
    console.error("Démarrage du service Auth impossible :", error);
    process.exit(1);
});