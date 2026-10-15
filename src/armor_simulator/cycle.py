"""The day of the simulated installation, shared by every simulated source.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The solar and the electrical readings must agree on when the mains fail, or the server would see an inconsistent state for several cycles: so the day, the phase of a sample and the window of
the outage are defined here, once, and both import them. Nothing is synchronised by timing: everything is a pure function of the sample number.
"""

from __future__ import annotations

DAY_SAMPLES = 240
OUTAGE_FROM, OUTAGE_TO = 0.80, 0.85


def phase(sample: int) -> float:
    """Where in the simulated day a sample falls: 0 (the start of the day) up to, but not including, 1."""
    return (sample % DAY_SAMPLES) / DAY_SAMPLES


def outage(sample: int) -> bool:
    """Whether the mains are out at this sample (for the solar inverter and the electrical node alike)."""
    return OUTAGE_FROM <= phase(sample) < OUTAGE_TO
