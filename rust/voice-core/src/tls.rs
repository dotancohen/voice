//! TLS certificate management for Voice sync.
//!
//! This module handles:
//! - Self-signed certificate generation
//! - Certificate fingerprint computation
//! - Trust On First Use (TOFU) verification
//! - SSL context creation

use std::fs;
use std::path::Path;

use sha2::{Digest, Sha256};

use crate::config::Config;
use crate::error::{VoiceError, VoiceResult};

/// Certificate validity period (10 years in days)
pub const CERT_VALIDITY_DAYS: u32 = 3650;

/// Compute SHA-256 fingerprint from DER-encoded certificate data
pub fn compute_fingerprint_from_der(der_data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(der_data);
    let result = hasher.finalize();

    let hex_parts: Vec<String> = result.iter().map(|b| format!("{:02x}", b)).collect();
    format!("SHA256:{}", hex_parts.join(":"))
}

/// Compute SHA-256 fingerprint from PEM certificate file
pub fn compute_fingerprint(cert_path: &Path) -> VoiceResult<String> {
    let pem_data = fs::read(cert_path)?;
    compute_fingerprint_from_pem(&pem_data)
}

/// Compute SHA-256 fingerprint from PEM certificate data
pub fn compute_fingerprint_from_pem(pem_data: &[u8]) -> VoiceResult<String> {
    // Find the base64 content between BEGIN and END markers
    let pem_str = std::str::from_utf8(pem_data)
        .map_err(|e| VoiceError::Tls(format!("Invalid PEM encoding: {}", e)))?;

    let start_marker = "-----BEGIN CERTIFICATE-----";
    let end_marker = "-----END CERTIFICATE-----";

    let start = pem_str
        .find(start_marker)
        .ok_or_else(|| VoiceError::Tls("No certificate found in PEM".to_string()))?
        + start_marker.len();
    let end = pem_str
        .find(end_marker)
        .ok_or_else(|| VoiceError::Tls("Invalid PEM format".to_string()))?;

    let base64_content: String = pem_str[start..end]
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect();

    // Decode base64 to get DER
    use base64::Engine;
    let der_data = base64::engine::general_purpose::STANDARD
        .decode(&base64_content)
        .map_err(|e| VoiceError::Tls(format!("Invalid base64 in PEM: {}", e)))?;

    Ok(compute_fingerprint_from_der(&der_data))
}

/// Verify that a certificate matches an expected fingerprint
pub fn verify_fingerprint(cert_path: &Path, expected_fingerprint: &str) -> VoiceResult<bool> {
    let actual_fingerprint = compute_fingerprint(cert_path)?;
    Ok(actual_fingerprint.to_lowercase() == expected_fingerprint.to_lowercase())
}

/// Trust On First Use certificate verifier
pub struct TOFUVerifier<'a> {
    config: &'a Config,
}

impl<'a> TOFUVerifier<'a> {
    pub fn new(config: &'a Config) -> Self {
        Self { config }
    }

    /// Verify a peer's certificate using TOFU
    ///
    /// Returns (is_trusted, fingerprint, error_message)
    pub fn verify_peer(&self, peer_id: &str, peer_cert_pem: &[u8]) -> (bool, String, Option<String>) {
        let actual_fingerprint = match compute_fingerprint_from_pem(peer_cert_pem) {
            Ok(fp) => fp,
            Err(e) => return (false, String::new(), Some(format!("Failed to compute fingerprint: {}", e))),
        };

        // Get stored fingerprint for this peer
        let peer = match self.config.get_peer(peer_id) {
            Some(p) => p,
            None => return (false, actual_fingerprint, Some("Unknown peer".to_string())),
        };

        let stored_fingerprint = &peer.certificate_fingerprint;

        match stored_fingerprint {
            None => {
                // First connection - TOFU: trust the fingerprint
                // Note: The caller should update the config to store the fingerprint
                (true, actual_fingerprint, None)
            }
            Some(stored) => {
                // Verify fingerprint matches
                if actual_fingerprint.to_lowercase() == stored.to_lowercase() {
                    (true, actual_fingerprint, None)
                } else {
                    (
                        false,
                        actual_fingerprint.clone(),
                        Some(format!(
                            "Certificate fingerprint mismatch! Expected: {}, Got: {}. \
                             This could indicate a man-in-the-middle attack or \
                             the peer regenerated their certificate.",
                            stored, actual_fingerprint
                        )),
                    )
                }
            }
        }
    }
}

/// Generate a self-signed certificate
///
/// This is a placeholder - actual certificate generation would require
/// the `rcgen` or `openssl` crate. For now, we assume certificates
/// are generated externally or by the Python code during transition.
pub fn generate_self_signed_cert(
    _cert_path: &Path,
    _key_path: &Path,
    _common_name: &str,
    _device_id: Option<&str>,
) -> VoiceResult<(String, String)> {
    Err(VoiceError::Tls(
        "Certificate generation not yet implemented in Rust. \
         Please generate certificates using the Python version or openssl."
            .to_string(),
    ))
}

/// Ensure server certificate exists
///
/// Returns (cert_path, key_path, fingerprint)
pub fn ensure_server_certificate(
    config: &Config,
    force_regenerate: bool,
) -> VoiceResult<(std::path::PathBuf, std::path::PathBuf, String)> {
    let certs_dir = config.certs_dir()?;
    let cert_path = certs_dir.join("server.crt");
    let key_path = certs_dir.join("server.key");

    if force_regenerate || !cert_path.exists() || !key_path.exists() {
        // For now, return an error - certificate generation will be added later
        return Err(VoiceError::Tls(format!(
            "Server certificate not found at {}. \
             Please generate certificates using: \
             openssl req -x509 -newkey rsa:2048 -keyout {} -out {} -days 3650 -nodes",
            cert_path.display(),
            key_path.display(),
            cert_path.display()
        )));
    }

    // Compute fingerprint of existing certificate
    let fingerprint = compute_fingerprint(&cert_path)?;

    Ok((cert_path, key_path, fingerprint))
}

#[cfg(test)]
mod tests {
    use super::*;

    // Sample self-signed certificate for testing
    const TEST_CERT_PEM: &str = r#"-----BEGIN CERTIFICATE-----
MIIBkTCB+wIJAKHBfpIgb5OJMA0GCSqGSIb3DQEBCwUAMBExDzANBgNVBAMMBnZv
aWNlMB4XDTIxMDEwMTAwMDAwMFoXDTMxMDEwMTAwMDAwMFowETEPMA0GA1UEAwwG
dm9pY2UwXDANBgkqhkiG9w0BAQEFAANLADBIAkEAyA8dF9VzOdqmGqKJLqJBNnvS
9BgqA8L5rqZxVQ8jFnqe5T0lKLqaA9xVtJvA8eHKjqhMvREXGVCrOqPeGhqZrwID
AQABo1MwUTAdBgNVHQ4EFgQUvCgqF3jqPmqTEYCTiEzxJqG6hwowHwYDVR0jBBgw
FoAUvCgqF3jqPmqTEYCTiEzxJqG6hwowDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG
9w0BAQsFAANBAJBF3J8cLqJBNnvS9BgqA8L5rqZxVQ8jFnqe5T0lKLqaA9xVtJvA
8eHKjqhMvREXGVCrOqPeGhqZrw8dF9VzOdqmGqI=
-----END CERTIFICATE-----"#;

    #[test]
    fn test_compute_fingerprint_from_pem() {
        let result = compute_fingerprint_from_pem(TEST_CERT_PEM.as_bytes());
        assert!(result.is_ok());
        let fingerprint = result.unwrap();
        assert!(fingerprint.starts_with("SHA256:"));
        // Fingerprint should have 64 hex chars separated by colons
        let parts: Vec<&str> = fingerprint[7..].split(':').collect();
        assert_eq!(parts.len(), 32);
    }

    #[test]
    fn test_fingerprint_format() {
        let der_data = vec![0u8; 32]; // Dummy data
        let fingerprint = compute_fingerprint_from_der(&der_data);
        assert!(fingerprint.starts_with("SHA256:"));
    }
}
