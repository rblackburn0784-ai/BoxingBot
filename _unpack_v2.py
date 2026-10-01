from pathlib import Path
import base64
import io
import shutil
import tarfile

root = Path(__file__).resolve().parent
payload_dir = root / "_v2_payload"
payload = b"".join(p.read_bytes() for p in sorted(payload_dir.glob("part_*")))
data = base64.b85decode(payload)

# Remove the obsolete v0.3 Python/source tree while preserving Git metadata,
# the historical media assets, licence, and the temporary promotion files.
for name in ["boxing_bot", "tests", "__pycache__"]:
    p = root / name
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()

for p in list(root.iterdir()):
    if p.name in {".git", ".github", "graphics", "LICENSE", "_v2_payload", "_unpack_v2.py"}:
        continue
    if p.is_file():
        p.unlink()

with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
    for member in tf.getmembers():
        rel = Path(member.name)
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError(f"Unsafe archive path: {member.name}")
    tf.extractall(root)

(root / ".gitignore").write_text(
    ".env\n"
    ".venv/\n"
    "venv/\n"
    "__pycache__/\n"
    "*.py[cod]\n"
    "boxing_v2.sqlite3\n"
    "boxing_v2.sqlite3-*\n"
    "backups/\n",
    encoding="utf-8",
)

readme_v2 = root / "README_V2.md"
if readme_v2.exists():
    shutil.copyfile(readme_v2, root / "README.md")

shutil.rmtree(payload_dir, ignore_errors=True)
