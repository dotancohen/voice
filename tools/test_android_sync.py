#!/usr/bin/env python3
"""
Cross-platform integration test for Voice <-> Android sync.

This script:
1. Starts a Voice sync server on the host
2. Sets up port forwarding to the Android emulator
3. Triggers sync operations on Android via adb
4. Verifies data synchronization

Prerequisites:
- Android emulator running with VoiceAndroid app installed
- adb in PATH
- Voice Python environment activated

Usage:
    python tools/test_android_sync.py
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config import Config
from core.database import Database


class AndroidSyncTest:
    """Test sync between Voice (Python) and Android."""

    def __init__(self):
        self.server_process = None
        self.temp_dir = None
        self.db = None
        self.config = None
        self.server_port = 54399  # Use unique port to avoid conflicts

    def setup(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp(prefix="voice_android_test_")
        db_path = Path(self.temp_dir) / "test.db"
        config_dir = Path(self.temp_dir)

        self.db = Database(str(db_path))
        self.config = Config(config_dir)

        print(f"Test directory: {self.temp_dir}")
        print(f"Device ID: {self.config.device_id_hex}")

    def start_server(self):
        """Start the Voice sync server."""
        print(f"Starting Voice server on port {self.server_port}...")

        env = os.environ.copy()
        env["VOICE_DB_PATH"] = str(Path(self.temp_dir) / "test.db")
        env["VOICE_CONFIG_DIR"] = self.temp_dir

        self.server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "core.sync",
                "serve",
                "--port",
                str(self.server_port),
            ],
            cwd=Path(__file__).parent.parent / "src",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        time.sleep(2)

        if self.server_process.poll() is not None:
            stdout, stderr = self.server_process.communicate()
            raise RuntimeError(
                f"Server failed to start:\n{stdout.decode()}\n{stderr.decode()}"
            )

        print("Server started successfully")

    def stop_server(self):
        """Stop the Voice sync server."""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            print("Server stopped")

    def setup_port_forwarding(self):
        """Set up adb port forwarding to emulator."""
        print(f"Setting up port forwarding: adb reverse tcp:{self.server_port} tcp:{self.server_port}")
        result = subprocess.run(
            ["adb", "reverse", f"tcp:{self.server_port}", f"tcp:{self.server_port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to set up port forwarding: {result.stderr}")
        print("Port forwarding established")

    def remove_port_forwarding(self):
        """Remove adb port forwarding."""
        subprocess.run(
            ["adb", "reverse", "--remove", f"tcp:{self.server_port}"],
            capture_output=True,
        )
        print("Port forwarding removed")

    def check_emulator(self):
        """Check if Android emulator is running."""
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
        )
        if "emulator" not in result.stdout and "device" not in result.stdout.split("\n")[1]:
            raise RuntimeError("No Android emulator/device found. Start an emulator first.")
        print("Android emulator/device detected")

    def create_test_data(self):
        """Create test data on the Voice server."""
        print("Creating test data on Voice server...")

        # Create notes
        note1_id = self.db.create_note("Note from desktop - sync test 1")
        note2_id = self.db.create_note("Note from desktop - sync test 2")

        # Create tags
        tag1_id = self.db.create_tag("DesktopTag1", None)
        tag2_id = self.db.create_tag("DesktopTag2", None)

        # Associate tags
        self.db.add_tag_to_note(note1_id, tag1_id)
        self.db.add_tag_to_note(note2_id, tag2_id)

        print(f"Created notes: {note1_id}, {note2_id}")
        print(f"Created tags: {tag1_id}, {tag2_id}")

        return {
            "notes": [note1_id, note2_id],
            "tags": [tag1_id, tag2_id],
        }

    def run_android_tests(self):
        """Run Android instrumented tests."""
        print("Running Android instrumented tests...")

        result = subprocess.run(
            [
                "./gradlew",
                "connectedAndroidTest",
                "-Pandroid.testInstrumentationRunnerArguments.class=com.dotancohen.voiceandroid.SyncIntegrationTest",
            ],
            cwd=Path(__file__).parent.parent.parent / "VoiceAndroid",
            capture_output=True,
            text=True,
        )

        print(result.stdout)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            return False

        return True

    def verify_sync_via_adb(self):
        """Verify sync by querying Android app database via adb."""
        print("Verifying sync via adb...")

        # This would need app-specific implementation to query the database
        # For now, just check if the app is responding
        result = subprocess.run(
            [
                "adb",
                "shell",
                "am",
                "broadcast",
                "-a",
                "com.dotancohen.voiceandroid.SYNC_STATUS",
            ],
            capture_output=True,
            text=True,
        )
        print(f"Broadcast result: {result.stdout}")
        return True

    def run(self):
        """Run the full integration test."""
        try:
            print("=" * 60)
            print("Voice <-> Android Sync Integration Test")
            print("=" * 60)

            self.setup()
            self.check_emulator()
            self.start_server()
            self.setup_port_forwarding()

            test_data = self.create_test_data()

            # Run Android tests
            if self.run_android_tests():
                print("\n" + "=" * 60)
                print("SUCCESS: Android tests passed")
                print("=" * 60)
            else:
                print("\n" + "=" * 60)
                print("FAILED: Android tests failed")
                print("=" * 60)
                return 1

            return 0

        except Exception as e:
            print(f"\nERROR: {e}")
            return 1

        finally:
            self.remove_port_forwarding()
            self.stop_server()
            if self.temp_dir:
                print(f"Test files remain at: {self.temp_dir}")


def main():
    """Main entry point."""
    test = AndroidSyncTest()
    sys.exit(test.run())


if __name__ == "__main__":
    main()
