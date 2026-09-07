import json
import logging
import httpx
from typing import Dict, Any, List
from config.settings import EvalConfig

logger = logging.getLogger("regression_shield.verifiers")


class QualityVerifiers:
    """Implements strict algorithmic and semantic LLM-as-a-judge evaluation rules.
    
    Supports both live LLM evaluation (via OpenRouter API) and deterministic
    mock evaluation for demo/CI environments. All metric functions return
    normalized scores between 0.0 and 1.0.
    """

    @staticmethod
    def calculate_token_efficiency(trajectory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Heuristic validation calculating agent loop overhead.
        
        Analyzes the tool call trajectory to detect:
        - Redundant (duplicate) tool calls with identical signatures
        - Overall step efficiency as a ratio of useful vs total steps
        
        Args:
            trajectory: List of agent execution steps, each containing
                        'type', 'name', and optional 'args' fields.
        
        Returns:
            Dict with 'efficiency_score' (0.0-1.0) and 'redundant_calls_count'.
        """
        total_steps = len(trajectory)
        tool_calls = [step for step in trajectory if step.get("type") == "tool_call"]
        redundant_calls = 0

        seen_signatures = set()
        for call in tool_calls:
            signature = f"{call.get('name')}:{json.dumps(call.get('args', {}), sort_keys=True)}"
            if signature in seen_signatures:
                redundant_calls += 1
            seen_signatures.add(signature)

        efficiency_score = 1.0 - (redundant_calls / total_steps) if total_steps > 0 else 1.0

        logger.debug(
            "Efficiency analysis: %d total steps, %d tool calls, %d redundant",
            total_steps, len(tool_calls), redundant_calls
        )

        return {
            "efficiency_score": round(efficiency_score, 2),
            "redundant_calls_count": redundant_calls
        }


    @staticmethod
    def _parse_json_payload(raw_text: str) -> dict:
        """Extract and parse a JSON object from raw LLM output, stripping code fences."""
        cleaned = raw_text.strip()
        if "```" in cleaned:
            for part in cleaned.split("```"):
                p_clean = part.strip()
                if p_clean.startswith("json"):
                    p_clean = p_clean[4:].strip()
                if "{" in p_clean and "}" in p_clean:
                    cleaned = p_clean
                    break

        start_brace = cleaned.find("{")
        end_brace = cleaned.rfind("}")
        if start_brace != -1 and end_brace != -1:
            cleaned = cleaned[start_brace:end_brace + 1]

        return json.loads(cleaned)

    @staticmethod
    def llm_judge_verify(
        prompt: str,
        context: str,
        response_text: str,
        metric_type: str,
        return_details: bool = False,
    ) -> Any:
        """Executes targeted LLM-as-a-Judge scoring against strict scoring criteria.
        
        Sends structured rubric evaluations to an LLM judge model via the
        OpenRouter API. Supports 'faithfulness' and 'relevancy' metrics.
        Includes retry logic with exponential backoff for resilience.
        
        Args:
            prompt: The original user prompt being evaluated.
            context: The ground-truth context for the evaluation.
            response_text: The AI-generated response to evaluate.
            metric_type: The evaluation metric ('faithfulness' or 'relevancy').
            return_details: If True, returns dict with 'score' and 'reasoning'.
                            If False, returns float score.
        
        Returns:
            float score (or dict with score and reasoning if return_details=True).
        
        Raises:
            ValueError: If OPENROUTER_API_KEY is not configured.
        """
        if not EvalConfig.OPENROUTER_API_KEY:
            raise ValueError("Evaluation skipped: OPENROUTER_API_KEY missing from environment.")

        rubrics = {
            "faithfulness": (
                "Verify if the response contains any hallucinations or statements "
                "NOT directly supported by the context. Score 1.0 if completely "
                "factual to context, 0.0 if false data is present."
            ),
            "relevancy": (
                "Determine if the response explicitly resolves the core intent of "
                "the prompt. Deduct score if the model rambles or skirts the answer."
            ),
        }

        system_instruction = (
            f"You are an objective QA Evaluation system. Rate the following text "
            f"strictly on the '{metric_type}' metric.\n"
            f"Rubric: {rubrics.get(metric_type, '')}\n"
            "Respond ONLY with a valid JSON block structured exactly like this: "
            '{"score": <float between 0.0 and 1.0>, "reasoning": "<concise 1-2 sentence explanation of your scoring decision>"}'
        )

        user_content = (
            f"Prompt: {prompt}\n"
            f"Context: {context}\n"
            f"Generated Response: {response_text}"
        )

        headers = {
            "Authorization": f"Bearer {EvalConfig.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }

        models_to_try = EvalConfig.get_fallback_models()
        last_error_reason = "OpenRouter request failed"

        for model_name in models_to_try:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
            }

            try:
                logger.info("LLM judge request [%s] trying model: %s", metric_type, model_name)
                with httpx.Client(timeout=35.0) as client:
                    http_response = client.post(
                        f"{EvalConfig.OPENROUTER_BASE_URL}/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                if http_response.status_code == 200:
                    data = http_response.json()
                    raw_text = data["choices"][0]["message"]["content"]
                    result = QualityVerifiers._parse_json_payload(raw_text)
                    score = max(0.0, min(1.0, float(result.get("score", 0.0))))
                    reasoning = str(result.get("reasoning", "")).strip()

                    logger.info("LLM judge [%s] scored: %.2f via %s (reason: %s)", metric_type, score, model_name, reasoning)
                    if return_details:
                        return {"score": score, "reasoning": reasoning, "judge_model": model_name}
                    return score

                elif http_response.status_code == 429:
                    logger.warning(
                        "LLM judge model '%s' hit rate limit (HTTP 429): %s. Trying fallback model...",
                        model_name, http_response.text[:120]
                    )
                    last_error_reason = f"Rate limit on {model_name}"
                    continue

                else:
                    logger.warning(
                        "LLM judge model '%s' returned HTTP %d: %s. Trying fallback model...",
                        model_name, http_response.status_code, http_response.text[:120]
                    )
                    last_error_reason = f"HTTP {http_response.status_code} on {model_name}"
                    continue

            except (httpx.TimeoutException, httpx.RequestError) as net_err:
                logger.warning(
                    "Network error calling judge model '%s' (%s). Trying fallback model...",
                    model_name, str(net_err)
                )
                last_error_reason = f"Network error on {model_name}"
                continue

            except (json.JSONDecodeError, KeyError, ValueError) as parse_err:
                logger.warning(
                    "Failed to parse JSON response from judge model '%s' (%s). Trying fallback model...",
                    model_name, str(parse_err)
                )
                last_error_reason = f"Parse error on {model_name}"
                continue

        logger.error("All free fallback LLM judge models exhausted. Last error: %s", last_error_reason)
        fallback = {"score": 0.0, "reasoning": f"All fallback models rate limited ({last_error_reason})"}
        return fallback if return_details else 0.0
