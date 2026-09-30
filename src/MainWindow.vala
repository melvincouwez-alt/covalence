// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Main window: link status, guided pairing, one switch per module, iCloud.
 */

/*
 * Main window. First run: the setup assistant (Onboarding), full window.
 * Then tabs: iPhone (Bluetooth), Messages, Téléphone, Contacts and Services
 * Apple (Internet), kept apart; a menu reopens the setup, the help and About.
 */

public class Covalence.MainWindow : Gtk.ApplicationWindow {
    private Daemon daemon;
    private Gtk.Stack stack;
    private Gtk.Stack pages;
    private Gtk.Stack settings_tabs;
    private Sidebar sidebar;
    private Gtk.HeaderBar main_header;
    private Onboarding onboarding;
    private Gtk.Label device_name;
    private Gtk.Label device_status;
    private Gtk.Button pair_button;
    private Gtk.Button reconnect_button;
    private Gtk.Button forget_button;
    private ModuleRow notifications_row;
    private ModuleRow media_row;
    private ModuleRow calls_row;
    private ModuleRow battery_row;
    private ModuleRow messages_row;
    private ModuleRow sound_row;
    private Gtk.DropDown sound_output;
    private string[] sound_outputs = {};
    private bool sound_updating = false;
    private string sound_state = "";
    private MessagesView messages_view;
    private string? pending_page = null;  // asked before the daemon answered

    public MainWindow (Gtk.Application app) {
        Object (application: app, title: _("Covalence"), default_width: 1080, default_height: 740);
        // Development (screenshots): COVALENCE_SNAPSHOT_SIZE=1080x860.
        var size = Environment.get_variable ("COVALENCE_SNAPSHOT_SIZE");
        if (size != null && size.contains ("x")) {
            var parts = size.split ("x");
            set_default_size (int.parse (parts[0]), int.parse (parts[1]));
        }
    }

    construct {
        // Headers live in the panes (sidebar | content), like elementary's Mail and Settings.
        titlebar = new Gtk.Grid () { visible = false };
        pages = new Gtk.Stack () { transition_type = Gtk.StackTransitionType.CROSSFADE };
        sidebar = new Sidebar (pages);
        main_header = new Gtk.HeaderBar () {
            show_title_buttons = true,
            decoration_layout = split_layout (false),
            title_widget = new Gtk.Label ("") { visible = false }
        };
        main_header.add_css_class ("flat");
        var header = main_header;

        var setup_action = new SimpleAction ("setup", null);
        setup_action.activate.connect (() => show_page ("setup"));
        add_action (setup_action);
        var help_action = new SimpleAction ("help", null);
        help_action.activate.connect (open_help);
        add_action (help_action);
        // Ctrl+1…8: sections in sidebar order.
        var section_action = new SimpleAction ("section", VariantType.INT32);
        section_action.activate.connect ((param) => {
            if (stack.visible_child_name == "main") {
                sidebar.select_index (param.get_int32 ());
            }
        });
        add_action (section_action);
        var about_action = new SimpleAction ("about", null);
        about_action.activate.connect (() => show_about (this));
        add_action (about_action);

        daemon = new Daemon ();

        pages.add_titled (build_device_page (), "device", "iPhone");
        messages_view = new MessagesView (daemon);
        pages.add_titled (messages_view, "messages", _("Messages"));
        var phone_view = new PhoneView (daemon);
        pages.add_titled (phone_view, "phone", _("Téléphone"));
        var contacts_view = new ContactsView (daemon);
        pages.add_titled (contacts_view, "contacts", _("Contacts"));
        pages.add_titled (new NotificationsView (daemon), "notifications", _("Notifications"));
        pages.add_titled (new NowPlayingView (daemon), "nowplaying", _("Lecture en cours"));
        pages.add_titled (new FilesView (daemon), "files", _("Fichiers"));
        pages.add_titled (new PhotosView (daemon), "photos", _("Photos"));
        pages.add_titled (new MirrorView (daemon), "mirror", _("Recopie d'écran"));
        pages.add_titled (new HeadphonesView (daemon), "headphones", _("Écouteurs"));
        pages.add_titled (new ServicesView (daemon), "services", _("Services Apple"));
        pages.add_titled (build_settings_page (), "settings", _("Réglages"));
        sidebar.add ("device", "iPhone", "phone", _("Aperçu"));
        sidebar.add ("messages", "iPhone", Config.APP_ID + ".Messages", _("Messages"));
        sidebar.add ("phone", "iPhone", Config.APP_ID + ".Phone", _("Téléphone"));
        sidebar.add ("contacts", "iPhone", Config.APP_ID + ".Contacts", _("Contacts"));
        sidebar.add ("notifications", "iPhone", "preferences-system-notifications", _("Notifications"));
        sidebar.add ("nowplaying", "iPhone", Config.APP_ID + ".NowPlaying", _("Lecture en cours"));
        sidebar.add ("files", "iPhone", "document-send", _("Fichiers"));
        sidebar.add ("photos", "iPhone", "multimedia-photo-viewer", _("Photos"));
        sidebar.add ("mirror", "iPhone", Config.APP_ID + ".Mirror", _("Recopie d'écran"));
        sidebar.add ("headphones", _("Accessoires"), "audio-headphones", _("Écouteurs"));
        sidebar.add ("services", _("Compte Apple"), "preferences-desktop-online-accounts", _("Services Apple"));
        sidebar.add_footer_action ("guide", "help-contents", _("Guide"));
        sidebar.action_activated.connect ((id) => open_help ());
        sidebar.add_footer ("settings", "preferences-system", _("Réglages"));
        var mini_player = new MiniPlayer (daemon);
        mini_player.open_requested.connect (() => pages.visible_child_name = "nowplaying");
        sidebar.set_player (mini_player);
        phone_view.history.message_requested.connect (write_to);
        contacts_view.message_requested.connect (write_to);
        notify["is-active"].connect (() => {
            if (is_active && pages.visible_child_name == "messages") {
                messages_view.window_activated ();
            } else {
                messages_view.update_viewing ();
            }
        });
        pages.notify["visible-child-name"].connect (() => {
            if (pages.visible_child_name == "settings" && UpdatesCard.pending (daemon) > 0) {
                settings_tabs.visible_child_name = "updates";  // the update card is there
            }
            messages_view.update_viewing ();
            if (pages.visible_child_name == "phone" && is_active) {
                daemon.call.begin ("MarkCallsSeen");
            }
        });

        onboarding = new Onboarding (daemon);
        onboarding.pair_requested.connect (() => new PairingDialog (this, daemon).present ());
        onboarding.finished.connect (() => {
            stack.visible_child_name = "main";
            pages.visible_child_name = "device";
            update_header ();
        });

        var offline = new Granite.Placeholder (_("Le service Covalence ne répond pas")) {
            description = _("Démarrez-le avec « systemctl --user start covalenced », "
                          + "ou consultez son journal avec « journalctl --user -u covalenced »."),
            icon = new ThemedIcon ("dialog-warning")
        };
        var retry = offline.append_button (new ThemedIcon ("view-refresh"), _("Réessayer"),
                                           _("Relancer la connexion au service"));
        retry.clicked.connect (() => daemon.connect_bus.begin ());

        // Main view: sidebar with its own header (close button), content with the menu.
        var logo = new Gtk.Image.from_icon_name (Config.APP_ID) { pixel_size = 24 };
        var app_name = new Gtk.Label (_("Covalence"));
        app_name.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
        var brand = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { margin_start = 3 };
        brand.append (logo);
        brand.append (app_name);
        var sidebar_header = new Gtk.HeaderBar () {
            show_title_buttons = true,
            decoration_layout = split_layout (true),
            title_widget = new Gtk.Label ("") { visible = false }
        };
        sidebar_header.pack_start (brand);
        // Follow the system's window buttons (e.g. minimize added in the desktop settings):
        // the left ones over the sidebar, the right ones over the content.
        Gtk.Settings.get_default ().notify["gtk-decoration-layout"].connect (() => {
            sidebar_header.decoration_layout = split_layout (true);
            main_header.decoration_layout = split_layout (false);
        });
        sidebar_header.add_css_class ("flat");
        var side = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { width_request = 210 };
        side.add_css_class (Granite.STYLE_CLASS_SIDEBAR);
        side.append (sidebar_header);
        side.append (sidebar);
        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        content.append (main_header);
        content.append (new CallBar (daemon));
        pages.vexpand = true;
        content.append (pages);
        var paned = new Gtk.Paned (Gtk.Orientation.HORIZONTAL) {
            start_child = side,
            end_child = content,
            resize_start_child = false,
            shrink_start_child = false,
            shrink_end_child = false
        };

        stack = new Gtk.Stack () { transition_type = Gtk.StackTransitionType.CROSSFADE, vexpand = true };
        stack.add_named (full_page (offline), "offline");
        stack.add_named (full_page (onboarding), "onboarding");
        stack.add_named (paned, "main");
        stack.visible_child_name = "offline";
        child = stack;
        update_header ();

        daemon.changed.connect (update);
        foreach (var row in new ModuleRow[] { notifications_row, media_row, calls_row,
                                             messages_row, battery_row }) {
            row.toggled.connect ((active) => daemon.set_module_enabled (row.module, active));
        }
        daemon.connect_bus.begin ();
    }

    /* Réglages: detached apps, setup assistant, help and About, in one place. */
    private Gtk.Widget build_settings_page () {
        var title = new Gtk.Label (_("Réglages")) { xalign = 0 };
        title.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());

        var detached = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        detached.add_css_class (Granite.CssClass.CARD);
        detached.append (launcher_row (Mode.MESSAGES, _("Messages"), _("Vos conversations dans leur propre fenêtre")));
        detached.append (launcher_row (Mode.PHONE, _("Téléphone"), _("Clavier, journal et appel en cours")));
        detached.append (launcher_row (Mode.CONTACTS, _("Contacts"), _("Le répertoire de l'iPhone")));
        detached.append (launcher_row (Mode.HEADPHONES, _("Écouteurs"), _("Batterie et réglages de vos AirPods")));
        detached.append (launcher_row (Mode.MIRROR, _("Recopie"), _("L'écran de l'iPhone et son contrôle depuis le PC")));
        var detached_hint = new Gtk.Label (
            _("Chaque app a sa propre fenêtre et son icône. L'interrupteur l'affiche ou non dans le menu Applications.")
        ) { xalign = 0, wrap = true };
        detached_hint.add_css_class (Granite.CssClass.DIM);
        detached_hint.add_css_class (Granite.CssClass.SMALL);

        var actions = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        actions.add_css_class (Granite.CssClass.CARD);
        actions.append (action_row ("system-run", _("Configuration initiale"),
                                    _("Relancer l'assistant pas à pas"), _("Ouvrir"), () => show_page ("setup")));
        actions.append (action_row ("help-contents", _("Guide"), _("Pas à pas, vie privée et dépannage (F1)"),
                                    _("Ouvrir"), open_help));
        actions.append (action_row ("starred-symbolic", _("Nouveautés"),
                                    _("Ce qui change dans la version %s").printf (Config.VERSION),
                                    _("Afficher"), () => WhatsNew.show (this)));
        actions.append (action_row (Config.APP_ID, _("À propos de Covalence"),
                                    _("Version %s, licence, remerciements").printf (Config.VERSION),
                                    _("Afficher"), () => show_about (this)));

        var language = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        language.add_css_class (Granite.CssClass.CARD);
        language.append (Language.settings_row (this));

        var alpha_hint = new Gtk.Label (
            _("Ces fonctionnalités reposent sur des comportements de l'iPhone pas encore vérifiés. "
              + "Elles peuvent ne rien faire. Désactivées par défaut.")
        ) { xalign = 0, wrap = true };
        alpha_hint.add_css_class (Granite.CssClass.DIM);
        alpha_hint.add_css_class (Granite.CssClass.SMALL);

        settings_tabs = new Gtk.Stack () {
            transition_type = Gtk.StackTransitionType.CROSSFADE,
            vexpand = true
        };
        // One tab per kind of feature.
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Appels")), build_calls_quiet_card (),
            new Granite.HeaderLabel (_("Internet via l'iPhone")), build_hotspot_card (),
            new Granite.HeaderLabel (_("Verrouillage de proximité")), build_proximity_card ()
        }), "connection", _("Connexion"));
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Lecture")), build_read_full_card (),
            new Granite.HeaderLabel (_("Codes SMS")), new CodesCard (daemon)
        }), "messages", _("Messages"));
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Choix des sons")), new SoundsCard (daemon),
            new Granite.HeaderLabel (_("Sons de Covalence")), new FreeSoundsCard (daemon, this)
        }), "sounds", _("Sons"));
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Langue")), language,
            new Granite.HeaderLabel (_("Barre du haut")), indicator_card (),
            new Granite.HeaderLabel (_("Apps séparées")), detached, detached_hint
        }), "display", _("Affichage"));
        settings_tabs.add_titled (settings_tab ({
            new UpdatesCard (daemon),
            new ComponentsCard ()
        }), "updates", _("Mises à jour"));
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Fonctionnalités expérimentales")), build_alpha_card (), alpha_hint
        }), "experimental", _("Expérimental"));
        settings_tabs.add_titled (settings_tab ({
            new Granite.HeaderLabel (_("Assistance")), actions
        }), "about", _("À propos"));
        var saved = saved_settings_tab ();
        if (settings_tabs.get_child_by_name (saved) != null) {
            settings_tabs.visible_child_name = saved;
        }
        settings_tabs.notify["visible-child-name"].connect (() => {
            save_settings_tab (settings_tabs.visible_child_name);
        });

        var switcher = new Gtk.StackSwitcher () {
            stack = settings_tabs,
            halign = Gtk.Align.CENTER,
            margin_bottom = 6
        };
        switcher.add_css_class ("settings-tabs");

        title.halign = Gtk.Align.CENTER;
        var top = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 18,
            margin_start = 24,
            margin_end = 24,
            halign = Gtk.Align.CENTER
        };
        top.append (title);
        top.append (switcher);
        var page = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        page.append (top);
        page.append (settings_tabs);
        return page;
    }

    /* The tab of Réglages last shown, kept in apps.conf [general] settings-tab. */
    private static string settings_prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    private static string saved_settings_tab () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (settings_prefs_path (), KeyFileFlags.NONE);
            return prefs.get_string ("general", "settings-tab");
        } catch (Error e) {
            return "connection";
        }
    }

    private static void save_settings_tab (string name) {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (settings_prefs_path (), KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_string ("general", "settings-tab", name);
        try {
            DirUtils.create_with_parents (Path.get_dirname (settings_prefs_path ()), 0700);
            prefs.save_to_file (settings_prefs_path ());
        } catch (Error e) {
            warning ("cannot save the settings tab: %s", e.message);
        }
    }

    /* One tab of Réglages: its cards in a centred, scrolling column. */
    private static Gtk.Widget settings_tab (Gtk.Widget[] children) {
        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 6,
            margin_bottom = 24,
            margin_start = 24,
            margin_end = 24,
            width_request = 560,
            halign = Gtk.Align.CENTER
        };
        foreach (var child in children) {
            content.append (child);
        }
        return new Gtk.ScrolledWindow () {
            child = content,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
    }

    /* Quiet calls (CallsQuiet): no ring, popup or audio on the PC, e.g. when Teams rings there too. */
    private Gtk.Widget build_calls_quiet_card () {
        var title_label = new Gtk.Label (_("Appels de l'iPhone en silence")) { xalign = 0 };
        var subtitle_label = new Gtk.Label (
            _("Ni sonnerie, ni notification, ni fenêtre, et le son de l'appel reste sur l'iPhone. "
              + "Utile quand Teams sonne déjà sur l'ordinateur : l'appel reste visible dans Téléphone.")
        ) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var sw = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = daemon.get_bool ("CallsQuiet") };
        sw.update_property (Gtk.AccessibleProperty.LABEL, title_label.label, -1);
        bool updating = false;
        sw.state_set.connect ((wanted) => {
            if (!updating) {
                daemon.call.begin ("SetCallsQuiet", new Variant ("(b)", wanted));
            }
            return false;
        });
        daemon.changed.connect (() => {
            var wanted = daemon.get_bool ("CallsQuiet");
            if (sw.active != wanted) {
                updating = true;
                sw.active = wanted;
                updating = false;
            }
        });
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9, margin_bottom = 9, margin_start = 12, margin_end = 12
        };
        box.append (text);
        box.append (sw);
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (new Gtk.ListBoxRow () { child = box, activatable = false });
        return list;
    }

    /* Whole text of unread messages (FetchUnread): downloading marks them read on the iPhone. */
    private Gtk.Widget build_read_full_card () {
        var title_label = new Gtk.Label (_("Toujours lire les messages en entier")) { xalign = 0 };
        var subtitle_label = new Gtk.Label (
            _("Récupère tout de suite le texte complet des messages de plus de 120 caractères. "
              + "Ils passent alors en lu sur l'iPhone.")
        ) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var sw = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = daemon.get_bool ("FetchUnread") };
        sw.update_property (Gtk.AccessibleProperty.LABEL, title_label.label, -1);
        bool updating = false;
        sw.state_set.connect ((wanted) => {
            if (updating) {
                return false;
            }
            if (!wanted) {
                daemon.call.begin ("SetFetchUnread", new Variant ("(b)", false));
                return false;
            }
            var dialog = new Granite.MessageDialog.with_image_from_icon_name (
                _("Toujours lire les messages en entier ?"),
                _("Pour avoir le texte complet d'un message non lu, Covalence doit le télécharger : "
                  + "il passera en lu sur l'iPhone dès son arrivée, même si vous ne l'avez pas "
                  + "ouvert."),
                Config.APP_ID + ".Messages", Gtk.ButtonsType.CANCEL) {
                transient_for = this,
                modal = true
            };
            var go = dialog.add_button (_("Activer"), Gtk.ResponseType.ACCEPT);
            go.add_css_class (Granite.CssClass.SUGGESTED);
            dialog.response.connect ((response) => {
                dialog.destroy ();
                if (response == Gtk.ResponseType.ACCEPT) {
                    daemon.call.begin ("SetFetchUnread", new Variant ("(b)", true));
                } else {
                    updating = true;
                    sw.active = false;
                    updating = false;
                }
            });
            dialog.present ();
            return false;
        });
        daemon.changed.connect (() => {
            var wanted = daemon.get_bool ("FetchUnread");
            if (sw.active != wanted) {
                updating = true;
                sw.active = wanted;
                updating = false;
            }
        });
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (text);
        box.append (sw);
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (new Gtk.ListBoxRow () { child = box, activatable = false });
        list.append (auto_emoji_row ());
        return list;
    }

    /* ":)" becomes 🙂 while typing (kept by the app in apps.conf, see ComposeField). */
    private Gtk.Widget auto_emoji_row () {
        var title_label = new Gtk.Label (_("Émojis automatiques")) { xalign = 0 };
        var subtitle_label = new Gtk.Label (
            _("« :) » devient 🙂, « :D » devient 😃, « <3 » devient ❤️… Retour arrière annule.")
        ) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var sw = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = ComposeField.auto_emoji_enabled () };
        sw.update_property (Gtk.AccessibleProperty.LABEL, title_label.label, -1);
        sw.notify["active"].connect (() => ComposeField.set_auto_emoji (sw.active));
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (text);
        box.append (sw);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private Gtk.Widget indicator_card () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (IndicatorSetting.row ());
        return list;
    }

    /* One switch per experimental feature (AlphaFeatures on the daemon). */
    private Gtk.Widget build_alpha_card () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (alpha_row ("map_history", _("Historique étendu des messages"),
                                _("Demande à l'iPhone les messages au-delà de la liste habituelle "
                                  + "(pages suivantes, un an en arrière)")));
        list.append (alpha_row ("mark_read", _("Marquer comme lu sur l'iPhone"),
                                _("Ouvrir une conversation dans Covalence la marque lue sur l'iPhone")));
        list.append (alpha_row ("ancs_actions", _("Actions des notifications"),
                                _("Boutons de l'iPhone (Marquer comme lu, Supprimer…) dans Notifications")));
        list.append (alpha_row ("pbap_favorites", _("Favoris de l'iPhone"),
                                _("Étoile sur les contacts favoris, lus à la prochaine synchronisation")));
        list.append (alpha_row ("iphone_control", _("Contrôler l'iPhone depuis le PC"),
                                _("Le PC comme souris et clavier Bluetooth de l'iPhone (app Recopie)")));
        return list;
    }

    private Gtk.Widget alpha_row (string feature, string title, string subtitle) {
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var subtitle_label = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var sw = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = daemon.alpha_enabled (feature) };
        sw.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
        bool updating = false;
        sw.notify["active"].connect (() => {
            if (!updating) {
                daemon.call.begin ("SetAlphaFeature", new Variant ("(sb)", feature, sw.active));
            }
        });
        daemon.changed.connect (() => {
            var wanted = daemon.alpha_enabled (feature);
            if (sw.active != wanted) {
                updating = true;
                sw.active = wanted;
                updating = false;
            }
        });
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (text);
        box.append (sw);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private delegate void RowAction ();

    private static Gtk.Widget action_row (string icon, string title, string subtitle, string button_label,
                                          owned RowAction action) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 32 };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var subtitle_label = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var button = new Gtk.Button.with_label (button_label) { valign = Gtk.Align.CENTER };
        button.clicked.connect (() => action ());
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (button);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private void update_header () {
        title = stack.visible_child_name == "onboarding" ? _("Configurer Covalence") : _("Covalence");
        update_badges ();
    }

    private void update_badges () {
        sidebar.set_badge ("messages", daemon.get_uint ("UnreadMessages"));
        sidebar.set_badge ("phone", daemon.get_uint ("MissedCalls"));
        sidebar.set_badge ("settings", UpdatesCard.pending (daemon));
    }

    /* Offline and first-run screens take the whole window, under a plain header. */
    private static Gtk.Widget full_page (Gtk.Widget page) {
        var header = new Gtk.HeaderBar ();
        header.add_css_class ("flat");
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        box.append (header);
        page.vexpand = true;
        box.append (page);
        return box;
    }

    private Gtk.Widget build_device_page () {
        var phone_icon = new Gtk.Image.from_icon_name ("phone") { pixel_size = 64 };
        device_name = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
        device_name.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());
        device_status = new Gtk.Label ("") { xalign = 0, wrap = true };
        device_status.add_css_class (Granite.CssClass.DIM);
        pair_button = new Gtk.Button.with_label (_("Appairer un iPhone…"));
        pair_button.clicked.connect (() => new PairingDialog (this, daemon).present ());
        reconnect_button = new Gtk.Button.with_label (_("Reconnecter"));
        reconnect_button.clicked.connect (() => daemon.call.begin ("Reconnect"));
        forget_button = new Gtk.Button.with_label (_("Oublier"));
        forget_button.clicked.connect (confirm_forget);
        var buttons = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { margin_top = 6 };
        buttons.append (pair_button);
        buttons.append (reconnect_button);
        buttons.append (forget_button);
        buttons.append (Guide.help_button ("link", _("Comment relier l'iPhone")));
        var summary_text = new Gtk.Box (Gtk.Orientation.VERTICAL, 3) {
            valign = Gtk.Align.CENTER,
            hexpand = true
        };
        summary_text.append (device_name);
        summary_text.append (device_status);
        summary_text.append (buttons);
        var summary = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 16) { margin_bottom = 6 };
        summary.append (phone_icon);
        summary.append (summary_text);

        notifications_row = new ModuleRow ("notifications", "preferences-system-notifications",
                                           _("Notifications"));
        media_row = new ModuleRow ("media", "applications-multimedia", _("Musique de l'iPhone"));
        calls_row = new ModuleRow ("calls", Config.APP_ID + ".Phone", _("Appels"));
        messages_row = new ModuleRow ("messages", Config.APP_ID + ".Messages", _("Messages et contacts"));
        battery_row = new ModuleRow ("battery", "battery-good", _("Batterie"));
        sound_row = build_sound_row ();
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        foreach (var row in new ModuleRow[] { notifications_row, media_row, sound_row, calls_row,
                                             messages_row, battery_row }) {
            list.append (row);
        }

        var guide = new PhoneGuide (daemon) { margin_top = 12 };
        guide.pair_requested.connect (() => new PairingDialog (this, daemon).present ());
        var expander = new Gtk.Expander (_("Guide de connexion")) { child = guide };

        var privacy = new Gtk.Label (
            _("Tout passe directement entre ce PC et l'iPhone, en Bluetooth. Les journaux de Covalence "
            + "ne contiennent jamais le texte des notifications ni des messages.")
        ) { wrap = true, xalign = 0 };
        privacy.add_css_class (Granite.CssClass.DIM);
        privacy.add_css_class (Granite.CssClass.SMALL);

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 18,
            margin_bottom = 24,
            margin_start = 24,
            margin_end = 24,
            width_request = 560,
            halign = Gtk.Align.CENTER
        };
        content.append (summary);
        content.append (new Granite.HeaderLabel (_("Fonctions")));
        content.append (list);
        content.append (new Granite.HeaderLabel (_("Internet")));
        content.append (build_hotspot_card ());
        content.append (expander);
        content.append (privacy);
        return new Gtk.ScrolledWindow () {
            child = content,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
    }

    /* Removes the iPhone and its keys from this PC, to start pairing again from scratch. */
    private void confirm_forget () {
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            _("Oublier cet iPhone ?"),
            _("Ce PC efface l'appairage. Pour un nouveau départ propre, oubliez aussi ce PC sur "
              + "l'iPhone (Réglages › Bluetooth › ⓘ › Oublier cet appareil), puis appairez à nouveau."),
            "bluetooth", Gtk.ButtonsType.CANCEL) {
            transient_for = this,
            modal = true
        };
        var go = dialog.add_button (_("Oublier"), Gtk.ResponseType.ACCEPT);
        go.add_css_class (Granite.CssClass.DESTRUCTIVE);
        dialog.response.connect ((response) => {
            dialog.destroy ();
            if (response == Gtk.ResponseType.ACCEPT) {
                daemon.call.begin ("Forget");
            }
        });
        dialog.present ();
    }

    /* Bluetooth tethering: a card of its own, shown on the overview and in Réglages. */
    private Gtk.Widget build_hotspot_card () {
        return new HotspotCard (daemon);
    }

    /* Proximity lock settings (Réglages, Général). */
    private Gtk.Widget build_proximity_card () {
        return new ProximityCard (daemon);
    }

    /* Sound of the iPhone (A2DP) played on this PC: allowed or not, and on which output. */
    private ModuleRow build_sound_row () {
        var row = new ModuleRow ("sound", "audio-speakers", _("Son de l'iPhone"));
        sound_output = new Gtk.DropDown.from_strings ({ _("Sortie par défaut") }) {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Sortie du PC pour le son de l'iPhone")
        };
        sound_output.notify["selected"].connect (() => {
            if (!sound_updating && sound_output.selected < sound_outputs.length) {
                daemon.call.begin ("SetPhoneAudioOutput",
                                   new Variant ("(s)", sound_outputs[sound_output.selected]));
            }
        });
        row.add_suffix (sound_output);
        row.toggled.connect ((active) => daemon.call.begin ("SetPhoneAudio", new Variant ("(b)", active)));
        return row;
    }

    private async void load_sound_outputs () {
        var items = yield daemon.call_list ("ListAudioOutputs");
        string[] names = { "" };
        string[] labels = { _("Sortie par défaut") };
        foreach (var item in items) {
            names += item.lookup_value ("name", VariantType.STRING).get_string ();
            labels += item.lookup_value ("description", VariantType.STRING).get_string ();
        }
        sound_updating = true;
        sound_outputs = names;
        sound_output.model = new Gtk.StringList (labels);
        var current = daemon.get_string ("PhoneAudioOutput");
        sound_output.selected = 0;
        for (int i = 0; i < names.length; i++) {
            if (names[i] == current) {
                sound_output.selected = i;
            }
        }
        sound_updating = false;
    }

    private void update_sound (bool connected) {
        var state = daemon.get_string ("PhoneAudio");
        if (state != sound_state) {
            // Outputs may have changed (headphones plugged in): reload on each change.
            sound_state = state;
            load_sound_outputs.begin ();
        }
        sound_output.sensitive = state != "off";
        string status;
        if (state == "off") {
            status = _("Refusé : vidéos et musique restent sur l'iPhone");
        } else if (state == "playing") {
            status = _("En lecture sur ce PC");
        } else if (connected) {
            status = _("Choisissez ce PC dans le bouton AirPlay de l'iPhone pour y envoyer le son");
        } else {
            status = _("iPhone absent");
        }
        sound_row.update (state != "off", status);
    }

    private void update () {
        update_badges ();
        if (!daemon.running) {
            stack.visible_child_name = "offline";
            return;
        }
        if (stack.visible_child_name == "offline") {
            if (pending_page == "setup" || (pending_page == null && !Setup.is_done ())) {
                onboarding.restart ();
                stack.visible_child_name = "onboarding";
            } else {
                stack.visible_child_name = "main";
                if (pending_page != null) {
                    pages.visible_child_name = pending_page;
                }
            }
            WhatsNew.maybe_show (this, !Setup.is_done ());
            pending_page = null;
            update_header ();
        }

        var paired = daemon.get_bool ("Paired");
        var connected = daemon.get_bool ("Connected");
        var bluetooth = daemon.get_bool ("BluetoothAvailable");
        var battery = daemon.get_int ("Battery");
        var name = daemon.get_string ("DeviceName");
        var bond_lost = daemon.get_string ("LinkProblem") == "bond-lost";

        device_name.label = name != "" ? name : _("Aucun iPhone");
        if (!bluetooth) {
            device_status.label = _("Bluetooth indisponible");
        } else if (bond_lost) {
            device_status.label = _("L'iPhone ne reconnaît plus ce PC : son appairage a été supprimé "
                                    + "sur l'iPhone. Appairez à nouveau.");
        } else if (!paired) {
            device_status.label = _("Appairez votre iPhone pour recevoir ses notifications et ses appels.");
        } else if (connected) {
            device_status.label = battery >= 0 ? _("Connecté · batterie %d %%").printf (battery) : _("Connecté");
        } else {
            device_status.label = _("Hors de portée ou Bluetooth coupé sur l'iPhone");
        }
        pair_button.visible = bluetooth;
        pair_button.label = bond_lost ? _("Appairer à nouveau…")
            : paired ? _("Appairer un autre iPhone…") : _("Appairer un iPhone…");
        if (paired && !bond_lost) {
            pair_button.remove_css_class (Granite.CssClass.SUGGESTED);
        } else {
            pair_button.add_css_class (Granite.CssClass.SUGGESTED);
        }
        reconnect_button.visible = paired && !connected && bluetooth && !bond_lost;
        forget_button.visible = name != "" && bluetooth;

        string waiting_le = connected
            ? _("En attente : l'iPhone doit se connecter à « Covalence » en Bluetooth basse consommation")
            : _("iPhone absent");

        var on = daemon.module_enabled ("notifications");
        notifications_row.update (on, !on ? _("Désactivées")
            : daemon.get_bool ("NotificationsLinked") ? _("Reçues de l'iPhone, avec leurs actions")
            : paired ? waiting_le : _("iPhone non appairé"));

        on = daemon.module_enabled ("media");
        media_row.update (on, !on ? _("Désactivée")
            : daemon.get_bool ("MediaLinked") ? _("Pilotable depuis Lecture en cours et l'indicateur de son")
            : paired ? waiting_le : _("iPhone non appairé"));

        on = daemon.module_enabled ("calls");
        var calls_off = calls_unavailable (daemon);
        calls_row.update (on, calls_off ? _(CALLS_UNAVAILABLE)
            : !on ? _("Désactivés")
            : daemon.get_bool ("CallsLinked") ? _("Prêt : les appels entrants s'affichent ici")
            : connected ? _("Profil mains libres non connecté")
            : _("iPhone absent"), !calls_off);

        on = daemon.module_enabled ("messages");
        string messages_status;
        switch (daemon.get_string ("MessagesState")) {
            case "ready":
                messages_status = daemon.get_string ("MessagesSend") == "no"
                    ? _("Lecture depuis l'iPhone ; réponse sur l'iPhone seulement")
                    : _("Messages de l'iPhone lus en Bluetooth");
                break;
            case "forbidden":
                messages_status = _("Refusé : activez « Afficher les notifications » pour ce PC "
                                  + "dans les réglages Bluetooth de l'iPhone");
                break;
            case "no-obex":
                messages_status = _("Paquet bluez-obexd manquant");
                break;
            case "connecting":
                messages_status = _("Connexion…");
                break;
            case "error":
                messages_status = _("Messages momentanément illisibles");
                break;
            default:
                messages_status = connected ? _("En attente") : _("iPhone absent");
                break;
        }
        messages_row.update (on, on ? messages_status : _("Désactivés"));

        on = daemon.module_enabled ("battery");
        battery_row.update (on, !on ? _("Alertes désactivées")
            : battery >= 0 ? _("%d %% · alerte à 20 %% et 10 %%").printf (battery)
            : _("Niveau inconnu"));

        update_sound (connected);

    }

    private void write_to (string address) {
        pages.visible_child_name = "messages";
        messages_view.start_conversation (address);
    }

    public void show_page (string name) {
        if (name == "setup" && !daemon.running) {
            pending_page = name;
        } else if (name == "setup") {
            onboarding.restart ();
            stack.visible_child_name = "onboarding";
        } else if (!daemon.running) {
            pending_page = name;
        } else {
            stack.visible_child_name = "main";
            pages.visible_child_name = name;
        }
        update_header ();
    }

    private void open_help () {
        Guide.open (this);
    }

    /* One side of the system window-button layout, "close:minimize,maximize" → "close:" or
       ":minimize,maximize", for a window split in two header bars. */
    public static string split_layout (bool start) {
        var layout = Gtk.Settings.get_default ().gtk_decoration_layout ?? "close:maximize";
        var parts = layout.split (":", 2);
        var left = parts[0];
        var right = parts.length > 1 ? parts[1] : "";
        return start ? left + ":" : ":" + right;
    }
}
