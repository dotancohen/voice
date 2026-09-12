Questions to Plan This Correctly

1. Platform Scope

- Is iOS also required, or Android-only? This significantly affects framework choice.
- What minimum Android version should be supported? (API 21/Android 5.0? API 26/Android 8.0?)
- Do you need tablet support or phone-only?

2. Sync Architecture

- The current sync protocol uses HTTP/REST. Will the mobile app act as a client-only, or should it also be able to serve as a sync server?
- How should sync behave on mobile data vs WiFi? (Auto-sync only on WiFi? User-controlled?)
- What's the expected data volume per sync? This matters for battery and bandwidth.
- How will conflict resolution work on mobile? The current CLI has sync resolve - do you need a mobile UI for this?

3. Media Files

- What audio formats need playback support? (MP3, WAV, FLAC, OGG, M4A?)
- What video formats? (MP4, MOV, WebM?)
- What's the expected file size range? (Voice notes are small, but video can be huge)
- Should media files sync automatically, or on-demand? (Sync metadata only, download files when accessed?)
- Where will media files be stored? On each sync server? Separate object storage (S3, etc.)?

4. Media Editing

- What audio editing features? (Trim, split, merge, speed adjustment, noise reduction?)
- What video editing features? (Trim, cut scenes, add text overlays, merge clips?)
- Does editing happen locally, server-side, or both?
- How should edited files relate to originals? (Replace? Keep both? Version history?)

5. Offline Functionality

- Should the app be fully functional offline? (Create notes, record, edit, queue for sync?)
- How much local storage should be assumed available?
- Should there be selective sync? (Sync only certain tags/folders to mobile?)

6. Authentication & Security

- Is there currently any authentication on the sync protocol? (I didn't see any in the README)
- Do you need user accounts, or is it device-based like now?
- Should media files be encrypted at rest on the device?
- Is end-to-end encryption required?

7. Recording & Transcription

- Should the app include voice recording? (You mention Axet Audio Recorder as external)
- Will transcription happen on-device, server-side, or cloud API?
- Is real-time transcription needed, or post-recording only?

8. User Experience

- Should the mobile app have feature parity with desktop, or a focused subset?
- Is the tag hierarchy UI suitable for mobile, or does it need adaptation?
- RTL support is in desktop - is it needed on mobile?
- Dark/light theme support?

9. Background Operations

- Should sync happen in background when app is closed?
- Should audio/video continue playing when app is backgrounded?
- Push notifications when sync completes or conflicts arise?

10. Technical Infrastructure

- What's your team's experience? (Python is current - any Kotlin, Dart, or React Native experience?)
- Is there a backend team separate from mobile?
- Do you have CI/CD infrastructure for mobile builds?
- Play Store distribution, or also sideloading/F-Droid?

11. Database

- SQLite is used now. Will mobile share the schema exactly?
- The sync protocol syncs notes and tags. Does it need extension for media metadata?
- Are there plans for a different database on mobile? (Room wraps SQLite nicely on Android)

12. Performance Requirements

- How many notes/media files should the app handle comfortably? (100? 10,000? 100,000?)
- What's acceptable sync time for a typical update?
- Battery consumption constraints?


