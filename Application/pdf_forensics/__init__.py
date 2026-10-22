"""
PDF Forensics Suite

A unified forensic analysis toolkit for PDF documents.
"""

__version__ = "1.0.3"
# Version policy: 1.0.0 is the first frozen release. Each later change is
# released as an incremental update (1.0.1, 1.0.2, ...) with its own build
# date. BUILD_DATE is carried by every output (CLI banner, report and graph
# footers, GUI About), so it identifies the build that produced it. For
# each update, change __version__ and BUILD_DATE together and add a dated
# CHANGELOG entry.
BUILD_DATE = "2026-10-22b"
__tool_name__ = "PDF Forensics Suite"
SCHEMA_REVISION = 9  # Increment when DB schema changes
