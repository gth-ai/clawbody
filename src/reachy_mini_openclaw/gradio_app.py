"""Interface web de ClawBody.

Refonte : la version précédente affichait un transcript jamais alimenté et un
onglet Personnalité qui ne touchait rien — `get_session_instructions()`, seul
lecteur de `CUSTOM_PROFILE`, n'était appelé nulle part dans le flux réel. Un
écran qui ment coûte plus cher qu'un écran absent.

Principe de la refonte : tout ce qui est affiché vient de `ui_state.STATE`,
alimenté par le thread de conversation. Rien n'est décoratif — si une valeur
apparaît, c'est qu'elle est mesurée.
"""

import logging
import os
import threading
from typing import Optional

import gradio as gr

from reachy_mini_openclaw import ui_state

logger = logging.getLogger(__name__)

# Fréquences de rafraîchissement. L'état est bon marché à lire (un verrou et
# quelques champs) ; la caméra l'est moins, on l'espace.
STATE_REFRESH_S = 0.5
CAMERA_REFRESH_S = 0.2

PHASE_LABELS = {
    ui_state.PHASE_IDLE: ("💤", "Au repos"),
    ui_state.PHASE_LISTENING: ("🎤", "Il t'écoute"),
    ui_state.PHASE_THINKING: ("🧠", "Réfléchit"),
    ui_state.PHASE_SPEAKING: ("🗣️", "Il parle"),
}

CSS = """
.phase-strip { font-size: 1.35rem; font-weight: 600; padding: 0.6rem 0.9rem;
  border-radius: 10px; background: var(--block-background-fill);
  border: 1px solid var(--border-color-primary); }
.health-strip { font-family: var(--font-mono); font-size: 0.9rem; opacity: 0.9; }
footer { display: none !important; }
"""


def launch_gradio(
    gateway_url: str = "ws://localhost:18789",
    robot_name: Optional[str] = None,
    enable_camera: bool = True,
    enable_openclaw: bool = True,
    enable_face_tracking: bool = True,
    head_tracker_type: Optional[str] = None,
    share: bool = False,
) -> None:
    """Lance l'interface web.

    Args:
        gateway_url: URL de la passerelle OpenClaw
        robot_name: Nom du robot pour la connexion
        enable_camera: Activer la caméra
        enable_openclaw: Activer l'intégration OpenClaw
        enable_face_tracking: Activer le suivi de visage
        head_tracker_type: Type de tracker ('yolo', 'mediapipe' ou None)
        share: Créer une URL publique
    """
    from reachy_mini_openclaw.config import config, set_custom_profile
    from reachy_mini_openclaw.prompts import get_available_profiles, save_custom_profile

    state = ui_state.STATE
    app = {"instance": None}

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start_conversation():
        from reachy_mini_openclaw.main import ClawBodyCore

        if app["instance"] is not None:
            return (*_controls(running=True), "Déjà en cours.")

        state.reset()
        state.set_error(None)
        try:
            instance = ClawBodyCore(
                gateway_url=gateway_url,
                robot_name=robot_name,
                enable_camera=enable_camera,
                enable_openclaw=enable_openclaw,
                enable_face_tracking=enable_face_tracking,
                head_tracker_type=head_tracker_type,
            )
        except Exception as e:
            # Remonté à l'écran plutôt que laissé dans les logs : c'est ici que
            # l'ancienne UI affichait « Started successfully » alors que rien
            # ne tournait.
            state.set_error(str(e))
            return (*_controls(running=False), f"❌ Démarrage impossible : {e}")

        app["instance"] = instance

        def run_app():
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(instance.run())
            except Exception as e:
                logger.error("App error: %s", e, exc_info=True)
                state.set_error(f"La conversation s'est arrêtée : {e}")
            finally:
                # Sans ça, l'ancienne UI restait bloquée sur « Already
                # running » après un plantage de fond, sans issue.
                state.set_running(False)
                app["instance"] = None
                loop.close()

        threading.Thread(target=run_app, daemon=True).start()
        return (*_controls(running=True), "Démarrage… le robot écoutera dans ~15 s.")

    def stop_conversation():
        instance = app["instance"]
        if instance is None:
            return (*_controls(running=False), "Rien à arrêter.")
        try:
            instance.stop()
        except Exception as e:
            logger.error("Stop error: %s", e)
        app["instance"] = None
        state.set_running(False)
        return (*_controls(running=False), "Arrêté.")

    def _controls(running: bool):
        return gr.update(interactive=not running), gr.update(interactive=running)

    # ------------------------------------------------------------------
    # Rafraîchissement
    # ------------------------------------------------------------------

    def refresh():
        phase, detail, since = state.phase()
        running, uptime = state.running()
        h = state.health()
        err = state.error()

        icon, label = PHASE_LABELS.get(phase, ("•", phase))
        if detail:
            label = f"{label} — {detail}"
        if phase != ui_state.PHASE_IDLE and since > 1:
            label = f"{label} ({since:.0f} s)"
        if not running:
            icon, label = ("⏸️", "Arrêté" if not err else "Arrêté sur erreur")
        strip = f"<div class='phase-strip'>{icon} {label}</div>"

        def dot(ok: bool) -> str:
            return "🟢" if ok else "⚪"

        health = (
            f"{dot(h.robot)} robot &nbsp; {dot(h.openclaw)} openclaw &nbsp; "
            f"{dot(h.realtime)} realtime &nbsp; "
            f"{dot(h.mcp_tools > 0)} mcp ({h.mcp_tools}) &nbsp; "
            f"{dot(h.camera)} caméra &nbsp; "
            f"{dot(h.tracking_hz > 0)} suivi {h.tracking_hz:.0f} Hz"
        )
        if running and uptime > 0:
            health += f" &nbsp;·&nbsp; {int(uptime // 60)} min {int(uptime % 60):02d} s"
        health = f"<div class='health-strip'>{health}</div>"

        msgs, _ = state.turns()
        # Toujours renvoyer le fil complet. Une déduplication par compteur
        # paraissait moins coûteuse, mais le compteur vit dans la closure et
        # serait donc partagé par tous les clients : deux onglets ouverts se
        # voleraient leurs mises à jour, et le second n'afficherait jamais rien.
        chat = gr.update(value=msgs)

        err_box = gr.update(value=err or "", visible=bool(err))
        return strip, health, chat, err_box

    def refresh_camera():
        instance = app["instance"]
        worker = getattr(instance, "camera_worker", None) if instance else None
        if worker is None:
            return gr.update()
        frame = worker.get_latest_frame()
        if frame is None:
            return gr.update()
        return gr.update(value=frame[:, :, ::-1])  # BGR -> RGB

    # ------------------------------------------------------------------
    # Personnalité
    # ------------------------------------------------------------------

    def apply_profile(profile_name: str):
        """Applique un profil, à chaud si une conversation tourne.

        L'ancienne version se contentait de poser une variable que plus rien
        ne lisait. On la pose toujours — pour la prochaine session — mais on
        pousse surtout un `session.update` dans la session en cours, comme le
        fait déjà la personnalité OpenClaw récupérée en arrière-plan.
        """
        name = (profile_name or "").strip()
        set_custom_profile(name or None)

        instance = app["instance"]
        loop = getattr(instance, "_loop", None) if instance else None
        handler = getattr(instance, "handler", None) if instance else None
        conn = getattr(handler, "connection", None) if handler else None

        if not (loop and handler and conn):
            return f"Profil « {name or 'défaut'} » retenu — actif au prochain démarrage."

        try:
            from reachy_mini_openclaw.prompts import get_session_instructions
            import asyncio

            instructions = handler._compose_instructions(get_session_instructions())
            fut = asyncio.run_coroutine_threadsafe(
                conn.session.update(
                    session={"type": "realtime", "instructions": instructions}
                ),
                loop,
            )
            fut.result(timeout=10)
            return f"✅ Profil « {name or 'défaut'} » appliqué immédiatement."
        except Exception as e:
            logger.error("Apply profile failed: %s", e)
            return f"Profil retenu, mais non appliqué à chaud : {e}"

    def save_profile(name: str, instructions: str):
        if not (name or "").strip():
            return "Donne un nom au profil."
        if not (instructions or "").strip():
            return "Les instructions sont vides."
        if save_custom_profile(name, instructions):
            return f"✅ Profil « {name} » enregistré. Recharge la liste pour le voir."
        return "❌ Échec de l'enregistrement."

    def reload_profiles():
        return gr.update(choices=[""] + get_available_profiles())

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    with gr.Blocks(title="ClawBody", css=CSS, theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🦞🤖 ClawBody")

        phase_strip = gr.HTML("<div class='phase-strip'>⏸️ Arrêté</div>")
        health_strip = gr.HTML("")
        error_box = gr.Textbox(
            label="Erreur", interactive=False, visible=False, lines=2
        )

        with gr.Row():
            start_btn = gr.Button("▶️ Démarrer", variant="primary", scale=1)
            stop_btn = gr.Button("⏹️ Arrêter", variant="stop", scale=1, interactive=False)
        status_text = gr.Textbox(label="", interactive=False, show_label=False)

        with gr.Tab("Conversation"):
            with gr.Row():
                with gr.Column(scale=3):
                    chat = gr.Chatbot(
                        label="Fil de conversation",
                        height=460,
                        type="messages",
                        show_copy_button=True,
                    )
                with gr.Column(scale=2):
                    camera = gr.Image(
                        label="Ce que voit le robot",
                        height=300,
                        show_download_button=False,
                        interactive=False,
                    )
                    gr.Markdown(
                        "Le robot te suit du regard quand il te détecte.\n\n"
                        "**Parle-lui simplement** — il choisit seul entre bouger, "
                        "consulter les données du mariage (instantané) ou "
                        "interroger OpenClaw (~10 s, il te prévient à voix haute)."
                    )

        with gr.Tab("Personnalité"):
            gr.Markdown(
                "Un profil remplace l'identité que le robot adopte. "
                "S'il est en train de tourner, le changement prend effet "
                "**immédiatement**, sans redémarrage."
            )
            with gr.Row():
                profile_dropdown = gr.Dropdown(
                    choices=[""] + get_available_profiles(),
                    label="Profil",
                    value="",
                    scale=3,
                )
                reload_btn = gr.Button("🔄", scale=0, min_width=50)
            apply_btn = gr.Button("Appliquer", variant="primary")
            profile_status = gr.Textbox(label="", interactive=False, show_label=False)

            gr.Markdown("### Créer un profil")
            new_name = gr.Textbox(label="Nom", placeholder="ex. guide-mariage")
            new_instructions = gr.Textbox(
                label="Instructions",
                lines=8,
                placeholder="Tu es… Décris l'identité et le ton à adopter.",
            )
            save_btn = gr.Button("Enregistrer")
            save_status = gr.Textbox(label="", interactive=False, show_label=False)

        with gr.Tab("Configuration"):
            mcp_line = (
                f"- **Serveur MCP direct** : `{config.MCP_SERVER_CMD} "
                f"{config.MCP_SERVER_ARGS}` — {len(config.MCP_TOOLS.split(','))} outils"
                if config.MCP_SERVER_CMD
                else "- **Serveur MCP direct** : désactivé"
            )
            gr.Markdown(
                f"""### Réglages en vigueur

- **Passerelle OpenClaw** : `{gateway_url}`
- **Session OpenClaw** : `{config.OPENCLAW_SESSION_KEY}`
- **Modèle OpenClaw** : `{config.OPENCLAW_MODEL or "défaut de l'agent"}`
- **Modèle Realtime** : `{config.OPENAI_MODEL}` · voix `{config.OPENAI_VOICE}`
- **Langue** : `{config.SPEECH_LANGUAGE or "libre"}`
- **Robot** : `{config.REACHY_HOST}` (mode `{config.REACHY_CONNECTION_MODE}`)
- **Suivi de visage** : {enable_face_tracking} · `{head_tracker_type or config.HEAD_TRACKER_TYPE}`
  sur `{config.VISION_DEVICE}` à {config.FACE_TRACKING_HZ:.0f} Hz
- **Silence de fin de tour (VAD)** : {config.VAD_SILENCE_MS} ms
{mcp_line}

Ces valeurs viennent de `.env` — modifie-le puis redémarre.
"""
            )

        # Câblage
        start_btn.click(
            start_conversation, outputs=[start_btn, stop_btn, status_text]
        )
        stop_btn.click(stop_conversation, outputs=[start_btn, stop_btn, status_text])
        apply_btn.click(apply_profile, inputs=[profile_dropdown], outputs=[profile_status])
        reload_btn.click(reload_profiles, outputs=[profile_dropdown])
        save_btn.click(
            save_profile, inputs=[new_name, new_instructions], outputs=[save_status]
        )

        gr.Timer(STATE_REFRESH_S).tick(
            refresh, outputs=[phase_strip, health_strip, chat, error_box]
        )
        if enable_camera:
            gr.Timer(CAMERA_REFRESH_S).tick(refresh_camera, outputs=[camera])

    # 127.0.0.1 par défaut : l'ancienne version écoutait sur 0.0.0.0 sans
    # authentification, donc n'importe qui sur le réseau pouvait démarrer le
    # robot. Mets CLAWBODY_UI_HOST=0.0.0.0 pour l'ouvrir sciemment.
    host = os.getenv("CLAWBODY_UI_HOST", "127.0.0.1")
    port = int(os.getenv("CLAWBODY_UI_PORT", "7860"))
    if host != "127.0.0.1":
        logger.warning(
            "Interface exposée sur %s sans authentification — réseau de confiance uniquement.",
            host,
        )
    demo.launch(share=share, server_name=host, server_port=port)
