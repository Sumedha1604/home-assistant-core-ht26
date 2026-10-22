"""Component to count within automations."""

from collections.abc import Callable
import logging
from typing import Any, Self, override

import voluptuous as vol

from homeassistant.const import (
    CONF_ICON,
    CONF_ID,
    CONF_MAXIMUM,
    CONF_MINIMUM,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_ON,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import collection, config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, VolDictType

from .const import CounterEntityStateAttribute

_LOGGER = logging.getLogger(__name__)

ATTR_INITIAL = "initial"
ATTR_STEP = "step"
ATTR_MINIMUM = "minimum"
ATTR_MAXIMUM = "maximum"
VALUE = "value"

CONF_INITIAL = "initial"
CONF_RESTORE = "restore"
CONF_STEP = "step"

CONF_ENHANCED_MODE = "enhanced_mode"
CONF_TIMER_ENTITY = "timer_entity"
CONF_SCHEDULE_ENTITY = "schedule_entity"

EVENT_TIMER_FINISHED = "timer.finished"

DEFAULT_INITIAL = 0
DEFAULT_STEP = 1
DOMAIN = "counter"

ENTITY_ID_FORMAT = DOMAIN + ".{}"

SERVICE_DECREMENT = "decrement"
SERVICE_INCREMENT = "increment"
SERVICE_RESET = "reset"
SERVICE_SET_VALUE = "set_value"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

STORAGE_FIELDS: VolDictType = {
    vol.Optional(CONF_ICON): cv.icon,
    vol.Optional(CONF_INITIAL, default=DEFAULT_INITIAL): vol.Coerce(int),
    vol.Required(CONF_NAME): vol.All(cv.string, vol.Length(min=1)),
    vol.Optional(CONF_MAXIMUM, default=None): vol.Any(None, vol.Coerce(int)),
    vol.Optional(CONF_MINIMUM, default=None): vol.Any(None, vol.Coerce(int)),
    vol.Optional(CONF_RESTORE, default=True): cv.boolean,
    vol.Optional(CONF_STEP, default=DEFAULT_STEP): cv.positive_int,
    vol.Optional(CONF_ENHANCED_MODE): cv.boolean,
    vol.Optional(CONF_TIMER_ENTITY): vol.Any(None, cv.entity_id),
    vol.Optional(CONF_SCHEDULE_ENTITY): vol.Any(None, cv.entity_id),
}


def _none_to_empty_dict[_T](value: _T | None) -> _T | dict[str, Any]:
    if value is None:
        return {}
    return value


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: cv.schema_with_slug_keys(
            vol.All(
                _none_to_empty_dict,
                {
                    vol.Optional(CONF_ICON): cv.icon,
                    vol.Optional(CONF_INITIAL, default=DEFAULT_INITIAL): vol.Coerce(
                        int
                    ),
                    vol.Optional(CONF_NAME): cv.string,
                    vol.Optional(CONF_MAXIMUM, default=None): vol.Any(
                        None, vol.Coerce(int)
                    ),
                    vol.Optional(CONF_MINIMUM, default=None): vol.Any(
                        None, vol.Coerce(int)
                    ),
                    vol.Optional(CONF_RESTORE, default=True): cv.boolean,
                    vol.Optional(CONF_STEP, default=DEFAULT_STEP): cv.positive_int,
                    vol.Optional(CONF_ENHANCED_MODE): cv.boolean,
                    vol.Optional(CONF_TIMER_ENTITY): vol.Any(None, cv.entity_id),
                    vol.Optional(CONF_SCHEDULE_ENTITY): vol.Any(None, cv.entity_id),
                },
            )
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the counters."""
    component = EntityComponent[Counter](_LOGGER, DOMAIN, hass)
    id_manager = collection.IDManager()

    yaml_collection = collection.YamlCollection(
        logging.getLogger(f"{__name__}.yaml_collection"), id_manager
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, yaml_collection, Counter
    )

    storage_collection = CounterStorageCollection(
        Store(hass, STORAGE_VERSION, STORAGE_KEY),
        id_manager,
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, storage_collection, Counter
    )

    await yaml_collection.async_load(
        [{CONF_ID: id_, **(conf or {})} for id_, conf in config.get(DOMAIN, {}).items()]
    )
    await storage_collection.async_load()

    collection.DictStorageCollectionWebsocket(
        storage_collection, DOMAIN, DOMAIN, STORAGE_FIELDS, STORAGE_FIELDS
    ).async_setup(hass)

    component.async_register_entity_service(SERVICE_INCREMENT, None, "async_increment")
    component.async_register_entity_service(SERVICE_DECREMENT, None, "async_decrement")
    component.async_register_entity_service(SERVICE_RESET, None, "async_reset")
    component.async_register_entity_service(
        SERVICE_SET_VALUE,
        {vol.Required(VALUE): vol.Coerce(int)},
        "async_set_value",
    )

    @callback
    def _register_task_rotation_panel(_event: Event | None = None) -> None:
        """Expose the frontend Task Rotation demo after frontend setup."""
        from homeassistant.components import frontend  # noqa: PLC0415

        if "frontend" not in hass.config.components:
            return
        if "task-rotation" in hass.data.get(frontend.DATA_PANELS, {}):
            return
        frontend.async_register_built_in_panel(
            hass,
            component_name="task-rotation",
            sidebar_title="Task Rotation",
            sidebar_icon="mdi:clipboard-check",
            frontend_url_path="task-rotation",
        )

    if hass.is_running:
        _register_task_rotation_panel()
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _register_task_rotation_panel
        )

    return True


class CounterStorageCollection(collection.DictStorageCollection):
    """Input storage based collection."""

    CREATE_UPDATE_SCHEMA = vol.Schema(STORAGE_FIELDS)

    @override
    async def _process_create_data(self, data: dict) -> dict:
        """Validate the config is valid."""
        return self.CREATE_UPDATE_SCHEMA(data)  # type: ignore[no-any-return]

    @callback
    @override
    def _get_suggested_id(self, info: dict) -> str:
        """Suggest an ID based on the config."""
        return info[CONF_NAME]  # type: ignore[no-any-return]

    @override
    async def _update_data(self, item: dict, update_data: dict) -> dict:
        """Return a new updated data object."""
        update_data = self.CREATE_UPDATE_SCHEMA(update_data)
        return {CONF_ID: item[CONF_ID]} | update_data


class Counter(collection.CollectionEntity, RestoreEntity):
    """Representation of a counter."""

    _attr_should_poll: bool = False
    editable: bool

    def __init__(self, config: ConfigType) -> None:
        """Initialize a counter."""
        self._config: ConfigType = config
        self._state: int | None = config[CONF_INITIAL]
        self._automatic_turns = 0
        self._unsub_timer_finished: Callable[[], None] | None = None

    @classmethod
    @override
    def from_storage(cls, config: ConfigType) -> Self:
        """Create counter instance from storage."""
        counter = cls(config)
        counter.editable = True
        return counter

    @classmethod
    @override
    def from_yaml(cls, config: ConfigType) -> Self:
        """Create counter instance from yaml config."""
        counter = cls(config)
        counter.editable = False
        counter.entity_id = ENTITY_ID_FORMAT.format(config[CONF_ID])
        return counter

    @property
    @override
    def name(self) -> str | None:
        """Return name of the counter."""
        return self._config.get(CONF_NAME)

    @property
    @override
    def icon(self) -> str | None:
        """Return the icon to be used for this entity."""
        return self._config.get(CONF_ICON)

    @property
    @override
    def state(self) -> int | None:
        """Return the current value of the counter."""
        return self._state

    @property
    @override
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        ret: dict[str, Any] = {
            CounterEntityStateAttribute.EDITABLE: self.editable,
            CounterEntityStateAttribute.INITIAL: self._config[CONF_INITIAL],
            CounterEntityStateAttribute.STEP: self._config[CONF_STEP],
        }

        if self._config[CONF_MINIMUM] is not None:
            ret[CounterEntityStateAttribute.MINIMUM] = self._config[CONF_MINIMUM]

        if self._config[CONF_MAXIMUM] is not None:
            ret[CounterEntityStateAttribute.MAXIMUM] = self._config[CONF_MAXIMUM]

        if self._config.get(CONF_ENHANCED_MODE, False):
            ret["automatic_turns"] = self._automatic_turns
        return ret

    @property
    @override
    def unique_id(self) -> str | None:
        """Return unique id of the entity."""
        return self._config[CONF_ID]  # type: ignore[no-any-return]

    def compute_next_state(self, state: int | None) -> int | None:
        """Keep the state within the range of min/max values."""
        if self._config[CONF_MINIMUM] is not None:
            state = max(self._config[CONF_MINIMUM], state)

        if self._config[CONF_MAXIMUM] is not None:
            state = min(self._config[CONF_MAXIMUM], state)

        return state

    def compute_next_step_state(self, state: int) -> int | None:
        """Wrap counter steps when enhanced mode is enabled."""
        minimum = self._config[CONF_MINIMUM]
        maximum = self._config[CONF_MAXIMUM]

        if (
            not self._config.get(CONF_ENHANCED_MODE, False)
            or minimum is None
            or maximum is None
        ):
            return self.compute_next_state(state)

        if state > maximum:
            return int(minimum)

        if state < minimum:
            return int(maximum)

        return state

    @callback
    def _unsubscribe_timer_finished(self) -> None:
        """Remove a previous Timer listener, if present."""
        if self._unsub_timer_finished is not None:
            self._unsub_timer_finished()
            self._unsub_timer_finished = None

    @callback
    def _subscribe_timer_finished(self) -> None:
        """Listen only when Enhanced Mode and a Timer are configured."""
        self._unsubscribe_timer_finished()
        if not self._config.get(CONF_ENHANCED_MODE, False):
            return
        if not self._config.get(CONF_TIMER_ENTITY):
            return

        self._unsub_timer_finished = self.hass.bus.async_listen(
            EVENT_TIMER_FINISHED, self._handle_timer_finished
        )

    @callback
    def _handle_timer_finished(self, event: Event[dict[str, Any]]) -> None:
        """Increment only for the selected Timer and an allowed Schedule."""
        if not self._config.get(CONF_ENHANCED_MODE, False):
            return
        if event.data.get("entity_id") != self._config.get(CONF_TIMER_ENTITY):
            return

        schedule_entity = self._config.get(CONF_SCHEDULE_ENTITY)
        if schedule_entity and not self.hass.states.is_state(schedule_entity, STATE_ON):
            return

        self._automatic_turns += 1
        self.async_increment()

    @override
    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to Home Assistant."""
        await super().async_added_to_hass()

        # __init__ will set self._state to self._initial, only override
        # if needed.
        if (
            self._config[CONF_RESTORE]
            and (state := await self.async_get_last_state()) is not None
        ):
            self._state = self.compute_next_state(int(state.state))
            saved_turns = state.attributes.get("automatic_turns")
            if type(saved_turns) is int and saved_turns >= 0:
                self._automatic_turns = saved_turns

        self.async_on_remove(self._unsubscribe_timer_finished)
        self._subscribe_timer_finished()

    @callback
    def async_decrement(self) -> None:
        """Decrement the counter, wrapping in enhanced mode."""
        self._state = self.compute_next_step_state(
            self._state - self._config[CONF_STEP]
        )
        self.async_write_ha_state()

    @callback
    def async_increment(self) -> None:
        """Increment the counter, wrapping in enhanced mode."""
        self._state = self.compute_next_step_state(
            self._state + self._config[CONF_STEP]
        )
        self.async_write_ha_state()

    @callback
    def async_reset(self) -> None:
        """Reset a counter."""
        self._state = self.compute_next_state(self._config[CONF_INITIAL])
        self.async_write_ha_state()

    @callback
    def async_set_value(self, value: int) -> None:
        """Set counter to value."""
        if (maximum := self._config.get(CONF_MAXIMUM)) is not None and value > maximum:
            raise ValueError(
                f"Value {value} for {self.entity_id}"
                f" exceeding the maximum value of {maximum}"
            )

        if (minimum := self._config.get(CONF_MINIMUM)) is not None and value < minimum:
            raise ValueError(
                f"Value {value} for {self.entity_id}"
                f" exceeding the minimum value of {minimum}"
            )

        if (step := self._config.get(CONF_STEP)) is not None and value % step != 0:
            raise ValueError(
                f"Value {value} for {self.entity_id}"
                f" is not a multiple of the step size {step}"
            )

        self._state = value
        self.async_write_ha_state()

    @override
    async def async_update_config(self, config: ConfigType) -> None:
        """Change the counter's settings WS CRUD."""
        self._config = config
        self._state = self.compute_next_state(self._state)
        self.async_write_ha_state()
        self._subscribe_timer_finished()
