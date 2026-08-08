const AUTH_API_URL = "";
const PAYMENT_API_URL = "";

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
    .addEventListener("submit", async function (event) {
        event.preventDefault();

        const product = productInput.value.trim();
        const amount = Number(amountInput.value);

        if (!product || !Number.isFinite(amount) || amount <= 0) {
            paymentResult.textContent =
                "Veuillez sélectionner un produit et saisir un montant valide.";
            paymentResult.className = "result error";
            return;
        }

        paymentResult.textContent = "Paiement en cours...";
        paymentResult.className = "result";

        try {
            const response = await fetch(`${PAYMENT_API_URL}/payments`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    product,
                    amount
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || "Échec du paiement.");
            }

            const formattedAmount = new Intl.NumberFormat("fr-CA", {
                style: "currency",
                currency: data.currency
            }).format(data.amount);

            paymentResult.textContent =
                `${data.message} Montant : ${formattedAmount} — Transaction : ${data.transactionId}`;

            paymentResult.className = "result success";
        } catch (error) {
            paymentResult.textContent =
                `Erreur de connexion au service Payment : ${error.message}`;

            paymentResult.className = "result error";
        }
    });