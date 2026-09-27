// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Apple-style message field shared by the Messages page and the quick reply
 * window: rounded, grows up to a few lines, Enter sends, Shift+Enter starts a
 * new line, emoji picker on the left and send button on the right. Both round
 * buttons have the same size and margins, so they line up with a one-line field
 * and stay on its last line when it grows.
 *
 * Automatic emojis: a smiley typed as its own word (":)", ":D", "<3"…) becomes
 * an emoji when followed by a space or on sending; Backspace right after puts
 * the text back. Off in apps.conf [messages] auto-emoji=false.
 */

public class Covalence.ComposeField : Gtk.Box {
    public signal void submitted ();

    public Gtk.TextBuffer buffer { get { return view.buffer; } }

    private Gtk.TextView view;
    private Gtk.Label placeholder;
    private Gtk.Button send_button;
    private string? undo_text = null;  // the smiley just replaced, for Backspace
    private int undo_offset = -1;

    private const string[,] SMILEYS = {
        { ":)", "🙂" }, { ":-)", "🙂" }, { ":]", "🙂" }, { ":D", "😃" }, { ":-D", "😃" },
        { "xD", "😆" }, { "XD", "😆" }, { "x)", "😆" }, { ";)", "😉" }, { ";-)", "😉" },
        { ":(", "🙁" }, { ":-(", "🙁" }, { ":'(", "😢" }, { ":P", "😛" }, { ":p", "😛" },
        { ":-P", "😛" }, { ":O", "😮" }, { ":o", "😮" }, { ":*", "😘" }, { "<3", "❤️" },
        { "^^", "😊" }, { ":/", "😕" }, { ":|", "😐" }, { "B)", "😎" }, { "8)", "😎" },
        { ":s", "😖" }, { ":S", "😖" }, { "</3", "💔" }
    };

    public static bool auto_emoji_enabled () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (Path.build_filename (Environment.get_user_config_dir (), "covalence",
                                                       "apps.conf"), KeyFileFlags.NONE);
            return prefs.get_boolean ("messages", "auto-emoji");
        } catch (Error e) {
            return true;
        }
    }

    public static void set_auto_emoji (bool enabled) {
        var path = Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (path, KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_boolean ("messages", "auto-emoji", enabled);
        try {
            DirUtils.create_with_parents (Path.get_dirname (path), 0700);
            prefs.save_to_file (path);
        } catch (Error e) {
            warning ("cannot save the automatic emoji choice: %s", e.message);
        }
    }

    /* The word just before the cursor, if it is a known smiley: replace it by its emoji. */
    private bool replace_smiley () {
        if (!auto_emoji_enabled ()) {
            return false;
        }
        var buf = view.buffer;
        Gtk.TextIter end;
        buf.get_iter_at_mark (out end, buf.get_insert ());
        var start = end;
        while (!start.starts_line ()) {
            var before = start;
            before.backward_char ();
            if (before.get_char ().isspace ()) {
                break;
            }
            start = before;
        }
        var word = buf.get_text (start, end, false);
        for (int i = 0; i < SMILEYS.length[0]; i++) {
            if (word == SMILEYS[i, 0]) {
                var offset = start.get_offset ();
                buf.begin_user_action ();
                buf.delete (ref start, ref end);
                buf.insert (ref start, SMILEYS[i, 1], -1);
                buf.end_user_action ();
                undo_text = word;
                undo_offset = offset;
                return true;
            }
        }
        return false;
    }

    /* Backspace right after a replacement: the smiley text comes back. */
    private bool undo_smiley () {
        if (undo_text == null) {
            return false;
        }
        var buf = view.buffer;
        Gtk.TextIter cursor, start;
        buf.get_iter_at_mark (out cursor, buf.get_insert ());
        buf.get_iter_at_offset (out start, undo_offset);
        var replaced = buf.get_text (start, cursor, false);
        var text = undo_text;
        undo_text = null;
        bool ours = false;
        for (int i = 0; i < SMILEYS.length[0]; i++) {
            if (SMILEYS[i, 0] == text && (replaced == SMILEYS[i, 1] || replaced == SMILEYS[i, 1] + " ")) {
                ours = true;
                break;
            }
        }
        if (!ours) {
            return false;
        }
        buf.begin_user_action ();
        buf.delete (ref start, ref cursor);
        buf.insert (ref start, replaced.has_suffix (" ") ? text + " " : text, -1);
        buf.end_user_action ();
        return true;
    }

    public ComposeField () {
        Object (orientation: Gtk.Orientation.HORIZONTAL, spacing: 2);
    }

    construct {
        add_css_class ("compose-field");

        view = new Gtk.TextView () {
            hexpand = true,
            wrap_mode = Gtk.WrapMode.WORD_CHAR,
            accepts_tab = false,
            top_margin = 8,
            bottom_margin = 8,
            left_margin = 4,
            right_margin = 4,
            valign = Gtk.Align.CENTER
        };
        view.add_css_class ("compose-text");
        view.update_property (Gtk.AccessibleProperty.LABEL, _("Message texte"), -1);
        var keys = new Gtk.EventControllerKey ();
        keys.key_pressed.connect ((keyval, keycode, state) => {
            if (keyval == Gdk.Key.BackSpace && undo_smiley ()) {
                return true;
            }
            var keep_undo = false;
            if (keyval == Gdk.Key.space) {
                keep_undo = replace_smiley ();
            }
            if ((keyval == Gdk.Key.Return || keyval == Gdk.Key.KP_Enter)
                && (state & Gdk.ModifierType.SHIFT_MASK) == 0) {
                replace_smiley ();
                undo_text = null;
                if (text () != "") {
                    submitted ();
                }
                return true;
            }
            if (!keep_undo && keyval != Gdk.Key.Shift_L && keyval != Gdk.Key.Shift_R) {
                undo_text = null;
            }
            return false;
        });
        view.add_controller (keys);

        placeholder = new Gtk.Label (_("Message texte")) {
            xalign = 0,
            margin_start = 5,
            can_target = false
        };
        placeholder.add_css_class (Granite.CssClass.DIM);
        var overlay = new Gtk.Overlay () { child = view };
        overlay.add_overlay (placeholder);
        var scroll = new Gtk.ScrolledWindow () {
            child = overlay,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            propagate_natural_height = true,
            max_content_height = 140,
            hexpand = true,
            valign = Gtk.Align.CENTER
        };

        var chooser = new Gtk.EmojiChooser ();
        chooser.emoji_picked.connect ((emoji) => {
            view.buffer.insert_at_cursor (emoji, -1);
            view.grab_focus ();
        });
        var emoji_button = new Gtk.MenuButton () {
            icon_name = "face-smile-symbolic",
            popover = chooser,
            tooltip_text = _("Émoji"),
            valign = Gtk.Align.END
        };
        emoji_button.add_css_class ("compose-round");
        emoji_button.add_css_class ("compose-emoji");

        send_button = new Gtk.Button.from_icon_name ("go-up-symbolic") {
            sensitive = false,
            tooltip_text = _("Envoyer (Entrée)"),
            valign = Gtk.Align.END
        };
        send_button.add_css_class ("circular");
        send_button.add_css_class (Granite.CssClass.SUGGESTED);
        send_button.add_css_class ("compose-round");
        send_button.clicked.connect (() => {
            replace_smiley ();
            undo_text = null;
            if (text () != "") {
                submitted ();
            }
        });

        view.buffer.changed.connect (() => {
            placeholder.visible = view.buffer.text == "";
            send_button.sensitive = text () != "";
        });

        append (emoji_button);
        append (scroll);
        append (send_button);
    }

    public string text () {
        return view.buffer.text.strip ();
    }

    public override bool grab_focus () {
        return view.grab_focus ();
    }
}
