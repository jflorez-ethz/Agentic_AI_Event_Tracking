# KPI hors ligne (tâche B7) — vidéos jamais vues

Version mesurée : arbre src `7e86f3b` (commit `bd6046f`). Règles figées : [rules.json](rules.json). Correspondance stricte, tolérance ±2 s. Runs complets : 7/7. Les anciens runs archivés ne sont pas lus. Vérité terrain : [heldout_truth.json](heldout_truth.json), figée avant les runs (XML CAVIAR, plus 2 labels manuels à confiance faible pour LeftBag_BehindChair). Le système n’a jamais vu ces vidéos ; les nombres restent petits.

## Alertes et événements critiques

| Vidéo | Run | Analysé | Événements attendus | Retrouvés | Ratés (cause) | Alertes brutes (approx.) | Alertes à un humain | dont vraies | Fausses / h |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| Browse1.mpg | Browse1 | 42.0/42.0 s | 0 | 0/0 | 0 (—) | 1 | 1 | 0/1 | 86 |
| Browse2_pts.mkv | Browse2 | 35.3/35.3 s | 0 | 0/0 | 0 (—) | 1 | 1 | 0/1 | 102 |
| Fight_OneManDown.mpg | Fight_OneManDown | 38.6/38.6 s | 1 | 1/1 | 0 (—) | 2 | 2 | 1/2 | 93 |
| LeftBag_BehindChair.mpg | LeftBag_BehindChair | 43.0/43.0 s | 2 | 0/2 | 2 (object_placed 21.0 s (label manuel) : never_seen, object_removed 34.0 s (label manuel) : never_seen) | 0 | 0 | 0/0 | 0 |
| Rest_InChair.mpg | Rest_InChair | 40.6/40.6 s | 0 | 0/0 | 0 (—) | 0 | 0 | 0/0 | 0 |
| Rest_SlumpOnFloor.mpg | Rest_SlumpOnFloor | 36.7/36.7 s | 1 | 1/1 | 0 (—) | 2 | 2 | 1/2 | 98 |
| Rest_WiggleOnFloor_pts.mkv | Rest_WiggleOnFloor | 52.0/52.0 s | 1 | 1/1 | 0 (—) | 4 | 2 | 1/2 | 69 |
| **Total** | | 288.2 s | **5** | **3/5** | **2** | 10 | 8 (réduction 20%) | **3/8** | 62 |

Objectif du plan : 0 événement critique raté ; au moins 70 % d’alertes en moins en gardant au moins 95 % des vrais événements. « Alertes brutes » est une approximation (observations de sécurité de la perception initiale) tant que le détecteur C1 n’existe pas.

## Sensibilité à la tolérance

| Tolérance | Retrouvés | Alertes vraies | Correspondance large (±2 s) |
|---|---:|---:|---:|
| ±1 s | 3/5 | 3/8 | — |
| ±2 s | 3/5 | 3/8 | 3/5 retrouvés, 3/8 vraies |
| ±5 s | 3/5 | 3/8 | — |

## Temps d’alerte et preuves

| Vidéo | Événement (XML) | Alerte | Temps tel qu’exécuté | Temps en direct (simulé) | Image citée à ±2 s | Fait principal du rapport |
|---|---|---|---:|---:|---|---|
| Fight_OneManDown.mpg | person_fell 13.72 s | supported 12.5–14.5 s | 168 s | 103 s | oui | person_fell |
| Rest_SlumpOnFloor.mpg | person_fell 26.08 s | needs_review:contradicted 20.0–27.5 s | 199 s | 135 s | oui | person_fell |
| Rest_WiggleOnFloor_pts.mkv | person_fell 27.76 s | supported 27.0–29.0 s | 239 s | 144 s | oui | person_fell |
| **Total** | | | | médiane 135 s, max 144 s (cible ≤ 30 s) | | |

Bornes basses : seuls les `elapsed_ms` des appels sont enregistrés (ni heure réelle, ni décodage, ni inspections ciblées, ni pauses).

| Vidéo | Rapport produit | Alertes avec image citée | Citations valides |
|---|---|---:|---:|
| Browse1.mpg | oui | 1/1 | 3/3 |
| Browse2_pts.mkv | oui | 1/1 | 3/3 |
| Fight_OneManDown.mpg | oui | 2/2 | 21/21 |
| LeftBag_BehindChair.mpg | oui | 0/0 | 0/0 |
| Rest_InChair.mpg | oui | 0/0 | 0/0 |
| Rest_SlumpOnFloor.mpg | oui | 2/2 | 5/5 |
| Rest_WiggleOnFloor_pts.mkv | oui | 2/2 | 8/8 |
| **Total** | | 8/8 | 40/40 |

## Coût

Tarifs `gemini-3.6-flash` en $ par million de tokens : lancement 0,75 / 3,75 (jusqu’au 31/12/2026), standard 1,50 / 7,50 (dès le 1/1/2027). Les tokens de réflexion sont facturés comme sortie, sans remise de cache.

| Vidéo | Tokens entrée / sortie | Run lancement ($) | Run standard ($) | dont agents (lancement) | Perception / caméra / mois, lancement ($) | standard ($) |
|---|---:|---:|---:|---:|---:|---:|
| Browse1.mpg | 137,907 / 32,447 | 0.225 | 0.450 | 0.096 | 7,994 | 15,989 |
| Browse2_pts.mkv | 112,775 / 33,752 | 0.211 | 0.422 | 0.093 | 8,673 | 17,346 |
| Fight_OneManDown.mpg | 112,564 / 32,666 | 0.207 | 0.414 | 0.089 | 7,929 | 15,859 |
| LeftBag_BehindChair.mpg | 117,802 / 27,547 | 0.192 | 0.383 | 0.074 | 7,121 | 14,242 |
| Rest_InChair.mpg | 130,283 / 44,796 | 0.266 | 0.531 | 0.127 | 8,863 | 17,725 |
| Rest_SlumpOnFloor.mpg | 137,292 / 40,751 | 0.256 | 0.512 | 0.123 | 9,385 | 18,771 |
| Rest_WiggleOnFloor_pts.mkv | 206,944 / 49,432 | 0.341 | 0.681 | 0.145 | 9,721 | 19,443 |
| **Total** | 955,567 / 261,391 | 1.697 | 3.394 | 0.746 | 8,550 | 17,100 |

Par mois : coût de la perception par minute analysée × 43 200 minutes (toute la vidéo, 30 jours). Les agents ne sont pas extrapolés au mois : leur coût suit le nombre d’événements, pas la durée. Avec la conception en deux étapes : non mesurable (pas encore de détecteur C1).

## Durée réelle des runs

| Vidéo | Durée de la vidéo | Durée du run (horloge) |
|---|---:|---:|
| Browse1.mpg | 42.0 s | 205 s |
| Browse2_pts.mkv | 35.3 s | 230 s |
| Fight_OneManDown.mpg | 38.6 s | 194 s |
| LeftBag_BehindChair.mpg | 43.0 s | 166 s |
| Rest_InChair.mpg | 40.6 s | 270 s |
| Rest_SlumpOnFloor.mpg | 36.7 s | 253 s |
| Rest_WiggleOnFloor_pts.mkv | 52.0 s | 323 s |

Jusqu’à 3 vidéos tournaient en parallèle : les durées incluent l’attente du fournisseur.

## Runs en échec (hors total)

Aucun.

Taux de réussite : 7/7.

## Comparaison avec le tableau de développement

Même version du système, mêmes règles. Les vidéos de développement ont servi à construire le système ; celles-ci jamais. Petits nombres : une différence d’un ou deux événements ne prouve rien.

| | Développement | Jamais vues |
|---|---:|---:|
| Vidéos | 9 | 7 |
| Événements critiques amenés à un humain | 7/8 (88%) | 3/5 (60%) |
| dont confirmés par l’agent | 3/8 (38%) | 2/5 (40%) |
| Alertes vraies | 7/12 (58%) | 3/8 (38%) |
| Fausses alertes par heure analysée | 46 | 62 |
| Temps d’alerte en direct simulé, médiane / max | 63 s / 144 s | 135 s / 144 s |
| Citations valides | 86/86 (100%) | 40/40 (100%) |
| Coût total (lancement) | 2.24 $ pour 6.6 min | 1.70 $ pour 4.8 min |
| Perception par minute (lancement) | 0.206 $ | 0.198 $ |

## Pas encore mesurable

- Temps humain de référence (B5) : recherche manuelle dans la vidéo et rapport écrit à la main, donc ni temps jusqu’à la preuve (B6 manque aussi) ni temps de rapport gagné.
- Rapports approuvés et taux de correction (B8) : `operator_label` est vide partout.
- Temps d’alerte réel : aucune heure réelle enregistrée ; seulement des bornes basses.
- Vraies alertes brutes et coût en deux étapes : détecteur C1 absent.
- Incendie : absent de CAVIAR.
