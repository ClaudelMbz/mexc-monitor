# MEXC — moniteur de nouveaux listings (spot)

Surveille en continu la liste des paires **spot** de MEXC. Dès qu'une nouvelle
paire apparaît, le script suit son prix pendant 5 minutes (échantillon toutes
les ~7 s) et produit une **courbe** (PNG + HTML interactif) + un CSV brut.

## Principe

1. Boucle toutes les 60 s → `GET /api/v3/exchangeInfo` (liste de toutes les paires).
2. **Premier lancement** : la liste complète est enregistrée comme référence
   (`data/known_symbols.json`). Aucune alerte, aucun suivi.
3. **Lancements suivants** : comparaison avec la référence.
   - Rien de neuf → on ne fait rien.
   - Nouvelle(s) paire(s) → pour chacune, un **thread** de suivi démarre en
     parallèle (la boucle d'1 min n'est jamais bloquée, même si plusieurs
     coins sont listés en même temps).
4. Suivi = prix (mid bid/ask) relevé toutes les `TRACK_SAMPLE_INTERVAL_SECONDS`
   pendant `TRACK_DURATION_SECONDS`, puis génération des graphiques.
5. La nouvelle paire entre dans la référence → plus jamais re-détectée.

La référence est sur disque : un redémarrage ne re-détecte pas tout l'univers.

## Installation

```powershell
cd mexc-monitor
py -m pip install -r requirements.txt
copy .env.example .env      # puis édite .env si besoin
```

Les données de marché spot MEXC sont **publiques** : la clé API n'est pas
nécessaire pour ce script. Renseigne quand même `MEXC_API_KEY` / `MEXC_API_SECRET`
dans `.env` si tu veux (utile seulement pour de futurs endpoints privés).

## Utilisation

```powershell
py selftest.py     # test rapide : suit BTCUSDT 20 s et génère les graphiques
py monitor.py      # le daemon ; Ctrl+C pour arrêter proprement
```

## Réglages (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | 60 | fréquence de vérification de la liste |
| `TRACK_DURATION_SECONDS` | 300 | durée de suivi d'un nouveau listing |
| `TRACK_SAMPLE_INTERVAL_SECONDS` | 7 | intervalle d'échantillonnage du prix (5–10 conseillé) |
| `QUOTE_FILTER` | `USDT` | ne suivre que les paires de cette devise ; vide = toutes |

## Résultats (`data/`)

```
data/
  known_symbols.json          référence des paires connues
  detections.jsonl            journal (1 ligne JSON par détection)
  dashboard.html              tableau récap de tous les listings  <-- à ouvrir
  listings/
    NEWUSDT_20260902_153012/
      prices.csv               timestamp, elapsed, price, bid, ask, spread
      summary.json             open/last/min/max, %variation, run-up, drawdown
      chart.png                courbe (matplotlib)
      chart.html               courbe interactive (Chart.js)
```

## Notes

- L'API MEXC peut être géo-restreinte selon le pays ; utilise un domaine miroir
  via `MEXC_BASE_URL` si nécessaire.
- Une paire peut apparaître dans `exchangeInfo` quelques minutes avant le début
  réel des échanges : les premiers échantillons peuvent être vides, c'est géré
  (lignes `price` vides dans le CSV, ignorées dans les stats).
