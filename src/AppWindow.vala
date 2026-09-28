// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Messages and Contacts as apps of their own: same program, launched as
 * io.github.melvincouwez.Covalence.Messages or .Contacts (symlinks), so each has
 * its own dock icon, launcher entry and window. Covalence itself keeps the iPhone
 * settings and the call history.
 */

namespace Covalence {
    public enum Mode {
        HUB, MESSAGES, CONTACTS, PHONE, HEADPHONES, MIRROR;

        public string suffix () {
            switch (this) {
                case MESSAGES: return ".Messages";
                case CONTACTS: return ".Contacts";
                case PHONE: return ".Phone";
                case HEADPHONES: return ".Headphones";
                case MIRROR: return ".Mirror";
                default: return "";
            }
        }

        /* Messages and Écouteurs use elementary's own icons (d9ecca9): their
           Covalence SVGs are gone, so the app id is no icon name for them. */
        public string icon_name () {
            switch (this) {
                case MESSAGES: return "internet-chat";
                case HEADPHONES: return "audio-headphones";
                default: return Config.APP_ID + suffix ();
            }
        }

        public string title () {
            switch (this) {
                case MESSAGES: return _("Messages");
                case CONTACTS: return _("Contacts");
                case PHONE: return _("Téléphone");
                case HEADPHONES: return _("Écouteurs");
                case MIRROR: return _("Recopie");
                default: return "Covalence";
            }
        }

        public string guide_topic () {
            switch (this) {
                case MESSAGES: return "messages";
                case CONTACTS: return "contacts";
                case PHONE: return "phone";
                case HEADPHONES: return "headphones";
                case MIRROR: return "mirror";
                default: return "welcome";
            }
        }

        public static Mode from_program (string program) {
            var name = Path.get_basename (program);
            if (name.has_suffix (".Messages")) {
                return MESSAGES;
            }
            if (name.has_suffix (".Contacts")) {
                return CONTACTS;
            }
            if (name.has_suffix (".Phone")) {
                return PHONE;
            }
            if (name.has_suffix (".Headphones")) {
                return HEADPHONES;
            }
            if (name.has_suffix (".Mirror")) {
                return MIRROR;
            }
            return HUB;
        }
    }

    /* Start (or reach) one of the three apps with the given arguments. */
    public void launch (Mode mode, string[] args = {}) {
        string[] argv = { Path.build_filename (Config.BINDIR, Config.APP_ID + mode.suffix ()) };
        foreach (var a in args) {
            argv += a;
        }
        try {
            new Subprocess.newv (argv, SubprocessFlags.NONE);
        } catch (Error e) {
            warning ("cannot start %s: %s", argv[0], e.message);
        }
    }

    public class AppWindow : Gtk.ApplicationWindow {
        public Mode mode { get; construct; }

        private Daemon daemon;
        private MessagesView? messages = null;

        public AppWindow (Gtk.Application app, Mode mode) {
            Object (application: app, mode: mode,
                    title: mode.title (),
                    default_width: mode == Mode.CONTACTS ? 760 : mode == Mode.HEADPHONES ? 620
                                   : mode == Mode.MIRROR ? 640 : 900,
                    default_height: 640);
        }

        construct {
            var header = new Gtk.HeaderBar ();
            header.add_css_class ("flat");
            header.title_widget = new Gtk.Label (title);
            ((Gtk.Label) header.title_widget).add_css_class ("title");
            header.pack_end (Guide.help_button (mode.guide_topic (), _("Guide (F1)")));
            titlebar = header;

            daemon = new Daemon ();
            Gtk.Widget content;
            if (mode == Mode.MESSAGES) {
                messages = new MessagesView (daemon);
                content = messages;
                notify["is-active"].connect (() => {
                    if (is_active) {
                        messages.window_activated ();
                    } else {
                        messages.update_viewing ();
                    }
                });
            } else if (mode == Mode.PHONE) {
                var phone = new PhoneView (daemon);
                phone.history.message_requested.connect ((address) => launch (Mode.MESSAGES, { "--to", address }));
                content = phone;
                // Looking at the call history clears the missed-calls badge.
                notify["is-active"].connect (() => {
                    if (is_active) {
                        daemon.call.begin ("MarkCallsSeen");
                    }
                });
            } else if (mode == Mode.HEADPHONES) {
                content = new HeadphonesView (daemon);
            } else if (mode == Mode.MIRROR) {
                content = new MirrorView (daemon);
            } else {
                var contacts = new ContactsView (daemon);
                contacts.message_requested.connect ((address) => launch (Mode.MESSAGES, { "--to", address }));
                content = contacts;
            }
            // The ongoing call is shown at the top of every Covalence window.
            var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
            box.append (new CallBar (daemon));
            content.vexpand = true;
            box.append (content);
            child = box;
            daemon.connect_bus.begin ();
        }

        public void open_thread (string thread) {
            if (messages != null) {
                messages.open_thread (thread, false);
            }
        }

        public void write_to (string address) {
            if (messages != null) {
                messages.start_conversation (address);
            }
        }
    }
}
