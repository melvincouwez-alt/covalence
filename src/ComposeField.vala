// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Apple-style message field shared by the Messages page and the quick reply
 * window: rounded, grows up to a few lines, Enter sends, Shift+Enter starts a
 * new line, emoji picker on the left and send button on the right. Both round
 * buttons have the same size and margins, so they line up with a one-line field
 * and stay on its last line when it grows.
 */

public class Covalence.ComposeField : Gtk.Box {
    public signal void submitted ();

    public Gtk.TextBuffer buffer { get { return view.buffer; } }

    private Gtk.TextView view;
    private Gtk.Label placeholder;
    private Gtk.Button send_button;

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
            if ((keyval == Gdk.Key.Return || keyval == Gdk.Key.KP_Enter)
                && (state & Gdk.ModifierType.SHIFT_MASK) == 0) {
                if (text () != "") {
                    submitted ();
                }
                return true;
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
