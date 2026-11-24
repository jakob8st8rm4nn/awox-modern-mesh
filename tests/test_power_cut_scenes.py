from awox import power_cut_color_scene, power_cut_white_scene
import pytest


@pytest.mark.parametrize("brightness, temperature, expected", [
    (0, 0, "01 00 99 00"),     # 153 mired
    (50, 50, "01 32 30 01"),   # 303.5 rounds to 304 mired
    (100, 100, "01 64 c6 01"), # 454 mired
])
def test_white_power_cut_scene_bytes(brightness, temperature, expected):
    assert power_cut_white_scene(brightness, temperature) == bytes.fromhex(expected)


@pytest.mark.parametrize("brightness, rgb, expected", [
    (0, (255, 0, 0), "03 00 00 fe"),
    (50, (0, 255, 0), "03 32 54 fe"),
    (100, (0, 0, 255), "03 64 a9 fe"),
    (100, (127, 127, 127), "03 64 00 00"),
])
def test_color_power_cut_scene_bytes(brightness, rgb, expected):
    assert power_cut_color_scene(brightness, *rgb) == bytes.fromhex(expected)


@pytest.mark.parametrize("value", [-1, 101, True, 50.0])
def test_power_cut_scene_rejects_invalid_percentages(value):
    with pytest.raises(ValueError, match="brightness"):
        power_cut_white_scene(value, 50)
    with pytest.raises(ValueError, match="temperature"):
        power_cut_white_scene(50, value)
    with pytest.raises(ValueError, match="brightness"):
        power_cut_color_scene(value, 255, 0, 0)


@pytest.mark.parametrize("rgb", [(-1, 0, 0), (0, 256, 0), (0, 0, True)])
def test_color_power_cut_scene_rejects_invalid_rgb(rgb):
    with pytest.raises(ValueError):
        power_cut_color_scene(50, *rgb)
