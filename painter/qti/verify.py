"""Checks on a written QTI package."""
from __future__ import annotations

from pathlib import Path
import zipfile


def verify_qti_zip(path: Path, expected_items: int) -> None:
    """Reopen the package and check every XML part parses and no item was lost."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad:
            raise IOError(f"{path.name}: corrupt member {bad}")
        names = zf.namelist()
        if "imsmanifest.xml" not in names:
            raise IOError(f"{path.name}: no imsmanifest.xml")
        found = 0
        for name in names:
            root = ET.fromstring(zf.read(name))
            found += sum(1 for el in root.iter() if el.tag.endswith("item")
                         and el.tag.rsplit("}", 1)[-1] == "item")
    if found != expected_items:
        raise IOError(f"{path.name}: {found} item(s) written, expected {expected_items}")
