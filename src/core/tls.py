"""TLS certificate management for Voice sync.

This module handles:
- Self-signed certificate generation
- Certificate fingerprint computation
- Trust On First Use (TOFU) verification
- SSL context creation

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import hashlib
import logging
import os
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# Certificate validity period (10 years)
CERT_VALIDITY_DAYS = 3650


def generate_self_signed_cert(
    cert_path: Path,
    key_path: Path,
    common_name: str = "Voice Sync",
    device_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Generate a self-signed certificate and private key.

    Uses the cryptography library to generate a 2048-bit RSA key
    and self-signed X.509 certificate.

    Args:
        cert_path: Path to save the certificate PEM file
        key_path: Path to save the private key PEM file
        common_name: Common Name (CN) for the certificate
        device_id: Optional device ID to include in subject

    Returns:
        Tuple of (certificate_fingerprint, certificate_path)

    Raises:
        ImportError: If cryptography library is not installed
        OSError: If files cannot be written
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required for TLS support. "
            "Install it with: pip install cryptography"
        )

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    # Build certificate subject
    subject_attrs = [
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Voice"),
    ]
    if device_id:
        subject_attrs.append(
            x509.NameAttribute(NameOID.SERIAL_NUMBER, device_id[:32])
        )

    subject = issuer = x509.Name(subject_attrs)

    # Build certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Ensure parent directories exist
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # Write private key
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    # Set restrictive permissions on private key
    os.chmod(key_path, 0o600)

    # Write certificate
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Compute fingerprint
    fingerprint = compute_fingerprint_from_cert(cert)

    logger.info(f"Generated self-signed certificate: {cert_path}")
    logger.info(f"Certificate fingerprint: {fingerprint}")

    return fingerprint, str(cert_path)


def compute_fingerprint(cert_path: Path) -> str:
    """Compute SHA-256 fingerprint of a certificate file.

    Args:
        cert_path: Path to PEM certificate file

    Returns:
        Fingerprint string in format "SHA256:xx:xx:xx..."

    Raises:
        FileNotFoundError: If certificate file doesn't exist
        ValueError: If certificate cannot be parsed
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required for TLS support. "
            "Install it with: pip install cryptography"
        )

    with open(cert_path, "rb") as f:
        cert_data = f.read()

    cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    return compute_fingerprint_from_cert(cert)


def compute_fingerprint_from_cert(cert) -> str:
    """Compute SHA-256 fingerprint from a certificate object.

    Args:
        cert: x509.Certificate object

    Returns:
        Fingerprint string in format "SHA256:xx:xx:xx..."
    """
    from cryptography.hazmat.primitives import hashes

    fingerprint_bytes = cert.fingerprint(hashes.SHA256())
    fingerprint_hex = ":".join(f"{b:02x}" for b in fingerprint_bytes)
    return f"SHA256:{fingerprint_hex}"


def compute_fingerprint_from_pem(pem_data: bytes) -> str:
    """Compute SHA-256 fingerprint from PEM certificate data.

    Args:
        pem_data: PEM-encoded certificate bytes

    Returns:
        Fingerprint string in format "SHA256:xx:xx:xx..."
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required for TLS support. "
            "Install it with: pip install cryptography"
        )

    cert = x509.load_pem_x509_certificate(pem_data, default_backend())
    return compute_fingerprint_from_cert(cert)


def verify_fingerprint(cert_path: Path, expected_fingerprint: str) -> bool:
    """Verify that a certificate matches an expected fingerprint.

    Args:
        cert_path: Path to PEM certificate file
        expected_fingerprint: Expected fingerprint (SHA256:xx:xx:xx...)

    Returns:
        True if fingerprint matches, False otherwise
    """
    try:
        actual_fingerprint = compute_fingerprint(cert_path)
        return actual_fingerprint.lower() == expected_fingerprint.lower()
    except Exception as e:
        logger.error(f"Error verifying fingerprint: {e}")
        return False


def create_server_ssl_context(
    cert_path: Path,
    key_path: Path,
) -> ssl.SSLContext:
    """Create an SSL context for the sync server.

    Args:
        cert_path: Path to PEM certificate file
        key_path: Path to PEM private key file

    Returns:
        Configured SSLContext for server use

    Raises:
        FileNotFoundError: If certificate or key file doesn't exist
        ssl.SSLError: If certificate or key is invalid
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    # Load certificate and key
    context.load_cert_chain(str(cert_path), str(key_path))

    # Security settings
    context.set_ciphers("ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20:DHE+CHACHA20")
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.options |= ssl.OP_NO_TLSv1
    context.options |= ssl.OP_NO_TLSv1_1

    logger.info(f"Created server SSL context with certificate: {cert_path}")
    return context


def create_client_ssl_context(
    trusted_fingerprint: Optional[str] = None,
    verify_mode: bool = True,
) -> ssl.SSLContext:
    """Create an SSL context for sync client connections.

    For TOFU mode, we create a context that will verify the certificate
    but allow connecting to get the fingerprint for first-time trust.

    Args:
        trusted_fingerprint: Expected fingerprint (for verification)
        verify_mode: If True, verify certificates. If False, allow any cert.

    Returns:
        Configured SSLContext for client use
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    if verify_mode and trusted_fingerprint:
        # We'll verify the fingerprint manually after connection
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        # We need to load CA certs to verify, but for self-signed
        # we'll handle verification ourselves
        context.verify_mode = ssl.CERT_NONE
    else:
        # TOFU mode - accept any certificate for first connection
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    # Security settings
    context.set_ciphers("ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20:DHE+CHACHA20")
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.options |= ssl.OP_NO_TLSv1
    context.options |= ssl.OP_NO_TLSv1_1

    return context


class TOFUVerifier:
    """Trust On First Use certificate verifier.

    On first connection to a peer, the certificate fingerprint is recorded.
    On subsequent connections, the fingerprint is verified to match.
    """

    def __init__(self, config):
        """Initialize TOFU verifier.

        Args:
            config: Config instance for storing fingerprints
        """
        self.config = config

    def verify_peer(
        self,
        peer_id: str,
        peer_cert_pem: bytes,
    ) -> Tuple[bool, str, Optional[str]]:
        """Verify a peer's certificate using TOFU.

        Args:
            peer_id: Peer's device UUID hex string
            peer_cert_pem: PEM-encoded certificate data

        Returns:
            Tuple of (is_trusted, fingerprint, error_message)
            - is_trusted: True if trusted (first use or fingerprint matches)
            - fingerprint: The certificate's fingerprint
            - error_message: Error message if not trusted, None otherwise
        """
        try:
            actual_fingerprint = compute_fingerprint_from_pem(peer_cert_pem)
        except Exception as e:
            return False, "", f"Failed to compute fingerprint: {e}"

        # Get stored fingerprint for this peer
        peer = self.config.get_peer(peer_id)
        if peer is None:
            # Unknown peer - cannot trust
            return False, actual_fingerprint, "Unknown peer"

        stored_fingerprint = peer.get("certificate_fingerprint")

        if stored_fingerprint is None:
            # First connection - TOFU: trust and store the fingerprint
            self.config.update_peer_certificate(peer_id, actual_fingerprint)
            logger.info(f"TOFU: Trusted new certificate for peer {peer_id}")
            return True, actual_fingerprint, None

        # Verify fingerprint matches
        if actual_fingerprint.lower() == stored_fingerprint.lower():
            return True, actual_fingerprint, None
        else:
            logger.warning(
                f"Certificate fingerprint mismatch for peer {peer_id}! "
                f"Expected: {stored_fingerprint}, Got: {actual_fingerprint}"
            )
            return False, actual_fingerprint, (
                f"Certificate fingerprint mismatch! "
                f"Expected: {stored_fingerprint}, Got: {actual_fingerprint}. "
                f"This could indicate a man-in-the-middle attack or "
                f"the peer regenerated their certificate."
            )

    def trust_peer_certificate(
        self,
        peer_id: str,
        fingerprint: str,
    ) -> bool:
        """Explicitly trust a peer's certificate fingerprint.

        Use this when the user confirms they want to trust a new certificate,
        e.g., after the peer regenerated their certificate.

        Args:
            peer_id: Peer's device UUID hex string
            fingerprint: Certificate fingerprint to trust

        Returns:
            True if successful, False if peer not found
        """
        return self.config.update_peer_certificate(peer_id, fingerprint)


def ensure_server_certificate(
    config,
    force_regenerate: bool = False,
) -> Tuple[Path, Path, str]:
    """Ensure server certificate exists, generating if needed.

    Args:
        config: Config instance
        force_regenerate: If True, regenerate even if exists

    Returns:
        Tuple of (cert_path, key_path, fingerprint)
    """
    certs_dir = config.get_certs_dir()
    cert_path = certs_dir / "server.crt"
    key_path = certs_dir / "server.key"

    if force_regenerate or not cert_path.exists() or not key_path.exists():
        device_id = config.get_device_id_hex()
        device_name = config.get_device_name()

        fingerprint, _ = generate_self_signed_cert(
            cert_path=cert_path,
            key_path=key_path,
            common_name=device_name,
            device_id=device_id,
        )

        # Store our own fingerprint in config
        config.set("server_certificate_fingerprint", fingerprint)

        logger.info(f"Generated server certificate with fingerprint: {fingerprint}")
    else:
        # Compute fingerprint of existing certificate
        fingerprint = compute_fingerprint(cert_path)
        stored_fingerprint = config.get("server_certificate_fingerprint")
        if stored_fingerprint != fingerprint:
            config.set("server_certificate_fingerprint", fingerprint)

    return cert_path, key_path, fingerprint


# Import for IP address in SAN
import ipaddress
