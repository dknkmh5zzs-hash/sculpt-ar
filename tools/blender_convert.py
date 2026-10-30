# Запуск:
#   Blender -b -P blender_convert.py -- <вход.stl|obj> <выход.glb> [--faces 100000] [--height 0.5] [--color 0.8,0.78,0.74]
# Импортирует скульпт, упрощает (Decimate), ставит на пол по центру,
# при необходимости масштабирует до реальной высоты в метрах и экспортирует GLB.
import bpy
import sys
import os
import argparse
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
p = argparse.ArgumentParser()
p.add_argument("src")
p.add_argument("dst")
p.add_argument("--faces", type=int, default=100000, help="целевое число треугольников")
p.add_argument("--height", type=float, default=0.0, help="высота модели в метрах (0 = оставить как есть)")
p.add_argument("--color", default="0.80,0.78,0.74", help="базовый цвет R,G,B (0..1)")
p.add_argument("--roughness", type=float, default=0.55)
p.add_argument("--metallic", type=float, default=0.0)
p.add_argument("--draco", action="store_true", help="Draco-сжатие (меньше файл, но хуже совместимость с Android)")
p.add_argument("--keep-material", action="store_true", help="оставить исходные материалы и текстуры (сканы)")
p.add_argument("--max-texture", type=int, default=4096, help="максимальная сторона текстуры: больше телефоны в AR не тянут")
a = p.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)

ext = os.path.splitext(a.src)[1].lower()
print(f"[sculpt-ar] импорт {a.src}")
if ext == ".stl":
    bpy.ops.import_mesh.stl(filepath=a.src)
elif ext == ".obj":
    bpy.ops.import_scene.obj(filepath=a.src)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=a.src)
elif ext == ".ply":
    bpy.ops.import_mesh.ply(filepath=a.src)
elif ext in (".usd", ".usda", ".usdc"):
    bpy.ops.wm.usd_import(filepath=a.src, import_usd_preview=True)
elif ext == ".usdz":
    # USDZ — это zip; распаковываем рядом с результатом и импортируем .usdc
    import tempfile, zipfile
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(a.src) as z:
        z.extractall(tmp)
    inner = next(n for n in z.namelist() if n.lower().endswith((".usdc", ".usda", ".usd")))
    bpy.ops.wm.usd_import(filepath=os.path.join(tmp, inner), import_usd_preview=True)
else:
    sys.exit(f"Неизвестный формат: {ext}")

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("В файле нет мешей")

# Отвязываем меши от родителей (USD/glTF кладут их в группы с поворотом), остальное удаляем
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)

# Объединяем всё в один объект
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# Склеиваем дубли вершин (STL хранит треугольники раздельно)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=1e-6)
bpy.ops.object.mode_set(mode="OBJECT")

tris = sum(len(poly.vertices) - 2 for poly in obj.data.polygons)
print(f"[sculpt-ar] треугольников в исходнике: {tris:,}")
if tris > a.faces:
    mod = obj.modifiers.new("Decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = a.faces / tris
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    tris = sum(len(poly.vertices) - 2 for poly in obj.data.polygons)
    print(f"[sculpt-ar] после Decimate: {tris:,}")

bpy.ops.object.shade_smooth()

# Центр по X/Y, низ на полу (Blender: Z вверх; экспортёр сам переведёт в Y-up)
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
mn = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
mx = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
obj.location -= Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
bpy.ops.object.transform_apply(location=True)

if a.height > 0:
    s = a.height / (mx.z - mn.z)
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(scale=True)
    print(f"[sculpt-ar] масштаб до высоты {a.height} м")

# Материал
if a.keep_material:
    print("[sculpt-ar] материалы оставлены исходные:", [m.name for m in obj.data.materials])
    for img in bpy.data.images:
        w, h = img.size
        if max(w, h) > a.max_texture:
            k = a.max_texture / max(w, h)
            img.scale(int(w * k), int(h * k))
            # сохраняем в файл, иначе экспортёр glTF в Blender 3.0 падает на изменённых картинках
            import tempfile
            img.filepath_raw = os.path.join(tempfile.mkdtemp(), "tex.jpg")
            img.file_format = "JPEG"
            img.save()
            print(f"[sculpt-ar] текстура {img.name}: {w}x{h} -> {img.size[0]}x{img.size[1]}")
else:
    mat = bpy.data.materials.new("Sculpture")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    r, g, b = (float(x) for x in a.color.split(","))
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
    bsdf.inputs["Roughness"].default_value = a.roughness
    bsdf.inputs["Metallic"].default_value = a.metallic
    obj.data.materials.clear()
    obj.data.materials.append(mat)

os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=a.dst,
    export_format="GLB",
    use_selection=False,
    export_normals=True,
    export_texcoords=a.keep_material,
    export_draco_mesh_compression_enable=a.draco,
    export_draco_mesh_compression_level=6,
    export_draco_position_quantization=14,
    export_draco_normal_quantization=10,
)
print(f"[sculpt-ar] готово: {a.dst} ({os.path.getsize(a.dst) / 1e6:.1f} МБ)")
