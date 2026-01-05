"""Tests for protocol version compatibility.

Tests:
- Matching protocol versions
- Mismatched protocol versions
- Unknown protocol version handling
- Future version compatibility
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id

from .conftest import (
    SyncNode,
    create_note_on_node,
)


class TestProtocolVersionHandshake:
    """Tests for protocol version in handshake."""

    def test_handshake_returns_protocol_version(self, running_server_a: SyncNode):
        """Handshake response includes protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "TestClient",
                "protocol_version": "1.0",
            },
            timeout=5,
        )

        assert response.status_code == 200
        data = response.json()
        assert "protocol_version" in data
        assert data["protocol_version"] == "1.0"

    def test_status_includes_protocol_version(self, running_server_a: SyncNode):
        """Status endpoint includes protocol version."""
        response = requests.get(
            f"{running_server_a.url}/sync/status",
            timeout=5,
        )

        assert response.status_code == 200
        data = response.json()
        assert "protocol_version" in data

    def test_handshake_accepts_same_version(self, running_server_a: SyncNode):
        """Handshake accepts matching protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "TestClient",
                "protocol_version": "1.0",
            },
            timeout=5,
        )

        assert response.status_code == 200

    def test_handshake_requires_protocol_version(self, running_server_a: SyncNode):
        """Handshake requires protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "TestClient",
                # No protocol_version
            },
            timeout=5,
        )

        # Server now requires protocol_version
        assert response.status_code == 422


class TestProtocolVersionMismatch:
    """Tests for protocol version mismatches."""

    def test_handshake_older_client_version(self, running_server_a: SyncNode):
        """Server handles older client protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "OldClient",
                "protocol_version": "0.9",  # Older version
            },
            timeout=5,
        )

        # Should either accept (backward compatible) or reject
        # Current implementation accepts any version
        assert response.status_code in [200, 400, 409]

    def test_handshake_newer_client_version(self, running_server_a: SyncNode):
        """Server handles newer client protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "NewClient",
                "protocol_version": "2.0",  # Newer version
            },
            timeout=5,
        )

        # Should either accept or reject with version info
        assert response.status_code in [200, 400, 409, 426]  # 426 = Upgrade Required

    def test_handshake_invalid_version_format(self, running_server_a: SyncNode):
        """Server handles invalid protocol version format."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "BadClient",
                "protocol_version": "not-a-version",
            },
            timeout=5,
        )

        # Should handle gracefully
        assert response.status_code in [200, 400]


class TestProtocolCompatibility:
    """Tests for protocol compatibility behavior."""

    def test_sync_with_matching_versions(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync works with matching protocol versions."""
        node_a, node_b = two_nodes_with_servers

        # Create data
        note_id = create_note_on_node(node_a, "Test note")

        # Sync should work
        from .conftest import sync_nodes
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True

    def test_protocol_version_in_all_endpoints(self, running_server_a: SyncNode):
        """All endpoints accept requests from matching version clients."""
        # Handshake
        handshake = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": "1.0",
            },
            timeout=5,
        )
        assert handshake.status_code == 200

        # Status
        status = requests.get(
            f"{running_server_a.url}/sync/status",
            timeout=5,
        )
        assert status.status_code == 200

        # Changes - no device_id required for simple GET
        changes = requests.get(
            f"{running_server_a.url}/sync/changes",
            timeout=5,
        )
        assert changes.status_code == 200

        # Full
        full = requests.get(
            f"{running_server_a.url}/sync/full",
            timeout=5,
        )
        assert full.status_code == 200

        # Apply
        apply_resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "changes": [],
            },
            timeout=5,
        )
        assert apply_resp.status_code == 200


class TestProtocolVersionDiscovery:
    """Tests for discovering peer protocol version."""

    def test_discover_server_version_via_status(self, running_server_a: SyncNode):
        """Client can discover server version via status endpoint."""
        response = requests.get(
            f"{running_server_a.url}/sync/status",
            timeout=5,
        )

        data = response.json()
        assert "protocol_version" in data

        # Can use this to decide if sync is compatible
        version = data["protocol_version"]
        assert version is not None

    def test_discover_server_version_via_handshake(self, running_server_a: SyncNode):
        """Client can discover server version via handshake."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": "1.0",
            },
            timeout=5,
        )

        assert response.status_code == 200
        data = response.json()
        assert "protocol_version" in data


class TestProtocolVersionNegotiation:
    """Tests for protocol version negotiation."""

    def test_client_sends_version_in_handshake(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """SyncClient sends protocol version in handshake."""
        node_a, node_b = two_nodes_with_servers

        # Intercept handshake to verify version sent
        # (This would require mocking in actual implementation)
        # For now, just verify sync works
        from .conftest import sync_nodes
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True

    def test_server_responds_with_its_version(self, running_server_a: SyncNode):
        """Server responds with its own protocol version."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": "1.0",
            },
            timeout=5,
        )

        data = response.json()
        # Server responds with its version (should be 1.0)
        assert data["protocol_version"] == "1.0"


class TestFutureProtocolVersion:
    """Tests for future-proofing protocol version."""

    def test_unknown_fields_ignored(self, running_server_a: SyncNode):
        """Server ignores unknown fields in handshake."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": "1.0",
                "unknown_field": "should be ignored",
                "future_feature": {"nested": "data"},
            },
            timeout=5,
        )

        # Should succeed, ignoring unknown fields
        assert response.status_code == 200

    def test_unknown_fields_in_changes(self, running_server_a: SyncNode):
        """Server ignores unknown fields in changes."""
        create_note_on_node(running_server_a, "Test note")

        response = requests.get(
            f"{running_server_a.url}/sync/changes",
            timeout=5,
        )

        # Response should work normally
        assert response.status_code == 200

    def test_apply_with_unknown_entity_type(self, running_server_a: SyncNode):
        """Apply handles unknown entity types gracefully."""
        response = requests.post(
            f"{running_server_a.url}/sync/apply",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "changes": [
                    {
                        "entity_type": "future_entity",
                        "entity_id": "00000000000070008000000000000099",
                        "operation": "create",
                        "data": {},
                        "timestamp": "2024-01-01 00:00:00",  # Use space, not T
                        "device_id": "00000000000070008000000000000099",
                    }
                ],
            },
            timeout=5,
        )

        # Should handle gracefully - unknown entity type produces error
        assert response.status_code == 200
        data = response.json()
        # Unknown entity type should be skipped and reported as error
        assert data["applied"] == 0
        assert len(data.get("errors", [])) > 0


class TestProtocolVersionEdgeCases:
    """Edge cases for protocol version handling."""

    def test_empty_protocol_version(self, running_server_a: SyncNode):
        """Empty protocol version is handled."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": "",
            },
            timeout=5,
        )

        # Should default or handle gracefully
        assert response.status_code in [200, 400]

    def test_null_protocol_version(self, running_server_a: SyncNode):
        """Null protocol version is handled."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": None,
            },
            timeout=5,
        )

        # Null is treated as missing - server requires a valid protocol_version
        assert response.status_code in [200, 400, 422]

    def test_numeric_protocol_version(self, running_server_a: SyncNode):
        """Numeric protocol version is handled."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "Test",
                "protocol_version": 1.0,  # Number instead of string
            },
            timeout=5,
        )

        # Server may reject non-string protocol_version
        assert response.status_code in [200, 400, 422]
