// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Lecture en cours: what the iPhone is playing (music, podcast, any audio app),
 * with its controls.
 *
 * The daemon publishes a NowPlaying dictionary (covalenced/nowplaying.py): the
 * position is sent with the moment it was measured and the rate, so the bar
 * moves here, once a second, only while the page is on screen.
 */

namespace Covalence {
    public class NowPlayingView : Gtk.Box {
        public Daemon daemon { get; construct; }

        private Gtk.Stack stack;
        private Granite.Placeholder idle;
        private Gtk.Button idle_play;
        private Gtk.Stack art_stack;
        private Gtk.Picture art;
        private Gtk.Label title_label;
        private Gtk.Label artist_label;
        private Gtk.Label album_label;
        private Gtk.Image app_icon;
        private Gtk.Label app_label;
        private Gtk.ProgressBar progress;
        private Gtk.Label elapsed_label;
        private Gtk.Label remaining_label;
        private Gtk.Button previous_button;
        private Gtk.Button play_button;
        private Gtk.Button next_button;
        private Gtk.Box volume_box;
        private Gtk.Scale volume;
        private bool updating = false;
        private uint tick = 0;
        private uint volume_timer = 0;

        private string status = "stopped";
        private double position = 0;
        private double position_time = 0;
        private double rate = 1;
        private double duration = 0;
        private string[] commands = {};

        public NowPlayingView (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
        }

        construct {
            idle = new Granite.Placeholder (_("Rien en lecture sur l'iPhone")) {
                description = _("Lancez de la musique, un podcast ou une vidéo sur l'iPhone : "
                                + "le titre et les commandes s'affichent ici."),
                icon = new ThemedIcon (Config.APP_ID + ".NowPlaying")
            };
            // Play reaches the iPhone even with nothing known: it resumes its last audio.
            idle_play = idle.append_button (new ThemedIcon ("media-playback-start"), _("Lecture"),
                                            _("Reprendre la dernière écoute de l'iPhone"));
            idle_play.clicked.connect (() => send ("play"));

            art = new Gtk.Picture () {
                content_fit = Gtk.ContentFit.COVER,
                can_shrink = true
            };
            var art_empty = new Gtk.Image.from_icon_name ("audio-x-generic-symbolic") { pixel_size = 96 };
            art_empty.add_css_class ("now-playing-empty");
            art_stack = new Gtk.Stack () {
                width_request = 240,
                height_request = 240,
                halign = Gtk.Align.CENTER,
                overflow = Gtk.Overflow.HIDDEN
            };
            art_stack.add_css_class ("now-playing-art");
            art_stack.add_named (art_empty, "empty");
            art_stack.add_named (art, "art");

            title_label = new Gtk.Label ("") {
                wrap = true,
                justify = Gtk.Justification.CENTER,
                max_width_chars = 36,
                selectable = true
            };
            title_label.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
            artist_label = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
            artist_label.add_css_class ("now-playing-artist");
            album_label = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
            album_label.add_css_class (Granite.CssClass.DIM);

            app_icon = new Gtk.Image () { pixel_size = 16 };
            app_label = new Gtk.Label ("");
            app_label.add_css_class (Granite.CssClass.DIM);
            app_label.add_css_class (Granite.CssClass.SMALL);
            var app_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { halign = Gtk.Align.CENTER };
            app_box.append (app_icon);
            app_box.append (app_label);

            progress = new Gtk.ProgressBar () { hexpand = true };
            progress.update_property (Gtk.AccessibleProperty.LABEL, _("Progression de la lecture"), -1);
            elapsed_label = new Gtk.Label ("0:00");
            remaining_label = new Gtk.Label ("");
            foreach (var l in new Gtk.Label[] { elapsed_label, remaining_label }) {
                l.add_css_class (Granite.CssClass.DIM);
                l.add_css_class (Granite.CssClass.SMALL);
                l.add_css_class ("numeric");
            }
            var times = new Gtk.CenterBox () { start_widget = elapsed_label, end_widget = remaining_label };
            var progress_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 4) { width_request = 320 };
            progress_box.append (progress);
            progress_box.append (times);

            previous_button = control_button ("media-skip-backward-symbolic", _("Précédent"), "previous");
            play_button = control_button ("media-playback-start-symbolic", _("Lecture"), "toggle");
            play_button.add_css_class ("now-playing-play");
            next_button = control_button ("media-skip-forward-symbolic", _("Suivant"), "next");
            var controls = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 18) { halign = Gtk.Align.CENTER };
            controls.append (previous_button);
            controls.append (play_button);
            controls.append (next_button);

            volume = new Gtk.Scale.with_range (Gtk.Orientation.HORIZONTAL, 0, 1, 0.0625) {
                hexpand = true,
                draw_value = false
            };
            volume.update_property (Gtk.AccessibleProperty.LABEL, _("Volume de l'iPhone"), -1);
            volume.value_changed.connect (on_volume);
            volume_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { width_request = 320 };
            volume_box.append (new Gtk.Image.from_icon_name ("audio-volume-low-symbolic"));
            volume_box.append (volume);
            volume_box.append (new Gtk.Image.from_icon_name ("audio-volume-high-symbolic"));

            var player = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
                margin_top = 24,
                margin_bottom = 24,
                margin_start = 24,
                margin_end = 24,
                halign = Gtk.Align.CENTER,
                valign = Gtk.Align.CENTER
            };
            player.append (art_stack);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { margin_top = 6 };
            text.append (title_label);
            text.append (artist_label);
            text.append (album_label);
            player.append (text);
            player.append (app_box);
            player.append (progress_box);
            player.append (controls);
            player.append (volume_box);
            var help = Guide.help_button ("sound", _("Lecture en cours : aide"));
            help.halign = Gtk.Align.CENTER;
            player.append (help);

            stack = new Gtk.Stack () { transition_type = Gtk.StackTransitionType.CROSSFADE, vexpand = true };
            stack.add_named (idle, "idle");
            stack.add_named (new Gtk.ScrolledWindow () {
                child = player,
                hscrollbar_policy = Gtk.PolicyType.NEVER
            }, "player");
            append (stack);

            daemon.changed.connect (update);
            map.connect (() => {
                update ();
                if (tick == 0) {
                    tick = Timeout.add_seconds (1, () => {
                        show_position ();
                        return Source.CONTINUE;
                    });
                }
            });
            unmap.connect (() => {
                if (tick != 0) {
                    Source.remove (tick);
                    tick = 0;
                }
            });
            update ();
        }

        private Gtk.Button control_button (string icon, string label, string command) {
            var button = new Gtk.Button.from_icon_name (icon) { tooltip_text = label, valign = Gtk.Align.CENTER };
            button.add_css_class ("circular");
            button.add_css_class ("flat");
            button.update_property (Gtk.AccessibleProperty.LABEL, label, -1);
            button.clicked.connect (() => send (command));
            return button;
        }

        private void send (string command) {
            daemon.call.begin ("MediaCommand", new Variant ("(s)", command));
        }

        private void on_volume () {
            if (updating) {
                return;
            }
            // AMS moves the volume by steps: one step per call, a little apart.
            if (volume_timer != 0) {
                Source.remove (volume_timer);
            }
            volume_timer = Timeout.add (250, () => {
                volume_timer = 0;
                daemon.call.begin ("SetMediaVolume", new Variant ("(d)", volume.get_value ()));
                return Source.REMOVE;
            });
        }

        private static string text (VariantDict d, string key) {
            var v = d.lookup_value (key, VariantType.STRING);
            return v != null ? v.get_string () : "";
        }

        private static double number (VariantDict d, string key, double fallback = 0) {
            var v = d.lookup_value (key, VariantType.DOUBLE);
            return v != null ? v.get_double () : fallback;
        }

        public void update () {
            var value = daemon.get_value ("NowPlaying");
            var d = new VariantDict (value);
            var title = text (d, "title");
            status = text (d, "status");
            if (value == null || text (d, "source") == "" || (title == "" && status != "playing")) {
                var can_play = d.lookup_value ("can_play", VariantType.BOOLEAN);
                idle_play.visible = can_play != null && can_play.get_boolean ();
                stack.visible_child_name = "idle";
                return;
            }
            stack.visible_child_name = "player";
            updating = true;
            title_label.label = title != "" ? title : _("Lecture en cours");
            var artist = text (d, "artist");
            artist_label.label = artist;
            artist_label.visible = artist != "";
            var album = text (d, "album");
            album_label.label = album;
            album_label.visible = album != "";

            var app = text (d, "app");
            var image = text (d, "app_image");
            var icon = text (d, "app_icon");
            if (image != "") {
                app_icon.set_from_file (image);
            } else {
                app_icon.set_from_icon_name (icon != "" ? icon : "phone");
            }
            app_label.label = app != "" ? _("Sur l'iPhone · %s").printf (app) : _("Sur l'iPhone");

            var artwork = text (d, "artwork");
            if (artwork != "") {
                art.set_filename (artwork);
                art_stack.visible_child_name = "art";
            } else {
                art.set_paintable (null);
                art_stack.visible_child_name = "empty";
            }

            position = number (d, "position");
            position_time = number (d, "position_time");
            rate = number (d, "rate", 1);
            duration = number (d, "duration");
            var cmds = d.lookup_value ("commands", VariantType.STRING_ARRAY);
            commands = cmds != null ? cmds.dup_strv () : new string[0];

            var playing = status == "playing";
            play_button.icon_name = playing ? "media-playback-pause-symbolic" : "media-playback-start-symbolic";
            play_button.tooltip_text = playing ? _("Pause") : _("Lecture");
            play_button.update_property (Gtk.AccessibleProperty.LABEL, play_button.tooltip_text, -1);
            // Never greyed out: toggle falls back to play/pause in the daemon.
            play_button.sensitive = true;
            previous_button.sensitive = can ("previous");
            next_button.sensitive = can ("next");

            var level = number (d, "volume", -1);
            var has_volume = d.lookup_value ("can_volume", VariantType.BOOLEAN);
            volume_box.visible = level >= 0 && has_volume != null && has_volume.get_boolean ();
            if (volume_box.visible && volume_timer == 0) {
                volume.set_value (level);
            }
            updating = false;
            show_position ();
        }

        private bool can (string command) {
            foreach (var c in commands) {
                if (c == command) {
                    return true;
                }
            }
            return false;
        }

        private void show_position () {
            if (stack.visible_child_name != "player") {
                return;
            }
            var now = get_real_time () / 1000000.0;
            var at = position;
            if (status == "playing" && position_time > 0) {
                at += rate * double.max (now - position_time, 0);
            }
            if (duration > 0) {
                at = double.min (at, duration);
                progress.fraction = at / duration;
                remaining_label.label = "−" + clock (duration - at);
            } else {
                progress.fraction = 0;
                remaining_label.label = "";
            }
            progress.visible = duration > 0;
            elapsed_label.label = clock (at);
        }

        private static string clock (double seconds) {
            var s = (int) double.max (seconds, 0);
            if (s >= 3600) {
                return "%d:%02d:%02d".printf (s / 3600, (s / 60) % 60, s % 60);
            }
            return "%d:%02d".printf (s / 60, s % 60);
        }
    }

    /*
     * Mini player at the bottom of the sidebar, above Réglages: small artwork,
     * title and artist, play/pause and next. A click elsewhere on it opens the
     * Now Playing page. Hidden while nothing is known.
     */
    public class MiniPlayer : Gtk.Box {
        public Daemon daemon { get; construct; }
        public signal void open_requested ();

        private Gtk.Stack art_stack;
        private Gtk.Image art;
        private Gtk.Label title_label;
        private Gtk.Label artist_label;
        private Gtk.Button toggle;

        public MiniPlayer (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.HORIZONTAL, spacing: 8);
        }

        construct {
            add_css_class ("mini-player");
            visible = false;
            art = new Gtk.Image () { pixel_size = 36 };
            art_stack = new Gtk.Stack () {
                hexpand = false,
                valign = Gtk.Align.CENTER,
                overflow = Gtk.Overflow.HIDDEN
            };
            art_stack.add_css_class ("mini-player-art");
            art_stack.add_named (new Gtk.Image.from_icon_name (Config.APP_ID + ".NowPlaying") {
                pixel_size = 36
            }, "empty");
            art_stack.add_named (art, "art");

            title_label = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
            title_label.add_css_class ("mini-player-title");
            artist_label = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
            artist_label.add_css_class (Granite.CssClass.DIM);
            artist_label.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) {
                hexpand = true,
                valign = Gtk.Align.CENTER
            };
            text.append (title_label);
            text.append (artist_label);

            toggle = new Gtk.Button.from_icon_name ("media-playback-start-symbolic") {
                valign = Gtk.Align.CENTER
            };
            toggle.add_css_class ("flat");
            toggle.add_css_class ("circular");
            toggle.clicked.connect (() => command ("toggle"));
            var next = new Gtk.Button.from_icon_name ("media-skip-forward-symbolic") {
                valign = Gtk.Align.CENTER,
                tooltip_text = _("Suivant")
            };
            next.add_css_class ("flat");
            next.add_css_class ("circular");
            next.update_property (Gtk.AccessibleProperty.LABEL, _("Suivant"), -1);
            next.clicked.connect (() => command ("next"));

            append (art_stack);
            append (text);
            append (toggle);
            append (next);

            var click = new Gtk.GestureClick ();
            click.released.connect ((n, x, y) => {
                var target = pick (x, y, Gtk.PickFlags.DEFAULT);
                if (target != null && (target == toggle || target.is_ancestor (toggle)
                                       || target == next || target.is_ancestor (next))) {
                    return;
                }
                open_requested ();
            });
            add_controller (click);
            tooltip_text = _("Lecture en cours");
            daemon.changed.connect (update);
            update ();
        }

        private void command (string name) {
            daemon.call.begin ("MediaCommand", new Variant ("(s)", name));
        }

        private static string text (VariantDict d, string key) {
            var v = d.lookup_value (key, VariantType.STRING);
            return v != null ? v.get_string () : "";
        }

        private void update () {
            var value = daemon.get_value ("NowPlaying");
            var d = new VariantDict (value);
            var title = text (d, "title");
            visible = value != null && title != "" && daemon.module_enabled ("media");
            if (!visible) {
                return;
            }
            title_label.label = title;
            var artist = text (d, "artist");
            artist_label.label = artist != "" ? artist : text (d, "app");
            artist_label.visible = artist_label.label != "";
            var artwork = text (d, "artwork");
            if (artwork != "") {
                art.set_from_file (artwork);
                art_stack.visible_child_name = "art";
            } else {
                art_stack.visible_child_name = "empty";
            }
            var playing = text (d, "status") == "playing";
            toggle.icon_name = playing ? "media-playback-pause-symbolic" : "media-playback-start-symbolic";
            toggle.tooltip_text = playing ? _("Pause") : _("Lecture");
            toggle.update_property (Gtk.AccessibleProperty.LABEL, toggle.tooltip_text, -1);
        }
    }
}
