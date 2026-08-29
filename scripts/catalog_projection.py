"""Single pure public projection shared by the builder and artifact verifier."""
from __future__ import annotations


PUBLIC_FIELDS = ("name", "url", "description", "project_type", "declaration_file", "tags", "platforms", "status", "requires", "summary_zh", "summary_en", "license", "validation_level", "maintainer_type", "last_validated", "commit_sha", "catalog_status", "declaration_status", "interface_status", "default_branch")


def public_registry_projection(snapshot: dict) -> list[dict]:
    snapshot_id = snapshot["snapshot_id"]
    return [{**{field: asset.get(field, "" if field not in {"tags", "platforms", "requires"} else []) for field in PUBLIC_FIELDS}, "category": asset["catalog"]["category"], "subcategory": asset["catalog"]["subcategory"], "stage": asset["workflow"]["primary_stage"], "catalog": asset["catalog"], "workflow": asset["workflow"], "interface": asset["interface"], "snapshot_id": snapshot_id} for asset in snapshot["assets"] if asset.get("status") != "deprecated"]
