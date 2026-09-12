# Bugs the tests missed

Every bug listed here happened in code that had tests. The tests ran, they
were green (or their failure was being ignored), and the bug shipped anyway.
Each entry says what broke, what the user saw, why the tests did not catch
it, and the rule that would have caught it. The rules are collected at the
end.

This document is about our own testing, not about the features. The features
are described in `README.md`, `SYNC_SPECIFICATION.md` and the Android
`README.md`.

---

## 1. Merging notes failed every time, and nobody was told

**What broke.** `merge_notes` in `voicecore/src/database.rs` read the note's
`created_at` and `deleted_at` as text:

```rust
let note_1: (String, String, Option<String>) = self.conn.query_row(
    "SELECT created_at, content, deleted_at FROM notes WHERE id = ?", ...)
    .map_err(|_| VoiceError::validation("note_id_1", "Note not found"))?;
```

Those columns hold whole seconds since the epoch, as integers. SQLite
refused the conversion, `query_row` returned a type error, and the `map_err`
turned every possible error into the words "Note not found". Merging notes
on the phone and `notes-merge` on the desktop could never work.

**What the user saw.** Selecting two notes and pressing Merge appeared to do
nothing at all.

**Why "silently".** Nothing swallowed the error on purpose; every caller
dropped it in a different way:

- the fleet test harness called it as `let _ = self.dbs[d].merge_notes(&a, &b);`,
  so the failure was discarded by the test that was meant to exercise it;
- the Android view model logged the error and left the screen unchanged;
- the desktop printed the message, but no test ran that command. There is
  one now (`tests/cli/test_cli_merge.py`), and writing it found a second
  gap: the command-line tests only see the test database when a
  `config.json` names it, so a test without one would have passed against
  an empty database.

So the operation never happened, and no layer said so out loud.

**Why the tests missed it.** There were thirty-six tests about time handling
and a randomised fleet test that merged notes on every run. The time tests
all wrote and read timestamps through the versioned-field code, which uses
integers correctly; none of them went through `merge_notes`. The fleet test
did call it, and threw the answer away.

**Rules.** [R1](#r1-never-discard-a-result-in-a-test) ·
[R2](#r2-assert-what-the-operation-produced-not-that-it-did-not-crash) ·
[R11](#r11-an-error-message-must-say-what-actually-went-wrong)

---

## 2. A failing test was hiding inside a pile of failing tests

**What broke.** `TestMergeNotes` was failing, correctly, the whole time. It
was one of a set of about sixty-six failures that we had agreed to treat as
"pre-existing" while working on something else.

**What the user saw.** The merge bug above, in production, while the test
that proved it existed was running red on every commit.

**Why the tests missed it.** They did not. We did. A suite with sixty-six
known failures cannot report a sixty-seventh.

**Rules.** [R3](#r3-the-suite-is-green-or-the-suite-is-broken) ·
[R4](#r4-quarantine-one-test-at-a-time-strictly-and-with-a-reason)

---

## 3. A test that had quietly started passing

**What broke.** `test_update_transcription_rebuilds_cache` was marked
`@pytest.mark.xfail(reason="update_transcription doesn't rebuild cache for
attached notes yet")`. The cache rebuild was implemented at some point and
the test began passing. Because the mark was not strict, the suite reported
`1 xpassed` and stayed green.

**What the user saw.** Nothing yet. This is a bug waiting to happen: if the
rebuild breaks again, the suite will report `1 xfailed` and stay green.

**Rules.** [R4](#r4-quarantine-one-test-at-a-time-strictly-and-with-a-reason)

---

## 4. Every note created over ADB lost all but its first word

**What broke.** `tools/voice-adb` built commands like

```
adb shell am broadcast -a com.dotancohen.voiceandroid.ADB --es text פתק עם מילים
```

The text was quoted on the workstation, the local shell removed the quotes,
and the phone's shell split what arrived on spaces. Android received
`text=פתק` and three stray arguments.

**What the user saw.** Notes created through the automation tool contained
one word.

**Why the tests missed it.** The Kotlin tests called the broadcast receiver
directly with a string in hand, which is the one thing that cannot go wrong.
Nothing ran the tool the way a person runs it, and the sample texts were
single words.

**Rules.** [R5](#r5-test-through-the-transport-the-user-uses) ·
[R6](#r6-fixture-text-is-several-hebrew-words-not-one-ascii-word)

---

## 5. Attachments could disagree about which note they belong to

**What broke.** Two devices moved the same attachment to different notes at
the same second. The upsert in `apply_sync_note_attachment` compared
`modified_at` with `>=`, so each device kept whatever arrived last, and the
loser was never told: the winner had nothing new to send, so the two
databases stayed different for ever.

**Why the tests missed it.** An attachment changes which note it belongs to
in exactly one way: a merge. Merging was broken (bug 1), so no attachment in
any run had ever changed note, and the upsert that decides between two
claims on the same attachment had never had two claims to decide between.
The randomised test went on generating merge operations, went on passing,
and covered nothing there. The bug appeared within minutes of fixing the
merge, on seed 408.

**The fix.** A deterministic tie-break (`modified_at`, then the smaller
`note_id`) plus `republish()`, which bumps the row's sequence number so the
device that lost the tie sends its copy onward and both sides converge.

**What the harness does now.** Every run counts the operations that actually
took effect (notes created, merges, tag links added and removed, tag moves,
attachments), and each test asserts at the end that none of those counts is
zero. Removing a tag also picks a tag the note really has: picking at random
almost never named one, so that path was reached about as often as the
broken merge was. The counting is in `Fleet::note_effect` and
`assert_operations_covered`.

**Rules.** [R7](#r7-a-randomised-test-must-prove-that-its-operations-did-something) ·
[R1](#r1-never-discard-a-result-in-a-test)

---

## 6. Adding two columns broke reading the sync feed

**What broke.** `get_versions_after_seq` read the sequence number with
`row.get::<_, Option<i64>>(14)`. Adding the two timezone columns to
`VERSION_COLUMNS` moved `seq` to index 16, so the feed read a timezone
offset as a sequence number.

**Why the tests missed it.** Nothing missed it: the fleet tests caught it
immediately. It is here because the fix is a rule, not a patch: positional
column access is a defect waiting for the next column.

**Rules.** [R10](#r10-name-columns-do-not-count-them)

---

## 7. An impossible timezone offset crashed the formatters

**What broke.** A record carrying an offset of, say, 200 hours (corrupt
data, or a peer with a bug) made `format_timestamp` in Python raise
`ValueError`, and would have made the Kotlin formatter throw
`DateTimeException`.

**Why the tests missed it.** The timezone tests covered real zones, half-hour
and quarter-hour offsets, both ends of the map, the hour that happens twice
and the hour that never happens. Every one of those is a *valid* input. No
test passed a value that cannot exist.

**The fix.** Both formatters fall back to the reader's own zone when the
offset is not a possible one, and both have a test that says so.

**Rules.** [R8](#r8-test-the-inputs-that-cannot-happen)

---

## 8. Timestamps displayed in UTC on the phone

**What broke.** The phone showed times three hours earlier than the clock on
the wall, because the strings were formatted in Rust, which had no idea what
zone the phone was in.

**Why the tests missed it.** The tests asserted that the formatter returned
what the formatter returns: they built a timestamp, formatted it, and
compared against a string built the same way. A test written in the shape of
the implementation agrees with the implementation no matter what either of
them does.

**The fix.** `Stamp { at, offset, zone }` crosses the binding, and the
platform renders it. The tests now assert a literal expected string
("2026-09-08 15:20") computed by hand from a known instant and a known
offset.

**Rules.** [R9](#r9-compute-the-expected-value-independently-of-the-code)

---

## 9. A second, English transcription appeared beside the Hebrew one

**What broke.** Some Hebrew recordings ended up with two transcriptions, the
second one translated into English, because of the language argument handed
to Whisper.

**Why the tests missed it.** The transcription tests checked that a
transcription record was created, updated and stored with its service
arguments. None of them asserted anything about the language actually
requested, and none ran two transcriptions of one recording.

**Rules.** [R2](#r2-assert-what-the-operation-produced-not-that-it-did-not-crash) ·
[R12](#r12-test-the-second-one)

---

## 10. Sync tests that described a design we no longer have

**What broke.** Nothing in the product. `tests/unit/test_sync.py` contained
four tests that sent a bare entity row from a "peer" and expected a conflict
to be recorded and both texts to be kept. Under the versioned design a row
is only a hint: the value travels as a version, and a row whose content
differs from the head is ignored (`SYNC_SPECIFICATION.md`, VER-4). The tests
were asserting the rules of a design that had been replaced.

**Why this is dangerous.** A stale test that fails is noise, and noise is
what let bug 2 hide. A stale test that passes is worse: it is a false
statement about the system, written down and trusted.

**The fix.** Those tests now use a second real `Database` as the peer and
exchange changes through `get_changes_since` / `apply_sync_changes`, which
is what a real device does. They cover the delete-versus-edit conflict from
both sides, the delete that travels because nobody edited, and the second
delete that is obeyed because the user has now seen the edit.

**Rules.** [R13](#r13-prefer-a-real-peer-to-a-hand-built-payload) ·
[R14](#r14-when-a-rule-changes-rewrite-the-tests-that-encode-the-old-one)

---

## 11. A boundary test that tested nothing

**What broke.** `test_long_content_truncated` created a note of exactly 200
characters and expected it to be truncated. The limit is 200, so nothing was
truncated. The test had been written when the limit was 100, and the Rust
doc comment still said "first 100 characters" long after the code took 200.

**The fix.** The test imports `CONTENT_TRUNCATE_LENGTH` from the pane, uses
`limit + 50` for the truncated case, and a second test uses exactly `limit`
and asserts that the text is shown whole. The stale comments were corrected.

**Rules.** [R15](#r15-take-the-constant-from-the-code-and-test-both-sides-of-the-boundary)

---

## 12. Interrupted transcriptions were never tested at all

**What broke.** When the phone kills the app in the middle of a
transcription, the "Pending..." record stays pending for ever. The sweep
that turns it into "Error: the app was closed before the transcription
finished" was written without a test, and the case where the recording is
then transcribed successfully, leaving the note showing an error next to a
good transcription, had never been considered.

**The fix.** The placeholder is deleted once the recording really has been
transcribed (`voicecore/src/android.rs::a_deleted_transcription_leaves_only_the_good_one`
and `OnDeviceTranscriberTest`, which says which rows count as placeholders
and which failures the user still has to see). The transcription runs under
a foreground service that survives the app being closed, and a job that
cannot get a service now waits in the queue instead of starting work in a
process Android is about to freeze: nothing is written to the database until
the work really begins, so an interrupted attempt leaves nothing behind at
all.

**Rules.** [R16](#r16-write-a-test-for-the-interruption-not-only-for-the-happy-path)

---

---

## 13. A purge that removed different things on different devices

**What broke.** Nothing shipped: the fleet tests caught it within a minute of
the trash bin's "delete for good" being written. It is here because of how it
was caught and what it says about the rule.

The first version removed a purged note's attachments with
`DELETE FROM note_attachments WHERE note_id = <the purged note>`. That reads
the note each attachment points at *now*. An attachment moves between notes:
that is what merging does. A device that had already applied the merge no
longer had the attachment on the purged note and kept it; a device that had
not applied it yet removed it. The two databases could then never agree
again, which is the one thing this system may not do.

**Why the ordinary tests would not have found it.** Every unit test of the
purge passed: on one device, with no merges in flight, the code did exactly
what it said. It took two devices, a merge, and an unlucky order of arrival,
which is what the randomised fleet test generates by construction.

**The rule that came out of it.** A destructive operation may cascade only
along relationships that never move (a tag link belongs to its note for ever;
a transcription to its recording), and everything else must be removed **by
name**, from a list that travels. Anything a receiver decides for itself, on
information the sender did not have, is a divergence waiting for the right
order of arrival.

**Rules.** [R7](#r7-a-randomised-test-must-prove-that-its-operations-did-something) ·
[R12](#r12-test-the-second-one)

---

# The rules

### R1. Never discard a `Result` in a test

`let _ = db.merge_notes(&a, &b);` in a test harness is a bug. If an
operation is allowed to fail in a random test, count the failures and assert
something about the count; do not throw the answer away. In Python,
`assert errors == []` beside every apply.

### R2. Assert what the operation produced, not that it did not crash

A test that calls a function and then checks nothing has tested that the
process is still alive. After a merge: both texts are in the surviving note,
the attachment now belongs to it, the other note is deleted.

### R3. The suite is green, or the suite is broken

There is no third state. A count of "known failures" is a place for new
failures to hide, and it hid one for weeks. Fix, delete, or quarantine.

### R4. Quarantine one test at a time, strictly, and with a reason

`@pytest.mark.xfail(strict=True, reason="...", ...)`. Strict, so that the
day it starts passing the suite tells you. With a reason and a date, so that
the quarantine is a decision and not a habit.

### R5. Test through the transport the user uses

Calling a broadcast receiver directly proves the receiver works. It says
nothing about the two shells, the ADB argument parser and the quoting rules
between the user's keyboard and that function. At least one test per tool
must run the tool.

The same test must also prove it is looking at the right data. A
command-line test that starts a subprocess against the wrong database
directory passes on an empty database and asserts nothing; assert that
something the test created is visible before asserting what the command did
to it.

### R6. Fixture text is several Hebrew words, not one ASCII word

Single-word ASCII fixtures pass through every broken quoting, splitting,
encoding and bidirectional-text path in the system. Hebrew catches encoding
and direction; several words catch quoting and splitting; the two together
have now caught both classes of bug in this project.

### R7. A randomised test must prove that its operations did something

A fleet test that generates merges is worth nothing if every merge fails.
Count each kind of operation that actually took effect and assert that the
counts are not zero across the test. A silent no-op removes a region of the
state space from every seed, and the test still passes.

Count across the whole test, not one seed: sixty random steps may never
happen to hold two notes at once, and a per-seed assertion would then fail
for the wrong reason. Counting also shows which paths are barely reached:
removing a tag chosen at random almost never named a tag the note had, so
that operation had been running thousands of times without once removing
anything.

### R8. Test the inputs that cannot happen

An offset of 200 hours, a negative duration, a timestamp before the epoch, a
UUID that is not hex, a JSON number where a string belongs. Corrupt and
hostile inputs arrive from peers, from files edited by hand, and from our
own older versions. "Valid input, every corner" is only half the job.

### R9. Compute the expected value independently of the code

If the expected value is produced by the same function, in the same way, the
test is a mirror. Write the literal: `"2026-09-08 15:20"`, `10800`,
`"Asia/Jerusalem"`. A literal is checkable by a person reading the test.

### R10. Name columns, do not count them

`row.get::<_, Option<i64>>(14)` breaks the day a column is added, and it
breaks quietly, reading the wrong value rather than failing. Select the
columns you want by name and read them by name.

### R11. An error message must say what actually went wrong

`.map_err(|_| VoiceError::validation("note_id_1", "Note not found"))` threw
away a type error and reported a missing row, and that is what made the bug
survive. Keep the cause: `format!("Note not found: {e}")`.

### R12. Test the second one

The second transcription of a recording, the second delete of a note, the
second device, the second sync of the same change, the second merge. Most of
these bugs live in the second one; almost every test in this repository used
to stop at the first.

### R13. Prefer a real peer to a hand-built payload

A dictionary written by hand in a test is what we *believe* a peer sends. It
stays believable long after it stops being true. Two real databases
exchanging changes through the real feed cannot drift from the protocol,
because they are the protocol.

### R14. When a rule changes, rewrite the tests that encode the old one

Changing a design rule (VER-4 made row values into hints) means finding
every test that asserts the old rule and rewriting it in the same commit.
Deleting one is allowed. Leaving one is not.

### R15. Take the constant from the code, and test both sides of the boundary

Import `CONTENT_TRUNCATE_LENGTH`; do not write 100 or 200 in the test. Then
test `limit` (whole) and `limit + something` (truncated). A test that uses
exactly the limit and expects truncation passes for years without testing
anything.

### R18. Test at the size the data really reaches

Every test of the waveform used a tenth of a second of audio. The user's
recordings run to eight hours. Between those two numbers is a factor of
300 000, and the code was linear in exactly that number.

For anything whose cost grows with the user's data — audio samples, file
bytes, notes, versions, log lines — write one test at the largest size that
is actually plausible, and make it prove the cost does *not* grow: a fixed
number of bars, a fixed number of bytes held, a bounded file. "It works on my
sample" is not a size test. Ask the user what their largest real case is; here
it was eight hours, and they told us the moment we asked.

### R17. Read it back through the other path

Every mutation has a reader that is not the writer: a cache, a list already on
screen, a search index, a view model that loaded once, the other application
after a sync. After changing something, write the test that reads it through
one of those. "The write returned true" is not evidence that anybody can see
the change.

### R16. Write a test for the interruption, not only for the happy path

The app is killed mid-transcription. The network dies mid-sync. The recorder
is interrupted by a call. Those are the states the user reports, and each of
them leaves a record behind that some later run has to tidy up. Test what is
left behind, and test what happens on the next run.


## 14. A renamed Tag went on showing its old name on every Note

**What broke.** Each Note keeps a cache of what its pane shows —
`di_cache_note_pane_display` — and that cache holds the *name* of every Tag on
the Note. Renaming a Tag wrote the new name into the `tags` table and left
every one of those caches alone. `versions.rs::apply_head_to_entity` rebuilds
a Note's caches when the Note's own fields change, and
`refresh_entity_caches` covers notes, note-tags, attachments, audio files and
transcriptions — but nothing at all when the entity written was a Tag.

**What the user saw.** They renamed a Tag and the old name stayed on their
Notes. Moving a Tag left the same stale copy. Only an unrelated edit to a
Note — adding another Tag, changing its text — brought the new name in, so
the application looked as though it had ignored the rename or lost it. On the
phone the Tag search kept showing the old list as well, because
`FilterViewModel` loads the Tags once when it is made and nothing asked it
again.

**Why the tests did not catch it.** `tests/unit/test_cache_rebuild.py` had
twenty tests, and every one of them changed the *Note*: its content, its
attachments, its transcriptions, the Tags attached to it. Not one changed the
*Tag itself* and then looked at the Note. The write was tested through the
writer's own path (`rename_tag` returns true, `get_tag` shows the new name)
and never read back through the other path, which is where the copy lived.

**The rule.** After a mutation, ask who else holds a copy of what changed, and
read it back through *their* path. A test that only asks the writer whether it
wrote is not a test of the feature; it is a test of the function.


## 15. The waveform kept every sample of the recording, and the phone died

**What broke.** `WaveformExtractor` decoded the whole recording into a
`MutableList<Short>` and then reduced it to 150 bars. A `List<Short>` boxes
every sample into an object of its own: about forty bytes for two bytes of
audio. A ten-minute recording is tens of millions of samples, so the list ran
to hundreds of megabytes against a heap of 256.

**What the user saw.** One Note playing, a second Note opened, and the
application vanished. `java.lang.OutOfMemoryError ... ArrayList.addAll` at
23:41 on 2026-09-10, found in the phone's crash buffer the next day. They had
also been reporting, separately, that waveforms often never appeared — the
same root: the work was redone on every visit and competed for one of the
phone's three hardware decoders.

**Why the tests did not catch it.** There were eleven tests of the waveform
code and every one of them used a convenient size: 1 500 samples, 15 000,
never more. The largest was a tenth of a second of audio. Nothing in the
suite ever asked what happens at the length the user's own recordings reach —
meetings of two hours, and a subject sleeping for eight.

**The rule.** Test at the size the data really reaches, not at the size that
is convenient to type. The same mistake was waiting in the desktop
application (`struct.unpack` of a whole recording: about a gigabyte for an
hour) and in its log file, which had no rotation and was read whole to show
its last thousand lines.

---

## What is checked now

| Bug | Test that would now catch it |
| --- | --- |
| 1. Merge failed | `database.rs::merging_two_notes_keeps_both_texts_and_moves_the_recording`, `merging_the_other_way_round_keeps_the_same_note`, and `tests/cli/test_cli_merge.py`, which runs the command a person runs |
| 3. Stale quarantine | mark removed; the test runs for real |
| 5. Attachment convergence | `convergence_tests.rs` (seed 408 reproduced it; merges now really run) |
| 7. Impossible offset | `an_impossible_offset_falls_back_instead_of_lying`, `an_offset_too_large_for_the_column_is_read_as_unknown`, and the Python and Kotlin equivalents |
| 8. UTC on the phone | `timezone_tests.rs` and `util/StampsTest.kt` assert literal wall-clock strings |
| 10. Stale sync design | `TestApplySyncChangesDeleteConflicts`, rewritten with a second real database |
| 11. Truncation boundary | `test_long_content_truncated`, `test_content_at_the_limit_is_not_truncated` |
| 12. Interrupted transcription | `android.rs::a_deleted_transcription_leaves_only_the_good_one` |
| 13. Divergent purge | `convergence_tests.rs` (purging is one of the random operations, and every run must perform one) |
| 15. Waveform held the recording | `WaveformAccumulatorTest` (Android) and `test_waveform_accumulator.py` (desktop), each feeding an hour of audio and asserting fixed memory and a fixed bar count |
| 14. Renamed Tag, stale Note | `test_cache_rebuild.py::TestCacheRebuildOnTagItselfChanging` — renaming, moving and deleting a Tag, each read back through the Note's cache |
