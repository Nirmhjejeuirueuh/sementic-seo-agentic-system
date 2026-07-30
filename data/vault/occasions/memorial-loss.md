---
type: Occasion
title: Memorial / Loss
collection_url:
status: existing
primary_keyword: pet memorial figurine
# "rainbow bridge" is the only bereavement-vocabulary alias kept here --
# it is pet-specific (see the "Loved Ones" note for the rest, moved
# there because the mentor's own keyword categories treat bare
# sympathy/grief/remembrance language as the human-audience group, not
# this pet-focused one).
aliases: [rainbow bridge]
# "loss" is auto-derived from splitting the title "Memorial / Loss" on
# "/" (see entity_aliases() in link_keywords.py), and it is too generic:
# it whole-word-matches "loss of husband gift", "loss of wife gift" --
# human-bereavement keywords with nothing to do with this pet-centric
# collection. Excluded so those keywords route to the "Loved Ones" split
# instead.
exclude_aliases: [loss]
# These 3 keywords contain the word "memorial" (this entity's own title,
# so it can't be removed as an alias -- 44 of the pet-cluster's 49
# keywords depend on it) but are conceptually human-bereavement, not
# pet. exclude_aliases can't express "except these specific keywords";
# this can. Each already correctly links to "Loved Ones" via its own
# aliases (funeral, loss of) -- this only stops the extra, unwanted
# link to the pet entity.
exclude_keywords:
  - loss of child memorial
  - funeral memorial keepsake
  - memorial gift for loss of loved one
source_section: "1.2, 1.3 -- see loved-ones.md for the human-bereavement split"
---

Covered by multiple existing collections: Memorial & Tribute, Pet
Memorials, Loved Ones, Pet Urns, Garden Markers, Keepsakes. No single
collection URL is given in the source document — treat this as a family
of existing pages rather than one page.
