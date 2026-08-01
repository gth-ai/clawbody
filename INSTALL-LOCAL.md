# ClawBody — installation sur cette machine

Ce que l'installation upstream ne dit pas, et ce qu'il a fallu changer pour que
ça tourne ici. Tout est déjà appliqué ; ce fichier explique **pourquoi**, pour
que rien ne soit défait par accident.

## Démarrer

```bash
cd /Volumes/gthSSD4TPRO/apps/reachy-mini/clawbody
./run.sh --gradio      # interface web sur http://127.0.0.1:7860
./run.sh               # mode console
```

`run.sh` pose `DYLD_FALLBACK_LIBRARY_PATH` avant de lancer — même correctif que
`../sim.sh`. Sans lui, GStreamer n'arrive pas à charger `libgstpython.dylib`
(il cherche `libpython3.12.dylib` via `@rpath`) et crache un pavé de warnings.

## Venv séparé — ne pas fusionner avec `../.venv`

ClawBody a son propre `.venv`. C'est **obligatoire**, pas un choix de style :

| Paquet | Contrainte |
|---|---|
| `reachy_mini` 1.9.0 | `pydantic >= 2.12.5` |
| `gradio` 5.50.0 (le plus récent que `fastrtc` accepte : `gradio < 6`) | `pydantic <= 2.12.3` |

Les deux ne peuvent pas cohabiter. Installer ClawBody dans `../.venv` y ferait
descendre `pydantic` 2.13.4 → 2.12.3, `numpy` 2.5.1 → 2.4.6 et
`gradio_client` 2.6.0 → 1.14.0, sous le plancher déclaré par le SDK — donc au
risque de casser `sim.sh` et `apps/mini_attentif`. **`../.venv` est resté
strictement inchangé** (vérifié par diff de `pip freeze` avant/après).

Ici on tranche par `overrides.txt` (`pydantic==2.12.3`). `pip check` signale
donc un écart :

```
reachy-mini 1.9.0 has requirement pydantic<3.0.0,>=2.12.5, but you have pydantic 2.12.3.
```

C'est **connu et assumé** : écart de patch, et tout le SDK a été exercé
avec (poses, moves, MovementManager, caméra, audio, outils) sans incident.

Réinstallation complète :

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --override overrides.txt \
  -e . reachy_mini==1.9.0 ultralytics supervision reachy-mini-dances-library
```

## Le robot n'est pas sur cette machine

`localhost:8000` est servi par l'app **Reachy Mini Control**, qui n'est qu'un
**proxy** : le robot est à `reachy-mini.local` = `10.0.0.25`, ce Mac est en
`10.0.0.179`.

En `connection_mode="auto"`, le SDK voit un daemon sur localhost, en déduit
qu'il est co-localisé et choisit le backend média **LOCAL** (caméra et audio en
IPC mémoire partagée). Les moteurs marchent — ils passent par le proxy HTTP —
mais la caméra ne renvoie **jamais** rien, sans erreur explicite.

D'où, dans `.env` :

```
REACHY_CONNECTION_MODE=network
REACHY_HOST=reachy-mini.local
```

qui force le backend **WebRTC** : vidéo 1280×720 et audio 16 kHz stéréo
bidirectionnel arrivent bien du robot.

> Si un jour le robot est branché en USB sur ce Mac (ou si tu passes au
> simulateur via `../sim.sh`), repasse en `REACHY_CONNECTION_MODE=auto`.

## Correctifs appliqués au code upstream

### 1. `openclaw_bridge.py` — protocole de la passerelle

Trois bugs empêchaient toute connexion à OpenClaw 2026.5.20 :

- **Version de protocole.** Le client annonçait `minProtocol = maxProtocol = 3` ;
  la passerelle exige 4 → `INVALID_REQUEST - protocol mismatch`.
  Corrigé en annonçant une plage `3..4`, compatible avec les deux générations.
- **Identité client.** Il se présentait comme `openclaw-control-ui` / mode
  `webchat`, avec un en-tête `Origin`. La passerelle applique alors la politique
  d'appairage de l'interface web et exige une identité device →
  `control ui requires device identity`. Il se présente maintenant comme un
  client `cli`, sans `Origin`.
- **Scopes.** Même connecté, un client authentifié par simple token se fait
  **vider ses scopes** faute d'identité device signée → `chat.send` échouait sur
  `missing scope: operator.write`.

Le troisième point n'est pas contournable proprement côté client : les scopes
viennent de l'appairage device (Ed25519), pas du token de passerelle. D'où un
**second transport**, désormais le défaut :

```
OPENCLAW_TRANSPORT=cli    # passe par `openclaw agent --json`
OPENCLAW_TRANSPORT=ws     # WebSocket direct (nécessite un device appairé)
```

Le mode `cli` réutilise l'identité déjà appairée du CLI OpenClaw. Il survit aux
mises à jour de la passerelle, contrairement à une réimplémentation Python de
la signature device. Coût : ~0,1 s de démarrage de process par tour, et pas de
streaming token par token (la réponse arrive d'un bloc).

Le sous-processus reçoit un environnement **expurgé** de `OPENCLAW_GATEWAY_URL`
et consorts : le CLI lit les mêmes noms de variables et traite une URL qu'il n'a
pas configurée lui-même comme un override exigeant des credentials explicites.

### 2. `tools/core_tools.py` — l'outil `dance` ne dansait pas

Le code faisait `from reachy_mini_dances_library import dances`, un symbole qui
n'existe pas : la bibliothèque expose `DanceMove` et
`collection.dance.AVAILABLE_MOVES`. L'`ImportError` était rattrapé, donc chaque
`dance()` retombait silencieusement sur une simple émotion.

Corrigé, avec une table `_DANCE_ALIASES` qui relie les noms expressifs du
schéma d'outil (`happy`, `excited`, `wave`…) aux 20 vraies chorégraphies.
`dance("simple_nod")` — un nom brut de la bibliothèque — marche aussi.

### 3. `vision/mediapipe_tracker.py` — API disparue

`mediapipe >= 0.10.35` ne fournit plus `mp.solutions` (seulement l'API Tasks),
dont dépend tout ce tracker. Il échouait à l'instanciation, après l'import,
avec un `AttributeError` opaque. Il lève maintenant un `ImportError` explicite
au chargement, ce qui laisse `get_head_tracker()` basculer proprement.

**Le tracker utilisé ici est YOLO** (`HEAD_TRACKER_TYPE=yolo`), modèle
`AdamCodd/YOLOv11n-face-detection` téléchargé depuis Hugging Face au premier
lancement. C'est ce qui pèse le plus dans les 2,7 Go du venv (torch).

> Le suivi de visage **natif du SDK** (`start_head_tracking()` /
> `get_tracked_face()`) fonctionne aussi, mais son détecteur ne tourne que
> lorsqu'il pilote lui-même la tête (mesuré : 6/10 détections à `weight=1.0`,
> 0/10 à `weight=0.0`). Il entrerait donc en conflit avec le `MovementManager`
> de ClawBody. Écarté pour cette raison.

### 4. `openai_realtime.py` — l'API Realtime Beta est morte

C'est le blocage le plus dur, et il touche **tout le monde** qui installe ClawBody
upstream aujourd'hui. Le code appelait `client.beta.realtime.connect()`. OpenAI a
coupé cette surface côté serveur :

```
The Realtime Beta API is no longer supported. Please use /v1/realtime for the GA API.
  type=invalid_request_error  code=beta_api_shape_disabled
```

Migré vers la GA (`client.realtime.connect()`). Quatre différences de forme :

| Beta | GA |
|---|---|
| `"modalities": ["text","audio"]` | `"output_modalities": ["audio"]` — la GA **refuse** les deux ensemble ; la transcription arrive avec l'audio |
| `"input_audio_format": "pcm16"` | `audio.input.format = {"type":"audio/pcm","rate":24000}` |
| `voice`, `turn_detection`, `input_audio_transcription` au premier niveau | regroupés sous `audio.input` / `audio.output` |
| `response.audio.delta`, `response.audio_transcript.{delta,done}` | `response.output_audio.delta`, `response.output_audio_transcript.{delta,done}` |

Inchangés : `input_audio_buffer.append(audio=…)`, `conversation.item.create`,
`response.created` / `response.done`, `response.function_call_arguments.done`,
`error`, et le format des outils. ClawBody échantillonnait déjà à 24 kHz, donc le
rééchantillonnage existant convient tel quel.

`session.update` accepté, 7 outils enregistrés, audio et transcription reçus.

### 5. Langue de la conversation

Au premier essai vocal, le robot a compris le français (`User: C'est bien avec
nous ou pas…`) mais **répondait en thaï**. Ce n'est pas un bug de transcription :
les instructions système sont pour l'essentiel le contexte renvoyé par
OpenClaw — 147 caractères produits par un modèle local de 2 Go — et rien n'y
fixe la langue, donc le modèle Realtime en choisit une plus ou moins au hasard.

Ajout d'un réglage `SPEECH_LANGUAGE` (ISO-639-1) qui agit à deux endroits :
`audio.input.transcription.language` (précision et latence de transcription) et
une consigne explicite ajoutée aux instructions système. `SPEECH_LANGUAGE=fr`
dans `.env`. Vide = comportement d'origine.

### 6. `tools/core_tools.py` — l'outil `camera` se faisait refuser

Le prompt envoyé à `gpt-4o-mini` demandait d'être *« specific about people »*.
Le modèle refuse alors la requête entière :

> I'm unable to provide a description of the image.

Reformulé : décrire la scène, le décor, la lumière, l'ambiance ; pour les
personnes, seulement combien et ce qu'elles font, sans description physique ni
identification. Le refus disparaît et l'outil renvoie une vraie description
(vérifié sur une image réelle du robot).

### 7. Le robot se coupait la parole tout seul

Symptôme : on n'entend pas Clawson. Deux causes distinctes, trouvées l'une
après l'autre.

**a. Un flux ALSA fantôme.** L'app `mini_attentif`, déployée plus tôt, tournait
encore sur le robot et tenait le haut-parleur ouvert sans jamais y écrire
(`/proc/asound/card0/pcm0p/sub0/status` : `state: RUNNING`, `appl_ptr: 0`,
`Subdevices: 0/1`). Plus rien ne sortait, pas même le son de test du daemon.
`./deploy.sh --stop` puis `POST /api/daemon/restart` ont libéré le périphérique.

> Attention : `deploy.sh --stop` envoie un `SIGINT` que l'app n'a pas honoré.
> Le process est bien mort, mais son flux ALSA est resté ouvert jusqu'au
> redémarrage du daemon.

**b. Pas d'annulation d'écho — le vrai coupable.** Haut-parleur et micro
partagent le même petit corps, sans AEC entre les deux. `receive()` envoyait le
micro à OpenAI **en permanence**, y compris pendant que le robot parlait. Le
robot s'entendait donc lui-même, le VAD serveur déclarait « l'utilisateur
parle », et la réponse en cours était annulée. Trace mesurée :

```
20:08:13 User started speaking (flushed 0 audio chunks)
20:08:15 Audio out: 1 chunks, 0.4s pushed to speaker     ← 0,4 s seulement
20:08:15 User started speaking (flushed 0 audio chunks)  ← le robot s'entend
20:08:15 Assistant: Salut ! Contente de te               ← phrase tronquée
```

`flushed 0` innocente le vidage de file : c'est bien le serveur qui coupait la
réponse. Correctif : mode **half-duplex** — `receive()` jette les trames micro
tant que le robot parle, plus une queue de `MIC_GATE_TAIL_MS` (500 ms par
défaut) pour couvrir latence et réverbération.

```
MIC_GATE_WHILE_SPEAKING=true    # false pour retrouver l'interruption à la voix
MIC_GATE_TAIL_MS=500
```

Une coupure sèche règle la troncature mais rend le robot ininterruptible, ce
qui est aussi désagréable. La version retenue est donc un **détecteur de
double-parole** : pendant que le robot parle, `receive()` mesure le niveau de
l'écho revenant au micro (moyenne glissante) et ne jette une trame que si elle
reste dans ce niveau. Une trame nettement plus forte — `MIC_ECHO_RATIO` fois
au-dessus, et au-dessus du plancher `MIC_MIN_RMS` — est quelqu'un qui parle
par-dessus : elle passe, et l'interruption fonctionne.

```
MIC_ECHO_RATIO=2.5   # plus bas = plus facile d'interrompre, plus de risque
MIC_MIN_RMS=0.02     # de le voir se recouper tout seul
```

Ce n'est pas une vraie AEC — ça compare des énergies, ça n'annule rien.

**Pourquoi pas une vraie AEC ?** Mesuré, pas supposé. Un chirp émis puis
corrélé avec la capture micro, 6 essais :

| | |
|---|---|
| délai d'écho moyen | **807 ms** |
| gigue | **370 ms** (536 → 906) |
| écart-type | 125 ms |

Un filtre adaptatif encaisse un délai long — il suffit d'allonger le filtre.
Ce qu'il n'encaisse pas, c'est un délai qui **bouge** : il s'accroche à une
réponse impulsionnelle supposée stable, et avec 370 ms de gigue il poursuit
une cible mouvante sans jamais converger. Le chemin est
Mac → Opus → réseau → jitter buffer → dmix (4096 trames à 16 kHz) → HP → air →
micro → dsnoop → Opus → réseau → jitter buffer → Mac. Le seul endroit où une
AEC serait viable, c'est **sur le robot**, où HP et micro sont locaux et le
délai stable — mais c'est le daemon de Pollen, écrasé à chaque mise à jour.

Le détecteur de double-parole est donc le bon outil pour cette topologie, pas
un pis-aller.

**Deux vrais bugs sortis de cette mesure.**

*a. La suppression suivait l'heure d'envoi, pas la lecture.* L'audio d'OpenAI
arrive bien plus vite que le temps réel — 10 s de parole poussées en 2 s — et
le robot bufferise le surplus. L'horodatage du dernier envoi ne dit donc rien
du moment où le robot se tait. `note_speaker_audio()` accumule maintenant la
**durée** poussée, et la suppression se base là-dessus.

*b. Interrompre ne coupait pas le son.* Vider notre file ne suffit pas : des
secondes de parole sont déjà dans la chaîne WebRTC et dans la file du daemon.
Le SDK expose `clear_player()` — qui flushe la chaîne d'envoi **et** demande
au daemon de vider sa file de lecture — mais il n'est pas remonté sur
`MediaManager`, et ClawBody ne l'appelait jamais. Il est désormais appelé sur
`speech_started`, via `robot.media.audio.clear_player()`.

C'est ce qui explique le « il ne s'arrête pas de façon fluide quand je parle » :
la détection marchait, mais le robot rejouait un tampon déjà parti.

Deux compteurs ont été ajoutés pour rendre ça diagnosticable :
`Audio out: N chunks, X.Xs pushed to speaker` et le nombre de trames vidées
dans `User started speaking (flushed N audio chunks)`. Le silence devient
lisible : plus de réponse du tout, ou une réponse jetée avant lecture.

**c. Démarrage borné.** `get_agent_context()` peut dépasser 2 minutes (tour
d'agent complet sur un modèle local), et se trouve entre « Ready! » et le
premier mot audible. Il est désormais plafonné par `OPENCLAW_CONTEXT_TIMEOUT`
(45 s), avec repli sur l'identité intégrée.

### 8. `camera_worker.py` — le suivi tournait à moitié vitesse

Symptôme : « il ne me track pas comme il faut », suivi mou.

La boucle de suivi terminait par un `time.sleep(0.04)` commenté « maintain
~25 Hz ». Mais c'est une pause **fixe, ajoutée au temps de travail** : YOLO
prend 31,5 ms sur une frame 720p, donc la période réelle était
31,5 + 40 = 71,5 ms, soit **13,2 Hz mesurés**. Or le lissage EMA juste
au-dessus est explicitement calé sur 25 Hz (`smoothing_alpha = 0.25`) — à
13 Hz il convergeait presque deux fois trop lentement.

Corrigé en cadence fixe : ne dormir que le reste de la période.
Mesuré dans l'app complète : **23,5–23,6 Hz**.

```
avant : 13,2 Hz        après : 23,6 Hz
```

La boucle logge maintenant sa fréquence toutes les 10 s, pour que le
ralentissement se voie au lieu de se deviner.

**Puis : YOLO tournait sur le CPU.** `main.py` l'instanciait avec
`device="cpu"` et le commentaire « CPU is fast enough for face detection ».
Mesuré sur 12 vraies frames 720p du robot :

| config | ms/frame | écart sur le centre détecté |
|---|---|---|
| cpu (défaut) | 27,6 | référence |
| **mps (GPU)** | **6,7** | **0,0000** — identique |
| cpu imgsz=320 | 8,5 | 0,0057 |
| mps imgsz=480 | 5,9 | 0,0079 |

Réduire la frame accélère mais déplace la détection ; le GPU va 4× plus vite
sans rien changer au résultat. Le device suit maintenant `VISION_DEVICE`
(défaut `auto` → mps / cuda / cpu).

**Et le lissage se dérive de la cadence.** Un alpha figé change silencieusement
la vitesse de convergence dès que la cadence bouge — c'est précisément le bug
ci-dessus. Il est désormais calculé depuis `FACE_TRACKING_HZ` en gardant
constant le temps de convergence à 95 % (0,42 s), ce qui redonne exactement
`alpha = 0,248` à 25 Hz. `FACE_TRACKING_HZ` passe à 30, la cadence de la
caméra.

Profil final de la boucle : `get_frame` 24,6 ms (bloque sur les 30 fps de la
caméra), YOLO 11,4 ms, `look_at_image` 0,1 ms. **C'est la caméra qui cadence
la boucle, plus le détecteur.**

```
13,2 Hz  →  25,4 Hz  (mesuré dans l'app complète, ×1,9)
```

### 9. Le bouton Start de l'interface Gradio ne marchait pas

Deux choses distinctes derrière « `clawbody --gradio` ne fonctionne pas ».

**a. La commande n'existe pas telle quelle ici.** ClawBody vit dans son propre
venv, donc `clawbody` n'est pas sur le PATH. Utilise `./run.sh --gradio`, qui
pointe le bon binaire *et* pose le correctif GStreamer.

**b. Et même lancée correctement, l'UI s'ouvrait sans jamais démarrer.**
`gradio_app.start_conversation()` construit `ClawBodyCore` avec
`enable_face_tracking=` et `head_tracker_type=` — deux paramètres que
`ClawBodyCore.__init__` n'acceptait pas. Le `TypeError` était avalé par le
`except Exception` du handler et affiché en « Error: … » dans la petite zone
Status. Le serveur répondait bien en HTTP 200 : seul le bouton était mort.

Les deux paramètres sont ajoutés et surchargent la config, ce qui rend enfin
effectif ce que l'UI (et `--no-face-tracking`) prétendaient régler.

**Au passage :** `ClawBodyCore.__init__` faisait `sys.exit(1)` si le robot
était injoignable. `SystemExit` n'hérite pas de `Exception`, donc il traversait
le `except Exception` de Gradio — bouton en échec, rien d'exploitable à
l'écran. Il lève maintenant une `RuntimeError`, que `main()` retransforme en
code de sortie pour la ligne de commande.

Vérifié via l'API Gradio, pas seulement par lecture :
`Start → 'Started successfully'`, `Stop → 'Stopped'`, et un cycle
start/stop/start/stop complet.

### 10. `ask_openclaw` échouait sur toutes les requêtes

Le robot a bien accès à tout OpenClaw — mesuré sur l'agent `main` :
**41 skills**, **13 outils** (`read`, `edit`, `write`, `exec`, `process`,
`sessions_*`, `subagents`, `image`), les 7 fichiers d'espace de travail
injectés (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`…), et
la session `agent:main:main` partagée avec WhatsApp et Telegram.

Sauf qu'en pratique chaque appel renvoyait :

```
Context overflow: prompt too large for the model.
```

Ce n'est pas ClawBody. Le modèle primaire de l'agent est `ollama/qwen3.5:2b`,
**16 384 tokens de fenêtre**, et le prompt système en consomme déjà
~10 900 (43 527 caractères : 14 264 de skills, 6 387 de schémas d'outils, le
reste en contexte projet) — **66 % de la fenêtre avant la moindre question**.
Mesuré sur un simple « Réponds OK » : 14 784 tokens, soit 90 %. Il n'y avait
pas la place pour une conversation.

Ajout de `OPENCLAW_MODEL`, qui ne s'applique **qu'aux requêtes du robot** —
tes autres canaux gardent leur défaut :

```
OPENCLAW_MODEL=openai/gpt-5.6-sol     # 372 000 tokens au lieu de 16 384
```

**Piège** : la passerelle refuse une surcharge de modèle absente de la liste
blanche de l'agent — `Model override "…" is not allowed for agent "main"`.
Cette liste, ce sont les **clés de `agents.defaults.models`** dans
`~/.openclaw/openclaw.json`. Il faut donc y ajouter le modèle :

```json
"agents": { "defaults": { "models": { "openai/gpt-5.6-sol": {} } } }
```

Ajout purement additif : le modèle primaire des autres canaux ne change pas.
Attention, `openclaw config set` ne sait pas écrire cette clé — son parseur de
chemin coupe sur le point de `gpt-5.6`, d'où l'édition directe du JSON.

Vérifié via le pont de ClawBody, pas seulement en lisant la config :

| test | résultat | durée |
|---|---|---|
| outil `exec` | `date +%H:%M` réellement exécuté → `21:09` | 16 s |
| skill `weather` | « 26 °C, ressenti 28 °C, humidité 65 %, vent 7 km/h » | 23 s |
| mémoire | « Tu t'appelles gth » | 9 s |

> À comparer : `ollama/qwen3.6` (36 B local, 262 k de contexte) répondait aux
> mêmes questions en 7–9 s, avec des réponses plus courtes. C'est l'arbitrage
> qualité / latence — reste en tête que ces secondes sont du silence pendant
> une conversation vocale.

> Les modèles Anthropic de la liste de repli sont inutilisables pour l'instant :
> `LLM request rejected: You're out of extra usage`.

### 11. Phrase d'attente avant `ask_openclaw`

Un appel à OpenClaw prend 16 à 23 s. Pendant ce temps le robot ne dit rien —
il fait bien son animation de réflexion, mais en conversation ce silence se lit
comme un plantage.

Réglé par la consigne, pas par de la plomberie : `ROBOT_BODY_INSTRUCTIONS`
demande de prononcer une courte phrase d'attente **puis** d'appeler l'outil,
dans la même réponse, et **uniquement** pour `ask_openclaw` — les outils de
mouvement et `camera` sont instantanés et restent silencieux.

Aucun exemple de formulation n'est figé dans la consigne : le modèle varie de
lui-même et suit `SPEECH_LANGUAGE`.

Vérifié en observant l'**ordre des événements** — l'audio doit précéder
`response.function_call_arguments.done` :

```
sans consigne : tool                    (silence sec)
avec consigne : audio → tool            « Bien sûr, je regarde ça. Un instant… »
```

6 cas sur 6 conformes : les 3 requêtes OpenClaw parlent d'abord, `look` et
`camera` partent sans un mot, une blague ne déclenche aucun outil.

- `ReachyMini()` était construit sans hôte ni mode de connexion : ajout de
  `REACHY_HOST` / `REACHY_CONNECTION_MODE` / `REACHY_MEDIA_BACKEND`.
- `--gradio` ne transmettait ni `enable_face_tracking` ni `head_tracker_type` :
  `--no-face-tracking` était ignoré en mode interface.

## Ce qui a été vérifié

| | État |
|---|---|
| Import de tous les modules | ✅ |
| `clawbody --help` | ✅ |
| Passerelle OpenClaw — connexion | ✅ |
| Passerelle OpenClaw — aller-retour avec Clawson | ✅ |
| Mouvements sur le robot physique | ✅ 7/7 outils |
| Caméra (1280×720 via WebRTC) | ✅ |
| Audio (16 kHz stéréo bidirectionnel) | ✅ |
| Détection de visage YOLO | ✅ |
| Interface Gradio (`:7860`) | ✅ |
| `../.venv` intact | ✅ |
| Session Realtime GA (audio + transcription + outils) | ✅ |
| Démarrage complet de l'app sur le robot | ✅ |
| **Boucle vocale de bout en bout** — micro du robot → VAD → transcription → réponse → haut-parleur | ✅ |
| **Outil déclenché à la voix** — `camera({})` appelé pendant une conversation parlée, image analysée, réponse orale | ✅ |
| Réponses en français après `SPEECH_LANGUAGE=fr` | ✅ |
| Voix entendue, phrases complètes, sans auto-interruption | ✅ |
| Interruption à la voix pendant que le robot parle | ✅ |
| Suivi de visage à 23,5 Hz (contre 13,2 avant correctif) | ✅ |

Ne pas lancer un second client `ReachyMini` pendant que l'app tourne : les deux
se disputent le flux média WebRTC et la session Realtime se reconnecte
(elle s'en remet toute seule, mais la conversation est coupée).

## Lenteurs connues

**~26 s de démarrage.** Avant d'ouvrir la session Realtime, ClawBody appelle
`get_agent_context()`, qui est un **tour d'agent OpenClaw complet** — chez toi le
modèle primaire est `ollama/qwen3.5:2b`, d'où le délai. Le contexte renvoyé est
d'ailleurs très court (44 caractères), ce petit modèle ne suivant pas vraiment la
consigne. Deux leviers si ça gêne : viser un modèle plus costaud pour cet appel,
ou mettre en cache le contexte entre deux lancements.

**~1 s par tour de conversation** en plus, côté transport CLI (démarrage du
process `openclaw` + tour d'agent). Le modèle domine largement ce coût.

## Sécurité

`OPENAI_API_KEY` est dans `.env` (mode 600, ignoré par git). Elle a transité par
une conversation avec un assistant — si tu préfères, révoque-la et génère-en une
autre sur platform.openai.com, puis remplace la ligne dans `.env`.

L'outil `camera` utilise aussi cette clé (`gpt-4o-mini`) pour décrire ce que voit
le robot.
