// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Covalence: iPhone and Apple services on elementary OS.
 * The app is a thin client of the covalenced daemon (io.github.melvincouwez.Covalence1).
 */

public class Covalence.Application : Gtk.Application {
    private const string STYLE = """
        .bubble {
            border-radius: 18px;
            padding: 7px 12px;
        }
        .bubble.incoming {
            background-color: alpha(@fg_color, 0.09);
            color: @fg_color;
        }
        .bubble.outgoing {
            background-color: @selected_bg_color;
            color: @selected_fg_color;
        }
        .reaction-badge {
            font-size: 0.85em;
            padding: 1px 7px;
            border-radius: 9999px;
            background-color: @base_color;
            color: @fg_color;
            border: 1px solid alpha(@fg_color, 0.15);
            box-shadow: 0 1px 2px alpha(black, 0.15);
        }
        .reaction-badge.pending {
            opacity: 0.6;
        }
        .reaction-strip {
            border-radius: 9999px;
            padding: 1px 3px;
            background-color: @base_color;
            border: 1px solid alpha(@fg_color, 0.12);
            box-shadow: 0 1px 3px alpha(black, 0.15);
        }
        .reaction-choice {
            font-size: 1.15em;
            min-width: 28px;
            min-height: 28px;
            padding: 0;
            border-radius: 9999px;
        }
        .control-pad {
            min-height: 220px;
            background-color: alpha(@fg_color, 0.04);
        }
        .control-pad:focus {
            background-color: alpha(@accent_color, 0.12);
        }
        .alpha-pill {
            font-size: 0.8em;
            font-weight: bold;
            padding: 1px 8px;
            border-radius: 9999px;
            background-color: alpha(@accent_color, 0.18);
            color: @accent_color;
        }
        .sent-check {
            color: alpha(@fg_color, 0.45);
            margin-top: -1px;
        }
        .search-flash .bubble {
            outline: 2px solid @selected_bg_color;
            outline-offset: 2px;
            transition: outline-color 300ms ease-out;
        }
        .hover-tools {
            transition: opacity 120ms ease-out;
        }
        .unread-dot {
            min-width: 9px;
            min-height: 9px;
            border-radius: 50%;
            background-color: @accent_color;
        }
        .compose-field {
            border: 1px solid alpha(@fg_color, 0.15);
            border-radius: 20px;
            padding: 0;
            background-color: @base_color;
        }
        .compose-field textview.compose-text,
        .compose-field textview.compose-text text,
        .compose-field scrolledwindow {
            background: none;
        }
        /* Emoji and send: same round 30 px footprint, 4 px from the field's edge. */
        .compose-round,
        menubutton.compose-round > button {
            min-width: 30px;
            min-height: 30px;
            padding: 0;
            margin: 0;
            border-radius: 9999px;
        }
        .compose-field > .compose-round {
            margin: 4px;
        }
        menubutton.compose-emoji > button {
            background: none;
            border: none;
            box-shadow: none;
            color: alpha(@fg_color, 0.65);
        }
        menubutton.compose-emoji > button:hover {
            color: @fg_color;
            background-color: alpha(@fg_color, 0.08);
        }
        window.quick-reply .quick-reply-title {
            font-weight: bold;
        }
        button.quick-answer {
            border-radius: 9999px;
            padding: 3px 12px;
        }
        button.keypad-key {
            min-width: 58px;
            min-height: 58px;
            padding: 0;
        }
        .keypad-digit {
            font-size: 1.5em;
        }
        .keypad-letters {
            font-size: 0.6em;
            font-weight: bold;
            letter-spacing: 1px;
            opacity: 0.6;
        }
        entry.dial-number {
            font-size: 1.4em;
        }
        button.call-option {
            min-width: 52px;
            min-height: 52px;
        }
        button.call-green,
        button.call-red {
            min-width: 64px;
            min-height: 64px;
            color: white;
            -gtk-icon-size: 24px;
        }
        button.call-green {
            background-image: linear-gradient(@LIME_500, @LIME_700);
        }
        button.call-red {
            background-image: linear-gradient(@STRAWBERRY_500, @STRAWBERRY_700);
        }
        .setup-column {
            padding: 18px;
        }
        .setup-number {
            min-width: 22px;
            min-height: 22px;
            border-radius: 9999px;
            background-color: alpha(@accent_color, 0.18);
            color: @accent_color;
            font-weight: bold;
            font-size: 0.85em;
        }
        .setup-step-title {
            font-weight: bold;
        }
        .onboarding-dot {
            min-width: 8px;
            min-height: 8px;
            border-radius: 9999px;
            background-color: alpha(@fg_color, 0.2);
        }
        .onboarding-dot.current {
            background-color: @accent_color;
        }
        button.choice-card {
            border-radius: 12px;
            padding: 0;
        }
        button.choice-card .choice-check {
            opacity: 0;
            color: @accent_color;
        }
        button.choice-card:checked {
            box-shadow: inset 0 0 0 2px @accent_color;
            background-color: alpha(@accent_color, 0.08);
        }
        button.choice-card:checked .choice-check {
            opacity: 1;
        }
        .call-bar {
            background-image: linear-gradient(@LIME_500, @LIME_700);
            color: white;
        }
        .call-bar label {
            color: white;
        }
        .call-bar-name {
            font-weight: bold;
        }
        .call-bar button {
            color: white;
            background: alpha(white, 0.15);
            border: none;
            box-shadow: none;
            min-width: 32px;
            min-height: 32px;
        }
        .call-bar button:checked {
            background: white;
            color: @LIME_700;
        }
        .call-bar button.call-red-small {
            background-image: linear-gradient(@STRAWBERRY_500, @STRAWBERRY_700);
        }
        .call-bar button.call-green-small {
            background: white;
            color: @LIME_700;
        }
        .unread {
            font-weight: bold;
        }
        .guide-tip {
            background-color: alpha(@accent_color, 0.08);
        }
        .guide-warning {
            background-color: alpha(@BANANA_500, 0.16);
        }
        .beta-badge {
            background-color: alpha(@accent_color, 0.15);
            color: @accent_color;
            border-radius: 999px;
            padding: 0 7px;
            font-size: 0.8em;
            font-weight: 600;
        }
        .now-playing-art {
            border-radius: 12px;
            background-color: alpha(@fg_color, 0.07);
            box-shadow: 0 3px 12px alpha(black, 0.25);
        }
        .now-playing-empty {
            color: alpha(@fg_color, 0.35);
        }
        .now-playing-artist {
            font-size: 1.15em;
        }
        .mini-player {
            margin: 6px;
            padding: 6px 4px 6px 6px;
            border-radius: 8px;
            background-color: alpha(@fg_color, 0.06);
        }
        .mini-player:hover {
            background-color: alpha(@fg_color, 0.1);
        }
        .mini-player-art {
            border-radius: 5px;
        }
        .mini-player-title {
            font-weight: 600;
        }
        .now-playing-play {
            min-width: 48px;
            min-height: 48px;
        }
        .now-playing-play image {
            -gtk-icon-size: 24px;
        }
    """;

    public Mode mode { get; construct; }
    // Started with --call, --reply, --page…: that action opened its window, activate() must not add the hub.
    private bool skip_activate = false;

    public Application (Mode mode) {
        // A snapshot run (development) must not take over the user's open windows.
        var snapshot = Environment.get_variable ("COVALENCE_SNAPSHOT") != null;
        Object (application_id: Config.APP_ID + mode.suffix (),
                flags: snapshot ? ApplicationFlags.NON_UNIQUE : ApplicationFlags.DEFAULT_FLAGS,
                mode: mode);
        add_main_option ("setup", 0, OptionFlags.NONE, OptionArg.NONE,
                         _("Open the setup assistant"), null);
        add_main_option ("page", 0, OptionFlags.NONE, OptionArg.STRING,
                         _("Open a tab: setup, device, messages, phone, contacts, headphones, guide"), "NAME");
        add_main_option ("topic", 0, OptionFlags.NONE, OptionArg.STRING,
                         _("With --page guide: open this topic of the guide"), "ID");
        add_main_option ("call", 0, OptionFlags.NONE, OptionArg.NONE,
                         _("Show the in-call window"), null);
        add_main_option ("to", 0, OptionFlags.NONE, OptionArg.STRING,
                         _("Write to a phone number or address (Messages)"), "ADDRESS");
        add_main_option ("thread", 0, OptionFlags.NONE, OptionArg.STRING,
                         _("Open a message thread"), "ID");
        add_main_option ("reply", 0, OptionFlags.NONE, OptionArg.STRING,
                         _("Open a message thread ready to answer"), "ID");
        add_main_option ("resolve-packages", 0, OptionFlags.HIDDEN, OptionArg.STRING,
                         _("Development: resolve comma-separated packages through PackageKit, install nothing"),
                         "NAMES");
    }

    /* Development check of the PackageKit path up to Resolve: prints the ids, installs nothing. */
    private static int resolve_packages (string names) {
        var loop = new MainLoop ();
        int status = 0;
        var installer = new PackageInstaller ();
        installer.resolve.begin (names.split (","), (obj, res) => {
            try {
                foreach (var id in installer.resolve.end (res)) {
                    print ("%s\n", id);
                }
            } catch (Error e) {
                printerr ("%s\n", e.message);
                status = 1;
            }
            loop.quit ();
        });
        loop.run ();
        return status;
    }

    /* covalenced opens a conversation from a notification: forward it to the running instance. */
    protected override int handle_local_options (VariantDict options) {
        string? thread = null;
        string? to = null;
        bool reply = options.lookup ("reply", "s", out thread);
        string? page = null;
        string? packages = null;
        if (options.lookup ("resolve-packages", "s", out packages)) {
            return resolve_packages (packages);
        }
        if (options.contains ("setup") || options.lookup ("page", "s", out page)) {
            try {
                register (null);
            } catch (Error e) {
                return 1;
            }
            if (page == "guide") {
                string? topic = null;
                options.lookup ("topic", "s", out topic);
                activate_action ("guide", new Variant ("s", topic ?? ""));
            } else {
                activate_action ("show-page", new Variant ("s", page ?? "setup"));
            }
            skip_activate = !get_is_remote ();
            return get_is_remote () ? 0 : -1;
        }
        if (options.contains ("call")) {
            try {
                register (null);
            } catch (Error e) {
                return 1;
            }
            activate_action ("show-call", null);
            skip_activate = !get_is_remote ();
            return get_is_remote () ? 0 : -1;
        }
        if (options.lookup ("to", "s", out to)) {
            try {
                register (null);
            } catch (Error e) {
                return 1;
            }
            activate_action ("write-to", new Variant ("s", to));
            skip_activate = !get_is_remote ();
            return get_is_remote () ? 0 : -1;
        }
        if (!reply && !options.lookup ("thread", "s", out thread)) {
            return -1;
        }
        try {
            register (null);
        } catch (Error e) {
            warning ("cannot register: %s", e.message);
            return 1;
        }
        activate_action ("open-thread", new Variant ("(sb)", thread, reply));
        // Remote: the running instance shows it, this process is done.
        // Primary: keep running, the window has just been opened.
        skip_activate = !get_is_remote ();
        return get_is_remote () ? 0 : -1;
    }

    protected override void startup () {
        base.startup ();
        Granite.init ();

        // Granite 7.7+ follows the system light/dark preference by itself.

        var quit_action = new SimpleAction ("quit", null);
        quit_action.activate.connect (() => quit ());
        add_action (quit_action);
        set_accels_for_action ("app.quit", { "<Control>q" });
        // Ctrl+1 to Ctrl+8: sections of the main window (win.section). Set here: in the
        // window's construct block the window has no application yet.
        for (int i = 0; i < 8; i++) {
            set_accels_for_action ("win.section(%d)".printf (i), { "<Control>%d".printf (i + 1) });
        }

        // F1 in every window, detached apps included: the built-in guide.
        var guide = new SimpleAction ("guide", VariantType.STRING);
        guide.activate.connect ((param) => {
            Guide.open (active_window, param.get_string ());
            foreach (var w in get_windows ()) {
                if (w is GuideWindow) {
                    maybe_snapshot (w);
                }
            }
        });
        add_action (guide);
        set_accels_for_action ("app.guide('')", { "F1" });

        var open_thread = new SimpleAction ("open-thread", new VariantType ("(sb)"));
        open_thread.activate.connect ((param) => {
            string thread;
            bool reply;
            param.get ("(sb)", out thread, out reply);
            if (reply) {
                new QuickReply (this, thread).present ();
                return;
            }
            if (mode != Mode.MESSAGES) {
                launch (Mode.MESSAGES, { "--thread", thread });
                return;
            }
            var window = messages_window ();
            window.present ();
            window.open_thread (thread);
            maybe_snapshot (window);
        });
        add_action (open_thread);

        var show_setup = new SimpleAction ("show-page", VariantType.STRING);
        show_setup.activate.connect ((param) => {
            MainWindow? window = null;
            foreach (var w in get_windows ()) {
                if (w is MainWindow) {
                    window = (MainWindow) w;
                }
            }
            if (window == null) {
                window = new MainWindow (this);
            }
            window.present ();
            window.show_page (param.get_string ());
            maybe_snapshot ();
        });
        add_action (show_setup);

        var show_call = new SimpleAction ("show-call", null);
        show_call.activate.connect (() => {
            foreach (var w in get_windows ()) {
                if (w is CallWindow) {
                    w.present ();
                    return;
                }
            }
            var call_window = new CallWindow (this);
            call_window.present ();
            maybe_snapshot (call_window);
        });
        add_action (show_call);

        var write_to = new SimpleAction ("write-to", VariantType.STRING);
        write_to.activate.connect ((param) => {
            if (mode != Mode.MESSAGES) {
                launch (Mode.MESSAGES, { "--to", param.get_string () });
                return;
            }
            var window = messages_window ();
            window.present ();
            window.write_to (param.get_string ());
        });
        add_action (write_to);

        Launchers.apply (Mode.MESSAGES);
        Launchers.apply (Mode.CONTACTS);
        Launchers.apply (Mode.PHONE);
        Launchers.apply (Mode.HEADPHONES);
        Launchers.apply (Mode.MIRROR);

        var css = new Gtk.CssProvider ();
        css.load_from_string (STYLE);
        Gtk.StyleContext.add_provider_for_display (Gdk.Display.get_default (), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION);
    }

    private AppWindow messages_window () {
        foreach (var w in get_windows ()) {
            if (w is AppWindow) {
                return (AppWindow) w;
            }
        }
        return new AppWindow (this, Mode.MESSAGES);
    }

    protected override void activate () {
        if (skip_activate) {
            skip_activate = false;
            return;
        }
        foreach (var w in get_windows ()) {
            if (!(w is QuickReply) && !(w is CallWindow)) {
                w.present ();
                return;
            }
        }
        if (mode == Mode.HUB) {
            new MainWindow (this).present ();
        } else {
            new AppWindow (this, mode).present ();
        }
        maybe_snapshot ();
    }

    /* Development only: COVALENCE_SNAPSHOT=/path.png renders the first window to a PNG after 3 s,
     * so the UI can be checked without screenshotting the desktop. */
    private void maybe_snapshot (Gtk.Window? shown = null) {
        var target = Environment.get_variable ("COVALENCE_SNAPSHOT");
        if (target == null || target == "") {
            return;
        }
        // COVALENCE_SNAPSHOT_DELAY: seconds before the capture (default 3).
        var delay = int.parse (Environment.get_variable ("COVALENCE_SNAPSHOT_DELAY") ?? "3");
        Timeout.add_seconds (delay > 0 ? delay : 3, () => {
            var window = shown ?? active_window ?? (get_windows ().length () > 0 ? get_windows ().nth_data (0) : null);
            if (window == null) {
                return Source.REMOVE;
            }
            var paintable = new Gtk.WidgetPaintable (window);
            var snapshot = new Gtk.Snapshot ();
            paintable.snapshot (snapshot, window.get_width (), window.get_height ());
            var node = snapshot.to_node ();
            var renderer = window.get_native ().get_renderer ();
            if (node != null && renderer != null) {
                var scale = window.get_scale_factor ();
                var texture = renderer.render_texture (node, null);
                texture.save_to_png (target);
                message ("snapshot saved (scale %d)", scale);
            }
            return Source.REMOVE;
        });
    }

    public static int main (string[] args) {
        Language.apply ();
        if (args.length == 2 && args[1] == "--copy-code") {
            return CodeCopy.run ();  // from a code notification (covalenced), no window
        }
        return new Application (Mode.from_program (args[0])).run (args);
    }
}
