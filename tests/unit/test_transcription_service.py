"""Tests for transcription service, especially credential handling."""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.core.transcription_service import TranscriptionService


# Sample service account data for testing (fake credentials)
FAKE_SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "key123",
    "private_key": """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA2mKqH0dSgVBv9pXv3mIQKaO8gP6vfj4d+kPNpXZJZ8X5pW9x
3HXKqCJF3GnPL+xvh7Ck3K4EqG6R7nGJXF6M3NJXQ4mGbzC5Rv8H3Qq0H7cK2qzP
vM7EqJXeNiGkLqJmvM7KqMFNqQ7JfM7bE2Vb5N8QJnE3MJxN+Nj3KdMHLnJaRvMy
vPq3VpJc+pLfM5Q8JqQXMZzMvPNJxMdMqMnL8nP5qX3J+nLfK3HJnLfJvM5nMnJL
vN3KqMdMqJnL+MnJqXfM3HJeNiGkLqJmvM7KqMFNqQ7JfM7bE2Vb5N8QJnE3MJxN
+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3Kqz
wIDAQABAoIBAC3qfM7HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5n
MnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnL
fJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXf
M3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+
MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMd
MqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLv
N3KqMdECgYEA8vM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdM
qJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN
3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5n
MnJLvN0CgYEA5LfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3Kq
MdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJ
LvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJv
M5nMnJECgYEAzvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJ
qXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJn
L+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3Kq
MdMqJn0CgYBJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMq
JnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3
KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nM
nJLvNQKBgQCJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMq
JnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3
KqMdMqJnL+MnJqXfM3HJnLfJvM5nMnJLvN3KqMdMqJnL+MnJqXfM3HJnLfJvM5nM
nJLvNQ==
-----END RSA PRIVATE KEY-----""",
    "client_email": "test@test-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test",
    "universe_domain": "googleapis.com",
}


def generate_real_rsa_key() -> str:
    """Generate a real RSA private key for testing."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return pem.decode("utf-8")


@pytest.fixture
def service_account_file(tmp_path: Path) -> Path:
    """Create a temporary service account JSON file with real RSA key."""
    sa_data = FAKE_SERVICE_ACCOUNT.copy()
    sa_data["private_key"] = generate_real_rsa_key()

    sa_file = tmp_path / "service_account.json"
    with open(sa_file, "w") as f:
        json.dump(sa_data, f)

    return sa_file


@pytest.fixture
def mock_database() -> MagicMock:
    """Create a mock database."""
    db = MagicMock()
    db.get_audio_file.return_value = {"id": "test123", "filename": "test.mp3"}
    return db


@pytest.fixture
def transcription_service(tmp_path: Path, mock_database: MagicMock) -> TranscriptionService:
    """Create a TranscriptionService instance."""
    audiofile_dir = tmp_path / "audiofiles"
    audiofile_dir.mkdir()
    return TranscriptionService(mock_database, audiofile_dir)


class TestJWTSigning:
    """Tests for JWT creation and signing."""

    def test_create_signed_jwt_has_three_parts(
        self, transcription_service: TranscriptionService
    ) -> None:
        """Signed JWT should have header.payload.signature format."""
        private_key = generate_real_rsa_key()

        jwt = transcription_service._create_signed_jwt(
            private_key_pem=private_key,
            client_email="test@example.com",
            token_uri="https://oauth2.googleapis.com/token",
            issued_at=1000000000,
            expires_at=1000003600,
            scope="https://www.googleapis.com/auth/cloud-platform",
        )

        parts = jwt.split(".")
        assert len(parts) == 3, "JWT should have 3 parts separated by dots"

    def test_create_signed_jwt_header_is_rs256(
        self, transcription_service: TranscriptionService
    ) -> None:
        """JWT header should specify RS256 algorithm."""
        private_key = generate_real_rsa_key()

        jwt = transcription_service._create_signed_jwt(
            private_key_pem=private_key,
            client_email="test@example.com",
            token_uri="https://oauth2.googleapis.com/token",
            issued_at=1000000000,
            expires_at=1000003600,
            scope="https://www.googleapis.com/auth/cloud-platform",
        )

        header_b64 = jwt.split(".")[0]
        # Add padding for base64 decode
        header_b64 += "=" * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_b64))

        assert header["alg"] == "RS256"
        assert header["typ"] == "JWT"

    def test_create_signed_jwt_payload_has_required_claims(
        self, transcription_service: TranscriptionService
    ) -> None:
        """JWT payload should have iss, sub, aud, iat, exp, scope claims."""
        private_key = generate_real_rsa_key()

        jwt = transcription_service._create_signed_jwt(
            private_key_pem=private_key,
            client_email="test@example.com",
            token_uri="https://oauth2.googleapis.com/token",
            issued_at=1000000000,
            expires_at=1000003600,
            scope="https://www.googleapis.com/auth/cloud-platform",
        )

        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert payload["iss"] == "test@example.com"
        assert payload["sub"] == "test@example.com"
        assert payload["aud"] == "https://oauth2.googleapis.com/token"
        assert payload["iat"] == 1000000000
        assert payload["exp"] == 1000003600
        assert payload["scope"] == "https://www.googleapis.com/auth/cloud-platform"

    def test_create_signed_jwt_signature_is_valid(
        self, transcription_service: TranscriptionService
    ) -> None:
        """JWT signature should be verifiable with the public key."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        # Generate key pair
        private_key_obj = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key = private_key_obj.public_key()

        private_key_pem = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        jwt = transcription_service._create_signed_jwt(
            private_key_pem=private_key_pem,
            client_email="test@example.com",
            token_uri="https://oauth2.googleapis.com/token",
            issued_at=1000000000,
            expires_at=1000003600,
            scope="https://www.googleapis.com/auth/cloud-platform",
        )

        parts = jwt.split(".")
        signing_input = f"{parts[0]}.{parts[1]}"
        signature_b64 = parts[2]
        signature_b64 += "=" * (4 - len(signature_b64) % 4)
        signature = base64.urlsafe_b64decode(signature_b64)

        # Verify signature (raises exception if invalid)
        public_key.verify(
            signature,
            signing_input.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )


class TestGoogleAccessToken:
    """Tests for Google access token generation."""

    def test_get_google_access_token_missing_credentials_path(
        self, transcription_service: TranscriptionService
    ) -> None:
        """Should raise ValueError if credentials_path is missing."""
        with pytest.raises(ValueError, match="credentials_path is required"):
            transcription_service._get_google_access_token({})

    def test_get_google_access_token_file_not_found(
        self, transcription_service: TranscriptionService
    ) -> None:
        """Should raise ValueError if credentials file doesn't exist."""
        with pytest.raises(ValueError, match="Credentials file not found"):
            transcription_service._get_google_access_token({
                "credentials_path": "/nonexistent/path.json"
            })

    def test_get_google_access_token_invalid_json(
        self, transcription_service: TranscriptionService, tmp_path: Path
    ) -> None:
        """Should raise ValueError if credentials file has invalid JSON."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json")

        with pytest.raises(ValueError, match="Failed to authenticate"):
            transcription_service._get_google_access_token({
                "credentials_path": str(bad_file)
            })

    def test_get_google_access_token_missing_private_key(
        self, transcription_service: TranscriptionService, tmp_path: Path
    ) -> None:
        """Should raise ValueError if private_key is missing from credentials."""
        bad_file = tmp_path / "missing_key.json"
        bad_file.write_text(json.dumps({"client_email": "test@test.com"}))

        with pytest.raises(ValueError, match="missing private_key"):
            transcription_service._get_google_access_token({
                "credentials_path": str(bad_file)
            })

    @patch("urllib.request.urlopen")
    def test_get_google_access_token_success(
        self,
        mock_urlopen: MagicMock,
        transcription_service: TranscriptionService,
        service_account_file: Path,
    ) -> None:
        """Should return access token on successful OAuth exchange."""
        # Mock the token response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "access_token": "ya29.test_token_12345",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        token = transcription_service._get_google_access_token({
            "credentials_path": str(service_account_file)
        })

        assert token == "ya29.test_token_12345"
        mock_urlopen.assert_called_once()


class TestProviderConfigLoading:
    """Tests for loading provider configs from app config."""

    def test_get_provider_config_no_config(
        self, transcription_service: TranscriptionService
    ) -> None:
        """Should return empty dict if no config is set."""
        result = transcription_service._get_provider_config_from_app_config("google")
        assert result == {}

    def test_get_provider_config_empty_transcription_config(
        self, tmp_path: Path, mock_database: MagicMock
    ) -> None:
        """Should return empty dict if transcription config is empty."""
        mock_config = MagicMock()
        mock_config.get_transcription_config.return_value = {}

        service = TranscriptionService(
            mock_database,
            tmp_path,
            config=mock_config,
        )

        result = service._get_provider_config_from_app_config("google")
        assert result == {}

    def test_get_provider_config_google(
        self, tmp_path: Path, mock_database: MagicMock
    ) -> None:
        """Should return google config from transcription config."""
        mock_config = MagicMock()
        mock_config.get_transcription_config.return_value = {
            "google": {
                "credentials_path": "/path/to/creds.json",
                "project_id": "my-project",
                "speech_model": "chirp_3",
            }
        }

        service = TranscriptionService(
            mock_database,
            tmp_path,
            config=mock_config,
        )

        result = service._get_provider_config_from_app_config("google")
        assert result["credentials_path"] == "/path/to/creds.json"
        assert result["project_id"] == "my-project"
        assert result["speech_model"] == "chirp_3"

    def test_get_provider_config_speechtext_ai(
        self, tmp_path: Path, mock_database: MagicMock
    ) -> None:
        """Should return speechtext_ai config from transcription config."""
        mock_config = MagicMock()
        mock_config.get_transcription_config.return_value = {
            "speechtext_ai": {
                "api_key": "secret_key_123",
            }
        }

        service = TranscriptionService(
            mock_database,
            tmp_path,
            config=mock_config,
        )

        result = service._get_provider_config_from_app_config("speechtext_ai")
        assert result["api_key"] == "secret_key_123"

    def test_get_provider_config_local_whisper(
        self, tmp_path: Path, mock_database: MagicMock
    ) -> None:
        """Should return local_whisper config from transcription config."""
        mock_config = MagicMock()
        mock_config.get_transcription_config.return_value = {
            "local_whisper": {
                "model_path": "/path/to/ggml-base.bin",
            }
        }

        service = TranscriptionService(
            mock_database,
            tmp_path,
            config=mock_config,
        )

        result = service._get_provider_config_from_app_config("local_whisper")
        assert result["model_path"] == "/path/to/ggml-base.bin"


class TestGoogleCloudClient:
    """Tests for Google Cloud client creation."""

    def test_create_google_cloud_client_missing_project_id(
        self,
        transcription_service: TranscriptionService,
        service_account_file: Path,
    ) -> None:
        """Should raise ValueError if project_id is missing."""
        with patch.object(
            transcription_service,
            "_get_google_access_token",
            return_value="test_token",
        ):
            with pytest.raises(ValueError, match="project_id is required"):
                transcription_service._create_google_cloud_client({
                    "credentials_path": str(service_account_file),
                })

    @patch("urllib.request.urlopen")
    @patch("voice_transcription.TranscriptionClient")
    def test_create_google_cloud_client_success(
        self,
        MockClient: MagicMock,
        mock_urlopen: MagicMock,
        transcription_service: TranscriptionService,
        service_account_file: Path,
    ) -> None:
        """Should create client with correct parameters."""
        # Mock token response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "access_token": "ya29.test_token",
            "expires_in": 3600,
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        MockClient.with_google_cloud.return_value = MagicMock()

        transcription_service._create_google_cloud_client({
            "credentials_path": str(service_account_file),
            "project_id": "test-project",
            "speech_location": "us",
            "speech_model": "chirp_3",
        })

        MockClient.with_google_cloud.assert_called_once_with(
            access_token="ya29.test_token",
            project_id="test-project",
            location="us",
            model="chirp_3",
        )
