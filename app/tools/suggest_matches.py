"""Missing catalog matches: subtract normalized identities without changing ranked proposals.

The caller supplies saved case/match identities and durable decisions for the folder. Figures,
source dates and program guidance stay on the matching tool's existing typed proposals.
"""

from collections.abc import Sequence

from app.tools.matches import MatchReference
from app.tools.suggestions import Proposal


def suggest_matches(
    proposals: tuple[Proposal, ...], saved: Sequence[MatchReference]
) -> tuple[Proposal, ...]:
    """Keep ranked catalog proposals whose full district/population/program identity is new."""
    return tuple(proposal for proposal in proposals if proposal.match not in saved)
