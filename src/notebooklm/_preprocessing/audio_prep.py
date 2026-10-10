"""Prepare audio for transcription: a temporary, normalised, lossless FLAC.

Ported from ``audio-segment-extractor/src/audioseg/preprocess.py``. The input
(audio, or the audio track of a video) is decoded with ``ffmpeg`` and turned
into:

* mono, at the source's original sample rate;
* ``PCM_16`` (``PCM_24`` when the source is 24-bit or wider);
* 80 Hz high-pass (4th-order Butterworth, zero-phase);
* integrated loudness of −19 LUFS with peaks capped at −1 dBFS;
* lossless FLAC.

The source file is only read, never modified. The caller owns the returned
temp file and deletes it (see :func:`prepared_audio`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

TARGET_LUFS = -19.0
PEAK_CEILING_DBFS = -1.0
HIGHPASS_HZ = 80.0
HIGHPASS_ORDER = 4


class AudioPrepError(RuntimeError):
    """ffmpeg is missing or could not decode the input."""


@dataclass
class PreparedAudio:
    path: str
    sample_rate: int
    subtype: str
    source_bits: int | None
    loudness_before: float | None
    loudness_after: float | None
    peak_dbfs: float


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise AudioPrepError("ffmpeg is required to decode audio/video artifacts")
    return exe


def probe(path: str) -> dict[str, Any]:
    """``{sample_rate, channels, bits}`` of the first audio stream (``ffprobe``)."""
    exe = shutil.which("ffprobe")
    if exe is None:
        raise AudioPrepError("ffprobe is required to inspect audio/video artifacts")
    out = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,bits_per_raw_sample,bits_per_sample,sample_fmt",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise AudioPrepError(f"ffprobe failed: {out.stderr.strip()[:300]}")
    streams = json.loads(out.stdout or "{}").get("streams") or []
    if not streams:
        raise AudioPrepError("no audio stream found")
    s = streams[0]
    bits = 0
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            bits = max(bits, int(s.get(key) or 0))
        except (TypeError, ValueError):
            pass
    fmt = str(s.get("sample_fmt") or "")
    if not bits and fmt.startswith(("s32", "flt", "dbl")):
        bits = 32
    return {
        "sample_rate": int(s.get("sample_rate") or 0),
        "channels": int(s.get("channels") or 1),
        "bits": bits or None,
    }


def decode(path: str, sample_rate: int) -> Any:
    """Decode the first audio stream to a float32 mono numpy array at ``sample_rate``."""
    import numpy as np

    out = subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-nostdin",
            "-i",
            path,
            "-vn",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        raise AudioPrepError(f"ffmpeg decode failed: {out.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def highpass(samples: Any, sample_rate: int, cutoff: float = HIGHPASS_HZ) -> Any:
    from scipy.signal import butter, sosfiltfilt

    if len(samples) < 64:
        return samples
    sos = butter(HIGHPASS_ORDER, cutoff, btype="highpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos, samples).astype("float32")


def normalize(samples: Any, sample_rate: int) -> tuple[Any, float | None, float | None]:
    """Gain to −19 LUFS, then scale down if the peak would exceed −1 dBFS.

    Returns ``(samples, loudness_before, loudness_after)``. Clips too short or
    too quiet to measure are only peak-capped.
    """
    import numpy as np
    import pyloudnorm as pyln

    meter = pyln.Meter(sample_rate)
    before: float | None = None
    try:
        measured = float(meter.integrated_loudness(samples))
        before = measured if np.isfinite(measured) else None
    except ValueError:
        before = None
    out = samples
    if before is not None:
        out = samples * (10 ** ((TARGET_LUFS - before) / 20))
    ceiling = 10 ** (PEAK_CEILING_DBFS / 20)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > ceiling:
        out = out * (ceiling / peak)
    after: float | None = None
    if before is not None:
        try:
            measured = float(meter.integrated_loudness(out))
            after = measured if np.isfinite(measured) else None
        except ValueError:
            after = None
    return out.astype("float32"), before, after


def prepare_audio(source_path: str, out_dir: str | None = None) -> PreparedAudio:
    """Write the prepared FLAC to a new temp file and describe it."""
    import numpy as np
    import soundfile as sf

    info = probe(source_path)
    sample_rate = info["sample_rate"] or 48000
    samples = decode(source_path, sample_rate)
    if samples.size == 0:
        raise AudioPrepError("decoded audio is empty")
    samples = highpass(samples, sample_rate)
    samples, before, after = normalize(samples, sample_rate)
    bits = info["bits"]
    subtype = "PCM_24" if bits and bits >= 24 else "PCM_16"
    fd, out_path = tempfile.mkstemp(suffix=".flac", prefix="nblm-prep-", dir=out_dir)
    os.close(fd)
    try:
        sf.write(out_path, samples, sample_rate, format="FLAC", subtype=subtype)
    except Exception:
        os.unlink(out_path)
        raise
    peak = float(np.max(np.abs(samples)))
    return PreparedAudio(
        path=out_path,
        sample_rate=sample_rate,
        subtype=subtype,
        source_bits=bits,
        loudness_before=before,
        loudness_after=after,
        peak_dbfs=20 * float(np.log10(peak)) if peak > 0 else float("-inf"),
    )


@contextmanager
def prepared_audio(source_path: str, out_dir: str | None = None) -> Iterator[PreparedAudio]:
    """:func:`prepare_audio`, deleting the temp FLAC on exit (also on error)."""
    prepared = prepare_audio(source_path, out_dir)
    try:
        yield prepared
    finally:
        try:
            os.unlink(prepared.path)
        except FileNotFoundError:
            pass
