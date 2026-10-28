app_id = 'io.github.kaibae19.Glance'

install_data(app_id + '.desktop', install_dir: get_option('datadir') / 'applications')
install_data(app_id + '.metainfo.xml', install_dir: get_option('datadir') / 'metainfo')
install_data(app_id + '.gschema.xml', install_dir: get_option('datadir') / 'glib-2.0' / 'schemas')
install_subdir('icons/hicolor', install_dir: get_option('datadir') / 'icons')

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('desktop file', desktop_validate, args: [files(app_id + '.desktop')])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('metainfo', appstreamcli, args: ['validate', '--no-net', '--explain', files(app_id + '.metainfo.xml')])
endif

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test('gschema', compile_schemas, args: ['--strict', '--dry-run', meson.current_source_dir()])
endif
