# Critic-Free Group-Relative Advantage for LLM Reasoning RL

## Motivation
PPO fine-tuning of LLMs for math reasoning carries a value/critic network as large as the policy itself. It is costly in memory (it roughly doubles the trainable footprint and optimizer state) and is a source of high-variance advantage estimates that destabilize training. The field treats the learned value baseline as a given because the actor-critic template is inherited from general RL, where states cannot be re-sampled. But in verifiable-reward reasoning you *can* sample many completions per prompt and score each — an empirical baseline that no method in this setting exploits to remove the critic. The open question: is the learned value network necessary at all here?

## Method
1. For each prompt, sample a group of G completions from the current policy (G in {4,8,16}).
2. Score each completion with the programmatic answer-checker → rewards r_1..r_G.
3. Compute the group mean r̄ and standard deviation s.
4. Set each completion's advantage A_i = (r_i − r̄) / (s + ε), broadcast to its tokens.
5. Update the policy with the standard PPO clipped surrogate using A_i, plus a KL-to-reference penalty. No value network, no value loss, no critic optimizer state.
6. Ablation: replace the group baseline with a learned value head to recover standard PPO for comparison.
