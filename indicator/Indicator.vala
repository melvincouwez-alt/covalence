/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * Covalence in the top bar (Wingpanel): the iPhone's state at a glance, with a dot for
 * unread messages or missed calls, and a popover with battery, what is playing, the call
 * in progress and shortcuts to the apps. Everything comes from the Covalence daemon over
 * D-Bus; the indicator hides itself when the daemon is not running or when the user turns
 * it off in Covalence (apps.conf [general] indicator=false).
 */

[CCode (cname = "GETTEXT_PACKAGE")]
extern const string GETTEXT_PACKAGE;
[CCode (cname = "LOCALEDIR")]
extern const string LOCALEDIR;

public class Covalence.Indicator : Wingpanel.Indicator {
    private const string BUS_NAME = "io.github.melvincouwez.Covalence.Daemon";
    private const string OBJECT_PATH = "/io/github/melvincouwez/Covalence/Daemon";
    private const string INTERFACE = "io.github.melvincouwez.Covalence1";
    private const string APP_ID = "io.github.melvincouwez.Covalence";

    private DBusProxy? proxy = null;
    private uint watch = 0;
    private FileMonitor? prefs_monitor = null;
    private bool wanted = true;

    private Gtk.Overlay display_widget;
    private Gtk.Image phone_icon;
    private Gtk.Box dot;

    private Gtk.Box? popover_widget = null;
    private Gtk.Label title;
    private Gtk.Label status;
    private Gtk.Box media_box;
    private Gtk.Label media_title;
    private Gtk.Label media_artist;
    private Gtk.Button play_button;
    private Gtk.Box call_box;
    private Gtk.Label call_label;
    private string call_path = "";
    private Gtk.Button messages_button;
    private Gtk.Button tethering_button;
    private bool tethering_on = false;

    public Indicator () {
        Object (code_name: "covalence");
    }

    construct {
        GLib.Intl.bindtextdomain (GETTEXT_PACKAGE, LOCALEDIR);
        GLib.Intl.bind_textdomain_codeset (GETTEXT_PACKAGE, "UTF-8");

        phone_icon = new Gtk.Image.from_icon_name ("phone-apple-iphone-symbolic");
        dot = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) {
            halign = Gtk.Align.END,
            valign = Gtk.Align.START,
            width_request = 6,
            height_request = 6,
            visible = false,
            can_target = false
        };
        dot.add_css_class ("covalence-indicator-dot");
        display_widget = new Gtk.Overlay () { child = phone_icon };
        display_widget.add_overlay (dot);

        var css = new Gtk.CssProvider ();
        css.load_from_string ("""
            .covalence-indicator-dot {
                background-color: @accent_color;
                border-radius: 9999px;
                min-width: 6px;
                min-height: 6px;
            }
            .covalence-indicator-off { opacity: 0.5; }
        """);
        Gtk.StyleContext.add_provider_for_display (Gdk.Display.get_default (), css,
                                                   Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION);

        visible = false;
        watch_prefs ();
        watch = Bus.watch_name (BusType.SESSION, BUS_NAME, BusNameWatcherFlags.NONE,
                                on_daemon_appeared, on_daemon_vanished);
    }

    public override Gtk.Widget get_display_widget () {
        return display_widget;
    }

    public override Gtk.Widget? get_widget () {
        if (popover_widget == null) {
            build_popover ();
            refresh ();
        }
        return popover_widget;
    }

    public override void opened () {
        refresh ();
        refresh_call.begin ();
    }

    public override void closed () {}

    /* --- the daemon ----------------------------------------------------------------------- */

    private void on_daemon_appeared (DBusConnection connection, string name, string owner) {
        connect_daemon.begin (connection);
    }

    private async void connect_daemon (DBusConnection connection) {
        try {
            proxy = yield new DBusProxy (connection, DBusProxyFlags.NONE, null, BUS_NAME, OBJECT_PATH,
                                         INTERFACE, null);
            proxy.g_properties_changed.connect (() => refresh ());
            proxy.g_signal.connect ((sender, signal_name, parameters) => {
                if (signal_name == "ActiveCallsChanged") {
                    refresh_call.begin ();
                }
            });
        } catch (Error e) {
            warning ("Covalence daemon unreachable: %s", e.message);
            proxy = null;
        }
        refresh ();
        refresh_call.begin ();
    }

    private void on_daemon_vanished (DBusConnection? connection, string name) {
        proxy = null;
        call_path = "";
        refresh ();
    }

    private Variant? prop (string name) {
        return proxy != null ? proxy.get_cached_property (name) : null;
    }

    private bool prop_bool (string name) {
        var v = prop (name);
        return v != null && v.is_of_type (VariantType.BOOLEAN) && v.get_boolean ();
    }

    private string prop_string (string name) {
        var v = prop (name);
        return v != null && v.is_of_type (VariantType.STRING) ? v.get_string () : "";
    }

    private int64 prop_number (string name, int64 fallback = 0) {
        var v = prop (name);
        if (v == null) {
            return fallback;
        }
        if (v.is_of_type (VariantType.INT32)) {
            return v.get_int32 ();
        }
        if (v.is_of_type (VariantType.UINT32)) {
            return v.get_uint32 ();
        }
        return fallback;
    }

    private string media_string (string key) {
        var v = prop ("NowPlaying");
        if (v == null) {
            return "";
        }
        var value = v.lookup_value (key, VariantType.STRING);
        return value != null ? value.get_string () : "";
    }

    /* The daemon may not offer every method (older versions): look before calling. */
    private bool has_method (string method) {
        if (proxy == null) {
            return false;
        }
        var info = proxy.get_interface_info ();
        if (info != null) {
            return info.lookup_method (method) != null;
        }
        try {
            var reply = proxy.get_connection ().call_sync (BUS_NAME, OBJECT_PATH,
                "org.freedesktop.DBus.Introspectable", "Introspect", null, new VariantType ("(s)"),
                DBusCallFlags.NONE, 500, null);
            var node = new DBusNodeInfo.for_xml (reply.get_child_value (0).get_string ());
            var iface = node.lookup_interface (INTERFACE);
            if (iface != null) {
                proxy.set_interface_info (iface);
                return iface.lookup_method (method) != null;
            }
        } catch (Error e) {
            debug ("introspection failed: %s", e.message);
        }
        return false;
    }

    private void call_daemon (string method, Variant? args = null) {
        if (proxy == null) {
            return;
        }
        proxy.call.begin (method, args, DBusCallFlags.NONE, 10000, null, (obj, res) => {
            try {
                proxy.call.end (res);
            } catch (Error e) {
                warning ("%s failed: %s", method, e.message);
            }
        });
    }

    private async void refresh_call () {
        if (proxy == null) {
            call_path = "";
            update_call ("");
            return;
        }
        try {
            var reply = yield proxy.call ("ListActiveCalls", null, DBusCallFlags.NONE, 3000, null);
            var calls = reply.get_child_value (0);
            call_path = "";
            var text = "";
            for (size_t i = 0; i < calls.n_children (); i++) {
                var call = calls.get_child_value (i);
                var path = call.lookup_value ("path", VariantType.STRING);
                var state = call.lookup_value ("state", VariantType.STRING);
                if (path == null) {
                    continue;
                }
                var who_name = call.lookup_value ("name", VariantType.STRING);
                var who_number = call.lookup_value ("number", VariantType.STRING);
                var who = who_name != null && who_name.get_string () != "" ? who_name.get_string ()
                    : who_number != null ? who_number.get_string () : "";
                call_path = path.get_string ();
                var label = state != null && state.get_string () == "incoming"
                    ? _("Appel entrant") : _("Appel en cours");
                text = who != "" ? "%s · %s".printf (label, who) : label;
                break;
            }
            update_call (text);
        } catch (Error e) {
            call_path = "";
            update_call ("");
        }
    }

    /* --- the user's choice in Covalence ---------------------------------------------------- */

    private static string prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    private void read_prefs () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            wanted = prefs.get_boolean ("general", "indicator");
        } catch (Error e) {
            wanted = true;  // shown unless turned off
        }
    }

    private void watch_prefs () {
        read_prefs ();
        try {
            prefs_monitor = File.new_for_path (prefs_path ()).monitor_file (FileMonitorFlags.NONE);
            prefs_monitor.changed.connect (() => {
                read_prefs ();
                refresh ();
            });
        } catch (Error e) {
            debug ("cannot watch apps.conf: %s", e.message);
        }
    }

    /* --- display ----------------------------------------------------------------------------- */

    private void refresh () {
        visible = wanted && proxy != null && prop_bool ("Paired");
        if (!visible) {
            return;
        }
        var connected = prop_bool ("Connected");
        if (connected) {
            phone_icon.remove_css_class ("covalence-indicator-off");
        } else {
            phone_icon.add_css_class ("covalence-indicator-off");
        }
        var unread = prop_number ("UnreadMessages");
        var missed = prop_number ("MissedCalls");
        dot.visible = unread > 0 || missed > 0;
        var name = prop_string ("DeviceName");
        display_widget.tooltip_text = connected
            ? _("%s relié").printf (name != "" ? name : "iPhone")
            : _("%s non relié").printf (name != "" ? name : "iPhone");

        if (popover_widget == null) {
            return;
        }
        title.label = name != "" ? name : "iPhone";
        var battery = prop_number ("Battery", -1);
        if (!connected) {
            status.label = _("Non relié");
        } else if (battery >= 0) {
            status.label = _("Relié · batterie %d %%").printf ((int) battery);
        } else {
            status.label = _("Relié");
        }

        var track = media_string ("title");
        var playing = media_string ("status") == "playing";
        media_box.visible = connected && track != "";
        media_title.label = track;
        media_artist.label = media_string ("artist");
        media_artist.visible = media_artist.label != "";
        play_button.icon_name = playing ? "media-playback-pause-symbolic"
                                        : "media-playback-start-symbolic";
        play_button.tooltip_text = playing ? _("Pause") : _("Lecture");

        messages_button.label = unread > 0
            ? ngettext ("Messages · %u non lu", "Messages · %u non lus", (ulong) unread).printf ((uint) unread)
            : _("Messages");

        tethering_button.visible = connected && has_method ("SetTethering");
        var tether = prop ("Tethering");
        tethering_on = tether != null && tether.is_of_type (VariantType.BOOLEAN) && tether.get_boolean ();
        tethering_button.label = tethering_on ? _("Couper la connexion via l'iPhone")
                                              : _("Se connecter via l'iPhone");
    }

    private void update_call (string text) {
        if (popover_widget == null) {
            return;
        }
        call_box.visible = text != "";
        call_label.label = text;
    }

    private Gtk.Button menu_button (string label) {
        var button = new Gtk.Button.with_label (label);
        button.add_css_class ("menuitem");
        var child = button.child as Gtk.Label;
        if (child != null) {
            child.xalign = 0;
        }
        return button;
    }

    private Gtk.Button media_control (string icon, string tooltip, string command) {
        var button = new Gtk.Button.from_icon_name (icon) { tooltip_text = tooltip };
        button.add_css_class ("flat");
        button.clicked.connect (() => call_daemon ("MediaCommand", new Variant ("(s)", command)));
        return button;
    }

    private void build_popover () {
        title = new Gtk.Label ("") { xalign = 0 };
        title.add_css_class ("heading");
        status = new Gtk.Label ("") { xalign = 0 };
        status.add_css_class (Granite.CssClass.DIM);
        var header = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) {
            margin_start = 12,
            margin_end = 12,
            margin_top = 6,
            margin_bottom = 6
        };
        header.append (title);
        header.append (status);

        // What is playing on the iPhone (AMS), with the three usual buttons.
        media_title = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END, max_width_chars = 28 };
        media_artist = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END, max_width_chars = 28 };
        media_artist.add_css_class (Granite.CssClass.DIM);
        var words = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { hexpand = true };
        words.append (media_title);
        words.append (media_artist);
        play_button = media_control ("media-playback-start-symbolic", _("Lecture"), "toggle");
        var controls = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { valign = Gtk.Align.CENTER };
        controls.append (media_control ("media-skip-backward-symbolic", _("Précédent"), "previous"));
        controls.append (play_button);
        controls.append (media_control ("media-skip-forward-symbolic", _("Suivant"), "next"));
        media_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            margin_start = 12,
            margin_end = 6,
            margin_top = 3,
            margin_bottom = 3
        };
        media_box.append (words);
        media_box.append (controls);

        // A call in progress or ringing: who, and hang up.
        call_label = new Gtk.Label ("") { xalign = 0, hexpand = true, ellipsize = Pango.EllipsizeMode.END };
        var hangup = new Gtk.Button.from_icon_name ("call-stop-symbolic") { tooltip_text = _("Raccrocher") };
        hangup.add_css_class (Granite.CssClass.DESTRUCTIVE);
        hangup.add_css_class (Granite.CssClass.CIRCULAR);
        hangup.clicked.connect (() => {
            if (call_path != "") {
                call_daemon ("CallAction", new Variant ("(os)", call_path, "hangup"));
            }
        });
        call_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            margin_start = 12,
            margin_end = 12,
            margin_top = 3,
            margin_bottom = 3,
            visible = false
        };
        call_box.append (call_label);
        call_box.append (hangup);

        messages_button = menu_button (_("Messages"));
        messages_button.clicked.connect (() => launch (APP_ID + ".Messages"));
        tethering_button = menu_button (_("Se connecter via l'iPhone"));
        tethering_button.visible = false;
        tethering_button.clicked.connect (() => {
            call_daemon ("SetTethering", new Variant ("(b)", !tethering_on));
            close ();
        });
        var open = menu_button (_("Ouvrir Covalence"));
        open.clicked.connect (() => launch (APP_ID));

        popover_widget = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { width_request = 260 };
        popover_widget.append (header);
        popover_widget.append (media_box);
        popover_widget.append (call_box);
        popover_widget.append (new Gtk.Separator (Gtk.Orientation.HORIZONTAL) { margin_top = 3, margin_bottom = 3 });
        popover_widget.append (messages_button);
        popover_widget.append (tethering_button);
        popover_widget.append (new Gtk.Separator (Gtk.Orientation.HORIZONTAL) { margin_top = 3, margin_bottom = 3 });
        popover_widget.append (open);
    }

    private void launch (string desktop_id) {
        close ();
        var info = new DesktopAppInfo (desktop_id + ".desktop");
        if (info == null) {
            info = new DesktopAppInfo (APP_ID + ".desktop");
        }
        if (info == null) {
            return;
        }
        try {
            info.launch (null, null);
        } catch (Error e) {
            warning ("cannot open %s: %s", desktop_id, e.message);
        }
    }
}

public Wingpanel.Indicator? get_indicator (Module module, Wingpanel.ServerType server_type) {
    if (server_type != Wingpanel.ServerType.SESSION) {
        return null;
    }
    return new Covalence.Indicator ();
}
