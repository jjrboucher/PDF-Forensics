# PyInstaller spec for the PDF Forensics Suite (one-folder build).
# Run from the Application folder:  pyinstaller build_exe/pdf_forensics.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

APP = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []
for pkg in ("pymupdf", "fitz", "pikepdf", "pyvis", "networkx", "openpyxl", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass  # package not installed: skip

# The application's own data files (icons, logo, branding.json)
datas += [
    (os.path.join(APP, "pdf_forensics", "assets"), os.path.join("pdf_forensics", "assets")),
    (os.path.join(APP, "pdf_forensics", "branding.json"), "pdf_forensics"),
]
# Licence and documentation shipped beside the executable
for f in ("LICENSE", "NOTICE", "README.md", "RELEASE_NOTES.md", "CHANGELOG.md"):
    datas.append((os.path.join(APP, f), "."))
datas.append((os.path.join(APP, "Documentation"), "Documentation"))

hiddenimports += ["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
                  "PIL.ImageTk", "psutil"]

a = Analysis(
    [os.path.join(APP, "pdf_forensics.py")],
    pathex=[APP],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=["matplotlib", "numpy.tests", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PDF_Forensics_Suite",
    console=True,   # keep a console so the command-line mode prints output; GUI opens when no arguments are given
    icon=os.path.join(APP, "pdf_forensics", "assets", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PDF_Forensics_Suite")
