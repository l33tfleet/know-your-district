"""District-bound fact access for agent calls; all results are detached from SQLite."""

from collections.abc import Sequence

from app.brief_facts import BriefFacts
from app.models import Fact
from etl.boundaries import DistrictId


class DistrictFacts:
    """Bind once to the brief's validated district, never to model-supplied scope."""

    def __init__(self, district: DistrictId) -> None:
        self._brief = BriefFacts(district)

    def get_facts(self, geography: str, indicators: Sequence[str]) -> dict[str, Fact | None]:
        """Return displayed indicators by name; None means no published row was found.

        Each Fact carries the original citation, uncertainty and vintage. Reject the
        entire call if any requested geography or indicator is outside this brief.
        """
        brief = self._brief
        if geography not in brief.geographies:
            raise ValueError(f"geography must be one of: {', '.join(brief.geographies)}")
        if any(indicator not in brief.variables for indicator in indicators):
            raise ValueError(f"indicators must be among: {', '.join(brief.variables)}")
        return {
            indicator: brief.facts.get((brief.variables[indicator], geography))
            for indicator in indicators
        }
