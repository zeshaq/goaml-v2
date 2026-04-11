import json
import math
import os
import random
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Annotated, List
from urllib.parse import urlparse

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(title="aml-scorer")

MODEL_PATH = os.getenv("SCORER_MODEL_PATH", "/models/aml_scorer.json")
METADATA_PATH = os.getenv("SCORER_METADATA_PATH", "/models/model_metadata.json")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://160.30.63.131:5000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "goaml-scorer")
MLFLOW_ARTIFACT_BUCKET = os.getenv("MLFLOW_ARTIFACT_BUCKET", "mlflow-artifacts")
MLFLOW_ARTIFACT_PREFIX = os.getenv("MLFLOW_ARTIFACT_PREFIX", "scorer-registry").strip("/")
ALLOW_BOOTSTRAP = os.getenv("SCORER_ALLOW_BOOTSTRAP", "true").lower() in {"1", "true", "yes", "on"}
model = None


class LegacyScoreRequest(BaseModel):
    features: List[List[float]]


class InlineScoreRequest(BaseModel):
    amount_usd: float
    transaction_type: str
    sender_country: str
    receiver_country: str
    currency: str
    channel: str
    hour_of_day: int
    day_of_week: int
    is_international: int
    is_cash: int
    is_crypto: int


class ScoreResponse(BaseModel):
    risk_score: float
    risk_level: str
    risk_factors: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    scoring_mode: str = "service"
    model_name: str | None = None
    registered_model_name: str | None = None
    model_version: str | None = None
    model_stage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegisterCurrentModelRequest(BaseModel):
    registered_model_name: str = Field(default_factory=lambda: os.getenv("SCORER_REGISTERED_MODEL_NAME", "goaml-xgboost-scorer"))
    experiment_name: str = Field(default_factory=lambda: MLFLOW_EXPERIMENT_NAME)
    actor: str | None = None
    description: str | None = None
    force_bootstrap_if_missing: bool = False


class DeployModelRequest(BaseModel):
    registered_model_name: str = Field(default_factory=lambda: os.getenv("SCORER_REGISTERED_MODEL_NAME", "goaml-xgboost-scorer"))
    version: str | None = None
    stage: str = "Production"
    actor: str | None = None
    notes: str | None = None
    reload_after_deploy: bool = True


class BootstrapModelRequest(BaseModel):
    actor: str | None = None
    sample_count: int = Field(default=2500, ge=500, le=20000)


class ChampionChallengerRequest(BaseModel):
    registered_model_name: str = Field(default_factory=lambda: os.getenv("SCORER_REGISTERED_MODEL_NAME", "goaml-xgboost-scorer"))
    champion_version: str | None = None
    challenger_version: str | None = None
    actor: str | None = None
    feature_rows: List[List[float]] = Field(default_factory=list)
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    sample_window: dict[str, Any] = Field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_mlflow():
    import mlflow

    os.environ.setdefault("MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI)
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return mlflow


def _s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MLFLOW_S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )


def _ensure_model_dir() -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(METADATA_PATH), exist_ok=True)


def _read_metadata() -> dict[str, Any]:
    if os.path.exists(METADATA_PATH):
        try:
            with open(METADATA_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_model_dir()
    with open(METADATA_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return payload


def _default_metadata() -> dict[str, Any]:
    payload = _read_metadata()
    payload.setdefault("model_name", os.getenv("SCORER_MODEL_NAME", "aml-xgboost-risk-scorer"))
    payload.setdefault("registered_model_name", os.getenv("SCORER_REGISTERED_MODEL_NAME", "goaml-xgboost-scorer"))
    payload.setdefault("model_version", os.getenv("SCORER_MODEL_VERSION"))
    payload.setdefault("model_stage", os.getenv("SCORER_MODEL_STAGE"))
    payload.setdefault("source", payload.get("source") or "gpu-01-local-model-dir")
    payload["model_path"] = payload.get("model_path") or MODEL_PATH
    payload["model_path_exists"] = os.path.exists(MODEL_PATH)
    payload["request_contract"] = "inline_transaction_or_legacy_features"
    payload["loaded_at"] = payload.get("loaded_at") or _utc_now_iso()
    payload["scoring_mode"] = "service" if payload["model_path_exists"] else "metadata_only"
    payload["mlflow_tracking_uri"] = MLFLOW_TRACKING_URI
    payload["admin_capabilities"] = ["register_current", "deploy_from_mlflow"] + (["bootstrap_baseline"] if ALLOW_BOOTSTRAP else [])
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(item) for item in warnings]
    if not payload["model_path_exists"]:
        warnings.append(f"Model file not found at {MODEL_PATH}")
    payload["warnings"] = list(dict.fromkeys(warnings))
    return payload


def load_runtime_metadata() -> dict[str, Any]:
    return _default_metadata()


def _set_loaded_model(booster) -> None:
    global model
    model = booster


def get_model():
    global model
    if model is None:
        import xgboost as xgb

        if not os.path.exists(MODEL_PATH):
            raise RuntimeError(f"Model not found at {MODEL_PATH}")
        booster = xgb.Booster()
        booster.load_model(MODEL_PATH)
        model = booster
    return model


def _save_booster(booster, metadata_updates: dict[str, Any] | None = None):
    _ensure_model_dir()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", dir=os.path.dirname(MODEL_PATH)) as handle:
        temp_path = handle.name
    booster.save_model(temp_path)
    os.replace(temp_path, MODEL_PATH)
    metadata = _default_metadata()
    metadata.update(metadata_updates or {})
    metadata["model_path"] = MODEL_PATH
    metadata["model_path_exists"] = True
    metadata["loaded_at"] = _utc_now_iso()
    metadata["scoring_mode"] = "service"
    metadata["warnings"] = [item for item in metadata.get("warnings", []) if "Model file not found" not in str(item)]
    _write_metadata(metadata)
    _set_loaded_model(booster)
    return metadata


def _predict_scores_for_booster(booster, feature_rows: list[list[float]]) -> list[float]:
    import xgboost as xgb

    matrix = xgb.DMatrix(np.asarray(feature_rows, dtype=np.float32))
    return [float(value) for value in booster.predict(matrix).tolist()]


def _load_booster_from_source(source_uri: str):
    import xgboost as xgb

    bundle_dir = _download_bundle_from_source(source_uri)
    try:
        model_file = _find_bundle_file(bundle_dir, "aml_scorer.json")
        booster = xgb.Booster()
        booster.load_model(model_file)
        return booster
    finally:
        shutil.rmtree(bundle_dir, ignore_errors=True)


def _score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {
            "mean_score": 0.0,
            "median_score": 0.0,
            "p95_score": 0.0,
            "high_risk_rate": 0.0,
            "medium_or_higher_rate": 0.0,
        }
    ordered = sorted(scores)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    return {
        "mean_score": round(float(np.mean(scores)), 6),
        "median_score": round(float(median), 6),
        "p95_score": round(float(np.percentile(scores, 95)), 6),
        "high_risk_rate": round(float(sum(1 for value in scores if value >= 0.75) / len(scores)), 6),
        "medium_or_higher_rate": round(float(sum(1 for value in scores if value >= 0.45) / len(scores)), 6),
    }


def inline_request_to_features(req: InlineScoreRequest) -> list[list[float]]:
    return [[
        float(req.amount_usd),
        float(req.is_international),
        float(req.is_cash),
        float(req.is_crypto),
        float(req.hour_of_day),
        float(req.day_of_week),
        1.0 if str(req.sender_country).upper() != str(req.receiver_country).upper() else 0.0,
    ]]


def build_risk_factors(req: InlineScoreRequest, score: float) -> list[str]:
    factors: list[str] = []
    if req.amount_usd >= 10000:
        factors.append("HIGH_AMT")
    if req.amount_usd >= 50000:
        factors.append("VERY_HIGH_AMT")
    if req.is_cash:
        factors.append("CASH")
    if req.is_crypto:
        factors.append("CRYPTO")
    if req.is_international:
        factors.append("INTERNATIONAL")
    if str(req.sender_country).upper() in {"IR", "KP", "SY", "CU"}:
        factors.append("SANCTIONED_COUNTRY")
    if req.hour_of_day < 5:
        factors.append("ODD_HOURS")
    if score >= 0.75:
        factors.append("ML_HIGH")
    elif score >= 0.45:
        factors.append("ML_MEDIUM")
    return factors


def risk_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _rule_target(amount_usd: float, is_international: int, is_cash: int, is_crypto: int, hour_of_day: int, sanctioned: int) -> float:
    score = 0.03
    if amount_usd >= 10_000:
        score += 0.25
    if amount_usd >= 50_000:
        score += 0.2
    if is_cash:
        score += 0.2
    if is_crypto:
        score += 0.24
    if is_international:
        score += 0.1
    if sanctioned:
        score += 0.32
    if hour_of_day < 5:
        score += 0.05
    score += random.uniform(-0.03, 0.03)
    return max(0.0, min(score, 1.0))


def bootstrap_baseline_model(sample_count: int = 2500, actor: str | None = None) -> dict[str, Any]:
    if not ALLOW_BOOTSTRAP:
        raise RuntimeError("Bootstrap baseline model generation is disabled.")
    import xgboost as xgb

    random.seed(42)
    np.random.seed(42)
    rows: list[list[float]] = []
    labels: list[float] = []
    for _ in range(sample_count):
        amount = float(np.random.lognormal(mean=8.6, sigma=1.0))
        is_international = int(random.random() < 0.42)
        is_cash = int(random.random() < 0.18)
        is_crypto = int(random.random() < 0.12)
        hour_of_day = int(random.randint(0, 23))
        day_of_week = int(random.randint(0, 6))
        sanctioned = int(random.random() < 0.035)
        rows.append([amount, is_international, is_cash, is_crypto, hour_of_day, day_of_week, sanctioned])
        labels.append(_rule_target(amount, is_international, is_cash, is_crypto, hour_of_day, sanctioned))

    X = np.asarray(rows, dtype=np.float32)
    y = np.asarray(labels, dtype=np.float32)
    dtrain = xgb.DMatrix(X, label=y)
    params = {
        "objective": "reg:squarederror",
        "max_depth": 4,
        "eta": 0.12,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "seed": 42,
        "eval_metric": "rmse",
    }
    booster = xgb.train(params, dtrain, num_boost_round=80)
    metadata = _save_booster(
        booster,
        {
            "model_name": os.getenv("SCORER_MODEL_NAME", "aml-xgboost-risk-scorer"),
            "registered_model_name": os.getenv("SCORER_REGISTERED_MODEL_NAME", "goaml-xgboost-scorer"),
            "model_version": None,
            "model_stage": None,
            "source": "bootstrap_baseline",
            "bootstrap": {
                "sample_count": sample_count,
                "actor": actor,
                "created_at": _utc_now_iso(),
            },
        },
    )
    return {
        "status": "bootstrapped",
        "sample_count": sample_count,
        "metadata": metadata,
    }


def _resolve_model_version(client, registered_model_name: str, version: str | None, stage: str | None):
    if version:
        return client.get_model_version(registered_model_name, str(version))
    target_stage = str(stage or "Production").lower()
    versions = client.search_model_versions(f"name='{registered_model_name}'")
    filtered = [item for item in versions if str(getattr(item, "current_stage", "")).lower() == target_stage]
    if not filtered:
        raise RuntimeError(f"No model version in stage {stage} for {registered_model_name}.")
    filtered.sort(key=lambda item: int(getattr(item, "version", "0")), reverse=True)
    return filtered[0]


def _ensure_experiment(client, experiment_name: str) -> str:
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment:
        return str(experiment.experiment_id)
    return str(client.create_experiment(experiment_name))


def _find_bundle_file(bundle_dir: str, filename: str) -> str:
    direct = os.path.join(bundle_dir, filename)
    if os.path.exists(direct):
        return direct
    for root, _, files in os.walk(bundle_dir):
        if filename in files:
            return os.path.join(root, filename)
    raise RuntimeError(f"Expected {filename} inside downloaded model bundle, but it was not found.")


def _parse_s3_uri(source_uri: str) -> tuple[str, str]:
    parsed = urlparse(source_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise RuntimeError(f"Unsupported model artifact source URI: {source_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _upload_bundle_to_artifact_store(bundle_dir: str, registered_model_name: str, run_id: str) -> tuple[str, dict[str, Any]]:
    s3 = _s3_client()
    prefix = f"{MLFLOW_ARTIFACT_PREFIX}/{registered_model_name}/runs/{run_id}/bundle".strip("/")
    uploaded_files: list[str] = []
    for root, _, files in os.walk(bundle_dir):
        for name in files:
            local_path = os.path.join(root, name)
            relative_path = os.path.relpath(local_path, bundle_dir).replace(os.sep, "/")
            object_key = f"{prefix}/{relative_path}"
            s3.upload_file(local_path, MLFLOW_ARTIFACT_BUCKET, object_key)
            uploaded_files.append(relative_path)
    return (
        f"s3://{MLFLOW_ARTIFACT_BUCKET}/{prefix}",
        {
            "bucket": MLFLOW_ARTIFACT_BUCKET,
            "prefix": prefix,
            "uploaded_files": sorted(uploaded_files),
        },
    )


def _download_bundle_from_source(source_uri: str) -> str:
    if source_uri.startswith("s3://"):
        bucket, prefix = _parse_s3_uri(source_uri)
        prefix = prefix.rstrip("/")
        if not prefix:
            raise RuntimeError("Model source URI is missing an artifact prefix.")
        download_dir = tempfile.mkdtemp(prefix="scorer-bundle-")
        s3 = _s3_client()
        continuation_token: str | None = None
        downloaded = 0
        while True:
            params: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if continuation_token:
                params["ContinuationToken"] = continuation_token
            response = s3.list_objects_v2(**params)
            for item in response.get("Contents", []) or []:
                key = item.get("Key")
                if not key or key.endswith("/"):
                    continue
                relative_path = key[len(prefix):].lstrip("/")
                if not relative_path:
                    continue
                target_path = os.path.join(download_dir, relative_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                s3.download_file(bucket, key, target_path)
                downloaded += 1
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        if downloaded == 0:
            raise RuntimeError(f"No model bundle objects were found at {source_uri}")
        return download_dir

    mlflow = _configure_mlflow()
    return mlflow.artifacts.download_artifacts(artifact_uri=source_uri)


def register_current_model_to_mlflow(payload: RegisterCurrentModelRequest) -> dict[str, Any]:
    if not os.path.exists(MODEL_PATH):
        if payload.force_bootstrap_if_missing:
            bootstrap_baseline_model(actor=payload.actor)
        else:
            raise RuntimeError(f"Model not found at {MODEL_PATH}")
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
    experiment_name = payload.experiment_name or MLFLOW_EXPERIMENT_NAME
    experiment_id = _ensure_experiment(client, experiment_name)
    runtime_metadata = load_runtime_metadata()
    run_name = f"scorer-register-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    run = client.create_run(
        experiment_id,
        tags={
            "mlflow.runName": run_name,
            "system": "goaml-v2",
            "deployment_target": "goaml-scorer",
            "registered_by": payload.actor or "unknown",
            "registered_model_name": payload.registered_model_name,
        },
    )
    run_id = str(run.info.run_id)
    bundle_dir = tempfile.mkdtemp(prefix="scorer-register-")
    try:
        client.log_param(run_id, "model_name", str(runtime_metadata.get("model_name") or "unknown"))
        client.log_param(run_id, "registered_model_name", payload.registered_model_name)
        client.log_param(run_id, "source", str(runtime_metadata.get("source") or "unknown"))
        client.log_param(run_id, "request_contract", str(runtime_metadata.get("request_contract") or "unknown"))
        if payload.description:
            client.set_tag(run_id, "registration_description", payload.description)

        shutil.copy2(MODEL_PATH, os.path.join(bundle_dir, "aml_scorer.json"))
        registration_metadata = {
            "registered_model_name": payload.registered_model_name,
            "run_id": run_id,
            "registered_at": _utc_now_iso(),
            "registered_by": payload.actor or "unknown",
            "description": payload.description,
            "experiment_name": experiment_name,
            "runtime_metadata": runtime_metadata,
        }
        with open(os.path.join(bundle_dir, "runtime_metadata.json"), "w", encoding="utf-8") as handle:
            json.dump(runtime_metadata, handle, indent=2, sort_keys=True)
        with open(os.path.join(bundle_dir, "registration_metadata.json"), "w", encoding="utf-8") as handle:
            json.dump(registration_metadata, handle, indent=2, sort_keys=True)

        source_uri, artifact_store = _upload_bundle_to_artifact_store(bundle_dir, payload.registered_model_name, run_id)
        client.set_tag(run_id, "artifact_bucket", artifact_store["bucket"])
        client.set_tag(run_id, "artifact_prefix", artifact_store["prefix"])

        created_version = client.create_model_version(
            name=payload.registered_model_name,
            source=source_uri,
            run_id=run_id,
        )
        version = str(created_version.version)
        if payload.description:
            client.update_model_version(
                name=payload.registered_model_name,
                version=version,
                description=payload.description,
            )

        resolved = None
        for _ in range(20):
            resolved = client.get_model_version(payload.registered_model_name, version)
            if str(getattr(resolved, "status", "")).upper() == "READY":
                break
            time.sleep(1)
        if resolved is None:
            raise RuntimeError("Model version registration did not return a version record.")

        client.set_model_version_tag(payload.registered_model_name, version, "registered_by", payload.actor or "unknown")
        client.set_model_version_tag(payload.registered_model_name, version, "deployment_target", "goaml-scorer")
        client.set_model_version_tag(payload.registered_model_name, version, "artifact_bucket", artifact_store["bucket"])
        client.set_model_version_tag(payload.registered_model_name, version, "artifact_prefix", artifact_store["prefix"])
        client.set_terminated(run_id, status="FINISHED")

        metadata = load_runtime_metadata()
        metadata["last_registered_run_id"] = run_id
        metadata["last_registered_version"] = version
        metadata["last_registered_source"] = source_uri
        metadata["last_registered_at"] = _utc_now_iso()
        metadata["last_registered_by"] = payload.actor or "unknown"
        _write_metadata(metadata)
        return {
            "status": "registered",
            "registered_model_name": payload.registered_model_name,
            "version": version,
            "stage": getattr(resolved, "current_stage", None) or "None",
            "run_id": run_id,
            "source_uri": source_uri,
            "artifact_store": artifact_store,
            "metadata": load_runtime_metadata(),
        }
    except Exception:
        try:
            client.set_tag(run_id, "registration_status", "failed")
            client.set_terminated(run_id, status="FAILED")
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(bundle_dir, ignore_errors=True)


def deploy_model_from_mlflow(payload: DeployModelRequest) -> dict[str, Any]:
    from mlflow.tracking import MlflowClient
    import xgboost as xgb

    client = MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
    resolved = _resolve_model_version(client, payload.registered_model_name, payload.version, payload.stage)
    resolved_version = str(getattr(resolved, "version"))
    resolved_stage = getattr(resolved, "current_stage", None) or payload.stage or "None"
    source_uri = getattr(resolved, "source", None)
    if not source_uri:
        raise RuntimeError("Resolved MLflow model version did not contain a source URI.")
    bundle_dir = _download_bundle_from_source(source_uri)
    try:
        model_file = _find_bundle_file(bundle_dir, "aml_scorer.json")
        booster = xgb.Booster()
        booster.load_model(model_file)
    finally:
        shutil.rmtree(bundle_dir, ignore_errors=True)
    metadata = _save_booster(
        booster,
        {
            "model_name": os.getenv("SCORER_MODEL_NAME", "aml-xgboost-risk-scorer"),
            "registered_model_name": payload.registered_model_name,
            "model_version": resolved_version,
            "model_stage": resolved_stage,
            "source": "mlflow_registry",
            "run_id": getattr(resolved, "run_id", None),
            "registry_source_uri": source_uri,
            "deployed_at": _utc_now_iso(),
            "deployed_by": payload.actor or "unknown",
            "deployment_notes": payload.notes,
        },
    )
    if payload.reload_after_deploy:
        _set_loaded_model(booster)
    return {
        "status": "deployed",
        "registered_model_name": payload.registered_model_name,
        "version": resolved_version,
        "stage": resolved_stage,
        "metadata": metadata,
    }


def compare_model_versions(payload: ChampionChallengerRequest) -> dict[str, Any]:
    from mlflow.tracking import MlflowClient

    if not payload.feature_rows:
        raise RuntimeError("Champion/challenger comparison requires at least one feature row.")
    client = MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
    champion_resolved = _resolve_model_version(client, payload.registered_model_name, payload.champion_version, "Production")
    champion_version = str(getattr(champion_resolved, "version"))

    challenger_version = payload.challenger_version
    challenger_resolved = None
    if challenger_version:
        challenger_resolved = client.get_model_version(payload.registered_model_name, str(challenger_version))
    else:
        versions = client.search_model_versions(f"name='{payload.registered_model_name}'")
        candidates = [item for item in versions if str(getattr(item, "version", "")) != champion_version]
        candidates.sort(key=lambda item: int(getattr(item, "version", "0")), reverse=True)
        if not candidates:
            raise RuntimeError("No challenger version is available for comparison.")
        challenger_resolved = candidates[0]
    challenger_version = str(getattr(challenger_resolved, "version"))
    if challenger_version == champion_version:
        raise RuntimeError("Champion and challenger versions must be different.")

    champion_source = getattr(champion_resolved, "source", None)
    challenger_source = getattr(challenger_resolved, "source", None)
    if not champion_source or not challenger_source:
        raise RuntimeError("One of the compared model versions is missing its artifact source URI.")

    champion_booster = _load_booster_from_source(champion_source)
    challenger_booster = _load_booster_from_source(challenger_source)
    champion_scores = _predict_scores_for_booster(champion_booster, payload.feature_rows)
    challenger_scores = _predict_scores_for_booster(challenger_booster, payload.feature_rows)

    top_changes: list[dict[str, Any]] = []
    absolute_deltas: list[float] = []
    disagreements = 0
    challenger_higher = 0
    challenger_lower = 0
    for index, (champion_score, challenger_score) in enumerate(zip(champion_scores, challenger_scores)):
        transaction = payload.transactions[index] if index < len(payload.transactions) and isinstance(payload.transactions[index], dict) else {}
        delta = float(challenger_score - champion_score)
        absolute_deltas.append(abs(delta))
        champion_bucket = risk_level(champion_score)
        challenger_bucket = risk_level(challenger_score)
        if champion_bucket != challenger_bucket:
            disagreements += 1
        if delta > 0.01:
            challenger_higher += 1
        elif delta < -0.01:
            challenger_lower += 1
        top_changes.append(
            {
                "transaction_ref": transaction.get("transaction_ref"),
                "transacted_at": transaction.get("transacted_at"),
                "persisted_score": round(float(transaction.get("persisted_score") or 0.0), 6),
                "persisted_risk_level": transaction.get("persisted_risk_level"),
                "champion_score": round(float(champion_score), 6),
                "challenger_score": round(float(challenger_score), 6),
                "delta": round(delta, 6),
                "champion_risk_level": champion_bucket,
                "challenger_risk_level": challenger_bucket,
            }
        )
    top_changes.sort(key=lambda item: abs(float(item.get("delta") or 0.0)), reverse=True)
    sample_size = len(payload.feature_rows)
    mean_abs_delta = float(sum(absolute_deltas) / sample_size) if sample_size else 0.0
    disagreement_rate = float(disagreements / sample_size) if sample_size else 0.0

    return {
        "status": "completed",
        "summary": {
            "status": "completed",
            "champion_version": champion_version,
            "challenger_version": challenger_version,
            "champion_stage": getattr(champion_resolved, "current_stage", None) or "Production",
            "challenger_stage": getattr(challenger_resolved, "current_stage", None) or "None",
            "sample_size": sample_size,
            "window_start": payload.sample_window.get("window_start"),
            "window_end": payload.sample_window.get("window_end"),
            "mean_abs_delta": round(mean_abs_delta, 6),
            "max_abs_delta": round(max(absolute_deltas or [0.0]), 6),
            "disagreement_rate": round(disagreement_rate, 6),
            "challenger_higher_rate": round(float(challenger_higher / sample_size) if sample_size else 0.0, 6),
            "challenger_lower_rate": round(float(challenger_lower / sample_size) if sample_size else 0.0, 6),
            "notes": payload.notes,
        },
        "metrics": {
            "champion": {
                "version": champion_version,
                "stage": getattr(champion_resolved, "current_stage", None) or "Production",
                **_score_summary(champion_scores),
            },
            "challenger": {
                "version": challenger_version,
                "stage": getattr(challenger_resolved, "current_stage", None) or "None",
                **_score_summary(challenger_scores),
            },
            "delta": {
                "mean_abs_delta": round(mean_abs_delta, 6),
                "median_abs_delta": round(float(np.median(absolute_deltas)) if absolute_deltas else 0.0, 6),
                "max_abs_delta": round(max(absolute_deltas or [0.0]), 6),
                "disagreement_rate": round(disagreement_rate, 6),
            },
            "top_changes": top_changes[:10],
        },
        "metadata": {
            "actor": payload.actor,
            "champion_source": champion_source,
            "challenger_source": challenger_source,
            "generated_at": _utc_now_iso(),
        },
    }


@app.get("/health")
def health():
    metadata = load_runtime_metadata()
    return {
        "status": "ok",
        "mode": metadata.get("scoring_mode"),
        "model_path_exists": metadata.get("model_path_exists"),
    }


@app.get("/metadata")
def metadata():
    return load_runtime_metadata()


@app.post("/admin/bootstrap-baseline")
def admin_bootstrap_baseline(payload: BootstrapModelRequest | None = None):
    payload = payload or BootstrapModelRequest()
    try:
        return bootstrap_baseline_model(sample_count=payload.sample_count, actor=payload.actor)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/admin/register-current")
def admin_register_current(payload: RegisterCurrentModelRequest):
    try:
        return register_current_model_to_mlflow(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/admin/deploy")
def admin_deploy(payload: DeployModelRequest):
    try:
        return deploy_model_from_mlflow(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/admin/champion-challenger")
def admin_champion_challenger(payload: ChampionChallengerRequest):
    try:
        return compare_model_versions(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/score", response_model=ScoreResponse)
def score(req: Annotated[LegacyScoreRequest | InlineScoreRequest, Body(...)]):
    try:
        import xgboost as xgb

        runtime_metadata = load_runtime_metadata()
        booster = get_model()
        if isinstance(req, InlineScoreRequest):
            feature_rows = inline_request_to_features(req)
            feature_payload: dict[str, Any] = req.model_dump()
        else:
            feature_rows = req.features
            feature_payload = {"features": req.features}
        X = np.array(feature_rows, dtype=np.float32)
        dmatrix = xgb.DMatrix(X)
        preds = booster.predict(dmatrix).tolist()
        score_value = float(preds[0]) if preds else 0.0
        return ScoreResponse(
            risk_score=score_value,
            risk_level=risk_level(score_value),
            risk_factors=build_risk_factors(req, score_value) if isinstance(req, InlineScoreRequest) else [],
            features=feature_payload,
            scoring_mode="service",
            model_name=runtime_metadata.get("model_name"),
            registered_model_name=runtime_metadata.get("registered_model_name"),
            model_version=str(runtime_metadata.get("model_version"))
            if runtime_metadata.get("model_version") not in (None, "")
            else None,
            model_stage=runtime_metadata.get("model_stage"),
            metadata=runtime_metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
