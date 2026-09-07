"""Tests for OpenRouter Free Model Fallback Cascade.

Verifies:
1. Fallback configuration validity (deduplicated list, free tier models).
2. LLM Judge multi-model failover when primary model hits HTTP 429.
3. LiveToolAgent multi-model failover on rate limits.
"""

import pytest
from unittest.mock import patch, MagicMock
from config.settings import EvalConfig
from core.verifiers import QualityVerifiers
from agent.live_tool_agent import LiveToolAgent


class TestFallbackConfiguration:
    def test_fallback_models_exist_and_deduplicated(self):
        models = EvalConfig.get_fallback_models()
        assert len(models) >= 3
        # Assert no duplicates
        assert len(models) == len(set(models))
        # Assert each model is a valid OpenRouter free tier identifier
        for m in models:
            assert ":free" in m
        # Assert primary model is first
        assert models[0] == EvalConfig.JUDGE_MODEL

    def test_llm_judge_failover_on_429(self):
        """Simulate primary model returning 429 and verify fallback to second model."""
        mock_429_response = MagicMock()
        mock_429_response.status_code = 429
        mock_429_response.text = '{"error":{"message":"Rate limit exceeded: Daily limit reached for minimax/minimax-m3:free"}}'

        mock_200_response = MagicMock()
        mock_200_response.status_code = 200
        mock_200_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"score": 0.95, "reasoning": "Fallback model evaluated successfully."}'
                }
            }]
        }

        with patch("httpx.Client.post", side_effect=[mock_429_response, mock_200_response]) as mock_post:
            result = QualityVerifiers.llm_judge_verify(
                prompt="Explain photosynthesis",
                context="Photosynthesis is the process plants use to turn sunlight into food.",
                response_text="Plants convert sunlight into chemical energy.",
                metric_type="faithfulness",
                return_details=True,
            )

            assert mock_post.call_count == 2
            assert result["score"] == 0.95
            assert "Fallback model evaluated successfully" in result["reasoning"]

    def test_live_agent_failover_on_429(self):
        """Simulate LiveToolAgent failing over to fallback model on 429."""
        mock_429_response = MagicMock()
        mock_429_response.status_code = 429
        mock_429_response.text = '{"error":{"message":"Rate limit exceeded"}}'

        mock_200_response = MagicMock()
        mock_200_response.status_code = 200
        mock_200_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "I have completed the task.",
                    "tool_calls": None
                }
            }]
        }

        agent = LiveToolAgent(mode="baseline")
        with patch("httpx.Client.post", side_effect=[mock_429_response, mock_200_response]) as mock_post:
            res = agent._run_live_api_loop("Test prompt", max_steps=1, api_key="fake-key")
            assert mock_post.call_count == 2
            assert res["final_response"] == "I have completed the task."
