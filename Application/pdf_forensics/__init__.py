"""
PDF Forensics Suite

A unified forensic analysis toolkit for PDF documents.
"""

__version__ = "1.1.1"
# Version policy: 1.0.0 is the first frozen release. Fixes are released as
# incremental updates (1.0.1, 1.0.2, ...); new features raise the minor
# version (1.1.0). Each release has its own build marker; a second build on
# the same date takes a letter (2026-10-22b). BUILD_DATE is carried by every output (CLI banner, report and graph
# footers, GUI About), so it identifies the build that produced it. For
# each update, change __version__ and BUILD_DATE together and add a dated
# CHANGELOG entry.
BUILD_DATE = "2026-10-22d"
__tool_name__ = "PDF Forensics Suite"
SCHEMA_REVISION = 10  # Increment when DB schema changes
