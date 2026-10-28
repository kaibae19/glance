blueprints = custom_target('blueprints',
  input: files('window.blp'),
  output: ['window.ui'],
  command: [find_program('blueprint-compiler'), 'batch-compile', '@OUTDIR@', '@CURRENT_SOURCE_DIR@', '@INPUT@'],
)

gnome.compile_resources('glance', 'glance.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

install_data(
  files('__init__.py', 'canvas.py', 'document.py', 'imageio.py', 'main.py', 'ops.py',
        'shortcuts.py', 'window.py'),
  install_dir: pkgdatadir / 'glance',
)
