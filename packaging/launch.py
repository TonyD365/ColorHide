import sys


def self_test():
    """Run the whole codec inside the packaged app; exit code 0 = OK. Used by CI on the built bundle."""
    import numpy as np

    from inkhue import api, channel
    y, x = np.mgrid[0:200, 0:300] / np.array([200, 300])[:, None, None]
    rgb = (np.stack([x, y, 1 - x * y], -1) * 255).astype(np.uint8)
    page, _ = api.encode(rgb, width_in=2.5, dpi=600)
    refiner = api.load_refiner()
    _, info = api.decode(channel.print_scan(page, seed=1), refiner)
    return 0 if info["rs_ok"] and refiner is not None else 1


if "--self-test" in sys.argv:
    sys.exit(self_test())

from inkhue.gui.main import main  # noqa: E402

sys.exit(main())
