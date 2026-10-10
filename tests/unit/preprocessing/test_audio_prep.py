"""Temporary FLAC preparation (fact-52): mono, original rate, bit depth, 80 Hz HPF, -19 LUFS."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from notebooklm._preprocessing import audio_prep

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

RATE = 44100


def _signal(seconds: float = 3.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    speech = 0.05 * np.sin(2 * np.pi * 1000 * t)
    rumble = 0.05 * np.sin(2 * np.pi * 25 * t)
    return (speech + rumble).astype(np.float32)


def _write(path: Path, subtype: str, stereo: bool = True) -> Path:
    mono = _signal()
    data = np.stack([mono, mono * 0.5], axis=1) if stereo else mono
    sf.write(path, data, RATE, subtype=subtype)
    return path


def _band_energy(x: np.ndarray, rate: int, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    return float(spec[(freqs >= lo) & (freqs <= hi)].sum())


def test_prepare_24bit_stereo_wav(tmp_path: Path) -> None:
    src = _write(tmp_path / "in.wav", "PCM_24")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    with audio_prep.prepared_audio(str(src), str(tmp_path)) as prep:
        info = sf.info(prep.path)
        assert info.format == "FLAC" and info.subtype == "PCM_24"
        assert info.channels == 1 and info.samplerate == RATE
        assert prep.source_bits == 24
        out, _ = sf.read(prep.path, dtype="float32")
        assert prep.loudness_after is not None
        assert prep.loudness_after == pytest.approx(audio_prep.TARGET_LUFS, abs=0.5)
        assert 20 * np.log10(np.max(np.abs(out))) <= audio_prep.PEAK_CEILING_DBFS + 0.05
        src_mono = _signal()
        ratio_in = _band_energy(src_mono, RATE, 15, 35) / _band_energy(src_mono, RATE, 900, 1100)
        ratio_out = _band_energy(out, RATE, 15, 35) / _band_energy(out, RATE, 900, 1100)
        assert ratio_out < ratio_in / 20  # 25 Hz rumble removed by the 80 Hz high-pass
        temp_path = prep.path
    assert not os.path.exists(temp_path)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before  # original untouched


def test_prepare_16bit_mono_and_cleanup_on_error(tmp_path: Path) -> None:
    src = _write(tmp_path / "in16.wav", "PCM_16", stereo=False)
    seen = {}
    with (
        pytest.raises(RuntimeError),
        audio_prep.prepared_audio(str(src), str(tmp_path)) as prep,
    ):
        seen["path"] = prep.path
        assert sf.info(prep.path).subtype == "PCM_16"
        raise RuntimeError("transcriber failed")
    assert not os.path.exists(seen["path"])


def test_video_audio_track(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=2",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    prep = audio_prep.prepare_audio(str(video), str(tmp_path))
    try:
        info = sf.info(prep.path)
        assert info.channels == 1 and info.samplerate == 44100
    finally:
        os.unlink(prep.path)


def test_errors(tmp_path: Path) -> None:
    bogus = tmp_path / "not-audio.txt"
    bogus.write_text("hello")
    with pytest.raises(audio_prep.AudioPrepError):
        audio_prep.prepare_audio(str(bogus))
    with pytest.raises(audio_prep.AudioPrepError):
        audio_prep.decode(str(bogus), 16000)


def test_normalize_quiet_and_short_inputs() -> None:
    silent = np.zeros(1000, dtype=np.float32)
    out, before, after = audio_prep.normalize(silent, RATE)
    assert before is None and after is None and float(np.max(np.abs(out))) == 0.0
    loud = np.full(100, 2.0, dtype=np.float32)
    out, _, _ = audio_prep.normalize(loud, RATE)
    assert float(np.max(np.abs(out))) == pytest.approx(10 ** (-1 / 20), rel=1e-4)
    assert audio_prep.highpass(loud[:10], RATE).shape == (10,)
