"""PCM encoding with headroom; attenuate oversized peaks instead of flat clipping."""
import numpy as np


def pcm16(samples):
    samples = np.asarray(samples, dtype=np.float32)
    if not np.isfinite(samples).all():
        raise ValueError("non-finite audio")
    peak = float(np.max(np.abs(samples))) if samples.size else 0.
    gain = min(1., .9 / peak) if peak else 1.
    return (samples * gain * 32767).astype("<i2").tobytes()
