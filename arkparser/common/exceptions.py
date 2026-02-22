"""
ARK Parser Exceptions.

Custom exception hierarchy for ARK save file parsing errors.
All exceptions inherit from ArkParseError for easy catching.
"""

from __future__ import annotations


class ArkParseError(Exception):
    """
    Base exception for all ARK parsing errors.

    Catch this to handle any parsing error:
        try:
            data = Obelisk.load("file")
        except ArkParseError as e:
            print(f"Failed to parse: {e}")
    """

    pass


class CorruptDataError(ArkParseError):
    """
    Raised when the file data appears corrupted or invalid.

    This typically occurs when:
    - The file header is malformed
    - String lengths are unreasonable
    - Expected data is missing
    """

    pass


class UnknownPropertyError(ArkParseError):
    """
    Raised when encountering an unknown property type.

    ARK files contain typed properties (IntProperty, FloatProperty, etc.).
    This is raised when we encounter a type we don't recognize.
    """

    def __init__(self, property_type: str, position: int | None = None) -> None:
        self.property_type = property_type
        self.position = position
        msg = f"Unknown property type: {property_type!r}"
        if position is not None:
            msg += f" at position 0x{position:X}"
        super().__init__(msg)


class UnknownStructError(ArkParseError):
    """
    Raised when encountering an unknown struct type.

    Structs are nested data structures within properties.
    This is raised when we encounter a struct type we don't recognize.
    """

    def __init__(self, struct_type: str, position: int | None = None) -> None:
        self.struct_type = struct_type
        self.position = position
        msg = f"Unknown struct type: {struct_type!r}"
        if position is not None:
            msg += f" at position 0x{position:X}"
        super().__init__(msg)


class UnexpectedDataError(ArkParseError):
    """
    Raised when data doesn't match expected values.

    For example, when a field that should always be zero isn't,
    or when we expect a specific marker byte that isn't present.
    """

    def __init__(self, message: str, expected: object = None, actual: object = None) -> None:
        self.expected = expected
        self.actual = actual
        if expected is not None and actual is not None:
            message = f"{message} (expected {expected!r}, got {actual!r})"
        super().__init__(message)


class EndOfDataError(ArkParseError):
    """
    Raised when trying to read past the end of the data.

    This usually indicates a parsing error earlier in the file,
    or that the file is truncated.
    """

    def __init__(self, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__(f"Attempted to read {requested} bytes, but only {available} bytes available")
