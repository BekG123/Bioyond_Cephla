"""Run with FreeCAD's Python interpreter / FreeCADCmd, no robot imports.

Converts the supplied Squid+ C-mount / four-position turret STEP to OBJ.
Keep source, checksum, tessellation tolerance and bounds for provenance.
"""
import hashlib
import json
import sys
from pathlib import Path

# Also support the Python executable bundled alongside FreeCADCmd.
freecad_lib = Path(sys.executable).resolve().parent.parent / "lib"
if (freecad_lib / "Part.pyd").exists():
    sys.path.append(str(freecad_lib))
import FreeCAD
import Part
import MeshPart

assets = Path(__file__).resolve().parent / "static" / "models"
source = Path(r"C:\Users\Cephla\Downloads\Squid+ with C-mount and 4 position turret.STEP")
shape = Part.read(str(source))
mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=1.0,
                              AngularDeflection=0.5, Relative=False)
vertices, facets = mesh.Topology
target = assets / "squid_plus_cmount_4turret.obj"
with target.open("w", encoding="ascii") as out:
    out.write("# Squid+ with C-mount and 4 position turret. Units: mm\n")
    for v in vertices:
        out.write(f"v {v.x:.4f} {v.y:.4f} {v.z:.4f}\n")
    for a, b, c in facets:
        out.write(f"f {a+1} {b+1} {c+1}\n")
box = shape.BoundBox
metadata = {
    "name": "Squid+ with C-mount and 4 position turret",
    "repository": "https://github.com/Cephla-Lab/Squid",
    "source_file": str(source),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "source_units": "mm", "tessellation_deflection_mm": 1.0,
    "angular_deflection_radians": 0.5,
    "authored_up_axis": "Y",
    "vertices": len(vertices), "triangles": len(facets),
    "bounds_mm": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
    "warning": "User-supplied Squid+ assembly. Visual reference only; not collision geometry or robot registration.",
}
(assets / "squid_plus_cmount_4turret.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(json.dumps(metadata), flush=True)
