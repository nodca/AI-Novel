"""Claude API client wrapper with fallback support."""
import time
import logging
from typing import Any, Dict

from anthropic import Anthropic

logger = logging.getLogger(__name__)

DEFAULT_PRICING_USD_PER_MILLION: Dict[str, Dict[str, float]] = {
    "__opus__": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_write": 18.75,
    },
    "__sonnet__": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_write": 3.75,
    },
    "__default__": {
        "input": 4.0,
        "output": 20.0,
        "cache_read": 0.4,
        "cache_write": 5.0,
    },
}


class ClaudeClient:
    def __init__(self, config: dict):
        api_cfg = config["anthropic"]
        writing_api_key = api_cfg.get("writing_api_key") or api_cfg.get("api_key", "")
        writing_base_url = api_cfg.get("writing_base_url") or api_cfg.get("base_url", "https://api.anthropic.com")
        analysis_api_key = api_cfg.get("analysis_api_key") or writing_api_key
        analysis_base_url = api_cfg.get("analysis_base_url") or writing_base_url

        self.writing_client = Anthropic(
            api_key=writing_api_key,
            base_url=writing_base_url,
        )
        # Keep backward compatibility for older call paths expecting `self.client`.
        self.client = self.writing_client
        if analysis_api_key == writing_api_key and analysis_base_url == writing_base_url:
            self.analysis_client = self.writing_client
        else:
            self.analysis_client = Anthropic(
                api_key=analysis_api_key,
                base_url=analysis_base_url,
            )
        self.writing_model = api_cfg.get("writing_model", "claude-opus-4-6-20260205")
        self.analysis_model = api_cfg.get("analysis_model", "claude-sonnet-4-6-20260219")
        self.writing_temperature = api_cfg.get("writing_temperature", 0.8)
        self.analysis_temperature = api_cfg.get("analysis_temperature", 0.3)
        self.max_retries = api_cfg.get("max_retries", 3)
        self.timeout = api_cfg.get("timeout", 600)
        self.pricing = self._build_pricing_map(api_cfg.get("pricing_usd_per_million", {}))

        telemetry = config.get("_telemetry", {})
        self.usage_callback = telemetry.get("usage_callback") if callable(telemetry.get("usage_callback")) else None
        self.stage_state = telemetry.get("stage_state") if isinstance(telemetry.get("stage_state"), dict) else {}
        self.telemetry_project_id = telemetry.get("project_id")
        self.telemetry_job_id = telemetry.get("job_id")
        self.telemetry_job_type = telemetry.get("job_type")

        # Fallback client
        fb = api_cfg.get("fallback", {})
        if fb.get("api_key"):
            self.fallback_client = Anthropic(
                api_key=fb["api_key"],
                base_url=fb.get("base_url", "https://api.anthropic.com"),
            )
        else:
            self.fallback_client = None

    def _call(self, client: Anthropic, model: str, prompt: str, max_tokens: int = 8192,
              temperature: float = 0.3, system: str = None) -> str:
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": messages, "temperature": temperature, "timeout": self.timeout}
        if system:
            kwargs["system"] = system

        for attempt in range(self.max_retries):
            try:
                started = time.monotonic()
                resp = client.messages.create(**kwargs)
                self._emit_usage(resp, model, started, provider="anthropic")
                return resp.content[0].text
            except Exception as e:
                logger.warning("API call failed (attempt %d): %s", attempt + 1, e)
                # Try fallback on last primary attempt
                if attempt == self.max_retries - 1 and self.fallback_client:
                    logger.info("Trying fallback API...")
                    try:
                        started = time.monotonic()
                        resp = self.fallback_client.messages.create(**kwargs)
                        self._emit_usage(resp, model, started, provider="anthropic-fallback")
                        return resp.content[0].text
                    except Exception as e2:
                        logger.error("Fallback also failed: %s", e2)
                        raise
                elif attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def call_opus(self, prompt: str, max_tokens: int = 8192, system: str = None) -> str:
        return self._call(self.writing_client, self.writing_model, prompt, max_tokens, self.writing_temperature, system)

    def call_sonnet(self, prompt: str, max_tokens: int = 16384, system: str = None) -> str:
        return self._call(self.analysis_client, self.analysis_model, prompt, max_tokens, self.analysis_temperature, system)

    def _emit_usage(self, resp: Any, model: str, started: float, provider: str) -> None:
        if not self.usage_callback:
            return

        usage = getattr(resp, "usage", None)
        input_tokens = self._usage_int(usage, "input_tokens")
        output_tokens = self._usage_int(usage, "output_tokens")
        cache_creation_input_tokens = self._usage_int(usage, "cache_creation_input_tokens")
        cache_read_input_tokens = self._usage_int(usage, "cache_read_input_tokens")
        latency_ms = int((time.monotonic() - started) * 1000)

        event = {
            "project_id": self.telemetry_project_id,
            "job_id": self.telemetry_job_id,
            "job_type": self.telemetry_job_type,
            "chapter_number": self.stage_state.get("chapter"),
            "stage": self.stage_state.get("stage"),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "latency_ms": latency_ms,
            "cost_estimate_usd": self._estimate_cost(
                model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_input_tokens,
                cache_write_tokens=cache_creation_input_tokens,
            ),
        }
        try:
            self.usage_callback(event)
        except Exception as exc:  # pragma: no cover
            logger.warning("usage callback failed: %s", exc)

    def _estimate_cost(
        self,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> float:
        pricing = self._resolve_pricing(model)
        if not pricing:
            return 0.0

        total = (
            (input_tokens * pricing.get("input", 0.0))
            + (output_tokens * pricing.get("output", 0.0))
            + (cache_read_tokens * pricing.get("cache_read", 0.0))
            + (cache_write_tokens * pricing.get("cache_write", 0.0))
        ) / 1_000_000.0
        return round(total, 6)

    def _resolve_pricing(self, model: str) -> Dict[str, float]:
        if model in self.pricing:
            return self.pricing[model]
        lowered = model.lower()
        if "opus" in lowered and "__opus__" in self.pricing:
            return self.pricing["__opus__"]
        if "sonnet" in lowered and "__sonnet__" in self.pricing:
            return self.pricing["__sonnet__"]
        return self.pricing.get("__default__", {})

    @staticmethod
    def _usage_int(usage: Any, key: str) -> int:
        if usage is None:
            return 0
        if isinstance(usage, dict):
            value = usage.get(key, 0)
        else:
            value = getattr(usage, key, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _build_pricing_map(custom: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        pricing: Dict[str, Dict[str, float]] = {
            key: dict(value)
            for key, value in DEFAULT_PRICING_USD_PER_MILLION.items()
        }
        if not isinstance(custom, dict):
            return pricing

        for model_key, model_value in custom.items():
            if not isinstance(model_value, dict):
                continue
            pricing[model_key] = {
                "input": ClaudeClient._to_float(model_value.get("input"), 0.0),
                "output": ClaudeClient._to_float(model_value.get("output"), 0.0),
                "cache_read": ClaudeClient._to_float(model_value.get("cache_read"), 0.0),
                "cache_write": ClaudeClient._to_float(model_value.get("cache_write"), 0.0),
            }
        return pricing

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
