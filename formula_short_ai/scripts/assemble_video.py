#!/usr/bin/env python3
"""Assemble downloaded AI clips into the final mythic formula short."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
INPUT_DIR = ROOT / "clips" / "input"
SELECTED_DIR = ROOT / "clips" / "selected"
OUTPUT_DIR = ROOT / "output"
WORK_DIR = ROOT / "output" / "_assembly_work"
AUDIO_DIR = ROOT / "audio"

VIDEO_SIZE = "1920:1080"
FPS = "24"
FINAL = OUTPUT_DIR / "mythic_formula_short.mp4"
PREVIEW = OUTPUT_DIR / "mythic_formula_reference_preview.mp4"


def run(cmd: list[str]) -> None:
    print("+", " ".join(str(part) for part in cmd))
    subprocess.run(cmd, check=True)


def load_shots() -> list[dict]:
    shot_file = DOCS_DIR / "shot_list.json"
    if not shot_file.exists():
        raise SystemExit("Missing docs/shot_list.json. Run generate_reference_assets.py first.")
    return json.loads(shot_file.read_text(encoding="utf-8"))


def find_music() -> Path | None:
    for name in ("music.mp3", "music.wav", "music.m4a", "music.aac", "music.flac"):
        candidate = AUDIO_DIR / name
        if candidate.exists():
            return candidate
    return None


def normalize_clip(source: Path, dest: Path) -> None:
    vf = (
        f"scale={VIDEO_SIZE}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_SIZE}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,format=yuv420p"
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(source),
            "-vf",
            vf,
            "-r",
            FPS,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            str(dest),
        ]
    )


def build_reference_preview(shots: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    preview_parts = []
    for idx, shot in enumerate(shots, start=1):
        image = ROOT / shot["reference_frame"]
        out = WORK_DIR / f"preview_{idx:02d}.mp4"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-loop",
                "1",
                "-t",
                str(min(4, shot["duration_seconds"])),
                "-i",
                str(image),
                "-vf",
                f"scale={VIDEO_SIZE},setsar=1,format=yuv420p",
                "-r",
                FPS,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                str(out),
            ]
        )
        preview_parts.append(out)
    concat(preview_parts, PREVIEW)


def concat(parts: list[Path], output: Path) -> None:
    list_file = WORK_DIR / "concat_list.txt"
    list_file.write_text("".join(f"file '{part.resolve()}'\n" for part in parts), encoding="utf-8")
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
        ]
    )


def assemble_final(shots: list[dict]) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    selected_sources = []
    missing = []
    for shot in shots:
        expected = INPUT_DIR / shot["clip_filename"]
        alternate = SELECTED_DIR / shot["clip_filename"]
        if expected.exists():
            selected_sources.append(expected)
        elif alternate.exists():
            selected_sources.append(alternate)
        else:
            missing.append(shot["clip_filename"])

    if missing:
        print("Missing AI clips:")
        for name in missing:
            print(f"  - {name}")
        print("\nBuilding a still-image reference preview instead.")
        build_reference_preview(shots)
        print(f"\nPreview written to: {PREVIEW}")
        return

    normalized = []
    for idx, source in enumerate(selected_sources, start=1):
        out = WORK_DIR / f"normalized_{idx:02d}.mp4"
        normalize_clip(source, out)
        normalized.append(out)

    silent = WORK_DIR / "silent_cut.mp4"
    concat(normalized, silent)

    music = find_music()
    if music:
        total_duration = sum(float(shot["duration_seconds"]) for shot in shots)
        fade_out_start = max(0, total_duration - 6)
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-i",
                str(silent),
                "-stream_loop",
                "-1",
                "-i",
                str(music),
                "-filter_complex",
                f"[1:a]volume=0.42,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=6[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-shortest",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(FINAL),
            ]
        )
    else:
        shutil.copyfile(silent, FINAL)

    print(f"\nFinal video written to: {FINAL}")


def main() -> None:
    shots = load_shots()
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    SELECTED_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    assemble_final(shots)


if __name__ == "__main__":
    main()
