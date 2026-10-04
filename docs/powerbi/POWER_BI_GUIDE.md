# Tableau de bord Power BI — KubeShop

## Fichiers à importer

Dans Power BI Desktop, choisir **Obtenir les données > Texte/CSV**, puis importer :

1. `data/output/dashboard_kpis.csv`
2. `data/output/daily_sales.csv`
3. `data/output/weekly_sales.csv`
4. `data/output/monthly_sales.csv`
5. `data/output/product_analytics.csv`
6. `data/output/recommendations.csv`

## Visuels recommandés

- Carte : `combined_revenue`
- Carte : `batch_orders`
- Carte : `batch_units`
- Carte : `total_clicks`
- Carte : `total_cart_additions`
- Courbe : `order_date` et `total_revenue` depuis `daily_sales.csv`
- Courbe : `week_start` et `total_revenue` depuis `weekly_sales.csv`
- Courbe : `month_start` et `total_revenue` depuis `monthly_sales.csv`
- Histogramme : `product` et `total_revenue` depuis `product_analytics.csv`
- Tableau : `rank`, `product`, `recommendation_score` et `recommended_action`

## Mesures DAX utiles

```DAX
Revenu total = SUM(product_analytics[total_revenue])

Unités vendues = SUM(product_analytics[batch_units])

Ventes temps réel = SUM(product_analytics[realtime_sales])

Taux de conversion =
DIVIDE(
    SUM(product_analytics[realtime_sales]),
    SUM(product_analytics[clicks]),
    0
)

Taux clic vers panier =
DIVIDE(
    SUM(product_analytics[cart_additions]),
    SUM(product_analytics[clicks]),
    0
)

Taux panier vers achat =
DIVIDE(
    SUM(product_analytics[realtime_sales]),
    SUM(product_analytics[cart_additions]),
    0
)
```

Formater `Revenu total` en devise CAD et les trois taux en pourcentage.
