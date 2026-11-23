# Test hors ligne de continuité visuelle

Trois paquets anonymisés de trois images natives couvrent exactement 10–13 s. Le manifeste associe chaque fichier au PTS, à l'index de présentation et au hash RGB24. Les paquets ne contiennent pas les réponses attendues. Les régions désignent des silhouettes locales et ne prétendent pas identifier des personnes.

## Clé de travail provisoire — ne pas transmettre avant la relecture

| Paquet | Manipulation | Référence provisoire |
|---|---|---|
| K7 | 250, 300, 325. Silhouette du haut aux deux extrémités. | La progression vers la gauche est compatible avec la même trajectoire. |
| M2 | Même paire finale, mais 300 est remplacée par 251, presque redondante avec 250. | La continuité de la source ne change pas. La vue de liaison est affaiblie. Le paquet pourrait rester suffisant grâce à la position et à l'apparence; l'abstention n'est pas présupposée. |
| Q4 | Même grille que K7. Région finale sur l'autre silhouette. | Les deux silhouettes sont simultanément visibles et suivent deux trajectoires distinctes dans la portion retenue. Contrôle négatif provisoire. |

Autour de 14,52 s (image 363), le contexte de la galerie, le premier plan et la perte de détails rendent le suivi plus incertain. Ce passage reste un exemple qualitatif indéterminé, hors des trois paquets. Les trois contrôles portent donc sur 10–13 s. Il ne faut pas extrapoler leur résultat à l'intervalle plus difficile.

## Grille à remplir

| Code | Jugement paquet et accord | Jugement source et accord | Réponse agent | Liens étayés / faux / non étayés | Abstention justifiée ? | Indices et PTS valides ? |
|---|---|---|---|---|---|---|
| K7 | | | | | | |
| M2 | | | | | | |
| Q4 | | | | | | |

Demander une réponse structurée avec `decision` parmi `same_person`, `different_people`, `indeterminate`, une `reason` et des `citations` donnant les indices et régions. Évaluer les liens selon ce que permet le paquet seul. Une bonne réponse par devinette reste non étayée. Une abstention peut être correcte même si la continuité est établie par la source complète. Conserver les jugements individuels et les désaccords. Les réponses de Gemini, les annotations indépendantes et l'accord sont tous non mesurés. Si M2 reste identifiable pour les relecteurs, il ne valide pas un contrôle d'abstention; il faut le remplacer ou limiter la conclusion du test.

## Reproduction locale

```sh
.venv/bin/python experiments/person_continuity_offline/build.py
ffmpeg -v error -ss 10 -i data/raw/Meet_WalkSplit_pts.mp4 -frames:v 76 -map 0:v:0 -c:v ffv1 /tmp/sa-person-continuity-reference.mkv
```

Le script compare les PTS FFprobe au catalogue source, relit chaque PNG et vérifie l'égalité exacte des pixels décodés. Le clip de référence contient les images consécutives 250–325. Fournir d'abord uniquement les fichiers du paquet et le formulaire paquet, puis la référence continue et le second formulaire. Produire les annotations indépendantes avant tout appel Gemini. Ensuite, sous autorisation distincte, exécuter le Verification Agent sur les mêmes paquets et noter les résultats avec la grille. Aucun code de production ni appel externe n'est requis pour la préparation.
