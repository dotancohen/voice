# Test plan 01: Syncing

Scope: notes, tags, synced settings, audio files and transcriptions moving between Desktop, Server and Android; conflicts; outages; large data; wrong clocks; version history.

Read `README.md` in this directory first. Every step says **where** to do it, **what** to type or tap, and what is **Expected**. Do the steps in order; later sections use notes created in earlier ones. If a step does not match its Expected line, stop, write down exactly what you saw (copy the text), and continue only if the plan says you may.

Estimated time: sections 0 to 2 about 3 hours; sections 3 to 7 about 4 hours.

---

## 0. Setup

### 0.1 What you need

- Desktop: a Linux computer with the Voice repository at `~/Projects/VoiceFamily/Voice` and the VoiceAndroid repository at `~/Projects/VoiceFamily/VoiceAndroid`, `adb` installed, and the Android phone connected by USB with USB debugging enabled.
- Server: a Linux computer you can reach with `ssh`. Its address is written in this plan as `SERVER`. Replace `SERVER` with the real address everywhere (for example `192.168.1.20`). Port 8384 on Server must be reachable from Desktop and from the phone (same Wi-Fi).
- An S3 bucket with an access key that can read and write it. Ask for: bucket name, region (or endpoint URL), access key id, secret access key.
- Six short audio files, a few seconds each, with Hebrew speech if possible. Name them exactly `desktop1.mp3`, `desktop2.mp3`, `desktop3.mp3`, `phone1.mp3`, `phone2.mp3`, `phone3.mp3` and put all six in `/home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest` on Desktop. (`.m4a` files are fine too; keep the same base names and use the real extension wherever the plan says `.mp3`.)

Folders used by this plan:

| Where | Folder | Meaning |
|-------|--------|---------|
| Desktop | `/home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest` | the permanent copies of all six test files; never import from here |
| Desktop | `/home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage` | plays the role of a voice recorder's storage; Voice imports from here |
| Desktop | `/home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/voice-audio` | where Voice keeps its own copies of audio files |
| Server | `/var/www/voice-testing/voice-audio` | where Voice keeps its audio files on Server |
| Android | `/storage/emulated/0/voice-testing/VoiceTest` | the permanent copies of `phone1.mp3`, `phone2.mp3`, `phone3.mp3` |
| Android | `/storage/emulated/0/voice-testing/VoiceTestStorage` | plays the role of the phone's voice recorder storage; Voice imports from here |

On the phone `/storage/emulated/0` is the same place as `/sdcard`; the plan always writes the long form.

The sync server speaks plain HTTP and has no login: anyone who can reach port 8384 can read and write everything. Use a private network. Section 8 lists what follows from this for the plans we will add later.

### 0.2 Prepare Desktop

Open a terminal on Desktop and run, one line at a time:

```bash
cd ~/Projects/VoiceFamily/Voice
git pull
git log -1 --format=%H          # write this commit hash on the results sheet
cd rust/voice-python && ../../.venv/bin/maturin develop --release && cd ../..
mkdir -p ~/.local/bin
ln -sf ~/Projects/VoiceFamily/Voice/bin/voice ~/.local/bin/voice
ln -sf ~/Projects/VoiceFamily/VoiceAndroid/tools/voice-adb ~/.local/bin/voice-adb
export PATH=~/.local/bin:$PATH
voice cli config show
```

Expected: the first line printed is `Using CONFIG_DIR: /home/<you>/.config/voice`, followed by `device_id = ...`, `device_name = ...` and the other keys.

If `voice: command not found`, run `export PATH=~/.local/bin:$PATH` again in this terminal; you must run it in every new terminal you open (or add it to `~/.bashrc`).

Now name the device and set its folders:

```bash
voice cli config set device_name Desktop
voice cli config set audiofile_directory /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/voice-audio
mkdir -p /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage
rm -f /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage/*
cp /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/desktop1.mp3 /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/desktop2.mp3 /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage/
ls /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage
voice cli config show
```

Expected: `ls` shows `desktop1.mp3` and `desktop2.mp3` (not `desktop3.mp3`: it is imported in 1.13). `config show` says `device_name = Desktop` and `audiofile_directory = /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/voice-audio`. Write the `device_id` value on the results sheet as *Desktop id*.

### 0.3 Prepare Server

```bash
ssh SERVER
cd ~/Projects/VoiceFamily/Voice
git pull
git log -1 --format=%H          # must be the same hash as on Desktop
cd rust/voice-python && ../../.venv/bin/maturin develop --release && cd ../..
mkdir -p ~/.local/bin
ln -sf ~/Projects/VoiceFamily/Voice/bin/voice ~/.local/bin/voice
export PATH=~/.local/bin:$PATH
voice cli config set device_name Server
voice cli config set audiofile_directory /var/www/voice-testing/voice-audio
voice cli config show
```

Expected: `device_name = Server`. Write the `device_id` value on the results sheet as *Server id*. You will type it on Desktop and on the phone, so copy it somewhere you can paste from.

### 0.4 Start the sync server on Server

Servers must keep running while you work elsewhere, so start it inside `tmux`:

```bash
ssh SERVER
tmux new -s voice
export PATH=~/.local/bin:$PATH
cd ~/Projects/VoiceFamily/Voice
voice cli sync serve --verbose
```

Expected: a line saying the server listens on `0.0.0.0:8384` and a line with the body limit (`100 MB`). Leave it running. To leave tmux without stopping the server press `Ctrl+B` then `D`. To come back later: `ssh SERVER` then `tmux attach -t voice`. This window is called **the server console** in the rest of the plan; you will be asked to read it.

Check from Desktop:

```bash
curl http://SERVER:8384/sync/status
```

Expected: one line of JSON containing `"protocol_version":"1.1"` and Server's device id.

### 0.5 Configure cloud storage (on Server only)

In a second SSH session to Server (not inside the tmux window):

```bash
ssh SERVER
export PATH=~/.local/bin:$PATH
cd ~/Projects/VoiceFamily/Voice
voice cli storage configure-s3 --bucket <bucket> --region <region> --access-key-id <id> --secret-access-key <secret> --prefix voice-test
voice cli storage status
```

Expected: `storage status` shows provider `s3`, the bucket and prefix `voice-test`. For an S3-compatible service add `--endpoint https://...` to the configure command. Do **not** configure storage on Desktop or Android: the test is that they receive it through sync.

### 0.6 Prepare the phone

Install the debug build. If the phone already has an older Voice build that was installed from a different computer, `adb install` fails with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`; in that case uninstall first (this deletes the phone's Voice data; that is fine on a test phone).

```bash
cd ~/Projects/VoiceFamily/VoiceAndroid
adb devices                      # the phone must be listed as "device", not "unauthorized"
adb uninstall com.dotancohen.voiceandroid   # only if the install below fails
adb install -r app/build/outputs/apk/debug/app-debug.apk
voice-adb ping
```

Expected: `adb install` prints `Success`; `voice-adb ping` prints `PING OK pong device=... id=...`. If it prints `ERROR no reply`, open the app once on the phone (it must have been started at least once), then run `voice-adb ping` again.

Grant storage access so the app can read `/storage/emulated/0/voice-testing/VoiceTestStorage`: on the phone open the app, tap **Settings → Import Audio Files**; if a **Storage Permission Required** notice appears tap **Grant** and allow "All files access" for Voice; press Back twice.

Put the phone's test files in place (from Desktop):

```bash
adb shell mkdir -p /storage/emulated/0/voice-testing/VoiceTest /storage/emulated/0/voice-testing/VoiceTestStorage
adb push /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/phone1.mp3 /storage/emulated/0/voice-testing/VoiceTest/
adb push /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/phone2.mp3 /storage/emulated/0/voice-testing/VoiceTest/
adb push /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/phone3.mp3 /storage/emulated/0/voice-testing/VoiceTest/
adb shell rm -f /storage/emulated/0/voice-testing/VoiceTestStorage/*
adb shell cp /storage/emulated/0/voice-testing/VoiceTest/phone1.mp3 /storage/emulated/0/voice-testing/VoiceTest/phone2.mp3 /storage/emulated/0/voice-testing/VoiceTestStorage/
adb shell ls /storage/emulated/0/voice-testing/VoiceTestStorage
```

Expected: `ls` shows exactly `phone1.mp3` and `phone2.mp3`. **Run these `rm` and `cp` lines again at the start of every future session**: earlier sessions may have left extra files or removed some.

Name the phone and point it at Server (paste the Server id you wrote down):

```bash
voice-adb set-device-name Android
voice-adb set-sync http://SERVER:8384 <server-id> Android
voice-adb status
```

Expected: `STATUS OK device=Android id=<32 hex characters> server=http://SERVER:8384 peer=<server-id> notes=0 ...`. Write the phone's id on the results sheet as *Android id*.

### 0.7 Connect Desktop to Server and do the first sync

```bash
voice cli sync add-peer <server-id> Server http://SERVER:8384
voice cli sync now
voice cli storage status
```

Expected: `sync now` prints `Sync with <server-id> completed:` with `Pulled:` greater than 0, `Pushed:` a number, and no `Errors:` line. `storage status` on Desktop now shows the S3 configuration that came from Server, although you never configured it on Desktop.

Then the phone:

```bash
voice-adb sync-now
```

Expected: `SYNC_NOW OK success received=<number greater than 0> sent=<number>`. On the server console you see lines for the phone: a handshake, `GET /sync/changes cursor=0`, `POST /sync/apply`.

### 0.8 How to read things during the tests

- **Desktop or Server, list notes:** `voice cli notes-list` prints one note per line: `<id> | <created> | <first line of the note>`. To find one note's id, filter by its first line, for example `voice cli notes-list | grep "פתק ראשון מהמחשב"`; the id is the 32-character text at the start of that line. Anywhere the plan says `<id of X>` do this with the first line X.
- **Desktop or Server, show a note:** `voice cli note-show <id>`. The first 8 characters of an id are enough for every `voice cli` command.
- **Desktop or Server, list tags:** `voice cli tags-list` shows every tag with its id.
- **Android, list notes:** `voice-adb list-notes` prints one line per note like `NOTE {"id":"...","first_line":"...","tags":[...],"conflicts":[...],"media":[{"audio_id":"...","filename":"...","state":"local"}]}`. The media `state` is one of `local` (file is on the phone), `in_cloud_not_downloaded`, `not_uploaded_yet`.
- **Android, show a note:** `voice-adb show-note "<first line of the note>"`. You may also give the id. Every `voice-adb` command that takes a note accepts either.
- **Android, open the app on a screen** (for steps done by hand): `voice-adb open notes`, `voice-adb open settings`, `voice-adb open sync`, `voice-adb open tags`, `voice-adb open import`, `voice-adb open-note "<first line>"`.
- **Server TUI:** in the second SSH session run `voice tui`; move with the arrow keys, `q` quits. Do not run the TUI inside the tmux window that holds the server.
- **Logs:** Desktop and Server write `~/.config/voice/voice.log`. The server console shows every request. Android: `voice-adb log` prints the app's last automation lines; the app's own log is under **Settings → View Log**.

### 0.9 The three-way sync

Many steps say **do the three-way sync**. It always means these four commands, in this order, and every one of them must succeed:

```bash
voice cli sync now          # Desktop pushes to Server and pulls from Server
voice-adb sync-now          # the phone pushes to Server and pulls from Server
voice cli sync now          # Desktop pulls what the phone just sent
voice-adb sync-now          # the phone pulls anything Desktop's second sync sent
```

Expected every time: Desktop prints `completed:` with no `Errors:` line; `voice-adb` prints `SYNC_NOW OK success ...`. Server needs no command: it is the hub, its database is updated by the others' syncs.

---

## 1. Everyday syncing

### 1.1 A note from Desktop reaches everyone

```bash
voice cli note-create "פתק ראשון מהמחשב"
voice cli sync now
voice-adb sync-now
voice-adb list-notes
```

Expected: `list-notes` prints one `NOTE` line whose `first_line` is `פתק ראשון מהמחשב`. On Server, in the second SSH session, `voice cli notes-list` shows the same note. The server console shows a `POST /sync/apply` from Desktop and then a `GET /sync/changes` from the phone.

### 1.2 A note from Android reaches Desktop through Server

```bash
voice-adb create-note "פתק מהטלפון"
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep "פתק מהטלפון"
```

Expected: the `grep` prints one line ending with `פתק מהטלפון`. Desktop never talked to the phone: Server relayed the note.

### 1.3 Edit on one device, see it everywhere

On Desktop start the GUI:

```bash
voice gui
```

In the GUI: click the note `פתק ראשון מהמחשב` in the list on the left, click **Edit**, click at the end of the text, press Enter, type `שורה שנייה`, click **Save**. Close the GUI. Then:

```bash
voice cli note-show $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32)
```

Expected: the content shows two lines. Now do the three-way sync (0.9), then:

```bash
voice-adb show-note "פתק ראשון מהמחשב"
```

Expected: the `NOTE` line's `content` is `פתק ראשון מהמחשב\nשורה שנייה` and `"conflicts":[]`.

### 1.4 Tags, including a brand-new tag

```bash
voice-adb create-tag עבודה
voice-adb tag-note "פתק מהטלפון" עבודה
voice-adb sync-now
voice cli sync now
voice cli tags-list
voice cli note-show $(voice cli notes-list | grep "פתק מהטלפון" | cut -c1-32)
```

Expected: `tags-list` on Desktop contains `עבודה` (write down its id: `<id of עבודה>`), and `note-show` lists the tag `עבודה` on the note.

Now from Desktop create a child tag and attach it:

```bash
voice cli tag-create דחוף --parent <id of עבודה>
voice cli tags-list
voice cli notes-tag --tags <id of דחוף> --notes $(voice cli notes-list | grep "פתק מהטלפון" | cut -c1-32)
```

Then do the three-way sync (0.9), then:

```bash
voice-adb list-tags
voice-adb show-note "פתק מהטלפון"
```

Expected: `list-tags` shows `דחוף` with `parent_id` equal to the id of `עבודה`; `show-note` shows `"tags":["עבודה","דחוף"]` (order may differ). On the phone, `voice-adb open tags` shows `דחוף` under `עבודה`.

### 1.5 Delete a note

First write down the note's id, because a deleted note no longer appears in lists:

```bash
voice cli notes-list | grep "פתק מהטלפון"
```

Copy the 32-character id at the start of that line to the results sheet as *Id of פתק מהטלפון (1.2)*. Then:

```bash
voice-adb delete-note "פתק מהטלפון"
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep "פתק מהטלפון"
voice cli note-history <that id>
```

Expected: the `grep` prints nothing (the note is gone from the list), Server's `voice cli notes-list` does not show it either, but `note-history` still lists its version `פתק מהטלפון`: deletion keeps history.

### 1.6 Audio: import on Desktop, download on demand on Android

```bash
voice cli audiofiles-import /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage
voice cli notes-list
voice cli sync now
voice cli storage upload-pending
```

Expected: `audiofiles-import` reports 2 imported files and `notes-list` shows two new notes whose first lines are the file names `desktop1.mp3` and `desktop2.mp3`. `sync now` completes with no `Warnings:` line (a cloud problem would appear there and be retried next sync). `upload-pending` reports that nothing is left to upload. Then:

```bash
voice cli audiofile-show $(voice cli notes-list | grep "desktop1.mp3" | cut -c1-32)
```

Expected: an `Uploaded:` line with a time. Now the phone:

```bash
voice-adb sync-now
voice-adb show-note desktop1.mp3
```

Expected: `"media":[{"audio_id":"...","filename":"desktop1.mp3","state":"in_cloud_not_downloaded"}]`. The file was **not** downloaded automatically. Open the note on the phone by hand:

```bash
voice-adb open-note desktop1.mp3
```

Expected on the phone's screen: a notice *Media missing: 1 file(s) not on this device* and a **Download** button. Tap **Download**.

Expected: the player appears and the file plays. Then:

```bash
voice-adb show-note desktop1.mp3
```

Expected: the media `state` is now `local`. Leave `desktop2.mp3` alone on the phone: step 7.4 checks that it was never downloaded.

Server: in the second SSH session run `voice tui`, select the note `desktop2.mp3` with the arrow keys, press `d`.

Expected: the TUI reports the download and, if `mpv` is installed on Server, player controls appear. Press `q`.

### 1.7 Audio: import on Android, download on Desktop

```bash
voice-adb import-audio /storage/emulated/0/voice-testing/VoiceTestStorage
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep phone
```

Expected: `import-audio` prints `IMPORTED [...]` with `phone1.mp3` and `phone2.mp3` and then `IMPORT_AUDIO OK ... imported=2`; `sync-now` succeeds; Desktop's list shows two notes `phone1.mp3` and `phone2.mp3`. Then:

```bash
voice cli note-audiofiles-list $(voice cli notes-list | grep "phone1.mp3" | cut -c1-32)
voice cli note-audiofiles-download $(voice cli notes-list | grep "phone1.mp3" | cut -c1-32)
ls /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/voice-audio
```

Expected: the first command says the file is *not on this device, in cloud storage (use audiofile-download)*; the second downloads it; `ls` shows a file named `<audio id>.mp3` (32 hex characters, lowercase extension).

### 1.8 A new recording appears in the phone's storage folder

This is the everyday case: the voice recorder saved a new file after Voice already imported the folder once.

```bash
adb shell cp /storage/emulated/0/voice-testing/VoiceTest/phone3.mp3 /storage/emulated/0/voice-testing/VoiceTestStorage/
adb shell ls /storage/emulated/0/voice-testing/VoiceTestStorage
voice-adb import-audio /storage/emulated/0/voice-testing/VoiceTestStorage
```

Expected: `ls` shows three files; `import-audio` prints `IMPORTED [...]` listing `phone1.mp3`, `phone2.mp3` and `phone3.mp3` and `imported=3`. **Write down** whether `phone1.mp3` and `phone2.mp3` were imported a second time (look at `voice-adb list-notes`: are there two notes named `phone1.mp3`?). Re-importing an unchanged file is a defect; record it in the results sheet either way, then continue:

```bash
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep phone3
```

Expected: a note `phone3.mp3` exists on Desktop.

### 1.9 Transcriptions

Desktop needs a Whisper model; the command explains how to get one if it is missing.

```bash
voice cli audiofile-transcribe $(voice cli audiofile-show $(voice cli notes-list | grep "phone1.mp3" | cut -c1-32) | grep -i "^ID" | cut -d' ' -f2) --language he
```

If that line is too clever for your shell, do it in two steps: `voice cli audiofile-show <id of phone1.mp3 note>` prints the audio file id on its `ID:` line; then `voice cli audiofile-transcribe <audio id> --language he`.

```bash
voice cli sync now
voice-adb sync-now
voice-adb open-note phone1.mp3
```

Expected: the transcription text is shown under the recording on the phone with its state flags. Then:

```bash
voice-adb set-transcription-state phone1.mp3 "original verified"
voice-adb sync-now
voice cli sync now
voice cli note-show $(voice cli notes-list | grep "phone1.mp3" | cut -c1-32)
```

Expected: the transcription's state on Desktop contains `verified`.

### 1.10 Synced settings

```bash
voice cli settings set transcription.preferred_languages '["he", "en"]'
voice cli sync now
```

On Server (second SSH session):

```bash
voice cli settings list
```

Expected: `transcription.preferred_languages = ["he", "en"]` (it arrived with Desktop's push; no command was needed on Server). Then `voice-adb sync-now` and `voice-adb get-setting transcription.preferred_languages` prints `GET_SETTING OK transcription.preferred_languages=["he", "en"]`.

### 1.11 Mirror on Server

On Server (second SSH session):

```bash
voice cli storage mirror enable
voice cli storage download-missing
ls /var/www/voice-testing/voice-audio
```

Expected: `download-missing` reports 5 downloaded (or "already on this device" for the one you fetched in 1.6), and `ls` shows five files. Then confirm the phone did not download anything it was not asked to:

```bash
voice-adb show-note desktop2.mp3
```

Expected: `"state":"in_cloud_not_downloaded"`.

### 1.12 Record a new voice message on the phone

The phone can record directly into a note. First set the recorder up by hand:

```bash
voice-adb open recorder
```

Expected on the phone: the **Recorder** screen with two radio buttons under *The New button creates* (*A new note*, *A new voice recording*), three radio buttons under *Recording format* (*Opus, 128 kb/s, 48 kHz (.ogg)* selected, *AAC, 96 kb/s, 44.1 kHz (.m4a)*, *WAV, 16 kHz, 16-bit mono (.wav)*), and a card for every microphone the phone has (at least one *Built-in microphone*). Leave *Opus* selected.

1. On the first microphone card tap **Test**, then speak while holding the phone normally. Expected: the bar moves with your voice and *now NN% · peak NN%* updates. Speak near the bottom edge, then the top edge, then each corner, and write on the results sheet which position gave the highest peak. Tap **Stop test**.
2. Repeat step 1 for every other microphone card. Type a friendly name in each card's *Friendly name* field, for example `מיקרופון תחתון` for the one that hears best near the bottom edge.
3. Tap the radio button of the microphone that had the highest peak, so it is the one used for recording.
4. Under *The New button creates* leave *A new note* selected. Press Back.

Now record:

```bash
voice-adb open notes
```

On the phone: **long-press** the **+** button at the left of the search field. Expected: a menu with *New Note* and *New Voice Recording*. Tap **New Voice Recording**. Expected: a new, empty note opens with the recorder inside it, in the place where the player of a note with a recording is: `00:00:00` in large digits, a flat line (the waveform), a large red round button, a small trash button to its left and a small tick (Save) to its right. If the phone asks for microphone permission, tap **Allow**.

1. Tap the red button and say clearly `זוהי הקלטה מהטלפון, אחת שתיים שלוש`. Expected: the digits count up in red, the waveform shows bars that move with your voice, and the red button now shows a pause symbol.
2. After about five seconds tap the red button. Expected: the line under the buttons says *Paused* and the digits stop. Wait three seconds, tap it again. Expected: recording continues and the digits continue from where they stopped (not from zero).
3. Tap the small **trash** button. Expected: a dialog *Discard this recording?* with three choices: **Discard**, **Restart** and **Cancel**. Tap **Restart**. Expected: the digits are back at `00:00:00` and recording has started again. Say `הקלטה שנייה` and after five seconds tap the small **tick** button to save.

Expected: the recorder disappears and the same note now shows the player with the recording's length; no second note was created. Tap play and listen: you hear `הקלטה שנייה` and **not** the first attempt. Then:

```bash
voice-adb list-notes | grep Recording
```

Expected: one `NOTE` line whose `first_line` starts with `Recording ` and whose media `state` is `local`. Write its `first_line` on the results sheet as *recording note*.

Test **Discard**: open the recorder again (long-press **+** → *New Voice Recording*), record three seconds, tap the small **trash** button, and in the dialog tap **Discard**. Expected: back on the notes list, with no new empty note in it, and `voice-adb list-notes | grep -c Recording` still prints `1`.

Test **Cancel**: open the recorder again, record three seconds, tap the small **trash** button, and in the dialog tap **Cancel**. Expected: the dialog closes and the recording is still there with its digits where they were. Tap the small **trash** button again and tap **Discard**.

Test that only one note records at a time: with a recording in progress, press Back to the notes list and open a different note, then tap its red **microphone**. Expected: a message that a recording is already in progress in another note, and no recorder controls. Go back to the recording and save it.

Test recording into a note that already exists: open any note that has no recording, tap the red **microphone** in its toolbar. Expected: the recorder appears inside that note. Record three seconds, tap the **tick**. Expected: the recording is added to that note, and the note keeps the text it already had.

Now sync it:

```bash
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep Recording
voice cli note-audiofiles-download $(voice cli notes-list | grep "Recording " | cut -c1-32)
ls /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/voice-audio
```

Expected: `sync-now` succeeds with no warnings (the phone uploaded the file); Desktop has the note; the download fetches one file and `ls` shows a new `<audio id>.ogg`. Play it on Desktop (`voice gui`, click the note, press play): you hear `הקלטה שנייה`. On Server, in the TUI, the note exists and `d` downloads it.

Finally set the default action: `voice-adb open recorder`, tap *A new voice recording*, press Back, go to the notes list and **tap** (do not long-press) **+**. Expected: the recorder opens directly. Tap **Trash**. Set the default back to *A new note*.

---

### 1.13 A note with several recordings

First import the third Desktop file, which was kept aside for this:

```bash
cp /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTest/desktop3.mp3 /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage/
voice cli audiofiles-import /home/dotancohen/Projects/VoiceFamily/VoiceFamily/voice-testing/VoiceTestStorage
voice cli notes-list | grep desktop
```

Expected: `audiofiles-import` reports 1 imported file (`desktop3.mp3`), and `notes-list` shows one note per Desktop file: `desktop1.mp3`, `desktop2.mp3`, `desktop3.mp3`. If `desktop1.mp3` or `desktop2.mp3` appears twice, that is a defect; write it down.

Desktop can merge two notes into one; the survivor keeps both recordings. Merge the `desktop2.mp3` and `desktop3.mp3` notes:

```bash
voice cli notes-merge $(voice cli notes-list | grep "desktop2.mp3" | cut -c1-32) $(voice cli notes-list | grep "desktop3.mp3" | cut -c1-32)
voice cli sync now
voice-adb sync-now
voice-adb list-notes | grep desktop2
```

Expected: the `NOTE` line for the merged note lists **two** entries under `media`, `desktop2.mp3` and `desktop3.mp3`. If either `state` is `in_cloud_not_downloaded`, run `voice-adb download-media desktop2.mp3` and check again.

The phone needs a Whisper model once (about 0.6 GB; several minutes on Wi-Fi):

```bash
voice-adb download-model large-v3-turbo-q5_0
voice-adb set-transcription model=large-v3-turbo-q5_0 language=he beam_size=1
voice-adb list-models | grep turbo-q5_0
```

Expected: the `MODEL` line shows `"installed":true` and `"selected":true`.

Now, on the phone, in the notes list: the merged note's row starts with a star and then two small buttons, `🔊1` and `🔊2`, followed by the date. In each button the speaker symbol is at the **left** of its number, and neither button has a small pen mark yet (that mark appears once the recording has a transcription).

1. Tap `🔊1`. Expected: the row unfolds a small player with the file name `desktop2.mp3` above it, and it starts playing; you hear the desktop2 recording. Tap `🔊2`. Expected: the player now shows `desktop3.mp3` and plays that recording instead. Tap `🔊2` again. Expected: the player folds away.
2. Tap the note row itself to open it. Expected: under the note text, a player with a waveform, the speed slider marked ½, 1 and 2, and a list of the two files, each with a transcribe icon at its left. Tap the second file's name. Expected: `desktop3.mp3` is highlighted and plays. Tap the first file's name. Expected: `desktop2.mp3` is highlighted and plays.
3. Tap the transcribe icon at the left of `desktop2.mp3`. Expected: a dialog *Transcribe on this phone* with the file name, a *Model* box showing *Whisper large-v3-turbo (5-bit)*, a *Language* box showing *Hebrew*, and the buttons **Cancel**, **Settings**, **Transcribe**. Tap **Transcribe**. Expected: a thin progress bar under the player and a notification *Transcribing desktop2.mp3*. Wait for the notification to disappear (a few minutes).
4. Now transcribe the second recording from the computer:

```bash
voice-adb transcribe desktop2.mp3 he 2
```

Expected: `OK queued ... file=desktop3.mp3`. Wait until the notification disappears again, then:

```bash
voice-adb list-transcriptions desktop2.mp3
```

Expected: two `TRANSCRIPTION` lines, one with `"filename":"desktop2.mp3"` and one with `"filename":"desktop3.mp3"`, each with `"service":"local_whisper"` and a Hebrew `content` that matches what is said in that recording. Write both texts on the results sheet.

5. On the phone, in the open note: tap the first file's name so it plays. Expected: exactly **one** transcription card is shown under the player, the one for `desktop2.mp3`. Tap the second file's name. Expected: the card changes to the `desktop3.mp3` transcription; the first one is no longer shown. Each card ends with a line `local_whisper | <today's date>` and three small icons (verified, cleaned, polished) on that same line; tap the first icon. Expected: it turns blue. Check with:

```bash
voice-adb list-transcriptions desktop2.mp3 | grep desktop3
```

Expected: the `desktop3.mp3` line's `state` contains `verified` without a `!` in front of it.

6. Go back to the notes list. Expected: both `🔊1` and `🔊2` on that note's row now carry a small pen mark, because both recordings have a transcription.

7. Sync and check Desktop:

```bash
voice-adb sync-now
voice cli sync now
voice cli note-show $(voice cli notes-list | grep "desktop2.mp3" | cut -c1-32)
```

Expected: Desktop shows both transcriptions with the same Hebrew texts, and the `desktop3.mp3` one is `verified`.

### 1.14 Leaving a note points out its row

```bash
voice-adb open notes
```

1. Scroll the notes list down so that a note in the middle of the screen is one you can recognise, and open that note by tapping it. Press **Back**. Expected: the list is exactly where you left it, not back at the top, and the row of the note you just left is briefly crossed by two dots that start in the middle of the row and travel out to its two edges. In a light theme they are bright; in a dark theme they are only slightly lighter than the row.
2. Open Voice's **Settings** → **Advanced**. Expected: *Spotlight duration* showing *0.50 seconds* and a slider.
3. Drag the slider to the far right (*1.00 seconds*), press Back twice, and repeat step 1. Expected: the same two dots, now clearly slower.
4. Go back to **Settings** → **Advanced**, drag the slider to the far left (*Off*), and repeat step 1. Expected: the list is still where you left it, and there are no dots at all.
5. Set it back to *0.50 seconds*.

### 1.15 The interface in Hebrew (right to left)

```bash
voice-adb open notes
```

On the phone, change the phone's language to Hebrew: open Android's **Settings** app (not Voice), then *General management* → *Language*, add **עברית** and move it to the first place. Return to Voice.

Expected: the whole Voice interface is mirrored, so each note's star and its `🔊1`, `🔊2` buttons are now at the **right** of the row and the date follows them to the left. Inside each button the speaker symbol is still at the left of its number (`🔊1`, never `1🔊`), and the pen mark is still after the number.

Set the phone's language back to English the same way, and check that the row reads left to right again. Write on the results sheet whether anything looked mirrored the wrong way.

### 1.16 Acting on several notes at once

```bash
voice-adb open notes
```

1. **Long-press** any note. Expected: its star turns into a filled circle with a tick, the card is tinted, and a bar appears at the bottom of the list with a number 1, an X at its left, and the buttons **Tag**, **Delete**, **Transcribe**.
2. Tap two more notes (a single tap now selects instead of opening). Expected: the number says 3.
3. Tap **Tag**. Expected: a dialog *Tags for 3 note(s)* listing the tags. Tap a tag that none of them has. Expected: its box fills. Tap **Done**, then look at the three note rows: each shows that tag after the date. Long-press one of them again, tap **Tag**, and tap that same tag twice: it empties (removed from all three) and fills again (added to all three). Tap **Done**.
4. With three notes selected, tap **Delete**. Expected: a dialog asking to delete 3 note(s). Tap **Cancel**. Expected: nothing is deleted and the three notes stay selected.
5. Press the phone's **Back** gesture. Expected: the selection ends and the bottom bar disappears; the notes list is still shown.
6. Long-press the note that has the two recordings from 1.13, then also select one note without any recording. Tap **Transcribe**, and in the dialog leave the model as *Whisper large-v3-turbo (5-bit)*, the one used in 1.13. Tap **Transcribe**. Expected: **nothing is queued**, and the message at the bottom says that both recordings already have a transcription from this model and that you should open a note to transcribe one again. This is on purpose: transcribing many notes at once never repeats work.
7. Open the note with the two recordings, and tap the transcribe icon at the left of `desktop2.mp3`. In the dialog tap **Transcribe**. Expected: a dialog *Transcribe again?* saying the file already has 1 transcription. Tap **Cancel**. Expected: nothing happens. Do it again and tap **Transcribe again**. Expected: the transcription starts. Wait for the notification to disappear, then:

```bash
voice-adb list-transcriptions desktop2.mp3
```

Expected: three `TRANSCRIPTION` lines for that note now (the two from 1.13 and the new one), no line says `Error:`, and every line shows a `"language"` and a `"model"`. Write both on the results sheet for the new line.

### 1.17 Times keep the clock they were written on

A note recorded at 15:20 in Jerusalem must still say 15:20 after the phone is
carried to another timezone. This checks that.

```bash
voice-adb open notes
```

1. On the phone, write down the date and time shown on the first note in the list, and the exact first line of that note. Also write down the current time on the phone's own clock.
2. Change the phone's timezone by hand: open Android's **Settings** app (not Voice), then *General management* → *Date and time*, turn **Automatic date and time** off, and set the time zone to **New York** (GMT-4). The phone's clock will jump back several hours.
3. Return to Voice and open the notes list again.

Expected: the note's date and time are **unchanged**, exactly as written down in step 1, because that is the clock that was being read where the note was made. Notes made long ago on other devices may differ; only compare the note you wrote down.

4. Now create a note while the phone thinks it is in New York:

```bash
voice-adb create-note "פתק מניו יורק"
voice-adb open notes
```

Expected: the new note is at the top of the list and its time matches the phone's **current** clock (the New York time), not Jerusalem time. So the list now shows a note from a few minutes ago with an earlier time than the note above it. That is correct and intended.

5. Put the phone back: Android's **Settings** → *General management* → *Date and time* → turn **Automatic date and time** back on. Return to Voice.

Expected: both notes keep the times they showed in steps 3 and 4. Nothing shifts back.

6. Sync and compare with Desktop:

```bash
voice-adb sync-now
voice cli sync now
voice cli notes-list | head -3
```

Expected: Desktop shows the New York note with the same time the phone showed for it, not translated into Desktop's timezone. Write both times on the results sheet.


### 1.18 Recording that does not stop, and merging notes

Two things a recorder must get right: it keeps recording when the user goes
elsewhere, and it does something sensible when the telephone rings.

```bash
voice-adb set-recorder start_immediately=true during_call=pause default_action=recording
voice-adb open notes
```

1. Look at the toolbar button at the left of the search field. Expected: it is a **red round dot**, not a `+`, because a tap now starts a recording.
2. Tap it. Expected: a new empty note opens with the recorder inside it and **recording has already started**: the digits are counting up and the waveform is moving. If the phone asks for permission to use the microphone, tap **Allow**; recording starts after that.
3. Say `אחת שתיים שלוש` and then press the phone's **home** gesture to leave Voice. Expected: a notification appears saying *Recording* with a running time, and the recording does not stop.
4. Open another application, for example the Android **Settings** app, and count slowly to ten. Then **lock the phone** with the power button and count to ten again. Expected: the notification still shows a growing time throughout.
5. Unlock the phone and tap the notification. Expected: the note returns with its recorder still counting, past twenty seconds.
6. Say `ארבע חמש שש`, tap the **tick** to save, and listen to the recording that appears in the note. Expected: it contains both what you said before leaving and what you said after coming back; nothing was cut.
7. Tap the red **microphone** in the note's toolbar to record again. Expected: the recorder appears showing `00:00:00` and an empty waveform, **not** the end of the recording you just made, and the red button starts a new recording when tapped.

Now the telephone. You need a second phone to call this one.

8. Start a new recording (`voice-adb open recording`), say `לפני השיחה`, and have the second phone call this one. **Answer the call.** Expected: the notification says the call is in progress and the recording pauses; the digits stop.
9. End the call. Expected: within a second or two the recording continues by itself and the digits move again. Say `אחרי השיחה` and tap the **tick** to save. Listen: both parts are there, with no silent gap of call length between them.
10. Repeat steps 8 and 9 with the other setting:

```bash
voice-adb set-recorder during_call=silence
```

Expected this time: the recording does **not** pause during the call, and the part recorded while the call was in progress is silent.

11. Put the settings back:

```bash
voice-adb set-recorder start_immediately=false during_call=pause default_action=note
```

Expected: the toolbar button is a `+` again.

**Merging notes.** In the notes list, long-press the note from step 6, then tap the note from step 9 and one note that has no recording at all.

12. Tap **Merge**. Expected: a dialog naming the oldest note and explaining that the others' text will be added below it. Tap **Merge**.
13. Expected: the three notes become one. Open it: its text holds all three notes' text with a separator between them, and both recordings are on it, each with its own `🔊` button. The other two notes are gone from the list.
14. Check the other devices:

```bash
voice-adb sync-now
voice cli sync now
voice cli notes-list | head -5
```

Expected: Desktop shows the same single note, and the two notes that were merged away are gone there too. Write on the results sheet how many recordings the merged note has.


### 1.19 The trash bin

A deleted note is not gone: it waits in the trash with its recordings until
you recover it or remove it for good. This section checks both, and that
"for good" reaches the other devices.

1. On the phone, open any note that has **no recording** and no text you care
   about, tap the **trash** icon in its toolbar and confirm. Expected: you are
   back on the notes list and the note is gone from it. Write its first line
   on the results sheet as *trashed note*.
2. Tap the **gear** at the end of the notes toolbar, then **Trash**. Expected:
   the *trashed note* is listed, with the time it was deleted and its text.
3. Tap **Recover** on it. Expected: the row disappears from the trash. Press
   Back and check the notes list: the note is there again with its text.
4. Delete it again (step 1), open Settings → Trash, and tap **Delete for
   good**. Expected: a dialog explaining that the note and its recordings are
   removed from every device and that it cannot be undone. Tap **Cancel**.
   Expected: the note is still in the trash.
5. Tap **Delete for good** again and confirm. Expected: the trash is empty
   again, and the note is not in the notes list.

Now on the Desktop:

```bash
voice cli trash-list
```

6. Expected: a line for every note in the desktop's trash. If the phone has
   synced since step 5, the note from step 5 is **not** listed: it was removed
   there too.

```bash
voice-adb sync-now
voice cli sync now
voice cli trash-list
```

7. Expected: still no line for the note from step 5, on either device. Write
   on the results sheet whether it stayed away.
8. On the Desktop GUI, open **File → Trash**. Expected: the same list as
   `trash-list`. Select a note, press **Recover**, and check that it comes
   back in the notes list. Delete it again from the notes list.
9. In the TUI, press **Ctrl+T**. Expected: the trash, with the same notes.
   Press **Delete for good** once. Expected: a warning that says to press
   again. Press it again. Expected: the note goes.
10. Sync both devices and check that the note removed in step 9 is gone from
    the phone as well:

```bash
voice cli sync now
voice-adb sync-now
voice-adb list-notes | grep -c "<first line of that note>"
```

Expected: `0`.

## 2. Conflicts

### 2.0 Before every test in this section

Do the three-way sync (0.9), then run on Desktop:

```bash
voice cli sync conflicts
```

Expected: `No unresolved conflicts.` If it lists anything, you skipped a resolution step earlier; go back to it.

### 2.1 Edits on different lines merge silently

```bash
voice cli note-create $'שורה אחת\nשורה שתיים\nשורה שלוש'
```

Do the three-way sync. Now, **without syncing in between**:

```bash
voice cli note-edit $(voice cli notes-list | grep "שורה אחת" | cut -c1-32) $'שורה אחת מהמחשב\nשורה שתיים\nשורה שלוש'
voice-adb edit-note "שורה אחת" $'שורה אחת\nשורה שתיים\nשורה שלוש מהטלפון'
```

Do the three-way sync. Then:

```bash
voice cli note-show $(voice cli notes-list | grep "שורה אחת" | cut -c1-32)
voice-adb show-note "שורה אחת מהמחשב"
voice cli sync conflicts
```

Expected: both devices show exactly the three lines `שורה אחת מהמחשב`, `שורה שתיים`, `שורה שלוש מהטלפון`; `sync conflicts` says none. Note that the note's first line is now `שורה אחת מהמחשב`; the plan uses that from here on.

### 2.2 Edits on the same line are kept and flagged

Without syncing in between:

```bash
voice cli note-edit $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32) $'שורה אחת מהמחשב\nשורה שתיים מהמחשב\nשורה שלוש מהטלפון'
voice-adb edit-note "שורה אחת מהמחשב" $'שורה אחת מהמחשב\nשורה שתיים מהטלפון\nשורה שלוש מהטלפון'
```

Do the three-way sync. Then:

```bash
voice cli note-show $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32)
voice-adb show-note "שורה אחת מהמחשב"
voice cli sync conflicts
voice-adb list-conflicts
```

Expected on Desktop and on the phone: line two is replaced by five lines: `<<<<<<< VERSION A`, one of the two versions, `=======`, the other version, `>>>>>>> VERSION B`; lines one and three are unchanged. `voice cli sync conflicts` lists one conflict `note ... content: Note content edited on both: Desktop vs Android` (the order of the names may differ). `voice-adb list-conflicts` shows one `CONFLICT` line with the **same id** (compare the first 8 characters). On Server, `voice cli sync conflicts` shows the same id again. Write the id on the results sheet as *conflict 2.2*.

### 2.3 Resolve side by side

```bash
voice gui
```

Click the note whose first line is `שורה אחת מהמחשב`. Expected: a red banner *CONFLICT (content): changed on Desktop and Android...* with buttons **Accept merge** and **Resolve…**. Click **Resolve…**.

Expected: a window with three text panes side by side (one per device, and *Result*) and the common ancestor below. Click **Start from A**. In the *Result* pane, click at the end of the second line and type ` מאוחד`. Click **Save**.

Expected: the banner disappears, the note shows three lines with no `<<<<<<<` anywhere. Close the GUI. Do the three-way sync. Then:

```bash
voice-adb show-note "שורה אחת מהמחשב"
voice cli sync conflicts
voice cli sync conflicts --all
```

Expected: the phone shows the same three lines and `"conflicts":[]`; `sync conflicts` says none; `--all` shows conflict 2.2 with `(resolved)`.

### 2.4 Accept as-is

Create a new conflict exactly as in 2.2 but with the words `גרסה ב` (Desktop) and `גרסה ג` (phone) on line two. After the three-way sync confirm the markers are there on both devices as before, then:

```bash
voice-adb accept-conflicts "שורה אחת מהמחשב"
voice-adb sync-now
voice cli sync now
voice cli note-show $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32)
voice cli sync conflicts
```

Expected: `accept-conflicts` prints `accepted=1`; the note still contains the markers on both devices (accepting keeps the merged text as it is); `sync conflicts` says none.

### 2.5 Fix by editing in the TUI

Create a new conflict as in 2.2 with the words `גרסה ד` and `גרסה ה`. After the three-way sync, on Server (second SSH session):

```bash
voice tui
```

Select the note with the arrow keys. Expected: the red banner. Click **Edit** (or press `s` later to save), delete the five marker lines and type instead one line `שורה שתיים סופית`, click **Save**. Expected: the banner disappears. Press `q`. Then do the three-way sync and check with `voice cli note-show` and `voice-adb show-note` that both show `שורה שתיים סופית` and no conflict.

### 2.6 Delete against edit

```bash
voice cli note-create "פתק שיימחק"
```

Do the three-way sync. Without syncing in between:

```bash
voice-adb edit-note "פתק שיימחק" $'פתק שיימחק\nעריכה חשובה'
voice cli note-delete $(voice cli notes-list | grep "פתק שיימחק" | cut -c1-32)
```

Do the three-way sync. Then:

```bash
voice cli notes-list | grep "פתק שיימחק"
voice cli note-show $(voice cli notes-list | grep "פתק שיימחק" | cut -c1-32)
voice-adb show-note "פתק שיימחק"
```

Expected: the note is **alive** on Desktop and on the phone, contains `עריכה חשובה`, and both show a `delete` conflict (`"conflicts":["delete"]` on the phone). Resolve it by accepting on Desktop:

```bash
voice cli sync conflicts
voice cli sync resolve <first 8 characters of the conflict id>
```

Do the three-way sync. Then delete it again on Desktop (`voice cli note-delete <id>`), do the three-way sync, and confirm with `voice-adb list-notes` that `פתק שיימחק` is gone and `voice cli sync conflicts` says none.

### 2.7 Tag renamed on two devices

Do the three-way sync. Without syncing in between:

```bash
voice cli tag-rename <id of דחוף> מיידי
voice-adb rename-tag דחוף בהול
```

Do the three-way sync. Then:

```bash
voice cli tags-list
voice-adb list-tags
voice cli sync conflicts --details
```

Expected: Desktop and the phone show the **same** name for that tag, either `מיידי` or `בהול` (whichever edit was later by the clock); `--details` shows a scalar conflict on the tag listing both names and both devices. Accept it:

```bash
voice cli sync resolve <first 8 characters of that conflict id>
```

Do the three-way sync. Write down which name won on the results sheet; the plan calls the tag `<the renamed tag>` from here on.

### 2.8 Tag link removed on one device, re-added on the other

Do the three-way sync. Without syncing in between:

```bash
voice cli tag-create חופשה
voice cli notes-tag --tags <id of חופשה> --notes $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32)
```

Do the three-way sync (now both devices have the link). Without syncing in between:

```bash
voice cli note-show $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32)      # confirm the tag is listed
voice-adb untag-note "פתק ראשון מהמחשב" חופשה
voice-adb tag-note "פתק ראשון מהמחשב" חופשה
```

Then remove it on Desktop: there is no CLI command to remove a tag from a note, so use the GUI: `voice gui`, click the note, click **Tags**, untick `חופשה`, close the dialog, close the GUI. Do the three-way sync. Then:

```bash
voice cli note-show $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32)
voice-adb show-note "פתק ראשון מהמחשב"
```

Expected: the tag `חופשה` is still attached on both devices and the phone shows `"conflicts":["tag"]`. Accept with `voice-adb accept-conflicts "פתק ראשון מהמחשב"` and do the three-way sync.

### 2.9 Transcription edited on two devices

Do the three-way sync. On Desktop find the transcription of `phone1.mp3` (from 1.9) and edit it in the GUI: `voice gui`, click the note `phone1.mp3`, in the transcription box click **Edit**, add the word `מחשב` at the end, **Save**, close the GUI. On the phone: `voice-adb open-note phone1.mp3`, in the transcription tap **Edit**, add the word `טלפון` at the end, tap **Save**. Do the three-way sync. Then:

```bash
voice cli note-show $(voice cli notes-list | grep "phone1.mp3" | cut -c1-32)
voice-adb show-note phone1.mp3
voice cli sync conflicts
```

Expected: the transcription text contains the markers with both words; the phone shows `"conflicts":["transcription"]`; `sync conflicts` on Desktop and `voice-adb list-conflicts` show the same conflict id. Accept it with `voice-adb accept-conflicts phone1.mp3` and do the three-way sync.

---

## 3. Outages and interruptions

### 3.1 Android offline for a long time

```bash
voice-adb airplane on
```

Expected: `OK airplane mode on`, and the phone shows the airplane icon. Now, over **at least one hour** (start a timer), do these on the phone while it is offline:

```bash
voice-adb create-note "פתק אופליין אחד"
voice-adb create-note "פתק אופליין שתיים"
voice-adb create-note "פתק אופליין שלוש"
voice-adb edit-note "פתק ראשון מהמחשב" $'פתק ראשון מהמחשב\nשורה שנייה\nשורה מהטלפון בלי רשת'
voice-adb tag-note "פתק אופליין אחד" עבודה
adb shell rm -f /storage/emulated/0/voice-testing/VoiceTestStorage/*
adb shell cp /storage/emulated/0/voice-testing/VoiceTest/phone2.mp3 /storage/emulated/0/voice-testing/VoiceTestStorage/
voice-adb import-audio /storage/emulated/0/voice-testing/VoiceTestStorage
voice-adb sync-now
```

Expected: every command prints `OK` except the last: `SYNC_NOW OK failed error=...` or `SYNC_NOW ERROR ...` mentioning the network. Meanwhile on Desktop (which is online):

```bash
voice cli note-create "פתק מהמחשב בזמן שהטלפון אופליין"
voice cli note-create "עוד פתק מהמחשב"
voice cli note-edit $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32) $'פתק ראשון מהמחשב מעודכן\nשורה שנייה'
voice cli sync now
```

When the hour has passed:

```bash
voice-adb airplane off
sleep 20
voice-adb sync-now
voice cli sync now
voice-adb sync-now
```

Expected: `sync-now` prints `success received=<at least 5> sent=<at least 5>`. Then check:

```bash
voice cli notes-list | grep "פתק אופליין"
voice cli note-show $(voice cli notes-list | grep "פתק ראשון מהמחשב" | cut -c1-32)
voice-adb show-note "פתק ראשון מהמחשב מעודכן"
voice cli sync conflicts
```

Expected: three `פתק אופליין` notes on Desktop; the edited note shows `פתק ראשון מהמחשב מעודכן`, `שורה שנייה`, `שורה מהטלפון בלי רשת` on both devices (different lines merged, no conflict); `sync conflicts` says none. The phone's new `phone2.mp3` note: `voice cli notes-list | grep phone2` shows two notes now (one from 1.7, one from this import) and `voice cli audiofile-show` of the new one has an `Uploaded:` line after this sync.

### 3.2 Desktop offline

```bash
nmcli networking off
voice cli note-create "פתק שנכתב בלי רשת"
voice cli sync now
echo "exit code: $?"
```

Expected: `sync now` prints `Sync with ... failed:` with a network error within about 30 seconds, and `exit code: 1`. Then:

```bash
nmcli networking on
sleep 10
voice cli sync now
```

Expected: `completed:` with no errors; on Server `voice cli notes-list | grep "בלי רשת"` shows the note. (If your Desktop has no `nmcli`, unplug the network cable or turn Wi-Fi off in the system menu instead.)

### 3.3 Server stopped in the middle of a sync

Create 300 notes on Desktop so the push takes a while:

```bash
for i in $(seq 1 300); do voice cli note-create "פתק מספר $i" > /dev/null; done
voice cli notes-list | wc -l
```

Now you need two hands: in one terminal start the sync, and **immediately** in the tmux window on Server press `Ctrl+C`:

```bash
voice cli sync now
```

Expected: Desktop's sync ends with `failed:` and a message about the push. Restart the server as in 0.4 (`tmux attach -t voice`, then `voice cli sync serve --verbose`). Then:

```bash
voice cli sync now
```

Expected: `completed:`. On Server, `voice cli notes-list | grep -c "פתק מספר"` prints `300` (every note exactly once), and the server console of the second sync shows `GET /sync/changes cursor=<a number greater than 0>`: it resumed instead of starting over. If you were too slow and the first sync completed, that is fine: write it down and continue.

### 3.4 Server database replaced

In the tmux window press `Ctrl+C`. In the second SSH session:

```bash
mv ~/.config/voice/notes.db ~/.config/voice/notes.db.bak
mv ~/.config/voice/notes.db-wal ~/.config/voice/notes.db-wal.bak 2>/dev/null
mv ~/.config/voice/notes.db-shm ~/.config/voice/notes.db-shm.bak 2>/dev/null
```

In the tmux window start the server again. On Desktop:

```bash
voice cli sync now
```

Expected: `Warnings (1):` with a line saying the peer has a new database and everything is exchanged again; afterwards on Server `voice cli notes-list | wc -l` shows the same count as Desktop's `voice cli notes-list | wc -l`, and `voice cli storage status` on Server shows the S3 configuration again (it came back from Desktop). Then:

```bash
voice-adb sync-now
```

Expected: `success` with a `warnings=[...]` part about the new database.

### 3.5 Phone app data cleared (lost phone)

```bash
adb shell pm clear com.dotancohen.voiceandroid
voice-adb ping
```

Expected: `pm clear` prints `Success`; `ping` prints a **new** device id. Set it up again exactly as in 0.6 (`set-device-name`, `set-sync` with the same Server id), then:

```bash
voice-adb initial-sync
voice-adb list-notes | wc -l
voice cli notes-list | wc -l
```

Expected: `initial-sync` prints `INITIAL_SYNC OK success received=<a large number> sent=...`; the two counts are equal (all notes are back); every `NOTE` line's `media` states are `in_cloud_not_downloaded` (nothing is downloaded until asked). Write the new Android id on the results sheet.

### 3.6 Reset sync state on Desktop does no harm

```bash
voice cli notes-list | wc -l
voice cli sync reset-timestamps
voice cli sync now
voice cli sync full-resync --peer <server-id>
voice cli notes-list | wc -l
voice cli sync conflicts
```

Expected: both syncs complete with no `Conflicts:` line; the two counts are the same; no conflicts.

---

## 4. Large data

### 4.1 Many notes

```bash
for i in $(seq 1 3000); do voice cli note-create "פתק גדול $i $(head -c 3000 /dev/urandom | base64 | tr -d '\n')" > /dev/null; done
time voice cli sync now
```

Expected: `completed:`. In the server console count the `POST /sync/apply` lines that arrived during this one sync: there must be **several** (each page is at most about 4 MB). Write the `real` time on the results sheet. Then:

```bash
time voice-adb sync-now
voice-adb list-notes | wc -l
voice cli notes-list | wc -l
```

Expected: `SYNC_NOW OK success received=<about 6000 or more>`; the two counts are equal. Write the time down and whether the phone stayed usable during the sync (try scrolling the notes list on the phone while it runs).

### 4.2 A very large single note

```bash
voice cli note-create "$(printf 'שורה ארוכה מאוד %.0s' $(seq 1 200000))"
voice cli sync now
voice-adb sync-now
voice-adb show-note "שורה ארוכה מאוד שורה ארוכה מאוד" 2>/dev/null | head -c 300
```

Expected: both syncs succeed; the phone has the note (the `show-note` may be ambiguous by first line; if so use `voice-adb list-notes | grep "שורה ארוכה" | head -1` to find its id and `voice-adb show-note <id>`).

### 4.3 Interrupt a large sync on the phone

```bash
adb shell pm clear com.dotancohen.voiceandroid
voice-adb set-device-name Android
voice-adb set-sync http://SERVER:8384 <server-id> Android
voice-adb sync-now &
sleep 3
voice-adb airplane on
wait
```

Expected: the sync prints `SYNC_NOW OK failed error=...` (a network error) or `ERROR`. Then:

```bash
voice-adb airplane off
sleep 20
voice-adb sync-now
voice-adb list-notes | wc -l
voice cli notes-list | wc -l
```

Expected: `SYNC_NOW OK success ...` and the two counts are equal. Write the new Android id on the results sheet (the `pm clear` gave the phone a new one).

---

## 5. Wrong clocks

Clocks decide only "later wins" cases (a tag renamed on two devices, a setting changed on two devices, a transcription flag switched both ways, the metadata of audio files). They must never decide whether data arrives. The README section *Where "later wins"* lists every such case.

### 5.1 The phone a year ahead

Open the phone's date screen from Desktop:

```bash
adb shell am start -a android.settings.DATE_SETTINGS
```

On the phone: switch **Set time automatically** (or **Use network-provided time**) off, tap **Date**, pick the same day next year, tap **OK**. Then:

```bash
voice-adb create-note "פתק מהעתיד"
voice-adb edit-note "פתק אופליין אחד" $'פתק אופליין אחד\nנערך בשנה הבאה'
voice-adb sync-now
voice cli sync now
voice cli notes-list | grep "פתק מהעתיד"
voice cli note-show $(voice cli notes-list | grep "פתק אופליין אחד" | cut -c1-32)
```

Expected: both changes arrived; the dates shown are a year ahead (expected and harmless). Now a rename race with the phone's clock ahead. Without syncing in between:

```bash
voice cli tag-rename <id of עבודה> עבודה-מחשב
voice-adb rename-tag עבודה עבודה-טלפון
```

Do the three-way sync, then `voice cli tags-list` and `voice-adb list-tags`.

Expected: both devices show `עבודה-טלפון` (the phone's clock is later, so it wins), and `voice cli sync conflicts --details` shows a scalar conflict listing both names. Accept it (`voice cli sync resolve <id>`), do the three-way sync.

Restore the phone's clock: `adb shell am start -a android.settings.DATE_SETTINGS`, switch automatic time back on.

### 5.2 Desktop years behind

Preferred way (works when the computer can reach the internet time service):

```bash
sudo timedatectl set-ntp false
sudo timedatectl set-time "2020-01-01 12:00:00"
date
```

If `timedatectl` is not available or the computer cannot reach NTP, set the clock relative to its current value instead (this keeps the offset exact and is reversible):

```bash
sudo date -s "$(date -d '-6 years' '+%Y-%m-%d %H:%M:%S')"
date
```

Expected: `date` prints a date in 2020. Then:

```bash
voice cli note-create "פתק מהעבר"
voice cli sync now
voice-adb sync-now
voice-adb show-note "פתק מהעבר"
```

Expected: the note arrived on the phone; nothing that was synced earlier is missing (`voice cli notes-list | wc -l` on Desktop equals the count from 4.3 plus the notes created since).

Restore the clock. Preferred: `sudo timedatectl set-ntp true` (wait a minute, then `date`). Without NTP: `sudo date -s "$(date -d '+6 years' '+%Y-%m-%d %H:%M:%S')"`; the clock may then be off by the seconds that passed, which is acceptable for testing.

---

## 6. History and restore

Use the note whose first line is `שורה אחת מהמחשב`: it was edited in 2.1, 2.2, 2.3, 2.4 and 2.5, so it has many versions.

```bash
voice cli note-history $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32)
```

Expected: a list with at least 8 versions, oldest first, each with a time, a device name (`Desktop`, `Android`, `Server`, or `merge` for merges), a kind, and the first line; the current one ends with `*`. Copy the id in brackets of the **first** line (the version `שורה אחת`). Then:

```bash
voice cli note-history $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32) --show <that version id>
voice cli note-restore $(voice cli notes-list | grep "שורה אחת מהמחשב" | cut -c1-32) <that version id>
voice cli note-show $(voice cli notes-list | grep "שורה אחת" | cut -c1-32)
```

Expected: `--show` prints exactly `שורה אחת`, `שורה שתיים`, `שורה שלוש`; `note-restore` prints `Restored note ... to version ...`; the note now has that text (its first line is `שורה אחת` again). Do the three-way sync, then:

```bash
voice-adb show-note "שורה אחת"
voice-adb history "שורה אחת"
```

Expected: the phone shows the restored text; `history` lists the same versions plus the restore as the newest one (`"current":true`). On the phone, `voice-adb open-note "שורה אחת"` then tap **History**: the same list, with **Restore this version** buttons on the others. In the GUI (`voice gui`) select the note and click **History…**: the same list.

---

## 7. Things that must never happen

Do these checks at the very end, after a final three-way sync.

### 7.1 Only the conflicts you created exist

```bash
voice cli sync conflicts
voice cli sync conflicts --all
voice-adb list-conflicts
```

Expected: `sync conflicts` prints `No unresolved conflicts.` and `voice-adb list-conflicts` prints `total_unresolved=0`. `--all` lists exactly these eight, all marked `(resolved)`:

| Created in | Kind | Resolved in |
|------------|------|-------------|
| 2.2 | content (note `שורה אחת מהמחשב`) | 2.3, by Resolve… |
| 2.4 | content (same note) | 2.4, by Accept merge on the phone |
| 2.5 | content (same note) | 2.5, by editing in the TUI |
| 2.6 | delete (note `פתק שיימחק`) | 2.6, by `sync resolve` |
| 2.7 | scalar (tag `דחוף` renamed) | 2.7, by `sync resolve` |
| 2.8 | tag link (note `פתק ראשון מהמחשב`, tag `חופשה`) | 2.8, by `accept-conflicts` |
| 2.9 | transcription (`phone1.mp3`) | 2.9, by `accept-conflicts` |
| 5.1 | scalar (tag `עבודה` renamed) | 5.1, by `sync resolve` |

Any other entry is a defect: copy the line to the results sheet.

### 7.2 The same text everywhere

For each of these five notes run `voice cli note-show <id>` on Desktop, `voice cli note-show <id>` on Server (second SSH session), and `voice-adb show-note "<first line>"`, and compare the content word for word:

1. `שורה אחת` (restored in section 6)
2. `פתק ראשון מהמחשב מעודכן`
3. `פתק אופליין אחד`
4. `פתק מהעבר`
5. `phone1.mp3` (compare the transcription text too)

Expected: identical on all three, including the conflict markers left by 2.4 in note 1's history (not in its current text, which was restored in section 6).

### 7.3 The same tags everywhere

```bash
voice cli tags-list
voice-adb list-tags
```

On Server: `voice cli tags-list`. Expected: the same tags with the same parents on all three: `עבודה-טלפון` with `<the renamed tag>` under it, and `חופשה`. No tag appears twice.

### 7.4 No audio file downloaded to the phone without asking

```bash
voice-adb list-notes | grep '"media":\[{' 
```

Expected, per note (the phone was cleared in 4.3, so every file must be `in_cloud_not_downloaded`, including `desktop1.mp3` which you downloaded before the clear and the recording you made in 1.12): every `state` is `in_cloud_not_downloaded`. If any is `local`, write down which note.

### 7.5 Logs

On Server console: no line containing `Error applying` unless a later line says `Applied ... previously failed changes`. On Desktop and Server:

```bash
grep -c "panicked\|database is locked" ~/.config/voice/voice.log
```

Expected: `0` on both.

---

## 8. Not covered yet: CLI and web API on Server

These will get their own plan. Points to settle first:

- The sync server has no authentication and no TLS: anyone who reaches port 8384 can read and write everything. Tests must run on a private network, and the plan will need a step that confirms the port is not exposed.
- The web interface (`voice web`) has no login either. Before testing it from another machine we need to decide whether it binds to localhost only or gets a token.
- `voice cli` commands over SSH act as the Server device: conflicts they create carry the name `Server`.

*(iPhone)* When an iPhone client exists, sections 1 to 6 apply to it unchanged with the device name `iPhone`, and it will need the same kind of automation hook as `voice-adb`.

---

## Results sheet

Copy this block into a new file `results/01-syncing-<date>-<name>.md` and fill it in as you go.

```
Commit:            
Date:              
Tester:            
Desktop id:        
Server id:         
Android id (0.6):  
Android id (3.5):  
Android id (4.3):  
Id of פתק מהטלפון (1.2):   
Conflict 2.2 id:   
Tag name that won in 2.7:  

| Step | Pass/Fail | Exact text seen, log excerpts, notes |
|------|-----------|--------------------------------------|
| 0.2  |           |                                      |
| ...  |           |                                      |
| 7.5  |           |                                      |

1.8 re-imported unchanged files? (yes/no):  
1.12 recording note first line:  
1.12 microphone with the highest peak and where:
1.13 desktop2.mp3 transcription text:  
1.13 desktop3.mp3 transcription text:  
1.14 did the row of the note you left flash, and did the list stay where it was:  
1.15 anything mirrored the wrong way in Hebrew:  
1.16 language and model of the repeated transcription:  
1.17 time of the first note before and after changing timezone:  
1.17 time of the New York note on the phone and on Desktop:  
1.18 did the recording survive home, another app and the lock screen:  
1.18 what happened during the telephone call, on each setting:  
1.18 recordings on the merged note:    
3.3 did the interruption happen in time? (yes/no):  
4.1 Desktop sync time:   
4.1 Android sync time:   
4.1 phone usable during sync? (yes/no):  
```
