"""The words of the Issues view (ISSUE-1), from the data the core returns."""

from __future__ import annotations

from src.core.issues_text import issue_sections, place_label, size_words
from src.core.models import UUID_SHORT_LEN

HERE = "01a09526bbbb70808f15a84d31aaa8d2"
PHONE = "01a0952602bc70808f15a84d31aaa8d2"


def test_sizes_read_as_people_read_them():
    assert size_words(None) == "size unknown"
    assert size_words(900) == "900 bytes"
    assert size_words(2048) == "2 KB"
    assert size_words(5 * 1024 * 1024) == "5.0 MB"
    assert size_words(3 * 1024 ** 3) == "3.0 GB"


def test_places_are_named_the_bucket_this_device_or_by_name():
    names = {PHONE: "הטלפון של דותן"}
    assert place_label("cloud", names, HERE) == "the bucket"
    assert place_label(HERE, names, HERE) == "this device"
    assert place_label(PHONE, names, HERE) == "הטלפון של דותן"
    unknown = "01a09526dddd70808f15a84d31aaa8d2"
    assert place_label(unknown, names, HERE) == unknown[:UUID_SHORT_LEN], "the project's short id"


def test_every_kind_of_issue_has_its_section_and_empty_kinds_are_left_out():
    issues = {
        "max_upload_bytes": 100 * 1024 * 1024,
        "recordings_not_in_cloud": [
            {"audio_id": "a" * 32, "filename": "הרצאה.wav", "size_bytes": 300 * 1024 * 1024, "reason": "too_large", "held_by": [HERE]},
            {"audio_id": "b" * 32, "filename": "פתק.m4a", "size_bytes": 1000, "reason": "waiting_for_upload", "held_by": [PHONE, HERE]},
            {"audio_id": "c" * 32, "filename": "אבד.3gp", "size_bytes": None, "reason": "no_copy_known", "held_by": []},
            {"audio_id": "d" * 32, "filename": "בלי דלי.ogg", "size_bytes": 10, "reason": "no_bucket", "held_by": [HERE]},
        ],
        "orphaned_transcriptions": [{"transcription_id": "e" * 32, "audio_file_id": "f" * 32, "content_start": "שלום"}],
        "orphaned_attachments": [{"attachment_id": "1" * 32, "note_id": "2" * 32, "target_id": "3" * 32, "attachment_type": "audio_file", "note_missing": True, "target_missing": True}],
        "orphaned_recordings": [],
        "tags_with_whitespace": [{"tag_id": "4" * 32, "name": "פגישת צוות", "path": "עבודה/פגישת צוות"}],
        "count": 7,
    }
    sections = dict(issue_sections(issues, {PHONE: "הטלפון"}, HERE))
    assert list(sections) == [
        "Recordings not in cloud storage (4)",
        "Transcriptions whose recording is not there (1)",
        "Attachments whose note or recording is not there (1)",
        "Tags whose names contain spaces (1)",
    ], "a kind with nothing in it has no section"
    lines = sections["Recordings not in cloud storage (4)"]
    assert lines[0] == "הרצאה.wav (300.0 MB): larger than the account's upload limit of 100.0 MB"
    assert lines[1] == "פתק.m4a (1000 bytes): waiting for הטלפון, this device to upload it"
    assert lines[2] == "אבד.3gp (size unknown): no device and no bucket is known to hold it"
    assert lines[3] == "בלי דלי.ogg (10 bytes): no bucket is set up for the account"
    short = lambda digit: digit * UUID_SHORT_LEN
    assert sections["Attachments whose note or recording is not there (1)"] == [f"Attachment {short('1')}: its note {short('2')} and its recording {short('3')} is not there"]
    assert sections["Tags whose names contain spaces (1)"] == ["עבודה/פגישת צוות"]


def test_nothing_to_report_is_no_sections():
    empty = {"max_upload_bytes": 1, "recordings_not_in_cloud": [], "orphaned_transcriptions": [], "orphaned_attachments": [], "orphaned_recordings": [], "tags_with_whitespace": [], "count": 0}
    assert issue_sections(empty, {}, HERE) == []
