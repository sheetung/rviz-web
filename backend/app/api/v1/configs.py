from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...core.config import get_settings

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = PROJECT_ROOT / "rvizweb_configs"
BACKUP_DIR = CONFIG_DIR / "backups"
CONFIG_SUFFIX = ".rvizweb"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_storage_lock = threading.Lock()


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vector3Config(StrictConfigModel):
    x: float = 0
    y: float = 0
    z: float = 0


class CameraConfig(StrictConfigModel):
    position: Vector3Config
    target: Vector3Config
    up: Vector3Config = Field(default_factory=lambda: Vector3Config(z=1))
    zoom: float = Field(default=1, gt=0, le=100)
    projection: Literal["perspective", "orthographic"] = "perspective"


class SceneConfig(StrictConfigModel):
    showGrid: bool = True
    showAxes: bool = True
    viewPreset: Literal["iso", "top", "front", "side"] = "iso"
    camera: Optional[CameraConfig] = None


class DisplayConfig(StrictConfigModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=512)
    messageType: str = Field(min_length=1, max_length=256)
    visible: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class LayoutConfig(StrictConfigModel):
    sceneWidth: float = Field(default=68, ge=20, le=90)
    panelHeights: Dict[str, float] = Field(default_factory=dict)
    collapsedPanels: Dict[str, bool] = Field(default_factory=dict)


class AppearanceConfig(StrictConfigModel):
    theme: Literal["dark", "light"] = "dark"


class VideoLayoutConfig(StrictConfigModel):
    x: Optional[float] = None
    y: Optional[float] = None
    width: float = Field(default=360, ge=160, le=4096)
    height: float = Field(default=240, ge=160, le=2160)


class VideoConfig(StrictConfigModel):
    sourceUrl: str = Field(default="", max_length=2048)
    visible: bool = False
    layout: VideoLayoutConfig = Field(default_factory=VideoLayoutConfig)

    @field_validator("sourceUrl")
    @classmethod
    def reject_persisted_credentials(cls, value: str) -> str:
        source_url = value.strip()
        if not source_url:
            return ""
        parsed = urlsplit(source_url)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("配置文件不能保存 RTSP 凭据或查询令牌，请在连接时输入")
        return source_url


class PositionConfig(StrictConfigModel):
    odomTopic: str = Field(default="", max_length=512)
    showRobotModel: bool = False
    showTrajectory: bool = True
    trajectoryLength: int = Field(default=100, ge=10, le=100)


class GoalConfig(StrictConfigModel):
    topic: str = Field(default="", max_length=512)
    x: float = 0
    y: float = 0
    z: float = 0


class LaserConfig(StrictConfigModel):
    laserType: Literal["2d", "3d"] = "3d"
    laserScanTopic: str = Field(default="", max_length=512)
    pointCloudTopic: str = Field(default="", max_length=512)
    showLaserPoints: bool = True
    showLaserLines: bool = True
    showIntensity: bool = False
    laserPointSize: float = Field(default=0.15, gt=0, le=10)
    pointSize: float = Field(default=0.03, gt=0, le=10)
    pointOpacity: float = Field(default=0.8, ge=0, le=1)


class MapConfig(StrictConfigModel):
    mapTopic: str = Field(default="", max_length=512)
    showMap: bool = True
    showMapGrid: bool = False
    showMapOrigin: bool = True
    mapOpacity: float = Field(default=0.8, ge=0, le=1)


class FrontendConfig(StrictConfigModel):

    fixedFrame: str = Field(default="map", min_length=1, max_length=256)
    followFrame: str = Field(default="", max_length=256)
    scene: SceneConfig = Field(default_factory=SceneConfig)
    displays: List[DisplayConfig] = Field(default_factory=list, max_length=256)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    appearance: AppearanceConfig = Field(default_factory=AppearanceConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    goal: GoalConfig = Field(default_factory=GoalConfig)
    position: PositionConfig = Field(default_factory=PositionConfig)
    laser: LaserConfig = Field(default_factory=LaserConfig)
    map: MapConfig = Field(default_factory=MapConfig)
    extensions: Dict[str, Any] = Field(default_factory=dict)


class ConfigPayload(BaseModel):
    name: str = Field(default="default.rvizweb")
    config: FrontendConfig


class StoredConfig(BaseModel):
    name: str
    version: Literal[1]
    config: FrontendConfig


class ConfigResponse(StoredConfig):
    modified_at: datetime
    repaired: bool = False
    repairs: List[str] = Field(default_factory=list)


class ConfigSaveResult(BaseModel):
    name: str
    status: Literal["saved"]
    modified_at: datetime


def _normalize_name(name: str) -> str:
    settings = get_settings()
    value = (name or "default.rvizweb").strip()
    if value.endswith(".rviz"):
        value = value[:-5]
    if not value.endswith(CONFIG_SUFFIX):
        value = f"{value}{CONFIG_SUFFIX}"
    if len(value) > settings.config_name_max_length:
        raise HTTPException(status_code=400, detail="配置文件名过长")
    if not SAFE_NAME.fullmatch(value):
        raise HTTPException(
            status_code=400, detail="配置文件名只能包含字母、数字、点、横线和下划线"
        )
    return value


def _config_path(name: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / _normalize_name(name)
    if path.parent.resolve() != CONFIG_DIR.resolve():
        raise HTTPException(status_code=400, detail="配置文件路径越界")
    if path.is_symlink():
        raise HTTPException(status_code=400, detail="配置文件不能是符号链接")
    return path


_CONFIG_ALIASES = {
    "fixed_frame": "fixedFrame",
    "follow_frame": "followFrame",
}
_SECTION_ALIASES = {
    "scene": {
        "show_grid": "showGrid",
        "show_axes": "showAxes",
        "view_preset": "viewPreset",
    },
    "layout": {
        "scene_width": "sceneWidth",
        "panel_heights": "panelHeights",
        "collapsed_panels": "collapsedPanels",
    },
    "video": {"source_url": "sourceUrl"},
    "position": {
        "odom_topic": "odomTopic",
        "show_robot_model": "showRobotModel",
        "show_trajectory": "showTrajectory",
        "trajectory_length": "trajectoryLength",
    },
    "laser": {
        "laser_type": "laserType",
        "laser_scan_topic": "laserScanTopic",
        "point_cloud_topic": "pointCloudTopic",
        "show_laser_points": "showLaserPoints",
        "show_laser_lines": "showLaserLines",
        "show_intensity": "showIntensity",
        "laser_point_size": "laserPointSize",
        "point_size": "pointSize",
        "point_opacity": "pointOpacity",
    },
    "map": {
        "map_topic": "mapTopic",
        "show_map": "showMap",
        "show_map_grid": "showMapGrid",
        "show_map_origin": "showMapOrigin",
        "map_opacity": "mapOpacity",
    },
}


def _rename_aliases(
    values: Dict[str, Any], aliases: Dict[str, str], prefix: str, repairs: List[str]
) -> None:
    for legacy_name, current_name in aliases.items():
        if legacy_name not in values:
            continue
        if current_name not in values:
            values[current_name] = values[legacy_name]
        values.pop(legacy_name, None)
        repairs.append(f"{prefix}{legacy_name}->{current_name}")


def _repair_stored_document(
    raw_document: Any, expected_name: str
) -> tuple[Dict[str, Any], List[str]]:
    if not isinstance(raw_document, dict):
        raise ValueError("配置文件根节点必须是对象")

    repairs: List[str] = []
    document = deepcopy(raw_document)
    if not isinstance(document.get("config"), dict):
        if "fixedFrame" in document or "fixed_frame" in document:
            document = {"name": expected_name, "version": 1, "config": document}
            repairs.append("document:wrapped")
        else:
            return document, repairs

    if document.get("name") != expected_name:
        document["name"] = expected_name
        repairs.append("document.name")
    if "version" not in document:
        document["version"] = 1
        repairs.append("document.version")
    elif document["version"] == "1":
        document["version"] = 1
        repairs.append("document.version:string->integer")

    config = document["config"]
    _rename_aliases(config, _CONFIG_ALIASES, "config.", repairs)
    for section_name, aliases in _SECTION_ALIASES.items():
        section = config.get(section_name)
        if isinstance(section, dict):
            _rename_aliases(section, aliases, f"config.{section_name}.", repairs)

    displays = config.get("displays")
    if isinstance(displays, list):
        for index, display in enumerate(displays):
            if isinstance(display, dict):
                _rename_aliases(
                    display,
                    {"message_type": "messageType"},
                    f"config.displays[{index}].",
                    repairs,
                )

    layout = config.get("layout")
    if isinstance(layout, dict):
        for mapping_name in ("panelHeights", "collapsedPanels"):
            mapping = layout.get(mapping_name)
            if isinstance(mapping, dict) and "controller" in mapping:
                mapping.pop("controller", None)
                repairs.append(f"config.layout.{mapping_name}.controller")

    known_fields = set(FrontendConfig.model_fields)
    unknown_fields = sorted(set(config) - known_fields)
    if unknown_fields:
        extensions = config.get("extensions")
        if not isinstance(extensions, dict):
            extensions = {}
            config["extensions"] = extensions
        legacy = extensions.setdefault("legacy", {})
        if not isinstance(legacy, dict):
            legacy = {"previous": legacy}
            extensions["legacy"] = legacy
        for field_name in unknown_fields:
            legacy[field_name] = config.pop(field_name)
            repairs.append(f"config.{field_name}->extensions.legacy")

    return document, repairs


def _read_validated_with_repairs(path: Path) -> tuple[StoredConfig, List[str]]:
    settings = get_settings()
    try:
        if path.stat().st_size > settings.config_max_bytes:
            raise HTTPException(status_code=413, detail="配置文件超过大小限制")
        content = path.read_text(encoding="utf-8")
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=404, detail="配置文件不存在") from exc
    try:
        raw_document = json.loads(content)
        repaired_document, repairs = _repair_stored_document(raw_document, path.name)
        return StoredConfig.model_validate(repaired_document), repairs
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"配置文件格式无效: {exc}",
        ) from exc


def _read_validated(path: Path) -> StoredConfig:
    stored, _ = _read_validated_with_repairs(path)
    return stored


def _write_atomic(path: Path, encoded: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=CONFIG_DIR,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {exc}") from exc


def _modified_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _prune_backups() -> None:
    settings = get_settings()
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        (
            path
            for path in BACKUP_DIR.glob(f"*{CONFIG_SUFFIX}.bak")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    retained_bytes = 0
    for index, path in enumerate(backups):
        size = path.stat().st_size
        exceeds_count = index >= settings.config_backup_max_files
        exceeds_bytes = retained_bytes + size > settings.config_backup_max_bytes
        if exceeds_count or exceeds_bytes:
            path.unlink(missing_ok=True)
        else:
            retained_bytes += size


def _create_backup(path: Path) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = BACKUP_DIR / f"{path.stem}.{stamp}{CONFIG_SUFFIX}.bak"
    shutil.copy2(path, backup_path)
    _prune_backups()


@router.get("/configs", response_model=List[str])
async def list_configs() -> List[str]:
    with _storage_lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        return sorted(
            path.name
            for path in CONFIG_DIR.glob(f"*{CONFIG_SUFFIX}")
            if path.is_file() and not path.is_symlink()
        )


@router.get("/configs/{name}", response_model=ConfigResponse)
async def get_config(name: str) -> ConfigResponse:
    with _storage_lock:
        path = _config_path(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="配置文件不存在")
        stored, repairs = _read_validated_with_repairs(path)
        if repairs:
            _create_backup(path)
            _write_atomic(path, stored.model_dump_json(indent=2).encode("utf-8"))
        return ConfigResponse(
            **stored.model_dump(),
            modified_at=_modified_at(path),
            repaired=bool(repairs),
            repairs=repairs,
        )


@router.post(
    "/configs/{name}",
    response_model=ConfigSaveResult,
)
async def save_config(name: str, payload: ConfigPayload) -> ConfigSaveResult:
    with _storage_lock:
        path = _config_path(name)
        raw_document, _ = _repair_stored_document(
            {
                "name": path.name,
                "version": 1,
                "config": payload.config.model_dump(),
            },
            path.name,
        )
        document = StoredConfig.model_validate(raw_document)
        encoded = document.model_dump_json(indent=2).encode("utf-8")
        if len(encoded) > get_settings().config_max_bytes:
            raise HTTPException(status_code=413, detail="配置内容超过大小限制")

        if path.exists():
            _create_backup(path)

        _write_atomic(path, encoded)
        return ConfigSaveResult(
            name=path.name,
            status="saved",
            modified_at=_modified_at(path),
        )


@router.delete(
    "/configs/{name}",
)
async def delete_config(name: str) -> Dict[str, str]:
    with _storage_lock:
        path = _config_path(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="配置文件不存在")
        _create_backup(path)
        path.unlink()
        return {"name": path.name, "status": "deleted"}
