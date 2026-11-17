import pytest

from xnbridge.errors import ResourcePressure
from xnbridge.server import _check_resources


@pytest.mark.parametrize("rss,available,load", [(1000, 4000, 0.5), (50, 100, 0.5), (50, 4000, 3.0)])
def test_resource_pressure_stops_heavy_work(bridge, monkeypatch, rss, available, load):
    monkeypatch.setattr("xnbridge.server.self_rss_mb", lambda: rss)
    monkeypatch.setattr("xnbridge.server.mem_available_mb", lambda: available)
    monkeypatch.setattr("xnbridge.server.cpu_load_per_core", lambda: load)
    with pytest.raises(ResourcePressure) as exc:
        _check_resources(bridge)
    assert exc.value.code == "RESOURCE_PRESSURE"


def test_unknown_resource_metrics_do_not_disable_normal_operation(bridge, monkeypatch):
    for name in ("self_rss_mb", "mem_available_mb", "cpu_load_per_core"):
        monkeypatch.setattr("xnbridge.server." + name, lambda: None)
    _check_resources(bridge)
