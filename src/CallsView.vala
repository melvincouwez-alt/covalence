// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Calls: the iPhone's call history read over PBAP (read only), newest first,
 * with missed calls in red, and buttons to call back (HFP, on click only) or
 * to write a message.
 */

namespace Covalence {
    public const string CALLS_UNAVAILABLE =
        N_("Les appels demandent PipeWire 1.4 ou plus récent.");

    /* PipeWire before 1.4 has no hands-free telephony API. */
    public bool calls_unavailable (Daemon daemon) {
        return daemon.running && !daemon.get_bool ("CallsSupported");
    }
}

public class Covalence.CallsView : Gtk.Box {
    public Daemon daemon { get; construct; }
    public bool with_dialer { get; construct; }
    public signal void message_requested (string address);

    private Gtk.ListBox list;
    private Gtk.Stack stack;
    private Granite.Toast toast;
    private Gtk.Label unavailable;
    private Gtk.MenuButton compose;

    public CallsView (Daemon daemon, bool with_dialer = true) {
        Object (daemon: daemon, with_dialer: with_dialer, orientation: Gtk.Orientation.VERTICAL,
                spacing: 0);
    }

    construct {
        list = new Gtk.ListBox () {
            selection_mode = Gtk.SelectionMode.NONE,
            show_separators = true,
            width_request = 480,
            halign = Gtk.Align.CENTER,
            margin_top = 18,
            margin_bottom = 18,
            valign = Gtk.Align.START
        };
        list.add_css_class (Granite.CssClass.CARD);
        var scroll = new Gtk.ScrolledWindow () {
            child = list,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
        var empty = new Granite.Placeholder (_("Aucun appel")) {
            description = _("Le journal d'appels vient de l'iPhone. Activez « Synchroniser les "
                          + "contacts » pour ce PC dans les réglages Bluetooth de l'iPhone."),
            icon = new ThemedIcon (Config.APP_ID + ".Phone")
        };
        stack = new Gtk.Stack ();
        stack.add_named (scroll, "list");
        stack.add_named (empty, "empty");
        unavailable = new Gtk.Label (_(CALLS_UNAVAILABLE)) {
            wrap = true,
            justify = Gtk.Justification.CENTER,
            margin_top = 12,
            margin_start = 12,
            margin_end = 12,
            visible = false
        };
        unavailable.add_css_class (Granite.CssClass.DIM);
        append (unavailable);
        compose = new Gtk.MenuButton () {
            popover = new DialPopover (daemon),
            halign = Gtk.Align.CENTER,
            margin_top = 12
        };
        var compose_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        compose_box.append (new Gtk.Image.from_icon_name ("input-dialpad-symbolic"));
        compose_box.append (new Gtk.Label (_("Composer un numéro")));
        compose.child = compose_box;
        if (with_dialer) {
            append (compose);
        }

        toast = new Granite.Toast ("");
        var overlay = new Gtk.Overlay () { child = stack, vexpand = true };
        overlay.add_overlay (toast);
        append (overlay);

        daemon.calls_changed.connect (() => reload.begin ());
        daemon.changed.connect (update_buttons);
        map.connect (() => reload.begin ());
    }

    private async void reload () {
        var items = yield daemon.call_list ("ListCalls");
        Gtk.Widget? child;
        while ((child = list.get_first_child ()) != null) {
            list.remove (child);
        }
        foreach (var item in items) {
            list.append (row (new VariantDict (item)));
        }
        stack.visible_child_name = items.length > 0 ? "list" : "empty";
        update_buttons ();
    }

    private Gtk.Widget row (VariantDict d) {
        var address = dict_string (d, "address");
        var name = dict_string (d, "name");
        var kind = dict_string (d, "kind");

        var avatar = new Avatar (36);
        avatar.show_person (name, dict_string (d, "avatar"));
        var name_label = new Gtk.Label (name) { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
        if (kind == "missed") {
            name_label.add_css_class (Granite.CssClass.ERROR);
        }
        string kind_text = kind == "missed" ? _("Manqué") : kind == "dialed" ? _("Sortant") : _("Entrant");
        var icon = new Gtk.Image.from_icon_name (
            kind == "missed" ? "call-missed-symbolic"
            : kind == "dialed" ? "call-outgoing-symbolic" : "call-incoming-symbolic");
        icon.add_css_class (Granite.CssClass.DIM);
        var detail = new Gtk.Label ("%s · %s".printf (kind_text, long_time (dict_int64 (d, "time")))) {
            xalign = 0
        };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var detail_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 4);
        detail_box.append (icon);
        detail_box.append (detail);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (name_label);
        text.append (detail_box);

        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 10) {
            margin_top = 6,
            margin_bottom = 6,
            margin_start = 12,
            margin_end = 8
        };
        box.append (avatar);
        box.append (text);
        if (address != "") {
            var write = new Gtk.Button.from_icon_name ("mail-message-new-symbolic") {
                tooltip_text = _("Envoyer un message"),
                valign = Gtk.Align.CENTER
            };
            write.add_css_class ("flat");
            write.clicked.connect (() => message_requested (address));
            var dial = new CallButton (daemon, address, toast);
            box.append (write);
            box.append (dial);
        }
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private void update_buttons () {
        // CallButton widgets follow CallsLinked themselves.
        var off = calls_unavailable (daemon);
        unavailable.visible = off;
        compose.sensitive = !off;
    }
}

/* Calls a number from the iPhone through the hands-free link, only when clicked. */
public class Covalence.CallButton : Gtk.Button {
    public delegate string NumberSource ();

    public Daemon daemon { get; construct; }
    public string number { get; construct; }
    public Granite.Toast? toast { get; construct; }
    public NumberSource? number_source = null;
    public signal void dialled ();

    public CallButton (Daemon daemon, string number, Granite.Toast? toast) {
        Object (daemon: daemon, number: number, toast: toast, icon_name: "call-start-symbolic",
                valign: Gtk.Align.CENTER);
    }

    construct {
        add_css_class ("flat");
        clicked.connect (() => {
            var target = number_source != null ? number_source () : number;
            if (only_digits (target).length < 2) {
                return;
            }
            sensitive = false;
            daemon.call_send.begin ("Dial", new Variant ("(s)", target), (obj, res) => {
                var ok = daemon.call_send.end (res);
                if (ok) {
                    dialled ();
                } else if (toast != null) {
                    toast.title = _("Appel impossible : l'iPhone n'est pas relié en mains libres");
                    toast.send_notification ();
                }
                update ();
            });
        });
        daemon.changed.connect (update);
        update ();
    }

    private void update () {
        var ready = daemon.get_bool ("CallsLinked");
        sensitive = ready;
        tooltip_text = ready ? _("Appeler depuis l'iPhone")
                     : calls_unavailable (daemon) ? _(CALLS_UNAVAILABLE)
                     : _("Appel indisponible : l'iPhone n'est pas relié en mains libres");
    }
}
