# MEXC — moniteur de nouveaux listings (spot)

Surveille en continu la liste des paires **spot** de MEXC. Dès qu'une nouvelle
paire apparaît, on attend le premier prix réel, on capture la microstructure
du démarrage (ticks), puis on suit les bougies 1m pendant 2 h pour voir
**spike → repli → stabilisation**, et on calcule des points d'entrée théoriques.

## Principe

1. Boucle toutes les `CHECK_INTERVAL_SECONDS` → `GET /api/v3/exchangeInfo`.
2. **Premier lancement** : la liste complète devient la référence
   (`data/known_symbols.json`). Aucune alerte, aucun suivi.
3. **Lancements suivants** : toute paire absente de la référence → un **thread**
   de suivi démarre en parallèle (la boucle n'est jamais bloquée).
4. **Suivi en 3 phases** :
   | Phase | Quoi | Cadence | Fin |
   |---|---|---|---|
   | 1 — attente (T2→T3) | paire visible, pas encore de prix | `PRICE_WAIT_POLL_SECONDS` (3 s) | 1er prix réel, ou timeout 2 h |
   | 2 — tick | microstructure du démarrage | `TRACK_SAMPLE_INTERVAL_SECONDS` (2 s) | `TRACK_DURATION_SECONDS` (180 s) |
   | 3 — bougies | spike / repli / stabilisation + analyse d'entrée | `KLINE_POLL_SECONDS` (30 s) | `KLINE_FOLLOW_MINUTES` (120 min) |
5. La paire entre dans la référence → plus jamais re-détectée.

### Les 3 instants

| | Quoi | Le script |
|---|---|---|
| T1 | annonce du listing (article MEXC) | ignoré |
| T2 | la paire apparaît dans `exchangeInfo` | **détection** |
| T3 | premier prix réel (les échanges ouvrent) | départ des chronos |

⚠️ La mèche vers un prix plancher rond (0.002 / 0.005) visible sur les charts
MEXC **n'apparaît pas** dans les bougies 1m de l'API. Le vrai prix de référence
est le `close` de la 1re bougie 1m (`reference_price`). `floor_reliable=false`
dans `summary.json` = la 1re bougie récupérée n'est pas celle de l'ouverture
(historique 1m limité à ~500 bougies ≈ 8 h côté MEXC).

## Installation

```powershell
cd mexc-monitor
py -m pip install -r requirements.txt
copy .env.example .env
```

Données de marché spot MEXC = **publiques**, clé API non nécessaire.

## Utilisation

```powershell
py selftest.py            # test complet (~1 min) sur BTCUSDT
py monitor.py             # le daemon ; Ctrl+C pour arrêter proprement
py plot.py                # regénère courbes + summary + dashboard + agrégat
py plot.py --backfill     # + re-télécharge les bougies 1m manquantes (< ~8 h)
py aggregate.py           # recalcule seulement les stats agrégées
```

## Réglages (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | 60 | fréquence de scan de la liste (10–15 pour détecter plus vite) |
| `PRICE_WAIT_POLL_SECONDS` | 3 | cadence d'interrogation tant que la paire ne trade pas |
| `PRICE_WAIT_TIMEOUT_SECONDS` | 7200 | abandon si aucun prix après ce délai |
| `TRACK_DURATION_SECONDS` | 180 | durée de la capture tick (depuis T3) |
| `TRACK_SAMPLE_INTERVAL_SECONDS` | 2 | intervalle des ticks |
| `KLINE_FOLLOW_MINUTES` | 120 | durée du suivi des bougies 1m (depuis T3) |
| `KLINE_POLL_SECONDS` | 30 | rafraîchissement des bougies |
| `QUOTE_FILTER` | `USDT` | ne suivre que cette devise de cotation ; vide = toutes |

## Résultats (`data/`)

```
data/
  known_symbols.json        référence des paires connues
  detections.jsonl          journal (1 ligne JSON par détection)
  dashboard.html            tableau de tous les listings           <-- à ouvrir
  aggregate.html / .json    stats agrégées + comparaison des stratégies d'entrée
  listings/<SYM>_<date>/
    prices.csv              ticks : phase, t_since_detection, t_since_first_price, price, bid, ask, spread
    klines.csv / .json      bougies 1m depuis le listing
    summary.json            plancher, spike, pic, repli, snapshots, entry_*
    chart.png / chart.html  bougies 1m + marqueurs pic / plus-bas + tableau des entrées
    chart_ticks.png/.html   zoom sur les 3 premières minutes
```

### `summary.json` — champs clés

- `reference_price` : close de la 1re bougie 1m (le vrai prix de départ)
- `first_minute_spike_pct` : amplitude de la 1re bougie
- `peak_price` / `peak_at_min` / `peak_vs_ref_pct` : le plus haut et quand
- `drawdown_from_peak_pct` / `post_spike_low_at_min` : le repli et quand
- `settle_vs_ref_pct` : où on en est en fin de fenêtre vs prix de référence
- `entry_buy_at_minute` : acheter au close de la minute N → rendement fin + meilleur
- `entry_limit_after_pullback` : ordre limite à -X % du plus haut glissant → idem
- `analysis_span_min` : durée réelle couverte par l'analyse

## Notes

- Ne pas héberger sur une IP US (API MEXC géo-restreinte). `MEXC_BASE_URL`
  pour un domaine miroir.
- Les stats agrégées ne valent rien tant que n < 20–30. Ce sont des rendements
  *théoriques* (ordre limite supposé rempli au niveau visé, sans frais/slippage).
