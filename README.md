---
title: ClawBody
emoji: 🦞
colorFrom: red
colorTo: purple
sdk: static
pinned: false
short_description: OpenClaw AI with robot body and face tracking
tags:
 - reachy_mini
 - reachy_mini_python_app
 - openclaw
 - clawson
 - embodied-ai
 - ai-assistant
 - voice-assistant
 - robotics
 - openai-realtime
 - conversational-ai
 - physical-ai
 - robot-body
 - speech-to-speech
 - multimodal
 - vision
 - expressive-robot
 - simulation
 - mujoco
 - face-tracking
 - face-detection
 - eye-contact
 - human-robot-interaction
---

# 🦞🤖 ClawBody

> **Fork de [tomrikert/clawbody](https://github.com/tomrikert/clawbody).**
> Copie indépendante, avec son propre historique git — elle ne pointe plus vers
> le dépôt d'origine. Tout le crédit du projet initial revient à son auteur.
>
> Ce fork existe parce que la version upstream ne démarre plus en l'état :
> l'API Realtime **Beta** d'OpenAI est coupée côté serveur, l'outil `dance`
> n'a jamais dansé (il importait un symbole inexistant, l'erreur était avalée),
> et `vision/mediapipe_tracker.py` ne peut plus se charger depuis que
> mediapipe a retiré `mp.solutions`.
>
> Les correctifs, les mesures qui les justifient et les pièges rencontrés sont
> documentés dans **[`INSTALL-LOCAL.md`](INSTALL-LOCAL.md)**.

**Give your OpenClaw AI agent a physical robot body!**

ClawBody combines OpenClaw's AI intelligence with Reachy Mini's expressive robot body, using OpenAI's Realtime API for ultra-responsive voice conversation. Your OpenClaw assistant (Clawson) can now see, hear, speak, and move in the physical world.

![Reachy Mini Dance](https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app/resolve/main/docs/assets/reachy_mini_dance.gif)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## 👁️ NEW: Face Tracking & Eye Contact

**The robot looks at you when you speak!**

ClawBody now includes real-time face tracking that makes conversations feel natural and engaging:

- **Automatic Face Detection**: Uses MediaPipe or YOLO to detect faces at 25Hz
- **Smooth Head Tracking**: Robot smoothly follows your face as you move
- **Natural Eye Contact**: Maintains engagement during conversation
- **Graceful Fallback**: Smoothly returns to neutral position when you leave

```bash
# Face tracking is enabled by default
clawbody

# Choose your tracker (MediaPipe is lighter, YOLO is more accurate)
clawbody --head-tracker mediapipe
clawbody --head-tracker yolo

# Disable if needed
clawbody --no-face-tracking
```

---

## 🎮 No Robot? No Problem!

**You don't need a physical Reachy Mini robot to use ClawBody!**

ClawBody works with the [Reachy Mini Simulator](https://huggingface.co/docs/reachy_mini/platforms/simulation/get_started), a MuJoCo-based physics simulation that runs on your computer. Watch Clawson move and express emotions on screen while you talk to your OpenClaw agent.

```bash
# Install simulator support
pip install "reachy-mini[mujoco]"

# Start the simulator (opens a 3D window)
reachy-mini-daemon --sim

# In another terminal, run ClawBody
clawbody --gradio
```

> 🍎 **Mac Users**: Use `mjpython -m reachy_mini.daemon.app.main --sim` instead.

---

## ✨ Features

- **👁️ Face Tracking**: Robot tracks your face and maintains eye contact during conversation
- **🎤 Real-time Voice Conversation**: OpenAI Realtime API for sub-second response latency
- **🧠 OpenClaw Intelligence**: Your responses come from OpenClaw with full tool access
- **👀 Vision**: See through the robot's camera and describe the environment
- **💃 Expressive Movements**: Natural head movements, emotions, dances, and audio-driven wobble
- **🦞 Clawson Embodied**: Your friendly space lobster AI assistant, now with a body!
- **🖥️ Simulator Support**: Works with or without physical hardware

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Your Voice / Microphone                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Reachy Mini Robot (or Simulator)                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Microphone  │  │   Camera    │  │   Movement System       │  │
│  │  (input)    │  │  (vision)   │  │ (head, antennas, body)  │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────▲────────────┘  │
└─────────┼────────────────┼──────────────────────┼───────────────┘
          │                │                      │
          ▼                ▼                      │
┌─────────────────────────────────────────────────┼───────────────┐
│                      ClawBody                   │               │
│  ┌─────────────────────────────────────────────┼────────────┐  │
│  │         OpenAI Realtime API Handler         │            │  │
│  │  • Speech recognition (Whisper)             │            │  │
│  │  • Text-to-speech (voices)                 ─┘            │  │
│  │  • Audio analysis → head wobble                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              OpenClaw Gateway Bridge                     │  │
│  │  • AI responses from Clawson                            │  │
│  │  • Full OpenClaw tool access                            │  │
│  │  • Conversation memory & context                        │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway                              │
│  • Web browsing  • Calendar  • Smart home  • Memory  • Tools    │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 Prerequisites

### Option A: With Physical Robot
- [Reachy Mini](https://www.pollen-robotics.com/reachy-mini/) robot (Wireless or Lite)

### Option B: With Simulator (No Hardware Required!)
- Any computer with Python 3.11+
- Install: `pip install "reachy-mini[mujoco]"`
- [Simulation Setup Guide](https://huggingface.co/docs/reachy_mini/platforms/simulation/get_started)

### Software (Both Options)
- Python 3.11+
- [Reachy Mini SDK](https://github.com/pollen-robotics/reachy_mini) installed
- [OpenClaw](https://github.com/openclaw/openclaw) gateway running
- OpenAI API key with Realtime API access

## 🚀 Installation

### Quick Start with Simulator

```bash
# Clone ClawBody
git clone https://github.com/tomrikert/clawbody
cd clawbody

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install ClawBody + simulator support + face tracking
pip install -e ".[mediapipe_vision]"
pip install "reachy-mini[mujoco]"

# Or for more accurate face tracking (requires more resources)
# pip install -e ".[yolo_vision]"

# Configure (see Configuration section)
cp .env.example .env
# Edit .env with your keys

# Terminal 1: Start the simulator
reachy-mini-daemon --sim

# Terminal 2: Run ClawBody
clawbody --gradio
```

### On a Physical Reachy Mini Robot

```bash
# SSH into the robot
ssh pollen@reachy-mini.local

# Clone the repository
git clone https://github.com/tomrikert/clawbody
cd clawbody

# Install in the apps virtual environment
/venvs/apps_venv/bin/pip install -e .
```

## ⚙️ Configuration

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` with your configuration:

```bash
# Required
OPENAI_API_KEY=sk-...your-key...

# OpenClaw Gateway (required for AI responses)
OPENCLAW_GATEWAY_URL=http://localhost:18789  # or your host IP
OPENCLAW_TOKEN=your-gateway-token
OPENCLAW_AGENT_ID=main

# Optional - Customize voice
OPENAI_VOICE=cedar

# Optional - Face tracking (enabled by default)
ENABLE_FACE_TRACKING=true
HEAD_TRACKER_TYPE=mediapipe  # or "yolo" for more accuracy
```

## 🎮 Usage

### With Simulator

```bash
# Terminal 1: Start simulator
reachy-mini-daemon --sim

# Terminal 2: Run ClawBody with web UI (recommended for simulator)
clawbody --gradio
```

The simulator opens a 3D window where you can watch the robot move. The Gradio web UI at http://localhost:7860 lets you interact via your browser's microphone.

### With Physical Robot

```bash
# Basic usage
clawbody

# With debug logging
clawbody --debug

# With specific robot
clawbody --robot-name my-reachy
```

### CLI Options

| Option | Description |
|--------|-------------|
| `--debug` | Enable debug logging |
| `--gradio` | Launch web UI instead of console mode |
| `--robot-name NAME` | Specify robot name for connection |
| `--gateway-url URL` | OpenClaw gateway URL |
| `--no-camera` | Disable camera functionality |
| `--no-openclaw` | Disable OpenClaw integration |
| `--head-tracker TYPE` | Face tracker: `mediapipe` (lighter) or `yolo` (more accurate) |
| `--no-face-tracking` | Disable face tracking |

## 🛠️ Robot Capabilities

ClawBody gives Clawson these physical abilities:

| Capability | Description |
|------------|-------------|
| **Face Tracking** | Automatically tracks and looks at people during conversation |
| **Look** | Move head to look in directions (left, right, up, down) |
| **See** | Capture images through the robot's camera |
| **Dance** | Perform expressive dance animations |
| **Emotions** | Express emotions through movement (happy, curious, thinking, etc.) |
| **Speak** | Voice output through the robot's speaker |
| **Listen** | Hear through the robot's microphone |

## 🖥️ Simulator Features

When running with the simulator:

- **3D Visualization**: Watch Clawson's movements in real-time
- **Scene Options**: Use `--scene minimal` to add objects (apple, duck, croissant)
- **Full SDK Compatibility**: The simulator behaves exactly like a real robot
- **Dashboard Access**: Visit http://localhost:8000 to see the robot dashboard

```bash
# Start simulator with objects on a table
reachy-mini-daemon --sim --scene minimal
```

## 🩺 Dépannage

### Le robot ne réagit pas à la voix

Vérifie d'abord ce que le journal montre, il départage les deux causes
possibles :

```bash
grep -E "User:|Réponse en|Audio out" clawbody.log
```

- **Aucune ligne `User:`** : la parole n'atteint pas OpenAI. Mesure le micro
  indépendamment (voir ci-dessous) ; s'il capte, c'est la boucle audio qui
  perd des trames.
- **Des lignes `User:` mais aucune `Audio out`** : la voix passe, c'est la
  réponse qui ne sort pas. Regarde les `Session error` juste avant.

Pour mesurer le micro sans OpenAI ni suivi de visage :

```python
import time, numpy as np
from reachy_mini import ReachyMini

with ReachyMini(host="reachy-mini.local") as m:
    sr = m.media.get_input_audio_samplerate()
    m.media.start_recording(); time.sleep(1)
    t0, n, rms = time.monotonic(), 0, 0.0
    while time.monotonic() - t0 < 10:      # parle pendant ce temps
        a = m.media.get_audio_sample()
        if a is not None:
            n += len(a)
            rms = max(rms, float(np.sqrt(np.mean(np.square(a)))))
    d = time.monotonic() - t0
    print(f"ratio={n/sr/d:.2f} (attendu ~1.0)  RMS_max={rms:.3f}")
```

Deux repères : le **ratio** doit valoir ~1,0 (nettement en dessous, des
trames sont jetées) et le **RMS** doit dépasser `MIC_MIN_RMS` (0,02 par
défaut) quand tu parles.

> **Ne mets jamais de `sleep` dans la boucle de lecture du micro.**
> `get_audio_sample()` descend sur `try_pull_sample(20 ms)`, qui attend déjà
> une trame et cadence donc la boucle à lui seul. Toute attente ajoutée
> passe sous le débit du micro (une trame toutes les ~12 ms) et l'appsink,
> réglé en `drop=True`, jette le surplus. Mesuré sur le robot : un
> `sleep(0.01)` faisait tomber le ratio à 0,83, soit 17 % de la voix perdue
> avant même le réseau. Assez pour que le VAD serveur n'y reconnaisse plus
> de parole, alors que le micro capte parfaitement.

### Les réponses sont lentes

Chaque tour de parole journalise son délai réel :

```
Réponse en 0.64 s (silence → premier son)
```

Ce délai inclut `VAD_SILENCE_MS` (500 ms par défaut), soit le temps que le
serveur attend avant de te considérer comme ayant fini. Une valeur autour de
0,6 à 0,9 s est normale. Pour gagner ~200 ms, au prix de coupures si tu
marques des pauses au milieu de tes phrases :

```bash
VAD_SILENCE_MS=300
```

Si le délai dépasse plusieurs secondes, cherche plutôt du côté de la charge
machine (voir ci-dessous).

### Le robot répond à ce que tu disais il y a vingt secondes

Symptôme différent du précédent : la première syllabe arrive vite, mais le
contenu est en retard d'un ou plusieurs tours de parole.

OpenAI génère la parole beaucoup plus vite que le temps réel (26 s d'audio
reçues en 9 s, mesuré ici) et `push_audio_sample()` ne bloque pas. Tout
partait donc d'un coup dans la file GStreamer, que le robot jouait ensuite à
vitesse normale : le retard s'accumulait d'un tour à l'autre, jusqu'à 21 s.

`play_loop` plafonne maintenant cette avance à `SPEECH_LEAD_S` (1,5 s par
défaut). Pour diagnostiquer, compare le temps réel écoulé aux secondes
d'audio poussées :

```bash
grep "Audio out:" clawbody.log | tail -20
```

Si le cumul progresse nettement plus vite que l'horloge, le retard se
reconstitue et `SPEECH_LEAD_S` mérite d'être baissé. Attention : une valeur
trop basse laisse moins de marge aux à-coups réseau, le robot ayant moins
d'avance devant lui.

Ce même emballement expliquait les `keepalive ping timeout` : pendant les
rafales, la tâche keepalive du WebSocket ne reprenait pas la main avant les
20 s de `ping_timeout`.

### `Session error: WebSocket connection closed with unsent messages`

Arrive quand tu coupes la parole au robot. ClawBody envoie désormais
`response.cancel` au serveur, qui cesse de produire de l'audio dont plus
personne ne veut. La reconnexion automatique existe de toute façon (~2 s),
donc une occurrence isolée reste sans conséquence.

### Lenteur générale, ventilateurs, machine chargée

ClawBody lance un serveur MCP par conversation. En cas d'arrêt brutal, ces
serveurs survivent au processus. Pour vérifier :

```bash
pgrep -f "mcp/server.ts" | wc -l     # devrait être 0 à l'arrêt
pgrep -lf "bin/clawbody"             # une seule instance attendue
```

Constaté en pratique : 95 serveurs orphelins et une instance ClawBody
oubliée depuis trois jours (3,8 Go, 113 % de CPU en continu). Pour nettoyer :

```bash
pkill -f "bin/clawbody"; sleep 3; pkill -9 -f "mcp/server.ts"
```

Note que `SIGINT` ne suffit pas toujours à arrêter ClawBody : prévois un
`SIGTERM` en second recours.

### Messages normaux au démarrage

Ceux-ci sont attendus et sans conséquence :

- `No Reachy Mini Audio USB device found` : pas de carte son USB, bascule
  sur l'audio système
- `Class AVFFrameReceiver is implemented in both...` : `av` et `cv2`
  embarquent chacun leur `libavdevice`
- `OpenClaw context fetch timed out after 45s` : la récupération de la
  personnalité est un tour d'agent complet (30 à 45 s). Elle tourne en
  arrière-plan, le robot écoute pendant ce temps ; en cas d'échec il garde
  son identité par défaut. Augmente `OPENCLAW_CONTEXT_TIMEOUT` si besoin.

## 📄 License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

ClawBody builds on:

- [Pollen Robotics](https://www.pollen-robotics.com/) - Reachy Mini robot, SDK, and simulator
- [OpenClaw](https://github.com/openclaw/openclaw) - AI assistant framework (Clawson!)
- [OpenAI](https://openai.com/) - Realtime API for voice I/O
- [MuJoCo](https://mujoco.org/) - Physics simulation engine
- [pollen-robotics/reachy_mini_conversation_app](https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app) - Movement and audio systems

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

- **This project**: [GitHub Issues](https://github.com/tomrikert/clawbody/issues)
- **OpenClaw Skills**: Submit ClawBody as a skill to [ClawHub](https://docs.openclaw.ai/tools/clawhub)
- **Reachy Mini Apps**: Submit to [Pollen Robotics](https://github.com/pollen-robotics)
