"""Synthetic test PDFs, made with pikepdf. No real case data is used; all
names and values are invented."""
import io
import re

import pikepdf


def simple_pdf(pages=1, info=None, version=None, linearize=False):
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    if info:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as _:
            pass
        for k, v in info.items():
            pdf.docinfo[pikepdf.Name("/" + k)] = v
    b = io.BytesIO()
    kw = {"object_stream_mode": pikepdf.ObjectStreamMode.disable,
          "linearize": linearize}
    if version:
        kw["min_version"] = version
    pdf.save(b, **kw)
    return b.getvalue()


def append_info_update(data, info, marker=None):
    """Append an incremental update that replaces the document information
    dictionary. marker: text placed inside the update (e.g. ExifTool's
    '%EndExifToolUpdate N')."""
    pdf = pikepdf.open(io.BytesIO(data))
    size = int(pdf.trailer.Size)
    root = pdf.Root.objgen
    pdf.close()
    prev = int(re.findall(rb"startxref\s+(\d+)", data)[-1])
    body = "<< " + " ".join(f"/{k} ({v})" for k, v in info.items()) + " >>"
    upd = b"\n"
    obj_off = len(data) + len(upd)
    upd += f"{size} 0 obj\n{body}\nendobj\n".encode()
    if marker:
        upd += marker.encode() + b"\n"
    xref_off = len(data) + len(upd)
    upd += (f"xref\n{size} 1\n{obj_off:010d} 00000 n \ntrailer\n"
            f"<< /Size {size + 1} /Root {root[0]} {root[1]} R "
            f"/Info {size} 0 R /Prev {prev} >>\nstartxref\n{xref_off}\n"
            f"%%EOF\n").encode()
    return data + upd
