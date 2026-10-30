from ytktv import low_power
from ytktv.config import Settings


def test_low_power_turns_on_once_for_weak_computers():
    assert low_power.weak_computer("x86_64", 2) and not low_power.weak_computer("x86_64", 8)
    settings = Settings(max_height=2160, lights=True)
    assert low_power.first_start(settings, weak=True)
    assert settings.low_power and settings.max_height == 720 and not settings.lights
    settings.low_power = False
    assert not low_power.first_start(settings, weak=True)  # only the first start decides
    strong = Settings()
    assert not low_power.first_start(strong, weak=False) and not strong.low_power
