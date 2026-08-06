const express = require("express");
const cors = require("cors");

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

app.get("/health", (req, res) => {
    res.status(200).json({
        status: "healthy",
        service: "kubeshop-auth-service"
    });
});

app.post("/login", (req, res) => {
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

    res.status(200).json({
        success: true,
        username,
        message: `Bienvenue ${username} ! Connexion réussie.`
    });
});

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route introuvable."
    });
});

app.listen(PORT, "0.0.0.0", () => {
    console.log(`Auth service démarré sur le port ${PORT}`);
});