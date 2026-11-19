import sys
from PIL import Image

src = sys.argv[1]
tag = sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
zoom = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
im = Image.open(src)
w, h = im.size
for i in range(n):
    y0 = max(0, int(h * i / n) - 25)
    y1 = min(h, int(h * (i + 1) / n) + 25)
    c = im.crop((0, y0, w, y1))
    c = c.resize((int(w * zoom), int((y1 - y0) * zoom)), Image.LANCZOS)
    c.save(f'_crops/{tag}_{i}.png')
print('ok', n)
