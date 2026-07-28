# Remaining products worksheet

Not a vault note itself (the loader skips this — it's not inside
`products/`, `styles/`, etc.). A working checklist for transcribing the
remaining 32 of 37 catalogue products. Tick items off as you go; this
file can be edited or deleted once you're done.

**5 already done:** Custom 3D Figurine from Photo, Custom Wedding Cake
Toppers, Custom Pet Figurine, Cute Chibi Figurine Standing, Custom 3D
Pet Memorial Statue.

---

## The template

Create one file per row below, in `data/vault/products/`, named to match
the URL slug. Copy this, fill in the blanks from the table, write 1–2
honest sentences in the body (what the product is + which source signal
justified each tag), and leave any list empty rather than guessing.

```
---
type: Product
title: <exact product name>
url: <url from table>
status: existing
styles: []
types: []
occasions: []
formats: []
recipients: []
keywords: [<a reasonable seed keyword>]
source_section: "1.1 row <n>"
---

<1-2 sentences>
```

**Tag names must match an existing taxonomy note's title
character-for-character.** The worksheet below already gives you the
exact strings — copy them, don't retype from memory.

---

## Worksheet

| # | Product | URL | Tag with |
|---|---|---|---|
| 1 | Turn Your Photo Into a Lifelike 3D Figurine | `/products/realistic` | `styles: [Realistic]` |
| 3 | Bobblehead Standing Figurine | `/products/bobblehead-standing-figurine` | `styles: [Bobblehead]` |
| 4 | Custom Half-Body 3D Figurine | `/products/custom-upper-body` | `formats: [Bust / Half-Body]` |
| 7 | Personalized Realistic Miniature Statue | `/products/personalized-figurines` | `styles: [Realistic]` |
| 8 | Personalized Custom Bobblehead from Photo | `/products/custom-bobbleheads-from-photo` | `styles: [Bobblehead]` |
| 9 | Custom 3D Portrait Bust | `/products/custom-3d-portrait-bust` | `formats: [Bust / Half-Body]` |
| 10 | 3D Printed Miniature Replica of Yourself | `/products/miniature-replica-from-photo` | *(leave all empty — see note ①)* |
| 12 | Personalized Couple Figurine (Anniversary) | `/products/personalized-anniversary-couple-gift` | `occasions: [Anniversary]` |
| 13 | Custom 3D Proposal & Engagement Statue | `/products/custom-engagement-statue` | `occasions: [Engagement]` |
| 14 | Custom Bridesmaid & Groomsman Mini-Me Gifts | `/products/custom-bridesmaid-groomsman-gift` | `occasions: [Wedding]` *(see note ②)* |
| 15 | Bespoke 3D Event Table Centerpiece Figurines | `/products/custom-event-centerpiece-figurines` | `occasions: [Events (general)]` |
| 17 | Luxury Custom 3D Pet Urn with Lifelike Statue | `/products/custom-pet-urn-with-figurine` | `types: [Pet]`, `occasions: [Memorial / Loss]` |
| 18 | Personalized 3D Tribute Figurine for Memorials | `/products/custom-human-memorial-figurine` | `occasions: [Memorial / Loss]` |
| 19 | Custom 3D Miniature Memorial Keepsake | `/products/miniature-memorial-keepsake` | `occasions: [Memorial / Loss]` |
| 20 | Custom 3D Gifts for Him | `/products/personalized-gifts-for-him` | `recipients: [Him]` |
| 21 | Unique Personalized 3D Gifts for Her | `/products/personalized-gifts-for-her` | `recipients: [Her]` |
| 22 | Personalized 3D Figurine — Gift for Boyfriend | `/products/gifts-for-boyfriend-personalized` | `recipients: [Boyfriend]` |
| 23 | Custom 3D Family Figurine — Gift for Mom & Dad | `/products/custom-family-gift-figurine` | `types: [Family]` |
| 24 | Custom Coach Appreciation Gift | `/products/custom-coach-appreciation-gift` | `recipients: [Coach]` |
| 25 | Family / Group Custom Figurine | `/products/family-group-custom-figurine` | `types: [Family]` |
| 26 | Custom 3D Keychain Figure (Cartoon) | `/products/custom-3d-keychain-figure-from-your-photo` | `formats: [Keychain]` |
| 27 | Magnetic Levitation Figurine Display Stand | `/products/magnetic-levitation-stand` | *(leave all empty — see note ③)* |
| 28 | Dust-Proof Acrylic Display Box | `/products/dust-proof-cover-with-door-for-custom-figure...` | *(leave all empty — see notes ③ and ④)* |
| 29 | Gift Box (packaging) | `/products/gift-box-simple-scarf-shirt-perfume-gift-box...` | *(leave all empty — see notes ③ and ④)* |
| 30 | Custom Magnetic Levitation Floating Figurine | `/products/custom-magnetic-levitation-floating-figurine-desk-decor` | *(leave all empty — see note ③)* |
| 31 | Custom Bronze 3D Portrait Figurine | `/products/custom-bronze-3d-portrait-figurine-personalized-human-statue` | `styles: [Bronze / Sculpture Finish]` |
| 32 | My Embrace — Personalized Jesus Figurine | `/products/my-embrace-personalized-jesus-figurine` | *(leave all empty — see note ⑤)* |
| 33 | Custom Miniature Builder (Eldritch Foundry alt.) | `/products/custom-miniature-builder-eldritch-foundry-alternative` | `types: [Model / Hobbyist]` |
| 34 | Wooden Base with Engraved Text | `/products/wooden-base-engraved` | *(leave all empty — see note ③)* |
| 35 | Premium Gift Box | `/products/premium-gift-box` | *(leave all empty — see note ③)* |
| 36 | Custom Corporate Realistic Standing Figurine | `/products/custom-corporate-realistic-standing-figurine` | `types: [Corporate]`, `styles: [Realistic]` |
| 37 | Personalized Football Figurine | `/products/personalized-football-figurine` | `types: [Sports]` |

---

## Notes on judgment calls

**① Row 10 — "Type: Self/Mini-me".** This signal doesn't appear anywhere
in the source document's own pillar tables (section 4 lists Sports,
Model/Hobbyist, Baby, Celebrity/Fan Art, Anime, Family, Pet, Corporate —
no "Self/Mini-Me"). So this isn't an oversight on our part; the document
itself never elevates it to a taxonomy dimension. Leave untagged. If you
later decide this deserves its own FigurineType, that's a real judgment
call for you to make as the business owner, not something to infer from
the document.

**② Row 14 — "Occasion: Wedding party".** No separate "Wedding party"
occasion note exists; the closest match is the existing `Wedding` note.
Tagging it there is a reasonable simplification, not a guess about an
unstated fact.

**③ Rows 27, 28, 29, 30, 34, 35 — accessory/packaging SKUs.** These
products *are* the accessory being sold (a display stand, a gift box),
rather than a figurine that pairs with one. No taxonomy note exists for
them to link to, and inventing a `PAIRS_WITH` relationship pointing a
product at itself would be circular. Leave every list empty — same
discipline as the flagship product. The `accessories/` folder stays
empty in this pass; we can revisit it once there's an actual figurine
product that's stated to pair with one of these.

**④ Rows 28, 29 — the URLs are truncated in the source document itself**
(they end in `...`). Do not guess the ending — use the truncated form
as-is, or better, verify the real slug against the live site before
filling it in, and update `source_section` to note you corrected it.

**⑤ Row 32 — "Niche: Religious".** Same situation as note ①: not part of
the document's three-pillar structure. Leave untagged.

---

## When you're done (or partway through)

```powershell
python -m src.ingest.vault
python -m scripts.inspect_vault
```

Safe to run after every few notes, not just at the end — everything is
`MERGE`d, so partial progress never breaks anything.
