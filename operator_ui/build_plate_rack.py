"""Build editable STEP and named OBJ parts using FreeCAD's bundled Python."""
import json
import sys
from pathlib import Path
sys.path.append(str(Path(sys.executable).resolve().parent.parent / 'lib'))
import FreeCAD as App
import Part
import MeshPart

assets = Path(__file__).resolve().parent / 'static' / 'models'
p = json.loads((assets / 'plate_rack_config.json').read_text())
w,d,h = p['shelf_width_mm'],p['shelf_depth_mm'],p['height_mm']
t,lip,lt,post = (p[k] for k in ['shelf_thickness_mm','lip_height_mm','lip_thickness_mm','post_width_mm'])
parts=[]
def box(x,y,z,dx,dy,dz):
    return Part.makeBox(dx,dy,dz,App.Vector(x,y,z))
parts.append(('base',box(-w/2-post,-d/2-8,0,w+2*post,d+16,p['base_thickness_mm'])))
for side in [-1,1]:
    x=-w/2-post if side<0 else w/2
    parts.append(('post_left' if side<0 else 'post_right',box(x,d/2-post, p['base_thickness_mm'],post,post,h-p['base_thickness_mm'])))
shelves=[]
for i in range(p['shelf_count']):
    z=p['first_shelf_top_mm']+i*p['shelf_pitch_mm']
    assert z+lip<=h
    shelf=box(-w/2,-d/2,z-t,w,d,t)
    shelf=shelf.cut(box(-p['front_notch_width_mm']/2,-d/2-1,z-t-1,p['front_notch_width_mm'],p['front_notch_depth_mm']+1,t+2))
    shelf=shelf.cut(Part.makeCylinder(p['center_hole_radius_mm'],t+2,App.Vector(0,0,z-t-1)))
    # Side guides sit outside the 90 mm usable shelf width; front stays open.
    guides=[box(-w/2-lt,-d/2,z-t,lt,d,t+lip),box(w/2,-d/2,z-t,lt,d,t+lip),box(-w/2,d/2-lt,z,w,lt,lip)]
    parts.append((f'shelf_{i+1}',Part.makeCompound([shelf,*guides])))
    shelves.append({'id':i+1,'surface_z_mm':z,'seat_center_mm':[0,0,z],'approach_mm':[0,-d/2-50,z+10]})
doc=App.newDocument('PlateRack')
for name,shape in parts:
    assert shape.isValid(),name
    obj=doc.addObject('PartDesign::Feature',name);obj.Label=name;obj.Shape=shape
doc.recompute()
Part.export(doc.Objects,str(assets/'plate_rack.step'))
doc.saveAs(str(assets/'plate_rack.FCStd'))
with (assets/'plate_rack.obj').open('w',encoding='ascii') as out:
    out.write('# Rack reconstruction, millimeters, Z-up. See plate_rack_config.json.\n')
    offset=1
    for name,shape in parts:
        mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=0.3,AngularDeflection=0.3,Relative=False)
        verts,faces=mesh.Topology
        out.write(f'o {name}\n')
        for v in verts:out.write(f'v {v.x:.5f} {v.y:.5f} {v.z:.5f}\n')
        for a,b,c in faces:out.write(f'f {a+offset} {b+offset} {c+offset}\n')
        offset+=len(verts)
compound=Part.makeCompound([s for _,s in parts]);b=compound.BoundBox
assert abs(b.ZLength-h)<1e-6
metadata={'name':'Photo-based plate rack','units':'mm','up_axis':'Z','shelves':shelves,'bounds_mm':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],'assumptions':p['notes']}
(assets/'plate_rack.json').write_text(json.dumps(metadata,indent=2))
print(json.dumps(metadata))
