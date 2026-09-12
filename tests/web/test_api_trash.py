"""Web API tests for the trash bin.

GET /api/trash lists the deleted notes, POST /api/trash/<id>/recover puts one
back, DELETE /api/trash/<id> removes it for good.
"""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from core.database import Database


@pytest.mark.web
class TestTrashApi:
    def test_an_empty_trash_returns_an_empty_list(self, client: FlaskClient) -> None:
        response = client.get("/api/trash")

        assert response.status_code == 200
        assert json.loads(response.data)["notes"] == []

    def test_a_deleted_note_appears_in_the_trash(
        self, client: FlaskClient, populated_db: Database
    ) -> None:
        note_id = populated_db.create_note("פתק שנמחק")
        client.delete(f"/api/notes/{note_id}")

        response = client.get("/api/trash")

        notes = json.loads(response.data)["notes"]
        assert [n["id"] for n in notes] == [note_id]
        assert notes[0]["content"] == "פתק שנמחק"

    def test_recover_puts_the_note_back(
        self, client: FlaskClient, populated_db: Database
    ) -> None:
        note_id = populated_db.create_note("להחזיר אותי")
        client.delete(f"/api/notes/{note_id}")

        response = client.post(f"/api/trash/{note_id}/recover")

        assert response.status_code == 200
        assert client.get(f"/api/notes/{note_id}").status_code == 200
        assert json.loads(client.get("/api/trash").data)["notes"] == []

    def test_recovering_a_note_that_is_not_in_the_trash_is_not_found(
        self, client: FlaskClient, populated_db: Database
    ) -> None:
        note_id = populated_db.create_note("פתק חי")

        response = client.post(f"/api/trash/{note_id}/recover")

        assert response.status_code == 404

    def test_purge_removes_the_note_for_good(
        self, client: FlaskClient, populated_db: Database
    ) -> None:
        note_id = populated_db.create_note("להיעלם לתמיד")
        client.delete(f"/api/notes/{note_id}")

        response = client.delete(f"/api/trash/{note_id}")

        assert response.status_code == 200
        assert populated_db.get_note_raw(note_id) is None
        assert json.loads(client.get("/api/trash").data)["notes"] == []

    def test_purge_refuses_a_note_that_is_not_in_the_trash(
        self, client: FlaskClient, populated_db: Database
    ) -> None:
        """Deleting is one step; removing for good is another."""
        note_id = populated_db.create_note("פתק חי")

        response = client.delete(f"/api/trash/{note_id}")

        assert response.status_code == 404
        assert populated_db.get_note(note_id) is not None

    def test_a_bad_id_is_rejected(self, client: FlaskClient) -> None:
        assert client.delete("/api/trash/not-a-uuid").status_code == 400
        assert client.post("/api/trash/not-a-uuid/recover").status_code == 400
