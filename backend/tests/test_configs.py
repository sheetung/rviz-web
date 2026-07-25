import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import configs


def _payload(fixed_frame: str = "map") -> configs.ConfigPayload:
    return configs.ConfigPayload(
        name="test.rvizweb",
        config=configs.FrontendConfig(fixedFrame=fixed_frame, displays=[]),
    )


@pytest.fixture
def config_storage(tmp_path, monkeypatch):
    config_dir = tmp_path / "rvizweb_configs"
    backup_dir = config_dir / "backups"
    settings = SimpleNamespace(
        config_max_bytes=1_048_576,
        config_name_max_length=96,
        config_backup_max_files=50,
        config_backup_max_bytes=52_428_800,
    )
    monkeypatch.setattr(configs, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(configs, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(configs, "get_settings", lambda: settings)
    return config_dir, backup_dir, settings


@pytest.mark.asyncio
async def test_save_uses_atomic_replace_and_leaves_no_temp_file(
    config_storage, monkeypatch
):
    config_dir, _, _ = config_storage
    replacements = []
    real_replace = configs.os.replace

    def tracked_replace(source, destination):
        replacements.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(configs.os, "replace", tracked_replace)

    result = await configs.save_config("flight", _payload())

    saved = configs._read_validated(config_dir / "flight.rvizweb")
    assert result.name == "flight.rvizweb"
    assert result.status == "saved"
    assert result.modified_at.tzinfo is not None
    assert saved.config.fixedFrame == "map"
    assert len(replacements) == 1
    assert replacements[0][1] == config_dir / "flight.rvizweb"
    assert not list(config_dir.glob(".flight.rvizweb.*"))


@pytest.mark.asyncio
async def test_get_config_returns_file_modification_time(config_storage):
    await configs.save_config("flight", _payload())

    result = await configs.get_config("flight")

    assert result.name == "flight.rvizweb"
    assert result.modified_at.tzinfo is not None
    assert result.modified_at == configs._modified_at(
        config_storage[0] / "flight.rvizweb"
    )


@pytest.mark.asyncio
async def test_overwrite_and_delete_create_backups(config_storage):
    config_dir, backup_dir, _ = config_storage

    await configs.save_config("flight", _payload("map"))
    await configs.save_config("flight", _payload("odom"))

    overwrite_backups = list(backup_dir.glob("flight.*.rvizweb.bak"))
    assert len(overwrite_backups) == 1
    assert configs._read_validated(overwrite_backups[0]).config.fixedFrame == "map"

    result = await configs.delete_config("flight")

    assert result == {"name": "flight.rvizweb", "status": "deleted"}
    assert not (config_dir / "flight.rvizweb").exists()
    assert len(list(backup_dir.glob("flight.*.rvizweb.bak"))) == 2


@pytest.mark.parametrize("name", ["../escape", "/absolute", "bad name", "link/child"])
def test_invalid_config_names_are_rejected(config_storage, name):
    with pytest.raises(HTTPException) as error:
        configs._config_path(name)
    assert error.value.status_code == 400


def test_symlink_config_is_rejected(config_storage):
    config_dir, _, _ = config_storage
    config_dir.mkdir(parents=True)
    target = config_dir / "target.rvizweb"
    target.write_text("{}", encoding="utf-8")
    (config_dir / "link.rvizweb").symlink_to(target)

    with pytest.raises(HTTPException) as error:
        configs._config_path("link")
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_theme_and_collapsed_panels_round_trip(config_storage):
    config_dir, _, _ = config_storage
    payload = configs.ConfigPayload(
        name="light.rvizweb",
        config=configs.FrontendConfig(
            fixedFrame="map",
            displays=[],
            layout=configs.LayoutConfig(
                sceneWidth=64,
                collapsedPanels={"settings": False, "controller": True},
            ),
            appearance=configs.AppearanceConfig(theme="light"),
        ),
    )

    await configs.save_config("light", payload)
    saved = configs._read_validated(config_dir / "light.rvizweb")

    assert saved.config.appearance.theme == "light"
    assert saved.config.layout.sceneWidth == 64
    assert saved.config.layout.collapsedPanels == {"settings": False}


@pytest.mark.asyncio
async def test_rtsp_video_settings_round_trip(config_storage):
    config_dir, _, _ = config_storage
    payload = configs.ConfigPayload(
        name="camera.rvizweb",
        config=configs.FrontendConfig(
            fixedFrame="map",
            displays=[],
            video=configs.VideoConfig(
                sourceUrl="rtsp://192.168.1.66:8554/1",
                visible=True,
                layout=configs.VideoLayoutConfig(
                    x=120,
                    y=80,
                    width=480,
                    height=300,
                ),
            ),
        ),
    )

    await configs.save_config("camera", payload)
    saved = configs._read_validated(config_dir / "camera.rvizweb")

    assert saved.config.video.sourceUrl == "rtsp://192.168.1.66:8554/1"
    assert saved.config.video.visible is True
    assert saved.config.video.layout.x == 120
    assert saved.config.video.layout.width == 480


def test_rtsp_credentials_cannot_be_persisted(config_storage):
    with pytest.raises(ValueError):
        configs.VideoConfig(sourceUrl="rtsp://camera:secret@192.168.1.66/live")


def test_unknown_top_level_config_fields_are_rejected(config_storage):
    with pytest.raises(ValueError):
        configs.FrontendConfig.model_validate(
            {
                "fixedFrame": "map",
                "unexpected": True,
            }
        )


@pytest.mark.asyncio
async def test_get_config_repairs_legacy_fields_and_preserves_unknown_data(
    config_storage,
):
    config_dir, backup_dir, _ = config_storage
    config_dir.mkdir(parents=True)
    path = config_dir / "legacy.rvizweb"
    path.write_text(
        json.dumps(
            {
                "name": "old-name.rvizweb",
                "version": 1,
                "config": {
                    "fixed_frame": "odom",
                    "position": {
                        "odom_topic": "/robot/odom",
                        "show_robot_model": True,
                        "show_trajectory": False,
                        "trajectory_length": 42,
                    },
                    "layout": {
                        "panel_heights": {"gps": 240, "controller": 520},
                        "collapsed_panels": {
                            "settings": False,
                            "controller": True,
                        },
                    },
                    "displays": [
                        {
                            "name": "/robot/odom",
                            "message_type": "nav_msgs/msg/Odometry",
                        }
                    ],
                    "legacyWidget": {"enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )

    result = await configs.get_config("legacy")

    assert result.repaired is True
    assert result.name == "legacy.rvizweb"
    assert result.config.fixedFrame == "odom"
    assert result.config.position.odomTopic == "/robot/odom"
    assert result.config.position.showRobotModel is True
    assert result.config.position.showTrajectory is False
    assert result.config.position.trajectoryLength == 42
    assert result.config.displays[0].messageType == "nav_msgs/msg/Odometry"
    assert result.config.layout.panelHeights == {"gps": 240}
    assert result.config.layout.collapsedPanels == {"settings": False}
    assert result.config.extensions["legacy"]["legacyWidget"] == {"enabled": True}
    assert len(list(backup_dir.glob("legacy.*.rvizweb.bak"))) == 1

    repaired_document = json.loads(path.read_text(encoding="utf-8"))
    assert repaired_document["config"]["fixedFrame"] == "odom"
    assert "fixed_frame" not in repaired_document["config"]
    assert "controller" not in repaired_document["config"]["layout"]["panelHeights"]

    second_result = await configs.get_config("legacy")
    assert second_result.repaired is False
    assert len(list(backup_dir.glob("legacy.*.rvizweb.bak"))) == 1


@pytest.mark.asyncio
async def test_robot_model_visibility_round_trip(config_storage):
    config_dir, _, _ = config_storage
    payload = configs.ConfigPayload(
        name="robot-model.rvizweb",
        config=configs.FrontendConfig(
            fixedFrame="map",
            displays=[],
            position=configs.PositionConfig(
                odomTopic="/robot/odom",
                showRobotModel=True,
            ),
        ),
    )

    await configs.save_config("robot-model", payload)
    saved = configs._read_validated(config_dir / "robot-model.rvizweb")

    assert saved.config.position.odomTopic == "/robot/odom"
    assert saved.config.position.showRobotModel is True
    assert configs.PositionConfig().showRobotModel is False
