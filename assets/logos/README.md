# Camera maker logos

Optional. Drop an SVG named after the maker, lowercased with anything
non-alphanumeric removed:

    sony.svg          for  Make = "SONY"
    canon.svg         for  Make = "Canon"
    nikon.svg         for  Make = "NIKON CORPORATION"
    fujifilm.svg      for  Make = "FUJIFILM"
    omdigitalsolutions.svg

If a file is present it is used on the plate under the photograph. If not, that
corner of the plate is simply left empty. No manufacturer artwork ships with
this repo, so by default nothing is shown there.

Nothing needs rebuilding or re-publishing: the site asks for the file once per
maker per visit and uses it if it is there. Drop one in and it appears.

Use a single-colour SVG that inherits `currentColor` where possible, so it
works in both light and dark themes. Rendered at 17px tall.
