# AI-Generated Formula Launch Film

This folder is a ready-to-use kit for generating a 60-90 second AI video where famous formulas are treated like premium 3D products in a sneaker-style launch campaign.

## What is included

- `assets/reference_frames/`: exact formula reference images with glossy ad-style composition.
- `assets/style_targets/formula_launch_realistic_color.png`: realistic color commercial style target.
- `assets/style_targets/formula_launch_realistic_bw.png`: black-and-white commercial style target.
- `assets/style_targets/formula_launch_style_target.png`: earlier glossy reference kept for comparison.
- `assets/storyboard/mythic_formula_storyboard.png`: a visual overview of the full short.
- `docs/ai_video_prompts.md`: prompts to paste into Luma, Runway, Kling, LTX Studio, or a similar web AI tool.
- `docs/style_target.md`: the style brief to append to prompts when the AI tool needs stronger direction.
- `docs/shot_list.csv` and `docs/shot_list.json`: timing, filenames, and scene metadata.
- `scripts/assemble_video.py`: stitches generated clips into a final video using ffmpeg.
- `clips/input/`: put downloaded AI video clips here.
- `audio/`: optional music bed goes here.
- `output/`: final video output goes here.

## Fast workflow

1. Open `docs/ai_video_prompts.md`.
2. Open `docs/style_target.md` and keep the style target image visible.
3. For each shot, upload the matching reference frame from `assets/reference_frames/`.
4. If your AI tool supports multiple references, also upload `assets/style_targets/formula_launch_realistic_color.png` or `assets/style_targets/formula_launch_realistic_bw.png` as the style reference based on the shot mode.
5. Generate 2-4 variants and keep the most 3D, glossy, aggressive version.
6. Rename selected clips exactly like the target clip names listed in the prompt doc.
7. Put selected clips in `clips/input/`.
8. Optional: put a music file at `audio/music.mp3`, `audio/music.wav`, or `audio/music.m4a`.
9. Run:

```bash
python3 formula_short_ai/scripts/assemble_video.py
```

The current storyboard image is:

`assets/storyboard/mythic_formula_storyboard.png`

## Direction Lock

This should feel like a premium sneaker campaign:

- glossy black studio floor
- hard rim lights and colored accent strips
- low wide-angle shots
- snap zooms, whip pans, speed ramps, Dutch angles
- formulas as thick physical 3D objects
- wet reflective black studio floor, haze, practical light tubes, micro-scratches, imperfect reflections
- black-and-white impact shots are allowed and should still feel like the same campaign
- no museum, no classroom, no chalkboard, no flat title-card feeling

## Expected clip filenames

- `01_blackout_launch.mp4`
- `02_pythagorean.mp4`
- `03_euler_identity.mp4`
- `04_quadratic.mp4`
- `05_fourier.mp4`
- `06_gaussian.mp4`
- `07_maxwell.mp4`
- `08_newton.mp4`
- `09_taylor.mp4`
- `10_formula_campaign.mp4`
