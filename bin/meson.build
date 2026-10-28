conf = configuration_data()
conf.set('PYTHON', py.full_path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)
conf.set('schemadir', get_option('prefix') / get_option('datadir') / 'glib-2.0' / 'schemas')

configure_file(
  input: 'glance.in',
  output: 'glance',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)
