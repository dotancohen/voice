//! Configuration management for Voice.
//!
//! This module handles loading and saving application configuration to/from
//! a JSON file. The config directory can be customized.
//!
//! Includes sync-related configuration:
//! - device_id: UUID7 identifying this device (generated on first run)
//! - device_name: Human-readable device name
//! - sync: Peer configuration and sync settings

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::error::{VoiceError, VoiceResult};

/// Theme colors configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThemeColours {
    /// Warning color for highlighting ambiguous tags
    #[serde(default = "default_warnings_color")]
    pub warnings: String,
    /// TUI border color when focused
    #[serde(default = "default_tui_border_focused")]
    pub tui_border_focused: String,
    /// TUI border color when unfocused
    #[serde(default = "default_tui_border_unfocused")]
    pub tui_border_unfocused: String,
    /// Warning color for dark theme
    #[serde(default)]
    pub warnings_dark: Option<String>,
    /// Warning color for light theme
    #[serde(default)]
    pub warnings_light: Option<String>,
}

impl Default for ThemeColours {
    fn default() -> Self {
        Self {
            warnings: default_warnings_color(),
            tui_border_focused: default_tui_border_focused(),
            tui_border_unfocused: default_tui_border_unfocused(),
            warnings_dark: None,
            warnings_light: None,
        }
    }
}

fn default_warnings_color() -> String {
    "#FFFF00".to_string()
}

fn default_tui_border_focused() -> String {
    "green".to_string()
}

fn default_tui_border_unfocused() -> String {
    "blue".to_string()
}

/// Themes configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Themes {
    #[serde(default)]
    pub colours: ThemeColours,
}

/// Peer configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerConfig {
    pub peer_id: String,
    pub peer_name: String,
    pub peer_url: String,
    pub certificate_fingerprint: Option<String>,
}

/// Sync configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_server_port")]
    pub server_port: u16,
    #[serde(default)]
    pub peers: Vec<PeerConfig>,
}

fn default_server_port() -> u16 {
    8384
}

impl Default for SyncConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            server_port: default_server_port(),
            peers: Vec::new(),
        }
    }
}

/// Main configuration structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigData {
    /// Path to the database file
    #[serde(default)]
    pub database_file: String,
    /// Default interface (null = auto-detect)
    pub default_interface: Option<String>,
    /// Window geometry for GUI
    pub window_geometry: Option<String>,
    /// Component implementations (future use)
    #[serde(default)]
    pub implementations: HashMap<String, String>,
    /// Theme configuration
    #[serde(default)]
    pub themes: Themes,
    /// Device ID (UUID7 hex)
    #[serde(default = "generate_device_id")]
    pub device_id: String,
    /// Human-readable device name
    #[serde(default = "get_default_device_name")]
    pub device_name: String,
    /// Sync configuration
    #[serde(default)]
    pub sync: SyncConfig,
    /// Server certificate fingerprint
    pub server_certificate_fingerprint: Option<String>,
}

fn generate_device_id() -> String {
    Uuid::now_v7().simple().to_string()
}

fn get_default_device_name() -> String {
    match hostname::get() {
        Ok(name) => format!("Voice on {}", name.to_string_lossy()),
        Err(_) => "Voice Device".to_string(),
    }
}

impl Default for ConfigData {
    fn default() -> Self {
        Self {
            database_file: String::new(),
            default_interface: None,
            window_geometry: None,
            implementations: HashMap::new(),
            themes: Themes::default(),
            device_id: generate_device_id(),
            device_name: get_default_device_name(),
            sync: SyncConfig::default(),
            server_certificate_fingerprint: None,
        }
    }
}

/// Configuration manager
pub struct Config {
    config_dir: PathBuf,
    config_file: PathBuf,
    data: ConfigData,
}

impl Config {
    /// Create a new configuration manager
    pub fn new(config_dir: Option<PathBuf>) -> VoiceResult<Self> {
        let config_dir = config_dir.unwrap_or_else(|| {
            dirs::config_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join("voice")
        });

        fs::create_dir_all(&config_dir)?;
        let config_file = config_dir.join("config.json");

        let data = if config_file.exists() {
            match fs::read_to_string(&config_file) {
                Ok(content) => serde_json::from_str(&content).unwrap_or_else(|_| {
                    let mut default = ConfigData::default();
                    default.database_file = config_dir.join("notes.db").to_string_lossy().to_string();
                    default
                }),
                Err(_) => {
                    let mut default = ConfigData::default();
                    default.database_file = config_dir.join("notes.db").to_string_lossy().to_string();
                    default
                }
            }
        } else {
            let mut default = ConfigData::default();
            default.database_file = config_dir.join("notes.db").to_string_lossy().to_string();
            default
        };

        let mut config = Self {
            config_dir,
            config_file,
            data,
        };

        // Save default config if it doesn't exist
        if !config.config_file.exists() {
            config.save()?;
        }

        Ok(config)
    }

    /// Save configuration to file
    pub fn save(&self) -> VoiceResult<()> {
        let content = serde_json::to_string_pretty(&self.data)?;
        fs::write(&self.config_file, content)?;
        Ok(())
    }

    /// Get the configuration directory path
    pub fn config_dir(&self) -> &Path {
        &self.config_dir
    }

    /// Get the database file path
    pub fn database_file(&self) -> &str {
        &self.data.database_file
    }

    /// Get the device ID as bytes
    pub fn device_id(&self) -> VoiceResult<Uuid> {
        Uuid::parse_str(&self.data.device_id)
            .map_err(|e| VoiceError::Config(format!("Invalid device_id: {}", e)))
    }

    /// Get the device ID as hex string
    pub fn device_id_hex(&self) -> &str {
        &self.data.device_id
    }

    /// Get the human-readable device name
    pub fn device_name(&self) -> &str {
        &self.data.device_name
    }

    /// Set the device name
    pub fn set_device_name(&mut self, name: &str) -> VoiceResult<()> {
        self.data.device_name = name.to_string();
        self.save()
    }

    /// Get sync configuration
    pub fn sync_config(&self) -> &SyncConfig {
        &self.data.sync
    }

    /// Check if sync is enabled
    pub fn is_sync_enabled(&self) -> bool {
        self.data.sync.enabled
    }

    /// Enable or disable sync
    pub fn set_sync_enabled(&mut self, enabled: bool) -> VoiceResult<()> {
        self.data.sync.enabled = enabled;
        self.save()
    }

    /// Get the sync server port
    pub fn sync_server_port(&self) -> u16 {
        self.data.sync.server_port
    }

    /// Set the sync server port
    pub fn set_sync_server_port(&mut self, port: u16) -> VoiceResult<()> {
        self.data.sync.server_port = port;
        self.save()
    }

    /// Get list of sync peers
    pub fn peers(&self) -> &[PeerConfig] {
        &self.data.sync.peers
    }

    /// Add a new sync peer
    pub fn add_peer(
        &mut self,
        peer_id: &str,
        peer_name: &str,
        peer_url: &str,
        certificate_fingerprint: Option<&str>,
        allow_update: bool,
    ) -> VoiceResult<()> {
        // Validate peer_id format
        if peer_id.len() != 32 || !peer_id.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(VoiceError::validation("peer_id", "must be 32 hex characters"));
        }

        // Check if peer already exists
        if let Some(existing) = self.data.sync.peers.iter_mut().find(|p| p.peer_id == peer_id) {
            if !allow_update {
                return Err(VoiceError::validation("peer_id", "peer already exists"));
            }
            existing.peer_name = peer_name.to_string();
            existing.peer_url = peer_url.to_string();
            if let Some(fp) = certificate_fingerprint {
                existing.certificate_fingerprint = Some(fp.to_string());
            }
        } else {
            self.data.sync.peers.push(PeerConfig {
                peer_id: peer_id.to_string(),
                peer_name: peer_name.to_string(),
                peer_url: peer_url.to_string(),
                certificate_fingerprint: certificate_fingerprint.map(String::from),
            });
        }

        self.save()
    }

    /// Remove a sync peer
    pub fn remove_peer(&mut self, peer_id: &str) -> VoiceResult<bool> {
        let original_len = self.data.sync.peers.len();
        self.data.sync.peers.retain(|p| p.peer_id != peer_id);
        let removed = self.data.sync.peers.len() < original_len;
        if removed {
            self.save()?;
        }
        Ok(removed)
    }

    /// Get a specific peer by ID
    pub fn get_peer(&self, peer_id: &str) -> Option<&PeerConfig> {
        self.data.sync.peers.iter().find(|p| p.peer_id == peer_id)
    }

    /// Update a peer's certificate fingerprint
    pub fn update_peer_certificate(&mut self, peer_id: &str, fingerprint: &str) -> VoiceResult<bool> {
        if let Some(peer) = self.data.sync.peers.iter_mut().find(|p| p.peer_id == peer_id) {
            peer.certificate_fingerprint = Some(fingerprint.to_string());
            self.save()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Get the certificates directory
    pub fn certs_dir(&self) -> VoiceResult<PathBuf> {
        let certs_dir = self.config_dir.join("certs");
        fs::create_dir_all(&certs_dir)?;
        Ok(certs_dir)
    }

    /// Get TUI colors
    pub fn tui_colors(&self) -> (&str, &str) {
        (
            &self.data.themes.colours.tui_border_focused,
            &self.data.themes.colours.tui_border_unfocused,
        )
    }

    /// Get warning color based on theme
    pub fn warning_color(&self, theme: &str) -> &str {
        match theme {
            "light" => self
                .data
                .themes
                .colours
                .warnings_light
                .as_deref()
                .unwrap_or(&self.data.themes.colours.warnings),
            _ => self
                .data
                .themes
                .colours
                .warnings_dark
                .as_deref()
                .unwrap_or(&self.data.themes.colours.warnings),
        }
    }

    /// Get a configuration value
    pub fn get(&self, key: &str) -> Option<String> {
        match key {
            "database_file" => Some(self.data.database_file.clone()),
            "default_interface" => self.data.default_interface.clone(),
            "device_id" => Some(self.data.device_id.clone()),
            "device_name" => Some(self.data.device_name.clone()),
            "server_certificate_fingerprint" => self.data.server_certificate_fingerprint.clone(),
            _ => None,
        }
    }

    /// Set a configuration value
    pub fn set(&mut self, key: &str, value: &str) -> VoiceResult<()> {
        match key {
            "database_file" => self.data.database_file = value.to_string(),
            "default_interface" => self.data.default_interface = Some(value.to_string()),
            "device_name" => self.data.device_name = value.to_string(),
            "server_certificate_fingerprint" => {
                self.data.server_certificate_fingerprint = Some(value.to_string())
            }
            _ => return Err(VoiceError::Config(format!("Unknown config key: {}", key))),
        }
        self.save()
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for Config
#[pyclass(name = "Config")]
pub struct PyConfig {
    inner: Config,
}

#[pymethods]
impl PyConfig {
    #[new]
    #[pyo3(signature = (config_dir=None))]
    fn new(config_dir: Option<&str>) -> PyResult<Self> {
        let path = config_dir.map(PathBuf::from);
        let config = Config::new(path)?;
        Ok(Self { inner: config })
    }

    /// Get the config directory path
    fn get_config_dir(&self) -> String {
        self.inner.config_dir().to_string_lossy().to_string()
    }

    /// Get the database file path
    fn get_database_file(&self) -> &str {
        self.inner.database_file()
    }

    /// Get device ID as hex string
    fn get_device_id_hex(&self) -> &str {
        self.inner.device_id_hex()
    }

    /// Get device ID as bytes
    fn get_device_id(&self) -> PyResult<Vec<u8>> {
        let uuid = self.inner.device_id()?;
        Ok(uuid.as_bytes().to_vec())
    }

    /// Get device name
    fn get_device_name(&self) -> &str {
        self.inner.device_name()
    }

    /// Set device name
    fn set_device_name(&mut self, name: &str) -> PyResult<()> {
        self.inner.set_device_name(name)?;
        Ok(())
    }

    /// Check if sync is enabled
    fn is_sync_enabled(&self) -> bool {
        self.inner.is_sync_enabled()
    }

    /// Enable or disable sync
    fn set_sync_enabled(&mut self, enabled: bool) -> PyResult<()> {
        self.inner.set_sync_enabled(enabled)?;
        Ok(())
    }

    /// Get sync server port
    fn get_sync_server_port(&self) -> u16 {
        self.inner.sync_server_port()
    }

    /// Set sync server port
    fn set_sync_server_port(&mut self, port: u16) -> PyResult<()> {
        self.inner.set_sync_server_port(port)?;
        Ok(())
    }

    /// Get all peers
    fn get_peers(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = pyo3::types::PyList::empty(py);
        for peer in self.inner.peers() {
            let dict = PyDict::new(py);
            dict.set_item("peer_id", &peer.peer_id)?;
            dict.set_item("peer_name", &peer.peer_name)?;
            dict.set_item("peer_url", &peer.peer_url)?;
            dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
            list.append(dict)?;
        }
        Ok(list.into())
    }

    /// Add a peer
    #[pyo3(signature = (peer_id, peer_name, peer_url, certificate_fingerprint=None, allow_update=true))]
    fn add_peer(
        &mut self,
        peer_id: &str,
        peer_name: &str,
        peer_url: &str,
        certificate_fingerprint: Option<&str>,
        allow_update: bool,
    ) -> PyResult<()> {
        self.inner
            .add_peer(peer_id, peer_name, peer_url, certificate_fingerprint, allow_update)?;
        Ok(())
    }

    /// Remove a peer
    fn remove_peer(&mut self, peer_id: &str) -> PyResult<bool> {
        let removed = self.inner.remove_peer(peer_id)?;
        Ok(removed)
    }

    /// Get a peer by ID
    fn get_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<Option<PyObject>> {
        match self.inner.get_peer(peer_id) {
            Some(peer) => {
                let dict = PyDict::new(py);
                dict.set_item("peer_id", &peer.peer_id)?;
                dict.set_item("peer_name", &peer.peer_name)?;
                dict.set_item("peer_url", &peer.peer_url)?;
                dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
                Ok(Some(dict.into()))
            }
            None => Ok(None),
        }
    }

    /// Update peer certificate
    fn update_peer_certificate(&mut self, peer_id: &str, fingerprint: &str) -> PyResult<bool> {
        let updated = self.inner.update_peer_certificate(peer_id, fingerprint)?;
        Ok(updated)
    }

    /// Get certificates directory
    fn get_certs_dir(&self) -> PyResult<String> {
        let path = self.inner.certs_dir()?;
        Ok(path.to_string_lossy().to_string())
    }

    /// Get TUI colors
    fn get_tui_colors(&self, py: Python<'_>) -> PyResult<PyObject> {
        let (focused, unfocused) = self.inner.tui_colors();
        let dict = PyDict::new(py);
        dict.set_item("focused", focused)?;
        dict.set_item("unfocused", unfocused)?;
        Ok(dict.into())
    }

    /// Get warning color
    #[pyo3(signature = (theme="dark"))]
    fn get_warning_color(&self, theme: &str) -> &str {
        self.inner.warning_color(theme)
    }

    /// Get a config value
    #[pyo3(signature = (key, default=None))]
    fn get(&self, key: &str, default: Option<&str>) -> Option<String> {
        self.inner.get(key).or_else(|| default.map(String::from))
    }

    /// Set a config value
    fn set(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.set(key, value)?;
        Ok(())
    }

    /// Get sync config as dict
    fn get_sync_config(&self, py: Python<'_>) -> PyResult<PyObject> {
        let sync = self.inner.sync_config();
        let dict = PyDict::new(py);
        dict.set_item("enabled", sync.enabled)?;
        dict.set_item("server_port", sync.server_port)?;

        let peers_list = pyo3::types::PyList::empty(py);
        for peer in &sync.peers {
            let peer_dict = PyDict::new(py);
            peer_dict.set_item("peer_id", &peer.peer_id)?;
            peer_dict.set_item("peer_name", &peer.peer_name)?;
            peer_dict.set_item("peer_url", &peer.peer_url)?;
            peer_dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
            peers_list.append(peer_dict)?;
        }
        dict.set_item("peers", peers_list)?;

        Ok(dict.into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_default_config() {
        let temp_dir = TempDir::new().unwrap();
        let config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();

        assert!(!config.device_id_hex().is_empty());
        assert!(!config.device_name().is_empty());
        assert!(!config.is_sync_enabled());
        assert_eq!(config.sync_server_port(), 8384);
    }

    #[test]
    fn test_add_peer() {
        let temp_dir = TempDir::new().unwrap();
        let mut config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();

        let peer_id = "0".repeat(32);
        config
            .add_peer(&peer_id, "Test Peer", "https://example.com:8384", None, false)
            .unwrap();

        let peer = config.get_peer(&peer_id).unwrap();
        assert_eq!(peer.peer_name, "Test Peer");
        assert_eq!(peer.peer_url, "https://example.com:8384");
    }

    #[test]
    fn test_remove_peer() {
        let temp_dir = TempDir::new().unwrap();
        let mut config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();

        let peer_id = "0".repeat(32);
        config
            .add_peer(&peer_id, "Test Peer", "https://example.com:8384", None, false)
            .unwrap();

        let removed = config.remove_peer(&peer_id).unwrap();
        assert!(removed);
        assert!(config.get_peer(&peer_id).is_none());
    }

    #[test]
    fn test_invalid_peer_id() {
        let temp_dir = TempDir::new().unwrap();
        let mut config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();

        let result = config.add_peer("invalid", "Test", "https://example.com", None, false);
        assert!(result.is_err());
    }

    #[test]
    fn test_config_persistence() {
        let temp_dir = TempDir::new().unwrap();

        {
            let mut config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();
            config.set_device_name("Test Device").unwrap();
            config.set_sync_enabled(true).unwrap();
        }

        {
            let config = Config::new(Some(temp_dir.path().to_path_buf())).unwrap();
            assert_eq!(config.device_name(), "Test Device");
            assert!(config.is_sync_enabled());
        }
    }
}
