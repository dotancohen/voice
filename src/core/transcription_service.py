"""Transcription service for Voice.

This module provides async transcription capabilities using VoiceTranscription.
It handles creating pending records, running transcription in background threads,
and updating records when complete.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for managing async transcription operations.

    This service:
    1. Creates "Pending..." records in the database immediately
    2. Runs transcription in background threads
    3. Updates database records when complete
    4. Calls completion/error callbacks for UI updates
    """

    def __init__(self, database: Any, audiofile_dir: Path) -> None:
        """Initialize the transcription service.

        Args:
            database: Database instance for storing transcriptions
            audiofile_dir: Directory containing audio files
        """
        self.database = database
        self.audiofile_dir = audiofile_dir
        self._active_tasks: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def transcribe_async(
        self,
        audio_file_id: str,
        provider_config: Dict[str, Any],
        on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """Start an async transcription.

        Creates a pending record immediately and starts transcription in background.

        Args:
            audio_file_id: Audio file UUID hex string
            provider_config: Provider configuration dict with keys:
                - provider_id: Provider identifier (e.g., "local_whisper")
                - model: Model name or path
                - language: Optional language hint
                - speaker_count: Optional speaker count
            on_complete: Callback(transcription_id, result) when complete
            on_error: Callback(transcription_id, error_message) on failure

        Returns:
            Transcription ID (hex string)
        """
        # Get audio file info
        audio_file = self.database.get_audio_file(audio_file_id)
        if not audio_file:
            raise ValueError(f"Audio file not found: {audio_file_id}")

        # Create pending record
        pending_content = f"Pending... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        service_name = provider_config.get("provider_id", "unknown")
        service_args = json.dumps(provider_config)

        transcription_id = self.database.create_transcription(
            audio_file_id=audio_file_id,
            content=pending_content,
            service=service_name,
            content_segments=None,
            service_arguments=service_args,
            service_response=None,
        )

        logger.info(
            f"Created pending transcription {transcription_id} for audio file {audio_file_id}"
        )

        # Start background thread
        thread = threading.Thread(
            target=self._run_transcription,
            args=(
                transcription_id,
                audio_file_id,
                audio_file["filename"],
                provider_config,
                on_complete,
                on_error,
            ),
            daemon=True,
        )

        with self._lock:
            self._active_tasks[transcription_id] = thread

        thread.start()

        return transcription_id

    def _run_transcription(
        self,
        transcription_id: str,
        audio_file_id: str,
        filename: str,
        provider_config: Dict[str, Any],
        on_complete: Optional[Callable[[str, Dict[str, Any]], None]],
        on_error: Optional[Callable[[str, str], None]],
    ) -> None:
        """Run transcription in background thread.

        Args:
            transcription_id: Transcription UUID hex string
            audio_file_id: Audio file UUID hex string
            filename: Audio filename
            provider_config: Provider configuration
            on_complete: Success callback
            on_error: Error callback
        """
        try:
            start_time = time.time()

            # Build audio file path
            audio_path = self.audiofile_dir / filename

            # Import here to avoid circular imports and lazy loading
            from voice_transcription import TranscriptionClient, TranscriptionConfig

            # Get model path from config
            provider_id = provider_config.get("provider_id", "local_whisper")

            if provider_id != "local_whisper":
                raise ValueError(f"Unsupported provider: {provider_id}")

            # Resolve model path
            model_path = self._resolve_model_path(provider_config)
            if not model_path:
                raise ValueError("No model path configured")

            # Create client
            client = TranscriptionClient.with_local_whisper(model_path)

            # Build config
            config = TranscriptionConfig(
                language=provider_config.get("language"),
                speaker_count=provider_config.get("speaker_count"),
                model=provider_config.get("model"),
            )

            # Run transcription
            logger.info(f"Starting transcription for {filename} with {provider_id}")
            result = client.transcribe(str(audio_path), config)

            elapsed_time = time.time() - start_time

            # Build segments JSON
            segments = []
            for seg in result.segments:
                segments.append({
                    "text": seg.text,
                    "start_seconds": seg.start_seconds,
                    "end_seconds": seg.end_seconds,
                    "speaker": seg.speaker,
                    "confidence": seg.confidence,
                })

            # Build service response
            service_response = json.dumps({
                "elapsed_time": round(elapsed_time, 3),
                "duration_seconds": result.duration_seconds,
                "languages": result.languages,
                "confidence": result.confidence,
                "speaker_count": result.speaker_count,
                "segment_count": len(result.segments),
            })

            # Update database
            self.database.update_transcription(
                transcription_id=transcription_id,
                content=result.content,
                content_segments=json.dumps(segments) if segments else None,
                service_response=service_response,
            )

            logger.info(
                f"Completed transcription {transcription_id} in {elapsed_time:.1f}s"
            )

            # Call completion callback
            if on_complete:
                result_dict = {
                    "content": result.content,
                    "segments": segments,
                    "duration_seconds": result.duration_seconds,
                    "languages": result.languages,
                    "elapsed_time": elapsed_time,
                }
                try:
                    on_complete(transcription_id, result_dict)
                except Exception as e:
                    logger.error(f"Error in completion callback: {e}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Transcription failed for {transcription_id}: {error_msg}")

            # Update database with error
            self.database.update_transcription(
                transcription_id=transcription_id,
                content=f"Error: {error_msg}",
                content_segments=None,
                service_response=json.dumps({"error": error_msg}),
            )

            # Call error callback
            if on_error:
                try:
                    on_error(transcription_id, error_msg)
                except Exception as cb_e:
                    logger.error(f"Error in error callback: {cb_e}")

        finally:
            # Remove from active tasks
            with self._lock:
                self._active_tasks.pop(transcription_id, None)

    def _resolve_model_path(self, provider_config: Dict[str, Any]) -> Optional[str]:
        """Resolve the model path from provider config.

        Args:
            provider_config: Provider configuration

        Returns:
            Model path string or None
        """
        # Check for explicit model_path first
        if "model_path" in provider_config and provider_config["model_path"]:
            return provider_config["model_path"]

        # Try to resolve model name to path
        model_name = provider_config.get("model", "base")

        # Common model locations
        search_dirs = [
            Path.home() / ".local" / "share" / "whisper",
            Path.home() / ".cache" / "whisper",
            Path("/usr/share/whisper"),
            Path("/usr/local/share/whisper"),
        ]

        for search_dir in search_dirs:
            model_file = search_dir / f"ggml-{model_name}.bin"
            if model_file.exists():
                return str(model_file)

        return None

    def get_active_transcriptions(self) -> List[str]:
        """Get list of active transcription IDs.

        Returns:
            List of transcription ID hex strings
        """
        with self._lock:
            return list(self._active_tasks.keys())

    def is_transcribing(self, transcription_id: str) -> bool:
        """Check if a transcription is still in progress.

        Args:
            transcription_id: Transcription UUID hex string

        Returns:
            True if transcription is in progress
        """
        with self._lock:
            return transcription_id in self._active_tasks
