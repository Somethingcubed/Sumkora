#!/usr/bin/env python3
"""Generate exact reference frames and prompt docs for the formula launch short."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "output" / "_matplotlib_cache"))

import matplotlib.pyplot as plt
from matplotlib import patheffects
from PIL import Image, ImageDraw, ImageFilter


REF_DIR = ROOT / "assets" / "reference_frames"
STORYBOARD_DIR = ROOT / "assets" / "storyboard"
DOCS_DIR = ROOT / "docs"
WIDTH, HEIGHT = 1920, 1080

MASTER_STYLE = (
    "Unified visual style for every shot: ultra-realistic luxury product commercial cinematography, like a premium sneaker, "
    "fragrance, or car launch film. The formula is a real physical 3D hero object, not text: thick bevels, real chrome/brushed metal/"
    "rubber/ceramic/acrylic materials, micro-scratches, fingerprints, dust, haze, grounded shadows, wet black reflective studio floor, "
    "black void background, practical light tubes, hard rim lights, shallow depth of field, real lens behavior, subtle film grain, "
    "high contrast, expensive and physically plausible. Avoid artificial plastic CGI, game render, museum, classroom, chalkboard, "
    "flat poster, title card, infographic, educational explainer."
)


SCENES = [
    {
        "id": "01_blackout_launch",
        "title": "Blackout Launch",
        "style_mode": "realistic color hero",
        "duration": 6,
        "formula": r"\sum\;\int\;\pi\;\sqrt{\ }\;\nabla",
        "subtitle": "Symbols drop like a product reveal.",
        "material": "gloss black carbon fiber, chrome edges, vapor, hard white rim light",
        "camera": "wide-angle floor skim, snap zoom, Dutch angle, speed-ramped reveal",
        "prompt": (
            "High-end sneaker launch commercial style. A glossy black carbon-fiber studio floor, oversized floating 3D math symbols "
            "with chrome bevels and white rim lights, vapor jets, hard reflections, ultra-wide lens from ground level, snap zoom and "
            "Dutch angle reveal, fast speed ramp, black void background, no museum, no stone tablet, no people. The symbols are physical "
            "3D objects with thickness and reflections."
        ),
    },
    {
        "id": "02_pythagorean",
        "title": "Pythagorean Impact",
        "style_mode": "black-and-white impact",
        "duration": 7,
        "formula": r"a^2+b^2=c^2",
        "subtitle": "A formula lands like a shoe drop.",
        "material": "white ceramic 3D letters, black rubber base, red accent light",
        "camera": "formula slams down, dust ring, whip pan to low heroic angle",
        "prompt": (
            "A premium athletic sneaker advertisement shot, except the hero product is the exact 3D formula a^2 + b^2 = c^2. "
            "White ceramic extruded letters slam onto a glossy black rubber platform, red accent light, dust shockwave, floating triangular "
            "geometry pieces, low heroic wide-angle camera, whip pan, crisp reflections, dramatic studio lighting. Keep the equation readable."
        ),
    },
    {
        "id": "03_euler_identity",
        "title": "Euler Hero Product",
        "style_mode": "realistic color hero",
        "duration": 8,
        "formula": r"e^{i\pi}+1=0",
        "subtitle": "The flagship model.",
        "material": "liquid chrome 3D type, black acrylic plinth, cyan and amber rim lights",
        "camera": "360 product orbit, macro reflections, fast push through the zero",
        "prompt": (
            "A luxury product-ad hero shot: the exact equation e^{i pi} + 1 = 0 as thick liquid-chrome 3D lettering on a glossy black acrylic "
            "plinth, cyan and amber rim lights, high-speed 360 orbit, macro reflections, anamorphic lens flare, camera pushes through the zero, "
            "premium sneaker commercial energy, black studio void. Keep text stable and readable."
        ),
    },
    {
        "id": "04_quadratic",
        "title": "Quadratic Deconstruction",
        "style_mode": "monochrome macro with silver highlights",
        "duration": 8,
        "formula": r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}",
        "subtitle": "Parts explode, then lock in.",
        "material": "matte black magnesium, polished silver edges, floating shards",
        "camera": "exploded-view parts assembly, orbiting macro, hard rack focus",
        "prompt": (
            "A glossy technical sneaker launch film: the exact quadratic formula x = (-b plus or minus sqrt(b^2 - 4ac)) / 2a appears as an "
            "exploded-view 3D product assembly. Matte black magnesium symbols with polished silver bevels float in separated layers, then snap "
            "together with magnetic precision. Harsh studio strips, rack focus, fast orbiting macro camera, no museum, no flat poster."
        ),
    },
    {
        "id": "05_fourier",
        "title": "Fourier Wave Tunnel",
        "style_mode": "cool color tunnel",
        "duration": 8,
        "formula": r"\hat f(\xi)=\int_{-\infty}^{\infty}f(x)e^{-2\pi i x\xi}\,dx",
        "subtitle": "Sound becomes a luxury object.",
        "material": "transparent smoked acrylic, blue laser caustics, moving waveform rails",
        "camera": "camera races through wave rails, then snaps to the formula",
        "prompt": (
            "A futuristic sneaker-ad CGI sequence. The Fourier transform is a physical transparent smoked-acrylic 3D object suspended inside a "
            "tunnel of blue laser waveform rails. The camera races through the waves, then snap-focuses on the formula, caustic reflections, "
            "speed ramp, hard rim lights, glossy black stage. Use the reference for layout; prioritize dimensional 3D form."
        ),
    },
    {
        "id": "06_gaussian",
        "title": "Gaussian Glow",
        "style_mode": "black-and-white glow",
        "duration": 7,
        "formula": r"\int_{-\infty}^{\infty} e^{-x^2}\,dx=\sqrt{\pi}",
        "subtitle": "The luminous sole shot.",
        "material": "frosted translucent gel, internal white glow, black glass floor",
        "camera": "top-down spin into low macro with bloom and reflection",
        "prompt": (
            "A luminous product-commercial shot: the Gaussian integral as thick frosted translucent gel letters glowing from within, like a premium "
            "sneaker sole material. Black glass floor, white bloom, violet edge light, top-down spin into low macro angle, reflections, vapor, "
            "shocking polished CGI lighting. Keep the equation readable."
        ),
    },
    {
        "id": "07_maxwell",
        "title": "Maxwell Electric Cut",
        "style_mode": "realistic color electric macro",
        "duration": 9,
        "formula": r"\nabla\cdot E=\frac{\rho}{\epsilon_0}\quad \nabla\times B=\mu_0J+\mu_0\epsilon_0\frac{\partial E}{\partial t}",
        "subtitle": "Electricity sells the shot.",
        "material": "black anodized aluminum, blue plasma, magnetic dust, chrome bevels",
        "camera": "violent macro montage, electrical glints, 12mm lens distortion",
        "prompt": (
            "Aggressive premium sneaker-ad CGI macro montage. Maxwell equation fragments are extruded black anodized aluminum 3D symbols with chrome "
            "bevels, blue plasma arcs crawling across them, magnetic dust lifting from a reflective floor, 12mm lens distortion, fast cuts, hard flashes, "
            "shallow focus. No museum artifact feeling; this is a launch commercial."
        ),
    },
    {
        "id": "08_newton",
        "title": "Newton Force Drop",
        "style_mode": "black-and-white impact",
        "duration": 6,
        "formula": r"F=ma",
        "subtitle": "One brutal impact.",
        "material": "oversized rubber-coated black letters, white edge trim",
        "camera": "falling object impact, handheld shake, low angle recoil",
        "prompt": (
            "A brutal product-launch impact shot: the exact formula F = ma as oversized rubber-coated 3D black letters with white edge trim, dropping "
            "onto a glossy studio floor. Impact shockwave, dust, handheld camera shake, low angle recoil, strobe flash, fast dramatic lighting, "
            "premium athletic advertising style."
        ),
    },
    {
        "id": "09_taylor",
        "title": "Taylor Mechanism",
        "style_mode": "realistic color mechanism",
        "duration": 8,
        "formula": r"f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^n",
        "subtitle": "A kinetic formula machine.",
        "material": "carbon fiber rings, titanium arms, orange rim light",
        "camera": "kinetic parts rotate around lens then align front-on",
        "prompt": (
            "High-end CGI sneaker mechanism shot. The Taylor series formula is built from carbon-fiber rings and titanium arms rotating around the camera, "
            "then snapping into a readable front-facing equation. Orange rim light, black reflective stage, shallow depth of field, fast premium product "
            "advertising motion, clean 3D physical symbols."
        ),
    },
    {
        "id": "10_formula_campaign",
        "title": "Formula Campaign Finale",
        "style_mode": "mixed color and monochrome campaign finale",
        "duration": 12,
        "formula": r"e^{i\pi}+1=0\quad a^2+b^2=c^2\quad F=ma",
        "subtitle": "All formulas as one impossible product line.",
        "material": "floating chrome, ceramic, rubber, translucent gel, carbon fiber",
        "camera": "hero pullback, formulas orbit like product lineup, final light blast",
        "prompt": (
            "Finale of a premium sneaker campaign, but the product line is famous formulas as floating 3D objects. Chrome Euler identity, white ceramic "
            "Pythagorean theorem, rubber F=ma, translucent glowing Gaussian material, carbon fiber accents, all orbiting over a black reflective stage. "
            "Hero pullback, final blast of white light, lens flare, smoke jets, dramatic ad-film lighting, no museum, no classroom."
        ),
    },
]


def ensure_dirs() -> None:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    STORYBOARD_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def texture_background(scene: dict) -> Image.Image:
    base_colors = {
        "ceramic": (205, 205, 198),
        "chrome": (28, 32, 38),
        "carbon": (5, 7, 9),
        "rubber": (8, 8, 9),
        "acrylic": (8, 14, 22),
        "magnesium": (12, 14, 16),
        "gel": (16, 20, 30),
        "aluminum": (9, 11, 13),
        "titanium": (12, 11, 10),
    }
    material = scene["material"].lower()
    color = (7, 8, 10)
    for key, value in base_colors.items():
        if key in material:
            color = value
            break

    img = Image.new("RGB", (WIDTH, HEIGHT), color)
    px = img.load()
    for y in range(0, HEIGHT, 2):
        for x in range(0, WIDTH, 2):
            grain = int(10 * math.sin(x * 0.031 + y * 0.009) + 8 * math.sin((x - y) * 0.019))
            r = max(0, min(255, color[0] + grain))
            g = max(0, min(255, color[1] + grain))
            b = max(0, min(255, color[2] + grain))
            px[x, y] = (r, g, b)
            if x + 1 < WIDTH:
                px[x + 1, y] = (r, g, b)
            if y + 1 < HEIGHT:
                px[x, y + 1] = (r, g, b)
            if x + 1 < WIDTH and y + 1 < HEIGHT:
                px[x + 1, y + 1] = (r, g, b)

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    accents = [(255, 54, 81, 95), (0, 208, 255, 90), (255, 132, 31, 70)]
    for i in range(-HEIGHT, WIDTH, 170):
        draw.line((i, HEIGHT, i + 860, 0), fill=(255, 255, 255, 18), width=8)
    draw.line((-80, 170, WIDTH + 120, 40), fill=accents[0], width=12)
    draw.line((420, HEIGHT + 80, WIDTH + 80, 420), fill=accents[1], width=10)
    draw.line((-140, 820, 680, HEIGHT + 40), fill=accents[2], width=14)

    for radius, alpha in ((330, 42), (520, 26), (710, 16)):
        draw.ellipse(
            (
                WIDTH // 2 - radius,
                HEIGHT // 2 - radius // 3,
                WIDTH // 2 + radius,
                HEIGHT // 2 + radius // 3,
            ),
            outline=(255, 255, 255, alpha),
            width=4,
        )

    floor = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    fd = ImageDraw.Draw(floor)
    fd.polygon(((0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, 620), (0, 760)), fill=(0, 0, 0, 118))
    for y in range(720, HEIGHT, 44):
        fd.line((0, y, WIDTH, y - 130), fill=(255, 255, 255, 18), width=2)
    overlay = Image.alpha_composite(overlay, floor)

    vignette = Image.new("L", (WIDTH, HEIGHT), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse((-360, -240, WIDTH + 360, HEIGHT + 300), fill=215)
    vignette = vignette.filter(ImageFilter.GaussianBlur(110))
    dark = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 200))
    img = Image.composite(img, Image.alpha_composite(img.convert("RGBA"), dark).convert("RGB"), vignette)
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((260, 120, WIDTH - 260, HEIGHT - 40), fill=(255, 255, 255, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    img = Image.alpha_composite(img, overlay).convert("RGB")
    return img


def formula_png(scene: dict) -> Image.Image:
    fig = plt.figure(figsize=(12, 3.8), dpi=200)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    txt = ax.text(
        0.5,
        0.5,
        f"${scene['formula']}$",
        color="#f8fbff",
        fontsize=42 if len(scene["formula"]) < 55 else 30,
        ha="center",
        va="center",
        path_effects=[
            patheffects.withStroke(linewidth=8, foreground="#020204", alpha=0.92),
            patheffects.withStroke(linewidth=3, foreground="#00d0ff", alpha=0.55),
            patheffects.withStroke(linewidth=1, foreground="#ff385c", alpha=0.45),
        ],
    )
    fig.canvas.draw()
    out = REF_DIR / f"{scene['id']}_formula_raw.png"
    fig.savefig(out, transparent=True, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    raw = Image.open(out).convert("RGBA")
    alpha_bbox = raw.getchannel("A").getbbox()
    if not alpha_bbox:
        return raw
    left, top, right, bottom = alpha_bbox
    pad = 48
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(raw.width, right + pad)
    bottom = min(raw.height, bottom + pad)
    cropped = raw.crop((left, top, right, bottom))
    cropped.save(out)
    return cropped


def make_reference(scene: dict) -> Path:
    bg = texture_background(scene).convert("RGBA")
    formula = formula_png(scene)
    max_w = int(WIDTH * 0.74)
    max_h = int(HEIGHT * 0.34)
    scale = min(max_w / formula.width, max_h / formula.height, 1.0)
    formula = formula.resize((int(formula.width * scale), int(formula.height * scale)), Image.Resampling.LANCZOS)
    idx = SCENES.index(scene)
    angle = [-7, 4, -3, 5, -5, 3, -6, 4, -4, 2][idx]
    formula = formula.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    shadow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    offset_x = [-120, 110, -40, 70, -100, 95, -55, 85, -75, 20][idx]
    offset_y = [-35, -10, 10, 40, -20, 5, 35, -5, 20, 10][idx]
    sx = (WIDTH - formula.width) // 2 + offset_x + 42
    sy = (HEIGHT - formula.height) // 2 + offset_y + 44
    shadow.alpha_composite(formula, (sx, sy))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    shadow = Image.eval(shadow, lambda p: int(p * 0.52))
    bg = Image.alpha_composite(bg, shadow)

    reflection = formula.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    reflection = reflection.resize((formula.width, max(1, int(formula.height * 0.48))), Image.Resampling.BICUBIC)
    reflection = Image.eval(reflection, lambda p: int(p * 0.24))
    reflection = reflection.filter(ImageFilter.GaussianBlur(5))
    rx = (WIDTH - formula.width) // 2 + offset_x
    ry = (HEIGHT - formula.height) // 2 + offset_y + formula.height + 34
    if ry < HEIGHT:
        bg.alpha_composite(reflection, (rx, ry))

    x = (WIDTH - formula.width) // 2 + offset_x
    y = (HEIGHT - formula.height) // 2 + offset_y
    bg.alpha_composite(formula, (x, y))

    draw = ImageDraw.Draw(bg)
    draw.line((88, 104, 450, 70), fill=(255, 255, 255, 140), width=3)
    draw.line((WIDTH - 520, HEIGHT - 126, WIDTH - 92, HEIGHT - 178), fill=(0, 208, 255, 130), width=4)
    draw.text((64, 46), scene["title"].upper(), fill=(255, 255, 255, 205))
    draw.text((64, HEIGHT - 92), scene["subtitle"], fill=(255, 255, 255, 175))
    draw.text((WIDTH - 360, 58), "FORMULA LAUNCH FILM", fill=(255, 56, 92, 160))

    out = REF_DIR / f"{scene['id']}.png"
    bg.convert("RGB").save(out, quality=95)
    return out


def make_storyboard(paths: list[Path]) -> Path:
    thumb_w, thumb_h = 480, 270
    margin, gap = 34, 24
    cols = 2
    rows = math.ceil(len(paths) / cols)
    board = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * (thumb_h + 72) + gap), (18, 18, 19))
    draw = ImageDraw.Draw(board)
    for idx, path in enumerate(paths):
        scene = SCENES[idx]
        img = Image.open(path).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        col = idx % cols
        row = idx // cols
        x = gap + col * (thumb_w + gap)
        y = gap + row * (thumb_h + 72)
        board.paste(img, (x, y))
        draw.text((x, y + thumb_h + 10), f"{idx + 1:02d}. {scene['title']} ({scene['duration']}s)", fill=(235, 220, 180))
        draw.text((x, y + thumb_h + 34), scene["camera"], fill=(170, 170, 170))
    out = STORYBOARD_DIR / "mythic_formula_storyboard.png"
    board.save(out, quality=95)
    return out


def write_docs(paths: list[Path], storyboard: Path) -> None:
    shot_rows = []
    for idx, scene in enumerate(SCENES, start=1):
        shot_rows.append(
            {
                "number": idx,
                "id": scene["id"],
                "title": scene["title"],
                "duration_seconds": scene["duration"],
                "reference_frame": f"assets/reference_frames/{scene['id']}.png",
                "formula": scene["formula"],
                "style_mode": scene["style_mode"],
                "material": scene["material"],
                "camera": scene["camera"],
                "prompt": f"{scene['prompt']} {MASTER_STYLE} Shot mode: {scene['style_mode']}.",
                "clip_filename": f"{scene['id']}.mp4",
            }
        )

    (DOCS_DIR / "shot_list.json").write_text(json.dumps(shot_rows, indent=2), encoding="utf-8")
    with (DOCS_DIR / "shot_list.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=shot_rows[0].keys())
        writer.writeheader()
        writer.writerows(shot_rows)

    prompt_md = ["# AI Video Prompts\n"]
    prompt_md.append(
        "Use each reference frame as the image-to-video input. Generate 2-4 variants per shot. "
        "This is a high-end 3D launch commercial, closer to a sneaker/ad film than a museum or explainer. "
        "Push hard lighting, wide lenses, reflections, smoke, fast camera moves, speed ramps, product-style hero framing, "
        "and physical 3D formula objects. Reject outputs where formulas become flat posters or museum plaques.\n"
    )
    for idx, row in enumerate(shot_rows, start=1):
        prompt_md.append(f"## {idx:02d}. {row['title']}\n")
        prompt_md.append(f"- Reference: `{row['reference_frame']}`")
        prompt_md.append(f"- Target clip name: `{row['clip_filename']}`")
        prompt_md.append(f"- Duration: `{row['duration_seconds']}s`")
        prompt_md.append(f"- Style mode: {row['style_mode']}")
        prompt_md.append(f"- Camera: {row['camera']}")
        prompt_md.append(f"- Prompt:\n\n> {row['prompt']}\n")
        prompt_md.append(
            "- Negative prompt: museum, stone tablet, classroom, chalkboard, flat poster, 2D typography, infographic, "
            "soft educational animation, people, cartoon style, warped text, unreadable equation, extra random letters, low resolution\n"
        )
    (DOCS_DIR / "ai_video_prompts.md").write_text("\n".join(prompt_md), encoding="utf-8")

    expected_names = "\n".join(f"- `{row['clip_filename']}`" for row in shot_rows)
    readme = f"""# AI-Generated Formula Launch Film

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

`{storyboard.relative_to(ROOT)}`

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

{expected_names}
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    ensure_dirs()
    paths = [make_reference(scene) for scene in SCENES]
    storyboard = make_storyboard(paths)
    write_docs(paths, storyboard)
    print(f"Generated {len(paths)} reference frames")
    print(storyboard)


if __name__ == "__main__":
    main()
