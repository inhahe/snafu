#!/usr/bin/env python3
"""Snafu package manager.

Manages local packages for the Snafu language.  Packages live under
~/.snafu/packages/<name>/ and are registered in ~/.snafu/registry.json.

When ``us my_package`` cannot find ``my_package.snf`` in the working directory,
the interpreter can also look in ``~/.snafu/packages/my_package/main.snf``
(add ``~/.snafu/packages`` to the module search path, or symlink the entry
point).

Usage:
    snafu_pkg init               Create snafu_pkg.json in the current directory
    snafu_pkg create  <name>     Scaffold a new package directory
    snafu_pkg publish [path]     Register a local package in the registry
    snafu_pkg install <name>     Install a package from the registry
    snafu_pkg remove  <name>     Uninstall a package
    snafu_pkg list               List installed packages
    snafu_pkg info    <name>     Show package metadata
    snafu_pkg search  <query>    Search the registry by name/description
"""

import sys
import os
import json
import shutil

SNAFU_HOME = os.path.expanduser("~/.snafu")
PACKAGES_DIR = os.path.join(SNAFU_HOME, "packages")
REGISTRY_PATH = os.path.join(SNAFU_HOME, "registry.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    """Create ~/.snafu/ and ~/.snafu/packages/ if they don't exist."""
    os.makedirs(PACKAGES_DIR, exist_ok=True)


def load_registry():
    """Load the JSON registry, returning an empty dict if absent."""
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(reg):
    """Persist the registry dict to disk."""
    ensure_dirs()
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def _load_manifest(path):
    """Read and return a snafu_pkg.json manifest, or None."""
    manifest_path = os.path.join(path, "snafu_pkg.json")
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init():
    """Create snafu_pkg.json in the current directory."""
    name = os.path.basename(os.getcwd())
    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": "",
        "author": "",
        "entry": "main.snf",
        "deps": [],
    }
    with open("snafu_pkg.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Created snafu_pkg.json for '{name}'")


def cmd_install(name):
    """Install a package from the registry into ~/.snafu/packages/<name>/."""
    reg = load_registry()
    if name not in reg:
        print(f"Package '{name}' not found in registry")
        return
    src = reg[name].get("path")
    if not src or not os.path.exists(src):
        print(f"Package source not found: {src}")
        return
    dest = os.path.join(PACKAGES_DIR, name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    # Recursively install dependencies
    manifest = _load_manifest(dest)
    if manifest:
        for dep in manifest.get("deps", []):
            dep_dest = os.path.join(PACKAGES_DIR, dep)
            if not os.path.exists(dep_dest):
                print(f"  installing dependency '{dep}'...")
                cmd_install(dep)
    print(f"Installed '{name}' to {dest}")


def cmd_list():
    """List installed packages."""
    if not os.path.exists(PACKAGES_DIR):
        print("No packages installed")
        return
    found = False
    for name in sorted(os.listdir(PACKAGES_DIR)):
        pkg_dir = os.path.join(PACKAGES_DIR, name)
        if not os.path.isdir(pkg_dir):
            continue
        found = True
        manifest = _load_manifest(pkg_dir)
        if manifest:
            print(f"  {name} v{manifest.get('version', '?')} — {manifest.get('description', '')}")
        else:
            print(f"  {name} (no manifest)")
    if not found:
        print("No packages installed")


def cmd_info(name):
    """Show metadata for an installed package."""
    pkg_dir = os.path.join(PACKAGES_DIR, name)
    manifest = _load_manifest(pkg_dir)
    if manifest:
        for k, v in manifest.items():
            print(f"  {k}: {v}")
    else:
        print(f"Package '{name}' not found")


def cmd_create(name):
    """Scaffold a new package directory with a manifest and entry point."""
    os.makedirs(name, exist_ok=True)
    os.makedirs(os.path.join(name, "lib"), exist_ok=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": f"The {name} package",
        "author": "",
        "entry": "main.snf",
        "deps": [],
    }
    with open(os.path.join(name, "snafu_pkg.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(name, "main.snf"), "w", encoding="utf-8") as f:
        f.write(f'# {name} package\nxp [hello]\n\ndf hello() = p("Hello from {name}!")\n')
    print(f"Created package '{name}/'")


def cmd_publish(path="."):
    """Register a local package directory in the global registry."""
    manifest = _load_manifest(path)
    if manifest is None:
        print("No snafu_pkg.json found")
        return
    reg = load_registry()
    reg[manifest["name"]] = {
        "version": manifest.get("version", "0.0.0"),
        "description": manifest.get("description", ""),
        "path": os.path.abspath(path),
    }
    save_registry(reg)
    print(f"Published '{manifest['name']}' v{manifest.get('version')}")


def cmd_search(query):
    """Search the registry by name or description substring."""
    reg = load_registry()
    q = query.lower()
    found = False
    for name, info in reg.items():
        if q in name.lower() or q in info.get("description", "").lower():
            print(f"  {name} v{info.get('version', '?')} — {info.get('description', '')}")
            found = True
    if not found:
        print(f"No packages matching '{query}'")


def cmd_remove(name):
    """Uninstall a package and remove it from the registry."""
    dest = os.path.join(PACKAGES_DIR, name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
        print(f"Removed '{name}'")
    else:
        print(f"Package '{name}' is not installed")
    reg = load_registry()
    if name in reg:
        del reg[name]
        save_registry(reg)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

USAGE = """\
Usage: snafu_pkg <command> [args]

Commands:
  init               Create snafu_pkg.json in the current directory
  create  <name>     Scaffold a new package
  publish [path]     Register a local package in the registry
  install <name>     Install a package from the registry
  remove  <name>     Uninstall a package
  list               List installed packages
  info    <name>     Show package metadata
  search  <query>    Search the registry"""


def main():
    ensure_dirs()
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        return

    cmd = args[0]
    if cmd == "init":
        cmd_init()
    elif cmd == "install" and len(args) > 1:
        cmd_install(args[1])
    elif cmd == "list":
        cmd_list()
    elif cmd == "info" and len(args) > 1:
        cmd_info(args[1])
    elif cmd == "create" and len(args) > 1:
        cmd_create(args[1])
    elif cmd == "publish":
        cmd_publish(args[1] if len(args) > 1 else ".")
    elif cmd == "search" and len(args) > 1:
        cmd_search(args[1])
    elif cmd == "remove" and len(args) > 1:
        cmd_remove(args[1])
    else:
        print(f"Unknown or incomplete command: {' '.join(args)}")
        print(USAGE)


if __name__ == "__main__":
    main()
