blueprints = custom_target('blueprints',
  input: files('adjust_size.blp', 'export.blp', 'window.blp'),
  output: ['adjust_size.ui', 'export.ui', 'window.ui'],
  command: [find_program('blueprint-compiler'), 'batch-compile', '@OUTDIR@', '@CURRENT_SOURCE_DIR@', '@INPUT@'],
)

gnome.compile_resources('glance', 'glance.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

install_data(
  files('__init__.py', 'adjust_size.py', 'canvas.py', 'document.py', 'estimate.py', 'export.py', 'imageio.py', 'main.py', 'markup.py', 'ops.py',
        'selection.py', 'shortcuts.py', 'sizing.py', 'window.py'),
  install_dir: pkgdatadir / 'glance',
)
