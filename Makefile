# observability: trends across our services, derived from their call logs.

# The suite runs against src/ and bin/, with nothing installed.
FUNCTIONAL_ENV = PYTHONPATH=$(CURDIR)/src OBSERVABILITY_BIN_DIR=$(CURDIR)/bin
EDITABLE =
include pubkit-python.mk

check: sync-check functional ## Everything CI runs
