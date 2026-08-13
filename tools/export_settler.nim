## Export the settler sprite atlas the broadcast viewer draws instead of a dot.
##
## The viewer is a single self-contained document, so it cannot fetch a PNG. What
## it consumes is a palette-indexed atlas as JSON: one index map per wealth rung
## plus a small palette whose *hat* and *tunic* slots the viewer repaints per
## tribe. Recolouring by palette substitution, not by canvas tint, is what lets a
## tribe hue land on the art instead of fighting it, and it keeps the whole atlas
## under 2 KB and synchronously decodable with no new browser global.
##
## Run by hand, never in CI, exactly like tools/vendor_fonts.mjs. CI provisions
## Python and Node for the viewer job and no Nim at all; the committed
## src/sugarscape/sprites/settler.json is the build input.
##
##     nim c -r -d:release tools/export_settler.nim
##     nim c -r -d:release tools/export_settler.nim --character:0 --contact:/tmp/all.png
##
## Options:
##   --character:N   0..15, row-major over the gnome sheet, two characters a row
##   --pose:P        0..3, 0 = front/south (the only pose the viewer draws)
##   --hatbot:Y      override the detected brim bottom row, in source pixels
##   --out:DIR       output directory, default src/sugarscape/sprites
##   --contact:PATH  also render all sixteen characters side by side for review

import std/[algorithm, base64, json, math, os, parseopt, strformat, strutils, tables]

import pixie
import bitworld/aseprite

const
  ArtPath = "src/sugarscape/art/gnomes.aseprite"
  OverridePath = "src/sugarscape/sprites/settler_override.png"

  Src = 16               ## authoring grid, one side
  Rungs = 3              ## wealth rungs the hat width encodes

  ## Row 0 and row 15 and column 0 and column 15 are reserved for the outline
  ## that the dilation in `addOutline` grows outward, so the art itself is
  ## composed inside a 14x14 core. Growing the outline outward rather than
  ## eroding it inward is the only way a 10px-wide body keeps any interior at
  ## all: a 1px inward outline would consume the legs entirely.
  CrownTop = 1
  CrownRows = 2
  BrimTop = 3
  BrimRows = 3           ## 3 source px = 0.16 cell, the floor for the width read
  BodyTop = 6
  BodyRows = 9
  BodyCore = 12

  ## The nine body rows are budgeted by feature, not shared out by area. A flat
  ## 1.9:1 area downsample of a 21-row gnome averages the face into the beard
  ## into the tunic and returns a smudge; giving the head three rows of its own
  ## is what keeps a settler reading as a creature with a face under a hat.
  HeadRows = 4
  TorsoRows = 3
  LegRows = 2

  ## Colours kept after quantisation. Area-downsampling a 1.9:1 reduction over
  ## hand-dithered art invents dozens of near-identical greys, and at nine rows
  ## tall that reads as noise rather than as a face. Collapsing the body to five
  ## flat masses is what makes it legible.
  HatColors = 3
  BodyColors = 5

  ## Outer, outline-included brim widths per rung. These land on 0.43 / 0.645 /
  ## 0.86 cell at SETTLER_BOX = 0.86, i.e. almost exactly the 0.42 / 0.64 / 0.90
  ## ladder measured through the 4.5:1 embed downsample, and they step by a flat
  ## 4 source px so no two rungs collapse into each other at the floor.
  RungOuter = [8, 12, 16]

  InkHex = "#2a1f12"     ## C.ink in viewer/broadcast.js; the outline colour
  PlateHex = "#1d1811"   ## the field the settlers stand on
  SugarHex = "#f4ecdb"
  SpiceHex = "#f0a63c"

  ## viewer/broadcast.js:3230, with entry 0 changed from #f0a63c. As shipped,
  ## TRIBE_INK[0] is byte-identical to SPICE_HEX - a literal 1.00:1 collision
  ## between a tribe and a resource. The replacement clears 7:1 against the
  ## plate and 2.07:1 against sugar, the best of any tribe.
  TribeInk = ["#f08a7a", "#7fb3d5", "#c9d17a", "#d98cae", "#8fd1c0", "#e8c07d"]

  ## The stops the viewer substitutes onto the hat and tunic slots.
  HatStops = [1.00, 0.80, 0.60]
  TunicStops = [0.80, 0.58]

  ## Measured, not assumed: these are the exact fully-transparent gutters in
  ## src/sugarscape/art/gnomes.aseprite. The characters are hand-placed and do
  ## NOT sit on a 32px grid, so slicing at n*32 shears every one of them.
  RowBands = [(2, 30), (34, 62), (66, 94), (98, 126),
              (130, 158), (162, 189), (193, 221), (226, 253)]
  ColBands = [(6, 31), (36, 58), (69, 93), (97, 122),
              (134, 158), (166, 190), (198, 222), (225, 249)]

type
  Role = enum
    ## What the viewer is allowed to do with a pixel. `roleHat` and `roleTunic`
    ## are repainted per tribe; everything else is the same for every settler.
    roleNone, roleOutline, roleHatLit, roleHatMid, roleHatDim,
    roleTunicLit, roleTunicDim, roleSkin, roleOther

  Pixel = object
    color: ColorRGBA
    role: Role

  Grid = array[Src * Src, Pixel]

proc parseHex(hex: string): ColorRGBA =
  ## Parses "#rrggbb" into an opaque colour.
  let body = hex.strip(chars = {'#'})
  rgba(
    uint8 parseHexInt(body[0 .. 1]),
    uint8 parseHexInt(body[2 .. 3]),
    uint8 parseHexInt(body[4 .. 5]),
    255,
  )

proc toHex(color: ColorRGBA): string =
  ## Formats a colour as "#rrggbbaa", the form the viewer's palette expects.
  &"#{color.r:02x}{color.g:02x}{color.b:02x}{color.a:02x}"

proc scale(color: ColorRGBA, factor: float): ColorRGBA =
  ## Multiplies a colour toward black, for the lit / mid / shadow hat stops.
  proc clampByte(value: float): uint8 =
    uint8 clamp(value, 0.0, 255.0)
  rgba(
    clampByte(color.r.float * factor),
    clampByte(color.g.float * factor),
    clampByte(color.b.float * factor),
    color.a,
  )

proc relativeLuminance(color: ColorRGBA): float =
  ## WCAG relative luminance, used for the plate-contrast report.
  proc channel(value: uint8): float =
    let v = value.float / 255.0
    if v <= 0.04045: v / 12.92 else: pow((v + 0.055) / 1.055, 2.4)
  0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b)

proc contrast(a, b: ColorRGBA): float =
  ## WCAG contrast ratio between two opaque colours.
  let
    x = relativeLuminance(a)
    y = relativeLuminance(b)
  (max(x, y) + 0.05) / (min(x, y) + 0.05)

proc isSkin(color: ColorRGBA): bool =
  ## Recognises the gnome flesh ramp: warm, light, and red through green blue.
  color.r > 150 and color.r > color.g and color.g > color.b and
    color.g.int - color.b.int > 12 and color.r.int - color.b.int > 40

proc at(image: Image, x, y: int): ColorRGBA =
  ## Reads one straight-alpha pixel, or transparent when out of bounds.
  if x < 0 or y < 0 or x >= image.width or y >= image.height:
    rgba(0, 0, 0, 0)
  else:
    image[x, y].rgba()

proc opaque(image: Image, x, y: int): bool =
  ## True when a pixel is solid enough to belong to the silhouette.
  image.at(x, y).a > 128

proc crop(image: Image, x0, y0, x1, y1: int): Image =
  ## Copies an inclusive rectangle out of an image.
  result = newImage(x1 - x0 + 1, y1 - y0 + 1)
  for y in 0 ..< result.height:
    for x in 0 ..< result.width:
      result[x, y] = image.at(x0 + x, y0 + y)

proc largestBlob(image: Image): Image =
  ## Keeps only the biggest connected run of opaque pixels.
  ##
  ## Several gnomes hold a prop clear of the body - a scroll, a pie, a bird on
  ## the hat brim - and at 16px a detached blob two pixels off the silhouette
  ## reads as a rendering fault, not as a prop. It also inflates the bounding
  ## box the whole downsample is fitted to, which shrinks the gnome for nothing.
  var
    label = newSeq[int](image.width * image.height)
    sizes: seq[int]
  for start in 0 ..< label.len:
    if label[start] != 0 or not image.opaque(start mod image.width, start div image.width):
      continue
    sizes.add(0)
    let id = sizes.len
    var queue = @[start]
    label[start] = id
    while queue.len > 0:
      let
        index = queue.pop()
        x = index mod image.width
        y = index div image.width
      sizes[id - 1].inc
      for (dx, dy) in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        let
          nx = x + dx
          ny = y + dy
        if nx < 0 or ny < 0 or nx >= image.width or ny >= image.height:
          continue
        let neighbour = ny * image.width + nx
        if label[neighbour] == 0 and image.opaque(nx, ny):
          label[neighbour] = id
          queue.add(neighbour)
  if sizes.len == 0:
    return image
  var best = 0
  for i, size in sizes:
    if size > sizes[best]:
      best = i
  result = newImage(image.width, image.height)
  for index in 0 ..< label.len:
    if label[index] == best + 1:
      result[index mod image.width, index div image.width] =
        image.at(index mod image.width, index div image.width)

proc tightBounds(image: Image): (int, int, int, int) =
  ## Returns the inclusive bounding box of the opaque pixels.
  var (x0, y0, x1, y1) = (image.width, image.height, -1, -1)
  for y in 0 ..< image.height:
    for x in 0 ..< image.width:
      if image.opaque(x, y):
        x0 = min(x0, x); y0 = min(y0, y); x1 = max(x1, x); y1 = max(y1, y)
  (x0, y0, x1, y1)

proc rowWidths(image: Image): seq[int] =
  ## Width of the opaque span on every row, zero on empty rows.
  for y in 0 ..< image.height:
    var (lo, hi) = (image.width, -1)
    for x in 0 ..< image.width:
      if image.opaque(x, y):
        lo = min(lo, x); hi = max(hi, x)
    result.add(if hi < 0: 0 else: hi - lo + 1)

proc firstSkinRow(image: Image): int =
  ## The topmost row carrying at least three flesh pixels, or -1 for none.
  for y in 3 ..< image.height:
    var count = 0
    for x in 0 ..< image.width:
      if image.opaque(x, y) and image.at(x, y).isSkin():
        count.inc
    if count >= 3:
      return y
  -1

proc detectBrim(image: Image): (int, int) =
  ## Finds the first and last row of the hat brim.
  ##
  ## Keyed on the face, not on the silhouette width. Width looks like the
  ## obvious signal and is not one: half these characters are widest at the
  ## beard or the shoulders, and several wear a plume, a leaf or a bird that
  ## makes the very top row as wide as the brim. Where the flesh starts is
  ## unambiguous - a hat ends where a face begins - and it puts the cut in the
  ## right place on every character in the sheet that has a visible face.
  ##
  ## The brim is then the three rows above that, which is what these hats are
  ## drawn as. Characters with no face at all (the closed helm, the chef under
  ## his toque) fall back to the sheet's own proportion, hats being about the
  ## top two fifths of a gnome.
  let skin = image.firstSkinRow()
  let bottom =
    if skin > 3: skin - 1
    else: max(3, image.height * 2 div 5)
  (max(0, bottom - 2), bottom)

proc weightedPalette(image: Image): seq[(ColorRGBA, int)] =
  ## Every distinct opaque colour with its pixel count, most used first.
  var counts: Table[string, (ColorRGBA, int)]
  for y in 0 ..< image.height:
    for x in 0 ..< image.width:
      if image.opaque(x, y):
        let color = image.at(x, y)
        let key = color.toHex()
        counts[key] = (color, counts.getOrDefault(key, (color, 0))[1] + 1)
  for value in counts.values:
    result.add(value)
  result.sort(proc(a, b: (ColorRGBA, int)): int = cmp(b[1], a[1]))

proc distance(a, b: ColorRGBA): float =
  ## Perceptually weighted squared RGB distance.
  let
    dr = a.r.float - b.r.float
    dg = a.g.float - b.g.float
    db = a.b.float - b.b.float
  0.30 * dr * dr + 0.59 * dg * dg + 0.11 * db * db

proc reduce(image: Image, keep: int, protect: seq[string] = @[]): seq[ColorRGBA] =
  ## Collapses an image's colours down to `keep` by repeatedly folding the
  ## least-used colour into its nearest survivor. Usage order is preserved, so
  ## the first result is always the dominant mass - which is what the lit stop
  ## of the hat and the tunic are keyed on.
  ##
  ## `protect` survives regardless of how few pixels carry it. A gnome's face is
  ## a dozen pixels against a hundred of robe, so plain least-used-first merging
  ## folds the flesh tone into the beard and the settler loses its face - the one
  ## feature that has to survive, because it is also the brightest thing on a
  ## sprite standing on a near-black plate.
  var weighted = image.weightedPalette()
  while weighted.len > keep:
    var victim = -1
    for i in countdown(weighted.high, 0):
      if weighted[i][0].toHex() notin protect:
        victim = i
        break
    if victim < 0:
      break
    let (color, count) = weighted[victim]
    weighted.delete(victim)
    var (best, bestDistance) = (0, float.high)
    for i, (candidate, _) in weighted:
      let d = color.distance(candidate)
      if d < bestDistance:
        bestDistance = d
        best = i
    weighted[best] = (weighted[best][0], weighted[best][1] + count)
    weighted.sort(proc(a, b: (ColorRGBA, int)): int = cmp(b[1], a[1]))
  for (color, _) in weighted:
    result.add(color)

proc nearest(color: ColorRGBA, palette: seq[ColorRGBA]): ColorRGBA =
  ## Snaps an averaged colour back onto the character's own palette.
  ##
  ## Area-averaging a 1.7:1 downsample invents in-between colours, which is what
  ## makes a shrunken sprite look like a smudge rather than like pixel art.
  ## Snapping keeps the source's own flat colour steps.
  result = palette[0]
  var best = float.high
  for candidate in palette:
    let
      dr = color.r.float - candidate.r.float
      dg = color.g.float - candidate.g.float
      db = color.b.float - candidate.b.float
      distance = 0.30 * dr * dr + 0.59 * dg * dg + 0.11 * db * db
    if distance < best:
      best = distance
      result = candidate

proc resample(image: Image, width, height: int, palette: seq[ColorRGBA]): Image =
  ## Area-downsamples an image and snaps every result onto the palette.
  result = newImage(width, height)
  for ty in 0 ..< height:
    for tx in 0 ..< width:
      let
        sx0 = tx * image.width div width
        sx1 = max(sx0 + 1, (tx + 1) * image.width div width)
        sy0 = ty * image.height div height
        sy1 = max(sy0 + 1, (ty + 1) * image.height div height)
      var
        sum = [0.0, 0.0, 0.0]
        covered = 0
        total = 0
      for sy in sy0 ..< sy1:
        for sx in sx0 ..< sx1:
          total.inc
          if image.opaque(sx, sy):
            let color = image.at(sx, sy)
            sum[0] += color.r.float
            sum[1] += color.g.float
            sum[2] += color.b.float
            covered.inc
      if covered * 2 < total:
        continue
      let averaged = rgba(
        uint8(sum[0] / covered.float),
        uint8(sum[1] / covered.float),
        uint8(sum[2] / covered.float),
        255,
      )
      result[tx, ty] = averaged.nearest(palette)

proc runCount(image: Image, y: int): int =
  ## Number of separate opaque runs on one row; two means legs, or two arms.
  var inside = false
  for x in 0 ..< image.width:
    let solid = image.opaque(x, y)
    if solid and not inside:
      result.inc
    inside = solid

proc splitBody(body: Image, skinRows: seq[int]): (int, int) =
  ## Splits a body into head / torso / legs at two source rows.
  ##
  ## The head ends at the last row still carrying flesh; the legs begin at the
  ## lowest run of rows that either split in two or fall under two thirds of the
  ## body's width. Both are properties of how these gnomes are drawn, not of any
  ## grid, so they are measured per character rather than assumed.
  let widths = body.rowWidths()
  var widest = 0
  for width in widths:
    widest = max(widest, width)
  var headBottom = min(body.height - 1, max(1, body.height div 4))
  if skinRows.len > 0:
    headBottom = clamp(skinRows[^1], 1, body.height - 3)
  var legTop = body.height
  while legTop > headBottom + 2:
    let y = legTop - 1
    if body.runCount(y) >= 2 or widths[y].float < widest.float * 0.66:
      legTop.dec
    else:
      break
  if legTop >= body.height:
    legTop = body.height - max(1, body.height div 6)
  (headBottom, legTop)

proc bodyRoles(body: Image): Table[string, Role] =
  ## Assigns every reduced body colour a role.
  ##
  ## `roleTunicLit` and `roleTunicDim` are the only body slots the viewer
  ## repaints, so this decides how much of a settler carries its tribe. The
  ## tunic is the biggest mass that is neither flesh nor near-black - a gnome's
  ## boots and its shadowed underside are not clothing, and painting them tribe
  ## colour turns the silhouette into a solid slab.
  for (color, _) in body.weightedPalette():
    result[color.toHex()] = if color.isSkin(): roleSkin else: roleOther
  # Counted over the torso rows only. Counting the whole body picks the beard,
  # which on most of these characters is the single largest mass and is exactly
  # the feature that must NOT move with the tribe: it is the light against the
  # plate that the ink outline cannot supply.
  var counts: Table[string, (ColorRGBA, int)]
  for y in HeadRows - 1 ..< BodyRows - 1:
    for x in 0 ..< body.width:
      if not body.opaque(x, y):
        continue
      let color = body.at(x, y)
      if color.isSkin():
        continue
      let key = color.toHex()
      counts[key] = (color, counts.getOrDefault(key, (color, 0))[1] + 1)
  var candidates: seq[(ColorRGBA, int)]
  for value in counts.values:
    candidates.add(value)
  candidates.sort(proc(a, b: (ColorRGBA, int)): int = cmp(b[1], a[1]))
  for i in 0 ..< min(2, candidates.len):
    result[candidates[i][0].toHex()] =
      if i == 0: roleTunicLit else: roleTunicDim

proc hatRoles(hat: Image, palette: seq[ColorRGBA]): Table[string, Role] =
  ## Maps the reduced hat colours onto the lit / mid / shadow stops by usage.
  ##
  ## Usage order rather than luminance order, and enough of the top colours are
  ## promoted to the lit stop to carry 60% of the hat. Only the lit stop clears
  ## 7:1 against the plate once it is repainted with a tribe hue - the 0.80 stop
  ## measures 4.6 to 6.9:1 and the 0.60 stop 2.6 to 3.6:1 - so a hat whose mass
  ## sits on the shaded stops is a hat that disappears on stripped ground.
  var
    weights = newSeq[int](palette.len)
    total = 0
  for y in 0 ..< hat.height:
    for x in 0 ..< hat.width:
      if not hat.opaque(x, y):
        continue
      var (best, bestDistance) = (0, float.high)
      for i, candidate in palette:
        let d = hat.at(x, y).distance(candidate)
        if d < bestDistance:
          bestDistance = d
          best = i
      weights[best].inc
      total.inc
  var running = 0
  for i, color in palette:
    let promoted = running * 5 < total * 3      # under 60% covered so far
    running += weights[i]
    result[color.toHex()] =
      if i == 0 or promoted: roleHatLit
      elif i == 1: roleHatMid
      else: roleHatDim

proc addOutline(grid: var Grid, ink: ColorRGBA) =
  ## Grows a one pixel ink outline outward around the silhouette.
  var added: seq[int]
  for y in 0 ..< Src:
    for x in 0 ..< Src:
      if grid[y * Src + x].role != roleNone:
        continue
      var touching = false
      for dy in -1 .. 1:
        for dx in -1 .. 1:
          let (nx, ny) = (x + dx, y + dy)
          if nx < 0 or ny < 0 or nx >= Src or ny >= Src:
            continue
          if grid[ny * Src + nx].role notin {roleNone, roleOutline}:
            touching = true
      if touching:
        added.add(y * Src + x)
  for index in added:
    grid[index] = Pixel(color: ink, role: roleOutline)

proc stamp(
  grid: var Grid, image: Image, top: int, roles: Table[string, Role]
) =
  ## Draws one resampled part, horizontally centred, into the composed grid.
  let x0 = (Src - image.width) div 2
  for y in 0 ..< image.height:
    for x in 0 ..< image.width:
      if not image.opaque(x, y):
        continue
      let color = image.at(x, y)
      grid[(top + y) * Src + x0 + x] =
        Pixel(color: color, role: roles.getOrDefault(color.toHex(), roleOther))

proc buildRung(
  crownSrc, brimSrc, body: Image,
  hatRoleTable, bodyRoleTable: Table[string, Role],
  hatPalette: seq[ColorRGBA],
  outer: int,
  ink: ColorRGBA,
): Grid =
  ## Composes one wealth rung: the real crown and brim art squeezed to this
  ## rung's width, over the shared body, then the outline.
  ##
  ## The crown and brim are resampled separately with fixed row budgets rather
  ## than resampling the hat as one block. A hat is roughly two thirds crown by
  ## height, so a single resample into five rows leaves the brim about one row
  ## thick - and the brim's *width* is the entire wealth signal, so a one-row
  ## brim throws the reading away.
  let
    core = outer - 2                             # the outline eats one px a side
    crownCore = clamp(
      crownSrc.width * core div max(1, brimSrc.width), 3, core - 2)
  result.stamp(crownSrc.resample(crownCore, CrownRows, hatPalette),
    CrownTop, hatRoleTable)
  result.stamp(brimSrc.resample(core, BrimRows - 1, hatPalette),
    BrimTop, hatRoleTable)
  # The brim's underside is ink, not a dark tribe stop. Hat and tunic are both
  # repainted the same hue, and at twelve rendered pixels a 1.00 stop against a
  # 0.80 stop is not a boundary - without a hard dark line under the brim the
  # settler reads as one coloured blob and the wealth rung stops being a hat.
  let brimX0 = (Src - core) div 2
  for x in brimX0 ..< brimX0 + core:
    result[(BrimTop + BrimRows - 1) * Src + x] =
      Pixel(color: ink, role: roleOutline)
  result.stamp(body, BodyTop, bodyRoleTable)
  result.addOutline(ink)

proc substitute(pixel: Pixel, tribe: ColorRGBA, starving: bool): ColorRGBA =
  ## Repaints one pixel the way the viewer will at draw time.
  ##
  ## Tribe identity is a palette swap on the hat and tunic slots, never a canvas
  ## tint over finished art: a tint multiplies the source hue in and the result
  ## is six muddy variants of one gnome instead of six tribes.
  if starving:
    return
      if pixel.role == roleOutline: tribe
      else: parseHex(PlateHex)
  case pixel.role
  of roleHatLit: tribe.scale(HatStops[0])
  of roleHatMid: tribe.scale(HatStops[1])
  of roleHatDim: tribe.scale(HatStops[2])
  of roleTunicLit: tribe.scale(TunicStops[0])
  of roleTunicDim: tribe.scale(TunicStops[1])
  else: pixel.color

proc renderGrid(
  grid: Grid, scale: int, tribe = rgba(0, 0, 0, 0), starving = false
): Image =
  ## Nearest-neighbour render of one rung, for human review. With `tribe` set,
  ## the hat and tunic slots are repainted exactly as the viewer will.
  result = newImage(Src * scale, Src * scale)
  for y in 0 ..< Src * scale:
    for x in 0 ..< Src * scale:
      let pixel = grid[(y div scale) * Src + (x div scale)]
      if pixel.role != roleNone:
        result[x, y] =
          if tribe.a == 0: pixel.color
          else: pixel.substitute(tribe, starving)

proc buildCharacter(
  sheet: Image, character, pose: int, hatBottomOverride: int
): (array[Rungs, Grid], string) =
  ## Cuts one character out of the sheet and composes all three rungs.
  let
    (rowLo, rowHi) = RowBands[character div 2]
    (colLo, colHi) = ColBands[(character mod 2) * 4 + pose]
  var cell = sheet.crop(colLo, rowLo, colHi, rowHi).largestBlob()
  let (bx0, by0, bx1, by1) = cell.tightBounds()
  cell = cell.crop(bx0, by0, bx1, by1)

  let detected = cell.detectBrim()
  let
    brimTop = detected[0]
    brimBottom = if hatBottomOverride >= 0: hatBottomOverride else: detected[1]
    ink = parseHex(InkHex)

  proc tight(image: Image): Image =
    let (x0, y0, x1, y1) = image.tightBounds()
    if x1 < x0: image else: image.crop(x0, y0, x1, y1)

  let
    crownSrc = tight(cell.crop(0, 0, cell.width - 1, max(0, brimTop - 1)))
    brimSrc = tight(cell.crop(0, brimTop, cell.width - 1, brimBottom))
    bodySrc = tight(
      cell.crop(0, brimBottom + 1, cell.width - 1, cell.height - 1))
    hatPalette = tight(cell.crop(0, 0, cell.width - 1, brimBottom)).reduce(HatColors)

  var skinKeys: seq[string]
  for (color, _) in bodySrc.weightedPalette():
    if color.isSkin() and skinKeys.len == 0:
      skinKeys.add(color.toHex())
  let bodyPalette = bodySrc.reduce(BodyColors, skinKeys)

  var skinRows: seq[int]
  for y in 0 ..< bodySrc.height:
    var count = 0
    for x in 0 ..< bodySrc.width:
      if bodySrc.opaque(x, y) and bodySrc.at(x, y).isSkin():
        count.inc
    if count >= 2:
      skinRows.add(y)
  let (headBottom, legTop) = bodySrc.splitBody(skinRows)

  # One horizontal factor for every band, so the head stays smaller than the
  # shoulders exactly as it is drawn. Only the vertical budget is redistributed.
  var body = newImage(BodyCore, BodyRows)
  for (srcTop, srcBottom, dstTop, dstRows) in [
    (0, headBottom, 0, HeadRows),
    (headBottom + 1, legTop - 1, HeadRows, TorsoRows),
    (legTop, bodySrc.height - 1, HeadRows + TorsoRows, LegRows),
  ]:
    if srcBottom < srcTop:
      continue
    let band = tight(bodySrc.crop(0, srcTop, bodySrc.width - 1, srcBottom))
    let width = clamp(
      band.width * BodyCore div max(1, bodySrc.width), 2, BodyCore)
    # No forced gap between the boots. Splitting the two leg rows down the
    # middle was tried and rejected: at twelve rendered pixels a wide brim over
    # two thin legs stops reading as a gnome and starts reading as a table.
    let scaled = band.resample(width, dstRows, bodyPalette)
    let x0 = (BodyCore - width) div 2
    for y in 0 ..< scaled.height:
      for x in 0 ..< scaled.width:
        if scaled.opaque(x, y):
          body[x0 + x, dstTop + y] = scaled.at(x, y)

  let
    hatRoleTable = tight(
      cell.crop(0, 0, cell.width - 1, brimBottom)).hatRoles(hatPalette)
    bodyRoleTable = body.bodyRoles()

  for rung in 0 ..< Rungs:
    result[0][rung] = buildRung(
      crownSrc, brimSrc, body, hatRoleTable, bodyRoleTable, hatPalette,
      RungOuter[rung], ink)
  result[1] = &"cell {cell.width}x{cell.height} brim rows {brimTop}..{brimBottom} " &
    &"crown {crownSrc.width}x{crownSrc.height} brim {brimSrc.width}x{brimSrc.height} " &
    &"body {bodySrc.width}x{bodySrc.height} -> {BodyCore}x{BodyRows} " &
    &"hat {hatPalette[0].toHex()}"

proc emit(grids: array[Rungs, Grid], outDir: string): (JsonNode, seq[ColorRGBA]) =
  ## Builds the palette-indexed atlas the viewer consumes.
  var
    palette = @[rgba(0, 0, 0, 0), parseHex(InkHex)]
    slots: Table[string, int]
    indices = newSeq[uint8](Rungs * Src * Src)
    # Indexed by stop, not by first appearance. The viewer multiplies the
    # tribe hue by HatStops[i] for hat[i], so a list in encounter order would
    # silently paint the shadow stop onto the lit slot.
    hatSlots = [-1, -1, -1]
    tunicSlots = [-1, -1]
  proc slot(color: ColorRGBA, role: Role): int =
    ## One palette slot per repaintable stop, keyed on the role alone.
    ##
    ## The 60% lit promotion means two source colours can share a stop, and the
    ## viewer's substitution is `palette[hat[i]] = tribe * HatStops[i]` - one
    ## index per stop, no more. Keying these on the colour as well would emit
    ## two lit slots, only one of which the viewer would ever repaint, and the
    ## other would keep the source gnome's own hat colour on every tribe.
    let key =
      if role in {roleHatLit, roleHatMid, roleHatDim,
                  roleTunicLit, roleTunicDim}: $role
      else: $role & color.toHex()
    if key in slots:
      return slots[key]
    palette.add(color)
    slots[key] = palette.high
    case role
    of roleHatLit: hatSlots[0] = palette.high
    of roleHatMid: hatSlots[1] = palette.high
    of roleHatDim: hatSlots[2] = palette.high
    of roleTunicLit: tunicSlots[0] = palette.high
    of roleTunicDim: tunicSlots[1] = palette.high
    else: discard
    palette.high
  for rung in 0 ..< Rungs:
    for index in 0 ..< Src * Src:
      let pixel = grids[rung][index]
      indices[rung * Src * Src + index] =
        case pixel.role
        of roleNone: 0'u8
        of roleOutline: 1'u8
        else: uint8 slot(pixel.color, pixel.role)
  var hexes = newJArray()
  for color in palette:
    hexes.add(%color.toHex())
  var hatJson = newJArray()
  for index in hatSlots:
    if index >= 0: hatJson.add(%index)
  var tunicJson = newJArray()
  for index in tunicSlots:
    if index >= 0: tunicJson.add(%index)
  var packed = newString(indices.len)
  for i, value in indices:
    packed[i] = char(value)
  result[0] = %*{
    "v": 1, "w": Src, "h": Src, "rungs": Rungs,
    "palette": hexes, "outline": 1, "hat": hatJson, "tunic": tunicJson,
    "pix": encode(packed),
  }
  result[1] = palette

when isMainModule:
  var
    ## Character 13, the tall-hatted gnome on the right of sheet row 7. Chosen on
    ## the numbers in the acceptance stats below, not on taste: it is the only
    ## one of the sixteen that clears the spec's "25% of opaque pixels at 7:1
    ## against the plate" gate, at 28.6%, and it carries 82% of its hat on the
    ## lit stop against a 60% floor. Re-run with --character:N to compare; the
    ## per-character scan is printed by --contact.
    character = 13
    pose = 0
    hatBottom = -1
    outDir = "src/sugarscape/sprites"
    contact = ""
  for kind, key, value in getopt():
    if kind != cmdLongOption: continue
    case key
    of "character": character = parseInt(value)
    of "pose": pose = parseInt(value)
    of "hatbot": hatBottom = parseInt(value)
    of "out": outDir = value
    of "contact": contact = value
    else: quit(&"unknown option --{key}")
  if character notin 0 .. 15 or pose notin 0 .. 3:
    quit("character must be 0..15 and pose 0..3")

  let sheet = readAseprite(ArtPath).renderFrame(0)
  createDir(outDir)

  if fileExists(OverridePath):
    echo &"NOTE: {OverridePath} exists but hand art is not wired up yet; ignoring"

  let (grids, report) = sheet.buildCharacter(character, pose, hatBottom)
  echo &"character {character} pose {pose}: {report}"

  let (atlas, palette) = grids.emit(outDir)
  let text = $atlas
  writeFile(outDir / "settler.json", text & "\n")
  echo &"settler.json {text.len} bytes, palette {palette.len} slots"

  # Acceptance stats, printed so the character choice is data-driven. The
  # contrast is measured *after* the tribe substitution, because that is the
  # only form any settler is ever drawn in.
  let plate = parseHex(PlateHex)
  var worstBright = 100.0
  for hex in TribeInk:
    let tribe = parseHex(hex)
    var opaqueCount, inkCount, brightCount, hatCount, litCount: int
    for index in 0 ..< Src * Src:
      let pixel = grids[Rungs - 1][index]
      if pixel.role == roleNone: continue
      opaqueCount.inc
      if pixel.role == roleOutline: inkCount.inc
      if pixel.substitute(tribe, false).contrast(plate) >= 7.0: brightCount.inc
      if pixel.role in {roleHatLit, roleHatMid, roleHatDim}:
        hatCount.inc
        if pixel.role == roleHatLit: litCount.inc
    let
      bright = 100.0 * brightCount.float / opaqueCount.float
      inked = 100.0 * brightCount.float / max(1, opaqueCount - inkCount).float
    worstBright = min(worstBright, bright)
    echo &"  tribe {hex}: {opaqueCount} opaque px ({inkCount} ink), " &
      &"{bright:.1f}% of all / {inked:.1f}% of non-outline clear 7:1 vs plate, " &
      &"hat {hatCount} px {100.0 * litCount.float / max(1, hatCount).float:.0f}% lit"
  echo &"  gate: >=25% bright needs {worstBright:.1f}% >= 25 -> " &
    (if worstBright >= 25.0: "PASS" else: "FAIL")
  for rung in 0 ..< Rungs:
    var (lo, hi, hatLo, hatHi) = (Src, -1, Src, -1)
    for y in 0 ..< Src:
      for x in 0 ..< Src:
        let role = grids[rung][y * Src + x].role
        if role == roleNone: continue
        lo = min(lo, x); hi = max(hi, x)
        if y < BrimTop + BrimRows - 1:
          hatLo = min(hatLo, x); hatHi = max(hatHi, x)
    echo &"  rung {rung}: hat rows span {hatHi - hatLo + 1} px, whole sprite {hi - lo + 1} px"

  # 8x review render: three rungs across, then the starving variant, over the
  # plate and repainted for tribe 1. Native colours would flatter the art -
  # nothing on the board is ever drawn in them.
  const Zoom = 8
  var preview = newImage(Src * Zoom * (Rungs + 1), Src * Zoom * TribeInk.len)
  preview.fill(plate)
  for row, hex in TribeInk:
    let tribe = parseHex(hex)
    for rung in 0 ..< Rungs:
      preview.draw(grids[rung].renderGrid(Zoom, tribe), translate(vec2(
        float(rung * Src * Zoom), float(row * Src * Zoom))))
    preview.draw(grids[Rungs - 1].renderGrid(Zoom, tribe, starving = true),
      translate(vec2(float(Rungs * Src * Zoom), float(row * Src * Zoom))))
  preview.writeFile(outDir / "settler_preview.png")

  # 1x atlas, the untinted art at authoring resolution.
  var flat = newImage(Src * Rungs, Src)
  for rung in 0 ..< Rungs:
    flat.draw(grids[rung].renderGrid(1), translate(vec2(float(rung * Src), 0)))
  flat.writeFile(outDir / "settler_atlas.png")

  # Board-scale evidence. The canvas backing store is fixed at 2880x1620, so a
  # settler is ~56 device px at a 1280 stage and ~25 at the 640 embed floor on a
  # 2x display, ~12 on a 1x one. Each size is drawn through a real bilinear
  # downscale and then magnified back with nearest so the question "what
  # survived" can be answered by looking rather than by arguing.
  const Sizes = [56, 25, 12]
  var scaleShot = newImage(5 * 64 * 2, Sizes.len * 64 * 2)
  scaleShot.fill(plate)
  for row, size in Sizes:
    for column in 0 .. 4:
      let tribe = parseHex(TribeInk[1])
      let sprite =
        if column == 3: grids[Rungs - 1].renderGrid(4, tribe, starving = true)
        elif column == 4: newImage(Src * 4, Src * 4)
        else: grids[min(column, Rungs - 1)].renderGrid(4, tribe)
      if column == 4:
        # The incumbent, for scale: today's settler is a tribe-filled disc of
        # radius 0.26 cell with a C.ink ring, wealth-scaled by a log ramp. Any
        # judgement of the sprite that is not made against this is worthless.
        let centre = float(Src * 4) / 2.0
        let outer = 0.26 * 1.18 * float(Src * 4) / 0.86
        for y in 0 ..< Src * 4:
          for x in 0 ..< Src * 4:
            let d = sqrt(pow(float(x) - centre + 0.5, 2) + pow(float(y) - centre + 0.5, 2))
            if d <= outer: sprite[x, y] = tribe
            if d > outer - 3.0 and d <= outer: sprite[x, y] = parseHex(InkHex)
      var tile = newImage(64, 64)
      # A cell of plate with a few grains, so the settler is judged against what
      # it actually stands next to rather than against a flat swatch.
      for y in 0 ..< 64:
        for x in 0 ..< 64:
          tile[x, y] = plate
      for (gx, gy, hex) in [(9, 9, SugarHex), (54, 12, SpiceHex),
                            (12, 52, SugarHex), (52, 54, SugarHex)]:
        for y in max(0, gy - 4) .. min(63, gy + 4):
          for x in max(0, gx - 4) .. min(63, gx + 4):
            if (x - gx) * (x - gx) + (y - gy) * (y - gy) <= 16:
              tile[x, y] = parseHex(hex)
      tile.draw(sprite.resize(55, 55), translate(vec2(4.5, 4.5)))
      let shrunk = tile.resize(size, size)
      scaleShot.draw(shrunk.resize(128, 128),
        translate(vec2(float(column * 128), float(row * 128))))
  scaleShot.writeFile(outDir / "settler_scale.png")
  echo &"wrote {outDir}/settler_preview.png, settler_atlas.png, settler_scale.png"

  if contact.len > 0:
    var sheetOut = newImage(Src * 8 * 8, Src * 8 * 2)
    sheetOut.fill(plate)
    for index in 0 .. 15:
      let (all, _) = sheet.buildCharacter(index, 0, -1)
      sheetOut.draw(all[Rungs - 1].renderGrid(8, parseHex(TribeInk[1])),
        translate(vec2(
          float((index mod 8) * Src * 8), float((index div 8) * Src * 8))))
      var worst = 100.0
      for hex in TribeInk:
        var opaqueCount, brightCount: int
        for cell in 0 ..< Src * Src:
          let pixel = all[Rungs - 1][cell]
          if pixel.role == roleNone: continue
          opaqueCount.inc
          if pixel.substitute(parseHex(hex), false).contrast(plate) >= 7.0:
            brightCount.inc
        worst = min(worst, 100.0 * brightCount.float / opaqueCount.float)
      echo &"  character {index:2d}: worst-tribe bright {worst:5.1f}%"
    sheetOut.writeFile(contact)
    echo &"wrote {contact}"
