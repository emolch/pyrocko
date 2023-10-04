# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line.
SPHINXOPTS    =
SPHINXBUILD   = python3 -m sphinx
SPHINXPROJ    = Pyrocko
SOURCEDIR     = source
BUILDDIR      = build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

html: Makefile squirrel_cli pyrocko_cli
	@$(SPHINXBUILD) -n "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS) $(O)

squirrel_cli:
	python3 ../maintenance/argparse_help_to_rst.py \
		pyrocko.squirrel.main \
		source/apps/squirrel/reference/

pyrocko_cli:
	python3 ../maintenance/argparse_help_to_rst.py \
		pyrocko.apps.pyrocko.main \
		source/apps/pyrocko/reference/

.PHONY: help Makefile squirrel_cli pyrocko_cli

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile squirrel_cli pyrocko_cli
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
