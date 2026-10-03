"""Hash the immutable evaluation evidence, excluding this manifest itself."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
entries = {}
for path in sorted(HERE.iterdir()):
    if path.is_file() and path.name != "manifest.sha256.json":
        data = path.read_bytes()
        entries[path.name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
(HERE / "manifest.sha256.json").write_text(
    json.dumps({"schema": "profile-beta-1-e4-sql-manifest-v1", "files": entries},
               indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(json.dumps({"files": len(entries), "total_bytes": sum(e["bytes"] for e in entries.values())}))
