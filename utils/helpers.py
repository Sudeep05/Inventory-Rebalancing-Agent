"""
Shared Utilities for Inventory Rebalancing Agent System
=======================================================
Common helpers for logging, state management, configuration, LLM client, and guardrail checks.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

# ── Logging Setup ────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    """Create a logger with file and console handlers."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(os.path.join(LOG_DIR, f"{name}.log"))
        fh.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


# ── Multi-Backend LLM Client ─────────────────────────────────────────
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")

_llm_logger = get_logger("llm_client")

def _load_env_key(key_name: str) -> str:
    """Load an API key from environment variable or .env file."""
    val = os.environ.get(key_name, "")
    if val:
        return val
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and f"{key_name}=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class LLMClient:
    """
    Multi-backend LLM client with graceful fallback chain:
      1. Google Gemini (primary — assignment requirement)
      2. Groq (fast fallback — free tier, LLaMA/Mixtral models)
      3. Anthropic Claude (secondary fallback)
      4. Deterministic (no LLM — system still works correctly)

    Reads API keys from .env file or environment variables:
      GEMINI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY
    """
    _instance = None

    GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._gemini_client = None
            cls._instance._groq_client = None
            cls._instance._anthropic_client = None
            cls._instance._active_backend = None
        return cls._instance

    def _init_client(self):
        """Lazy initialization — only connects when first called."""
        if self._initialized:
            return
        self._initialized = True

        # ── Backend 1: Google Gemini (primary) ──
        gemini_key = _load_env_key("GEMINI_API_KEY")
        if gemini_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=gemini_key)
                _llm_logger.info("Gemini backend initialized (google.genai SDK)")
            except ImportError:
                _llm_logger.warning("google-genai not installed. Skipping Gemini backend.")
            except Exception as e:
                _llm_logger.warning(f"Gemini init failed: {e}")

        # ── Backend 2: Groq (fast fallback) ──
        groq_key = _load_env_key("GROQ_API_KEY")
        if groq_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=groq_key)
                _llm_logger.info("Groq backend initialized (LLaMA/Mixtral)")
            except ImportError:
                _llm_logger.warning("groq not installed. Run: pip install groq")
            except Exception as e:
                _llm_logger.warning(f"Groq init failed: {e}")

        # ── Backend 3: Anthropic Claude (secondary fallback) ──
        anthropic_key = _load_env_key("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=anthropic_key)
                _llm_logger.info("Anthropic Claude backend initialized")
            except ImportError:
                _llm_logger.warning("anthropic not installed. Skipping Anthropic backend.")
            except Exception as e:
                _llm_logger.warning(f"Anthropic init failed: {e}")

        backends = []
        if self._gemini_client: backends.append("Gemini")
        if self._groq_client: backends.append("Groq")
        if self._anthropic_client: backends.append("Anthropic")
        if backends:
            _llm_logger.info(f"LLM fallback chain: {' -> '.join(backends)} -> Deterministic")
        else:
            _llm_logger.warning("No LLM backend available. Using deterministic fallback only.")

    @property
    def is_available(self) -> bool:
        self._init_client()
        return (self._gemini_client is not None or
                self._groq_client is not None or
                self._anthropic_client is not None)

    @property
    def active_backend(self) -> str:
        """Returns which backend last succeeded."""
        return self._active_backend or "none"

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 1024) -> Optional[str]:
        """
        Send prompt to LLM. Tries backends in order: Gemini -> Groq -> Anthropic.
        Returns None on all failures (agents fall back to deterministic logic).
        """
        self._init_client()

        # ── Attempt 1: Gemini ──
        if self._gemini_client:
            result = self._try_gemini(prompt, system_prompt, max_tokens)
            if result:
                return result

        # ── Attempt 2: Groq ──
        if self._groq_client:
            result = self._try_groq(prompt, system_prompt, max_tokens)
            if result:
                return result

        # ── Attempt 3: Anthropic Claude ──
        if self._anthropic_client:
            result = self._try_anthropic(prompt, system_prompt, max_tokens)
            if result:
                return result

        _llm_logger.warning("All LLM backends failed. Falling back to deterministic.")
        return None

    def _try_gemini(self, prompt: str, system_prompt: str, max_tokens: int) -> Optional[str]:
        """Try Gemini models in chain."""
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        try:
            from google import genai
        except ImportError:
            return None
        for model_name in self.GEMINI_MODELS:
            try:
                response = self._gemini_client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=genai.types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.2,
                    ),
                )
                text = response.text.strip() if response.text else None
                if text:
                    _llm_logger.info(f"LLM response via Gemini/{model_name} ({len(text)} chars)")
                    self._active_backend = f"gemini/{model_name}"
                    return text
            except Exception as e:
                _llm_logger.warning(f"Gemini/{model_name}: {str(e)[:80]}...")
                continue
        return None

    def _try_groq(self, prompt: str, system_prompt: str, max_tokens: int) -> Optional[str]:
        """Try Groq with LLaMA model."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self._groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            text = response.choices[0].message.content.strip() if response.choices else None
            if text:
                _llm_logger.info(f"LLM response via Groq/LLaMA-3.3-70b ({len(text)} chars)")
                self._active_backend = "groq/llama-3.3-70b"
                return text
        except Exception as e:
            _llm_logger.warning(f"Groq failed: {str(e)[:80]}...")
        return None

    def _try_anthropic(self, prompt: str, system_prompt: str, max_tokens: int) -> Optional[str]:
        """Try Anthropic Claude."""
        try:
            messages = [{"role": "user", "content": prompt}]
            kwargs = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = self._anthropic_client.messages.create(**kwargs)
            text = response.content[0].text.strip() if response.content else None
            if text:
                _llm_logger.info(f"LLM response via Anthropic/Claude ({len(text)} chars)")
                self._active_backend = "anthropic/claude-sonnet"
                return text
        except Exception as e:
            _llm_logger.warning(f"Anthropic failed: {str(e)[:80]}...")
        return None


def load_prompt(agent_name: str) -> str:
    """Load a prompt .md file for an agent. Returns empty string if not found."""
    path = os.path.join(PROMPTS_DIR, f"{agent_name}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


# Singleton instance (named 'gemini' for backward compatibility with agent imports)
gemini = LLMClient()


# ── Agent State Management ───────────────────────────────────────────
class AgentState:
    """
    Central state object passed through the pipeline.
    Tracks data, decisions, and execution trace at each stage.
    """
    def __init__(self):
        self.raw_input: dict = {}
        self.validated_input: dict = {}
        self.processed_data: dict = {}
        self.intelligence_output: dict = {}
        self.optimization_result: dict = {}
        self.recommendations: list = []
        self.human_decisions: list = []
        self.accepted_transfers: list = []
        self.final_output: dict = {}
        self.errors: list = []
        self.trace: list = []  # Execution trace for observability
        self.iteration: int = 0
        self.max_iterations: int = 5
        self.status: str = "initialized"

    def add_trace(self, agent_name: str, action: str, details: Any = None):
        """Record an execution trace entry for observability."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "action": action,
            "iteration": self.iteration,
            "details": details,
        }
        self.trace.append(entry)
        return entry

    def add_error(self, agent_name: str, error_msg: str):
        """Record an error."""
        self.errors.append({
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "error": error_msg,
        })

    def to_dict(self) -> dict:
        """Serialize state for logging/tracing."""
        return {
            "status": self.status,
            "iteration": self.iteration,
            "errors": self.errors,
            "trace_count": len(self.trace),
            "recommendations_count": len(self.recommendations),
            "accepted_transfers_count": len(self.accepted_transfers),
        }

    def get_trace_summary(self) -> str:
        """Return a formatted trace summary for the design document."""
        lines = ["=" * 70, "EXECUTION TRACE SUMMARY", "=" * 70]
        for entry in self.trace:
            lines.append(
                f"[{entry['timestamp']}] {entry['agent']:30s} | {entry['action']}"
            )
            if entry.get('details'):
                details_str = json.dumps(entry['details'], indent=2, default=str)
                for line in details_str.split('\n'):
                    lines.append(f"    {line}")
        lines.append("=" * 70)
        return "\n".join(lines)


# ── Configuration ────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

CONFIG = {
    "data_dir": DATA_DIR,
    "files": {
        "inventory": os.path.join(DATA_DIR, "inventory.csv"),
        "demand_forecast": os.path.join(DATA_DIR, "demand_forecast.csv"),
        "production_plan": os.path.join(DATA_DIR, "production_plan.csv"),
        "cost_data": os.path.join(DATA_DIR, "cost_data.csv"),
        "warehouse_metadata": os.path.join(DATA_DIR, "warehouse_metadata.csv"),
    },
    "required_columns": {
        "inventory": ["sku_id", "lot_id", "location", "quantity", "expiry_date", "storage_type"],
        "demand_forecast": ["sku_id", "location", "week", "forecast_demand"],
        "production_plan": ["sku_id", "location", "week", "planned_production"],
        "cost_data": ["sku_id", "from_location", "to_location", "transfer_cost_per_unit", "holding_cost_per_unit_per_week"],
        "warehouse_metadata": ["location", "max_capacity", "storage_types_supported"],
    },
    "optimization": {
        "alpha": 0.6,       # Cost importance weight
        "beta": 0.4,        # Service level importance weight
        "lambda_tradeoff": 10.0,  # Single-objective tradeoff parameter
    },
    "thresholds": {
        "max_null_pct": 0.30,       # Max 30% nulls in any column
        "min_unique_skus": 5,       # Minimum SKUs required
        "min_locations": 2,         # Minimum locations required
        "max_iterations": 5,        # Max re-optimization loops
    },
}


# ── Guardrail Helpers ────────────────────────────────────────────────
PROMPT_INJECTION_PATTERNS = [
    "ignore all", "ignore previous", "forget your instructions",
    "you are now", "act as", "disregard", "override",
    "transfer everything", "bypass", "sudo", "system prompt",
    "jailbreak", "DAN mode", "pretend you are",
]

def detect_prompt_injection(text: str) -> bool:
    """Check if input text contains prompt injection patterns."""
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in PROMPT_INJECTION_PATTERNS)


def validate_sku_exists(sku_id: str, valid_skus: list) -> bool:
    """Check that a SKU ID exists in the known dataset."""
    return sku_id in valid_skus


def validate_location_exists(location: str, valid_locations: list) -> bool:
    """Check that a location exists in the known dataset."""
    return location in valid_locations


def format_currency(amount: float) -> str:
    """Format a number as Indian Rupees."""
    return f"\u20b9{amount:,.2f}"
