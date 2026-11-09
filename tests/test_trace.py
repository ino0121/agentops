from aops.trace import price_name, token_usage


def test_claude_usage_counts_cache_in_input():
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 1121, "cache_read_input_tokens": 22652, "output_tokens": 249,
             "cache_creation": {"ephemeral_1h_input_tokens": 1121, "ephemeral_5m_input_tokens": 0}}
    assert token_usage(usage) == {"input_tokens": 23775, "output_tokens": 249, "total_tokens": 24024,
                                  "cache_read_input_tokens": 22652, "cache_creation_input_tokens": 1121,
                                  "cache_creation_input_tokens_above_1hr": 1121}


def test_codex_usage_takes_this_turn():
    usage = {"total": {"inputTokens": 41143, "outputTokens": 242, "totalTokens": 41385},
             "turn": {"inputTokens": 20720, "cachedInputTokens": 20420, "cacheWriteInputTokens": 297,
                      "outputTokens": 144, "totalTokens": 20864}}
    assert token_usage(usage) == {"input_tokens": 20720, "output_tokens": 144, "total_tokens": 20864,
                                  "cache_read_input_tokens": 20420, "cache_creation_input_tokens": 297}


def test_no_usage_and_price_names():
    assert token_usage({}) is None
    assert price_name("system.ai.claude-opus-5-5") == "claude-opus-5-5"
    assert price_name("gpt-6-sol") == "gpt-6-sol" and price_name(None) is None
