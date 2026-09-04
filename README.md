# MEXC — moniteur de nouveaux listings (spot)

Surveille en continu la liste des paires **spot** de MEXC. Dès qu'une nouvelle
paire apparaît, le script attend le premier prix réel puis suit son évolution
pendant 3 minutes, et produit une **courbe** (PNG + HTML interactif) + un CSV brut.

## Principe

1. Boucle toutes les `CHECK_INTERVAL_SECONDS` → `GET /api/v3/exchangeInfo`
   (liste de toutes les paires).
2. **Premier lancement** : la liste complète est enregistrée comme référence
   (`data/known_symbols.json`). Aucune alerte, aucun suivi.
3. **Lancements suivants** : comparaison avec la référence.
   - Rien de neuf → on ne fait rien.
   - Nouvelle(s) paire(s) → pour chacune, un **thread** de suivi démarre en
     parallèle (la boucle principale n'est jamais bloquée, même si plusieurs
     coins sont listés en même temps).
4. **Suivi en 2 phases** :
   - **Phase 1 (T2 → T3)** : la paire est visible mais ne trade pas encore.
     On interroge le prix toutes les `PRICE_WAIT_POLL_SECONDS` (3 s) jusqu'au
     premier prix réel, ou abandon après `PRICE_WAIT_TIMEOUT_SECONDS` (2 h).
   - **Phase 2 (mesure)** : à partir du premier prix, on échantillonne toutes
     les `TRACK_SAMPLE_INTERVAL_SECONDS` (2 s) pendant `TRACK_DURATION_SECONDS`
     (180 s). Puis génération des graphiques.
5. La nouvelle paire entre dans la référence → plus jamais re-détectée.

La référence est sur disque : un redémarrage ne re-détecte pas tout l'univers.

### Les 3 instants

| | Quoi | Le script |
|---|---|---|
| T1 | annonce du listing (article MEXC) | ignoré |
| T2 | la paire apparaît dans `exchangeInfo` | **détection** |
| T3 | premier prix réel (les échanges ouvrent) | départ du chrono de 3 min |

## Installation

```powershell
cd mexc-monitor
py -m pip install -r requirements.txt
copy .env.example .env      # puis édite .env si besoin
```

Les données de marché spot MEXC sont **publiques** : la clé API n'est pas
nécessaire. Renseigne quand même `MEXC_API_KEY` / `MEXC_API_SECRET` dans `.env`
si tu veux (utile seulement pour de futurs endpoints privés).

## Utilisation

```powershell
py selftest.py     # test rapide : suit BTCUSDT ~20 s et génère les graphiques
py monitor.py      # le daemon ; Ctrl+C pour arrêter proprement
py plot.py         # regénère les courbes depuis les CSV déjà collectés
```

## Réglages (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | 60 | fréquence de vérification de la liste (baisser à 10–15 pour détecter plus vite) |
| `PRICE_WAIT_POLL_SECONDS` | 3 | cadence d'interrogation du prix tant que la paire ne trade pas |
| `PRICE_WAIT_TIMEOUT_SECONDS` | 7200 | abandon si aucun prix après ce délai |
| `TRACK_DURATION_SECONDS` | 180 | durée de mesure, **à partir du premier prix réel** |
| `TRACK_SAMPLE_INTERVAL_SECONDS` | 2 | intervalle d'échantillonnage pendant la mesure |
| `QUOTE_FILTER` | `USDT` | ne suivre que les paires de cette devise ; vide = toutes |

## Résultats (`data/`)

```
data/
  known_symbols.json          référence des paires connues
  detections.jsonl            journal (1 ligne JSON par détection)
  dashboard.html              tableau récap de tous les listings  <-- à ouvrir
  listings/
    NEWUSDT_20260902_153012/
      prices.csv               timestamp, phase, t_since_detection, t_since_first_price, price, bid, ask, spread
      summary.json             wait_seconds, open/last/min/max, %variation, run-up, drawdown, statut
      chart.png                courbe (matplotlib)
      chart.html               courbe interactive (Chart.js)
```

Le CSV contient les deux phases : lignes `phase=wait` (avant le premier prix)
puis `phase=track` (fenêtre de mesure). L'axe des courbes = minutes depuis T3.

## Notes

- L'API MEXC peut être géo-restreinte selon le pays ; utilise un domaine miroir
  via `MEXC_BASE_URL` si nécessaire. Ne pas héberger sur une IP US.
- `status` dans `summary.json` : `ok`, `timeout_no_price`, `stopped_before_price`,
  `stopped_during_track`, `rerendered`.
