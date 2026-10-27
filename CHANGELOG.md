# Changelog

Every release is on [GitHub Releases](https://github.com/TonyD365/Inkhue/releases) with installers for macOS,
Windows and Linux. Pages printed with any version decode with every later version.

## 1.2.1
- Scans at **400 dpi** decode reliably (was 1200 dpi): the page grid is measured from the timing track's spectrum,
  and the dots are read with cubic interpolation. Poor prints and scans decode about twice as often.
- Recommended scan: 600 dpi, at least 400.

## 1.2.0
- **Documents** (mostly white pages) work: every cell keeps at least one dot so blank paper carries data.
- Neural refiner retrained on photos plus documents: page color error on a real worksheet nearly halved.
- Damaged areas stay gray instead of random color; upside-down and sideways scans decode.
- Clear messages for pages without hidden color and for too-coarse scans; scanner and secure-print hints.

## 1.1.1
- Maintenance: CI and pull-request labelling fixes. No changes to the app.

## 1.1.0
- **ColorHide is now Inkhue.**
- Refiner retrained on 8× more photos; pen strokes across the frame no longer stop decoding.
- *Fill the paper*, a live print preview with all print settings, faster decoding.

## 1.0.0
- First release: hide a photo's color in a black-and-white print and recover it from a scan; printer-style app,
  installers, automatic updates.
