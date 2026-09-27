// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * About Covalence: version, licence, independence from Apple and trademarks.
 */

namespace Covalence {
    public const string LEGAL_NOTICE = N_(
        "Covalence est un logiciel libre et indépendant. Elle n'est ni affiliée à Apple Inc., ni "
        + "approuvée, sponsorisée ou soutenue par Apple Inc., ni par elementary, Inc.\n\n"
        + "Apple, iPhone, iCloud, iCloud Drive, iMessage, Apple Music, AirPods et le logo Apple sont des "
        + "marques d'Apple Inc., déposées aux États-Unis et dans d'autres pays et régions. elementary "
        + "est une marque d'elementary, Inc. Ces noms ne sont employés que pour décrire la "
        + "compatibilité.\n\n"
        + "Covalence utilise des protocoles publiés : Bluetooth HFP, MAP et PBAP ; ANCS et AMS, "
        + "spécifiés par Apple ; CalDAV, CardDAV et IMAP. Deux fonctions reposent sur des interfaces "
        + "non documentées : les écouteurs (protocole AAP décrit par LibrePods) et iCloud Drive et "
        + "Photos (via rclone). Elles peuvent cesser de fonctionner sans préavis. Covalence n'a "
        + "décompilé aucun logiciel Apple.\n\n"
        + "Aucune donnée ne passe par un serveur de Covalence : il n'y en a pas.\n\n"
        + "Ce programme est distribué sans aucune garantie. Utilisez-le à vos propres risques ; "
        + "l'usage d'iCloud reste soumis aux conditions d'Apple.");

    public void show_about (Gtk.Window? parent) {
        var about = new Gtk.AboutDialog () {
            transient_for = parent,
            modal = true,
            program_name = "Covalence",
            logo_icon_name = Config.APP_ID,
            version = Config.VERSION,
            comments = _("Pour utiliser un iPhone et iCloud depuis elementary OS.\n"
                       + "Projet libre, non affilié à Apple Inc."),
            license_type = Gtk.License.GPL_3_0,
            copyright = _("© 2026 Melvin Couwez et les contributeurs de Covalence"),
            authors = { "Melvin Couwez" },
            website = "https://github.com/melvincouwez-alt/covalence",
            website_label = _("Code source")
        };
        about.add_credit_section (_("Mentions légales"), { _(LEGAL_NOTICE) });
        about.add_credit_section (_("Écouteurs : merci à LibrePods"), {
            _("Le protocole des AirPods utilisé par Covalence a été décrit par le projet LibrePods "
            + "(https://github.com/librepods-org/librepods, GPL-3.0-or-later), créé par Kavish Devar. "
            + "Merci à lui et à tous les contributeurs de LibrePods pour leur remarquable travail "
            + "de rétro-ingénierie, sans lequel cette fonction n'existerait pas. "
            + "Covalence n'est pas affiliée à LibrePods.")
        });
        // "Name https://…" entries are shown as links by Gtk.AboutDialog.
        about.add_credit_section (_("iCloud Drive et Photos : merci à rclone"), {
            _("rclone, Nick Craig-Wood et contributeurs (MIT) https://github.com/rclone/rclone")
        });
        about.add_credit_section (_("Projets utilisés"), {
            _("LibrePods, Kavish Devar et contributeurs (GPL-3.0-or-later) https://github.com/librepods-org/librepods"),
            "rclone (MIT) https://github.com/rclone/rclone",
            _("BlueZ et obexd (GPL-2.0-or-later) https://github.com/bluez/bluez"),
            "PipeWire (MIT) https://gitlab.freedesktop.org/pipewire/pipewire",
            "WirePlumber (MIT) https://gitlab.freedesktop.org/pipewire/wireplumber",
            "Evolution Data Server (LGPL) https://gitlab.gnome.org/GNOME/evolution-data-server",
            "libsecret (LGPL-2.1-or-later) https://gitlab.gnome.org/GNOME/libsecret",
            "GTK (LGPL-2.1-or-later) https://gitlab.gnome.org/GNOME/gtk",
            "Granite (LGPL-3.0-or-later) https://github.com/elementary/granite",
            _("Icônes elementary, pour l'icône de l'app (GPL-3.0) https://github.com/elementary/icons"),
            "Vala (LGPL-2.1-or-later) https://gitlab.gnome.org/GNOME/vala",
            "PyGObject (LGPL-2.1-or-later) https://gitlab.gnome.org/GNOME/pygobject"
        });
        about.present ();
    }
}
