from __future__ import annotations

from pathlib import Path
from shutil import which
import math
import struct
import subprocess
import tempfile
import wave


def write_mock_wav(
    path: Path,
    duration_seconds: float,
    frequency_hz: float = 440.0,
    sample_rate: int = 24_000,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = max(1, int(duration_seconds * sample_rate))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        frames = bytearray()
        for frame in range(total_frames):
            value = int(
                0.12
                * 32767
                * math.sin(2 * math.pi * frequency_hz * frame / sample_rate)
            )
            frames.extend(struct.pack("<h", value))
        wav.writeframes(bytes(frames))


def concatenate_wavs(
    segment_paths: list[Path], output_path: Path, silence_ms: int = 120
) -> Path:
    if not segment_paths:
        raise ValueError("Cannot concatenate an empty list of WAV files.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(segment_paths[0]), "rb") as first:
        params = first.getparams()
        audio_params = (
            params.nchannels,
            params.sampwidth,
            params.framerate,
            params.comptype,
            params.compname,
        )

    silence_frames = int(params.framerate * silence_ms / 1000)
    silence = b"\x00" * silence_frames * params.nchannels * params.sampwidth

    with wave.open(str(output_path), "wb") as output:
        output.setparams(params)

        for index, segment_path in enumerate(segment_paths):
            with wave.open(str(segment_path), "rb") as segment:
                segment_params = segment.getparams()
                current_params = (
                    segment_params.nchannels,
                    segment_params.sampwidth,
                    segment_params.framerate,
                    segment_params.comptype,
                    segment_params.compname,
                )
                if current_params != audio_params:
                    raise ValueError(
                        f"WAV parameters for `{segment_path}` do not match the first segment."
                    )

                output.writeframes(segment.readframes(segment.getnframes()))
                if index < len(segment_paths) - 1:
                    output.writeframes(silence)

    return output_path


def concatenate_audio_files(segment_paths: list[Path], output_path: Path) -> Path:
    """Stitch audio segments end-to-end, trimming the silence padding that
    TTS providers (ElevenLabs especially) bake into each clip's edges.
    Without trimming, every segment boundary leaves an audible 300-600ms gap.
    """
    if not segment_paths:
        raise ValueError("Cannot concatenate an empty list of audio files.")
    if which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to assemble compressed audio segments.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # silenceremove twice via areverse trims silence from BOTH ends of each
    # input. Threshold -45dB / 80ms covers the typical ElevenLabs padding
    # without clipping the voice. Then concat the trimmed streams.
    n = len(segment_paths)
    trim = (
        "silenceremove=start_periods=1:start_silence=0.08:start_threshold=-45dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.08:start_threshold=-45dB,"
        "areverse"
    )
    filter_parts = [f"[{i}:a]{trim}[a{i}]" for i in range(n)]
    concat_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[out]")
    filter_complex = ";".join(filter_parts)

    args: list[str] = ["ffmpeg", "-y"]
    for path in segment_paths:
        args.extend(["-i", str(path)])
    args.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_path),
        ]
    )

    try:
        subprocess.run(args, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed to assemble audio: {exc.stderr}") from exc

    return output_path


def audio_duration_seconds(path: Path) -> float | None:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / wav.getframerate()

    if which("ffprobe") is None:
        return None

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
