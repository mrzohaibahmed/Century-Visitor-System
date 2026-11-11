"""Database errors that mean the same thing for every backend (raised by repositories, caught by services)."""


class DuplicateKey(Exception):
    """A write broke a unique constraint (e.g. a name or username that already exists)."""
