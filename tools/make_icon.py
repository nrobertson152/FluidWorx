#!/usr/bin/env python3
"""Draw the FluidWorx application icon (development tool, needs Pillow).

Same family as the OpenSchematix mark: a blue rounded square with a faint grid, a white line and gold ports,
here bent into an "F" with a drop of fluid. Placeholder artwork until a Director-supplied logo replaces it.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "fluidworx" / "resources"
S = 1024


def base():
    grad = Image.new("RGBA", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            px[x, y] = (int(28 - 12 * t), int(118 - 52 * t), int(228 - 96 * t), 255)
    d = ImageDraw.Draw(grad)
    for i in range(0, S, 64):
        d.line([(i, 0), (i, S)], fill=(255, 255, 255, 26), width=2)
        d.line([(0, i), (S, i)], fill=(255, 255, 255, 26), width=2)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], 190, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def main():
    im = base()
    d = ImageDraw.Draw(im)
    w = 96
    white = (255, 255, 255, 255)
    # the F: a line from the bottom port up, over to the top port, with a branch to a third port
    d.line([(350, 810), (350, 250), (760, 250)], fill=white, width=w, joint="curve")
    d.line([(350, 515), (660, 515)], fill=white, width=w)
    for x, y in ((350, 250),):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=white)
    gold, navy = (246, 178, 40, 255), (20, 62, 130, 255)
    for x, y in ((350, 810), (760, 250), (660, 515)):
        d.ellipse([x - 86, y - 86, x + 86, y + 86], fill=gold)
        d.ellipse([x - 40, y - 40, x + 40, y + 40], fill=navy)
    im = im.resize((512, 512), Image.LANCZOS)
    OUT.mkdir(exist_ok=True)
    for size in (512, 256, 64):
        im.resize((size, size), Image.LANCZOS).save(OUT / f"fluidworx-{size}.png")
    im.save(OUT / "fluidworx.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
