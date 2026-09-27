# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
# Source strings are French; en.po is the English translation (beta).
# Update the template and en.po: meson compile -C build covalence-pot covalence-update-po
i18n = import('i18n')
i18n.gettext(gettext_package,
  preset: 'glib',
  args: ['--from-code=UTF-8', '--keyword=ngettext:1,2', '--keyword=pgettext:1c,2',
         '--add-comments=TRANSLATORS'],
)
