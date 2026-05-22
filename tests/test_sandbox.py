import pytest

from src.agent.sandbox import ResourceLimits
from src.common.config import Config


def _config_with_limits(prefix="sandbox", **limits):
    config = Config()
    for key, value in limits.items():
        config.set(f"{prefix}.{key}", value)
    return config


def test_resource_limits_from_config_uses_defaults():
    limits = ResourceLimits.from_config(Config())

    assert limits.cpu_time == 60
    assert limits.memory_mb == 512
    assert limits.disk_mb == 100


def test_resource_limits_from_config_accepts_integer_strings():
    config = _config_with_limits(
        cpu_time="30",
        memory_mb="256",
        disk_mb="64",
    )

    limits = ResourceLimits.from_config(config)

    assert limits.cpu_time == 30
    assert limits.memory_mb == 256
    assert limits.disk_mb == 64


def test_resource_limits_from_config_supports_custom_prefix():
    config = _config_with_limits(
        prefix="sandbox.resource_limits",
        cpu_time=15,
        memory_mb=128,
        disk_mb=32,
    )

    limits = ResourceLimits.from_config(
        config, prefix="sandbox.resource_limits"
    )

    assert limits.cpu_time == 15
    assert limits.memory_mb == 128
    assert limits.disk_mb == 32


@pytest.mark.parametrize("field", ["cpu_time", "memory_mb", "disk_mb"])
@pytest.mark.parametrize("value", [-1, 0, "0", "-5", "", "many", True])
def test_resource_limits_from_config_rejects_invalid_values(field, value):
    config = _config_with_limits(
        cpu_time=60,
        memory_mb=512,
        disk_mb=100,
    )
    config.set(f"sandbox.{field}", value)

    with pytest.raises(ValueError, match=field):
        ResourceLimits.from_config(config)
