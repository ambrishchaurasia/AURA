"""Windows settings operations that call OS APIs directly instead of clicking UI."""


class ActionError(Exception):
    """An operation failed for a reason worth telling the user verbatim."""
