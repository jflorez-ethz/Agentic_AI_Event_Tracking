"""Archived experimental reader for reproducing superseded metrics only."""
import re
from pathlib import Path


def ground_truth(xml):
    """XML person tracks {id: {frame: box}} and the bag's first and last frames (if any)."""
    persons, bag = {}, {}
    for frame in re.split(r'<frame number="', Path(xml).read_text())[1:]:
        n = int(frame.split('"')[0])
        for oid, body in re.findall(r'<object id="(\d+)">(.*?)</object>', frame, re.S):
            b = {k: int(v) for k, v in re.findall(r'(h|w|xc|yc)="(\d+)"', body)}
            box = (b["xc"] - b["w"] / 2, b["yc"] - b["h"] / 2, b["xc"] + b["w"] / 2, b["yc"] + b["h"] / 2)
            role = (re.search(r"<role[^>]*>\s*([^<]*?)\s*</role>", body) or [0, ""])[1]
            (bag if "object" in role else persons.setdefault(oid, {}))[n] = box
    return persons, bag
