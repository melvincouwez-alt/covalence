// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * First-run setup, full window: welcome, what to connect (iPhone and/or Apple
 * services), the iPhone steps, the Apple services steps, the apps, done.
 * Everything can be skipped and redone later from the menu; all options stay
 * in the tabs.
 */

public class Covalence.Onboarding : Gtk.Box {
    public Daemon daemon { get; construct; }
    public signal void finished ();
    public signal void pair_requested ();

    private Gtk.Stack stack;
    private Gtk.Box dots;
    private Gtk.Button back;
    private Gtk.Button next;
    private Gtk.Button skip;
    private Gtk.ToggleButton want_phone;
    private Gtk.ToggleButton want_apple;
    private string[] flow = {};
    private int position = 0;

    public Onboarding (Daemon daemon) {
        Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        add_css_class ("onboarding");
        stack = new Gtk.Stack () {
            transition_type = Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
            vexpand = true,
            hhomogeneous = false,
            vhomogeneous = false
        };
        stack.add_named (welcome_page (), "welcome");
        stack.add_named (choice_page (), "choice");

        var phone_guide = new PhoneGuide (daemon);
        phone_guide.pair_requested.connect (() => pair_requested ());
        stack.add_named (step_page ("phone", _("Connexion avec votre iPhone"),
            _("Par Bluetooth : notifications, musique, messages, contacts et appels."), phone_guide),
            "phone");
        stack.add_named (step_page ("folder-remote", _("Services Apple"),
            _("Par Internet, avec votre compte Apple : courriel, agendas, rappels, contacts et fichiers iCloud."),
            new AppleGuide (daemon)), "apple");
        stack.add_named (apps_page (), "apps");
        stack.add_named (done_page (), "done");

        back = new Gtk.Button.with_label (_("Retour"));
        back.clicked.connect (() => go (position - 1));
        skip = new Gtk.Button.with_label (_("Passer la configuration"));
        skip.add_css_class ("flat");
        skip.clicked.connect (finish);
        next = new Gtk.Button.with_label (_("Commencer"));
        next.add_css_class (Granite.CssClass.SUGGESTED);
        next.clicked.connect (() => {
            if (position == flow.length - 1) {
                finish ();
            } else {
                go (position + 1);
            }
        });
        dots = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 8) {
            halign = Gtk.Align.CENTER,
            valign = Gtk.Align.CENTER,
            hexpand = true
        };
        var left = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { width_request = 200 };
        left.append (back);
        left.append (skip);
        var right = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            width_request = 200,
            halign = Gtk.Align.END
        };
        right.append (next);
        var footer = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 12,
            margin_bottom = 18,
            margin_start = 24,
            margin_end = 24
        };
        footer.append (left);
        footer.append (dots);
        footer.append (right);

        append (stack);
        append (footer);
        compute_flow ();
        go (0);
    }

    public void restart () {
        compute_flow ();
        go (0);
    }

    private void compute_flow () {
        string[] pages = { "welcome", "choice" };
        if (want_phone.active) {
            pages += "phone";
        }
        if (want_apple.active) {
            pages += "apple";
        }
        if (want_phone.active) {
            pages += "apps";
        }
        pages += "done";
        flow = pages;
    }

    private void go (int index) {
        if (index < 0 || index >= flow.length) {
            return;
        }
        if (flow[position] == "choice") {
            compute_flow ();
        }
        stack.transition_type = index >= position ? Gtk.StackTransitionType.SLIDE_LEFT
                                                   : Gtk.StackTransitionType.SLIDE_RIGHT;
        position = index;
        stack.visible_child_name = flow[index];

        Gtk.Widget? child;
        while ((child = dots.get_first_child ()) != null) {
            dots.remove (child);
        }
        for (int i = 0; i < flow.length; i++) {
            var dot = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { valign = Gtk.Align.CENTER };
            dot.add_css_class ("onboarding-dot");
            if (i == index) {
                dot.add_css_class ("current");
            }
            dots.append (dot);
        }
        back.visible = index > 0;
        skip.visible = index == 0;
        var page = flow[index];
        next.label = page == "welcome" ? _("Commencer")
                   : page == "done" ? _("Ouvrir Covalence")
                   : _("Continuer");
        next.sensitive = page != "choice" || want_phone.active || want_apple.active;
    }

    private void finish () {
        Setup.set_done ();
        finished ();
    }

    // --- pages ----------------------------------------------------------------------

    private static Gtk.Widget centered (Gtk.Widget child, int width = 560) {
        child.halign = Gtk.Align.CENTER;
        child.valign = Gtk.Align.CENTER;
        child.width_request = width;
        child.margin_top = 24;
        child.margin_bottom = 24;
        return new Gtk.ScrolledWindow () {
            child = child,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
    }

    private static Gtk.Label title (string text) {
        var label = new Gtk.Label (text) { wrap = true, justify = Gtk.Justification.CENTER };
        label.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());
        return label;
    }

    private static Gtk.Label body (string text) {
        var label = new Gtk.Label (text) {
            wrap = true,
            justify = Gtk.Justification.CENTER,
            use_markup = true,
            max_width_chars = 60
        };
        label.add_css_class (Granite.CssClass.DIM);
        return label;
    }

    private Gtk.Widget welcome_page () {
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        box.append (new Gtk.Image.from_icon_name (Config.APP_ID) { pixel_size = 128 });
        box.append (title (_("Bienvenue dans Covalence")));
        var language = Language.welcome_row (this);
        language.margin_bottom = 6;
        box.append (language);
        box.append (body (_("Votre iPhone et iCloud sur elementary OS : notifications, "
                          + "messages, appels, contacts, musique, courriel, agendas et fichiers iCloud.")));
        var privacy = body (_("Tout passe directement entre ce PC, votre iPhone et Apple. Covalence n'utilise "
                            + "aucun serveur et ne conserve ni ne journalise le contenu de vos messages "
                            + "ailleurs que sur ce PC."));
        privacy.add_css_class (Granite.CssClass.SMALL);
        privacy.margin_top = 12;
        box.append (privacy);
        var legal = body (_("Projet libre et indépendant, non affilié à Apple Inc."));
        legal.add_css_class (Granite.CssClass.SMALL);
        box.append (legal);
        // Only shown when something is missing (BlueZ, obexd, EDS typelibs…).
        box.append (new ComponentsCard () { margin_top = 12 });
        var guide_link = new Gtk.Button.with_label (_("Ouvrir le guide")) { halign = Gtk.Align.CENTER, margin_top = 6 };
        guide_link.add_css_class ("flat");
        guide_link.clicked.connect (() => Guide.open (get_root () as Gtk.Window, "start"));
        box.append (guide_link);
        return centered (box);
    }

    private Gtk.ToggleButton choice_card (string icon, string heading, string text) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 64 };
        var head = new Gtk.Label (heading) { wrap = true, justify = Gtk.Justification.CENTER };
        head.add_css_class (Granite.HeaderLabel.Size.H3.to_string ());
        var desc = new Gtk.Label (text) { wrap = true, justify = Gtk.Justification.CENTER, max_width_chars = 26 };
        desc.add_css_class (Granite.CssClass.DIM);
        desc.add_css_class (Granite.CssClass.SMALL);
        var check = new Gtk.Image.from_icon_name ("object-select-symbolic");
        check.add_css_class ("choice-check");
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 8) {
            margin_top = 18,
            margin_bottom = 18,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (head);
        box.append (desc);
        box.append (check);
        var card = new Gtk.ToggleButton () { child = box, active = true, hexpand = true };
        card.add_css_class ("choice-card");
        card.toggled.connect (() => {
            next.sensitive = want_phone.active || want_apple.active;
        });
        return card;
    }

    private Gtk.Widget choice_page () {
        want_phone = choice_card ("phone", _("Votre iPhone"),
            _("Par Bluetooth : notifications, musique, messages, contacts et appels sur ce PC."));
        want_apple = choice_card ("folder-remote", _("Services Apple"),
            _("Par Internet : courriel, agendas, rappels, contacts et iCloud Drive."));
        var cards = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 18) { homogeneous = true };
        cards.append (want_phone);
        cards.append (want_apple);
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        box.append (title (_("Que voulez-vous connecter ?")));
        box.append (body (_("Les deux sont indépendants : vous pourrez ajouter l'autre plus tard.")));
        cards.margin_top = 12;
        box.append (cards);
        return centered (box, 620);
    }

    private Gtk.Widget step_page (string icon, string heading, string text, Gtk.Widget guide) {
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        box.append (new Gtk.Image.from_icon_name (icon) { pixel_size = 64 });
        box.append (title (heading));
        box.append (body (text));
        var card = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { margin_top = 12 };
        card.add_css_class (Granite.CssClass.CARD);
        card.add_css_class ("setup-column");
        card.append (guide);
        box.append (card);
        var later = body (_("Une étape peut attendre : chaque réglage reste disponible dans Covalence."));
        later.add_css_class (Granite.CssClass.SMALL);
        box.append (later);
        return centered (box);
    }

    private Gtk.Widget app_choice (Mode mode, string icon, string name, string text) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 48 };
        var title_label = new Gtk.Label (name) { xalign = 0 };
        title_label.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
        var desc = new Gtk.Label (text) { xalign = 0, wrap = true };
        desc.add_css_class (Granite.CssClass.DIM);
        desc.add_css_class (Granite.CssClass.SMALL);
        var text_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text_box.append (title_label);
        text_box.append (desc);
        var shown = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = Launchers.is_visible (mode) };
        shown.notify["active"].connect (() => Launchers.set_visible (mode, shown.active));
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text_box);
        box.append (shown);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private Gtk.Widget apps_page () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (app_choice (Mode.MESSAGES, Config.APP_ID + ".Messages", _("Messages"),
                                 _("Vos conversations dans leur propre fenêtre, avec leur icône dans le dock.")));
        list.append (app_choice (Mode.PHONE, Config.APP_ID + ".Phone", _("Téléphone"),
                                 _("Clavier, journal d'appels et appel en cours, avec une pastille des appels manqués.")));
        list.append (app_choice (Mode.CONTACTS, Config.APP_ID + ".Contacts", _("Contacts"),
                                 _("Le répertoire de l'iPhone, pour appeler ou écrire.")));
        list.append (app_choice (Mode.HEADPHONES, "audio-headphones", _("Écouteurs"),
                                 _("Batterie, contrôle du bruit et réglages de vos AirPods.")));
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        box.append (title (_("Apps séparées")));
        box.append (body (_("Messages, Téléphone, Contacts et Écouteurs sont toujours dans Covalence. Vous pouvez aussi "
                          + "les avoir comme apps à part dans le menu des applications et le dock.")));
        list.margin_top = 12;
        box.append (list);
        return centered (box);
    }

    private Gtk.Widget done_page () {
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        box.append (new Gtk.Image.from_icon_name ("process-completed") { pixel_size = 96 });
        box.append (title (_("C'est prêt")));
        box.append (body (_("Covalence tourne en arrière-plan : les notifications, messages et appels "
                          + "arrivent même fenêtre fermée. Pour refaire cette configuration, ouvrez le "
                          + "menu en haut à droite de Covalence.")));
        return centered (box);
    }
}
