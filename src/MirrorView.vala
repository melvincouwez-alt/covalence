// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Recopie d'écran (experimental): the iPhone's screen in a window on the PC,
 * through UxPlay, a free AirPlay receiver (covalenced/mirror.py). The receiver
 * only runs between « Recevoir l'écran de l'iPhone » and « Arrêter ».
 *
 * The picture stays in UxPlay's own window (another program: its video cannot be
 * drawn in this GTK window without passing frames between processes). This page
 * is the control panel: start and stop, profile, rotation, full screen, and the
 * iPhone control pad (covalenced/hid.py: the PC as a Bluetooth mouse and keyboard).
 */

public class Covalence.MirrorView : Gtk.Box {
    public Daemon daemon { get; construct; }

    // HID usages and modifier bits for iOS shortcuts (⌘ = GUI).
    private const uint GUI = 0x08;
    private const uint KEY_H = 0x0B;
    private const uint KEY_SPACE = 0x2C;
    private const uint KEY_TAB = 0x2B;
    private const uint EVDEV_LEFTMETA = 125;
    private const uint BUTTON_LEFT = 1;
    private const uint BUTTON_RIGHT = 2;

    private InstallBox install;
    private Gtk.Box ready_box;
    private Gtk.Button start_button;
    private Gtk.Label state_label;
    private Gtk.Label steps;
    private Gtk.DropDown profile;
    private Gtk.DropDown rotation;
    private Gtk.Switch fullscreen;
    private Gtk.Label decoder_label;
    private bool updating = false;

    private Gtk.Switch control_switch;
    private Gtk.Box control_box;
    private Gtk.Label control_state;
    private Gtk.ToggleButton command_held;
    private Gtk.SpinButton width_spin;
    private Gtk.SpinButton height_spin;
    private double last_x = -1;
    private double last_y = -1;
    private double pending_x = 0;
    private double pending_y = 0;
    private uint flush_timer = 0;

    public MirrorView (Daemon daemon) {
        Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        Gtk.ScrolledWindow scroll;
        var content = PageHeader.column (out scroll);
        var top = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        var header = PageHeader.build (
            _("Recopie d'écran"),
            _("L'écran de l'iPhone dans une fenêtre de ce PC, par AirPlay, sur le même Wi-Fi."),
            _("Expérimental"));
        header.hexpand = true;
        top.append (header);
        var guide = Guide.help_button ("mirror", _("Guide de la recopie et du contrôle"));
        guide.valign = Gtk.Align.START;
        top.append (guide);
        content.append (top);

        install = new InstallBox ();
        install.installed.connect (() => daemon.call.begin ("StopMirror"));  // refreshes the state
        content.append (install);

        ready_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        start_button = new Gtk.Button.with_label (_("Recevoir l'écran de l'iPhone")) {
            halign = Gtk.Align.START
        };
        start_button.add_css_class (Granite.CssClass.SUGGESTED);
        start_button.clicked.connect (toggle);
        state_label = new Gtk.Label ("") { xalign = 0, wrap = true };
        state_label.add_css_class (Granite.CssClass.DIM);
        steps = new Gtk.Label ("") { xalign = 0, wrap = true, use_markup = true };
        ready_box.append (start_button);
        ready_box.append (state_label);
        ready_box.append (new Granite.HeaderLabel (_("Affichage")));
        ready_box.append (build_options ());
        ready_box.append (new Granite.HeaderLabel (_("Sur l'iPhone")));
        ready_box.append (steps);
        var note = new Gtk.Label (
            _("Covalence utilise UxPlay, un récepteur AirPlay libre. Il n'écoute le réseau que pendant "
              + "la recopie. Fermez la fenêtre de recopie ou touchez « Arrêter » pour finir.")
        ) { xalign = 0, wrap = true };
        note.add_css_class (Granite.CssClass.DIM);
        note.add_css_class (Granite.CssClass.SMALL);
        ready_box.append (note);
        content.append (ready_box);

        content.append (new Granite.HeaderLabel (_("Contrôler l'iPhone depuis le PC")));
        content.append (build_control ());
        append (scroll);

        daemon.changed.connect (update);
        update ();
    }

    // --- display options -------------------------------------------------------------------

    private Gtk.Widget option_row (string title, string subtitle, Gtk.Widget control) {
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        if (subtitle != "") {
            var sub = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
            sub.add_css_class (Granite.CssClass.DIM);
            sub.add_css_class (Granite.CssClass.SMALL);
            text.append (sub);
        }
        control.valign = Gtk.Align.CENTER;
        control.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9, margin_bottom = 9, margin_start = 12, margin_end = 12
        };
        box.append (text);
        box.append (control);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private Gtk.Widget build_options () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);

        profile = new Gtk.DropDown.from_strings ({ _("Fluide"), _("Qualité") });
        profile.notify["selected"].connect (() => {
            if (!updating) {
                set_option ("profile", profile.selected == 1 ? "quality" : "fluid");
            }
        });
        list.append (option_row (_("Profil"),
                                 _("Fluide : le moins de retard, pour piloter l'iPhone. Qualité : le son "
                                   + "reste calé sur l'image, pour une vidéo."), profile));

        rotation = new Gtk.DropDown.from_strings ({ _("Aucune"), _("Vers la droite"), _("Vers la gauche") });
        rotation.notify["selected"].connect (() => {
            if (!updating) {
                string[] values = { "", "R", "L" };
                set_option ("rotation", values[rotation.selected]);
            }
        });
        list.append (option_row (_("Rotation"), "", rotation));

        fullscreen = new Gtk.Switch ();
        fullscreen.notify["active"].connect (() => {
            if (!updating) {
                set_option ("fullscreen", fullscreen.active ? "true" : "false");
            }
        });
        list.append (option_row (_("Plein écran"), _("Échap ou F11 dans la fenêtre de recopie pour en sortir"),
                                 fullscreen));

        decoder_label = new Gtk.Label ("") { xalign = 1 };
        decoder_label.add_css_class (Granite.CssClass.DIM);
        list.append (option_row (_("Décodage vidéo"),
                                 _("Choisi selon la carte graphique ; repli en logiciel en cas d'échec"),
                                 decoder_label));
        var hint = new Gtk.Label (_("Les changements s'appliquent au prochain démarrage de la recopie.")) {
            xalign = 0, wrap = true
        };
        hint.add_css_class (Granite.CssClass.DIM);
        hint.add_css_class (Granite.CssClass.SMALL);
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
        box.append (list);
        box.append (hint);
        return box;
    }

    private void set_option (string key, string value) {
        daemon.call.begin ("SetMirrorOption", new Variant ("(ss)", key, value));
    }

    /* The PC's screen size, so the iPhone sends a picture that fits it. */
    private void send_screen_size () {
        var display = Gdk.Display.get_default ();
        if (display == null) {
            return;
        }
        Gdk.Monitor? monitor = null;
        var native = get_native ();
        if (native != null && native.get_surface () != null) {
            monitor = display.get_monitor_at_surface (native.get_surface ());
        }
        if (monitor == null && display.get_monitors ().get_n_items () > 0) {
            monitor = (Gdk.Monitor) display.get_monitors ().get_item (0);
        }
        if (monitor == null) {
            return;
        }
        var area = monitor.geometry;
        var scale = monitor.scale_factor;
        set_option ("screen", "%dx%d".printf (area.width * scale, area.height * scale));
    }

    private void toggle () {
        var running = Props.flag (daemon.get_value ("Mirror"), "running");
        if (!running) {
            send_screen_size ();
        }
        daemon.call.begin (running ? "StopMirror" : "StartMirror");
    }

    // --- control ----------------------------------------------------------------------------

    private Gtk.Widget build_control () {
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        list.add_css_class (Granite.CssClass.CARD);
        control_switch = new Gtk.Switch ();
        control_switch.notify["active"].connect (() => {
            if (!updating) {
                daemon.call.begin ("SetAlphaFeature",
                                   new Variant ("(sb)", "iphone_control", control_switch.active));
            }
        });
        list.append (option_row (_("Souris et clavier Bluetooth"),
                                 _("Le PC se présente à l'iPhone comme une souris et un clavier. "
                                   + "Expérimental, désactivé par défaut."), control_switch));
        box.append (list);

        control_state = new Gtk.Label ("") { xalign = 0, wrap = true };
        control_state.add_css_class (Granite.CssClass.DIM);
        box.append (control_state);

        control_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        control_box.append (build_pad ());

        var shortcuts = new Gtk.FlowBox () {
            selection_mode = Gtk.SelectionMode.NONE, max_children_per_line = 4, column_spacing = 6,
            row_spacing = 6, homogeneous = false
        };
        shortcuts.append (shortcut_button (_("Accueil"), _("⌘H : retour à l'écran d'accueil"), KEY_H));
        shortcuts.append (shortcut_button (_("Recherche"), _("⌘Espace : recherche de l'iPhone"), KEY_SPACE));
        shortcuts.append (shortcut_button (_("Changer d'app"), _("⌘Tab : app précédente"), KEY_TAB));
        command_held = new Gtk.ToggleButton.with_label ("⌘") {
            tooltip_text = _("Maintenir ⌘ enfoncé pour la prochaine touche (la touche Super du PC "
                             + "est souvent prise par le bureau)")
        };
        command_held.toggled.connect (() => {
            daemon.call.begin ("ControlKey", new Variant ("(ub)", EVDEV_LEFTMETA, command_held.active));
        });
        shortcuts.append (command_held);
        var center = new Gtk.Button.with_label (_("Recaler le pointeur")) {
            tooltip_text = _("Ramène le pointeur au centre de l'écran de l'iPhone")
        };
        center.clicked.connect (() => daemon.call.begin ("ControlGoto", new Variant ("(dd)", 0.5, 0.5)));
        shortcuts.append (center);
        control_box.append (shortcuts);

        var entry = new Gtk.Entry () {
            placeholder_text = _("Texte à taper sur l'iPhone"),
            hexpand = true
        };
        var send = new Gtk.Button.with_label (_("Taper"));
        send.clicked.connect (() => type_text (entry));
        entry.activate.connect (() => type_text (entry));
        var line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        line.append (entry);
        line.append (send);
        control_box.append (line);

        var size_list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        size_list.add_css_class (Granite.CssClass.CARD);
        width_spin = new Gtk.SpinButton.with_range (50, 4000, 10);
        height_spin = new Gtk.SpinButton.with_range (50, 8000, 10);
        width_spin.value_changed.connect (send_size);
        height_spin.value_changed.connect (send_size);
        size_list.append (option_row (_("Largeur de l'écran pour le pointeur"),
                                      _("Si « Recaler » ne tombe pas au centre, ajustez ces deux valeurs"),
                                      width_spin));
        size_list.append (option_row (_("Hauteur de l'écran pour le pointeur"), "", height_spin));
        var expander = new Gtk.Expander (_("Réglage du pointeur")) { child = size_list };
        control_box.append (expander);
        box.append (control_box);
        return box;
    }

    private Gtk.Widget shortcut_button (string label, string tooltip, uint usage) {
        var button = new Gtk.Button.with_label (label) { tooltip_text = tooltip };
        button.clicked.connect (() => {
            daemon.call.begin ("ControlShortcut", new Variant ("(uu)", usage, GUI));
        });
        return button;
    }

    private void type_text (Gtk.Entry entry) {
        var text = entry.text;
        if (text == "") {
            return;
        }
        daemon.call.begin ("ControlText", new Variant ("(s)", text));
        entry.text = "";
    }

    private void send_size () {
        if (!updating) {
            daemon.call.begin ("SetControlSize", new Variant ("(uu)", (uint) width_spin.value,
                                                             (uint) height_spin.value));
        }
    }

    /* The pad: the PC's mouse over it moves the iPhone's pointer; keys typed while it has
       the focus go to the iPhone. */
    private Gtk.Widget build_pad () {
        var pad = new Gtk.DrawingArea () {
            content_height = 220,
            hexpand = true,
            focusable = true,
            can_focus = true,
            cursor = new Gdk.Cursor.from_name ("crosshair", null)
        };
        pad.add_css_class ("control-pad");
        pad.update_property (Gtk.AccessibleProperty.LABEL, _("Pavé de contrôle de l'iPhone"), -1);
        pad.set_draw_func ((area, cr, width, height) => {
            var layout = area.create_pango_layout (
                area.has_focus
                ? _("Souris et clavier dirigés vers l'iPhone")
                : _("Cliquez ici, puis déplacez la souris : le pointeur de l'iPhone suit"));
            layout.set_width ((width - 24) * Pango.SCALE);
            layout.set_alignment (Pango.Alignment.CENTER);
            int text_width, text_height;
            layout.get_pixel_size (out text_width, out text_height);
            var color = area.get_color ();
            cr.set_source_rgba (color.red, color.green, color.blue, 0.55);
            cr.move_to (12, (height - text_height) / 2.0);
            Pango.cairo_show_layout (cr, layout);
        });

        var motion = new Gtk.EventControllerMotion ();
        motion.enter.connect ((x, y) => {
            last_x = x;
            last_y = y;
        });
        motion.motion.connect ((x, y) => {
            if (last_x >= 0) {
                pending_x += x - last_x;
                pending_y += y - last_y;
                schedule_flush ();
            }
            last_x = x;
            last_y = y;
        });
        motion.leave.connect (() => last_x = -1);
        pad.add_controller (motion);

        var click = new Gtk.GestureClick () { button = 0 };
        click.pressed.connect ((n, x, y) => {
            pad.grab_focus ();
            pad.queue_draw ();
            daemon.call.begin ("ControlButton", new Variant ("(ub)", button_of (click), true));
        });
        click.released.connect ((n, x, y) => {
            daemon.call.begin ("ControlButton", new Variant ("(ub)", button_of (click), false));
        });
        pad.add_controller (click);

        var wheel = new Gtk.EventControllerScroll (Gtk.EventControllerScrollFlags.VERTICAL
                                                   | Gtk.EventControllerScrollFlags.DISCRETE);
        wheel.scroll.connect ((dx, dy) => {
            daemon.call.begin ("ControlScroll", new Variant ("(i)", (int) (-dy)));
            return true;
        });
        pad.add_controller (wheel);

        var keys = new Gtk.EventControllerKey ();
        keys.key_pressed.connect ((keyval, keycode, state) => {
            daemon.call.begin ("ControlKey", new Variant ("(ub)", keycode - 8, true));
            return true;
        });
        keys.key_released.connect ((keyval, keycode, state) => {
            daemon.call.begin ("ControlKey", new Variant ("(ub)", keycode - 8, false));
        });
        pad.add_controller (keys);
        var focus = new Gtk.EventControllerFocus ();
        focus.leave.connect (() => {
            daemon.call.begin ("ControlRelease");
            command_held.active = false;
            pad.queue_draw ();
        });
        pad.add_controller (focus);

        var frame = new Gtk.Frame (null) { child = pad };
        return frame;
    }

    private static uint button_of (Gtk.GestureClick click) {
        return click.get_current_button () == Gdk.BUTTON_SECONDARY ? BUTTON_RIGHT : BUTTON_LEFT;
    }

    /* Moves are gathered and sent about 60 times a second. */
    private void schedule_flush () {
        if (flush_timer != 0) {
            return;
        }
        flush_timer = Timeout.add (16, () => {
            flush_timer = 0;
            var dx = (int) pending_x;
            var dy = (int) pending_y;
            if (dx != 0 || dy != 0) {
                pending_x -= dx;
                pending_y -= dy;
                daemon.call.begin ("ControlMove", new Variant ("(ii)", dx, dy));
            }
            return Source.REMOVE;
        });
    }

    // --- state ---------------------------------------------------------------------------------

    private void update () {
        updating = true;
        var mirror = daemon.get_value ("Mirror");
        var missing = Props.strings (mirror, "missing");
        install.set_missing (missing, _("La recopie d'écran"));
        ready_box.visible = missing.length == 0;
        var running = Props.flag (mirror, "running");
        var name = Props.str (mirror, "name");
        start_button.label = running ? _("Arrêter") : _("Recevoir l'écran de l'iPhone");
        start_button.remove_css_class (running ? Granite.CssClass.SUGGESTED : Granite.CssClass.DESTRUCTIVE);
        start_button.add_css_class (running ? Granite.CssClass.DESTRUCTIVE : Granite.CssClass.SUGGESTED);
        var error = Props.str (mirror, "error");
        var pin = Props.str (mirror, "pin");
        if (running && pin != "") {
            state_label.label = _("En attente de l'iPhone sous le nom « %s ». Code à saisir sur "
                                  + "l'iPhone : %s").printf (name, pin);
        } else if (running) {
            state_label.label = _("En attente de l'iPhone sous le nom « %s »").printf (name);
        } else if (error == "exited") {
            state_label.label = _("Le récepteur s'est arrêté. Vérifiez qu'Avahi fonctionne et réessayez.");
        } else if (error != "" && error != "missing") {
            state_label.label = _("Le récepteur s'est arrêté : %s").printf (error);
        } else {
            state_label.label = _("Arrêté");
        }
        steps.label = _("1. Ouvrez le Centre de contrôle.\n2. Touchez « Recopie de l'écran ».\n"
                        + "3. Choisissez <b>%s</b>.\n4. Saisissez le code affiché ici.").printf (
                        Markup.escape_text (name));
        profile.selected = Props.str (mirror, "profile") == "quality" ? 1 : 0;
        var rot = Props.str (mirror, "rotation");
        rotation.selected = rot == "R" ? 1 : rot == "L" ? 2 : 0;
        fullscreen.active = Props.flag (mirror, "fullscreen");
        switch (Props.str (mirror, "decoder")) {
            case "nvidia": decoder_label.label = _("NVIDIA"); break;
            case "vaapi": decoder_label.label = _("VA-API"); break;
            default: decoder_label.label = _("Logiciel"); break;
        }

        var control = daemon.get_value ("Control");
        var enabled = Props.flag (control, "enabled");
        control_switch.active = enabled;
        control_box.visible = enabled && Props.flag (control, "registered");
        var control_error = Props.str (control, "error");
        if (!enabled) {
            control_state.label = _("Activez l'interrupteur, puis suivez le guide : appairage dans Réglages › "
                                    + "Bluetooth de l'iPhone et AssistiveTouch pour le pointeur.");
        } else if (control_error != "") {
            control_state.label = _("Bluetooth a refusé la souris et le clavier : %s").printf (control_error);
        } else if (Props.flag (control, "connected")) {
            control_state.label = _("L'iPhone utilise la souris et le clavier de Covalence.");
        } else {
            control_state.label = _("Publiés. Sur l'iPhone : Réglages › Bluetooth, touchez « Covalence » "
                                    + "sous Autres appareils (ou reconnectez-le).");
        }
        var width = Props.integer (control, "width");
        var height = Props.integer (control, "height");
        if (width > 0 && (int) width_spin.value != width) {
            width_spin.value = width;
        }
        if (height > 0 && (int) height_spin.value != height) {
            height_spin.value = height;
        }
        updating = false;
    }
}
