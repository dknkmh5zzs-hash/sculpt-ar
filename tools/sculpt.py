#!/usr/bin/env python3
"""Sculpt Art AR: добавление работ и сборка сайта.

  ./sculpt add <файл.stl|obj> <slug> --title "Лошадь" [--meta "Бронза, 2025"] [--desc "..."]
               [--height 0.4] [--faces 100000] [--color 0.8,0.78,0.74] [--usdz model.usdz]
  ./sculpt build      пересобрать все страницы и QR-коды из works.json
  ./sculpt list       показать работы
  ./sculpt preview    открыть сайт локально в браузере
  ./sculpt remove <slug>
"""
import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
WORKS = ROOT / "works.json"
CONFIG = ROOT / "site.json"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def load(path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def esc(s):
    return html.escape(s or "", quote=True)


def render_work(w, cfg):
    t = (TOOLS / "work_template.html").read_text("utf-8")
    desc = f'<p class="desc">{esc(w["desc"])}</p>' if w.get("desc") else ""
    ios = 'ios-src="model.usdz"' if (ROOT / w["slug"] / "model.usdz").exists() else ""
    rep = {
        "{{TITLE}}": esc(w["title"]),
        "{{META}}": esc(w.get("meta", "")),
        "{{DESC_BLOCK}}": desc,
        "{{IOS_SRC}}": ios,
        "{{AR_SCALE}}": "fixed" if w.get("height") else "auto",
        "{{SITE_URL}}": esc(cfg["site_url"]),
        "{{SITE_LABEL}}": esc(cfg["site_label"]),
    }
    for k, v in rep.items():
        t = t.replace(k, v)
    (ROOT / w["slug"] / "index.html").write_text(t, "utf-8")


def render_home(works, cfg):
    cards = "\n".join(
        f'''    <a class="card" href="{esc(w["slug"])}/">
      <model-viewer src="{esc(w["slug"])}/model.glb" alt="{esc(w["title"])}" environment-image="neutral"
        auto-rotate rotation-per-second="14deg" interaction-prompt="none" shadow-intensity="1" loading="lazy"></model-viewer>
      <div class="cap"><b>{esc(w["title"])}</b><span>{esc(w.get("meta", ""))}</span></div>
    </a>'''
        for w in works
    )
    page = f'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#14120f">
  <title>Sculpt Art — AR</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=Inter:wght@400;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="assets/style.css">
  <script type="module" src="https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js"></script>
</head>
<body>
  <header class="top">
    <a class="brand" href="./">Sculpt<span>·</span>Art</a>
    <nav><a href="{esc(cfg["site_url"])}">{esc(cfg["site_label"])}</a></nav>
  </header>
  <main class="home">
    <h1>Скульптуры в&nbsp;AR</h1>
    <p class="lead">Выберите работу и поставьте её у себя в комнате с помощью телефона.</p>
    <div class="grid">
{cards}
    </div>
  </main>
</body>
</html>
'''
    (ROOT / "index.html").write_text(page, "utf-8")


def render_qr(works, cfg):
    base = cfg.get("base_url", "").rstrip("/")
    if not base:
        print("! QR-коды пропущены: укажите base_url в site.json (например https://ваш-ник.github.io/sculpt-ar)")
        return
    import segno
    out = ROOT / "qr"
    out.mkdir(exist_ok=True)
    for w in works:
        url = f"{base}/{w['slug']}/"
        q = segno.make(url, error="h")
        q.save(out / f"{w['slug']}.svg", scale=10, border=2, dark="#14120f")
        q.save(out / f"{w['slug']}.png", scale=20, border=2, dark="#14120f")
        print(f"  QR {w['slug']}: {url}")


def build():
    cfg = load(CONFIG, {})
    works = load(WORKS, [])
    for w in works:
        render_work(w, cfg)
    render_home(works, cfg)
    render_qr(works, cfg)
    (ROOT / ".nojekyll").touch()
    print(f"Собрано работ: {len(works)}")


def add(a):
    src = Path(a.src).expanduser().resolve()
    if not src.exists():
        sys.exit(f"Нет файла: {src}")
    d = ROOT / a.slug
    d.mkdir(exist_ok=True)
    if src.suffix.lower() == ".glb" and a.no_convert:
        shutil.copy(src, d / "model.glb")
    else:
        cmd = [BLENDER, "-b", "-P", str(TOOLS / "blender_convert.py"), "--",
               str(src), str(d / "model.glb"), "--faces", str(a.faces),
               "--height", str(a.height or 0), "--color", a.color]
        if a.keep_material or src.suffix.lower() in (".usdz", ".usd", ".usdc", ".glb", ".gltf"):
            cmd.append("--keep-material")
        print("Blender обрабатывает модель, это может занять несколько минут…")
        r = subprocess.run(cmd, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if "[sculpt-ar]" in line:
                print(line)
        if r.returncode or not (d / "model.glb").exists():
            sys.exit("Ошибка Blender:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    if a.usdz:
        shutil.copy(Path(a.usdz).expanduser(), d / "model.usdz")

    works = [w for w in load(WORKS, []) if w["slug"] != a.slug]
    works.append({"slug": a.slug, "title": a.title, "meta": a.meta, "desc": a.desc, "height": a.height})
    save(WORKS, works)
    build()


def main():
    p = argparse.ArgumentParser(description="Sculpt Art AR")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add", help="добавить или обновить работу")
    pa.add_argument("src")
    pa.add_argument("slug", help="латиница для адреса, например horse")
    pa.add_argument("--title", required=True)
    pa.add_argument("--meta", default="")
    pa.add_argument("--desc", default="")
    pa.add_argument("--height", type=float, default=None, help="реальная высота в метрах (включает AR в натуральную величину)")
    pa.add_argument("--faces", type=int, default=100000)
    pa.add_argument("--color", default="0.80,0.78,0.74", help="цвет материала R,G,B; бронза: 0.55,0.38,0.22")
    pa.add_argument("--usdz", help="готовый USDZ для iPhone (необязательно)")
    pa.add_argument("--keep-material", action="store_true", help="оставить текстуры исходника (для USDZ/GLB включено само)")
    pa.add_argument("--no-convert", action="store_true", help="GLB уже готов, просто скопировать")
    sub.add_parser("build")
    sub.add_parser("list")
    sub.add_parser("preview")
    pr = sub.add_parser("remove")
    pr.add_argument("slug")
    a = p.parse_args()

    if a.cmd == "add":
        add(a)
    elif a.cmd == "build":
        build()
    elif a.cmd == "preview":
        import webbrowser
        webbrowser.open("http://localhost:8765/")
        subprocess.run([sys.executable, "-m", "http.server", "8765", "-d", str(ROOT)])
    elif a.cmd == "list":
        for w in load(WORKS, []):
            print(f"{w['slug']:<16} {w['title']}")
    elif a.cmd == "remove":
        save(WORKS, [w for w in load(WORKS, []) if w["slug"] != a.slug])
        shutil.rmtree(ROOT / a.slug, ignore_errors=True)
        (ROOT / "qr" / f"{a.slug}.svg").unlink(missing_ok=True)
        (ROOT / "qr" / f"{a.slug}.png").unlink(missing_ok=True)
        build()


if __name__ == "__main__":
    main()
