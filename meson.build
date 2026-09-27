# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
project('io.github.melvincouwez.Covalence', 'vala', 'c',
  version: '0.2.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 1.0',
)

app_id = meson.project_name()
prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / 'covalence'
localedir = prefix / get_option('localedir')
gettext_package = 'covalence'

python = find_program('python3')

conf = configuration_data()
conf.set('APP_ID', app_id)
conf.set('VERSION', meson.project_version())
conf.set('BINDIR', bindir)
conf.set('PKGDATADIR', pkgdatadir)
conf.set('PYTHON', python.full_path())
conf.set('GETTEXT_PACKAGE', gettext_package)
conf.set('LOCALEDIR', localedir)

# Interface texts: French source strings, English in po/en.po (beta).
add_project_arguments('-DGETTEXT_PACKAGE="@0@"'.format(gettext_package), language: 'c')

# Daemon (Python + Gio): see README for why it is not Vala yet.
install_subdir('covalenced', install_dir: pkgdatadir, exclude_directories: ['__pycache__'])
foreach script : ['covalenced', 'covalence-icloud-signin', 'covalence-icloud-drive', 'covalence-rclone']
  configure_file(input: 'bin' / script + '.in', output: script, configuration: conf,
                 install: true, install_dir: bindir, install_mode: 'rwxr-xr-x')
endforeach

install_subdir('data' / 'guide', install_dir: pkgdatadir)

install_data('docs' / 'mentions-legales.md', 'docs' / 'confidentialite.md',
             'docs' / 'privacy.md', 'LICENSE',
             install_dir: pkgdatadir / 'docs')

subdir('data')
subdir('po')
subdir('src')

gnome = import('gnome')
gnome.post_install(gtk_update_icon_cache: true, update_desktop_database: true)
