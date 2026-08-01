# Rapport — réduire les temps d'attente ClawBody ↔ OpenClaw

*Mesures du 31 juillet 2026, sur cette machine (Mac Studio, robot Reachy Mini
Wireless en WebRTC, passerelle OpenClaw 2026.7.1-2, modèle `openai/gpt-5.6-sol`).*

Document local, **non commité** : il décrit l'infrastructure privée alors que le
dépôt `gth-ai/clawbody` est public.

---

## 1. Où part le temps — la chaîne complète, mesurée

Quand tu poses une question qui a besoin d'OpenClaw (« quel temps fait-il ? »,
« où est assise Diane ? ») :

```
Tu parles
  → VAD serveur détecte la fin        : 0,6 s de silence (config) + ~0,3 s
  → gpt-realtime décide + phrase
    d'attente « Je regarde ça… »      : ~1-2 s   (masque le début de l'attente)
  → ask_openclaw
      ├─ spawn CLI openclaw + WS      : ~2,2 s   (node boot, connexion, session)
      ├─ chargement de la session     : ← LE PROBLÈME (voir §2)
      ├─ tour d'agent (modèle + outils): 6-11 s  (une seule passe d'outil)
      │                                  ×N si l'agent enchaîne les outils
      └─ retour JSON
  → gpt-realtime lit le résultat
    et répond à voix haute            : ~1 s
```

### Chiffres bruts relevés

| Scénario | Temps total |
|---|---|
| Outil local (`look`, `dance`, `camera`) | **< 1 s** — jamais concerné |
| Question générale sans outil (Realtime seul) | **~1 s** |
| `ask_openclaw`, session **vierge**, gpt-5.6-sol | **8,3 s** (serveur : 6,1 s) |
| `ask_openclaw`, session `main` en début de journée | 16-23 s |
| `ask_openclaw`, session `main` en fin de journée | **70-128 s** |
| Question mariage multi-outils (session chargée) | **115 s** |
| `ollama/qwen3.6` local, chaud / froid | 7-9 s / 38 s |
| Démarrage : récupération du contexte OpenClaw | 20-26 s (plafonné à 45) |

---

## 2. Le constat central : la session partagée est le goulot

ClawBody parle à l'agent `main` sur la session `agent:main:main` — **la même
que WhatsApp et Telegram**, et celle où tous les tests d'aujourd'hui se sont
accumulés. Conséquences mesurées :

- Transcript de session : **12 Mo** (`9ce384a3….trajectory.jsonl`), 209 Mo de
  sessions au total pour l'agent `main`.
- **~104 000 tokens de contexte relus à chaque tour** (le cache OpenAI les
  absorbe côté coût, pas côté vitesse : l'attention sur 104 k ralentit chaque
  token généré).
- La passerelle déclenche des **compactions de transcript qui verrouillent la
  session** — observé : `session file locked (timeout 60000ms)`, verrou tenu
  par la passerelle elle-même. Pendant ce temps, tout tour attend.

### La preuve A/B (même modèle, même question « Réponds ok »)

| | Session `main` | Session vierge |
|---|---|---|
| Temps total | 70-128 s | **8,3 s** |
| Contexte | ~104 k tokens | 16,8 k tokens |
| Compaction/verrou | oui, 60 s+ | aucun |

**Le modèle n'est pas le problème : 6,1 s de calcul. Tout le reste est du
poids de session.** Et c'est auto-aggravant : chaque conversation du robot
alourdit la session, qui ralentit la suivante.

---

## 3. Propositions, par rapport gain/effort

### P1 — Session dédiée au robot ⭐ *(le geste qui change tout)*

`OPENCLAW_SESSION_KEY=robot` dans `clawbody/.env` (le pont supporte déjà
`--session-id`).

- **Gain : 70-128 s → ~8-10 s par requête, immédiatement et durablement** —
  la session du robot ne subit plus le poids de WhatsApp, et inversement les
  conversations vocales n'alourdissent plus ta session de messagerie.
- **Ce qui est conservé** : l'identité et la mémoire longue durée. Les fichiers
  injectés (`USER.md`, `MEMORY.md`, `SOUL.md`, `IDENTITY.md`) sont **par
  agent**, pas par session — le robot sait toujours qui tu es.
- **Ce qui est perdu** : le fil en direct des conversations WhatsApp/Telegram
  (« de quoi on parlait tout à l'heure ? » ne traversera plus les canaux).
- Effort : **1 ligne de config**. Réversible instantanément.

### P2 — Démarrage non bloquant *(à faire dans la foulée)*

Aujourd'hui `get_agent_context()` (20-26 s) s'exécute **entre** « Ready! » et le
moment où le robot entend. Or l'API Realtime accepte `session.update` en cours
de session : on peut démarrer immédiatement avec l'identité de secours, puis
injecter la personnalité OpenClaw dès qu'elle arrive.

- **Gain : le robot écoute ~25 s plus tôt.** Avec P1, la récupération du
  contexte elle-même passe sous les 10 s.
- Effort : faible (déplacer l'appel dans une tâche asyncio + un
  `session.update`).

### P3 — Outils mariage en direct dans ClawBody *(le gros gain domaine)*

Pour le mariage, la chaîne actuelle est absurde de longueur :
Realtime → CLI → passerelle → agent → gpt-5.6-sol → outil `wedding_*` → serveur
MCP → Postgres, **avec un tour de modèle complet par outil appelé** (d'où les
115 s sur une question de plan de table).

ClawBody peut parler **directement** au serveur MCP (`mcp/server.ts`), comme le
fait le plugin, et exposer `find_guest_seat`, `get_guest_profile`,
`get_seating_plan`, `list_rooms`, `get_rsvp_stats`… comme outils natifs du
modèle Realtime, à côté de `look` et `dance`.

- **Gain : questions mariage 20-115 s → ~1-3 s** (une requête SQL + la voix).
  C'est le domaine que tu interroges le plus pendant les préparatifs.
- Le refus des suppressions reste garanti : il est dans `server.ts`.
- **Coût** : ~un module Python (client MCP stdio — le protocole est simple),
  et 8 outils de plus dans la session Realtime. On garde `ask_openclaw` pour
  tout le reste.
- Effort : moyen (une demi-journée), le pattern existe déjà en TypeScript dans
  `openclaw-plugin/index.ts`.

### P4 — Hygiène de sessions *(maintenance, à faire une fois)*

- La compaction en cours sur la session de 12 Mo va se terminer, mais la
  session restera lourde. Après passage à P1, **archiver/réinitialiser**
  `agent:main:main` (`/reset` ou nouvelle session) pour redonner de l'air à
  WhatsApp aussi.
- 209 Mo de sessions accumulées : purger les anciennes ne change pas la
  latence des tours, mais évite les compactions surprises.

### P5 — Garder un cache local des questions fréquentes *(optionnel)*

ClawBody peut précharger au démarrage (et rafraîchir toutes les X minutes)
le tableau de bord mariage : totaux RSVP, occupation des salles, stats.
Les questions « combien de confirmés ? » se répondent alors **instantanément**
depuis la mémoire, sans aucun aller-retour.

- Gain : 0 s perçu sur les questions de synthèse ; risque : donnée vieille de
  quelques minutes. Pertinent surtout le jour J.
- Effort : faible une fois P3 en place (même client MCP).

### P6 — Modèle : rester sur `gpt-5.6-sol`

Une fois P1 appliqué, `gpt-5.6-sol` sur session légère (8,3 s) fait **jeu égal
avec qwen3.6 local chaud (7-9 s)** tout en répondant mieux — et sans le
démarrage à froid de 38 s d'ollama. Le routage bi-modèle envisagé n'a plus de
raison d'être. Si un jour tu repasses en local : `OLLAMA_KEEP_ALIVE=2h` pour
tuer le démarrage à froid.

### P7 — Micro-réglage VAD *(cosmétique)*

`silence_duration_ms` est à 600 ms : chaque échange attend 0,6 s après ta
dernière syllabe. 450-500 ms rend le tour de parole plus vif, au prix d'un
risque accru de te couper sur une pause. À tester à l'oreille.

---

## 4. Ce que je déconseille (évalué, écarté)

**Transport WebSocket direct vers la passerelle** (économiserait les ~2,2 s de
spawn CLI). Exige de réimplémenter en Python l'identité device Ed25519
d'OpenClaw, lue dans du code minifié, fragile à chaque mise à jour — pour un
gain marginal une fois P1-P3 en place. Le CLI est lent mais incassable.

**Streaming de la réponse OpenClaw vers la voix.** L'API Realtime consomme un
résultat d'outil (`function_call_output`) de façon atomique : il n'existe pas
de moyen propre de faire parler le modèle sur un résultat partiel. La phrase
d'attente déjà en place est la bonne réponse à ce problème.

**Compacter le prompt système de l'agent `main`** (41 skills, 43 k caractères).
Le vrai levier serait un agent dédié au robot avec 5 skills — mais avec P1+P3,
le prompt de `main` ne pèse plus que ~6 s par requête *résiduelle* ; créer et
maintenir un second agent n'est plus justifié. À reconsidérer seulement si le
8-10 s résiduel gêne encore.

---

## 5. Cibles chiffrées

| Interaction | Aujourd'hui | Après P1+P2 | Après P1-P3 |
|---|---|---|---|
| Démarrage → robot à l'écoute | ~30-50 s | **~10 s** | ~10 s |
| Mouvement, caméra, conversation simple | < 1 s | < 1 s | < 1 s |
| Question mariage (place, profil, stats) | 20-115 s | 8-12 s | **1-3 s** |
| Météo, web, agenda, mémoire (ask_openclaw) | 70-128 s* | **8-12 s** | 8-12 s |
| Stats mariage préchargées (P5) | — | — | **~0 s** |

\* état actuel dégradé par la session de 12 Mo ; c'était 16-23 s ce matin.

**Ordre recommandé : P1 (1 ligne, gain ×10) → P4 (nettoyage) → P2 (démarrage)
→ P3 (mariage) → P5/P7 si l'envie te prend.**

---

## 6. Ce qui a été implémenté — résultats mesurés

| | État | Mesure après |
|---|---|---|
| **P1** session dédiée `clawbody-robot` | ✅ | 70-128 s → **~8-12 s** |
| **P2** démarrage non bloquant | ✅ | 30-50 s → **16 s** avant écoute |
| **P3** outils MCP en direct (10 outils) | ✅ | 20-115 s → **2,2 s** |
| **P7** VAD 600 → 500 ms | ✅ | tour de parole plus vif |
| **P4** nettoyage sessions | ⏸ décision utilisateur | 209 Mo, session `main` à 12 Mo |
| **P5** préchargement | ❌ écarté | voir ci-dessous |

### Détail P3 — routage vérifié

Chaque question part vers le bon outil, sans tour d'agent :

| Question | Outil choisi | Total |
|---|---|---|
| « Où est assise Diane Donfack ? » | `wedding_find_guest_seat` | **2,2 s** |
| « Combien de places libres à … ? » | `wedding_get_seating_plan` | ~2,5 s |
| « Igor a-t-il offert un cadeau ? » | `wedding_get_guest_profile` | ~2,3 s |
| « Quel temps fait-il ? » | `ask_openclaw` *(inchangé)* | 8-12 s |
| « Regarde à gauche » | `look` *(local)* | < 1 s |

Décomposition du 2,2 s : ~1,6 s de décision du modèle + 0,6 s de requête MCP.

### Suivi QA à la voix

Ajouté ensuite : `create_issue`, `list_issues`, `update_issue_status`,
`add_issue_comment`. L'usage type est de tester le site sur son téléphone et
de dicter le bug sans lâcher l'appareil. Mesuré : **0,2 à 1,0 s** par appel.

`delete_issue` reste dehors, cohérent avec le blocage des suppressions. Le
modèle s'y adapte correctement — à « supprime l'issue sur le bouton RSVP » il
n'appelle aucun outil et propose de la fermer à la place.

Session Realtime finale : **22 outils** (7 robot + 14 mariage + `ask_openclaw`).

### P5 écarté — et pourquoi

Le préchargement devait économiser l'aller-retour données. Une fois P3 en
place, cet aller-retour coûte **0,1 à 0,6 s** : le gain serait invisible à
l'oreille, alors que le coût — servir une donnée périmée de plusieurs minutes
sur un plan de table qu'on modifie en direct — est réel. Le levier restant
n'est pas la donnée mais la décision du modèle (~1,6 s), que le
préchargement ne touche pas.

À reconsidérer seulement pour le jour J, en mode « salle bondée, réseau
saturé », où une réponse figée vaut mieux qu'une requête qui échoue.

### P4 — ce qui reste à ta main

La session `agent:main:main` fait toujours 12 Mo (209 Mo au total pour
l'agent). Depuis P1, **le robot n'y touche plus** — elle ne ralentit donc plus
que WhatsApp et Telegram. La réinitialiser leur rendrait la même vivacité,
mais c'est ton historique de conversations : je ne l'ai pas touchée.

### Fuite de processus corrigée en chemin

Le premier jet du client MCP laissait 2 processus par arrêt : `tsx` lance un
`node` enfant, et tuer le parent laisse l'enfant. C'est exactement le
mécanisme qui avait produit 557 orphelins côté pont OpenClaw. Le client place
maintenant le serveur dans son propre groupe de processus et signale le groupe
entier — vérifié : 2 processus au démarrage, **0 après arrêt**.
