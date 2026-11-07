"""Build a multi-resolution ICO from the original vector mark, without dependencies."""
import struct
import zlib
from pathlib import Path


def icon_png(size):
    rows = []
    # Original stylized T / downward lightning mark.
    polygon = [(0.25, .25), (.77, .25), (.68, .43), (.56, .43), (.47, .76), (.30, .76), (.39, .43), (.20, .43)]
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = (x + .5) / size, (y + .5) / size
            inside = False
            j = len(polygon) - 1
            for i, (px, py) in enumerate(polygon):
                qx, qy = polygon[j]
                if (py > v) != (qy > v) and u < (qx-px)*(v-py)/(qy-py)+px:
                    inside = not inside
                j = i
            rounded = (max(.16-u, 0, u-.84)**2 + max(.16-v, 0, v-.84)**2) <= .16**2
            row.extend((255,255,255,255) if inside else (int(90+35*v),int(64+12*v),235,255 if rounded else 0))
        rows.append(bytes(row))
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', size,size,8,6,0,0,0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


sizes = [16, 32, 48, 64, 128, 256]
images = [icon_png(s) for s in sizes]
offset = 6 + 16 * len(sizes)
header = struct.pack('<3H', 0, 1, len(sizes))
for size, image in zip(sizes, images):
    header += struct.pack('<4B2H2I', size % 256, size % 256, 0, 0, 1, 32, len(image), offset)
    offset += len(image)
Path('turboweb/static/app.ico').write_bytes(header + b''.join(images))
Path('turboweb/static/logo.png').write_bytes(images[-1])
