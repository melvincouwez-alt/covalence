// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Contacts: the iPhone's phone book as read over PBAP (read only), with search,
 * a detail pane and "send a message" on each phone number. ContactList is also
 * the body of the new-message picker in the Messages page.
 */

namespace Covalence {
    public class Contact : Object {
        public string name { get; construct; }
        public string photo { get; construct; }
        public string[] addresses { get; construct; }
        public string uid { get; construct; }  /* iCloud card id, "" for the iPhone's */
        public bool favorite { get; set; default = false; }  /* alpha: iPhone favourites (PBAP) */

        public Contact (string name, string photo, string[] addresses, string uid = "") {
            Object (name: name, photo: photo, addresses: addresses, uid: uid);
        }

        public static Contact from_variant (Variant item) {
            var d = new VariantDict (item);
            var list = d.lookup_value ("addresses", new VariantType ("as"));
            string[] addresses = list != null ? list.dup_strv () : new string[0];
            var contact = new Contact (dict_string (d, "name"), dict_string (d, "photo"), addresses,
                                       dict_string (d, "uid"));
            contact.favorite = dict_bool (d, "favorite");
            return contact;
        }

        public bool is_phone (string address) {
            return !address.contains ("@");
        }

        public string summary () {
            foreach (var a in addresses) {
                if (is_phone (a)) {
                    return format_address (a);
                }
            }
            return addresses.length > 0 ? addresses[0] : "";
        }

        public bool matches (string query) {
            if (query == "") {
                return true;
            }
            var q = search_fold (query);
            if (search_fold (name).contains (q)) {
                return true;
            }
            var digits = only_digits (query);
            foreach (var a in addresses) {
                if (search_fold (a).contains (q)
                    || (digits.length >= 3 && only_digits (a).contains (digits))
                    || (digits.length >= 3 && digits.has_prefix ("0")
                        && only_digits (a).contains (digits.substring (1)))) {
                    return true;
                }
            }
            return false;
        }
    }

    /* Comparable form for search: accents dropped, case folded ("Élodie" -> "elodie"). */
    public string search_fold (string text) {
        var builder = new StringBuilder ();
        var decomposed = text.normalize (-1, NormalizeMode.ALL);
        unichar c;
        int i = 0;
        while (decomposed.get_next_char (ref i, out c)) {
            var type = c.type ();
            if (type != UnicodeType.NON_SPACING_MARK && type != UnicodeType.SPACING_MARK
                && type != UnicodeType.ENCLOSING_MARK) {
                builder.append_unichar (c);
            }
        }
        return builder.str.casefold ();
    }

    public string only_digits (string text) {
        var builder = new StringBuilder ();
        unichar c;
        int i = 0;
        while (text.get_next_char (ref i, out c)) {
            if (c.isdigit ()) {
                builder.append_unichar (c);
            }
        }
        return builder.str;
    }

    /* +33612345678 -> 06 12 34 56 78; other numbers and e-mails unchanged. */
    public string format_address (string address) {
        if (address.has_prefix ("+33") && address.length == 12) {
            var national = "0" + address.substring (3);
            var builder = new StringBuilder ();
            for (int i = 0; i < national.length; i += 2) {
                if (i > 0) {
                    builder.append (" ");
                }
                builder.append (national.substring (i, 2));
            }
            return builder.str;
        }
        return address;
    }

    /* Something the user typed that can be written to directly. */
    public bool looks_like_address (string text) {
        var t = text.strip ();
        if (t.contains ("@")) {
            return t.index_of ("@") > 0 && t.contains (".");
        }
        var digits = only_digits (t);
        return digits.length >= 3 && digits.length + 6 >= t.length;
    }

    public class ContactRow : Gtk.ListBoxRow {
        public Contact contact { get; construct; }

        public ContactRow (Contact contact, int avatar_size = 32) {
            Object (contact: contact);
            var avatar = new Avatar (avatar_size);
            avatar.show_person (contact.name, contact.photo);
            var name = new Gtk.Label (contact.name) {
                xalign = 0,
                ellipsize = Pango.EllipsizeMode.END
            };
            var detail = new Gtk.Label (contact.summary ()) {
                xalign = 0,
                ellipsize = Pango.EllipsizeMode.END
            };
            detail.add_css_class (Granite.CssClass.DIM);
            detail.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) {
                valign = Gtk.Align.CENTER,
                hexpand = true
            };
            text.append (name);
            text.append (detail);
            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9) {
                margin_top = 5,
                margin_bottom = 5,
                margin_start = 6,
                margin_end = 6
            };
            box.append (avatar);
            box.append (text);
            if (contact.favorite) {
                var star = new Gtk.Image.from_icon_name ("starred-symbolic") {
                    tooltip_text = _("Favori sur l'iPhone"),
                    valign = Gtk.Align.CENTER
                };
                star.add_css_class ("favorite-star");
                box.append (star);
            }
            child = box;
        }
    }

    /* Searchable contact list; "activated" gives the contact or a typed address. */
    public class ContactList : Gtk.Box {
        public Daemon daemon { get; construct; }
        public bool offer_typed { get; construct; }

        public signal void contact_selected (Contact contact);
        public signal void address_chosen (string address);

        public Gtk.SearchEntry search { get; private set; }
        private Gtk.ListBox list;
        private Gtk.ListBoxRow typed_row;
        private Gtk.Label typed_label;
        private Gtk.Stack stack;
        private Granite.Placeholder empty;
        private int count = 0;

        public ContactList (Daemon daemon, bool offer_typed) {
            Object (daemon: daemon, offer_typed: offer_typed,
                    orientation: Gtk.Orientation.VERTICAL, spacing: 6);
        }

        construct {
            search = new Gtk.SearchEntry () {
                placeholder_text = offer_typed ? _("Nom, numéro ou adresse") : _("Rechercher")
            };
            typed_label = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
            var typed_icon = new Gtk.Image.from_icon_name ("mail-message-new-symbolic");
            var typed_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9) {
                margin_top = 8,
                margin_bottom = 8,
                margin_start = 12,
                margin_end = 6
            };
            typed_box.append (typed_icon);
            typed_box.append (typed_label);
            typed_row = new Gtk.ListBoxRow () { child = typed_box, visible = false };

            list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.SINGLE };
            list.add_css_class ("navigation-sidebar");
            list.append (typed_row);
            list.set_filter_func ((row) => {
                var contact_row = row as ContactRow;
                return contact_row == null ? typed_row.visible
                                           : contact_row.contact.matches (search.text.strip ());
            });
            list.row_activated.connect (on_row);
            if (!offer_typed) {
                list.row_selected.connect ((row) => {
                    var contact_row = row as ContactRow;
                    if (contact_row != null) {
                        contact_selected (contact_row.contact);
                    }
                });
            }
            search.search_changed.connect (() => {
                var text = search.text.strip ();
                typed_row.visible = offer_typed && looks_like_address (text);
                typed_label.label = _("Écrire à %s").printf (text);
                list.invalidate_filter ();
                update_empty ();
            });
            search.activate.connect (() => {
                var text = search.text.strip ();
                if (typed_row.visible) {
                    address_chosen (text);
                    return;
                }
                for (int i = 0; ; i++) {
                    var row = list.get_row_at_index (i);
                    if (row == null) {
                        break;
                    }
                    var contact_row = row as ContactRow;
                    if (contact_row != null && contact_row.contact.matches (text)) {
                        on_row (contact_row);
                        break;
                    }
                }
            });

            var scroll = new Gtk.ScrolledWindow () {
                child = list,
                hscrollbar_policy = Gtk.PolicyType.NEVER,
                vexpand = true,
                propagate_natural_height = offer_typed,
                max_content_height = 420
            };
            empty = new Granite.Placeholder (_("Aucun contact")) {
                description = _("Les contacts viennent de l'iPhone. Activez « Synchroniser les "
                              + "contacts » pour ce PC dans les réglages Bluetooth de l'iPhone."),
                icon = new ThemedIcon (Config.APP_ID + ".Contacts")
            };
            stack = new Gtk.Stack () { vhomogeneous = false };
            stack.add_named (scroll, "list");
            stack.add_named (empty, "empty");
            append (search);
            append (stack);
        }

        private void on_row (Gtk.ListBoxRow row) {
            if (row == typed_row) {
                address_chosen (search.text.strip ());
                return;
            }
            var contact_row = row as ContactRow;
            if (contact_row != null) {
                contact_selected (contact_row.contact);
            }
        }

        private void update_empty () {
            stack.visible_child_name = count > 0 || typed_row.visible ? "list" : "empty";
        }

        public bool loaded { get; private set; default = false; }

        public async void reload () {
            if (!daemon.running) {
                return;
            }
            loaded = true;
            bool ok;
            var items = yield daemon.try_list ("ListContacts", null, out ok);
            if (!ok) {
                return;  // failed call: keep the contacts shown
            }
            Gtk.ListBoxRow? row;
            while ((row = list.get_row_at_index (1)) != null) {
                list.remove (row);
            }
            count = 0;
            foreach (var item in items) {
                list.append (new ContactRow (Contact.from_variant (item)));
                count++;
            }
            update_empty ();
        }
    }

    /* The Contacts page: list on the left, the selected card on the right. */
    public class ContactsView : Gtk.Box {
        public Daemon daemon { get; construct; }
        public signal void message_requested (string address);

        private ContactList contacts;
        private Gtk.Stack detail_stack;
        private Avatar detail_avatar;
        private Gtk.Label detail_name;
        private Gtk.ListBox detail_list;
        private Gtk.Label source_label;
        private Gtk.Button new_button;
        private Gtk.Button edit_button;
        private Gtk.Label note;
        private Gtk.CheckButton bluetooth_choice;
        private Gtk.CheckButton icloud_choice;
        private Contact? shown = null;
        private bool updating = false;
        private bool loaded {
            get { return contacts.loaded; }
        }

        public ContactsView (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.HORIZONTAL, spacing: 0);
        }

        construct {
            contacts = new ContactList (daemon, false) {
                margin_top = 6,
                margin_start = 6,
                margin_end = 6
            };
            contacts.contact_selected.connect (show_contact);

            // Source of the cards and how they are managed (Bluetooth or iCloud)
            source_label = new Gtk.Label ("") { xalign = 0, hexpand = true, ellipsize = Pango.EllipsizeMode.END };
            source_label.add_css_class (Granite.CssClass.DIM);
            source_label.add_css_class (Granite.CssClass.SMALL);
            new_button = new Gtk.Button.from_icon_name ("list-add-symbolic") { tooltip_text = _("Nouveau contact") };
            new_button.add_css_class ("flat");
            new_button.clicked.connect (() => edit (""));
            var options = new Gtk.MenuButton () {
                icon_name = "open-menu-symbolic",
                tooltip_text = _("Gestion des fiches de contact"),
                popover = build_options ()
            };
            options.add_css_class ("flat");
            var bar = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 3) { margin_start = 6, margin_end = 6 };
            bar.append (source_label);
            bar.append (new_button);
            bar.append (options);
            var side = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { width_request = 280 };
            side.append (contacts);
            side.append (bar);
            contacts.vexpand = true;

            detail_avatar = new Avatar (96) { margin_top = 24 };
            detail_name = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
            detail_name.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
            detail_list = new Gtk.ListBox () {
                selection_mode = Gtk.SelectionMode.NONE,
                show_separators = true,
                width_request = 360,
                halign = Gtk.Align.CENTER,
                margin_top = 12
            };
            detail_list.add_css_class (Granite.CssClass.CARD);
            edit_button = new Gtk.Button.with_label (_("Modifier")) { halign = Gtk.Align.CENTER, margin_top = 12 };
            edit_button.clicked.connect (() => {
                if (shown != null) {
                    edit (shown.uid);
                }
            });
            note = new Gtk.Label ("") {
                wrap = true, justify = Gtk.Justification.CENTER, max_width_chars = 50, margin_top = 12
            };
            note.add_css_class (Granite.CssClass.DIM);
            note.add_css_class (Granite.CssClass.SMALL);
            var card = new Gtk.Box (Gtk.Orientation.VERTICAL, 6) {
                halign = Gtk.Align.CENTER,
                margin_bottom = 24
            };
            card.append (detail_avatar);
            card.append (detail_name);
            card.append (detail_list);
            card.append (edit_button);
            card.append (note);
            var card_scroll = new Gtk.ScrolledWindow () {
                child = card,
                hscrollbar_policy = Gtk.PolicyType.NEVER
            };

            var none = new Granite.Placeholder (_("Contacts")) {
                description = _("Choisissez un contact."),
                icon = new ThemedIcon (Config.APP_ID + ".Contacts")
            };
            detail_stack = new Gtk.Stack () { hexpand = true };
            detail_stack.add_css_class ("view");
            detail_stack.add_named (none, "none");
            detail_stack.add_named (card_scroll, "card");

            var paned = new Gtk.Paned (Gtk.Orientation.HORIZONTAL) {
                start_child = side,
                end_child = detail_stack,
                resize_start_child = false,
                shrink_start_child = false,
                shrink_end_child = false,
                hexpand = true
            };
            append (paned);
            map.connect (() => contacts.reload.begin ());
            daemon.contacts_changed.connect (() => contacts.reload.begin ());
            daemon.changed.connect (update_source);
            update_source ();
            // The detached Contacts app is mapped before it reaches the daemon: load once it does.
            daemon.changed.connect (() => {
                if (!loaded && daemon.running && get_mapped ()) {
                    contacts.reload.begin ();
                }
            });
        }

        private Gtk.Popover build_options () {
            var title = new Gtk.Label (_("Gestion des fiches de contact")) { xalign = 0 };
            title.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
            bluetooth_choice = new Gtk.CheckButton ();
            icloud_choice = new Gtk.CheckButton () { group = bluetooth_choice };
            var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 9) {
                margin_top = 12,
                margin_bottom = 12,
                margin_start = 12,
                margin_end = 12,
                width_request = 340
            };
            box.append (title);
            box.append (choice (bluetooth_choice, _("Lecture via Bluetooth et cache local"),
                _("Aucune modification possible. Simple : repose seulement sur la connexion avec votre iPhone.")));
            box.append (choice (icloud_choice, _("Gestion via iCloud"),
                _("Créer, modifier et supprimer des fiches. Nécessite le compte iCloud (Services Apple) "
                + "et Internet ; iCloud transmet les changements à l'iPhone.")));
            bluetooth_choice.toggled.connect (() => {
                if (!updating && bluetooth_choice.active) {
                    daemon.call.begin ("SetContactsSource", new Variant ("(s)", "bluetooth"));
                }
            });
            icloud_choice.toggled.connect (() => {
                if (!updating && icloud_choice.active) {
                    daemon.call.begin ("SetContactsSource", new Variant ("(s)", "icloud"));
                }
            });
            return new Gtk.Popover () { child = box };
        }

        private static Gtk.Widget choice (Gtk.CheckButton check, string title, string text) {
            var title_label = new Gtk.Label (title) { xalign = 0 };
            var text_label = new Gtk.Label (text) { xalign = 0, wrap = true, max_width_chars = 40 };
            text_label.add_css_class (Granite.CssClass.DIM);
            text_label.add_css_class (Granite.CssClass.SMALL);
            var labels = new Gtk.Box (Gtk.Orientation.VERTICAL, 2);
            labels.append (title_label);
            labels.append (text_label);
            check.child = labels;
            return check;
        }

        private bool editable () {
            return daemon.get_string ("ContactsSource") == "icloud" && daemon.get_string ("ContactsBook") == "ready";
        }

        private void update_source () {
            var icloud = daemon.get_string ("ContactsSource") == "icloud";
            updating = true;
            bluetooth_choice.active = !icloud;
            icloud_choice.active = icloud;
            updating = false;
            string text;
            switch (icloud ? daemon.get_string ("ContactsBook") : "bluetooth") {
                case "ready":
                    text = _("Contacts iCloud, modifiables");
                    break;
                case "connecting":
                    text = _("Ouverture des contacts iCloud…");
                    break;
                case "no-account":
                    text = _("Compte iCloud non connecté (Services Apple)");
                    break;
                case "missing":
                    text = _("Composant EBook manquant (gir1.2-ebook-1.2)");
                    break;
                case "error":
                    text = _("Contacts iCloud momentanément illisibles");
                    break;
                default:
                    text = _("Contacts de l'iPhone, lecture seule");
                    break;
            }
            source_label.label = text;
            new_button.visible = editable ();
            if (shown != null) {
                edit_button.visible = editable () && shown.uid != "";
            }
            note.label = icloud
                ? _("Les changements passent par iCloud, qui les transmet à l'iPhone.")
                : _("Contacts lus sur l'iPhone en Bluetooth, en lecture seule. Pour les modifier, "
                  + "choisissez « Gestion via iCloud » dans le menu de la liste.");
        }

        private void edit (string uid) {
            var editor = new ContactEditor (get_root () as Gtk.Window, daemon, uid);
            editor.saved.connect ((new_uid) => {
                if (new_uid == "") {
                    shown = null;
                    detail_stack.visible_child_name = "none";
                }
                // The daemon reloads the book and emits ContactsChanged.
            });
            editor.present ();
        }

        private void show_contact (Contact contact) {
            shown = contact;
            edit_button.visible = editable () && contact.uid != "";
            detail_avatar.show_person (contact.name, contact.photo);
            detail_name.label = contact.name;
            Gtk.Widget? child;
            while ((child = detail_list.get_first_child ()) != null) {
                detail_list.remove (child);
            }
            foreach (var address in contact.addresses) {
                var kind = new Gtk.Label (contact.is_phone (address) ? _("téléphone") : "e-mail") {
                    xalign = 0
                };
                kind.add_css_class (Granite.CssClass.DIM);
                kind.add_css_class (Granite.CssClass.SMALL);
                var value = new Gtk.Label (format_address (address)) {
                    xalign = 0,
                    selectable = true,
                    ellipsize = Pango.EllipsizeMode.END
                };
                var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { hexpand = true };
                text.append (kind);
                text.append (value);
                var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
                    margin_top = 6,
                    margin_bottom = 6,
                    margin_start = 12,
                    margin_end = 6
                };
                box.append (text);
                if (contact.is_phone (address)) {
                    var write = new Gtk.Button.from_icon_name ("mail-message-new-symbolic") {
                        tooltip_text = _("Envoyer un message"),
                        valign = Gtk.Align.CENTER
                    };
                    write.add_css_class ("flat");
                    write.clicked.connect (() => message_requested (address));
                    box.append (write);
                    box.append (new CallButton (daemon, address, null));
                }
                detail_list.append (new Gtk.ListBoxRow () { child = box, activatable = false });
            }
            detail_stack.visible_child_name = "card";
        }
    }
}
