"""Export JSON and YAML from the same implemented, validated contract."""

import argparse
import json
from pathlib import Path

import yaml

from app.main import create_app

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs/001-personalized-learning-loop/contracts/openapi.runtime.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = create_app().openapi()
    document["servers"] = [{"url": "http://localhost:8000"}]
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    yaml_path = CONTRACT_PATH.with_name("openapi.yaml")
    yaml_encoded = yaml.safe_dump(document, allow_unicode=True, sort_keys=True)
    if args.check:
        for path, expected in ((CONTRACT_PATH, encoded), (yaml_path, yaml_encoded)):
            if not path.exists() or path.read_text() != expected:
                raise SystemExit("Implemented OpenAPI snapshot differs; regenerate and review it.")
    else:
        CONTRACT_PATH.write_text(encoded)
        yaml_path.write_text(yaml_encoded)


if __name__ == "__main__":
    main()
