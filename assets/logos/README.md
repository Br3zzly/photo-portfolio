# Camera maker logos

Optional. Drop an SVG named after the maker, lowercased with anything
non-alphanumeric removed:

    sony.svg          for  Make = "SONY"
    canon.svg         for  Make = "Canon"
    nikon.svg         for  Make = "NIKON CORPORATION"
    fujifilm.svg      for  Make = "FUJIFILM"
    omdigitalsolutions.svg

If a file is present it is used on the plate under the photograph. If not, the
maker's name is set as a wordmark instead, which is what happens by default --
no manufacturer artwork ships with this repo.

Use a single-colour SVG that inherits `currentColor` where possible, so it
works in both light and dark themes. Rendered at 17px tall.
