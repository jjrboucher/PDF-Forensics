"""Builds the whole window (launch_app) against stand-ins for tkinter and
PyMuPDF, so a mistake that only shows when the window is built (a name
that no longer exists, a wrong call) fails a test instead of the
application's start-up. Run by test_gui_build.py in its own process,
because it replaces modules. Nothing is shown and no case is opened."""
import sys, os, tempfile, traceback
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
class W(mock.MagicMock):
    def __init__(self, *a, **k):
        super().__init__()
    def __mro_entries__(self, bases): return (object,)
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080
    def winfo_width(self): return 1200
    def winfo_height(self): return 800
    def winfo_reqwidth(self): return 1200
    def winfo_reqheight(self): return 800
tk = mock.MagicMock(name="tkinter")
for n in ["Tk","Toplevel","Frame","Label","Text","Scrollbar","Canvas","Button","Listbox","Entry","Menu","Checkbutton","Radiobutton","PanedWindow","Spinbox","Scale","LabelFrame","Message"]:
    setattr(tk, n, type(n, (W,), {}))
for n in ["StringVar","BooleanVar","IntVar","DoubleVar"]:
    class V:
        def __init__(self, master=None, value=None, **k): self.v = value; self.cb=[]
        def get(self): return self.v
        def set(self, v):
            self.v = v
            for c in self.cb: c("", "", "write")
        def trace_add(self, mode, cb): self.cb.append(cb)
    setattr(tk, n, V)
tk.TclError = Exception
ttk = mock.MagicMock(name="ttk")
for n in ["Frame","Label","Button","Entry","Combobox","Checkbutton","Radiobutton","Scrollbar","Progressbar","Notebook","Separator","Treeview","Style","Spinbox","LabelFrame","Widget","Scale"]:
    setattr(ttk, n, type(n, (W,), {}))
tk.ttk = ttk
sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": mock.MagicMock(),
                    "tkinter.messagebox": mock.MagicMock(), "tkinter.font": mock.MagicMock(),
                    "tkinter.simpledialog": mock.MagicMock()})
_tmp = tempfile.mkdtemp()
for _v in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
    os.environ[_v] = _tmp
for m in ["pymupdf","fitz"]:
    sys.modules.setdefault(m, mock.MagicMock())
from pdf_forensics.gui import app
try:
    app.launch_app()
except Exception:
    traceback.print_exc()
    sys.exit(1)
print("WINDOW BUILT")
