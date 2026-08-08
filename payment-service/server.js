const express = require("express");
const cors = require("cors");
const crypto = require("crypto");

const app = express();
const PORT = process.env.PORT || 3002;

app.use(cors());
app.use(express.json());

app.get("/health", (req, res) => {
    res.status(200).json({
        status: "healthy",
        service: "kubeshop-payment-service"
    });
});

app.post("/payments", (req, res) => {
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

    res.status(201).json({
        success: true,
        transactionId,
        product,
        amount,
        currency: "CAD",
        status: "approved",
        processedAt: new Date().toISOString(),
        message: `Paiement approuvé pour ${product}.`
    });
});

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route introuvable."
    });
});

app.listen(PORT, "0.0.0.0", () => {
    console.log(`Payment service démarré sur le port ${PORT}`);
});