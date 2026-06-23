"""Per-request qua_sdk DeployConfig selection (WHERE/HOW the SDK stages run).

GPU path = the SDK's SPACE_ZEROGPU preset (float16, AOTI band, dynamic
batching) with ASR torch.compile forced OFF: ZeroGPU forks per lease so the
compile cache never amortizes, and dynamo crashes on the wav2vec2 mask path
(torch 2.8 + transformers 5.0 ConstantVariable assertion). CPU path = the
local-subprocess / worker / dev fallback: ``config.CPU_DTYPE`` (bfloat16
dodges the SDPA QK^T cache cliff), no compile, tighter 300s batch cap. The
choice is made inside the stage functions because the same code body runs in
three contexts: a ZeroGPU lease, a forced-CPU subprocess/worker (per-thread
flag or no CUDA), and plain local dev.
"""

from __future__ import annotations

from qua_sdk.deploy.presets import SPACE_ZEROGPU, BatchingConfig, DeployConfig

CPU_MAX_BATCH_SECONDS = 300


def gpu_deploy() -> DeployConfig:
    cfg = SPACE_ZEROGPU.model_copy(deep=True)
    cfg.torch_compile = False
    return cfg


def cpu_deploy() -> DeployConfig:
    from config import CPU_DTYPE
    return DeployConfig(
        name="space_cpu", device="cpu", dtype=CPU_DTYPE, torch_compile=False,
        batching=BatchingConfig(max_batch_seconds=CPU_MAX_BATCH_SECONDS),
    )


def select_deploy() -> DeployConfig:
    """Unconditionally returns CPU deploy config since this is a CPU-only pipeline."""
    return cpu_deploy()
