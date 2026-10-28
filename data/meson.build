desktop_file = install_data('io.github.kaibae19.Glance.desktop',
  install_dir: get_option('datadir') / 'applications')

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('desktop file', desktop_validate, args: [files('io.github.kaibae19.Glance.desktop')])
endif
