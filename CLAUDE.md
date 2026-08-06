# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Lancer

```bash
./run.sh                  # mode console
./run.sh --gradio         # interface web sur http://127.0.0.1:7860
./run.sh --debug          # logs verbeux (nécessaire pour voir le barge-in et l'écho)
```

Autres drapeaux : `--no-camera`, `--no-openclaw`, `--no-face-tracking`,
`--local-vision`, `--robot-name`, `--gateway-url`, `--profile`.

Passe toujours par `run.sh`, jamais par `.venv/bin/clawbody` directement : le
script exporte `DYLD_FALLBACK_LIBRARY_PATH` vers le `libpython3.12.dylib` que
`libgstpython.dylib` cherche via `@rpath` sans le trouver. Sans ça, le plugin
GStreamer échoue et chaque lancement crache un pavé de warnings.

## Venv séparé : ne pas fusionner avec `../.venv`

ClawBody a son propre `.venv`, et c'est une contrainte, pas un choix de style :
`reachy_mini` 1.9.0 exige `pydantic >= 2.12.5`, `gradio` le plafonne à
`<= 2.12.3`. L'installer dans `../.venv` y ferait redescendre `pydantic`,
`numpy` et `gradio_client` sous le plancher du SDK, cassant `sim.sh` et
`apps/mini_attentif`.

L'écart est tranché par `overrides.txt` (`pydantic==2.12.3`), donc `pip check`
signale un conflit connu et assumé. Réinstallation complète :

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --override overrides.txt \
  -e . reachy_mini==1.9.0 ultralytics supervision reachy-mini-dances-library
```

Il n'y a pas de suite de tests ni de CI. La vérification se fait en lançant
contre le robot et en lisant `clawbody.log` (voir la section Dépannage du
README, qui donne les commandes de diagnostic et un script de mesure du micro).

## Architecture

Deux boucles asyncio tournent en parallèle dans `ClawBodyCore` (`main.py`), avec
une contrainte de temps réel qui gouverne tout le fichier :

- **`record_loop`** lit le micro et pousse vers le handler OpenAI.
- **`play_loop`** récupère la parole générée et la pousse au robot.

**Rien de bloquant ne doit entrer dans ces boucles.** Deux pièges déjà rencontrés,
tous deux corrigés, tous deux faciles à réintroduire :

1. `get_audio_sample()` descend sur `try_pull_sample(20 ms)`, qui **bloque**. Il
   tourne donc dans `asyncio.to_thread`, et il ne faut **pas** ajouter de `sleep`
   dans `record_loop` : l'attente bloquante cadence déjà la boucle, et toute
   attente supplémentaire la fait passer sous le débit du micro (une trame toutes
   les ~12 ms). L'appsink est en `drop=True`, donc le surplus est silencieusement
   jeté.
2. OpenAI génère la parole bien plus vite que le temps réel. `play_loop` plafonne
   l'avance à `SPEECH_LEAD_S` ; sans ce garde-fou, tout part d'un coup dans
   GStreamer et le robot répond avec le retard accumulé.

### Le mouvement se compose en deux couches

`MovementManager` (`moves.py`) additionne à chaque tick :

- une **pose primaire** : le geste ou la danse en cours ;
- des **offsets secondaires** : `speech_offsets` + `face_tracking_offsets` +
  `thinking_offsets`, sommés terme à terme sur les 6 DOF.

Le suivi de visage n'écrase donc jamais un geste, il s'y superpose. Les offsets
de suivi sont produits par le thread de `CameraWorker` et lus sous verrou.

### Deux chemins vers l'intelligence, à ne pas confondre

- **`OpenClawBridge`** (`openclaw_bridge.py`) parle à l'agent OpenClaw, par CLI
  (défaut, via `openclaw agent`) ou par WebSocket. Un appel est un **tour d'agent
  complet** : compter des dizaines de secondes. C'est pourquoi
  `get_agent_context()` tourne en arrière-plan pendant que le robot écoute déjà,
  et non avant l'ouverture de la session.
- **`McpStdioClient`** (`mcp_client.py`) expose les outils d'un serveur MCP
  externe *directement* dans la session Realtime, préfixés par `MCP_TOOL_PREFIX`.
  Ces appels-là sont rapides et n'impliquent pas OpenClaw. Le serveur doit être
  démarré (`start_mcp()`) **avant** la construction de la session, puisque ses
  outils y sont annoncés.

Les outils du robot lui-même (`tools/core_tools.py`) sont exécutés localement,
sans aller-retour réseau. `ToolDependencies` est le sac de dépendances passé aux
implémentations.

### Suppression d'écho

Haut-parleur et micro partagent un petit corps sans annulation d'écho matérielle :
le robot s'entend parler, le VAD serveur croit à une interruption et coupe la
réponse. `_should_drop_mic` compare donc chaque trame à un niveau d'écho appris
pendant que le robot parle, plutôt que de couper le micro (ce qui interdirait
toute interruption). La comptabilité repose sur `_speaker_busy_until`, alimenté
par `note_speaker_audio()` : l'instant où l'audio est *poussé* ne dit rien de
quand le robot se tait, seule la durée cumulée le dit.

## État de l'interface

`ui_state.STATE` (`ui_state.py`) est la source de vérité de l'UI Gradio. Principe
à respecter : **les pastilles doivent refléter ce qui est mesuré maintenant**, pas
ce qui s'est connecté au dernier lancement. Le robot est sondé via
`/api/daemon/status` et non par un test TCP, car le port 8000 répond même quand le
backend est arrêté. Ce qui n'existe qu'à l'intérieur d'une conversation (realtime,
mcp, caméra, suivi) passe en gris neutre à l'arrêt, jamais en rouge : ce n'est pas
en panne, c'est sans objet.

## Réglages qui comptent

Tout se règle par `.env` (voir `.env.example`) :

| Variable | Effet |
|---|---|
| `VAD_SILENCE_MS` | silence avant que le serveur te considère comme ayant fini. Principal poste du délai de réponse. |
| `SPEECH_LEAD_S` | avance maximale entre ce qui est remis au robot et ce qu'il a fini de dire. |
| `MIC_ECHO_RATIO`, `MIC_MIN_RMS` | seuils de détection d'une interruption face à l'écho. |
| `MCP_SERVER_CMD` | vide désactive tout le volet MCP. |
| `OPENCLAW_SESSION_KEY` | `main` partage le contexte avec les autres canaux OpenClaw. |

## À savoir

- `INSTALL-LOCAL.md` documente onze correctifs appliqués au code upstream (API
  Realtime Beta supprimée côté serveur, protocole de la passerelle, API MediaPipe
  disparue…). À lire avant de conclure qu'un comportement est un bug local.
- Le fork vise le **robot en réseau** (`reachy-mini.local`), donc le backend média
  est WebRTC. `No Reachy Mini Audio USB device found` est normal dans ce mode.
- ClawBody lance un serveur MCP par conversation. En cas d'arrêt brutal ils
  survivent au processus : vérifier `pgrep -f "mcp/server.ts" | wc -l` (95
  orphelins relevés une fois). `SIGINT` ne suffit pas toujours à arrêter
  ClawBody, prévoir `SIGTERM`.
