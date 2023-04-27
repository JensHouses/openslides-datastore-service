from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from datastore.shared.postgresql_backend.sql_event_types import EVENT_TYPE
from datastore.shared.typing import JSON, Fqid

from .events import BaseEvent, DeleteFieldsEvent, ListUpdateEvent, UpdateEvent
from .exceptions import MigrationSetupException
from .migration_keyframes import MigrationKeyframeAccessor


@dataclass
class PositionData:
    position: int
    timestamp: datetime
    user_id: int
    information: JSON


class BaseMigration:
    """
    The base class to represent a migration. The `target_migration_index` must be set
    by each migration.

    This class is instantiated once! `migrate` may be called many times, once for
    each position. To realize a per-position storage use the `position_init` method:
    There you can setup class members. This method is called once for each position.

    During the migration one has access to
    - self.old_accessor
    - self.new_accessor
    - self.position_data
    which are set for each position just before `position_init`.
    """

    target_migration_index = -1

    old_accessor: MigrationKeyframeAccessor
    new_accessor: MigrationKeyframeAccessor
    position_data: PositionData
    # The status all models would have after the original events of this position were applied
    model_status: Dict[Fqid, EVENT_TYPE]

    def __init__(self):
        self.name = self.__class__.__name__
        if self.target_migration_index == -1:
            raise MigrationSetupException(
                f"You need to specify target_migration_index of {self.name}"
            )

    def migrate(
        self,
        events: List[BaseEvent],
        old_accessor: MigrationKeyframeAccessor,
        new_accessor: MigrationKeyframeAccessor,
        position_data: PositionData,
    ) -> List[BaseEvent]:
        """
        Receives a list of events from one position to migrate. old_accessor and
        new_accessor provide access to the data of the datastore before this position,
        once unmigrated, once migrated. position_data contains auxillary data from the
        position to migrate.

        It should return a list of events which to fully replace all (provided)
        events of the position. If None is returned, this migration does not affect
        the position and the events of this position can be left as-is. It is ok to
        modify the provided events.
        """
        self.old_accessor = old_accessor
        self.new_accessor = new_accessor
        self.position_data = position_data
        self._set_model_status(events)
        self.position_init()

        new_events: List[BaseEvent] = []
        for event in self.order_events(events):
            old_event = event.clone()
            translated_events = self.migrate_event(event)
            if translated_events is None:
                translated_events = [old_event]  # noop

            # filter out empty events
            filtered_events = self._filter_noop_events(translated_events)

            old_accessor.apply_event(old_event)
            for translated_event in filtered_events:
                new_accessor.apply_event(translated_event)
                new_events.append(translated_event)

        # After migrating every event of this position, some
        # additional events to append to the position can be created
        additional_events = self.get_additional_events()
        if additional_events is None:
            additional_events = []  # noop
        for additional_event in additional_events:
            new_accessor.apply_event(additional_event)
        new_events.extend(additional_events)

        return new_events

    def _set_model_status(self, events: List[BaseEvent]) -> None:
        """
        Sets the model status for each model in this position.
        """
        self.model_status = {}
        for event in events:
            if (
                event.type in (EVENT_TYPE.CREATE, EVENT_TYPE.DELETE)
                and self.model_status.get(event.fqid) != EVENT_TYPE.DELETE
            ):
                self.model_status[event.fqid] = event.type

    def order_events(self, events: List[BaseEvent]) -> Iterable[BaseEvent]:
        """
        Yield create events first, everything else afterwards. This guarantees that all referenced
        models are created before any other are updated.
        This is the runtime-optimal approach by using a generator - the list is only iterared ~1.5
        times.
        """
        events_queue = []
        for event in events:
            if event.type == "create":
                yield event
            else:
                events_queue.append(event)
        yield from events_queue

    def _filter_noop_events(self, events: Iterable[BaseEvent]) -> Iterable[BaseEvent]:
        for event in events:
            if isinstance(event, UpdateEvent):
                if not event.data:
                    continue
            elif isinstance(event, ListUpdateEvent):
                if not any(
                    value
                    for field in (event.add, event.remove)
                    for value in field.values()
                ):
                    continue
            elif isinstance(event, DeleteFieldsEvent):
                if not event.data:
                    continue
            yield event

    def position_init(self) -> None:
        """
        This hook can be used to setup initial data for each position.
        """

    def migrate_event(
        self,
        event: BaseEvent,
    ) -> Optional[List[BaseEvent]]:
        """
        This needs to be implemented by each migration. This is the core logic of the
        migration to convert the given event. The provided event can be modified.
        """
        raise NotImplementedError()

    def get_additional_events(self) -> Optional[List[BaseEvent]]:
        """
        Here, additional events can be returned that are appended to the position after
        the migrated events. Return None if there are no such additional events. This is
        also the default behavior.
        """
        return None

    def will_exist(self, fqid: Fqid) -> bool:
        """
        Returns True iff the model would exist after this position without the migration.
        """
        return (
            self.new_accessor.model_not_deleted(fqid)
            and self.model_status.get(fqid) != EVENT_TYPE.DELETE
        ) or self.model_status.get(fqid) == EVENT_TYPE.CREATE
