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
            copyright = _("© 2026 Melvin Couwez et les contributeurs de Covalence"),
            authors = { "Melvin Couwez" },
            website = "https://github.com/melvincouwez-alt/covalence",
            website_label = _("Code source")
        };
        // The legal notice is long prose: in the wrapped licence page, not in a credit line.
        about.license = _(LEGAL_NOTICE) + "\n\n"
            + _("Covalence est distribuée sous licence GNU GPL, version 3 ou ultérieure : "
                + "https://www.gnu.org/licenses/gpl-3.0.html");
        about.wrap_license = true;
        // Short entries: "Name https://…" shows Name as a link, and keeps the window narrow.
        about.add_credit_section (_("Écouteurs AirPods"), {
            _("LibrePods, Kavish Devar et contributeurs https://github.com/librepods-org/librepods"),
            _("Merci pour la rétro-ingénierie du protocole"),
            _("Covalence n'est pas affiliée à LibrePods")
        });
        about.add_credit_section (_("iCloud Drive et Photos"), {
            _("rclone, Nick Craig-Wood et contributeurs https://github.com/rclone/rclone")
        });
        about.add_credit_section (_("Sons"), {
            _("Rosée, Envol, Vague, Écho · AOSP · Apache-2.0 https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds"),
            _("Duo, Clochette · AOSP · Apache-2.0 https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds"),
            _("Aurore, Orbite, Horizon, Écume · AOSP · Apache-2.0 https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds"),
            _("Brise, Cascade, Carrousel · AOSP · Apache-2.0 https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds"),
            _("Carillon, Cristal, Pop, Bulle · Kenney · CC0 https://kenney.nl/assets/interface-sounds"),
            _("Givre · Kenney · CC0 https://kenney.nl/assets/interface-sounds"),
            _("Téléphone · Covalence · CC0")
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
