#!/usr/bin/env python3
"""Apply the round glass mask to 720x720 device screenshots (in place)."""
import sys
from PIL import Image, ImageDraw

for name in sys.argv[1:]:
    img = Image.open(name).convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.size[0] - 1, img.size[1] - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 255))
    out.paste(img, (0, 0), mask)
    out.convert("RGB").save(name)
