"""Tests for the optional Enhanced Counter Mode."""

from unittest.mock import patch

import pytest

from homeassistant.components.counter import Counter, CounterStorageCollection


def make_counter(
    *,
    initial: int = 1,
    minimum: int | None = 1,
    maximum: int | None = 3,
    step: int = 1,
    enhanced_mode: bool | None = None,
) -> Counter:
    """Create a Counter without setting up all of Home Assistant."""
    config = {
        "id": "test_counter",
        "name": "Test Counter",
        "initial": initial,
        "minimum": minimum,
        "maximum": maximum,
        "step": step,
        "restore": False,
    }

    if enhanced_mode is not None:
        config["enhanced_mode"] = enhanced_mode

    return Counter.from_storage(config)


@pytest.mark.parametrize(
    ("enhanced_mode", "expected"),
    [(None, 3), (False, 3), (True, 1)],
)
def test_increment_at_maximum(enhanced_mode: bool | None, expected: int) -> None:
    """Only Enhanced Mode wraps from maximum to minimum."""
    counter = make_counter(
        initial=3,
        enhanced_mode=enhanced_mode,
    )

    with patch.object(counter, "async_write_ha_state") as write_state:
        counter.async_increment()

    assert counter.state == expected
    write_state.assert_called_once_with()


@pytest.mark.parametrize(
    ("enhanced_mode", "expected"),
    [(None, 1), (False, 1), (True, 3)],
)
def test_decrement_at_minimum(enhanced_mode: bool | None, expected: int) -> None:
    """Only Enhanced Mode wraps from minimum to maximum."""
    counter = make_counter(
        initial=1,
        enhanced_mode=enhanced_mode,
    )

    with patch.object(counter, "async_write_ha_state") as write_state:
        counter.async_decrement()

    assert counter.state == expected
    write_state.assert_called_once_with()


def test_enhanced_mode_increments_through_full_cycle() -> None:
    """A three-person rotation cycles 1, 2, 3, 1, 2."""
    counter = make_counter(enhanced_mode=True)

    with patch.object(counter, "async_write_ha_state") as write_state:
        actual = []

        for _ in range(4):
            counter.async_increment()
            actual.append(counter.state)

    assert actual == [2, 3, 1, 2]
    assert write_state.call_count == 4


def test_enhanced_mode_decrements_through_full_cycle() -> None:
    """Decrementing rotates backwards and wraps to maximum."""
    counter = make_counter(enhanced_mode=True)

    with patch.object(counter, "async_write_ha_state"):
        actual = []

        for _ in range(4):
            counter.async_decrement()
            actual.append(counter.state)

    assert actual == [3, 2, 1, 3]


@pytest.mark.parametrize(
    ("initial", "increment", "expected"),
    [(2, True, 1), (2, False, 3)],
)
def test_larger_step_wraps_to_opposite_boundary(
    initial: int,
    increment: bool,
    expected: int,
) -> None:
    """Crossing a limit wraps to the opposite boundary."""
    counter = make_counter(
        initial=initial,
        step=2,
        enhanced_mode=True,
    )

    with patch.object(counter, "async_write_ha_state"):
        if increment:
            counter.async_increment()
        else:
            counter.async_decrement()

    assert counter.state == expected


@pytest.mark.parametrize(
    ("minimum", "maximum", "initial", "increment", "expected"),
    [
        (None, None, 3, True, 4),
        (None, None, 1, False, 0),
        (1, None, 1, False, 1),
        (None, 3, 3, True, 3),
    ],
)
def test_missing_boundary_preserves_normal_behavior(
    minimum: int | None,
    maximum: int | None,
    initial: int,
    increment: bool,
    expected: int,
) -> None:
    """A missing limit must not trigger cyclic wrapping."""
    counter = make_counter(
        initial=initial,
        minimum=minimum,
        maximum=maximum,
        enhanced_mode=True,
    )

    with patch.object(counter, "async_write_ha_state"):
        if increment:
            counter.async_increment()
        else:
            counter.async_decrement()

    assert counter.state == expected


def test_reset_does_not_wrap() -> None:
    """Reset restores the configured initial value."""
    counter = make_counter(
        initial=2,
        enhanced_mode=True,
    )

    with patch.object(counter, "async_write_ha_state"):
        counter.async_increment()
        assert counter.state == 3

        counter.async_reset()

    assert counter.state == 2


async def test_updating_mode_keeps_state_and_enables_wrapping() -> None:
    """Switching modes preserves the value and updates behavior."""
    counter = make_counter(
        initial=3,
        enhanced_mode=False,
    )

    new_config = dict(counter._config) | {"enhanced_mode": True}

    with patch.object(counter, "async_write_ha_state"):
        await counter.async_update_config(new_config)

        assert counter.state == 3

        counter.async_increment()

    assert counter.state == 1


def test_existing_storage_configuration_omits_enhanced_mode() -> None:
    """Legacy configurations do not acquire a new field."""
    saved = CounterStorageCollection.CREATE_UPDATE_SCHEMA({"name": "Existing Counter"})

    assert "enhanced_mode" not in saved
    assert saved["step"] == 1


def test_storage_accepts_new_optional_fields() -> None:
    """The new UI settings are accepted by Core's storage schema."""
    saved = CounterStorageCollection.CREATE_UPDATE_SCHEMA(
        {
            "name": "Household Rotation",
            "initial": 1,
            "minimum": 1,
            "maximum": 3,
            "enhanced_mode": True,
            "timer_entity": "timer.test_timer",
            "schedule_entity": "schedule.test_schedule",
        }
    )

    assert saved["enhanced_mode"] is True
    assert saved["timer_entity"] == "timer.test_timer"
    assert saved["schedule_entity"] == "schedule.test_schedule"
