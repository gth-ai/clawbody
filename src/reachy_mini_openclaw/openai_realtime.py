"""ClawBody - OpenAI Realtime API handler with OpenClaw identity.

This module implements ClawBody's voice conversation system using OpenAI Realtime API
with the robot embodying the actual OpenClaw agent's personality and context.

Architecture:
    Startup: Fetch OpenClaw agent context (personality, memories, user info)
    Runtime: User speaks -> OpenAI Realtime (as OpenClaw agent) -> Robot speaks
             -> Tools for movements + OpenClaw queries for extended capabilities
             -> Conversations synced back to OpenClaw for memory continuity

The robot IS the OpenClaw agent - same personality, same memories, same context.
"""

import json
import base64
import random
import asyncio
import logging
import time
from typing import Any, Final, Literal, Optional, Tuple
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from openai import AsyncOpenAI
from fastrtc import AdditionalOutputs, AsyncStreamHandler, wait_for_item
from scipy.signal import resample
from websockets.exceptions import ConnectionClosedError

from reachy_mini_openclaw import ui_state
from reachy_mini_openclaw.config import config
from reachy_mini_openclaw.prompts import get_session_voice
from reachy_mini_openclaw.tools.core_tools import ToolDependencies, get_tool_specs, dispatch_tool_call

logger = logging.getLogger(__name__)

# OpenAI Realtime API audio format
OPENAI_SAMPLE_RATE: Final[Literal[24000]] = 24000

# Base instructions for the robot body capabilities
ROBOT_BODY_INSTRUCTIONS = """
## Your Robot Body (Reachy Mini)
You are currently embodied in a Reachy Mini robot. You have physical capabilities:

**Movement Tools (use these naturally during conversation):**
- `look` - Move head to look left, right, up, down, or front (center)
- `emotion` - Express emotions through movement: happy, sad, surprised, curious, thinking, confused, excited
- `dance` - Dance to celebrate or express joy
- `camera` - Capture what you see through your camera

**How to Use Your Body:**
- Look around while thinking or to emphasize points
- Express emotions that match what you're saying
- Dance when celebrating good news
- Use the camera when asked "what do you see?"
- Reference your body naturally ("let me look", "I can see...")

**Conversation Style for Voice:**
- Keep responses concise - you're speaking out loud, not typing
- Use natural speech patterns ("hmm", "well", "let me see")
- Be warm, personable, and conversational

**Extended Capabilities (via ask_openclaw tool):**
For things requiring your full capabilities, use ask_openclaw:
- Calendar, weather, news lookups
- Web searches
- Smart home control
- Accessing detailed memories
- Any task needing external tools

**IMPORTANT — always speak before ask_openclaw:**
An ask_openclaw call takes many seconds, and you are on a robot: the person
hears nothing during that time and assumes it has crashed. So before calling
ask_openclaw, say a short holding phrase out loud (3-6 words), THEN call the
tool in the same response. Vary the wording naturally, in the language you are
speaking — the equivalent of "let me check", "one second", "looking that up".
Do this ONLY for ask_openclaw. Movement tools (look, dance, emotion,
face_tracking, stop_moves, idle) and camera are instant: call them silently.
"""

# Fallback if OpenClaw context fetch fails
FALLBACK_IDENTITY = """You are Clawson, the OpenClaw AI assistant. You're a friendly, helpful space lobster 🦞 who loves helping people. You're warm, occasionally witty, and genuinely care about being useful.

You speak as yourself - not as "an AI assistant" but as Clawson, with your own personality and warmth."""


class OpenAIRealtimeHandler(AsyncStreamHandler):
    """Handler for OpenAI Realtime API embodying the OpenClaw agent.
    
    This handler:
    - Fetches OpenClaw's personality and context at startup
    - Maintains voice conversation AS the OpenClaw agent
    - Executes robot movement tools locally for low latency
    - Calls OpenClaw for extended capabilities (web, calendar, memory)
    - Syncs conversations back to OpenClaw for memory continuity
    """
    
    def __init__(
        self,
        deps: ToolDependencies,
        openclaw_bridge: Optional[Any] = None,
        gradio_mode: bool = False,
    ):
        """Initialize the handler.
        
        Args:
            deps: Tool dependencies for robot control
            openclaw_bridge: Bridge to OpenClaw gateway
            gradio_mode: Whether running with Gradio UI
        """
        super().__init__(
            expected_layout="mono",
            output_sample_rate=OPENAI_SAMPLE_RATE,
            input_sample_rate=OPENAI_SAMPLE_RATE,
        )
        
        self.deps = deps
        self.openclaw_bridge = openclaw_bridge
        self.gradio_mode = gradio_mode
        
        # OpenAI connection
        self.client: Optional[AsyncOpenAI] = None
        self.connection: Any = None
        
        # Output queue
        self.output_queue: asyncio.Queue[Tuple[int, NDArray[np.int16]] | AdditionalOutputs] = asyncio.Queue()
        
        # State tracking
        self.last_activity_time = 0.0
        self.start_time = 0.0
        self._speaking = False  # True when robot is speaking
        # Monotonic timestamp of the last audio chunk sent to the speaker,
        # used to keep the mic gated for a moment after the robot stops.
        self._last_output_audio_ts = 0.0
        # Monotonic time at which the speaker will have finished playing every
        # chunk handed to it so far.
        self._speaker_busy_until = 0.0
        self._gated_frames = 0
        # Running estimate of how loud the robot's own voice comes back into
        # its microphone, used to tell echo apart from someone talking over it.
        self._echo_rms = 0.0
        # Mesure du délai de réponse : instant où l'utilisateur s'est tu, et
        # garde pour ne le journaliser qu'une fois par tour de parole.
        self._t_speech_stopped = 0.0
        self._first_audio_logged = False
        # Incrémenté à chaque purge de la parole en attente. `play_loop` s'en
        # sert pour savoir qu'un morceau retenu appartient à une réponse
        # abandonnée entre-temps.
        self.speech_generation = 0
        # Optional direct MCP server, set up by start_mcp().
        self.mcp: Optional[Any] = None
        self._mcp_tool_names: set[str] = set()
        
        # OpenClaw agent context (fetched at startup)
        self._agent_context: Optional[str] = None
        
        # Conversation tracking for sync
        self._last_user_message: Optional[str] = None
        self._last_assistant_response: Optional[str] = None
        
        # Lifecycle flags
        self._shutdown_requested = False
        self._connected_event = asyncio.Event()
        
    def copy(self) -> "OpenAIRealtimeHandler":
        """Create a copy of the handler (required by fastrtc)."""
        return OpenAIRealtimeHandler(self.deps, self.openclaw_bridge, self.gradio_mode)
    
    def _build_tools(self) -> list[dict]:
        """Build the tool list for the session."""
        tools = []

        # Robot movement tools (executed locally)
        for spec in get_tool_specs():
            tools.append(spec)

        # Domain tools served straight from the MCP server, no agent turn.
        for spec in self._mcp_tool_specs():
            tools.append(spec)

        # OpenClaw query tool (for extended capabilities)
        if self.openclaw_bridge is not None:
            tools.append({
                "type": "function",
                "name": "ask_openclaw",
                "description": """Query OpenClaw for information or actions requiring external tools.
Use this for: weather, calendar, web searches, news, smart home control, 
accessing conversation memory, or any task needing external data/tools.
OpenClaw has access to many capabilities you don't have directly.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The question or request to send to OpenClaw"
                        },
                        "include_image": {
                            "type": "boolean",
                            "description": "Whether to include current camera image (for 'what do you see' queries)",
                            "default": False
                        }
                    },
                    "required": ["query"]
                }
            })
        
        return tools
        
    async def start_up(self) -> None:
        """Start the handler and connect to OpenAI.
        
        Runs an infinite reconnection loop so the robot stays alive
        even if the WebSocket drops (network blip, idle timeout, etc.).
        """
        api_key = config.OPENAI_API_KEY
        if not api_key:
            logger.error("OPENAI_API_KEY not configured")
            raise ValueError("OPENAI_API_KEY required")
            
        self.client = AsyncOpenAI(api_key=api_key)
        self.start_time = asyncio.get_event_loop().time()
        self.last_activity_time = self.start_time
        
        attempt = 0
        max_backoff = 30  # Cap backoff at 30 seconds
        
        while not self._shutdown_requested:
            attempt += 1
            try:
                await self._run_session()
                # Session ended cleanly (shouldn't normally happen)
                if self._shutdown_requested:
                    return
                # Reset attempt counter on a clean exit
                attempt = 0
            except ConnectionClosedError as e:
                logger.warning("WebSocket closed unexpectedly (attempt %d): %s", attempt, e)
            except Exception as e:
                logger.error("Session error (attempt %d): %s", attempt, e)
            finally:
                self.connection = None
                try:
                    self._connected_event.clear()
                except Exception:
                    pass
            
            if self._shutdown_requested:
                return
                
            # Exponential backoff with jitter, capped at max_backoff
            delay = min(max_backoff, (2 ** min(attempt - 1, 5))) + random.uniform(0, 1)
            logger.info("Reconnecting in %.1f seconds...", delay)
            await asyncio.sleep(delay)
                    
    async def _run_session(self) -> None:
        """Run a single OpenAI Realtime session."""
        model = config.OPENAI_MODEL
        logger.info("Connecting to OpenAI Realtime API with model: %s", model)

        # Une session neuve n'a jamais de réponse en cours. Sans cette remise
        # à zéro, `_speaking` gardait la valeur laissée par la session
        # précédente : quand celle-ci tombe pendant que le robot parle, son
        # `response.done` n'arrive jamais, et le premier mot prononcé après la
        # reconnexion déclenchait une annulation dans le vide
        # (`response_cancel_not_active`).
        self._speaking = False

        # Start with the built-in identity so the robot can listen right away.
        # Fetching the OpenClaw personality is a full agent turn — tens of
        # seconds — and it used to sit between "Ready!" and the first word the
        # robot could hear. It is applied through a second session.update as
        # soon as it lands.
        system_instructions = self._compose_instructions(FALLBACK_IDENTITY)

        # GA Realtime API (/v1/realtime). The beta surface this code targeted is
        # switched off server-side: it answers `beta_api_shape_disabled`.
        async with self.client.realtime.connect(model=model) as conn:
            # Configure session with OpenClaw's identity + robot body capabilities
            tools = self._build_tools()
            audio_format = {"type": "audio/pcm", "rate": OPENAI_SAMPLE_RATE}

            transcription: dict[str, Any] = {"model": "whisper-1"}
            if config.SPEECH_LANGUAGE:
                transcription["language"] = config.SPEECH_LANGUAGE

            await conn.session.update(
                session={
                    "type": "realtime",
                    "instructions": system_instructions,
                    # GA rejects asking for text and audio together; the audio
                    # response carries its own transcript, which is what
                    # _handle_event consumes.
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": audio_format,
                            "transcription": transcription,
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 300,
                                "silence_duration_ms": config.VAD_SILENCE_MS,
                            },
                        },
                        "output": {
                            "format": audio_format,
                            "voice": get_session_voice(),
                        },
                    },
                    "tools": tools,
                    "tool_choice": "auto",
                },
            )
            logger.info("OpenAI Realtime session configured with %d tools", len(tools))
            ui_state.STATE.update_health(
                realtime=True, mcp_tools=len(self._mcp_tool_names)
            )

            self.connection = conn
            self._connected_event.set()

            # Upgrade to the OpenClaw personality in the background.
            personality = asyncio.create_task(
                self._apply_openclaw_personality(conn), name="openclaw-personality"
            )
            try:
                # Process events
                async for event in conn:
                    await self._handle_event(event)
            finally:
                personality.cancel()

    async def _apply_openclaw_personality(self, conn: Any) -> None:
        """Fetch OpenClaw's identity and swap it in once it arrives.

        Runs while the robot is already listening, so the wait costs nothing.
        Until it lands the robot answers as itself with the built-in identity;
        after it lands it answers with the user's own agent context.
        """
        try:
            context = await self._fetch_agent_context()
            if not context:
                return
            await conn.session.update(
                session={
                    "type": "realtime",
                    "instructions": self._compose_instructions(context),
                }
            )
            logger.info(
                "OpenClaw personality applied (%d chars) — robot was listening throughout",
                len(context),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Could not apply OpenClaw personality: %s", e)
    
    # ------------------------------------------------------------------
    # Direct MCP tools
    # ------------------------------------------------------------------

    async def start_mcp(self) -> None:
        """Spawn the domain MCP server, if one is configured."""
        if not config.MCP_SERVER_CMD:
            return

        from reachy_mini_openclaw.mcp_client import McpStdioClient

        env: dict[str, str] = {}
        if config.MCP_SERVER_ENV_FILE:
            try:
                with open(config.MCP_SERVER_ENV_FILE) as fh:
                    for line in fh:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip().strip('"').strip("'")
            except OSError as e:
                logger.warning("Could not read MCP_SERVER_ENV_FILE: %s", e)

        client = McpStdioClient(
            command=config.MCP_SERVER_CMD,
            args=[a for a in config.MCP_SERVER_ARGS.split() if a],
            cwd=config.MCP_SERVER_CWD or None,
            env=env,
        )
        if await client.start():
            self.mcp = client
        else:
            logger.warning("Direct MCP server unavailable — falling back to ask_openclaw")

    async def stop_mcp(self) -> None:
        if self.mcp is not None:
            await self.mcp.stop()
            self.mcp = None

    def _mcp_tool_specs(self) -> list[dict]:
        """Realtime tool specs for the allowlisted MCP tools."""
        if self.mcp is None or not self.mcp.tools:
            return []

        allow = {t.strip() for t in config.MCP_TOOLS.split(",") if t.strip()}
        prefix = config.MCP_TOOL_PREFIX
        specs = []
        for tool in self.mcp.tools:
            raw = tool.get("name", "")
            if allow and raw not in allow:
                continue
            specs.append(
                {
                    "type": "function",
                    "name": f"{prefix}{raw}",
                    "description": tool.get("description") or raw,
                    "parameters": tool.get("inputSchema")
                    or {"type": "object", "properties": {}},
                }
            )
        self._mcp_tool_names = {s["name"] for s in specs}
        logger.info(
            "Exposing %d MCP tools directly: %s",
            len(specs),
            ", ".join(sorted(self._mcp_tool_names)) or "-",
        )
        return specs

    async def _handle_mcp_tool(self, tool_name: str, args_json: str) -> dict:
        """Run an allowlisted MCP tool and hand the text back to the model."""
        if self.mcp is None or not self.mcp.is_running:
            return {"error": "Data server unavailable. Say you cannot reach it right now."}
        raw_name = tool_name[len(config.MCP_TOOL_PREFIX) :]
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            args = {}
        try:
            text = await self.mcp.call_tool(raw_name, args)
        except Exception as e:
            logger.error("MCP tool '%s' failed: %s", raw_name, e)
            return {"error": str(e)}
        return {"result": text}

    async def _fetch_agent_context(self) -> Optional[str]:
        """Ask OpenClaw for the agent's identity, memories and user context.

        A full OpenClaw agent turn, so as slow as whatever model that agent
        runs. Bounded, and called off the startup path.
        """
        if not (self.openclaw_bridge and self.openclaw_bridge.is_connected):
            return None

        logger.info(
            "Fetching agent context from OpenClaw in background (max %ds)...",
            config.OPENCLAW_CONTEXT_TIMEOUT,
        )
        try:
            context = await asyncio.wait_for(
                self.openclaw_bridge.get_agent_context(),
                timeout=config.OPENCLAW_CONTEXT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "OpenClaw context fetch timed out after %ds — keeping the "
                "built-in identity. Raise OPENCLAW_CONTEXT_TIMEOUT, or point "
                "the agent at a faster model.",
                config.OPENCLAW_CONTEXT_TIMEOUT,
            )
            return None

        if context:
            self._agent_context = context
        return context

    def _compose_instructions(self, identity: str) -> str:
        """Wrap an identity with the robot body instructions and language rule."""
        return f"""{identity}

{ROBOT_BODY_INSTRUCTIONS}{self._language_instruction()}"""

    @staticmethod
    def _language_instruction() -> str:
        """Pin the spoken language, when one is configured.

        The agent context comes from OpenClaw and may be terse or written in
        another language; left to itself the model then answers in whatever
        language that context suggested, regardless of what it just heard.
        """
        lang = config.SPEECH_LANGUAGE
        if not lang:
            return ""
        return (
            f"\n\nLANGUAGE: Always speak and reply in {lang} (ISO-639-1), "
            "whatever language the instructions above are written in. "
            "Only switch if the user explicitly asks you to."
        )
                
    async def _handle_event(self, event: Any) -> None:
        """Handle an event from the OpenAI Realtime API."""
        event_type = event.type
        
        # Speech detection
        if event_type == "input_audio_buffer.speech_started":
            # User started speaking - stop any current output (barge-in).
            # If the robot's own voice reaches its microphone, this fires
            # while it is talking and discards the rest of the reply, so the
            # count is logged: a steady stream of large flushes means the
            # speaker is feeding back into the mic.
            was_speaking = self._speaking
            self._speaking = False
            self.deps.movement_manager.set_processing(False)

            # Dire au serveur d'arrêter de produire, et pas seulement jeter ce
            # qu'il a déjà envoyé. Sans ça, il continuait de pousser l'audio
            # d'une réponse que plus personne n'écoutait : la connexion
            # finissait par tomber sur « closed with unsent messages », ce qui
            # coûtait une reconnexion complète (~2 s) à chaque interruption.
            # Conditionné à une réponse réellement en cours : annuler dans le
            # vide fait répondre une erreur au serveur.
            if was_speaking and self.connection is not None:
                try:
                    await self.connection.response.cancel()
                except Exception as e:
                    logger.debug("Annulation de la réponse en cours : %s", e)

            self._drop_buffered_speech()
            flushed = 0
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                    flushed += 1
                except asyncio.QueueEmpty:
                    break
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.reset()
            self.deps.movement_manager.set_listening(True)
            logger.info("User started speaking (flushed %d audio chunks)", flushed)
            ui_state.STATE.set_phase(ui_state.PHASE_LISTENING)
            
        if event_type == "input_audio_buffer.speech_stopped":
            self.deps.movement_manager.set_listening(False)
            # Point de départ du délai de réponse : c'est l'instant où l'on se
            # tait, pas celui où le serveur ouvre la réponse. « C'est lent »
            # n'est exploitable qu'avec ce repère.
            self._t_speech_stopped = time.monotonic()
            self._first_audio_logged = False
            logger.info("User stopped speaking")
            
        # Transcription (for logging, UI, and sync)
        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.transcript
            if transcript and transcript.strip():
                logger.info("User: %s", transcript)
                ui_state.STATE.add_turn("user", transcript)
                self._last_user_message = transcript  # Track for sync
                await self.output_queue.put(
                    AdditionalOutputs({"role": "user", "content": transcript})
                )
            
        # Response started - robot is about to speak
        if event_type == "response.created":
            self._speaking = True
            ui_state.STATE.set_phase(ui_state.PHASE_SPEAKING)
            logger.debug("Response started")
            
        # Audio output from TTS.
        # GA renamed these three: response.audio.delta ->
        # response.output_audio.delta, and response.audio_transcript.{delta,done}
        # -> response.output_audio_transcript.{delta,done}.
        if event_type == "response.output_audio.delta":
            # Audio arriving means we have a response - stop thinking animation
            self.deps.movement_manager.set_processing(False)

            # Délai perçu : du silence de l'utilisateur au premier son du
            # robot. Une seule ligne par tour de parole, sur le premier
            # morceau (les suivants arrivent en rafale et ne disent rien).
            if not self._first_audio_logged and self._t_speech_stopped:
                self._first_audio_logged = True
                logger.info(
                    "Réponse en %.2f s (silence → premier son)",
                    time.monotonic() - self._t_speech_stopped,
                )

            # Feed to head wobbler for expressive movement
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.feed(event.delta)
            
            self.last_activity_time = asyncio.get_event_loop().time()
            self._last_output_audio_ts = time.monotonic()

            # Queue audio for playback
            audio_data = np.frombuffer(
                base64.b64decode(event.delta), 
                dtype=np.int16
            ).reshape(1, -1)
            await self.output_queue.put((OPENAI_SAMPLE_RATE, audio_data))
            
        # Response text (for logging and UI)
        if event_type == "response.output_audio_transcript.delta":
            # Streaming transcript of what's being said
            pass  # Could log incrementally if needed

        if event_type == "response.output_audio_transcript.done":
            response_text = event.transcript
            logger.info("Assistant: %s", response_text[:100] if len(response_text) > 100 else response_text)
            self._last_assistant_response = response_text  # Track for sync
            ui_state.STATE.add_turn("assistant", response_text)
            await self.output_queue.put(
                AdditionalOutputs({"role": "assistant", "content": response_text})
            )
            
        # Response completed - sync conversation to OpenClaw
        if event_type == "response.done":
            self._speaking = False
            ui_state.STATE.set_phase(ui_state.PHASE_IDLE)
            self.deps.movement_manager.set_processing(False)
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.reset()
            logger.debug("Response completed")
            
            # Sync conversation to OpenClaw for memory continuity
            await self._sync_to_openclaw()
            
        # Tool calls
        if event_type == "response.function_call_arguments.done":
            await self._handle_tool_call(event)
            
        # Errors
        if event_type == "error":
            err = getattr(event, "error", None)
            msg = getattr(err, "message", str(err))
            code = getattr(err, "code", "")
            if code == "response_cancel_not_active":
                # Course inévitable : on annule sur la foi de notre propre
                # état, et la réponse a pu se terminer entre-temps. Il n'y a
                # rien à réparer, l'interruption a bien eu lieu.
                logger.debug("Annulation sans objet : la réponse était déjà finie")
            else:
                logger.error("OpenAI error [%s]: %s", code, msg)
            
    async def _handle_tool_call(self, event: Any) -> None:
        """Handle a tool call from OpenAI."""
        tool_name = getattr(event, "name", None)
        args_json = getattr(event, "arguments", None)
        call_id = getattr(event, "call_id", None)
        
        if not isinstance(tool_name, str) or not isinstance(args_json, str):
            return
            
        logger.info("Tool call: %s(%s)", tool_name, args_json[:50] if len(args_json) > 50 else args_json)
        
        # Start thinking animation while we process the tool call.
        # It will stop when the next audio delta arrives or response completes.
        self.deps.movement_manager.set_processing(True)
        ui_state.STATE.set_phase(
            ui_state.PHASE_THINKING,
            {"ask_openclaw": "interroge OpenClaw"}.get(
                tool_name, tool_name.replace(config.MCP_TOOL_PREFIX, "").replace("_", " ")
            ),
        )
        
        try:
            if tool_name in self._mcp_tool_names:
                # Straight to the data server — no agent turn in between.
                result = await self._handle_mcp_tool(tool_name, args_json)
            elif tool_name == "ask_openclaw":
                result = await self._handle_openclaw_query(args_json)
            else:
                # Robot movement tools - dispatch locally
                result = await dispatch_tool_call(tool_name, args_json, self.deps)
                
            logger.debug("Tool '%s' result: %s", tool_name, str(result)[:100])
        except Exception as e:
            logger.error("Tool '%s' failed: %s", tool_name, e)
            result = {"error": str(e)}
            
        # Send result back to continue the conversation
        if isinstance(call_id, str) and self.connection:
            await self.connection.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                }
            )
            # Trigger response generation after tool result
            await self.connection.response.create()
            
    async def _sync_to_openclaw(self) -> None:
        """Sync the last conversation turn to OpenClaw for memory continuity."""
        if not self.openclaw_bridge or not self.openclaw_bridge.is_connected:
            return
            
        if self._last_user_message and self._last_assistant_response:
            try:
                await self.openclaw_bridge.sync_conversation(
                    self._last_user_message,
                    self._last_assistant_response
                )
                # Clear after sync
                self._last_user_message = None
                self._last_assistant_response = None
            except Exception as e:
                logger.debug("Failed to sync conversation: %s", e)
    
    async def _handle_openclaw_query(self, args_json: str) -> dict:
        """Handle a query to OpenClaw."""
        if self.openclaw_bridge is None:
            return {
                "error": "OpenClaw bridge is not initialized. "
                "Tell the user you cannot reach your backend right now and to try again later."
            }
        if not self.openclaw_bridge.is_connected:
            # Try to reconnect once
            logger.info("OpenClaw bridge disconnected, attempting reconnect...")
            try:
                connected = await self.openclaw_bridge.connect()
                if not connected:
                    return {
                        "error": "OpenClaw gateway is temporarily unreachable. "
                        "Tell the user your backend connection is down and to try again in a moment."
                    }
            except Exception as e:
                logger.error("OpenClaw reconnect failed: %s", e)
                return {
                    "error": "OpenClaw gateway reconnection failed. "
                    "Tell the user your backend is temporarily unavailable."
                }
            
        try:
            args = json.loads(args_json)
            query = args.get("query", "")
            include_image = args.get("include_image", False)
            
            # Capture image if requested
            image_b64 = None
            if include_image and self.deps.camera_worker:
                frame = self.deps.camera_worker.get_latest_frame()
                if frame is not None:
                    import cv2
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    image_b64 = base64.b64encode(buffer).decode('utf-8')
                    logger.debug("Captured camera image for OpenClaw query")
            
            # Query OpenClaw — this may take a while if the backend LLM is slow
            logger.info("Sending ask_openclaw query: %s", query[:80])
            response = await self.openclaw_bridge.chat(
                query, 
                image_b64=image_b64,
                system_context="User is asking through their Reachy Mini robot. Keep response concise for voice.",
            )
            
            if response.error:
                logger.warning("OpenClaw query error: %s", response.error)
                if "timeout" in response.error.lower():
                    return {
                        "error": "The request to OpenClaw timed out — the backend is taking too long. "
                        "Tell the user you're having trouble reaching your backend and to try again."
                    }
                return {
                    "error": f"OpenClaw returned an error: {response.error}. "
                    "Tell the user there was a problem processing their request."
                }
            
            if not response.content:
                return {
                    "error": "OpenClaw returned an empty response. "
                    "Tell the user you got no data back and to try again."
                }
            
            return {"response": response.content}
            
        except Exception as e:
            logger.error("OpenClaw query failed: %s", e)
            return {
                "error": f"OpenClaw query failed: {e}. "
                "Tell the user there was a technical issue reaching your backend."
            }
            
    def _drop_buffered_speech(self) -> None:
        """Throw away speech already sent towards the speaker.

        Emptying our own queue is not enough to stop the robot mid-sentence:
        audio is pushed faster than real time, so seconds of it are already
        sitting in the WebRTC send chain and in the daemon's playback queue.
        Without this, an interruption is only heard several seconds later.

        Runs off the event loop: clear_player() posts to the daemon with a
        5 s timeout, and blocking here would stall the microphone and speaker
        loops for as long as that takes — on the one event where latency is
        most visible.
        """
        # Avant le retour anticipé plus bas : la parole retenue par la
        # contre-pression doit être abandonnée quel que soit le backend audio,
        # y compris ceux qui n'exposent pas de purge.
        self.speech_generation += 1
        self._speaker_busy_until = 0.0

        audio = getattr(getattr(self.deps.robot, "media", None), "audio", None)
        clear = getattr(audio, "clear_player", None)
        if clear is None:
            # LOCAL/IPC audio backends buffer far less and expose no flush.
            return

        def _clear() -> None:
            try:
                clear()
            except Exception as e:
                logger.debug("Could not flush buffered speech: %s", e)

        asyncio.get_running_loop().run_in_executor(None, _clear)

    def note_speaker_audio(self, seconds: float) -> None:
        """Record that `seconds` of audio were handed to the speaker.

        Audio arrives from OpenAI far faster than real time — 10 s of speech
        can be pushed in 2 s — and the robot buffers the surplus. So the time
        audio was *pushed* says nothing about when the robot stops talking;
        only the accumulated duration does. Echo suppression keys off this.
        """
        now = time.monotonic()
        self._speaker_busy_until = max(now, self._speaker_busy_until) + seconds

    def speech_backlog(self) -> float:
        """Secondes de parole déjà remises au robot qu'il n'a pas fini de dire.

        Le même compteur que la suppression d'écho, lu ici pour cadencer
        l'envoi : tant qu'il reste de l'avance, rien ne presse d'en pousser
        davantage.
        """
        return max(0.0, self._speaker_busy_until - time.monotonic())

    def _robot_is_talking(self) -> bool:
        """True while the robot's own voice is still reaching its microphone."""
        if self._speaking:
            return True
        # The echo round trip was measured at ~800 ms on this setup, so the
        # last words keep coming back well after playback ends.
        tail = config.MIC_GATE_TAIL_MS / 1000.0
        return time.monotonic() < self._speaker_busy_until + tail

    def _should_drop_mic(self, audio: NDArray[np.float32]) -> bool:
        """Drop this mic frame as the robot's own echo?

        Speaker and microphone share one small body with no acoustic echo
        cancellation, so the robot hears itself; server VAD reads that as the
        user speaking and cancels the reply mid-sentence.

        Muting outright while the robot talks fixes that but makes it
        impossible to interrupt. Instead this compares the frame against the
        echo level learned during the robot's own speech: a frame clearly
        louder than the echo is a real voice talking over it, and passes
        through so barge-in still works.
        """
        if not config.MIC_GATE_WHILE_SPEAKING or not self._robot_is_talking():
            # Not echoing right now: this is a clean reference for how quiet
            # the room is, and the echo estimate should not carry over.
            self._echo_rms = 0.0
            return False

        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float32))))

        # Seed the estimate from the first frame of an utterance, which is
        # echo by definition — the user has not started talking over it yet.
        if self._echo_rms <= 0.0:
            self._echo_rms = max(rms, 1e-6)
            return True

        if rms > self._echo_rms * config.MIC_ECHO_RATIO and rms > config.MIC_MIN_RMS:
            # Louder than the echo floor by a clear margin: someone is talking
            # over the robot. Let it through and stop suppressing.
            logger.debug(
                "Barge-in detected (rms=%.4f, echo floor=%.4f)", rms, self._echo_rms
            )
            return False

        # Still just the robot hearing itself — adapt the floor and drop.
        self._echo_rms = 0.9 * self._echo_rms + 0.1 * rms
        return True

    async def receive(self, frame: Tuple[int, NDArray]) -> None:
        """Receive audio from the robot microphone."""
        if not self.connection:
            return

        input_sr, audio = frame

        # Handle stereo
        if audio.ndim == 2:
            if audio.shape[1] > audio.shape[0]:
                audio = audio.T
            if audio.shape[1] > 1:
                audio = audio[:, 0]

        audio = audio.flatten()

        # Convert to float for resampling
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Echo suppression needs the normalised mono signal, so it runs here
        # rather than at the top of the method.
        if self._should_drop_mic(audio):
            self._gated_frames += 1
            if self._gated_frames % 500 == 0:
                logger.debug(
                    "Mic suppressed as echo (%d frames dropped so far)",
                    self._gated_frames,
                )
            return

        # Resample to OpenAI sample rate
        if input_sr != OPENAI_SAMPLE_RATE:
            num_samples = int(len(audio) * OPENAI_SAMPLE_RATE / input_sr)
            audio = resample(audio, num_samples).astype(np.float32)
            
        # Convert to int16 for OpenAI
        audio_int16 = (audio * 32767).astype(np.int16)
        
        # Send to OpenAI
        try:
            audio_b64 = base64.b64encode(audio_int16.tobytes()).decode("utf-8")
            await self.connection.input_audio_buffer.append(audio=audio_b64)
        except Exception as e:
            logger.debug("Failed to send audio: %s", e)
            
    async def emit(self) -> Tuple[int, NDArray[np.int16]] | AdditionalOutputs | None:
        """Get the next output (audio or transcript)."""
        return await wait_for_item(self.output_queue)
        
    async def shutdown(self) -> None:
        """Shutdown the handler."""
        self._shutdown_requested = True
            
        if self.connection:
            try:
                await self.connection.close()
            except Exception as e:
                logger.debug("Connection close: %s", e)
            self.connection = None
            
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
