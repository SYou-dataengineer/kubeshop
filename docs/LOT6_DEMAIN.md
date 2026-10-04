# Lot 6 — Panier temps réel et analyses semaine/mois

Ce guide permet de reprendre le projet sans improvisation. Le Lot 6 ajoute :

- l'événement `product_added_to_cart`;
- le topic Kafka `cart-events`;
- un troisième flux PySpark Structured Streaming;
- les tables Cassandra du panier;
- les agrégations Batch par semaine et par mois;
- le sélecteur Jour/Semaine/Mois dans le dashboard;
- une validation finale de 27 contrôles.

Le nombre de services reste à 11. Aucun volume existant ne doit être supprimé.

## 1. Préparer une branche sécurisée

Dans PowerShell :

```powershell
Set-Location "D:\Session 4\Haitham Rehouma\kubeshop-git"

git status
git switch feature/bigdata-pipeline
git pull --ff-only
git switch -c feature/lot6-cart-periods
```

Le résultat attendu avant d'appliquer le Lot 6 est `working tree clean`.

Si la branche existe déjà :

```powershell
git switch feature/lot6-cart-periods
```

## 2. Appliquer le correctif préparé

Copier `Lot6_Panier_Semaine_Mois.patch` à la racine du projet, puis :

```powershell
git apply --check .\Lot6_Panier_Semaine_Mois.patch
git apply .\Lot6_Panier_Semaine_Mois.patch
git status --short
```

Ne pas continuer si `git apply --check` affiche une erreur. Dans ce cas,
conserver le message complet pour le diagnostic.

Après application réussie, retirer seulement le fichier de transfert :

```powershell
Remove-Item .\Lot6_Panier_Semaine_Mois.patch
```

## 3. Démarrer Docker Desktop

Ouvrir Docker Desktop manuellement ou exécuter :

```powershell
Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
```

Attendre que le moteur réponde :

```powershell
while ($true) {
    docker info *> $null

    if ($LASTEXITCODE -eq 0) {
        break
    }

    Write-Host "Docker démarre, veuillez patienter..."
    Start-Sleep -Seconds 5
}
```

Préparer la variable Compose, dans la même fenêtre PowerShell :

```powershell
$ComposeFiles = @(
    "-f", ".\docker-compose.yml",
    "-f", ".\docker-compose.bigdata.yml"
)
```

## 4. Construire et lancer la plateforme

```powershell
docker compose @ComposeFiles config --quiet
docker compose @ComposeFiles up -d --build
docker compose @ComposeFiles ps
```

Cassandra et Airflow peuvent prendre plusieurs minutes. Attendre que les
services disposant d'un healthcheck deviennent `healthy`.

Pour reconstruire uniquement les composants modifiés :

```powershell
docker compose @ComposeFiles up -d --build `
    event-service frontend stream-processor airflow analytics-dashboard
```

En cas de problème :

```powershell
docker compose @ComposeFiles logs --tail 100 event-service
docker compose @ComposeFiles logs --tail 100 stream-processor
docker compose @ComposeFiles logs --tail 100 airflow
```

## 5. Tester l'ajout au panier

### Test visuel

1. Ouvrir `http://localhost:8080`.
2. Cliquer sur `Ajouter au panier`.
3. Vérifier le message confirmant l'ajout.

### Test API reproductible

```powershell
$DemoProduct = "Panier Lot6 $(Get-Date -Format 'yyyyMMdd-HHmmss')"

$CartBody = @{
    product = $DemoProduct
    price = 129.99
    quantity = 2
    sessionId = [guid]::NewGuid().ToString()
} | ConvertTo-Json

$CartResponse = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8080/events/cart" `
    -ContentType "application/json" `
    -Body $CartBody

$CartResponse | ConvertTo-Json -Depth 6
```

La réponse attendue contient :

- `eventPublished: true`;
- `kafkaTopic: cart-events`;
- `eventType: product_added_to_cart`.

Attendre le micro-lot PySpark :

```powershell
Start-Sleep -Seconds 15
```

Au tout premier démarrage, Spark peut avoir besoin de 60 à 90 secondes pour
télécharger ses composants et initialiser les flux. Si Cassandra ne contient
pas encore l'événement, consulter les journaux, attendre, puis relancer la
requête sans republier un nouvel événement :

```powershell
docker compose @ComposeFiles logs --tail 80 stream-processor
```

Vérifier le topic Kafka :

```powershell
docker compose @ComposeFiles exec -T kafka `
    /opt/kafka/bin/kafka-topics.sh `
    --bootstrap-server kafka:19092 `
    --describe `
    --topic cart-events
```

Afficher et retrouver l'événement publié :

```powershell
$KafkaMessages = docker compose @ComposeFiles exec -T kafka `
    /opt/kafka/bin/kafka-console-consumer.sh `
    --bootstrap-server kafka:19092 `
    --topic cart-events `
    --from-beginning `
    --timeout-ms 10000 2>&1

$KafkaMessages | Select-String -SimpleMatch $CartResponse.event.eventId
```

Vérifier l'événement exact dans Cassandra :

```powershell
$EventId = $CartResponse.event.eventId

docker compose @ComposeFiles exec -T cassandra cqlsh -e `
    "SELECT event_id, product, quantity, price FROM kubeshop_analytics.cart_events WHERE event_id = $EventId;"
```

Vérifier les compteurs :

```powershell
$CqlProduct = $DemoProduct.Replace("'", "''")

docker compose @ComposeFiles exec -T cassandra cqlsh -e `
    "SELECT product, cart_additions_count, cart_items_count, total_cart_value_cents FROM kubeshop_analytics.product_cart_metrics WHERE product = '$CqlProduct';"
```

Pour une quantité de 2 à 129,99 $, le résultat attendu est :

- `cart_additions_count = 1`;
- `cart_items_count = 2`;
- `total_cart_value_cents = 25998`.

## 6. Tester semaine et mois

Déclencher le pipeline Batch :

```powershell
docker compose @ComposeFiles exec -T airflow `
    airflow dags trigger kubeshop_batch_analytics
```

Vérifier l'état jusqu'à obtenir `success` :

```powershell
docker compose @ComposeFiles exec -T airflow `
    airflow dags list-runs -d kubeshop_batch_analytics
```

Afficher les nouveaux fichiers :

```powershell
Import-Csv .\data\output\weekly_sales.csv | Format-Table
Import-Csv .\data\output\monthly_sales.csv | Format-Table
```

Résultats attendus :

| Période | Commandes | Unités | Revenu CAD |
|---|---:|---:|---:|
| 2026-09-21 au 2026-09-27 | 7 | 11 | 5 179,89 |
| 2026-09-28 au 2026-10-04 | 7 | 13 | 5 439,87 |
| Septembre 2026 | 11 | 20 | 8 459,80 |
| Octobre 2026 | 3 | 4 | 2 159,96 |
| Total | 14 | 24 | 10 619,76 |

Vérifier Cassandra :

```powershell
docker compose @ComposeFiles exec -T cassandra cqlsh -e `
    "SELECT * FROM kubeshop_analytics.batch_weekly_sales;"

docker compose @ComposeFiles exec -T cassandra cqlsh -e `
    "SELECT * FROM kubeshop_analytics.batch_monthly_sales;"
```

Ouvrir `http://localhost:8082` et essayer les boutons `Jour`, `Semaine` et
`Mois`. Le dashboard est un instantané mis à jour par Airflow; la preuve du
quasi temps réel reste Kafka puis Cassandra.

## 7. Validation finale

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\validate-project.ps1
```

Résultat visé :

```text
Réussis : 27 | Échecs : 0
Validation globale réussie.
```

Contrôles Git :

```powershell
git diff --check
git status --short --untracked-files=all
```

## 8. Captures pour le PPT

Conserver neuf captures propres :

1. les 11 services actifs;
2. le bouton `Ajouter au panier`;
3. la réponse JSON `eventPublished: true`;
4. l'événement `product_added_to_cart` dans Kafka;
5. les compteurs panier dans Cassandra;
6. les ventes hebdomadaires;
7. les ventes mensuelles;
8. le DAG Airflow en `success` et le dashboard Jour/Semaine/Mois;
9. la validation `27 PASS / 0 FAIL`.

Ne pas afficher le mot de passe Airflow dans les captures.

## 9. Commit et publication

Seulement après les 27 validations :

```powershell
git add .
git diff --cached --check
git status
git commit -m "feat: add cart events and period analytics"
git push -u origin feature/lot6-cart-periods
```

## 10. Arrêt propre

Conserver les conteneurs et les données :

```powershell
docker compose @ComposeFiles stop
docker compose @ComposeFiles ps -a
```

Retirer les conteneurs tout en conservant les volumes :

```powershell
docker compose @ComposeFiles down
```

Ne pas utiliser `down -v`, car cette option supprimerait PostgreSQL, Redis,
Cassandra, les métadonnées Airflow et les checkpoints Spark.

## 11. Démarrage le jour de la présentation

Ouvrir Docker Desktop, puis :

```powershell
Set-Location "D:\Session 4\Haitham Rehouma\kubeshop-git"

$ComposeFiles = @(
    "-f", ".\docker-compose.yml",
    "-f", ".\docker-compose.bigdata.yml"
)

docker compose @ComposeFiles up -d
docker compose @ComposeFiles ps
pwsh -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\validate-project.ps1
```

Ouvrir ensuite :

- boutique : `http://localhost:8080`;
- Airflow : `http://localhost:8081`;
- dashboard : `http://localhost:8082`.

## 12. Retour arrière

Si une anomalie apparaît avant le commit :

```powershell
docker compose @ComposeFiles down
git stash push -u -m "lot6-a-verifier"
git switch feature/bigdata-pipeline
docker compose @ComposeFiles up -d
```

Le travail peut être récupéré plus tard :

```powershell
git switch feature/lot6-cart-periods
git stash pop
```
