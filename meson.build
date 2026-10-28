project('glance', version: '0.1.0', meson_version: '>= 1.0.0')

gnome = import('gnome')
py = import('python').find_installation('python3')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

subdir('data')
subdir('src')

test('unit', py, args: ['-m', 'pytest', '-q', meson.project_source_root() / 'tests'],
     workdir: meson.project_source_root())

gnome.post_install(update_desktop_database: true)
