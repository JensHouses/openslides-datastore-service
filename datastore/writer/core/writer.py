from typing import List, Protocol

from datastore.shared.di import service_interface

from .write_request import WriteRequest


@service_interface
class Writer(Protocol):
    """For detailed interface descriptions, see the docs repo."""

    def write(
        self,
        write_requests: List[WriteRequest],
        log_all_modified_fields: bool = True,
    ) -> None:
        """Writes into the DB."""

    def reserve_ids(self, collection: str, amount: int) -> List[int]:
        """Gets multiple reserved ids"""

    def delete_history_information(self) -> None:
        """Delete all history information from all positions."""

    def truncate_db(self) -> None:
        """Truncate all tables. Dev mode only"""

    def write_action_worker(
        self,
        write_request: WriteRequest,
    ) -> None:
        """Writes or updates an action_worker-object"""
