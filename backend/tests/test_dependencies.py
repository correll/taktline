"""Everything `app/` imports has to be declared in requirements.txt.

A production 500 traced back to `import httpx` inside the floor-plan URL
fetcher. httpx is not a dependency of this app — it arrives in development
transitively, because Starlette's TestClient needs it — so every test passed,
locally and in CI, while the deployed image had no httpx at all and raised
ImportError on the first request that reached that line.

No test of behaviour can catch that: the thing missing in production is
present wherever tests run. It has to be checked structurally, against the
manifest, which is what this does.
"""

import ast
import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
REQS = pathlib.Path(__file__).resolve().parents[1] / "requirements.txt"

# Distribution name → the module it installs, where they differ.
INSTALLS = {
    "sqlalchemy": {"sqlalchemy"}, "asyncpg": {"asyncpg"}, "alembic": {"alembic"},
    "pydantic": {"pydantic"}, "pydantic-settings": {"pydantic_settings"},
    "python-multipart": {"multipart", "python_multipart"},
    "argon2-cffi": {"argon2"}, "email-validator": {"email_validator"},
    "aiosmtplib": {"aiosmtplib"}, "openpyxl": {"openpyxl"}, "slowapi": {"slowapi"},
    "fastapi": {"fastapi"}, "uvicorn": {"uvicorn"}, "websockets": {"websockets"},
    "httpx": {"httpx"}, "pillow": {"PIL"},
}


# Modules a DECLARED package is guaranteed to install, so they cannot go
# missing the way httpx did. FastAPI is built on Starlette and cannot be
# installed without it; pydantic v2 is a thin shell over pydantic-core. Listing
# them is a claim with a reason, not a way of quieting the check — anything
# that is merely "probably there" belongs in requirements.txt instead.
GUARANTEED_BY = {
    "starlette": "fastapi",
    "pydantic_core": "pydantic",
}


def _declared() -> set:
    mods = set()
    for line in REQS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower()
        mods |= INSTALLS.get(name, {name.replace("-", "_")})
    return mods


def _imported() -> dict:
    """Top-level module → the file that imports it, for everything under app/."""
    found: dict = {}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if (node.module and node.level == 0) else []
            else:
                continue
            for n in names:
                found.setdefault(n.split(".")[0], path.relative_to(APP).as_posix())
    return found


def test_every_third_party_import_is_declared():
    stdlib = getattr(sys, "stdlib_module_names", set())
    declared = _declared() | set(GUARANTEED_BY)
    missing = {
        mod: where for mod, where in _imported().items()
        if mod not in stdlib and mod not in declared and mod != "app"
        and not mod.startswith("_")
    }
    assert missing == {}, (
        "these are imported by the app but not declared in requirements.txt:\n  "
        + "\n  ".join(f"{m}  (in {w})" for m, w in sorted(missing.items()))
        + "\n\nA package that happens to be installed in development — anything a "
          "test tool pulls in — will not be in the deployed image, and the first "
          "request to reach the import raises ImportError as a 500.")


def test_the_check_can_actually_fail():
    """Guard the guard: if the import walk or the manifest parse silently found
    nothing, the test above would pass on any input."""
    assert len(_imported()) > 15, _imported()
    assert {"fastapi", "sqlalchemy", "httpx"} <= _declared(), sorted(_declared())
    # Every guarantee names a package that is genuinely declared.
    for mod, by in GUARANTEED_BY.items():
        assert by in _declared(), f"{mod} is said to come from {by}, which is not required"
