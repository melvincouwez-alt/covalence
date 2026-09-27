title: Troubleshooting
icon: dialog-question
summary: Common problems and what to try.
---
### "The Covalence service is not responding"
The background service is stopped. Open a Terminal and type `systemctl --user restart covalenced`. Its log: `journalctl --user -u covalenced`.

### The iPhone does not reconnect
1. Check that Bluetooth is on, on both sides.
2. Click **Reconnect** in the [Overview](app:device).
3. Otherwise, on the iPhone: Settings › Bluetooth, tap the computer's name.
4. As a last resort, forget the device on both sides and [pair](guide:link) again.

### No notifications
The low energy link is not open. Open nRF Connect on the iPhone and tap **Connect** next to "Covalence". Also check **Share System Notifications**.

### The iPhone refuses messages
Turn on **Show Notifications** (Settings › Bluetooth › ⓘ), then click **Check** in the setup.

### A message shows twice
Delete the extra copy (right-click, **Delete from Covalence**). If it happens again, report it on the project page.

### A message only shows its beginning
That is intended until it is read on the iPhone. See [Messages](guide:messages).

### A call has no sound
During the call, turn on **PC audio**. Check the output and microphone in System Settings › Sound.

### No calls at all
On elementary OS 8, calls are not available (PipeWire too old). See [Phone](guide:phone).

### iCloud Drive or Photos is empty
Apple probably wants the sign-in confirmed again: **Reconnect…** in [Apple Services](app:services). Log: `journalctl --user -u covalence-icloud-drive`.

### "rclone not found" or too old
rclone 1.69 or newer is needed. Follow the **Missing components** card in [Settings](app:settings).

### The earbuds stay on "reading state"
Put the earbuds back in the case, close it, then open it again near the computer.

### Report a problem
Open an issue on the project page (Issues tab). Describe what you were doing, without pasting your messages or numbers.
