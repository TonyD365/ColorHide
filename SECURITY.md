# Security policy

Inkhue reads images, PDFs and scans, and updates itself from GitHub releases. If you find a way to make it run
code, write files where it shouldn't, or install something that isn't an official release, please report it
**privately** through [GitHub security advisories](https://github.com/TonyD365/Inkhue/security/advisories/new)
rather than a public issue. You'll get a reply within a week.

Supported: the latest release.

How updates are protected: the app only installs the archive for its platform from the release marked *Latest*
on `TonyD365/Inkhue`, after checking it against `SHA256SUMS.txt` from the same release. Every release file
also carries a GitHub build-provenance attestation (`gh attestation verify <file> -R TonyD365/Inkhue`).

Note that Inkhue hides color from the eye, not from people: the format is public and nothing is encrypted.
Don't use it to protect secrets.
