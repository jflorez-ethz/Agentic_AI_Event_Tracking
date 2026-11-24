# KPI hors ligne (tâche B7)

Version mesurée : arbre src `7e86f3b` (commit `bd6046f`). Règles figées : [rules.json](rules.json). Correspondance stricte, tolérance ±2 s. Runs complets : 9/9. Les anciens runs archivés ne sont pas lus. Vérité terrain : XML CAVIAR. Tous ces clips ont servi au développement : aucune conclusion de généralisation.

## Alertes et événements critiques

| Vidéo | Run | Analysé | Événements XML | Retrouvés | Ratés (cause) | Alertes brutes (approx.) | Alertes à un humain | dont vraies | Fausses / h |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| LeftBag.mpg | LeftBag | 57.8/57.8 s | 2 | 2/2 | 0 (—) | 6 | 6 | 2/6 | 249 |
| LeftBag_AtChair.mpg | LeftBag_AtChair | 44.8/44.8 s | 2 | 1/2 | 1 (object_placed 18.4 s : never_seen) | 1 | 1 | 1/1 | 0 |
| LeftBag_PickedUp.mpg | LeftBag_PickedUp | 54.5/54.5 s | 2 | 2/2 | 0 (—) | 1 | 2 | 2/2 | 0 |
| LeftBox_pts.mkv | LeftBox | 34.8/34.8 s | 1 | 1/1 | 0 (—) | 1 | 1 | 1/1 | 0 |
| Meet_WalkSplit_pts.mp4 | Meet_WalkSplit | 25.0/25.0 s | 0 | 0/0 | 0 (—) | 0 | 0 | 0/0 | 0 |
| Meet_WalkTogether1_pts.mp4 | Meet_WalkTogether1 | 28.3/28.3 s | 0 | 0/0 | 0 (—) | 0 | 0 | 0/0 | 0 |
| Rest_FallOnFloor.mpg | Rest_FallOnFloor | 40.6/40.6 s | 1 | 1/1 | 0 (—) | 2 | 2 | 1/2 | 89 |
| TwoEnterShop1front_pts.mkv | TwoEnterShop1front | 65.8/65.8 s | 0 | 0/0 | 0 (—) | 1 | 0 | 0/0 | 0 |
| Walk2.mpg | Walk2 | 42.5/42.5 s | 0 | 0/0 | 0 (—) | 0 | 0 | 0/0 | 0 |
| **Total** | | 394.0 s | **8** | **7/8** | **1** | 12 | 12 (réduction 0%) | **7/12** | 46 |

Objectif du plan : 0 événement critique raté ; au moins 70 % d’alertes en moins en gardant au moins 95 % des vrais événements. « Alertes brutes » est une approximation (observations de sécurité de la perception initiale) tant que le détecteur C1 n’existe pas.

## Sensibilité à la tolérance

| Tolérance | Retrouvés | Alertes vraies | Correspondance large (±2 s) |
|---|---:|---:|---:|
| ±1 s | 7/8 | 7/12 | — |
| ±2 s | 7/8 | 7/12 | 7/8 retrouvés, 7/12 vraies |
| ±5 s | 7/8 | 7/12 | — |

## Temps d’alerte et preuves

| Vidéo | Événement (XML) | Alerte | Temps tel qu’exécuté | Temps en direct (simulé) | Image citée à ±2 s | Fait principal du rapport |
|---|---|---|---:|---:|---|---|
| LeftBag.mpg | object_placed 38.04 s | supported 37.0–38.5 s | 264 s | 144 s | oui | object_placed |
| LeftBag.mpg | object_removed 54.44 s | needs_review:not_checked 50.0–55.0 s | 164 s | 42 s | oui | object_placed |
| LeftBag_AtChair.mpg | object_removed 37.20 s | needs_review:unclear_observation 34.5–36.5 s | 111 s | 46 s | oui | person_moved |
| LeftBag_PickedUp.mpg | object_placed 20.36 s | needs_review:unclear_observation 20.0–20.6 s | 132 s | 58 s | oui | person_moved |
| LeftBag_PickedUp.mpg | object_removed 40.88 s | needs_review:unclear_observation 40.0–41.0 s | 132 s | 63 s | oui | person_moved |
| LeftBox_pts.mkv | object_placed 23.08 s | supported 21.0–23.5 s | 188 s | 140 s | oui | object_placed |
| Rest_FallOnFloor.mpg | person_fell 26.44 s | supported 25.5–28.0 s | 182 s | 108 s | oui | person_fell |
| **Total** | | | | médiane 63 s, max 144 s (cible ≤ 30 s) | | |

Bornes basses : seuls les `elapsed_ms` des appels sont enregistrés (ni heure réelle, ni décodage, ni inspections ciblées, ni pauses).

| Vidéo | Rapport produit | Alertes avec image citée | Citations valides |
|---|---|---:|---:|
| LeftBag.mpg | oui | 6/6 | 49/49 |
| LeftBag_AtChair.mpg | oui | 1/1 | 6/6 |
| LeftBag_PickedUp.mpg | oui | 2/2 | 4/4 |
| LeftBox_pts.mkv | oui | 1/1 | 16/16 |
| Meet_WalkSplit_pts.mp4 | oui | 0/0 | 0/0 |
| Meet_WalkTogether1_pts.mp4 | oui | 0/0 | 0/0 |
| Rest_FallOnFloor.mpg | oui | 2/2 | 11/11 |
| TwoEnterShop1front_pts.mkv | oui | 0/0 | 0/0 |
| Walk2.mpg | oui | 0/0 | 0/0 |
| **Total** | | 12/12 | 86/86 |

## Coût

Tarifs `gemini-3.6-flash` en $ par million de tokens : lancement 0,75 / 3,75 (jusqu’au 31/12/2026), standard 1,50 / 7,50 (dès le 1/1/2027). Les tokens de réflexion sont facturés comme sortie, sans remise de cache.

| Vidéo | Tokens entrée / sortie | Run lancement ($) | Run standard ($) | dont agents (lancement) | Perception / caméra / mois, lancement ($) | standard ($) |
|---|---:|---:|---:|---:|---:|---:|
| LeftBag.mpg | 213,045 / 54,599 | 0.365 | 0.729 | 0.127 | 10,651 | 21,303 |
| LeftBag_AtChair.mpg | 117,543 / 27,862 | 0.193 | 0.385 | 0.074 | 6,888 | 13,776 |
| LeftBag_PickedUp.mpg | 167,549 / 36,988 | 0.264 | 0.529 | 0.102 | 7,733 | 15,466 |
| LeftBox_pts.mkv | 112,745 / 36,256 | 0.221 | 0.441 | 0.106 | 8,513 | 17,026 |
| Meet_WalkSplit_pts.mp4 | 75,627 / 28,409 | 0.163 | 0.327 | 0.077 | 8,969 | 17,937 |
| Meet_WalkTogether1_pts.mp4 | 120,064 / 27,145 | 0.192 | 0.384 | 0.086 | 9,661 | 19,322 |
| Rest_FallOnFloor.mpg | 184,359 / 43,932 | 0.303 | 0.606 | 0.112 | 12,194 | 24,388 |
| TwoEnterShop1front_pts.mkv | 226,742 / 48,014 | 0.350 | 0.700 | 0.131 | 8,629 | 17,258 |
| Walk2.mpg | 112,043 / 29,424 | 0.194 | 0.389 | 0.079 | 7,030 | 14,060 |
| **Total** | 1,329,717 / 332,629 | 2.245 | 4.489 | 0.894 | 8,884 | 17,768 |

Par mois : coût de la perception par minute analysée × 43 200 minutes (toute la vidéo, 30 jours). Les agents ne sont pas extrapolés au mois : leur coût suit le nombre d’événements, pas la durée. Avec la conception en deux étapes : non mesurable (pas encore de détecteur C1).

## Durée réelle des runs

| Vidéo | Durée de la vidéo | Durée du run (horloge) |
|---|---:|---:|
| LeftBag.mpg | 57.8 s | 344 s |
| LeftBag_AtChair.mpg | 44.8 s | 187 s |
| LeftBag_PickedUp.mpg | 54.5 s | 246 s |
| LeftBox_pts.mkv | 34.8 s | 236 s |
| Meet_WalkSplit_pts.mp4 | 25.0 s | 166 s |
| Meet_WalkTogether1_pts.mp4 | 28.3 s | 175 s |
| Rest_FallOnFloor.mpg | 40.6 s | 288 s |
| TwoEnterShop1front_pts.mkv | 65.8 s | 357 s |
| Walk2.mpg | 42.5 s | 196 s |

Jusqu’à 3 vidéos tournaient en parallèle : les durées incluent l’attente du fournisseur.

## Runs en échec (hors total)

Aucun.

Taux de réussite : 9/9.

## Pas encore mesurable

- Temps humain de référence (B5) : recherche manuelle dans la vidéo et rapport écrit à la main, donc ni temps jusqu’à la preuve (B6 manque aussi) ni temps de rapport gagné.
- Rapports approuvés et taux de correction (B8) : `operator_label` est vide partout.
- Temps d’alerte réel : aucune heure réelle enregistrée ; seulement des bornes basses.
- Vraies alertes brutes et coût en deux étapes : détecteur C1 absent.
- Incendie : absent de CAVIAR.
