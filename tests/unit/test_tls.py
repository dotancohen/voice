"""Unit tests for TLS certificate management.

Tests certificate generation, fingerprint computation, and TOFU verification.
"""

from __future__ import annotations

import ssl
import uuid
from pathlib import Path

import pytest

from core.config import Config

# Skip all tests if cryptography is not installed
pytest.importorskip("cryptography")

from core.tls import (
    generate_self_signed_cert,
    compute_fingerprint,
    compute_fingerprint_from_pem,
    verify_fingerprint,
    create_server_ssl_context,
    create_client_ssl_context,
    TOFUVerifier,
    ensure_server_certificate,
)


@pytest.fixture
def tls_config(test_config_dir: Path) -> Config:
    """Create a config instance for TLS testing."""
    return Config(config_dir=test_config_dir)


@pytest.fixture
def cert_files(test_config_dir: Path) -> tuple[Path, Path]:
    """Generate test certificate and key files."""
    certs_dir = test_config_dir / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_path = certs_dir / "test.crt"
    key_path = certs_dir / "test.key"

    generate_self_signed_cert(
        cert_path=cert_path,
        key_path=key_path,
        common_name="Test Certificate",
    )

    return cert_path, key_path


class TestGenerateCertificate:
    """Test certificate generation."""

    def test_generates_certificate_and_key(self, test_config_dir: Path) -> None:
        """Certificate and key files are created."""
        certs_dir = test_config_dir / "certs"
        cert_path = certs_dir / "gen_test.crt"
        key_path = certs_dir / "gen_test.key"

        fingerprint, _ = generate_self_signed_cert(
            cert_path=cert_path,
            key_path=key_path,
            common_name="Test",
        )

        assert cert_path.exists()
        assert key_path.exists()
        assert fingerprint.startswith("SHA256:")

    def test_generates_with_device_id(self, test_config_dir: Path) -> None:
        """Certificate includes device ID in subject."""
        certs_dir = test_config_dir / "certs"
        cert_path = certs_dir / "device_test.crt"
        key_path = certs_dir / "device_test.key"
        device_id = uuid.uuid4().hex

        fingerprint, _ = generate_self_signed_cert(
            cert_path=cert_path,
            key_path=key_path,
            common_name="Device Test",
            device_id=device_id,
        )

        assert cert_path.exists()
        assert fingerprint.startswith("SHA256:")

    def test_key_has_restricted_permissions(self, test_config_dir: Path) -> None:
        """Private key has 0600 permissions."""
        import os
        import stat

        certs_dir = test_config_dir / "certs"
        cert_path = certs_dir / "perm_test.crt"
        key_path = certs_dir / "perm_test.key"

        generate_self_signed_cert(
            cert_path=cert_path,
            key_path=key_path,
            common_name="Perm Test",
        )

        # Check key permissions (owner read/write only)
        key_mode = os.stat(key_path).st_mode
        assert (key_mode & 0o777) == 0o600


class TestComputeFingerprint:
    """Test fingerprint computation."""

    def test_computes_fingerprint_from_file(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Computes fingerprint from certificate file."""
        cert_path, _ = cert_files
        fingerprint = compute_fingerprint(cert_path)

        assert fingerprint.startswith("SHA256:")
        # SHA256 fingerprint has 64 hex chars + colons
        parts = fingerprint.split(":")[1:]  # Skip "SHA256" prefix
        hex_str = "".join(parts)
        assert len(hex_str) == 64

    def test_fingerprint_is_consistent(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Same certificate produces same fingerprint."""
        cert_path, _ = cert_files
        fp1 = compute_fingerprint(cert_path)
        fp2 = compute_fingerprint(cert_path)
        assert fp1 == fp2

    def test_computes_fingerprint_from_pem(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Computes fingerprint from PEM data."""
        cert_path, _ = cert_files
        with open(cert_path, "rb") as f:
            pem_data = f.read()

        fingerprint = compute_fingerprint_from_pem(pem_data)
        file_fingerprint = compute_fingerprint(cert_path)

        assert fingerprint == file_fingerprint


class TestVerifyFingerprint:
    """Test fingerprint verification."""

    def test_verify_matching_fingerprint(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Verification succeeds for matching fingerprint."""
        cert_path, _ = cert_files
        fingerprint = compute_fingerprint(cert_path)

        result = verify_fingerprint(cert_path, fingerprint)
        assert result is True

    def test_verify_wrong_fingerprint(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Verification fails for wrong fingerprint."""
        cert_path, _ = cert_files
        wrong_fingerprint = "SHA256:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"

        result = verify_fingerprint(cert_path, wrong_fingerprint)
        assert result is False

    def test_verify_case_insensitive(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Verification is case-insensitive."""
        cert_path, _ = cert_files
        fingerprint = compute_fingerprint(cert_path)

        result_upper = verify_fingerprint(cert_path, fingerprint.upper())
        result_lower = verify_fingerprint(cert_path, fingerprint.lower())

        assert result_upper is True
        assert result_lower is True


class TestSSLContext:
    """Test SSL context creation."""

    def test_create_server_context(
        self, cert_files: tuple[Path, Path]
    ) -> None:
        """Creates server SSL context."""
        cert_path, key_path = cert_files
        context = create_server_ssl_context(cert_path, key_path)

        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_create_client_context(self) -> None:
        """Creates client SSL context."""
        context = create_client_ssl_context()

        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_client_context_tofu_mode(self) -> None:
        """Client context in TOFU mode accepts any certificate."""
        context = create_client_ssl_context(verify_mode=False)

        assert context.verify_mode == ssl.CERT_NONE


class TestTOFUVerifier:
    """Test Trust On First Use verification."""

    def test_unknown_peer_not_trusted(
        self, tls_config: Config, cert_files: tuple[Path, Path]
    ) -> None:
        """Unknown peer is not trusted."""
        verifier = TOFUVerifier(tls_config)
        cert_path, _ = cert_files
        with open(cert_path, "rb") as f:
            cert_pem = f.read()

        peer_id = uuid.uuid4().hex
        is_trusted, fingerprint, error = verifier.verify_peer(peer_id, cert_pem)

        assert is_trusted is False
        assert "Unknown peer" in error

    def test_first_connection_trusts_cert(
        self, tls_config: Config, cert_files: tuple[Path, Path]
    ) -> None:
        """First connection to known peer trusts certificate (TOFU)."""
        verifier = TOFUVerifier(tls_config)
        cert_path, _ = cert_files
        with open(cert_path, "rb") as f:
            cert_pem = f.read()

        # Add peer without fingerprint
        peer_id = uuid.uuid4().hex
        tls_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="https://example.com:8384",
            certificate_fingerprint=None,
        )

        is_trusted, fingerprint, error = verifier.verify_peer(peer_id, cert_pem)

        assert is_trusted is True
        assert error is None
        assert fingerprint.startswith("SHA256:")

        # Check fingerprint was stored
        peer = tls_config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == fingerprint

    def test_matching_fingerprint_trusted(
        self, tls_config: Config, cert_files: tuple[Path, Path]
    ) -> None:
        """Matching fingerprint is trusted."""
        verifier = TOFUVerifier(tls_config)
        cert_path, _ = cert_files
        fingerprint = compute_fingerprint(cert_path)
        with open(cert_path, "rb") as f:
            cert_pem = f.read()

        # Add peer with fingerprint
        peer_id = uuid.uuid4().hex
        tls_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="https://example.com:8384",
            certificate_fingerprint=fingerprint,
        )

        is_trusted, actual_fp, error = verifier.verify_peer(peer_id, cert_pem)

        assert is_trusted is True
        assert error is None
        assert actual_fp == fingerprint

    def test_mismatched_fingerprint_not_trusted(
        self, tls_config: Config, cert_files: tuple[Path, Path]
    ) -> None:
        """Mismatched fingerprint is not trusted."""
        verifier = TOFUVerifier(tls_config)
        cert_path, _ = cert_files
        with open(cert_path, "rb") as f:
            cert_pem = f.read()

        # Add peer with wrong fingerprint
        peer_id = uuid.uuid4().hex
        wrong_fingerprint = "SHA256:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
        tls_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="https://example.com:8384",
            certificate_fingerprint=wrong_fingerprint,
        )

        is_trusted, _, error = verifier.verify_peer(peer_id, cert_pem)

        assert is_trusted is False
        assert "mismatch" in error.lower()

    def test_trust_peer_certificate(
        self, tls_config: Config, cert_files: tuple[Path, Path]
    ) -> None:
        """Can explicitly trust a new certificate."""
        verifier = TOFUVerifier(tls_config)
        cert_path, _ = cert_files
        new_fingerprint = compute_fingerprint(cert_path)

        # Add peer with old fingerprint
        peer_id = uuid.uuid4().hex
        old_fingerprint = "SHA256:01:02:03:04:05:06:07:08:09:0a:0b:0c:0d:0e:0f:10:11:12:13:14:15:16:17:18:19:1a:1b:1c:1d:1e:1f:20"
        tls_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="https://example.com:8384",
            certificate_fingerprint=old_fingerprint,
        )

        # Explicitly trust new certificate
        result = verifier.trust_peer_certificate(peer_id, new_fingerprint)
        assert result is True

        # Verify new fingerprint is stored
        peer = tls_config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == new_fingerprint


class TestEnsureServerCertificate:
    """Test server certificate provisioning."""

    def test_generates_if_missing(self, tls_config: Config) -> None:
        """Generates certificate if missing."""
        cert_path, key_path, fingerprint = ensure_server_certificate(tls_config)

        assert cert_path.exists()
        assert key_path.exists()
        assert fingerprint.startswith("SHA256:")

    def test_reuses_existing(self, tls_config: Config) -> None:
        """Reuses existing certificate."""
        # First call - generate
        cert_path1, key_path1, fp1 = ensure_server_certificate(tls_config)

        # Second call - reuse
        cert_path2, key_path2, fp2 = ensure_server_certificate(tls_config)

        assert cert_path1 == cert_path2
        assert key_path1 == key_path2
        assert fp1 == fp2

    def test_force_regenerate(self, tls_config: Config) -> None:
        """Force regenerates certificate."""
        # First call - generate
        _, _, fp1 = ensure_server_certificate(tls_config)

        # Second call - force regenerate
        _, _, fp2 = ensure_server_certificate(tls_config, force_regenerate=True)

        # New certificate should have different fingerprint
        assert fp1 != fp2

    def test_stores_fingerprint_in_config(self, tls_config: Config) -> None:
        """Stores server fingerprint in config."""
        _, _, fingerprint = ensure_server_certificate(tls_config)

        stored = tls_config.get("server_certificate_fingerprint")
        assert stored == fingerprint
