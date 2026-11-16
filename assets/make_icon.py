"""Pack assets/icon-png/*.png into assets/cx-ops-ai.ico (stdlib only).

The PNGs are exported from cxops/web/static/icon.svg (64 pt artboard) at 16-256 px with VectorCraft.
ICO files can hold PNG-compressed images directly (Windows Vista and later). Run:  python assets/make_icon.py
"""
import struct
from pathlib import Path

HERE = Path(__file__).parent


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


def main() -> None:
    pngs = sorted(((png_size(p.read_bytes())[0], p.read_bytes()) for p in (HERE / "icon-png").glob("*.png")))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, data in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    out = HERE / "cx-ops-ai.ico"
    out.write_bytes(struct.pack("<HHH", 0, 1, len(pngs)) + entries + blobs)
    print(f"Wrote {out} with sizes {[s for s, _ in pngs]}")


if __name__ == "__main__":
    main()
