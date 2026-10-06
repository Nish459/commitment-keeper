class SearchError(Exception):
    """The web search request failed."""


class EmailError(Exception):
    """Sending an email failed."""


class EmailNotConfiguredError(EmailError):
    """Outbound email is not set up."""


class RecipientNotAllowedError(EmailError):
    """The recipient is not on the allowed list."""


class DemoLimitError(Exception):
    """A demo workspace used up its allowance, or the server is busy."""


class NoDueDateError(Exception):
    """The promise has no deadline, so there is nothing to put on a calendar."""
