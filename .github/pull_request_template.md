## What & why

<!-- One or two sentences. Link the issue: Fixes #123 -->

## How it was checked

- [ ] `pytest tests` passes
- [ ] Tried it in the app (Hide color → Test cycle, or a real print/scan)
- [ ] Real printer / scanner used: <!-- model + dpi, or "simulated only" -->

## On-paper format

- [ ] This PR does **not** change how pages are laid out on paper
      (`payload.py` constants, `halftone.py` patterns, `layout.py` frame). If it does, it bumps `VERSION`
      and keeps decoding old pages — see *Format stability* in the README.

<!-- CI posts a codec benchmark comparing this branch with main. -->
