"""Dependency extraction from root-level package manifests (public files only)."""

import json
import re
import tomllib
from dataclasses import dataclass

MANIFEST_FILES = ["package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml"]


@dataclass(frozen=True)
class ParsedDependency:
    ecosystem: str
    name: str
    version_spec: str | None
    dep_type: str
    manifest_path: str


_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)\s*(\[[^\]]*\])?\s*([<>=!~].*)?$")


def _split_requirement(line: str) -> tuple[str, str | None] | None:
    line = line.split("#", 1)[0].split(";", 1)[0].strip()
    if not line or line.startswith(("-", "git+", "http:", "https:", ".")):
        return None
    match = _REQ_RE.match(line)
    if not match:
        return None
    return match.group(1).lower().replace("_", "-"), (match.group(3) or "").strip() or None


def parse_package_json(text: str, path: str = "package.json") -> list[ParsedDependency]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    out: list[ParsedDependency] = []
    for key, dep_type in (("dependencies", "runtime"), ("devDependencies", "dev"), ("peerDependencies", "runtime")):
        section = data.get(key) if isinstance(data, dict) else None
        if isinstance(section, dict):
            for name, spec in section.items():
                out.append(ParsedDependency("npm", str(name), str(spec)[:120] if spec else None, dep_type, path))
    return out


def parse_requirements(text: str, path: str = "requirements.txt") -> list[ParsedDependency]:
    out = []
    for line in text.splitlines():
        parsed = _split_requirement(line)
        if parsed:
            out.append(ParsedDependency("pypi", parsed[0], parsed[1], "runtime", path))
    return out


def parse_pyproject(text: str, path: str = "pyproject.toml") -> list[ParsedDependency]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    out: list[ParsedDependency] = []
    project = data.get("project") or {}
    for line in project.get("dependencies") or []:
        parsed = _split_requirement(str(line))
        if parsed:
            out.append(ParsedDependency("pypi", parsed[0], parsed[1], "runtime", path))
    for group in (project.get("optional-dependencies") or {}).values():
        for line in group or []:
            parsed = _split_requirement(str(line))
            if parsed:
                out.append(ParsedDependency("pypi", parsed[0], parsed[1], "dev", path))
    poetry = ((data.get("tool") or {}).get("poetry") or {})
    for name, spec in (poetry.get("dependencies") or {}).items():
        if name.lower() != "python":
            out.append(ParsedDependency("pypi", name.lower().replace("_", "-"), spec if isinstance(spec, str) else None, "runtime", path))
    return out


def parse_go_mod(text: str, path: str = "go.mod") -> list[ParsedDependency]:
    out: list[ParsedDependency] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        indirect = "// indirect" in raw
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require ") and not in_block:
            line = line[len("require "):].strip()
        elif not in_block:
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append(ParsedDependency("go", parts[0], parts[1], "dev" if indirect else "runtime", path))
    return out


def parse_cargo(text: str, path: str = "Cargo.toml") -> list[ParsedDependency]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    out: list[ParsedDependency] = []
    sections = [(data.get("dependencies"), "runtime"), (data.get("dev-dependencies"), "dev"),
                ((data.get("workspace") or {}).get("dependencies"), "runtime")]
    for section, dep_type in sections:
        if isinstance(section, dict):
            for name, spec in section.items():
                version = spec if isinstance(spec, str) else (spec.get("version") if isinstance(spec, dict) else None)
                out.append(ParsedDependency("cargo", name, version, dep_type, path))
    return out


PARSERS = {
    "package.json": parse_package_json,
    "requirements.txt": parse_requirements,
    "pyproject.toml": parse_pyproject,
    "go.mod": parse_go_mod,
    "Cargo.toml": parse_cargo,
}


def parse_manifest(filename: str, text: str) -> list[ParsedDependency]:
    parser = PARSERS.get(filename)
    if not parser:
        return []
    seen: set[tuple[str, str, str]] = set()
    unique: list[ParsedDependency] = []
    for dep in parser(text, filename):
        key = (dep.ecosystem, dep.name, dep.dep_type)
        if key not in seen and len(dep.name) <= 200:
            seen.add(key)
            unique.append(dep)
    return unique[:400]
