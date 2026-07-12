"""Generate deterministic Task 4 audio and evidence metadata.

The browser recording is captured separately with playwright-cli. After recording,
pass ``--probe-recordings`` to persist canonical ffprobe evidence for both videos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_UNIT_PATH = ROOT / "data" / "curriculum" / "audio" / "02-advanced.json"
ASSET_DIR = ROOT / "data" / "assets" / "audio"
ASSET_PATH = ASSET_DIR / "task4-segmentation-alignment.wav"
AUTHORIZATION_PATH = ASSET_DIR / "task4-segmentation-alignment.authorization.json"
EVIDENCE_DIR = ROOT / "evidence" / "audio-learning-chain"
RECORDING_METADATA_PATH = EVIDENCE_DIR / "recording-metadata.json"
WEBM_PATH = EVIDENCE_DIR / "learning-loop.webm"
MP4_PATH = EVIDENCE_DIR / "learning-loop.mp4"
WEBM_PROBE_PATH = EVIDENCE_DIR / "ffprobe-webm.json"
MP4_PROBE_PATH = EVIDENCE_DIR / "ffprobe-mp4.json"

SAMPLE_RATE = 16_000
DURATION_SECONDS = 3.9
FRAME_COUNT = round(SAMPLE_RATE * DURATION_SECONDS)
MAX_AMPLITUDE = 12_000
TARGET_UNIT_ID = "TU-AUDIO-SEGMENTATION-ALIGNMENT-001"
TARGET_ERROR_TYPE = "boundary_alignment_mismatch"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    path.write_text(f"{rendered}\n", encoding="utf-8", newline="\n")


def load_target_unit() -> dict[str, Any]:
    document = json.loads(SOURCE_UNIT_PATH.read_text(encoding="utf-8"))
    units = [unit for unit in document["units"] if unit["id"] == TARGET_UNIT_ID]
    if len(units) != 1:
        raise ValueError(f"Expected one {TARGET_UNIT_ID}, found {len(units)}")
    return units[0]


def smooth_gate(local_time: float, duration: float) -> float:
    """Return a short deterministic attack/release envelope."""
    ramp = 0.035
    attack = min(1.0, local_time / ramp)
    release = min(1.0, (duration - local_time) / ramp)
    return max(0.0, min(attack, release))


def voiced_sample(time_seconds: float, start: float, end: float, base_hz: float) -> int:
    if not start <= time_seconds < end:
        return 0
    local_time = time_seconds - start
    duration = end - start
    envelope = smooth_gate(local_time, duration)
    phrase_pulse = 0.72 + 0.28 * math.sin(2.0 * math.pi * 3.1 * local_time) ** 2
    value = (
        math.sin(2.0 * math.pi * base_hz * local_time)
        + 0.38 * math.sin(2.0 * math.pi * base_hz * 2.0 * local_time)
        + 0.17 * math.sin(2.0 * math.pi * base_hz * 3.0 * local_time)
    )
    return round(MAX_AMPLITUDE * envelope * phrase_pulse * value / 1.55)


def generate_pcm_frames() -> bytes:
    samples: list[int] = []
    for frame_index in range(FRAME_COUNT):
        time_seconds = frame_index / SAMPLE_RATE
        sample = voiced_sample(time_seconds, 0.4, 1.55, 196.0)
        sample += voiced_sample(time_seconds, 2.1, 3.35, 246.0)
        sample = max(-32_768, min(32_767, sample))
        samples.append(sample)
    return struct.pack(f"<{len(samples)}h", *samples)


def generate_audio() -> str:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ASSET_PATH), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.setcomptype("NONE", "not compressed")
        audio.writeframes(generate_pcm_frames())
    return hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest()


def write_authorization(digest: str) -> None:
    write_json(
        AUTHORIZATION_PATH,
        {
            "asset_id": "ASSET-AUDIO-TASK4-TONE-SILENCE-TONE-001",
            "authorization": {
                "contains_personal_data": False,
                "development_publication_allowed": True,
                "statement": (
                    "This synthetic tone-silence-tone sample was generated locally "
                    "for Task 4 by the repository script; it contains no recorded voice, "
                    "third-party performance, or personal data."
                ),
                "student_use_allowed": True,
                "type": "self-authored",
            },
            "file": ASSET_PATH.name,
            "generation": {
                "algorithm": "deterministic_harmonic_tone_with_fixed_envelope",
                "deterministic": True,
                "script": "scripts/generate_task4_audio_evidence.py",
                "speech_anchor_surrogates_ms": [
                    {"end_ms": 1550, "start_ms": 400},
                    {"end_ms": 3350, "start_ms": 2100},
                ],
            },
            "schema_version": "1.0.0",
            "sha256": digest,
            "technical_metadata": {
                "channels": 1,
                "codec": "PCM signed 16-bit little-endian",
                "duration_seconds": DURATION_SECONDS,
                "frame_count": FRAME_COUNT,
                "sample_rate_hz": SAMPLE_RATE,
                "sample_width_bytes": 2,
            },
        },
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recording_artifacts() -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for key, recording, probe_path in (
        ("webm", WEBM_PATH, WEBM_PROBE_PATH),
        ("mp4", MP4_PATH, MP4_PROBE_PATH),
    ):
        if not recording.is_file() or not probe_path.is_file():
            continue
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        video = next(
            stream for stream in probe["streams"] if stream["codec_type"] == "video"
        )
        artifacts[key] = {
            "codec": video["codec_name"],
            "duration_seconds": float(probe["format"]["duration"]),
            "ffprobe_file": probe_path.relative_to(ROOT).as_posix(),
            "file": recording.relative_to(ROOT).as_posix(),
            "height": int(video["height"]),
            "sha256": file_sha256(recording),
            "size_bytes": recording.stat().st_size,
            "width": int(video["width"]),
        }
    for key, screenshot in (
        ("screenshot", EVIDENCE_DIR / "learning-loop-desktop.png"),
        ("mobile_screenshot", EVIDENCE_DIR / "learning-loop-mobile.png"),
    ):
        if not screenshot.is_file():
            continue
        payload = screenshot.read_bytes()
        if payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Screenshot is not a PNG: {screenshot}")
        width, height = struct.unpack(">II", payload[16:24])
        artifacts[key] = {
            "file": screenshot.relative_to(ROOT).as_posix(),
            "height": height,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "width": width,
        }
    return artifacts


def write_recording_metadata(unit: dict[str, Any], digest: str) -> None:
    exercise = unit["exercise"]
    diagnostic = next(
        rule
        for rule in exercise["evaluation"]["diagnostic_rules"]
        if rule["error_type"] == TARGET_ERROR_TYPE
    )
    mapping = next(
        item
        for item in unit["learning_path"]["error_mappings"]
        if item["error_type"] == TARGET_ERROR_TYPE
    )
    write_json(
        RECORDING_METADATA_PATH,
        {
            "automated_browser": "playwright-cli",
            "artifacts": recording_artifacts(),
            "correct_retry": {
                "capability_refs": exercise["capability_refs"],
                "passed": True,
                "score": 1.0,
                "submission": exercise["answer"],
            },
            "evidence_flow": [
                "read_project_policy",
                "submit_wrong_boundary_attempt",
                "receive_rule_linked_feedback",
                "open_remediation",
                "apply_speech_anchor_boundaries",
                "submit_successful_retry",
            ],
            "exercise_id": exercise["exercise_id"],
            "generated_audio_sha256": digest,
            "recording_script": "evidence/audio-learning-chain/record-learning-loop.js",
            "source_audio_file": "data/assets/audio/task4-segmentation-alignment.wav",
            "source_unit_file": "data/curriculum/audio/02-advanced.json",
            "unit_id": unit["id"],
            "viewport": {"height": 800, "width": 1280},
            "wrong_attempt": {
                "capability_refs": mapping["capability_refs"],
                "error_type": diagnostic["error_type"],
                "feedback": diagnostic["feedback"],
                "passed": False,
                "remediation": diagnostic["remediation"],
                "remediation_resource_refs": mapping["remediation_resource_refs"],
                "rule_refs": mapping["rule_refs"],
                "score": 0.0,
                "submission": diagnostic["submission"],
            },
        },
    )


def find_ffprobe() -> str:
    executable = shutil.which("ffprobe")
    if not executable:
        raise RuntimeError("ffprobe is required for --probe-recordings")
    return executable


def probe_recording(recording: Path, destination: Path) -> None:
    if not recording.is_file() or recording.stat().st_size == 0:
        raise FileNotFoundError(f"Recording is missing or empty: {recording}")
    completed = subprocess.run(
        [
            find_ffprobe(),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(recording),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    write_json(destination, json.loads(completed.stdout))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe-recordings",
        action="store_true",
        help="also write ffprobe JSON for the existing WebM and MP4 recordings",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    digest = generate_audio()
    unit = load_target_unit()
    write_authorization(digest)
    if args.probe_recordings:
        probe_recording(WEBM_PATH, WEBM_PROBE_PATH)
        probe_recording(MP4_PATH, MP4_PROBE_PATH)
    write_recording_metadata(unit, digest)
    print(f"audio_sha256={digest}")
    print(f"audio_frames={FRAME_COUNT}")
    print(f"audio_duration_seconds={DURATION_SECONDS:.6f}")


if __name__ == "__main__":
    main()
