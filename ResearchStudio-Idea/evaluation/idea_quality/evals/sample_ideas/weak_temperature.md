# Learnable Per-Head Attention Temperature for Faster Transformers

## Motivation
Transformer language models could be a bit faster at inference. Attention is a core cost, and it would be nice if the model could spend less effort on it. We think giving each attention head more control over its own behavior could help with this.

## Method
1. Add a single learnable temperature scalar τ_h per attention head.
2. Divide the attention logits by τ_h before the softmax, so each head can sharpen or flatten its attention distribution.
3. Train τ_h jointly with the rest of the model during normal training; no other changes.
4. At inference, use the learned τ_h values as-is.
