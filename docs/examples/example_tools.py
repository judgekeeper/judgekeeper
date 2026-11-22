"""Small helpers shared by the load.py scripts of label-studio/, people-agree/ and agent-steps/.

Nothing here talks to a model. It downloads one pinned file and checks its SHA-256, and it
builds the objects of a Label Studio "JSON" export (the full one: tasks with annotations and
predictions), in the shape Label Studio 1.23 writes.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path


def download(url: str, dest: Path, sha256: str) -> Path:
    """Fetch `url` to `dest` unless it is there, then check it against the pinned SHA-256."""
    if not dest.exists():
        print(f"downloading {dest.name}")
        with urllib.request.urlopen(url, timeout=300) as r:
            body = r.read()
        part = dest.with_suffix(dest.suffix + ".part")
        part.write_bytes(body)
        part.replace(dest)
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    if got != sha256:
        sys.exit(f"{dest.name}: sha256 {got} is not the pinned {sha256}; stop and look.")
    return dest


def choices_region(from_name: str, to_name: str, choice: str) -> dict:
    return {"from_name": from_name, "to_name": to_name, "type": "choices",
            "value": {"choices": [choice]}}


def number_region(from_name: str, to_name: str, number: int) -> dict:
    return {"from_name": from_name, "to_name": to_name, "type": "number",
            "value": {"number": number}}


def annotation(ann_id: int, task_id: int, project: int, completed_by: int, result: list,
               stamp: str, lead_time: float = 0.0, ground_truth: bool = False) -> dict:
    """One annotation. `completed_by` is a bare integer, as in a real export."""
    return {
        "id": ann_id, "completed_by": completed_by, "result": result, "was_cancelled": False,
        "ground_truth": ground_truth, "created_at": stamp, "updated_at": stamp,
        "draft_created_at": None, "lead_time": lead_time, "prediction": {},
        "result_count": len(result), "unique_id": f"annotation-{ann_id}", "import_id": None,
        "last_action": None, "bulk_created": False, "task": task_id, "project": project,
        "updated_by": completed_by, "parent_prediction": None, "parent_annotation": None,
        "last_created_by": None,
    }


def prediction(pred_id: int, task_id: int, project: int, model_version: str, result: list,
               stamp: str) -> dict:
    """One full prediction object (what the snapshot option predictions.only_id=false writes)."""
    return {
        "id": pred_id, "result": result, "model_version": model_version, "created_ago": "",
        "score": None, "cluster": None, "neighbors": None, "mislabeling": 0.0,
        "created_at": stamp, "updated_at": stamp, "model": None, "model_run": None,
        "task": task_id, "project": project,
    }


def task(task_id: int, project: int, data: dict, annotations: list, predictions: list,
         meta: dict, stamp: str) -> dict:
    return {
        "id": task_id, "annotations": annotations, "drafts": [], "predictions": predictions,
        "data": data, "meta": meta, "created_at": stamp, "updated_at": stamp,
        "allow_skip": True, "inner_id": task_id,
        "total_annotations": len([a for a in annotations if not a["was_cancelled"]]),
        "cancelled_annotations": len([a for a in annotations if a["was_cancelled"]]),
        "total_predictions": len(predictions), "comment_count": 0,
        "unresolved_comment_count": 0, "last_comment_updated_at": None, "project": project,
        "updated_by": 1, "comment_authors": [],
    }
