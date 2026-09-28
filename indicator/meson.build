# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
# Covalence in the top bar: a Wingpanel indicator (GTK 4, wingpanel-9), built when the
# Wingpanel development files are present (option indicator=auto) or required (enabled).
shared_library('covalence-indicator',
  'Indicator.vala',
  dependencies: [
    wingpanel_dep,
    dependency('gtk4'),
    dependency('granite-7'),
    dependency('gio-2.0'),
    dependency('gio-unix-2.0'),
  ],
  c_args: ['-DLOCALEDIR="@0@"'.format(localedir)],
  install: true,
  install_dir: wingpanel_dep.get_variable('indicatorsdir'),
)
