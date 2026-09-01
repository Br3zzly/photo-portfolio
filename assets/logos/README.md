# Camera maker logos

Optional. Two SVGs per maker, named after the maker lowercased with anything
non-alphanumeric removed, plus the colour of the artwork:

    sony_logo_black.svg     for  Make = "SONY"
    sony_logo_white.svg
    canon_logo_black.svg    for  Make = "Canon"
    canon_logo_white.svg
    nikon_logo_black.svg    for  Make = "NIKON CORPORATION"
    fujifilm_logo_black.svg for  Make = "FUJIFILM"

Both colours are needed because the card inverts against the page: it is a
dark card on the light theme and a white one on the dark theme. The site puts
both in the page and shows whichever reads against the card, so the theme
toggle swaps them instantly with no second request.

If the pair is missing, that corner of the plate is simply left empty. No
manufacturer artwork ships with this repo, so by default nothing is shown
there.

Nothing needs rebuilding or re-publishing: the site asks for the black one
once per maker per visit and uses the pair if it is there. Drop them in and
they appear.

Rendered at 14px tall, so use artwork whose proportions suit a wordmark. The
files are used as-is rather than recoloured, which is why the colour is in the
name.
