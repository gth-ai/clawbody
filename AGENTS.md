# AGENTS.md

Comment travailler dans ce dépôt. `CLAUDE.md` décrit l'architecture ; ce
fichier-ci décrit la méthode, tirée de ce qui a réellement fonctionné et de ce
qui a réellement fait perdre du temps.

## La règle qui prime sur toutes les autres

**Mesure avant de conclure.** Ce projet est un système temps réel réparti sur
trois machines (Mac, robot, API OpenAI) où presque tous les symptômes sont
trompeurs. Sur une seule session de débogage, trois hypothèses parfaitement
plausibles ont été démenties par la mesure :

| Hypothèse | Ce que la mesure a montré |
|---|---|
| Les pipelines GStreamer s'empilaient à chaque conversation | Tous les threads vivants portaient le même indice. L'ancien pipeline était bien détruit. |
| `GstWebRTCClient` n'implémente pas `get_audio_sample` | Il en hérite de `AudioBase`. Un `grep "^    def "` ne montre pas les méthodes héritées. |
| `play_loop` était gelé plus d'une seconde | La sonde cumulait la dérive d'`asyncio.sleep` : elle affichait 570 ms sans robot ni micro. Le vrai écart entre deux tours était de 11 ms. |

Aucune n'aurait été détectée par relecture du code. Écris le script de mesure,
lance-le, et laisse le chiffre trancher.

**Corollaire** : une sonde qui donne un chiffre spectaculaire est suspecte avant
d'être convaincante. Fais-la tourner sur un cas témoin (sans robot, sans charge)
pour savoir ce qu'elle affiche quand tout va bien.

## Mesurer sur ce projet

Le journal est l'instrument principal. `clawbody.log` est **écrasé à chaque
lancement** : copie-le dans le scratchpad avant de relancer, sinon tu perds les
preuves.

```bash
grep -E "User:|Réponse en|Audio out" clawbody.log   # le fil d'une conversation
```

Lecture des trois signaux :

- **aucune ligne `User:`** : la voix n'atteint pas OpenAI. Mesure le micro
  isolément (script dans le README) : le *ratio* dit si des trames sont jetées,
  le *RMS* dit si le micro capte.
- **`User:` mais pas d'`Audio out`** : la voix passe, la réponse ne sort pas.
  Regarde les `Session error` juste avant.
- **`Audio out` qui progresse plus vite que l'horloge** : le robot accumule du
  retard de parole, et répond à ce qui a été dit bien plus tôt.

Certaines lignes utiles (barge-in, écho) sont en `logger.debug`. **Un `grep` qui
ne renvoie rien sur un run sans `--debug` ne prouve rien.**

## Avant de déboguer, nettoie l'environnement

Il a été constaté une instance ClawBody oubliée depuis trois jours (3,8 Go,
113 % de CPU en continu) et 95 serveurs MCP orphelins. Toute mesure prise dans
ces conditions est fausse.

```bash
pgrep -lf "bin/clawbody"                 # une seule instance attendue
pgrep -f "mcp/server.ts" | wc -l         # 0 à l'arrêt
pkill -f "bin/clawbody"; sleep 3; pkill -9 -f "mcp/server.ts"
```

`SIGINT` ne suffit pas toujours à arrêter ClawBody : prévois `SIGTERM`.

## Toucher aux boucles audio

`record_loop` et `play_loop` sont temps réel. Avant d'y ajouter quoi que ce soit,
demande-toi si l'appel peut bloquer, même brièvement. Un `sleep(0.01)` d'apparence
anodine y jetait 17 % de la voix captée.

Vérifie qu'un appel du SDK ne bloque pas avant de l'appeler dans une boucle :
`get_audio_sample()` descend sur `try_pull_sample(20 ms)`, ce qui ne se voit pas
depuis la signature.

Ces boucles peuvent se tester **sans robot** : un faux handler et un faux media
suffisent à valider la contre-pression, l'absence de perte et l'abandon après
interruption. Fais-le avant de mobiliser le matériel.

## Interpréter une différence entre le SDK lu et le SDK exécuté

`../sdk-repo/` est un clone de lecture ; le code qui tourne est dans
`.venv/lib/python3.12/site-packages/reachy_mini/`. Ils peuvent diverger.
Quand un comportement contredit le code, `diff` les deux avant d'aller plus loin.

## Tester avec le robot

Le robot est physique et l'utilisateur est dans la boucle : **tu ne peux pas
valider seul** un correctif audio. Prépare tout (lancement, surveillance du log),
puis dis précisément quoi faire et quoi observer. Sur la contre-pression, la
consigne utile était : « pose une question qui appelle une réponse longue, puis
coupe-lui la parole ». C'est le seul geste qui exerce à la fois le plafond et
le barge-in.

En attendant, ne laisse pas tourner des moniteurs à vide : s'ils expirent sans
événement, constate-le et rends la main plutôt que d'en réarmer un de plus.

## Rendre compte

Distingue systématiquement trois états, sans les confondre dans le récit :

1. **mesuré** (un chiffre avant/après),
2. **testé hors robot** (logique validée, matériel non exercé),
3. **écrit mais non vérifié**.

Quand une de tes hypothèses tombe, corrige-la en une phrase et continue. Ne
laisse pas une conclusion démentie dans un récapitulatif : le suivi de visage
passé de 1-13 Hz à 27,9 Hz est un fait ; « `play_loop` était gelé » ne l'était
pas, et le dire aurait envoyé la personne suivante sur une fausse piste.

## Conventions du dépôt

- **Français** pour les commentaires ajoutés, les messages de commit et la
  documentation. Le code d'origine est en anglais : ne le traduis pas au passage.
- **Pas de tiret cadratin** (`—`) dans les textes rédigés (voir les préférences
  globales de l'utilisateur). Le demi-cadratin `–` des plages de valeurs reste
  correct.
- **Aucune attribution IA** dans les commits ou les PR : pas de trailer
  `Co-Authored-By`, pas de mention d'outil.
- Les messages de commit expliquent **pourquoi**, avec les chiffres mesurés.
  Regarde `git log` : c'est la forme attendue, et c'est ce qui rend le
  raisonnement rejouable des mois plus tard.
- Les commentaires de code disent **ce que le naïf aurait fait et pourquoi ça
  échoue**. Un commentaire qui paraphrase la ligne suivante n'apporte rien.

## Documenter au bon endroit

- `CLAUDE.md` : architecture et invariants, pour se rendre productif vite.
- `INSTALL-LOCAL.md` : correctifs appliqués à l'upstream et particularités de
  cette machine. **À lire avant de conclure qu'un comportement est un bug local.**
- `README.md` : dépannage destiné à l'utilisateur, avec commandes de diagnostic.
- `.env.example` : tout nouveau réglage y figure, avec l'effet du curseur dans
  les deux sens.
