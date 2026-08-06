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
    .addEventListener("submit", function (event) {
        event.preventDefault();

        const username = document.getElementById("username").value.trim();
        const password = document.getElementById("password").value;

        if (!username || !password) {
            authResult.textContent = "Veuillez remplir tous les champs.";
            authResult.className = "result error";
            return;
        }

        authResult.textContent = `Bienvenue ${username} ! Connexion simulée avec succès.`;
        authResult.className = "result success";
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