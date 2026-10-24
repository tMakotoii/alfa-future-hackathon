from functools import lru_cache

import yaml


@lru_cache
def load_sectors(path: str = "config/sectors.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sensitivity(sectors: dict, okved2: str, factor: str) -> float:
    s = sectors["sectors"].get(okved2)
    if s is None:
        return sectors["default"].get(factor, 0.0)
    return s["sensitivity"].get(factor, 0.0)
