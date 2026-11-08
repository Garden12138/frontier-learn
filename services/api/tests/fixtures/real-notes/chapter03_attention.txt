"""Chapter 3 examples that build self-attention step by step."""

from __future__ import annotations

import torch
from torch import nn

from llm_from_scratch.attention import MultiHeadAttention


def softmax_naive(x: torch.Tensor) -> torch.Tensor:
    """Educational softmax formula; use torch.softmax in real model code."""
    exponentials = torch.exp(x)
    return exponentials / exponentials.sum(dim=0)


class SelfAttentionV1(nn.Module):
    """Single-example self-attention with explicit parameter matrices."""

    def __init__(self, d_in: int, d_out: int) -> None:
        super().__init__()
        self.W_query = nn.Parameter(torch.rand(d_in, d_out))
        self.W_key = nn.Parameter(torch.rand(d_in, d_out))
        self.W_value = nn.Parameter(torch.rand(d_in, d_out))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 2:
            raise ValueError("SelfAttentionV1 expects [num_tokens, d_in]")
        keys = x @ self.W_key
        queries = x @ self.W_query
        values = x @ self.W_value
        attention_scores = queries @ keys.transpose(0, 1)
        attention_weights = torch.softmax(
            attention_scores / (keys.size(-1) ** 0.5),
            dim=-1,
        )
        return attention_weights @ values


class SelfAttentionV2(nn.Module):
    """Single-example self-attention using optimized linear layers."""

    def __init__(self, d_in: int, d_out: int, qkv_bias: bool = False) -> None:
        super().__init__()
        self.W_query = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_key = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_value = nn.Linear(d_in, d_out, bias=qkv_bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 2:
            raise ValueError("SelfAttentionV2 expects [num_tokens, d_in]")
        keys = self.W_key(x)
        queries = self.W_query(x)
        values = self.W_value(x)
        attention_scores = queries @ keys.transpose(0, 1)
        attention_weights = torch.softmax(
            attention_scores / (keys.size(-1) ** 0.5),
            dim=-1,
        )
        return attention_weights @ values


class CausalAttention(nn.Module):
    """Educational single-head causal attention for batched inputs."""

    def __init__(
        self,
        d_in: int,
        head_dim: int,
        context_length: int,
        dropout: float,
        qkv_bias: bool = False,
    ) -> None:
        super().__init__()
        self.W_query = nn.Linear(d_in, head_dim, bias=qkv_bias)
        self.W_key = nn.Linear(d_in, head_dim, bias=qkv_bias)
        self.W_value = nn.Linear(d_in, head_dim, bias=qkv_bias)
        self.dropout = nn.Dropout(dropout)
        self.register_buffer(
            "mask",
            torch.triu(
                torch.ones(context_length, context_length, dtype=torch.bool),
                diagonal=1,
            ),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, num_tokens, _ = x.shape
        if num_tokens > self.mask.size(0):
            raise ValueError(
                f"Input has {num_tokens} tokens, but mask supports "
                f"{self.mask.size(0)}"
            )

        keys = self.W_key(x)
        queries = self.W_query(x)
        values = self.W_value(x)
        attention_scores = queries @ keys.transpose(1, 2)
        attention_scores.masked_fill_(
            self.mask[:num_tokens, :num_tokens],
            -torch.inf,
        )
        attention_weights = torch.softmax(
            attention_scores / (keys.size(-1) ** 0.5),
            dim=-1,
        )
        return self.dropout(attention_weights) @ values


class MultiHeadAttentionWrapper(nn.Module):
    """Educational implementation that stacks independent attention heads."""

    def __init__(
        self,
        d_in: int,
        head_dim: int,
        context_length: int,
        dropout: float,
        num_heads: int,
        qkv_bias: bool = False,
    ) -> None:
        super().__init__()
        self.heads = nn.ModuleList(
            [
                CausalAttention(
                    d_in=d_in,
                    head_dim=head_dim,
                    context_length=context_length,
                    dropout=dropout,
                    qkv_bias=qkv_bias,
                )
                for _ in range(num_heads)
            ]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.cat([head(x) for head in self.heads], dim=-1)


def build_demo_inputs() -> torch.Tensor:
    """Return the six token embeddings used throughout chapter 3."""
    return torch.tensor(
        [
            [0.43, 0.15, 0.89],  # Your
            [0.55, 0.87, 0.66],  # journey
            [0.57, 0.85, 0.64],  # starts
            [0.22, 0.58, 0.33],  # with
            [0.77, 0.25, 0.10],  # one
            [0.05, 0.80, 0.55],  # step
        ]
    )


def main() -> None:
    torch.manual_seed(123)
    inputs = build_demo_inputs()
    batch = torch.stack((inputs, inputs), dim=0)

    print("SelfAttentionV1:")
    print(SelfAttentionV1(d_in=3, d_out=2)(inputs))

    print("\nSelfAttentionV2:")
    print(SelfAttentionV2(d_in=3, d_out=2)(inputs))

    print("\nStacked educational heads:")
    wrapper = MultiHeadAttentionWrapper(
        d_in=3,
        head_dim=1,
        context_length=6,
        dropout=0.0,
        num_heads=2,
    )
    print(wrapper(batch))

    print("\nVectorized MultiHeadAttention:")
    attention = MultiHeadAttention(
        d_in=3,
        d_out=2,
        context_length=6,
        dropout=0.0,
        num_heads=2,
    )
    output = attention(batch)
    print(output)
    print("shape:", tuple(output.shape))


if __name__ == "__main__":
    main()
