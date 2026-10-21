"""Tests for Enhanced Counter Timer and Schedule event handling."""

from unittest.mock import patch

import pytest

from homeassistant.components.counter import Counter
from homeassistant.core import HomeAssistant

TIMER = "timer.task_timer"
OTHER_TIMER = "timer.another_timer"
SCHEDULE = "schedule.task_schedule"


def make_counter(
    hass: HomeAssistant,
    *,
    enhanced: bool = True,
    timer: str | None = TIMER,
    schedule: str | None = SCHEDULE,
) -> Counter:
    """Create a counter linked to the test Home Assistant event bus."""
    config = {
        "id": "rotation_test",
        "name": "Rotation Test",
        "initial": 1,
        "minimum": 1,
        "maximum": 3,
        "step": 1,
        "restore": False,
        "enhanced_mode": enhanced,
    }
    if timer:
        config["timer_entity"] = timer
    if schedule:
        config["schedule_entity"] = schedule

    counter = Counter.from_storage(config)
    counter.hass = hass
    return counter


@pytest.mark.parametrize(
    ("schedule_state", "expected"),
    [("on", 2), ("off", 1), ("unavailable", 1)],
)
async def test_timer_respects_schedule(
    hass: HomeAssistant, schedule_state: str, expected: int
) -> None:
    """Only an active Schedule allows the selected Timer to increment."""
    counter = make_counter(hass)
    hass.states.async_set(SCHEDULE, schedule_state)
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        try:
            hass.bus.async_fire("timer.finished", {"entity_id": TIMER})
            await hass.async_block_till_done()
            assert counter.state == expected
        finally:
            counter._unsubscribe_timer_finished()


async def test_unrelated_timer_is_ignored(hass: HomeAssistant) -> None:
    """A finish event from a different Timer never increments this counter."""
    counter = make_counter(hass)
    hass.states.async_set(SCHEDULE, "on")
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        try:
            hass.bus.async_fire("timer.finished", {"entity_id": OTHER_TIMER})
            await hass.async_block_till_done()
            assert counter.state == 1
        finally:
            counter._unsubscribe_timer_finished()


async def test_disabled_mode_ignores_timer(hass: HomeAssistant) -> None:
    """Turning Enhanced Mode off disables automatic increments."""
    counter = make_counter(hass, enhanced=False)
    hass.states.async_set(SCHEDULE, "on")
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        hass.bus.async_fire("timer.finished", {"entity_id": TIMER})
        await hass.async_block_till_done()
        assert counter.state == 1


async def test_timer_without_schedule_is_allowed(hass: HomeAssistant) -> None:
    """Optional Schedule: with none selected, a matching Timer is sufficient."""
    counter = make_counter(hass, schedule=None)
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        try:
            hass.bus.async_fire("timer.finished", {"entity_id": TIMER})
            await hass.async_block_till_done()
            assert counter.state == 2
        finally:
            counter._unsubscribe_timer_finished()


async def test_reconfigure_timer_replaces_listener(hass: HomeAssistant) -> None:
    """Old Timer is ignored after configuration changes; new Timer works."""
    counter = make_counter(hass)
    hass.states.async_set(SCHEDULE, "on")
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        try:
            await counter.async_update_config(
                {**counter._config, "timer_entity": OTHER_TIMER}
            )
            hass.bus.async_fire("timer.finished", {"entity_id": TIMER})
            await hass.async_block_till_done()
            assert counter.state == 1

            hass.bus.async_fire("timer.finished", {"entity_id": OTHER_TIMER})
            await hass.async_block_till_done()
            assert counter.state == 2
        finally:
            counter._unsubscribe_timer_finished()


async def test_unsubscribe_stops_automatic_increment(hass: HomeAssistant) -> None:
    """Removing the listener prevents further automatic increments."""
    counter = make_counter(hass)
    hass.states.async_set(SCHEDULE, "on")
    with patch.object(counter, "async_write_ha_state"):
        counter._subscribe_timer_finished()
        counter._unsubscribe_timer_finished()
        hass.bus.async_fire("timer.finished", {"entity_id": TIMER})
        await hass.async_block_till_done()
        assert counter.state == 1
