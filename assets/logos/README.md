# Camera maker logos

Optional. One SVG per maker, named after the maker lowercased with anything
non-alphanumeric removed:

    sony_logo_black.svg       for  Make = "SONY"
    canon_logo_black.svg      for  Make = "Canon"
    nikon_logo_black.svg      for  Make = "NIKON CORPORATION"
    fujifilm_logo_black.svg   for  Make = "FUJIFILM"

The plate is always white, so the artwork always wants to be the dark one --
which is what the `_black` in the name is there to remind you of.

If a file is missing, that corner of the plate is simply left empty. No
manufacturer artwork ships with this repo, so by default nothing is shown
there.

Nothing needs rebuilding or re-publishing: the site asks for the file once per
maker per visit and uses it if it is there. Drop one in and it appears.

Rendered at 14px tall, so use artwork whose proportions suit a wordmark.
