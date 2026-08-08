const AUTH_API_URL = "http://localhost:3001";

const productInput = document.getElementById("product");
const amountInput = document.getElementById("amount");
const authResult = document.getElementById("auth-result");
const paymentResult = document.getElementById("payment-result");

function selectProduct(productName, price) {
    productInput.value = productName;
    amountInput.value = price.toFixed(2);

    paymentResult.textContent = `${productName} a été sélectionné.`;
    paymentResult.className = "result success";

    document
        .getElementById("payment-form")
        .scrollIntoView({ behavior: "smooth" });
}

document
    .getElementById("login-form")
    .addEventListener("submit", async function (event) {
        event.preventDefault();

        const username = document.getElementById("username").value.trim();
        const password = document.getElementById("password").value;

        if (!username || !password) {
            authResult.textContent = "Veuillez remplir tous les champs.";
            authResult.className = "result error";
            return;
        }

        authResult.textContent = "Connexion en cours...";
        authResult.className = "result";

        try {
            const response = await fetch(`${AUTH_API_URL}/login`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    username,
                    password
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || "Échec de la connexion.");
            }

            authResult.textContent = data.message;
            authResult.className = "result success";
        } catch (error) {
            authResult.textContent =
                `Erreur de connexion au service : ${error.message}`;
            authResult.className = "result error";
        }
    });

document
    .getElementById("payment-form")
    .addEventListener("submit", function (event) {
        event.preventDefault();

        const product = productInput.value;
        const amount = Number(amountInput.value);

        if (!product || !amount) {
            paymentResult.textContent =
                "Veuillez d’abord sélectionner un produit.";
            paymentResult.className = "result error";
            return;
        }

        const formattedAmount = new Intl.NumberFormat("fr-CA", {
            style: "currency",
            currency: "CAD"
        }).format(amount);

        paymentResult.textContent =
            `Paiement simulé avec succès : ${product} — ${formattedAmount}`;

        paymentResult.className = "result success";
    });