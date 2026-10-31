"""#288: card id 0 passes the digits check, so only `CardId` keeps it away from the store."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.folders import routes as folder_routes
from tests.regressions.test_journey_folder_save import FORM, card_id, client, create, flag

# Reuse the folder journey's private policy and store file unchanged.
__all__ = ["client", "flag"]

WRITES = [("priority", "priority=high&reason=Outreach+week"), ("status", "status=contacted")]


@pytest.mark.parametrize(("field", "body"), WRITES)
def test_card_id_zero_is_404_with_no_store_lookup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, field: str, body: str
) -> None:
    path = create(client)
    real_card = card_id(client, path)
    spy = MagicMock()
    monkeypatch.setattr(folder_routes, "FolderStore", spy)

    response = client.post(f"{path}/cards/0/{field}", content=body, headers=FORM)

    assert response.status_code == 404
    spy.assert_not_called()

    # The same request with a real card reaches the store, so the spy above can see a call.
    assert client.post(f"{path}/cards/{real_card}/{field}", content=body, headers=FORM)
    spy.assert_called()
