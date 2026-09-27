// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Quick reply, opened by "Répondre" in a message notification. elementary's
 * notification server has no inline reply (its capabilities are actions, body
 * and markup only), and on gala's Wayland session an app cannot place a window
 * under the notification bubble (no layer-shell; pantheon panels only anchor at
 * the top or bottom centre; XWayland would be blurry at 166 %). So this window
 * looks like the notification unfolded: a compact card without a title bar,
 * the same header, the last messages and the field. Enter sends and closes;
 * clicking elsewhere with nothing typed closes it too.
 */

public class Covalence.QuickReply : Gtk.Window {
    public string thread_id { get; construct; }

    private Daemon daemon;
    private Avatar avatar;
    private Gtk.Label title_label;
    private Gtk.Box recent;
    private ComposeField field;
    private Gtk.ProgressBar bar;
    private Gtk.Label status;
    private Gtk.Stack bottom;
    private Gtk.Label limit;
    private Gtk.ScrolledWindow canned;

    public QuickReply (Gtk.Application app, string thread_id) {
        Object (application: app, thread_id: thread_id, title: _("Répondre"),
                default_width: 380, resizable: false);
    }

    construct {
        add_css_class ("quick-reply");
        // An empty title bar keeps the rounded corners and shadow of the window
        // without showing a bar: the card itself carries the header.
        titlebar = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { visible = false };

        avatar = new Avatar (36);
        title_label = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
        title_label.add_css_class ("quick-reply-title");
        var app_label = new Gtk.Label (_("Messages · Covalence")) { xalign = 0 };
        app_label.add_css_class (Granite.CssClass.DIM);
        app_label.add_css_class (Granite.CssClass.SMALL);
        var names = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { hexpand = true, valign = Gtk.Align.CENTER };
        names.append (title_label);
        names.append (app_label);
        var close_button = new Gtk.Button.from_icon_name ("window-close-symbolic") {
            valign = Gtk.Align.START,
            tooltip_text = _("Fermer (Échap)")
        };
        close_button.add_css_class ("circular");
        close_button.add_css_class ("flat");
        close_button.clicked.connect (() => close ());
        var header = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 10) {
            margin_top = 12,
            margin_start = 12,
            margin_end = 8
        };
        header.append (avatar);
        header.append (names);
        header.append (close_button);

        recent = new Gtk.Box (Gtk.Orientation.VERTICAL, 4) {
            margin_top = 6,
            margin_start = 12,
            margin_end = 12
        };

        bar = new Gtk.ProgressBar () { visible = false };
        bar.add_css_class ("send-bar");
        status = new Gtk.Label ("") { wrap = true, xalign = 0, visible = false, margin_start = 12 };
        status.add_css_class (Granite.CssClass.SMALL);

        field = new ComposeField ();
        field.submitted.connect (send);

        // Ready-made answers: one click puts them in the field, Enter sends.
        var chips = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        foreach (var answer in new string[] {
            _("J'arrive"), _("Je te rappelle"), _("OK 👍"), _("Merci !"), _("Je suis occupé, je te réponds vite")
        }) {
            var chip = new Gtk.Button.with_label (answer);
            chip.add_css_class ("quick-answer");
            chip.clicked.connect (() => {
                field.buffer.text = answer;
                field.grab_focus ();
            });
            chips.append (chip);
        }
        canned = new Gtk.ScrolledWindow () {
            child = chips,
            vscrollbar_policy = Gtk.PolicyType.NEVER,
            hscrollbar_policy = Gtk.PolicyType.EXTERNAL,
            margin_start = 12,
            margin_end = 12
        };
        limit = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
        limit.add_css_class (Granite.CssClass.DIM);
        limit.add_css_class (Granite.CssClass.SMALL);
        bottom = new Gtk.Stack () { vhomogeneous = false };
        bottom.add_named (field, "field");
        bottom.add_named (limit, "limit");

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 8) { margin_bottom = 12 };
        content.append (header);
        content.append (bar);
        content.append (recent);
        content.append (status);
        content.append (canned);
        var bottom_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) {
            margin_start = 12,
            margin_end = 12
        };
        bottom_box.append (bottom);
        content.append (bottom_box);
        child = content;

        var keys = new Gtk.EventControllerKey ();
        keys.key_pressed.connect ((keyval) => {
            if (keyval == Gdk.Key.Escape) {
                close ();
                return true;
            }
            return false;
        });
        ((Gtk.Widget) this).add_controller (keys);

        // Like a notification: clicking elsewhere dismisses it, unless something is typed.
        notify["is-active"].connect (() => {
            if (!is_active && field.text () == "" && field.sensitive) {
                close ();
            }
        });

        daemon = new Daemon ();
        daemon.send_progress.connect ((thread, id, fraction) => {
            if (thread == thread_id) {
                bar.visible = true;
                bar.fraction = fraction.clamp (0.0, 1.0);
            }
        });
        load.begin ();
    }

    private async void load () {
        yield daemon.connect_bus ();
        foreach (var item in yield daemon.call_list ("ListThreads")) {
            var d = new VariantDict (item);
            if (dict_string (d, "id") != thread_id) {
                continue;
            }
            var name = dict_string (d, "name");
            var group = dict_bool (d, "group");
            title_label.label = name;
            avatar.show_person (name, dict_string (d, "avatar"), group);
            if (group || !dict_bool (d, "can_send")) {
                canned.visible = false;
                limit.label = group ? _("Répondez aux groupes depuis l'iPhone.")
                                    : _("Pas de numéro de téléphone : répondez depuis l'iPhone.");
                bottom.visible_child_name = "limit";
            }
        }
        var messages = yield daemon.call_list ("GetMessages", new Variant ("(s)", thread_id));
        int first = int.max (0, messages.length - 3);
        for (int i = first; i < messages.length; i++) {
            var d = new VariantDict (messages[i]);
            var outgoing = dict_bool (d, "outgoing");
            var bubble = new Gtk.Label (dict_string (d, "body")) {
                wrap = true,
                wrap_mode = Pango.WrapMode.WORD_CHAR,
                xalign = 0,
                max_width_chars = 40,
                selectable = true,
                halign = outgoing ? Gtk.Align.END : Gtk.Align.START
            };
            bubble.add_css_class ("bubble");
            bubble.add_css_class (outgoing ? "outgoing" : "incoming");
            recent.append (bubble);
        }
        field.grab_focus ();
    }

    private void send () {
        var text = field.text ();
        if (text == "") {
            return;
        }
        field.sensitive = false;
        status.visible = false;
        bar.visible = true;
        bar.fraction = 0.02;
        daemon.call_send.begin ("SendMessage", new Variant ("(ss)", thread_id, text), (obj, res) => {
            if (daemon.call_send.end (res)) {
                daemon.call.begin ("MarkThreadSeen", new Variant ("(s)", thread_id));
                close ();
                return;
            }
            // The daemon kept the message in the thread as "not sent".
            field.buffer.text = "";
            field.sensitive = true;
            bar.visible = false;
            status.label = _("Non envoyé : le message est gardé dans la conversation, "
                           + "où vous pourrez le renvoyer.");
            status.add_css_class (Granite.CssClass.ERROR);
            status.visible = true;
        });
    }
}
