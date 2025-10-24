"""Data migration utilities for BoxingBot."""

def migrate(data: dict) -> dict:
    """Upgrade the configuration data to the latest schema version.

    The only supported migration updates version 1 payloads by ensuring
    a ``fights`` dictionary is present and bumping the version to 2.
    If the payload is already at a newer version it is returned
    unchanged.
    """
    version = data.get("version", 1)
    if version == 1:
        # Example migration: ensure fights dictionary exists and bump version.
        data.setdefault("fights", {})
        data["version"] = 2
    return data