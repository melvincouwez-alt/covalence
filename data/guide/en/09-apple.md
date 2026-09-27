title: Apple Account
icon: preferences-desktop-online-accounts
summary: Mail, calendars, reminders, contacts, iCloud Drive and Photos.
---
## Mail, calendars, reminders and contacts
These services use an **app-specific password**, not your Apple Account password.
1. On account.apple.com: **Sign-In and Security › App-Specific Passwords**, then create one named "Covalence".
2. In [Apple Services](app:services), click **Sign in…**
3. Enter your Apple Account email and that password. Covalence checks it with Apple and stores it in your session keyring.
4. Your accounts show up in Mail, Tasks and Calendar.

To remove everything: **Disconnect** in Apple Services, then revoke the app-specific password on account.apple.com.

## iCloud Drive and iCloud Photos
Both go through **rclone**, a free tool that signs in the way the icloud.com website does.

!warn Read this before signing in. It needs your **Apple Account password** and a code shown on the iPhone. Apple does not officially offer this access: its iCloud terms restrict automated access and allow Apple to suspend an account. **Advanced Data Protection** must also be turned off, which reduces end-to-end encryption of your iCloud data. Use this feature at your own risk.

1. In Apple Services, click **Connect…** next to iCloud Drive.
2. Enter your Apple Account password, then the six-digit code shown on the iPhone.
3. The **iCloud Drive** folder shows up in your home folder and in Files.
4. For photos: **Connect…** next to iCloud Photos. The **iCloud Photos** folder shows up in your Pictures, read-only. Each album is a folder.

- The options (gear button) set the location, mounting at login, read-only mode, the space used offline and how soon changes show up.
- Covalence does not do a full two-way sync: a conflict or a mass deletion could lose files.
- About once a month, Apple asks to confirm the sign-in again: **Reconnect…** in Apple Services, with a new code.
- rclone 1.69 or newer is needed. If your system has an older one, the Missing components card says so.
