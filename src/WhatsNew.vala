/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * « Nouveautés »: what changed in this version, shown once after an update and from Réglages.
 * The version last shown is kept in apps.conf [general] whats-new.
 */

namespace Covalence.WhatsNew {

    private struct Item {
        string icon;
        string title;
        string text;
    }

    private static Item[] items () {
        return {
            { "audio-headphones-symbolic", _("AirPods Pro 3"),
              _("Contrôle du bruit, audio adaptatif et détection de conversation sont reconnus. "
                + "Des écouteurs plus récents que Covalence gardent toutes leurs commandes.") },
            { "security-high-symbolic", _("Sécurité renforcée"),
              _("Le code d'appairage se confirme aussi sur le PC. Un autre programme doit vous "
                + "demander avant d'appeler, d'envoyer ou d'appairer. Mises à jour, fichiers "
                + "LocalSend et recopie mieux protégés ; codes SMS liés à leur site.") },
            { "emblem-ok-symbolic", _("Messages fiables"),
              _("Plus de doublons après une reconnexion, les groupes restent groupés, chaque "
                + "iPhone a son propre historique et les contacts se rechargent avec « Réessayer ».") },
            { "bluetooth-active-symbolic", _("Appairage simplifié"),
              _("L'iPhone trouve ce PC dans Réglages › Bluetooth, sans app en plus. La reconnexion "
                + "est plus stable et un bouton « Oublier » permet de repartir de zéro.") },
            { "video-display-symbolic", _("Recopie et contrôle"),
              _("La recopie d'écran devient une app, plus fluide. Expérimental : pilotez l'iPhone "
                + "avec la souris et le clavier du PC (guide dans l'app).") },
            { "audio-volume-high-symbolic", _("19 sons libres"),
              _("Onze sons de plus pour les notifications et les appels (Réglages › Sons).") },
            { "network-cellular-symbolic", _("Internet via l'iPhone"),
              _("Un bouton dans l'Aperçu utilise le partage de connexion de l'iPhone, en Bluetooth.") },
            { "phone-apple-iphone-symbolic", _("Barre du haut"),
              _("Batterie, lecture en cours, appel et messages non lus à côté de l'horloge. "
                + "Se déconnecter une fois pour l'afficher.") },
            { "system-search-symbolic", _("Recherche et épingles"),
              _("Ctrl+F cherche dans les messages. Épinglez une conversation ou marquez-la non lue "
                + "d'un clic droit.") },
            { "folder-download-symbolic", _("Fichiers, recopie et photos"),
              _("Échangez des fichiers avec l'app LocalSend, affichez l'écran de l'iPhone "
                + "(expérimental) et importez les photos par câble USB.") },
            { "folder-remote-symbolic", _("iCloud"),
              _("État de synchro d'iCloud Drive dans Fichiers, raccourcis vers Localiser, Notes "
                + "et Masquer mon adresse e-mail.") },
            { "system-lock-screen-symbolic", _("Verrouillage de proximité"),
              _("Le PC se verrouille quand l'iPhone s'éloigne (désactivé par défaut, "
                + "jamais de déverrouillage).") },
            { "preferences-system-symbolic", _("Réglages en onglets"),
              _("Connexion, Messages, Sons, Affichage, Mises à jour, Expérimental, À propos ; les sons libres "
                + "de Covalence s'essaient d'un clic.") },
            { "face-smile-symbolic", _("Émojis automatiques"),
              _("« :) » devient 🙂 pendant la saisie. Retour arrière annule ; réglable dans Réglages.") },
            { "object-select-symbolic", _("Messages envoyés"),
              _("Une petite coche apparaît sous un message dès que l'iPhone confirme son envoi.") },
            { "emoji-body-symbolic", _("Réactions"),
              _("Les réactions reçues s'affichent sur le bon message, sans doublon, et se cumulent. "
                + "Au survol d'un message : réagir, copier ou supprimer.") },
            { "dialog-password-symbolic", _("Codes SMS"),
              _("Un code reçu par SMS se copie depuis la notification. Expérimental : remplissage "
                + "dans Chrome, Chromium, Edge et Firefox (Réglages › Codes SMS).") },
            { "format-justify-fill-symbolic", _("Messages en entier"),
              _("« Tout lire » récupère la suite d'un message long non lu, ou toujours, "
                + "au choix dans Réglages. Le message passe alors en lu sur l'iPhone.") },
            { "view-refresh-symbolic", _("Synchroniser"),
              _("Un bouton dans Messages relit les messages, les contacts et le journal d'appels.") },
            { "audio-volume-high-symbolic", _("Sons"),
              _("Choisissez le son des messages, des notifications de l'iPhone et la sonnerie "
                + "des appels, dont 8 sons libres fournis avec Covalence (Réglages › Sons).") },
            { "system-software-update-symbolic", _("Mises à jour"),
              _("Covalence recherche les nouvelles versions et s'installe depuis Réglages.") },
            { "applications-science-symbolic", _("Fonctionnalités expérimentales"),
              _("À essayer dans Réglages : historique étendu, marquer comme lu sur l'iPhone, "
                + "actions des notifications, favoris des contacts.") }
        };
    }

    private static string prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    private static string last_shown () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            return prefs.get_string ("general", "whats-new");
        } catch (Error e) {
            return "";
        }
    }

    private static void remember () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_string ("general", "whats-new", Config.VERSION);
        try {
            DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
            prefs.save_to_file (prefs_path ());
        } catch (Error e) {
            warning ("cannot save the version shown: %s", e.message);
        }
    }

    /* Once per version, after an update (not on a first install: the setup assistant runs then). */
    public void maybe_show (Gtk.Window parent, bool first_run) {
        if (last_shown () == Config.VERSION) {
            return;
        }
        remember ();
        if (!first_run) {
            Idle.add (() => {
                show (parent);
                return Source.REMOVE;
            });
        }
    }

    public void show (Gtk.Window? parent) {
        var list = new Gtk.Box (Gtk.Orientation.VERTICAL, 14) {
            margin_top = 6,
            margin_bottom = 6
        };
        foreach (var item in items ()) {
            var icon = new Gtk.Image.from_icon_name (item.icon) {
                pixel_size = 24,
                valign = Gtk.Align.START
            };
            icon.add_css_class (Granite.CssClass.ACCENT);
            var title = new Gtk.Label (item.title) { xalign = 0 };
            title.add_css_class ("heading");
            var text = new Gtk.Label (item.text) {
                xalign = 0,
                wrap = true,
                max_width_chars = 48
            };
            text.add_css_class (Granite.CssClass.DIM);
            var words = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true };
            words.append (title);
            words.append (text);
            var row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12);
            row.append (icon);
            row.append (words);
            list.append (row);
        }
        var scrolled = new Gtk.ScrolledWindow () {
            child = list,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            propagate_natural_height = true,
            max_content_height = 420
        };
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            _("Nouveautés de Covalence %s").printf (Config.VERSION),
            _("Ce qui change dans cette version."),
            Config.APP_ID, Gtk.ButtonsType.NONE) {
            transient_for = parent,
            modal = true
        };
        dialog.custom_bin.append (scrolled);
        var ok = dialog.add_button (_("Continuer"), Gtk.ResponseType.CLOSE);
        ok.add_css_class (Granite.CssClass.SUGGESTED);
        dialog.response.connect (() => dialog.destroy ());
        dialog.present ();
    }
}
