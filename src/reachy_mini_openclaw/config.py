"""Configuration management for Reachy Mini OpenClaw.

Handles environment variables and configuration settings for the application.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")


@dataclass
class Config:
    """Application configuration loaded from environment variables."""
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    OPENAI_MODEL: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-realtime-1.5"))
    OPENAI_VOICE: str = field(default_factory=lambda: os.getenv("OPENAI_VOICE", "cedar"))
    # Silence (ms) the server waits for before deciding your turn ended.
    # Lower feels snappier; too low and it cuts you off on a pause.
    VAD_SILENCE_MS: int = field(
        default_factory=lambda: int(os.getenv("VAD_SILENCE_MS", "500"))
    )
    # ISO-639-1 code ("fr", "en", …), or empty to let the model decide.
    # Worth setting: the agent context that seeds the session comes from
    # OpenClaw and may be short or in another language, in which case the
    # Realtime model picks a reply language essentially at random. This also
    # improves transcription accuracy and latency.
    SPEECH_LANGUAGE: str = field(default_factory=lambda: os.getenv("SPEECH_LANGUAGE", ""))
    
    # OpenClaw Gateway Configuration
    # "cli" shells out to the `openclaw agent` command, which carries the
    # paired device identity the gateway requires for operator scopes.
    # "ws" speaks the gateway WebSocket directly — lower latency, but only
    # usable where this client itself is a paired device.
    OPENCLAW_TRANSPORT: str = field(default_factory=lambda: os.getenv("OPENCLAW_TRANSPORT", "cli"))
    OPENCLAW_CLI: str = field(default_factory=lambda: os.getenv("OPENCLAW_CLI", "openclaw"))
    # Model for the robot's OpenClaw queries only; empty keeps the agent's own
    # default. Worth setting: the robot's questions arrive on top of a system
    # prompt carrying every skill, tool and workspace file, so a small-context
    # model overflows before it can answer anything.
    OPENCLAW_MODEL: str = field(default_factory=lambda: os.getenv("OPENCLAW_MODEL", ""))
    # Seconds to wait for the OpenClaw personality/context fetch at startup
    # before falling back to the built-in identity. It is a full agent turn,
    # so it is only as fast as the model that agent runs.
    OPENCLAW_CONTEXT_TIMEOUT: int = field(
        default_factory=lambda: int(os.getenv("OPENCLAW_CONTEXT_TIMEOUT", "45"))
    )
    OPENCLAW_GATEWAY_URL: str = field(default_factory=lambda: os.getenv("OPENCLAW_GATEWAY_URL", "ws://localhost:18789"))
    OPENCLAW_TOKEN: Optional[str] = field(default_factory=lambda: os.getenv("OPENCLAW_TOKEN"))
    OPENCLAW_AGENT_ID: str = field(default_factory=lambda: os.getenv("OPENCLAW_AGENT_ID", "main"))
    # Session key for OpenClaw - uses "main" to share context with WhatsApp and other channels
    # Format: agent:<agent_id>:<session_key>, but we only need the session key part here
    OPENCLAW_SESSION_KEY: str = field(default_factory=lambda: os.getenv("OPENCLAW_SESSION_KEY", "main"))
    
    # ── Direct MCP server (optional) ──
    # Lets the robot query a domain MCP server itself instead of routing the
    # question through an OpenClaw agent turn. The agent round trip exists to
    # *choose* a tool; the Realtime model already chose it, so that trip is
    # pure latency — measured 1-3 s here against 20-115 s through OpenClaw.
    # Empty MCP_SERVER_CMD disables the whole feature.
    MCP_SERVER_CMD: str = field(default_factory=lambda: os.getenv("MCP_SERVER_CMD", ""))
    MCP_SERVER_ARGS: str = field(default_factory=lambda: os.getenv("MCP_SERVER_ARGS", ""))
    MCP_SERVER_CWD: str = field(default_factory=lambda: os.getenv("MCP_SERVER_CWD", ""))
    # .env file to hand to the MCP server (its DATABASE_URL and friends).
    MCP_SERVER_ENV_FILE: str = field(default_factory=lambda: os.getenv("MCP_SERVER_ENV_FILE", ""))
    # Prefix keeps these apart from the robot's own tools in the session.
    MCP_TOOL_PREFIX: str = field(default_factory=lambda: os.getenv("MCP_TOOL_PREFIX", "wedding_"))
    # Comma-separated allowlist. Empty exposes every tool the server advertises
    # — usually a bad trade: each schema costs prompt tokens and blurs the
    # model's choice. Name the handful worth answering instantly.
    MCP_TOOLS: str = field(default_factory=lambda: os.getenv("MCP_TOOLS", ""))

    # Robot Configuration
    ROBOT_NAME: Optional[str] = field(default_factory=lambda: os.getenv("ROBOT_NAME"))
    # Hostname of the daemon, used when REACHY_CONNECTION_MODE is "network"
    # (or when "auto" finds no daemon on localhost).
    REACHY_HOST: str = field(default_factory=lambda: os.getenv("REACHY_HOST", "reachy-mini.local"))
    # "auto" | "localhost_only" | "network".
    # Use "network" when a daemon answers on localhost but only proxies a robot
    # that lives elsewhere: "auto" would pick the LOCAL media backend and the
    # shared-memory camera/audio IPC would silently yield no frames. "network"
    # selects the WebRTC backend, which streams both over the wire.
    REACHY_CONNECTION_MODE: str = field(default_factory=lambda: os.getenv("REACHY_CONNECTION_MODE", "auto"))
    # "default" auto-detects (LOCAL when co-located, else WebRTC); "no_media"
    # skips camera and audio entirely.
    REACHY_MEDIA_BACKEND: str = field(default_factory=lambda: os.getenv("REACHY_MEDIA_BACKEND", "default"))
    
    # Feature Flags
    ENABLE_OPENCLAW_TOOLS: bool = field(default_factory=lambda: os.getenv("ENABLE_OPENCLAW_TOOLS", "true").lower() == "true")
    ENABLE_CAMERA: bool = field(default_factory=lambda: os.getenv("ENABLE_CAMERA", "true").lower() == "true")
    ENABLE_FACE_TRACKING: bool = field(default_factory=lambda: os.getenv("ENABLE_FACE_TRACKING", "true").lower() == "true")
    # Mute the microphone while the robot is talking (half-duplex).
    # The robot's speaker and microphone share a body and there is no acoustic
    # echo cancellation between them, so without this the robot hears its own
    # voice, server VAD fires, and the reply is cut off after a fraction of a
    # second. Costs the ability to interrupt the robot mid-sentence.
    MIC_GATE_WHILE_SPEAKING: bool = field(
        default_factory=lambda: os.getenv("MIC_GATE_WHILE_SPEAKING", "true").lower() == "true"
    )
    # Keep suppressing echo this long after the last outgoing audio, to cover
    # speaker latency and room reverberation.
    MIC_GATE_TAIL_MS: int = field(
        default_factory=lambda: int(os.getenv("MIC_GATE_TAIL_MS", "400"))
    )
    # How much louder than the measured echo a frame must be to count as
    # someone talking over the robot. Lower = easier to interrupt but more
    # risk the robot cuts itself off again; higher = the opposite.
    MIC_ECHO_RATIO: float = field(
        default_factory=lambda: float(os.getenv("MIC_ECHO_RATIO", "2.5"))
    )
    # Absolute noise floor (0..1 RMS): below this nothing counts as speech,
    # so room hiss can never register as a barge-in.
    MIC_MIN_RMS: float = field(
        default_factory=lambda: float(os.getenv("MIC_MIN_RMS", "0.02"))
    )
    # Avance maximale, en secondes, entre ce qui a été remis au robot et ce
    # qu'il a fini de dire. OpenAI génère la parole beaucoup plus vite que le
    # temps réel ; sans plafond, tout part d'un coup dans la file de lecture et
    # le robot répond avec le retard ainsi accumulé (21 s mesurés). Descendre
    # rend l'interruption plus franche mais expose aux à-coups réseau, puisque
    # le robot a moins d'avance devant lui.
    SPEECH_LEAD_S: float = field(
        default_factory=lambda: float(os.getenv("SPEECH_LEAD_S", "1.5"))
    )

    # Face Tracking Configuration
    # Options: "yolo", "mediapipe", or None for auto-detect
    HEAD_TRACKER_TYPE: Optional[str] = field(default_factory=lambda: os.getenv("HEAD_TRACKER_TYPE", "yolo"))
    # Rate of the face-tracking control loop. Smoothing is derived from this,
    # so raising it makes tracking crisper without changing how it feels.
    # 30 matches the camera's own frame rate, which is what actually paces the
    # loop; going higher just spins on frames that have not arrived.
    FACE_TRACKING_HZ: float = field(
        default_factory=lambda: float(os.getenv("FACE_TRACKING_HZ", "30"))
    )
    
    # Local Vision Processing
    ENABLE_LOCAL_VISION: bool = field(default_factory=lambda: os.getenv("ENABLE_LOCAL_VISION", "false").lower() == "true")
    LOCAL_VISION_MODEL: str = field(default_factory=lambda: os.getenv("LOCAL_VISION_MODEL", "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"))
    VISION_DEVICE: str = field(default_factory=lambda: os.getenv("VISION_DEVICE", "auto"))  # "auto", "cuda", "mps", "cpu"
    HF_HOME: str = field(default_factory=lambda: os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
    
    # Custom Profile (for personality customization)
    CUSTOM_PROFILE: Optional[str] = field(default_factory=lambda: os.getenv("REACHY_MINI_CUSTOM_PROFILE"))
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        if not self.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required")
        return errors


# Global configuration instance
config = Config()


def set_custom_profile(profile: Optional[str]) -> None:
    """Update the custom profile at runtime."""
    global config
    config.CUSTOM_PROFILE = profile
    os.environ["REACHY_MINI_CUSTOM_PROFILE"] = profile or ""


def set_face_tracking_enabled(enabled: bool) -> None:
    """Enable or disable face tracking at runtime."""
    global config
    config.ENABLE_FACE_TRACKING = enabled


def set_local_vision_enabled(enabled: bool) -> None:
    """Enable or disable local vision processing at runtime."""
    global config
    config.ENABLE_LOCAL_VISION = enabled
