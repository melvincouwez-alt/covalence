// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Edit or create a contact card in iCloud (Contacts managed through iCloud).
 * iCloud then brings the change to the iPhone. Deleting asks first.
 */

public class Covalence.ContactEditor : Gtk.Window {
    public Daemon daemon { get; construct; }
    public string uid { get; construct; }

    public signal void saved (string uid);

    private const string[] PHONE_KEYS = { "mobile", "iphone", "domicile", "travail", "principal", "autre" };
    private const string[] PHONE_NAMES = { N_("mobile"), "iPhone", N_("domicile"), N_("travail"), N_("principal"), N_("autre") };
    private const string[] EMAIL_KEYS = { "domicile", "travail", "autre" };
    private const string[] EMAIL_NAMES = { N_("domicile"), N_("travail"), N_("autre") };

    private Gtk.Entry given;
    private Gtk.Entry family;
    private Gtk.Entry org;
    private Gtk.TextView note;
    private Gtk.ListBox phones;
    private Gtk.ListBox emails;
    private Gtk.Button save_button;
    private Gtk.Label error;
    private Gtk.Stack stack;

    public ContactEditor (Gtk.Window? parent, Daemon daemon, string uid) {
        Object (transient_for: parent, modal: true, daemon: daemon, uid: uid,
                title: uid == "" ? _("Nouveau contact") : _("Modifier le contact"),
                default_width: 460, default_height: 560);
    }

    construct {
        var header = new Gtk.HeaderBar ();
        header.add_css_class ("flat");
        titlebar = header;

        given = new Gtk.Entry () { placeholder_text = _("Prénom") };
        family = new Gtk.Entry () { placeholder_text = _("Nom") };
        org = new Gtk.Entry () { placeholder_text = _("Entreprise") };
        var names = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
        names.append (given);
        names.append (family);
        names.append (org);

        phones = list_box ();
        var add_phone = new Gtk.Button.with_label (_("Ajouter un numéro")) { halign = Gtk.Align.START };
        add_phone.add_css_class ("flat");
        add_phone.clicked.connect (() => add_entry (phones, PHONE_KEYS, PHONE_NAMES, "mobile", "", true));
        emails = list_box ();
        var add_email = new Gtk.Button.with_label (_("Ajouter une adresse e-mail")) { halign = Gtk.Align.START };
        add_email.add_css_class ("flat");
        add_email.clicked.connect (() => add_entry (emails, EMAIL_KEYS, EMAIL_NAMES, "domicile", "", true));

        note = new Gtk.TextView () {
            wrap_mode = Gtk.WrapMode.WORD_CHAR,
            top_margin = 6,
            bottom_margin = 6,
            left_margin = 6,
            right_margin = 6,
            height_request = 64
        };
        note.add_css_class (Granite.CssClass.CARD);

        error = new Gtk.Label ("") { wrap = true, xalign = 0, visible = false };
        error.add_css_class (Granite.CssClass.ERROR);

        var hint = new Gtk.Label (
            _("La fiche est enregistrée dans iCloud, qui la transmet à l'iPhone en quelques secondes.")
        ) { wrap = true, xalign = 0 };
        hint.add_css_class (Granite.CssClass.DIM);
        hint.add_css_class (Granite.CssClass.SMALL);

        var form = new Gtk.Box (Gtk.Orientation.VERTICAL, 8) {
            margin_start = 24,
            margin_end = 24,
            margin_bottom = 12
        };
        form.append (names);
        form.append (new Granite.HeaderLabel (_("Téléphone")));
        form.append (phones);
        form.append (add_phone);
        form.append (new Granite.HeaderLabel (_("E-mail")));
        form.append (emails);
        form.append (add_email);
        form.append (new Granite.HeaderLabel (_("Notes")));
        form.append (note);
        form.append (hint);
        form.append (error);

        var cancel = new Gtk.Button.with_label (_("Annuler"));
        cancel.clicked.connect (() => close ());
        save_button = new Gtk.Button.with_label (_("Enregistrer"));
        save_button.add_css_class (Granite.CssClass.SUGGESTED);
        save_button.clicked.connect (() => save.begin ());
        var actions = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            margin_start = 24,
            margin_end = 24,
            margin_top = 6,
            margin_bottom = 24
        };
        if (uid != "") {
            var delete_button = new Gtk.Button.with_label (_("Supprimer"));
            delete_button.add_css_class (Granite.CssClass.DESTRUCTIVE);
            delete_button.clicked.connect (confirm_delete);
            actions.append (delete_button);
        }
        var spacer = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { hexpand = true };
        actions.append (spacer);
        actions.append (cancel);
        actions.append (save_button);

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        content.append (new Gtk.ScrolledWindow () {
            child = form,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        });
        content.append (actions);

        var spinner = new Gtk.Spinner () { spinning = true, halign = Gtk.Align.CENTER, valign = Gtk.Align.CENTER };
        stack = new Gtk.Stack ();
        stack.add_named (spinner, "loading");
        stack.add_named (content, "form");
        child = stack;

        if (uid == "") {
            add_entry (phones, PHONE_KEYS, PHONE_NAMES, "mobile", "", false);
            stack.visible_child_name = "form";
        } else {
            load.begin ();
        }
    }

    private static Gtk.ListBox list_box () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        list.add_css_class (Granite.CssClass.CARD);
        return list;
    }

    /* A row: label drop-down, value entry, remove button. */
    private void add_entry (Gtk.ListBox list, string[] keys, string[] names, string label, string value,
                            bool focus) {
        string[] shown = {};
        foreach (var name in names) {
            shown += _(name);
        }
        var dropdown = new Gtk.DropDown.from_strings (shown) { valign = Gtk.Align.CENTER };
        for (int i = 0; i < keys.length; i++) {
            if (keys[i] == label) {
                dropdown.selected = i;
            }
        }
        var entry = new Gtk.Entry () { text = value, hexpand = true };
        if (list == phones) {
            entry.input_purpose = Gtk.InputPurpose.PHONE;
        } else {
            entry.input_purpose = Gtk.InputPurpose.EMAIL;
        }
        var remove = new Gtk.Button.from_icon_name ("list-remove-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Retirer")
        };
        remove.add_css_class ("flat");
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            margin_top = 4,
            margin_bottom = 4,
            margin_start = 6,
            margin_end = 4
        };
        box.append (dropdown);
        box.append (entry);
        box.append (remove);
        var row = new EntryRow (keys, dropdown, entry) { child = box, activatable = false };
        remove.clicked.connect (() => list.remove (row));
        list.append (row);
        if (focus) {
            entry.grab_focus ();
        }
    }

    private Variant entries (Gtk.ListBox list) {
        var builder = new VariantBuilder (new VariantType ("a(ss)"));
        for (int i = 0; ; i++) {
            var row = list.get_row_at_index (i) as EntryRow;
            if (row == null) {
                break;
            }
            var value = row.entry.text.strip ();
            if (value != "") {
                builder.add ("(ss)", row.keys[row.dropdown.selected], value);
            }
        }
        return builder.end ();
    }

    private async void load () {
        stack.visible_child_name = "loading";
        try {
            var reply = yield daemon.call_checked ("GetContact", new Variant ("(s)", uid));
            var card = new VariantDict (reply.get_child_value (0));
            given.text = dict_string (card, "given");
            family.text = dict_string (card, "family");
            org.text = dict_string (card, "org");
            note.buffer.text = dict_string (card, "note");
            fill (card, "phones", phones, PHONE_KEYS, PHONE_NAMES);
            fill (card, "emails", emails, EMAIL_KEYS, EMAIL_NAMES);
            stack.visible_child_name = "form";
        } catch (Error e) {
            stack.visible_child_name = "form";
            show_error (_("Fiche illisible : %s").printf (clean (e)));
            save_button.sensitive = false;
        }
    }

    private void fill (VariantDict card, string key, Gtk.ListBox list, string[] keys, string[] names) {
        var items = card.lookup_value (key, new VariantType ("a(ss)"));
        if (items == null) {
            return;
        }
        for (size_t i = 0; i < items.n_children (); i++) {
            string label, value;
            items.get_child (i, "(ss)", out label, out value);
            add_entry (list, keys, names, label != "" ? label : keys[keys.length - 1], value, false);
        }
    }

    private async void save () {
        if (given.text.strip () == "" && family.text.strip () == "" && org.text.strip () == "") {
            show_error (_("Indiquez au moins un prénom, un nom ou une entreprise."));
            return;
        }
        var card = new VariantBuilder (new VariantType ("a{sv}"));
        card.add ("{sv}", "uid", new Variant.string (uid));
        card.add ("{sv}", "given", new Variant.string (given.text.strip ()));
        card.add ("{sv}", "family", new Variant.string (family.text.strip ()));
        card.add ("{sv}", "org", new Variant.string (org.text.strip ()));
        card.add ("{sv}", "note", new Variant.string (note.buffer.text.strip ()));
        card.add ("{sv}", "phones", entries (phones));
        card.add ("{sv}", "emails", entries (emails));
        save_button.sensitive = false;
        error.visible = false;
        try {
            var reply = yield daemon.call_checked ("SaveContact", new Variant.tuple ({ card.end () }));
            string new_uid;
            reply.get ("(s)", out new_uid);
            saved (new_uid);
            close ();
        } catch (Error e) {
            show_error (_("Non enregistré : %s").printf (clean (e)));
            save_button.sensitive = true;
        }
    }

    private void confirm_delete () {
        var name = (given.text + " " + family.text).strip ();
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            _("Supprimer %s ?").printf (name != "" ? name : _("ce contact")),
            _("La fiche est supprimée d'iCloud, donc aussi de l'iPhone et de vos autres appareils."),
            "edit-delete", Gtk.ButtonsType.CANCEL) {
            transient_for = this,
            modal = true
        };
        var remove = dialog.add_button (_("Supprimer"), Gtk.ResponseType.ACCEPT);
        remove.add_css_class (Granite.CssClass.DESTRUCTIVE);
        dialog.response.connect ((response) => {
            dialog.destroy ();
            if (response == Gtk.ResponseType.ACCEPT) {
                delete_card.begin ();
            }
        });
        dialog.present ();
    }

    private async void delete_card () {
        try {
            yield daemon.call_checked ("DeleteContact", new Variant ("(s)", uid));
            saved ("");
            close ();
        } catch (Error e) {
            show_error (_("Non supprimé : %s").printf (clean (e)));
        }
    }

    private void show_error (string text) {
        error.label = text;
        error.visible = true;
    }

    private static string clean (Error e) {
        DBusError.strip_remote_error (e);
        return e.message;
    }
}

/* A label + value line of the editor. */
private class Covalence.EntryRow : Gtk.ListBoxRow {
    public string[] keys;
    public Gtk.DropDown dropdown;
    public Gtk.Entry entry;

    public EntryRow (string[] keys, Gtk.DropDown dropdown, Gtk.Entry entry) {
        this.keys = keys;
        this.dropdown = dropdown;
        this.entry = entry;
    }
}
