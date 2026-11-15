"""In-browser editors and viewers for DocVault files.

Every edit_* function draws an editor for the file and returns the edited file as bytes,
or None when the user has not changed anything. The caller adds the commit message and saves
the bytes as a new version.
"""
import base64
import csv
import difflib
import io
import json
import os
import re

import streamlit as st
import streamlit.components.v1 as components

TEXT_EXT = {"txt", "md", "markdown", "json", "xml", "html", "htm", "css", "js", "ts", "jsx", "tsx", "py", "java",
            "c", "h", "cpp", "cs", "go", "rs", "php", "rb", "sh", "bat", "ps1", "sql", "yaml", "yml", "toml", "ini",
            "cfg", "conf", "env", "log", "svg", "tex", "r", "kt", "swift", "vue", "gitignore"}
CSV_EXT = {"csv", "tsv"}
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogv"}
AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
EDITABLE = {"text", "csv", "xlsx", "docx", "pptx", "image", "pdf"}
VIEWABLE = {"video", "audio"}
MAX_GRID_CELLS = 150_000
MAX_VIEW_MB = 60


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def kind_of(name: str) -> str:
    e = ext_of(name)
    if e in TEXT_EXT:
        return "text"
    if e in CSV_EXT:
        return "csv"
    if e in ("xlsx", "xlsm"):
        return "xlsx"
    if e == "docx":
        return "docx"
    if e == "pptx":
        return "pptx"
    if e in IMAGE_EXT:
        return "image"
    if e == "pdf":
        return "pdf"
    if e in VIDEO_EXT:
        return "video"
    if e in AUDIO_EXT:
        return "audio"
    return "other"


def can_edit(name: str) -> bool:
    return kind_of(name) in EDITABLE


def can_view(name: str) -> bool:
    return kind_of(name) in VIEWABLE


# ----------------------------------------------------------------------------- new blank files
NEW_TYPES = {"Document (.docx)": "docx", "Spreadsheet (.xlsx)": "xlsx", "Presentation (.pptx)": "pptx",
             "Text (.txt)": "txt", "Markdown (.md)": "md", "CSV table (.csv)": "csv"}


def blank_file(ext: str) -> bytes:
    if ext == "docx":
        import docx
        buf = io.BytesIO()
        d = docx.Document()
        d.add_paragraph("")
        d.save(buf)
        return buf.getvalue()
    if ext == "xlsx":
        import openpyxl
        buf = io.BytesIO()
        wb = openpyxl.Workbook()
        wb.active["A1"] = ""
        wb.save(buf)
        return buf.getvalue()
    if ext == "pptx":
        import pptx
        buf = io.BytesIO()
        p = pptx.Presentation()
        slide = p.slides.add_slide(p.slide_layouts[0])
        slide.shapes.title.text = "Title"
        p.save(buf)
        return buf.getvalue()
    if ext == "md":
        return b"# Untitled\n"
    if ext == "csv":
        return b"A,B,C\n"
    return b"\n"


# ----------------------------------------------------------------------------- text and code
ACE_LANG = {"py": "python", "js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript",
            "json": "json", "md": "markdown", "markdown": "markdown", "html": "html", "htm": "html", "css": "css",
            "xml": "xml", "svg": "xml", "yaml": "yaml", "yml": "yaml", "sql": "sql", "sh": "sh", "bat": "batchfile",
            "ps1": "powershell", "java": "java", "c": "c_cpp", "h": "c_cpp", "cpp": "c_cpp", "cs": "csharp",
            "go": "golang", "rs": "rust", "php": "php", "rb": "ruby", "toml": "toml", "ini": "ini", "kt": "kotlin",
            "swift": "swift", "tex": "latex", "r": "r", "vue": "html"}


def _code_box(base: str, ext: str, key: str) -> str:
    """A code editor with line numbers and colours (falls back to a plain box)."""
    try:
        if os.environ.get("DOCVAULT_PLAIN_EDITOR"):
            raise ImportError
        from streamlit_ace import st_ace
    except ImportError:
        return st.text_area("Content", value=base, height=520, key=key + "_text", label_visibility="collapsed")
    out = st_ace(value=base, language=ACE_LANG.get(ext, "text"), theme="chrome", height=520, font_size=14,
                 show_gutter=True, wrap=False, auto_update=True, key=key + "_ace")
    return base if out is None else out


def edit_text(data: bytes, name: str, key: str):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        st.error("This file is not UTF-8 text, so it cannot be edited here. Download it to edit it.")
        return None
    bom = text.startswith("\ufeff")
    if bom:
        text = text[1:]
    crlf = "\r\n" in text
    base = text.replace("\r\n", "\n")
    ext = ext_of(name)
    new = _code_box(base, ext, key)
    if ext == "json" and new.strip():
        try:
            json.loads(new)
        except ValueError as exc:
            st.warning("This is not valid JSON yet: %s" % exc)
    if ext in ("md", "markdown"):
        with st.expander("Preview"):
            st.markdown(new)
    elif ext in ("html", "htm"):
        with st.expander("Preview"):
            st.components.v1.html(new, height=420, scrolling=True)
    elif ext == "svg" and new.strip():
        with st.expander("Preview"):
            st.markdown("<div>%s</div>" % new, unsafe_allow_html=True)
    if new == base:
        return None
    out = new.replace("\n", "\r\n") if crlf else new
    return (("\ufeff" if bom else "") + out).encode("utf-8")


# ----------------------------------------------------------------------------- grids (csv, xlsx)
def col_label(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def grid_editor(rows, key: str):
    """rows: list of lists of strings. Returns (edited rows, changed?)."""
    import pandas as pd
    width = max([len(r) for r in rows] + [1])
    rows = [list(r) + [""] * (width - len(r)) for r in rows] or [[""] * width]
    df = pd.DataFrame(rows, columns=[col_label(i) for i in range(width)], dtype=str)
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=key, height=480)
    new_rows = [["" if v is None or (isinstance(v, float) and v != v) else str(v) for v in r]
                for r in edited.values.tolist()]
    return new_rows, new_rows != rows


def edit_csv(data: bytes, name: str, key: str):
    delim = "\t" if ext_of(name) == "tsv" else ","
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        st.error("This file is not UTF-8 text, so it cannot be edited here. Download it to edit it.")
        return None
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if sum(len(r) for r in rows) > MAX_GRID_CELLS:
        st.warning("This table is too large to edit in the browser. Download it to edit it.")
        return None
    new_rows, changed = grid_editor(rows, key + "_grid")
    if not changed:
        return None
    out = io.StringIO()
    csv.writer(out, delimiter=delim, lineterminator="\n").writerows(new_rows)
    return out.getvalue().encode("utf-8")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return str(v)


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _typed(new: str, old):
    """Turn the text typed in the grid back into a number when the cell held a number."""
    if new == "":
        return None
    if new.startswith("="):
        return new
    if isinstance(old, bool):
        return new.strip().upper() == "TRUE"
    if (old is None or isinstance(old, (int, float))) and _NUM.match(new.strip()):
        n = new.strip()
        return float(n) if "." in n else int(n)
    return new


def edit_xlsx(data: bytes, name: str, key: str):
    import openpyxl
    from openpyxl.cell.cell import MergedCell
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), keep_vba=ext_of(name) == "xlsm")
    except Exception:
        st.error("This spreadsheet could not be opened for editing. Download it to edit it.")
        return None
    st.caption("Edit cells like in a spreadsheet; add rows at the bottom of a sheet. Formulas start with = and "
               "are recalculated when the file is opened in Excel. Charts and pictures inside a spreadsheet "
               "are not kept when you save here.")
    sheets = wb.worksheets
    if not sheets:
        return None
    tabs = st.tabs([ws.title for ws in sheets]) if len(sheets) > 1 else [st.container()]
    changed_any = False
    for n, (ws, tab) in enumerate(zip(sheets, tabs)):
        with tab:
            if (ws.max_row or 1) * (ws.max_column or 1) > MAX_GRID_CELLS:
                st.warning("This sheet is too large to edit in the browser.")
                continue
            rows = [[_cell_text(c.value) for c in r] for r in ws.iter_rows(min_row=1, max_row=ws.max_row or 1,
                                                                            max_col=ws.max_column or 1)]
            new_rows, changed = grid_editor(rows, "%s_sheet%d" % (key, n))
            if not changed:
                continue
            changed_any = True
            for i, row in enumerate(new_rows):
                for j, text in enumerate(row):
                    old_cell = ws.cell(row=i + 1, column=j + 1)
                    if isinstance(old_cell, MergedCell):
                        continue
                    if text == _cell_text(old_cell.value):
                        continue
                    old_cell.value = _typed(text, old_cell.value)
            if len(new_rows) < (ws.max_row or 0):
                ws.delete_rows(len(new_rows) + 1, ws.max_row - len(new_rows))
    if not changed_any:
        return None
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- Word
def _set_par_text(p, text: str):
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r.text = ""
    else:
        try:
            p.add_run().text = text                # python-pptx
        except TypeError:
            p.add_run(text)                        # python-docx


def _insert_after(prev, text: str, style_name=None):
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph
    el = OxmlElement("w:p")
    prev._p.addnext(el)
    p = Paragraph(el, prev._parent)
    if style_name:
        try:
            p.style = style_name
        except KeyError:
            pass
    p.add_run(text)
    return p


def apply_paragraph_edits(doc, new_lines):
    """Make the document's body paragraphs read as new_lines, keeping the formatting of unchanged ones."""
    pars = list(doc.paragraphs)
    old = [p.text for p in pars]
    sm = difflib.SequenceMatcher(None, old, new_lines, autojunk=False)
    last = None                                   # the paragraph the next new one goes after
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            last = pars[i2 - 1]
            continue
        olds, news = pars[i1:i2], new_lines[j1:j2]
        for p, text in zip(olds, news):           # same positions: change the text, keep the style
            _set_par_text(p, text)
            last = p
        for p in olds[len(news):]:                # paragraphs that were deleted
            p._p.getparent().remove(p._p)
        for text in news[len(olds):]:             # paragraphs that were added
            if last is None:
                last = doc.paragraphs[0].insert_paragraph_before(text) if doc.paragraphs else doc.add_paragraph(text)
            else:
                last = _insert_after(last, text, last.style.name if last.style is not None else None)


_rte_component = None


def rich_text_box(html: str, key: str, height: int = 700):
    """A Word-like page with a formatting toolbar. Returns the edited HTML, or None until something changes."""
    global _rte_component
    if _rte_component is None:
        _rte_component = components.declare_component("docvault_rte", path=os.path.join(os.path.dirname(__file__), "rte"))
    return _rte_component(html=html, height=height, key=key, default=None)


def docx_to_html(data: bytes) -> str:
    import mammoth
    return mammoth.convert_to_html(io.BytesIO(data)).value


def html_to_docx(original: bytes, html: str) -> bytes:
    """Write the edited page into a copy of the original file, so its styles and page setup are kept."""
    import docx
    import tempfile
    from htmldocx import HtmlToDocx
    doc = docx.Document(io.BytesIO(original))
    body = doc.element.body
    for el in list(body):
        if not el.tag.endswith("}sectPr"):
            body.remove(el)
    with tempfile.TemporaryDirectory() as tmp:                 # the converter reads pictures from files
        count = [0]

        def to_file(m):
            count[0] += 1
            path = os.path.join(tmp, "img%d.%s" % (count[0], "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)))
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(m.group(2)))
            return 'src="%s"' % path.replace("\\", "/")

        html = re.sub(r'src="data:image/(\w+);base64,([^"]+)"', to_file, html)
        HtmlToDocx().add_html_to_document(html, doc)
        buf = io.BytesIO()
        doc.save(buf)
    return buf.getvalue()


def edit_docx(data: bytes, name: str, key: str):
    try:
        if os.environ.get("DOCVAULT_PLAIN_EDITOR"):
            raise ImportError
        import docx  # noqa: F401
        import htmldocx  # noqa: F401
        import mammoth  # noqa: F401
    except ImportError:
        return _edit_docx_text(data, name, key)
    try:
        html = docx_to_html(data)
    except Exception:
        st.error("This document could not be opened for editing. Download it to edit it.")
        return None
    st.caption("Some complex formatting (text boxes, columns, tracked changes, unusual fonts) may change when saved. "
               "The original stays in the history, so you can always roll back.")
    new_html = rich_text_box(html, key + "_rte")
    if new_html is None:
        return None
    try:
        return html_to_docx(data, new_html)
    except Exception as exc:
        st.error("Could not build the Word file from your edits (%s)." % exc)
        return None


def _edit_docx_text(data: bytes, name: str, key: str):
    import docx
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception:
        st.error("This document could not be opened for editing. Download it to edit it.")
        return None
    st.caption("One line is one paragraph. Press Enter to start a new paragraph. The formatting of paragraphs you "
               "do not touch (fonts, headings, pictures) is kept.")
    old = [p.text for p in doc.paragraphs]
    new_text = st.text_area("Document text", value="\n".join(old), height=520, key=key + "_doc",
                            label_visibility="collapsed")
    new_lines = new_text.split("\n")
    changed = new_lines != old
    table_edits = []
    if doc.tables:
        with st.expander("Tables (%d)" % len(doc.tables)):
            for t_i, table in enumerate(doc.tables):
                st.markdown("**Table %d**" % (t_i + 1))
                try:
                    rows = [[c.text for c in r.cells] for r in table.rows]
                except Exception:
                    st.caption("This table has merged cells and cannot be edited here.")
                    continue
                import pandas as pd
                width = max(len(r) for r in rows) if rows else 0
                if not width:
                    continue
                rows = [r + [""] * (width - len(r)) for r in rows]
                df = pd.DataFrame(rows, columns=[col_label(i) for i in range(width)], dtype=str)
                edited = st.data_editor(df, use_container_width=True, key="%s_tbl%d" % (key, t_i))
                new_rows = [["" if v is None else str(v) for v in r] for r in edited.values.tolist()]
                if new_rows != rows:
                    table_edits.append((t_i, rows, new_rows))
    if not changed and not table_edits:
        return None
    if changed:
        apply_paragraph_edits(doc, new_lines)
    for t_i, rows, new_rows in table_edits:
        table = doc.tables[t_i]
        for i, row in enumerate(new_rows):
            for j, text in enumerate(row):
                if text != rows[i][j]:
                    _set_par_text(table.rows[i].cells[j].paragraphs[0], text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PowerPoint
def _set_frame_text(tf, text: str):
    lines = text.split("\n")
    pars = list(tf.paragraphs)
    for i, line in enumerate(lines):
        p = pars[i] if i < len(pars) else tf.add_paragraph()
        _set_par_text(p, line)
    for p in pars[len(lines):]:
        p._p.getparent().remove(p._p)


def escape_html(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ALIGN_CSS = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFY": "justify"}


def _runs_html(p, slide_w: float) -> str:
    out = []
    for r in p.runs:
        css = []
        f = r.font
        try:
            if f.size:
                css.append("font-size:%.3fcqw" % (f.size * 100 / slide_w))
            if f.bold is not None:
                css.append("font-weight:%s" % ("700" if f.bold else "400"))
            if f.italic is not None:
                css.append("font-style:%s" % ("italic" if f.italic else "normal"))
            if f.underline is not None:
                css.append("text-decoration:%s" % ("underline" if f.underline else "none"))
            if f.color is not None and f.color.type is not None and str(f.color.type).startswith("RGB"):
                css.append("color:#%s" % f.color.rgb)
            if f.name:
                css.append("font-family:'%s'" % f.name.replace("'", "").replace('"', ""))
        except Exception:
            pass
        out.append('<span style="%s">%s</span>' % (";".join(css), escape_html(r.text)))
    return "".join(out)


def _text_html(tf, slide_w: float, override=None) -> str:
    if override is not None:
        return "".join("<div>%s</div>" % (escape_html(line) or "<br>") for line in override.split("\n"))
    parts = []
    for p in tf.paragraphs:
        inner = _runs_html(p, slide_w) if p.text else ""
        style = ""
        if p.alignment is not None:
            css = _ALIGN_CSS.get(str(p.alignment).split(".")[-1].split(" ")[0].upper())
            if css:
                style = ' style="text-align:%s"' % css
        parts.append("<div%s>%s</div>" % (style, inner or "<br>"))
    return "".join(parts)


def _slide_html(prs, slide, typed: dict, idx=None) -> str:
    """The slide as HTML: positions, text with its formatting, pictures and background colour.
    With idx set, every shape carries a data-key so the browser editor can edit, move and resize it in place."""
    bg = "#ffffff"
    try:
        if slide.background.fill.type == 1:
            bg = "#%s" % slide.background.fill.fore_color.rgb
    except Exception:
        pass
    sw_, sh_ = float(prs.slide_width), float(prs.slide_height)
    parts = []
    for sh in slide.shapes:
        try:
            if sh.left is None or sh.top is None or sh.width is None or sh.height is None:
                continue
            box = "left:%.3f%%;top:%.3f%%;width:%.3f%%;height:%.3f%%;" % (
                sh.left * 100 / sw_, sh.top * 100 / sh_, sh.width * 100 / sw_, sh.height * 100 / sh_)
            dk = " data-key='%d'" % sh.shape_id if idx is not None else ""
            if sh.shape_type == 13:                                   # a picture
                uri = "data:%s;base64,%s" % (sh.image.content_type, base64.b64encode(sh.image.blob).decode())
                parts.append("<div%s data-kind='pic' style='position:absolute;%s'><img src='%s' style='width:100%%;"
                             "height:100%%;object-fit:contain;pointer-events:none'></div>"
                             % (dk if idx is not None else "", box, uri))
            elif sh.has_text_frame:
                size, bold = 18, False
                for p in sh.text_frame.paragraphs:
                    if p.runs:
                        if p.runs[0].font.size:
                            size = p.runs[0].font.size.pt
                        bold = bool(p.runs[0].font.bold)
                        break
                if (sh.is_placeholder and size == 18 and sh.placeholder_format.type is not None
                        and "TITLE" in str(sh.placeholder_format.type)):
                    size, bold = 32, True
                cq = max(1.1, size * 12700 * 100 / sw_)               # text size as a share of the slide width
                body = _text_html(sh.text_frame, sw_, typed.get(sh.shape_id))
                parts.append("<div%s%s style='position:absolute;%s%sfont-size:%.2fcqw;line-height:1.2;color:#222;"
                             "font-weight:%s;font-family:Calibri,Arial,sans-serif'>%s</div>"
                             % (dk, " data-kind='text'" if idx is not None else "", box,
                                "" if idx is not None else "overflow:hidden;", cq, "700" if bold else "400", body))
        except Exception:
            continue
    return ("<div style='position:relative;width:100%%;aspect-ratio:%d/%d;container-type:inline-size;background:%s;"
            "border:1px solid #bbb;box-shadow:0 2px 8px rgba(0,0,0,.2);overflow:hidden'>%s</div>"
            % (prs.slide_width, prs.slide_height, bg, "".join(parts)))


def _blank_slide_html(prs) -> str:
    return ("<div style='position:relative;width:100%%;aspect-ratio:%d/%d;container-type:inline-size;background:#ffffff;"
            "border:1px solid #bbb;box-shadow:0 2px 8px rgba(0,0,0,.2);overflow:hidden'></div>"
            % (prs.slide_width, prs.slide_height))


_slides_component = None


def slides_box(slides: list, blank: str, slide_w_pt: float, key: str, height: int = 720):
    """Slides you click and type on directly, with a toolbar. Returns the new state of the deck, or None until you change something."""
    global _slides_component
    if _slides_component is None:
        _slides_component = components.declare_component("docvault_slides",
                                                         path=os.path.join(os.path.dirname(__file__), "slides"))
    return _slides_component(slides=slides, blank=blank, slide_w_pt=slide_w_pt, height=height, key=key, default=None)


# ---- writing the browser's edits back into the presentation
def _write_paragraphs(tf, paras: list):
    """Replace the text of a text frame with paras (runs with bold, italic, underline, size, colour, font).
    The properties of the original run are kept as the starting point, so theme colours and fonts survive."""
    import copy
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt
    aligns = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT, "justify": PP_ALIGN.JUSTIFY}
    pars = list(tf.paragraphs)
    paras = paras or [{"align": None, "runs": []}]
    for i, para in enumerate(paras):
        ref = pars[i] if i < len(pars) else (pars[-1] if pars else None)
        base_rpr = None
        if ref is not None and ref.runs and ref.runs[0]._r.rPr is not None:
            base_rpr = copy.deepcopy(ref.runs[0]._r.rPr)
        if i < len(pars):
            p = pars[i]
        else:
            p = tf.add_paragraph()
            if ref is not None and ref._p.pPr is not None and p._p.pPr is None:
                p._p.insert(0, copy.deepcopy(ref._p.pPr))
        for child in list(p._p):
            if child.tag.endswith("}r") or child.tag.endswith("}br") or child.tag.endswith("}fld"):
                p._p.remove(child)
        for run in para.get("runs", []):
            text = run.get("t") or ""
            if not text:
                continue
            r = p.add_run()
            r.text = text
            if base_rpr is not None:
                if r._r.rPr is not None:
                    r._r.remove(r._r.rPr)
                r._r.insert(0, copy.deepcopy(base_rpr))
            f = r.font
            if run.get("sz") is not None:
                f.size = Pt(float(run["sz"]))
            if run.get("b") is not None:
                f.bold = bool(run["b"])
            if run.get("i") is not None:
                f.italic = bool(run["i"])
            if run.get("u") is not None:
                f.underline = bool(run["u"])
            if run.get("c"):
                f.color.rgb = RGBColor.from_string(str(run["c"]).upper())
            if run.get("f"):
                f.name = str(run["f"])
        if para.get("align") in aligns:
            p.alignment = aligns[para["align"]]
    for p in pars[len(paras):]:
        p._p.getparent().remove(p._p)


def _clone_slide(prs, src):
    """A copy of a slide (shapes, pictures and background) added at the end of the deck."""
    import copy
    new = prs.slides.add_slide(src.slide_layout)
    for shp in list(new.shapes):
        shp._element.getparent().remove(shp._element)
    new_tree, src_tree = new.shapes._spTree, src.shapes._spTree
    for el in src_tree:
        if el.tag.endswith("}nvGrpSpPr") or el.tag.endswith("}grpSpPr"):
            continue
        el2 = copy.deepcopy(el)
        for blip in el2.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
            rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if rid:
                _part, new_rid = new.part.get_or_add_image_part(io.BytesIO(src.part.related_part(rid).blob))
                blip.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", new_rid)
        new_tree.append(el2)
    src_bg = src._element.cSld.find("{http://schemas.openxmlformats.org/presentationml/2006/main}bg")
    if src_bg is not None:
        new._element.cSld.insert(0, copy.deepcopy(src_bg))
    return new


def _blank_layout(prs):
    layouts = list(prs.slide_layouts)
    for lay in layouts:
        if lay.name and lay.name.lower() == "blank":
            return lay
    return min(layouts, key=lambda lay: len(lay.placeholders))


def apply_deck_state(prs, state: dict):
    """state comes from the browser: the final list of slides, each with its text edits, new geometry,
    deleted shapes and added text boxes."""
    sld_ids = prs.slides._sldIdLst
    originals = list(prs.slides)
    original_ids = list(sld_ids)
    final_ids = []
    sw, sh = prs.slide_width, prs.slide_height
    for entry in state["slides"]:
        src = entry.get("src")
        if src is not None and not 0 <= int(src) < len(originals):
            raise ValueError("unknown slide")
        if src is not None and not entry.get("copy"):
            slide, sld_id = originals[int(src)], original_ids[int(src)]
        else:
            slide = _clone_slide(prs, originals[int(src)]) if src is not None else prs.slides.add_slide(_blank_layout(prs))
            if src is None:
                for shp in list(slide.shapes):
                    shp._element.getparent().remove(shp._element)
            sld_id = sld_ids[-1]
        by_id = {str(s.shape_id): s for s in slide.shapes}
        for key in entry.get("deleted", []):
            shape = by_id.get(str(key))
            if shape is not None:
                shape._element.getparent().remove(shape._element)
        for key, geom in (entry.get("geom") or {}).items():
            shape = by_id.get(str(key))
            if shape is not None:
                l, t, w, h = (float(x) for x in geom)
                shape.left, shape.top = int(sw * l / 100), int(sh * t / 100)
                shape.width, shape.height = int(sw * w / 100), int(sh * h / 100)
        for key, paras in (entry.get("edits") or {}).items():
            shape = by_id.get(str(key))
            if shape is not None and shape.has_text_frame:
                _write_paragraphs(shape.text_frame, paras)
        for add in entry.get("adds", []):
            l, t, w, h = (float(x) for x in add["geom"])
            box = slide.shapes.add_textbox(int(sw * l / 100), int(sh * t / 100), int(sw * w / 100), int(sh * h / 100))
            box.text_frame.word_wrap = True
            _write_paragraphs(box.text_frame, add.get("paras") or [])
        final_ids.append(sld_id)
    for sld_id in original_ids:                                  # slides that were deleted
        if sld_id not in final_ids:
            prs.part.drop_rel(sld_id.rId)
    for sld_id in list(sld_ids):
        sld_ids.remove(sld_id)
    for sld_id in final_ids:
        sld_ids.append(sld_id)


def edit_pptx(data: bytes, name: str, key: str):
    import pptx
    if os.environ.get("DOCVAULT_PLAIN_EDITOR"):
        return _edit_pptx_text(data, name, key)
    try:
        prs = pptx.Presentation(io.BytesIO(data))
    except Exception:
        st.error("This presentation could not be opened for editing. Download it to edit it.")
        return None
    if not len(prs.slides):
        return None
    st.caption("Click any text on a slide and type. Use the toolbar for bold, italic, underline, size, colour and "
               "alignment (select some text first, or the whole box is changed). Drag the Move tab to move a "
               "box and the Resize tab to resize it. Add, copy, reorder and delete slides above the slide.")
    state = slides_box([{"html": _slide_html(prs, s, {}, idx=True), "src": i} for i, s in enumerate(prs.slides)],
                       _blank_slide_html(prs), prs.slide_width / 12700.0, key + "_slides")
    if not state:
        return None
    try:
        apply_deck_state(prs, state)
        buf = io.BytesIO()
        prs.save(buf)
        return buf.getvalue()
    except Exception as exc:
        st.error("Could not build the presentation from your edits (%s)." % exc)
        return None


def _edit_pptx_text(data: bytes, name: str, key: str):
    import pptx
    try:
        prs = pptx.Presentation(io.BytesIO(data))
    except Exception:
        st.error("This presentation could not be opened for editing. Download it to edit it.")
        return None
    st.caption("Slide by slide: the preview shows each slide as it looks and updates as you type. Text is editable; "
               "layout, pictures and design are kept as they are.")
    edits = []
    total = len(prs.slides)
    if not total:
        return None
    n = st.number_input("Slide", 1, total, 1, key=key + "_slide") if total > 1 else 1
    s_i = int(n) - 1
    slide = prs.slides[s_i]
    shapes = [sh for sh in slide.shapes if sh.has_text_frame]
    left, right = st.columns([3, 2])
    typed = {}
    with right:
        st.markdown("**Slide %d of %d**" % (s_i + 1, total))
        if not shapes:
            st.caption("No text on this slide.")
        for sh_i, sh in enumerate(shapes):
            old = "\n".join(p.text for p in sh.text_frame.paragraphs)
            # widgets of other slides are forgotten by Streamlit, so keep every edit in our own dictionary
            store = st.session_state.setdefault(key + "_pp", {})
            new = st.text_area(sh.name, value=store.get((s_i, sh.shape_id), old), key="%s_s%d_%d" % (key, s_i, sh_i))
            typed[sh.shape_id] = new
            if new != old:
                store[(s_i, sh.shape_id)] = new
            else:
                store.pop((s_i, sh.shape_id), None)
    with left:
        st.markdown(_slide_html(prs, slide, typed), unsafe_allow_html=True)
    for (o_i, shape_id), val in st.session_state.get(key + "_pp", {}).items():
        sh = next((x for x in prs.slides[o_i].shapes if x.shape_id == shape_id), None)
        if sh is not None:
            edits.append((sh, val))
    if not edits:
        return None
    for sh, new in edits:
        _set_frame_text(sh.text_frame, new)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- images
def edit_image(data: bytes, name: str, key: str):
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format or "PNG"
        animated = getattr(img, "is_animated", False)
        img.load()
    except Exception:
        st.error("This picture could not be opened.")
        return None
    if animated:
        st.info("Animated pictures can only be viewed here.")
        st.image(data)
        return None
    from PIL import ImageDraw, ImageEnhance, ImageFont
    t_basic, t_crop, t_note = st.tabs(["Adjust", "Crop", "Annotate"])
    with t_basic:
        c1, c2, c3, c4 = st.columns(4)
        rot = c1.selectbox("Rotate", [0, 90, 180, 270], format_func=lambda d: "None" if d == 0 else "%d\u00b0 left" % d,
                           key=key + "_rot")
        flip = c2.selectbox("Flip", ["None", "Horizontal", "Vertical"], key=key + "_flip")
        gray = c3.checkbox("Black and white", key=key + "_gray")
        pct = c4.slider("Size %", 10, 200, 100, key=key + "_pct")
        b1, b2 = st.columns(2)
        bright = b1.slider("Brightness", 0.2, 2.0, 1.0, 0.05, key=key + "_br")
        contrast = b2.slider("Contrast", 0.2, 2.0, 1.0, 0.05, key=key + "_ct")
    with t_crop:
        st.caption("Cut away this much from each side (percent).")
        k1, k2, k3, k4 = st.columns(4)
        cl = k1.slider("Left", 0, 90, 0, key=key + "_cl")
        ct_ = k2.slider("Top", 0, 90, 0, key=key + "_ctop")
        cr = k3.slider("Right", 0, 90, 0, key=key + "_cr")
        cb = k4.slider("Bottom", 0, 90, 0, key=key + "_cb")
    with t_note:
        a1, a2, a3 = st.columns([3, 1, 1])
        note = a1.text_input("Text to write on the picture", key=key + "_note")
        ncolor = a2.color_picker("Colour", "#e11d48", key=key + "_nc")
        nsize = a3.slider("Text size", 10, 200, 40, key=key + "_ns")
        p1, p2 = st.columns(2)
        nx = p1.slider("Across %", 0, 100, 10, key=key + "_nx")
        ny = p2.slider("Down %", 0, 100, 10, key=key + "_ny")
        box = st.checkbox("Draw a rectangle around the text", key=key + "_nb")
    out = img
    if rot:
        out = out.rotate(rot, expand=True)
    if flip == "Horizontal":
        out = ImageOps.mirror(out)
    elif flip == "Vertical":
        out = ImageOps.flip(out)
    if cl + cr >= 95 or ct_ + cb >= 95:
        st.warning("That crop leaves almost nothing of the picture.")
    elif cl or ct_ or cr or cb:
        w, h = out.size
        out = out.crop((w * cl // 100, h * ct_ // 100, w - w * cr // 100, h - h * cb // 100))
    if gray:
        out = ImageOps.grayscale(out)
    if bright != 1.0:
        out = ImageEnhance.Brightness(out).enhance(bright)
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if note.strip():
        if out.mode not in ("RGB", "RGBA"):
            out = out.convert("RGB")
        out = out.copy()
        draw = ImageDraw.Draw(out)
        try:
            font = ImageFont.truetype("arial.ttf", nsize)
        except OSError:
            try:
                font = ImageFont.load_default(size=nsize)
            except TypeError:
                font = ImageFont.load_default()
        pos = (out.width * nx // 100, out.height * ny // 100)
        if box:
            bb = draw.textbbox(pos, note, font=font)
            draw.rectangle((bb[0] - 8, bb[1] - 8, bb[2] + 8, bb[3] + 8), outline=ncolor, width=max(2, nsize // 12))
        draw.text(pos, note, fill=ncolor, font=font)
    if pct != 100:
        out = out.resize((max(1, out.width * pct // 100), max(1, out.height * pct // 100)))
    st.image(out)
    if out is img:
        return None
    if fmt.upper() == "JPEG" and out.mode not in ("RGB", "L"):
        out = out.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format=fmt, quality=95) if fmt.upper() == "JPEG" else out.save(buf, format=fmt)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PDF
def _apply_pdf_ops(data: bytes, ops: list):
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    for op in ops:
        pages = range(len(doc)) if op["page"] < 0 else [op["page"]]
        for pn in pages:
            page = doc[pn]
            r = page.rect
            if op["type"] == "highlight":
                for quad in page.search_for(op["text"], quads=True):
                    page.add_highlight_annot(quad)
            elif op["type"] == "comment":
                page.add_text_annot(fitz.Point(r.width * op["x"] / 100, r.height * op["y"] / 100), op["text"])
            elif op["type"] == "sign_text":
                page.insert_text(fitz.Point(r.width * op["x"] / 100, r.height * op["y"] / 100), op["text"],
                                 fontname="tiit", fontsize=op["size"], color=(0.05, 0.1, 0.5))
            elif op["type"] == "sign_image":
                x0, y0 = r.width * op["x"] / 100, r.height * op["y"] / 100
                w = r.width * op["w"] / 100
                page.insert_image(fitz.Rect(x0, y0, x0 + w, y0 + w * 0.4), stream=op["image"], keep_proportion=True)
    return doc


def edit_pdf(data: bytes, name: str, key: str):
    try:
        import fitz
        doc0 = fitz.open(stream=data, filetype="pdf")
    except Exception:
        st.warning("This PDF can only be viewed here.")
        view_file(data, name, key)
        return None
    total = len(doc0)
    ops_key = key + "_ops"
    ops = st.session_state.setdefault(ops_key, [])
    st.caption("Highlight text, add comments and sign. Your marks are added to a new copy of the PDF.")
    left, right = st.columns([3, 2])
    with right:
        page_no = int(st.number_input("Page", 1, total, 1, key=key + "_pg")) if total > 1 else 1
        t_hi, t_co, t_si = st.tabs(["Highlight", "Comment", "Sign"])
        with t_hi:
            phrase = st.text_input("Text to highlight", key=key + "_hl")
            where = st.radio("Where", ["This page", "Whole document"], horizontal=True, key=key + "_hlw")
            if st.button("Highlight it", key=key + "_hlb") and phrase.strip():
                ops.append({"type": "highlight", "page": page_no - 1 if where == "This page" else -1, "text": phrase.strip()})
                st.rerun()
        with t_co:
            ctext = st.text_area("Comment", key=key + "_ct", height=80)
            c1, c2 = st.columns(2)
            cx = c1.slider("Across %", 0, 100, 10, key=key + "_cx")
            cy = c2.slider("Down %", 0, 100, 10, key=key + "_cy")
            if st.button("Add comment", key=key + "_cb") and ctext.strip():
                ops.append({"type": "comment", "page": page_no - 1, "x": cx, "y": cy, "text": ctext.strip()})
                st.rerun()
        with t_si:
            mode = st.radio("Signature", ["Type my name", "Upload a picture"], horizontal=True, key=key + "_sm")
            sig_text = st.text_input("Name", key=key + "_st") if mode == "Type my name" else ""
            sig_img = st.file_uploader("Signature picture (png, jpg)", type=["png", "jpg", "jpeg"], key=key + "_si") \
                if mode == "Upload a picture" else None
            s1, s2 = st.columns(2)
            sx = s1.slider("Across %", 0, 100, 60, key=key + "_sx")
            sy = s2.slider("Down %", 0, 100, 85, key=key + "_sy")
            sw = st.slider("Size %", 5, 60, 25, key=key + "_sw")
            if st.button("Place signature", key=key + "_sb"):
                if mode == "Type my name" and sig_text.strip():
                    ops.append({"type": "sign_text", "page": page_no - 1, "x": sx, "y": sy, "text": sig_text.strip(),
                                "size": max(10, sw * 1.2)})
                    st.rerun()
                elif mode == "Upload a picture" and sig_img is not None:
                    ops.append({"type": "sign_image", "page": page_no - 1, "x": sx, "y": sy, "w": sw,
                                "image": sig_img.getvalue()})
                    st.rerun()
                else:
                    st.error("Type your name or upload a picture first.")
        if ops:
            st.markdown("**Your marks (%d)**" % len(ops))
            if st.button("Undo the last mark", key=key + "_undo"):
                ops.pop()
                st.rerun()
    doc = _apply_pdf_ops(data, ops) if ops else doc0
    with left:
        pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(1.4, 1.4))
        st.image(pix.tobytes("png"), caption="Page %d of %d" % (page_no, total))
    return doc.tobytes(garbage=3, deflate=True) if ops else None


# ----------------------------------------------------------------------------- viewers
def view_file(data: bytes, name: str, key: str):
    k = kind_of(name)
    if k == "video":
        st.video(data)
    elif k == "audio":
        st.audio(data)
    elif k == "pdf":
        if len(data) > MAX_VIEW_MB * 1024 * 1024:
            st.info("This PDF is too large to show here. Download it instead.")
            return
        b64 = base64.b64encode(data).decode()
        st.components.v1.html(
            "<iframe id='f' style='width:100%;height:760px;border:0'></iframe><script>"
            "const b=atob('%s');const a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);"
            "document.getElementById('f').src=URL.createObjectURL(new Blob([a],{type:'application/pdf'}));"
            "</script>" % b64, height=780)
    else:
        st.info("This file type cannot be shown here. Download it instead.")


EDITORS = {"text": edit_text, "csv": edit_csv, "xlsx": edit_xlsx, "docx": edit_docx, "pptx": edit_pptx,
           "image": edit_image, "pdf": edit_pdf}


def edit_file(data: bytes, name: str, key: str):
    return EDITORS[kind_of(name)](data, name, key)
