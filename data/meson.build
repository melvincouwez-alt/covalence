# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
# System install (the .deb): /usr/lib/systemd/user; user install: ~/.local/share/systemd/user.
user_unit_dir = prefix == '/usr' ? '/usr/lib/systemd/user' : datadir / 'systemd' / 'user'

configure_file(input: 'covalenced.service.in', output: 'covalenced.service', configuration: conf,
               install: true, install_dir: user_unit_dir)
configure_file(input: 'metainfo.xml.in', output: app_id + '.metainfo.xml', configuration: conf,
               install: true, install_dir: datadir / 'metainfo')
configure_file(input: 'icloud-drive.service.in', output: 'covalence-icloud-drive.service',
               configuration: conf, install: true, install_dir: user_unit_dir)
configure_file(input: 'icloud-photos.service.in', output: 'covalence-icloud-photos.service',
               configuration: conf, install: true, install_dir: user_unit_dir)
configure_file(input: 'dbus.service.in', output: app_id + '.Daemon.service', configuration: conf,
               install: true, install_dir: datadir / 'dbus-1' / 'services')
configure_file(input: 'app.desktop.in', output: app_id + '.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
install_data('cloud-providers.ini', rename: app_id + '.ini',
             install_dir: datadir / 'cloud-providers')
foreach suffix : ['', '.Contacts', '.Phone', '.NowPlaying', '.Mirror']
  install_data('icons' / app_id + suffix + '.svg',
               install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
endforeach
# Messages and Contacts: the same program under their own application ids.
configure_file(input: 'messages.desktop.in', output: app_id + '.Messages.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
configure_file(input: 'contacts.desktop.in', output: app_id + '.Contacts.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
configure_file(input: 'phone.desktop.in', output: app_id + '.Phone.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
configure_file(input: 'headphones.desktop.in', output: app_id + '.Headphones.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
configure_file(input: 'mirror.desktop.in', output: app_id + '.Mirror.desktop', configuration: conf,
               install: true, install_dir: datadir / 'applications')
foreach suffix : ['.Messages', '.Contacts', '.Phone', '.Headphones', '.Mirror']
  install_symlink(app_id + suffix, pointing_to: app_id, install_dir: bindir)
endforeach

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  foreach suffix : ['', '.Messages', '.Contacts', '.Phone', '.Headphones', '.Mirror']
    test('desktop file' + suffix, desktop_validate,
         args: [meson.current_build_dir() / app_id + suffix + '.desktop'])
  endforeach
endif
