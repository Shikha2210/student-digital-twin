"""Dataset adapters.

An adapter is the *only* place a dataset's native vocabulary appears. Adding a
dataset means writing one subclass; it must never mean editing `state/`,
`models/` or `simulation/`.

The contract deliberately forces a coverage manifest. Gate 1 §03 requires it and
the reason is methodological, not tidiness: without it, a transfer experiment
cannot tell "the context differs" from "this dataset has no forum channel".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..schema import AdapterOutput, CoverageManifest


class DatasetAdapter(ABC):
    """Base contract for turning a raw dataset into canonical form."""

    #: short identifier used in run manifests and file names
    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """True when the raw data is present and loadable."""

    @abstractmethod
    def coverage(self) -> CoverageManifest:
        """Declare every canonical type as available or unavailable.

        Must be answerable without loading the data, so a caller can plan a
        channel-controlled comparison before paying the load cost.
        """

    @abstractmethod
    def load(self) -> AdapterOutput:
        """Produce canonical events, context metadata, outcomes and coverage."""

    def describe(self) -> dict[str, object]:
        cov = self.coverage()
        return {
            "adapter": self.name,
            "available": self.is_available(),
            "supplies": sorted(cov.available),
            "missing": sorted(cov.unavailable),
            "notes": cov.notes,
        }


class RawDataMissing(FileNotFoundError):
    """Raised when an adapter is asked to load data that is not present.

    Carries the exact placement instructions so the failure is actionable rather
    than merely correct.
    """

    def __init__(self, dataset: str, expected_dir: Path, files: list[str]) -> None:
        listing = "\n  ".join(files)
        super().__init__(
            f"{dataset} raw data not found.\n"
            f"Expected directory: {expected_dir.resolve()}\n"
            f"Expected files:\n  {listing}\n"
            f"See data/README.md for the download link and licence terms.\n"
            f"The prototype runs on the synthetic fixture without this data, but "
            f"any result so produced is NOT an {dataset} result and must never be "
            f"reported as one."
        )


from .oulad import OULADAdapter  # noqa: E402
from .synthetic import SyntheticAdapter  # noqa: E402

REGISTRY: dict[str, type[DatasetAdapter]] = {
    "oulad": OULADAdapter,
    "synthetic": SyntheticAdapter,
}


def get_adapter(name: str, **kwargs) -> DatasetAdapter:
    if name not in REGISTRY:
        raise KeyError(f"unknown adapter {name!r}; available: {sorted(REGISTRY)}")
    return REGISTRY[name](**kwargs)


__all__ = [
    "DatasetAdapter",
    "RawDataMissing",
    "OULADAdapter",
    "SyntheticAdapter",
    "REGISTRY",
    "get_adapter",
]
