"""Context-adaptive student digital twin.

The package is organised along the Gate 1 pipeline:

    raw data -> adapter -> canonical events -> features -> twin state
                                                             |
                                          +------------------+------------------+
                                          |                  |                  |
                                       readout           explanation        simulation

Nothing in `state/`, `models/`, `simulation/` or `evaluation/` may import an
adapter. That direction of dependency is what makes a second dataset an adapter
rather than a rewrite.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
