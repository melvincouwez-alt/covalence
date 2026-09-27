title: Privacy
icon: preferences-system-privacy
summary: What Covalence keeps, where, and how to erase it.
---
Covalence runs entirely on your computer. Its author runs no server and receives no data: no Covalence account, no telemetry, no usage statistics, no crash reports sent anywhere.

## Data handled
- Received from the iPhone over Bluetooth: notifications, messages (text, sender, date), contacts, call history, music and battery state.
- Exchanged directly with Apple: iCloud mail, calendars, reminders, contacts, files and photos.

## Where it is kept
- Message and contact cache: `~/.local/share/covalence/`, readable by your account only.
- Settings: `~/.config/covalence/`. The iCloud Drive configuration there is encrypted.
- Passwords and keys: your session keyring.
- iCloud accounts: handled by the system (Evolution Data Server).
- Covalence's logs never contain message text or phone numbers.

## Network access
Apart from iCloud, Covalence only reaches public Apple services, with no account:
- icons of the iPhone apps that send notifications: only the app's identifier is sent (for example `net.whatsapp.WhatsApp`), never the content of a notification. Cache: `~/.cache/covalence/app-icons/`. To turn it off: `app-icons=false` in the `[notifications]` group of `~/.config/covalence/covalenced.conf`;
- [Now Playing](guide:sound) artwork: only the artist and the title are sent. Cache: `~/.cache/covalence/artwork/`. To turn it off: `artwork=false` in the `[media]` group of the same file;
- downloading rclone, only when you ask for it.

## Erase everything
1. In Apple Services, disconnect iCloud Drive, iCloud Photos and the account.
2. Delete the `~/.local/share/covalence/`, `~/.config/covalence/` and `~/.cache/covalence/` folders.
3. In the Passwords and Keys app, delete the Covalence and iCloud entries.

Uninstalling the package does not remove these files. Your contacts' messages and details remain your responsibility: do not share these folders.
