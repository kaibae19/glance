project('glance', version: '1.0.0', meson_version: '>= 1.0.0', license: 'GPL-3.0-or-later')

gnome = import('gnome')
py = import('python').find_installation('python3')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

subdir('data')
subdir('src/glance')
subdir('bin')

if get_option('tests')
  test('unit', py, args: ['-m', 'pytest', '-q', meson.project_source_root() / 'tests'],
       workdir: meson.project_source_root())
endif

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
