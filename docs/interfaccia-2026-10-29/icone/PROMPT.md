# Icone CER · 29 ottobre 2026

Strumento integrato `image_gen.imagegen`, `transparent_background: true`.
Riferimento di stile: il foglio di Casa, `docs/interfaccia-2026-10-29/icone/foglio-originale.webp` del progetto Casa (sola lettura).
Una chiamata, otto soggetti nuovi. Il foglio ha restituito alpha: la post-produzione conserva la trasparenza, elimina solo le piccole componenti isolate, ritaglia e riduce. Nessun soggetto disegnato a mano.

```text
Use case: stylized-concept.
Asset type: production sprite sheet for an Italian energy community app, the sister app of Casa / Energia in chiaro.
Input image is a STYLE reference only: match the exact soft clay material, chunky rounded forms, orthographic three-quarter front camera, upper-left lighting and coherent palette of the supplied Casa icon sheet. Create NEW subjects, do not copy the old subjects.
Primary request: ONE sheet with exactly EIGHT separate mini illustrations in FOUR columns and TWO rows, landscape 1536x768 if possible, equal square cells. Each subject centered and fully contained within the central 65% of its cell, large empty gutters. Simple bold silhouettes legible at 24px.
EXACT row-major order:
Row 1: (1) comunita: three friendly lavender and purple human busts grouped in front of a tiny mint house, a community of families; (2) contatore: one rounded lavender electricity meter with purple lightning bolt and an aqua indicator, no numerals; (3) tetto-mappa: a small lavender house with a purple solar panel roof standing on a tiny folded mint map, one amber location pin; (4) condivisa: two small lavender houses linked by two chunky aqua curved arrows around one amber lightning bolt, shared energy.
Row 2: (5) riparto: a round aqua and purple pie disc split into three clearly separated chunky segments, one amber coin; (6) economia-comunita: two small lavender houses beside a rounded lavender wallet with two amber coins; (7) scheda-famiglia: a lavender paper card with folded purple corner, one raised purple family-of-three symbol and one aqua check, no writing; (8) ombre: a tall lavender building beside a small purple-roof house and amber sun, a solid muted blue shadow wedge from the tall building towards the house.
Purple #6d28d9 and lavender unify all subjects; emerald/aqua #0b7a5e, warm amber and ice blue accents. Matte clay with gentle highlights and subtle self-shading. No flat line art.
Background must be GENUINELY transparent RGBA alpha 0, including all gutters and internal empty spaces. No gradient, no halo, no scenery, no floor, no cast shadows outside the icon subjects, no checkerboard painted into image. Exactly eight icons, no text, no letters, no numerals, no watermark, no grid lines or card tiles.
```
