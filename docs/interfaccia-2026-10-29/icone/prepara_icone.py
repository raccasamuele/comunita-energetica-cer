"""Solo post-produzione del foglio ImageGen. Non disegna i soggetti. Eseguire dalla radice."""
from pathlib import Path
import hashlib
import json
import sys
from PIL import Image

source = Path(sys.argv[1])
raw = source.read_bytes()
image = Image.open(source).convert('RGBA')
names = ['comunita', 'contatore', 'tetto-mappa', 'condivisa', 'riparto', 'economia-comunita', 'scheda-famiglia', 'ombre']
out = Path('web/public/icons')
docs = Path('docs/interfaccia-2026-10-29/icone')
assets = []
preview = Image.new('RGBA', (768, 384), '#f3f2f9')
for index, name in enumerate(names):
    col, row = index % 4, index // 4
    bounds = (round(col*image.width/4), round(row*image.height/2), round((col+1)*image.width/4), round((row+1)*image.height/2))
    cell = image.crop(bounds)
    # Elimina i piccoli puntini trasparenti/colorati isolati prodotti dal generatore.
    # Conserva le componenti grandi (anche sole, frecce o monete staccati dal soggetto).
    alpha = cell.getchannel('A')
    pixels = alpha.load()
    seen = set()
    for y in range(cell.height):
        for x in range(cell.width):
            if (x,y) in seen or pixels[x,y] < 24:
                continue
            stack, component = [(x,y)], []
            seen.add((x,y))
            while stack:
                px, py = stack.pop()
                component.append((px,py))
                for nx, ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                    if 0 <= nx < cell.width and 0 <= ny < cell.height and (nx,ny) not in seen and pixels[nx,ny] >= 24:
                        seen.add((nx,ny)); stack.append((nx,ny))
            if len(component) < 140:
                for px,py in component: pixels[px,py] = 0
    alpha = alpha.point(lambda a: 0 if a < 24 else a)
    cell.putalpha(alpha)
    bbox = cell.getbbox()
    subject = cell.crop(bbox)
    for size, suffix in ((48, ''),(96, '-2x')):
        scaled = subject.copy()
        scaled.thumbnail((round(size*.88), round(size*.88)), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (size,size))
        canvas.alpha_composite(scaled, ((size-scaled.width)//2,(size-scaled.height)//2))
        path = out / f'{name}{suffix}.webp'
        canvas.save(path, 'WEBP', quality=90, method=6)
        assert path.stat().st_size <= 12000
        assets.append({'file':path.name,'size':size,'bytes':path.stat().st_size,'crop':bbox})
        if size == 96: preview.alpha_composite(canvas, (col*192+48,row*192+32))
        else: preview.alpha_composite(canvas, (col*192+72,row*192+136))
reduced = image.copy()
reduced.thumbnail((1152,768),Image.Resampling.LANCZOS)
reduced.save(docs/'foglio-originale.webp','WEBP',quality=82,method=6)
assert (docs/'foglio-originale.webp').stat().st_size <= 200000
preview.convert('RGB').save(docs/'anteprima.webp','WEBP',quality=86,method=6)
(docs/'asset.json').write_text(json.dumps({'source_sha256':hashlib.sha256(raw).hexdigest(),'sheet':image.size,'grid':[4,2],'assets':assets},indent=2),encoding='utf-8')
print(json.dumps({'sheet':image.size,'assets':len(assets),'max_bytes':max(a['bytes'] for a in assets),'total_bytes':sum(a['bytes'] for a in assets),'original_bytes':(docs/'foglio-originale.webp').stat().st_size}))
