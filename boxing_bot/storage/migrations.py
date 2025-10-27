def migrate(data: dict) -> dict:
    v = data.get("version",1)
    if v == 1:
        # example: add fights dict if missing
        data.setdefault("fights", {})
        data["version"] = 2
    return data