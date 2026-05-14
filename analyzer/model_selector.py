"""Smart model selector for OpenRouter free models.

Uses DeepSeek V4 Flash to select the best free models per task,
with 3-day caching to avoid redundant API calls.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Task descriptions for model selection
TASK_DESCRIPTIONS = {
    "cluster_classification": "从新闻/技术文章标题和描述中分类 cluster 属于哪个行业类别（如 AI、FinTech、Health、Security 等）",
    "rss_pain_extraction": "从 RSS newsletter 内容中提取用户痛点信号，识别用户抱怨的问题和需求",
    "sec_enrichment": "从 SEC Form D 文件中提取公司信息：公司名、行业、业务模式、融资额等结构化数据",
}

DEFAULT_FALLBACK_MODELS = [
    "openai/gpt-oss-120b:free",
    "inclusionai/ring-2.6-1t:free",
]

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
CACHE_PATH = "/home/kaige/Projects/TrendRadar/data/model-selector-cache.json"
CACHE_TTL_DAYS = 3
SNAPSHOT_TTL_DAYS = 1


def _get_openclaw_key(key_name: str) -> Optional[str]:
    """Load API key from environment or openclaw config."""
    key = os.environ.get(key_name)
    if key:
        return key
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("env", {}).get(key_name)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _get_openrouter_key() -> Optional[str]:
    return _get_openclaw_key("OPENROUTER_API_KEY")


def _get_deepseek_key() -> Optional[str]:
    return _get_openclaw_key("DEEPSEEK_API_KEY")


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    """Load cache from disk. Returns empty dict if missing or corrupt."""
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cache file corrupt, removing: %s", e)
        try:
            os.remove(CACHE_PATH)
        except OSError:
            pass
        return {}


def _save_cache(cache: dict) -> None:
    """Save cache to disk, creating parent dir if needed."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def _is_cache_valid(cache: dict, task: str) -> bool:
    """Check if cache entry for task is still valid."""
    selections = cache.get("selections", {})
    entry = selections.get(task)
    if not entry:
        return False
    try:
        selected_at = datetime.fromisoformat(entry["selected_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    return datetime.now(timezone.utc) - selected_at < timedelta(days=CACHE_TTL_DAYS)


def _is_snapshot_valid(cache: dict) -> bool:
    """Check if free models snapshot is still fresh."""
    try:
        snapshot_at = datetime.fromisoformat(cache.get("snapshot_at", "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - snapshot_at < timedelta(days=SNAPSHOT_TTL_DAYS)


# ---------------------------------------------------------------------------
# OpenRouter free models fetching
# ---------------------------------------------------------------------------

def fetch_free_models() -> list[str]:
    """Fetch all currently available :free models from OpenRouter API."""
    api_key = _get_openrouter_key()
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not available, using defaults")
        return []

    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models?filter=free",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        # Filter to only :free models, extract id and context info
        free_models = []
        for m in models:
            model_id = m.get("id", "")
            context = m.get("context_length", 0)
            if model_id and ":free" in model_id:
                free_models.append(f"{model_id} — {context}")
        logger.info("Fetched %d free models from OpenRouter", len(free_models))
        return free_models
    except Exception as e:
        logger.warning("Failed to fetch free models: %s", e)
        return []


# ---------------------------------------------------------------------------
# Model selection via DeepSeek
# ---------------------------------------------------------------------------

def select_best_models(task: str, free_models: list[str]) -> tuple[list[str], str]:
    """Use DeepSeek V4 Flash to select the top 2 best models for a task.

    DeepSeek V4 Flash uses reasoning mode where content may be empty.
    We parse JSON from either content or reasoning_content.

    Returns:
        (selected_models, reason)
    """
    api_key = _get_deepseek_key()
    if not api_key:
        logger.warning("DEEPSEEK_API_KEY not available, using defaults")
        return DEFAULT_FALLBACK_MODELS, "DeepSeek unavailable, using defaults"

    task_desc = TASK_DESCRIPTIONS.get(task, task)

    # Build model list string (limit to 10 most promising models for clarity)
    top_models = free_models[:10] if len(free_models) > 10 else free_models
    models_list = "\n".join(f"- {m}" for m in top_models)

    prompt = f"""从以下 OpenRouter 免费模型中选择最适合任务的 2 个模型。

任务: {task_desc}

模型列表 (model_id — context_length):
{models_list}

选择标准:
1. context window >= 64K
2. 适合分类/提取任务
3. 稳定可靠

在 reasoning 里分析后，必须在 content 输出最终 JSON:
{{"selected": ["model_id_1:free", "model_id_2:free"], "reason": "简短解释"}}"""

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
                "temperature": 0.0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        msg = result.get("choices", [{}])[0].get("message", {})
        
        # DeepSeek V4 Flash reasoning mode: content may be empty, JSON in reasoning_content
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        
        # Try to find JSON in content first, then in reasoning
        json_str = None
        for source in [content, reasoning]:
            if source:
                # Try direct parse
                try:
                    parsed = json.loads(source.strip())
                    json_str = source
                    break
                except json.JSONDecodeError:
                    # Try to extract JSON block with regex
                    import re
                    match = re.search(r'\{[^{}]*"selected"[^{}]*\}', source, re.DOTALL)
                    if match:
                        try:
                            parsed = json.loads(match.group())
                            json_str = match.group()
                            break
                        except json.JSONDecodeError:
                            pass
        
        if not json_str:
            # Last resort: extract model names from reasoning text
            if reasoning:
                model_pattern = r'([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+:free)'
                found = re.findall(model_pattern, reasoning)
                if len(found) >= 2:
                    logger.info("Extracted models from reasoning for %s: %s", task, found[:2])
                    return found[:2], "Extracted from reasoning"
            logger.warning("No valid JSON found in DeepSeek response for %s", task)
            return DEFAULT_FALLBACK_MODELS, "DeepSeek returned no JSON"

        parsed = json.loads(json_str)
        selected = parsed.get("selected", [])
        reason = parsed.get("reason", "")

        # Normalize to :free suffix
        models = []
        for m in selected:
            if ":free" not in m:
                m = m + ":free"
            models.append(m)

        # Ensure we have at least 2 models
        if len(models) < 2:
            models = models + DEFAULT_FALLBACK_MODELS[:2-len(models)]

        logger.info("DeepSeek selected models for %s: %s", task, models)
        return models[:2], reason

    except Exception as e:
        logger.error("DeepSeek model selection failed: %s", e)
        return DEFAULT_FALLBACK_MODELS, f"DeepSeek error: {e}"


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def get_models(task: str) -> list[str]:
    """Get selected models for a task, using cache if valid.

    Cache logic:
    - If selection for task is < 3 days old → return cached
    - If free models snapshot is < 1 day old → reuse it, reselect
    - Otherwise → fetch fresh models, then select
    """
    cache = _load_cache()
    selections = cache.get("selections", {})

    # Check if we have a valid cached selection
    if _is_cache_valid(cache, task):
        models = selections[task]["models"]
        logger.info("Cache hit for task %s: %s", task, models)
        return models

    # Determine which free models to use
    if _is_snapshot_valid(cache):
        free_models = cache.get("free_models_snapshot", [])
        logger.info("Using cached free models snapshot (%d models)", len(free_models))
    else:
        free_models = fetch_free_models()
        if not free_models:
            # No API access, use defaults
            logger.warning("No free models fetched, using defaults")
            return DEFAULT_FALLBACK_MODELS

    # Select best models for this task
    selected, reason = select_best_models(task, free_models)

    # Update cache
    now = datetime.now(timezone.utc).isoformat()
    cache.setdefault("selections", {})[task] = {
        "models": selected,
        "selected_at": now,
        "reason": reason,
    }
    cache["free_models_snapshot"] = free_models
    cache["snapshot_at"] = now
    cache["version"] = 1
    cache["ttl_days"] = CACHE_TTL_DAYS

    _save_cache(cache)
    logger.info("Updated cache for task %s: %s (%s)", task, selected, reason)

    return selected


def call_openrouter(
    prompt: str,
    task: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> dict:
    """Call OpenRouter with automatic fallback to second model.

    Args:
        prompt: The user prompt to send.
        task: Task key (e.g. 'cluster_classification') for model selection.
        max_tokens: Max tokens in response.
        temperature: Sampling temperature.

    Returns:
        OpenRouter API response dict.

    Raises:
        RuntimeError: If all models fail.
    """
    models = get_models(task)
    api_key = _get_openrouter_key()

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    for model in models:
        try:
            resp = requests.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                logger.warning("Rate limited on %s, trying fallback", model)
                time.sleep(2)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Model %s failed: %s, trying fallback", model, e)
            time.sleep(1)

    raise RuntimeError(f"All models failed for task {task}")


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    task = sys.argv[1] if len(sys.argv) > 1 else "cluster_classification"
    print(f"Testing model selector for task: {task}")
    models = get_models(task)
    print(f"Selected models: {models}")

    # Test a simple call
    test_prompt = "Classify this text into a category: 'AI startup raises $50M for autonomous agents'"
    try:
        result = call_openrouter(test_prompt, task, max_tokens=100)
        print(f"Call result: {result['choices'][0]['message']['content'][:100]}")
    except Exception as e:
        print(f"Call failed: {e}")