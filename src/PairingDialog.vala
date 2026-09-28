// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Guided pairing: opens the daemon's pairing window, shows the numeric
 * comparison code and reports the outcome.
 */

public class Covalence.PairingDialog : Gtk.Window {
    public Daemon daemon { get; construct; }

    private Gtk.Stack stack;
    private Gtk.Label code_label;
    private Gtk.Label code_hint;
    private Gtk.Box confirm_box;
    private bool code_seen = false;
    private bool finished = false;
    private bool started = false;

    public PairingDialog (Gtk.Window parent, Daemon daemon) {
        Object (
            daemon: daemon,
            transient_for: parent,
            modal: true,
            title: _("Appairer un iPhone"),
            default_width: 440,
            resizable: false
        );
    }

    construct {
        var header = new Gtk.HeaderBar ();
        header.add_css_class ("flat");
        titlebar = header;

        // Step list
        var steps = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        var title = new Gtk.Label (_("Appairer un iPhone")) { xalign = 0 };
        title.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
        steps.append (title);
        steps.append (step (1, _("Gardez l'iPhone déverrouillé, à côté de ce PC.")));
        var pc_name = daemon.get_string ("AdapterName");
        if (pc_name == "") {
            pc_name = Environment.get_host_name ();
        }
        steps.append (step (2, _("Sur l'iPhone, ouvrez Réglages › Bluetooth et touchez « %s » "
                            + "sous Autres appareils.").printf (pc_name)));
        steps.append (step (3, _("Comparez le code ci-dessous avec celui de l'iPhone. S'ils sont "
                            + "identiques, touchez « Jumeler » sur l'iPhone et « Le code correspond » "
                            + "ici.")));
        steps.append (step (4, _("Acceptez le partage des notifications et des contacts si l'iPhone "
                            + "le demande.")));

        code_label = new Gtk.Label ("······") {
            margin_top = 12,
            selectable = true
        };
        code_label.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());
        code_label.add_css_class ("numeric");
        code_hint = new Gtk.Label (_("En attente de l'iPhone…"));
        code_hint.add_css_class (Granite.CssClass.DIM);
        var spinner = new Gtk.Spinner () { spinning = true };
        var waiting = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { halign = Gtk.Align.CENTER };
        waiting.append (spinner);
        waiting.append (code_hint);
        steps.append (code_label);
        steps.append (waiting);

        // Nothing is paired until the user says the codes match: a device nearby could
        // otherwise pair on its own while the PC is visible.
        var match_button = new Gtk.Button.with_label (_("Le code correspond"));
        match_button.add_css_class (Granite.CssClass.SUGGESTED);
        match_button.clicked.connect (() => answer (true));
        var refuse_button = new Gtk.Button.with_label (_("Codes différents"));
        refuse_button.clicked.connect (() => answer (false));
        confirm_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            halign = Gtk.Align.CENTER,
            visible = false
        };
        confirm_box.append (refuse_button);
        confirm_box.append (match_button);
        steps.append (confirm_box);

        var done_page = new Granite.Placeholder (_("C'est fait")) {
            description = _("L'iPhone est appairé. Ses notifications arriveront ici, "
                          + "et les appels dès que le profil mains libres sera connecté."),
            icon = new ThemedIcon ("process-completed")
        };
        var failed_page = new Granite.Placeholder (_("L'appairage n'a pas abouti")) {
            description = _("Le délai est écoulé. Vérifiez que le Bluetooth de l'iPhone est actif, "
                          + "puis recommencez."),
            icon = new ThemedIcon ("dialog-warning")
        };

        stack = new Gtk.Stack () {
            transition_type = Gtk.StackTransitionType.CROSSFADE,
            vhomogeneous = false
        };
        stack.add_named (steps, "steps");
        stack.add_named (done_page, "done");
        stack.add_named (failed_page, "failed");

        var close_button = new Gtk.Button.with_label (_("Annuler"));
        close_button.clicked.connect (() => close ());
        var actions = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            halign = Gtk.Align.END,
            margin_top = 12
        };
        actions.append (close_button);

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_start = 24,
            margin_end = 24,
            margin_bottom = 24
        };
        content.append (stack);
        content.append (actions);
        child = content;

        daemon.pairing_code.connect ((passkey) => {
            code_seen = true;
            code_label.label = "%06u".printf (passkey);
            code_hint.label = _("Le même code doit s'afficher sur l'iPhone");
            confirm_box.visible = true;
        });
        daemon.pairing_code_answered.connect ((matches) => {
            confirm_box.visible = false;
            code_hint.label = matches ? _("Code confirmé, appairage en cours…")
                                      : _("Code refusé. Recommencez depuis l'iPhone si besoin.");
        });
        daemon.changed.connect (() => {
            if (daemon.get_bool ("Pairing")) {
                started = true;
                return;
            }
            if (finished || !started) {
                return;
            }
            finished = true;
            var ok = code_seen && daemon.get_bool ("Paired");
            stack.visible_child_name = ok ? "done" : "failed";
            close_button.label = _("Fermer");
            if (ok) {
                close_button.add_css_class (Granite.CssClass.SUGGESTED);
            }
        });
        close_request.connect (() => {
            if (!finished) {
                daemon.call.begin ("StopPairing");
            }
            return false;
        });

        daemon.call.begin ("StartPairing", null, (obj, res) => {
            if (!daemon.call.end (res)) {
                finished = true;
                stack.visible_child_name = "failed";
            }
        });
    }

    private void answer (bool matches) {
        confirm_box.visible = false;
        daemon.call.begin ("ConfirmPairing", new Variant ("(b)", matches));
    }

    private Gtk.Widget step (int number, string text) {
        var badge = new Gtk.Label (number.to_string ()) { valign = Gtk.Align.START, width_chars = 2 };
        badge.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
        var label = new Gtk.Label (text) { xalign = 0, wrap = true, max_width_chars = 44, hexpand = true };
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        box.append (badge);
        box.append (label);
        return box;
    }
}
