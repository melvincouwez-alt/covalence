/*
 * Built-in guide: a native window (no browser), French and English.
 *
 * Topics are small text files installed in PKGDATADIR/guide/<lang>/NN-id.md:
 *
 *     title: Relier l'iPhone
 *     icon: phone
 *     summary: One line shown under the title and in the list.
 *     ---
 *     ## Heading
 *     A paragraph, lines joined until a blank line. **bold**, `code`,
 *     [a link](guide:messages), [a section of the app](app:services), [a site](https://…).
 *     - a bullet
 *     1. a numbered step
 *     !tip A tip, until a blank line.
 *     !warn A warning, until a blank line.
 *     ### A question (troubleshooting)
 *
 * The folder next to the sources (COVALENCE_GUIDE_DIR) is read first when set, for development.
 */

namespace Covalence.Guide {
    public string language () {
        var forced = Environment.get_variable ("COVALENCE_GUIDE_LANG");
        if (forced == "fr" || forced == "en") {
            return forced;
        }
        return Language.resolved ();
    }

    /* Open the guide (one window per app), on a topic if given. */
    public void open (Gtk.Window? parent, string topic = "") {
        var app = GLib.Application.get_default () as Gtk.Application;
        GuideWindow? window = null;
        if (app != null) {
            foreach (var w in app.get_windows ()) {
                if (w is GuideWindow) {
                    window = (GuideWindow) w;
                }
            }
        }
        if (window == null) {
            window = new GuideWindow (app);
        }
        if (topic != "") {
            window.show_topic (topic);
        }
        window.present ();
    }

    /* Small round "?" that opens one topic of the guide. */
    public Gtk.Button help_button (string topic, string tooltip) {
        var button = new Gtk.Button.from_icon_name ("help-contents-symbolic") {
            tooltip_text = tooltip,
            valign = Gtk.Align.CENTER
        };
        button.add_css_class ("flat");
        button.add_css_class ("circular");
        button.clicked.connect (() => open (button.get_root () as Gtk.Window, topic));
        return button;
    }

    public class Topic : Object {
        public string id;
        public string title = "";
        public string icon = "help-contents";
        public string summary = "";
        public string body = "";
    }
}

public class Covalence.GuideWindow : Gtk.Window {
    private string lang;
    private Guide.Topic[] topics = {};
    private Gtk.ListBox list;
    private Gtk.SearchEntry search;
    private Gtk.Box content;
    private Gtk.ScrolledWindow scroll;
    private Gtk.Label header_title;
    private Gtk.Label side_title;
    private Gtk.ToggleButton fr_button;
    private Gtk.ToggleButton en_button;
    private string current = "";
    private bool switching = false;

    public GuideWindow (Gtk.Application? app) {
        Object (application: app, default_width: 980, default_height: 700);
    }

    construct {
        lang = Guide.language ();
        title = lang == "fr" ? "Guide de Covalence" : "Covalence Guide";

        // Sidebar: search + topics, same layout as the main window.
        search = new Gtk.SearchEntry () {
            margin_top = 6,
            margin_bottom = 6,
            margin_start = 12,
            margin_end = 12
        };
        list = new Gtk.ListBox () { vexpand = true };
        list.add_css_class ("navigation-sidebar");
        list.row_selected.connect ((row) => {
            if (row != null && !switching) {
                render (topics[row.get_index ()]);
            }
        });
        list.set_filter_func ((row) => matches (topics[row.get_index ()], search.text));
        search.search_changed.connect (() => {
            list.invalidate_filter ();
            var first = first_visible ();
            if (first != null && search.text.strip () != "") {
                list.select_row (first);
            }
        });
        search.activate.connect (() => {
            var first = first_visible ();
            if (first != null) {
                list.select_row (first);
            }
        });

        var side_header = new Gtk.HeaderBar () {
            show_title_buttons = false,
            title_widget = new Gtk.Label ("") { visible = false }
        };
        side_header.add_css_class ("flat");
        side_header.pack_start (new Gtk.WindowControls (Gtk.PackType.START));
        side_title = new Gtk.Label ("") { xalign = 0, margin_start = 12 };
        side_title.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());

        var side = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { width_request = 250 };
        side.add_css_class ("sidebar");
        side.append (side_header);
        side.append (side_title);
        side.append (search);
        side.append (new Gtk.ScrolledWindow () { child = list, hscrollbar_policy = Gtk.PolicyType.NEVER, vexpand = true });

        // Language switch: only the guide's language, the app keeps its own.
        fr_button = new Gtk.ToggleButton.with_label ("FR");
        en_button = new Gtk.ToggleButton.with_label ("EN") { group = fr_button };
        (lang == "fr" ? fr_button : en_button).active = true;
        var switcher = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0);
        switcher.add_css_class ("linked");
        switcher.append (fr_button);
        switcher.append (en_button);
        fr_button.toggled.connect (() => {
            if (fr_button.active) {
                set_language ("fr");
            }
        });
        en_button.toggled.connect (() => {
            if (en_button.active) {
                set_language ("en");
            }
        });

        header_title = new Gtk.Label ("") { ellipsize = Pango.EllipsizeMode.END };
        header_title.add_css_class ("title");
        var main_header = new Gtk.HeaderBar () { title_widget = header_title, decoration_layout = MainWindow.split_layout (false) };
        main_header.add_css_class ("flat");
        main_header.pack_end (switcher);

        content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 12,
            margin_bottom = 36,
            margin_start = 36,
            margin_end = 36
        };
        var clamp = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { halign = Gtk.Align.CENTER, width_request = 620 };
        clamp.append (content);
        scroll = new Gtk.ScrolledWindow () {
            child = clamp,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true,
            hexpand = true
        };
        var main = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        main.append (main_header);
        main.append (scroll);
        main.add_css_class (Granite.STYLE_CLASS_VIEW);

        var paned = new Gtk.Paned (Gtk.Orientation.HORIZONTAL) {
            start_child = side,
            end_child = main,
            resize_start_child = false,
            shrink_start_child = false,
            shrink_end_child = false
        };
        child = paned;
        titlebar = new Gtk.Grid () { visible = false };

        // Esc closes, Ctrl+F searches.
        var keys = new Gtk.EventControllerKey ();
        keys.key_pressed.connect ((keyval, code, state) => {
            if (keyval == Gdk.Key.Escape && search.text == "") {
                close ();
                return true;
            }
            if (keyval == Gdk.Key.f && (state & Gdk.ModifierType.CONTROL_MASK) != 0) {
                search.grab_focus ();
                return true;
            }
            return false;
        });
        ((Gtk.Widget) this).add_controller (keys);
        // Typing anywhere searches (not in snapshot runs: they must not catch the user's keys).
        if (Environment.get_variable ("COVALENCE_SNAPSHOT") == null) {
            search.set_key_capture_widget (this);
        } else {
            search.focusable = false;
            list.focusable = false;
        }

        load ();
        update_texts ();
        show_topic (Environment.get_variable ("COVALENCE_GUIDE_TOPIC") ?? "");
        // Development: COVALENCE_GUIDE_SEARCH fills the search box (snapshot of a search).
        var query = Environment.get_variable ("COVALENCE_GUIDE_SEARCH");
        if (query != null) {
            search.text = query;
        }
    }

    private void update_texts () {
        search.placeholder_text = lang == "fr" ? "Rechercher dans le guide" : "Search the guide";
        side_title.label = "Guide";
        title = lang == "fr" ? "Guide de Covalence" : "Covalence Guide";
        fr_button.tooltip_text = "Français";
        en_button.tooltip_text = "English";
    }

    private void set_language (string wanted) {
        if (wanted == lang) {
            return;
        }
        var keep = current;
        lang = wanted;
        load ();
        update_texts ();
        show_topic (keep);
    }

    public void show_topic (string id) {
        int index = 0;
        for (int i = 0; i < topics.length; i++) {
            if (topics[i].id == id) {
                index = i;
            }
        }
        if (topics.length == 0) {
            return;
        }
        search.text = "";
        var row = list.get_row_at_index (index);
        if (list.get_selected_row () == row) {
            render (topics[index]);
        } else {
            list.select_row (row);
        }
    }

    private Gtk.ListBoxRow? first_visible () {
        for (int i = 0; ; i++) {
            var row = list.get_row_at_index (i);
            if (row == null) {
                return null;
            }
            if (row.get_child_visible () && matches (topics[i], search.text)) {
                return row;
            }
        }
    }

    private static string fold (string text) {
        return text.normalize (-1, NormalizeMode.NFKD).casefold ()
            .replace ("́", "").replace ("̀", "").replace ("̂", "")
            .replace ("̈", "").replace ("̧", "");
    }

    private bool matches (Guide.Topic topic, string query) {
        var q = fold (query.strip ());
        if (q == "") {
            return true;
        }
        var hay = fold (topic.title + "\n" + topic.summary + "\n" + topic.body);
        foreach (var word in q.split (" ")) {
            if (word != "" && !hay.contains (word)) {
                return false;
            }
        }
        return true;
    }

    // --- loading ---------------------------------------------------------------------------

    private static string guide_dir () {
        var dev = Environment.get_variable ("COVALENCE_GUIDE_DIR");
        if (dev != null && dev != "") {
            return dev;
        }
        return Path.build_filename (Config.PKGDATADIR, "guide");
    }

    private void load () {
        switching = true;
        Gtk.ListBoxRow? row;
        while ((row = list.get_row_at_index (0)) != null) {
            list.remove (row);
        }
        topics = {};
        var dir_path = Path.build_filename (guide_dir (), lang);
        var names = new GLib.List<string> ();
        try {
            var dir = Dir.open (dir_path);
            string? name;
            while ((name = dir.read_name ()) != null) {
                if (name.has_suffix (".md")) {
                    names.insert_sorted (name, strcmp);
                }
            }
        } catch (Error e) {
            warning ("guide not found in %s: %s", dir_path, e.message);
        }
        foreach (var name in names) {
            var topic = parse_file (Path.build_filename (dir_path, name));
            if (topic != null) {
                topics += topic;
                list.append (topic_row (topic));
            }
        }
        switching = false;
    }

    private static Guide.Topic? parse_file (string path) {
        string text;
        try {
            FileUtils.get_contents (path, out text);
        } catch (Error e) {
            return null;
        }
        var topic = new Guide.Topic ();
        var base_name = Path.get_basename (path);
        topic.id = base_name.substring (0, base_name.length - 3);
        var dash = topic.id.index_of ("-");
        if (dash > 0) {
            topic.id = topic.id.substring (dash + 1);  // "03-link" -> "link"
        }
        var split = text.index_of ("\n---\n");
        var head = split >= 0 ? text.substring (0, split) : "";
        topic.body = split >= 0 ? text.substring (split + 5) : text;
        foreach (var line in head.split ("\n")) {
            var colon = line.index_of (":");
            if (colon < 0) {
                continue;
            }
            var key = line.substring (0, colon).strip ();
            var value = line.substring (colon + 1).strip ();
            if (key == "title") {
                topic.title = value;
            } else if (key == "icon") {
                topic.icon = value.replace ("@APP_ID@", Config.APP_ID);
            } else if (key == "summary") {
                topic.summary = value;
            }
        }
        return topic;
    }

    private Gtk.ListBoxRow topic_row (Guide.Topic topic) {
        var image = new Gtk.Image.from_icon_name (topic.icon) { pixel_size = 24 };
        var label = new Gtk.Label (topic.title) { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9) { margin_top = 3, margin_bottom = 3 };
        box.append (image);
        box.append (label);
        return new Gtk.ListBoxRow () { child = box };
    }

    // --- rendering --------------------------------------------------------------------------

    private void render (Guide.Topic topic) {
        current = topic.id;
        header_title.label = topic.title;
        Gtk.Widget? child;
        while ((child = content.get_first_child ()) != null) {
            content.remove (child);
        }

        var top = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) { margin_bottom = 6 };
        top.append (new Gtk.Image.from_icon_name (topic.icon) { pixel_size = 48, valign = Gtk.Align.START });
        var titles = new Gtk.Box (Gtk.Orientation.VERTICAL, 3) { valign = Gtk.Align.CENTER };
        var h1 = new Gtk.Label (topic.title) { xalign = 0, wrap = true };
        h1.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());
        titles.append (h1);
        if (topic.summary != "") {
            var sub = new Gtk.Label (topic.summary) { xalign = 0, wrap = true };
            sub.add_css_class (Granite.CssClass.DIM);
            titles.append (sub);
        }
        top.append (titles);
        content.append (top);

        Gtk.Box? steps = null;
        int step = 0;
        Gtk.Box? bullets = null;
        string para = "";
        string callout = "";
        bool warn = false;

        var lines = topic.body.split ("\n");
        for (int i = 0; i <= lines.length; i++) {
            var raw = i < lines.length ? lines[i] : "";
            var line = raw.strip ();

            bool is_step = false;
            string step_text = "";
            var dot = line.index_of (". ");
            if (dot > 0 && dot <= 2) {
                is_step = true;
                for (int k = 0; k < dot; k++) {
                    if (!line[k].isdigit ()) {
                        is_step = false;
                    }
                }
                step_text = is_step ? line.substring (dot + 2) : "";
            }
            var block_start = line == "" || line.has_prefix ("#") || line.has_prefix ("- ")
                              || line.has_prefix ("!tip ") || line.has_prefix ("!warn ") || is_step;

            if (block_start || i == lines.length) {
                if (para != "") {
                    content.append (paragraph (para));
                    para = "";
                }
                if (callout != "") {
                    content.append (callout_box (callout, warn));
                    callout = "";
                }
            }
            if (!line.has_prefix ("- ") && bullets != null && line != "") {
                bullets = null;
            }
            if (!is_step && steps != null && line != "") {
                steps = null;
                step = 0;
            }
            if (i == lines.length || line == "") {
                continue;
            }

            if (line.has_prefix ("### ")) {
                var h = new Gtk.Label (inline (line.substring (4))) { xalign = 0, wrap = true, use_markup = true, margin_top = 6 };
                h.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
                content.append (h);
            } else if (line.has_prefix ("## ")) {
                var h = new Gtk.Label (inline (line.substring (3))) { xalign = 0, wrap = true, use_markup = true, margin_top = 12 };
                h.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
                content.append (h);
            } else if (line.has_prefix ("- ")) {
                if (bullets == null) {
                    bullets = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
                    content.append (bullets);
                }
                var row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9);
                var dot_label = new Gtk.Label ("•") { valign = Gtk.Align.START, margin_start = 6 };
                dot_label.add_css_class (Granite.CssClass.DIM);
                row.append (dot_label);
                row.append (text_label (line.substring (2)));
                bullets.append (row);
            } else if (is_step) {
                if (steps == null) {
                    steps = new Gtk.Box (Gtk.Orientation.VERTICAL, 10) { margin_top = 3 };
                    content.append (steps);
                }
                step++;
                var row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 10);
                var number = new Gtk.Label ("%d".printf (step)) { valign = Gtk.Align.START };
                number.add_css_class ("setup-number");
                row.append (number);
                row.append (text_label (step_text));
                steps.append (row);
            } else if (line.has_prefix ("!tip ")) {
                callout = line.substring (5);
                warn = false;
            } else if (line.has_prefix ("!warn ")) {
                callout = line.substring (6);
                warn = true;
            } else if (callout != "") {
                callout += " " + line;
            } else {
                para = para == "" ? line : para + " " + line;
            }
        }
        // After the new content is laid out: back to the top.
        Idle.add (() => {
            scroll.vadjustment.value = 0;
            return Source.REMOVE;
        });
    }

    private Gtk.Label text_label (string text) {
        var label = new Gtk.Label (inline (text)) {
            xalign = 0,
            wrap = true,
            wrap_mode = Pango.WrapMode.WORD_CHAR,
            use_markup = true,
            selectable = false,
            hexpand = true
        };
        label.activate_link.connect (follow);
        return label;
    }

    private Gtk.Widget paragraph (string text) {
        return text_label (text);
    }

    private Gtk.Widget callout_box (string text, bool warning) {
        var icon = new Gtk.Image.from_icon_name (warning ? "dialog-warning" : "dialog-information") {
            pixel_size = 24,
            valign = Gtk.Align.START
        };
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) { margin_top = 3, margin_bottom = 3 };
        box.add_css_class (Granite.CssClass.CARD);
        box.add_css_class (warning ? "guide-warning" : "guide-tip");
        var inner = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 12,
            margin_bottom = 12,
            margin_start = 12,
            margin_end = 12
        };
        inner.append (icon);
        inner.append (text_label (text));
        box.append (inner);
        return box;
    }

    /* **bold**, `code`, [text](target), with the rest escaped. */
    private static string inline (string source) {
        var out = new StringBuilder ();
        int i = 0;
        while (i < source.length) {
            if (source.substring (i).has_prefix ("**")) {
                var end = source.index_of ("**", i + 2);
                if (end > 0) {
                    out.append ("<b>" + inline (source.substring (i + 2, end - i - 2)) + "</b>");
                    i = end + 2;
                    continue;
                }
            }
            if (source[i] == '`') {
                var end = source.index_of ("`", i + 1);
                if (end > 0) {
                    out.append ("<tt>" + Markup.escape_text (source.substring (i + 1, end - i - 1)) + "</tt>");
                    i = end + 1;
                    continue;
                }
            }
            if (source[i] == '[') {
                var close = source.index_of ("](", i);
                var end = close > 0 ? source.index_of (")", close) : -1;
                if (close > 0 && end > 0) {
                    var text = source.substring (i + 1, close - i - 1);
                    var target = source.substring (close + 2, end - close - 2);
                    out.append ("<a href=\"%s\">%s</a>".printf (Markup.escape_text (target), inline (text)));
                    i = end + 1;
                    continue;
                }
            }
            var next = i;
            source.get_next_char (ref next, null);
            out.append (Markup.escape_text (source.substring (i, next - i)));
            i = next;
        }
        return out.str;
    }

    private bool follow (string uri) {
        if (uri.has_prefix ("guide:")) {
            show_topic (uri.substring (6));
            return true;
        }
        if (uri.has_prefix ("app:")) {
            var page = uri.substring (4);
            var app = application as Covalence.Application;
            if (app != null && app.mode == Mode.HUB) {
                app.activate_action ("show-page", new Variant ("s", page));
            } else {
                launch (Mode.HUB, { "--page", page });
            }
            return true;
        }
        return false;  // web links: default handler
    }
}
