"""Bound the v2.0.3 CT2 attention decoder by Whisper's positional capacity.

The pinned backend forwards max_new_tokens without subtracting the prompt.
Continuation prompts can contain many tokens even when they contain few words.
"""
import logging


def install_decoder_guard(model):
    engine = model._engine  # Pinned CrisperWhisper 2.0.3 CT2 implementation.
    original = engine.generate_greedy_with_attention

    def bounded_decode(features, prompt_tokens, *, max_new_tokens, **kwargs):
        # Reserve one position for the decoder's final forward step.
        available = 448 - len(prompt_tokens) - 1
        if available < 1:
            raise ValueError("max_target_positions: continuation prompt fills the decoder")
        budget = min(max_new_tokens, available)
        if budget < max_new_tokens:
            logging.getLogger(__name__).warning(
                "[DECODER LIMIT] prompt=%d tokens; generation budget %d -> %d",
                len(prompt_tokens), max_new_tokens, budget,
            )
        return original(features, prompt_tokens, max_new_tokens=budget, **kwargs)

    engine.generate_greedy_with_attention = bounded_decode
