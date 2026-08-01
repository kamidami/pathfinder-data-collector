class CollectorError(Exception):
    """Base exception for expected collector failures."""


class ContractError(CollectorError):
    """Raised when a local data contract is invalid."""
