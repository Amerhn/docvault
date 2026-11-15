"""Themes, the vault-wheel logo, and the CSS (colors, top bar, cards, animations) for the Streamlit interface."""
import math
from html import escape

THEMES = {
    "light":    dict(label="White",    dark=False, accent="#000000", accent2="#333333", on="#FFFFFF", bg="#FFFFFF", surface="#FFFFFF", text="#000000", muted="#595959", border="#D4D4D4"),
    "dark":     dict(label="Black",    dark=True,  accent="#FFFFFF", accent2="#CCCCCC", on="#000000", bg="#000000", surface="#111111", text="#FFFFFF", muted="#A6A6A6", border="#333333"),
    "paper":    dict(label="Paper",    dark=False, accent="#1A1A1A", accent2="#4D4D4D", on="#FFFFFF", bg="#F2F2F2", surface="#FFFFFF", text="#111111", muted="#666666", border="#D9D9D9"),
    "silver":   dict(label="Silver",   dark=False, accent="#262626", accent2="#595959", on="#FFFFFF", bg="#E3E3E3", surface="#F5F5F5", text="#0D0D0D", muted="#555555", border="#BDBDBD"),
    "graphite": dict(label="Graphite", dark=True,  accent="#F2F2F2", accent2="#BFBFBF", on="#161616", bg="#1C1C1C", surface="#262626", text="#F5F5F5", muted="#A8A8A8", border="#3D3D3D"),
    "sky":      dict(label="Sky",      dark=False, accent="#0B5FFF", accent2="#4C8DFF", on="#FFFFFF", bg="#F0F6FF", surface="#FFFFFF", text="#0B1B33", muted="#52627A", border="#CFE0F7"),
    "mint":     dict(label="Mint",     dark=False, accent="#0F8A5F", accent2="#34C38F", on="#FFFFFF", bg="#EFFAF4", surface="#FFFFFF", text="#0B2A1F", muted="#4F6B5E", border="#C9E8D9"),
    "violet":   dict(label="Violet",   dark=False, accent="#6D3FD6", accent2="#9B7BEA", on="#FFFFFF", bg="#F6F2FF", surface="#FFFFFF", text="#1E1236", muted="#625A78", border="#DDD2F5"),
    "amber":    dict(label="Amber",    dark=False, accent="#D9480F", accent2="#F59E0B", on="#FFFFFF", bg="#FFF6EC", surface="#FFFFFF", text="#33170B", muted="#7A5B4C", border="#F5D9C0"),
    "blush":    dict(label="Blush",    dark=False, accent="#D6336C", accent2="#F06595", on="#FFFFFF", bg="#FFF0F5", surface="#FFFFFF", text="#3A0F22", muted="#7C5566", border="#F7CADA"),
    "indigo":   dict(label="Indigo night", dark=True, accent="#8AA9FF", accent2="#B4C7FF", on="#0A1020", bg="#0B1220", surface="#131C33", text="#EAF0FF", muted="#9AA8C7", border="#26345A"),
    "aurora":   dict(label="Aurora",   dark=True,  accent="#2DD4BF", accent2="#5EEAD4", on="#04201C", bg="#061715", surface="#0D2623", text="#E6FFFB", muted="#8DB8B1", border="#1B4640"),
}
DEFAULT_THEME = "light"
FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600;700&display=swap');"
FONT_STACK = "'Google Sans','Google Sans Text','Product Sans','Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "rgba(%d,%d,%d,%s)" % (r, g, b, alpha)


def logo_svg(size: int = 34) -> str:
    """A vault wheel: a ring, a hub, and six spokes with handles."""
    spokes = ""
    for k in range(6):
        a = math.radians(60 * k)
        x2, y2 = 50 + 37 * math.cos(a), 50 + 37 * math.sin(a)
        kx, ky = 50 + 43 * math.cos(a), 50 + 43 * math.sin(a)
        spokes += ('<line x1="50" y1="50" x2="%.2f" y2="%.2f" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>'
                   '<circle cx="%.2f" cy="%.2f" r="5.5" fill="currentColor"/>' % (x2, y2, kx, ky))
    return ('<svg class="dv-wheel-svg" viewBox="0 0 100 100" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">'
            '<g class="dv-wheel">'
            '<circle cx="50" cy="50" r="28" fill="none" stroke="currentColor" stroke-width="7"/>'
            '<circle cx="50" cy="50" r="10" fill="currentColor"/>%s</g></svg>' % (size, size, spokes))


def logo_html(size: int = 34, text_px: int = 22) -> str:
    return ('<div class="dv-logo">%s<span class="dv-word" style="font-size:%dpx">DocVault</span></div>'
            % (logo_svg(size), text_px))


def brand_html() -> str:
    return ('<div class="dv-brand"><div class="dv-logo dv-logo-big">%s</div>'
            '<div class="dv-word dv-word-big">DocVault</div>'
            '<div class="dv-tag">Every version of your files, kept safe.</div></div>' % logo_svg(84))


def initials(name: str) -> str:
    parts = [p for p in escape(name or "?").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def css(theme_key: str, avatar_uri: str = None, name: str = "?") -> str:
    t = THEMES.get(theme_key, THEMES[DEFAULT_THEME])
    dark = t["dark"]
    if avatar_uri:
        avatar_bg = "background:url('%s') center/cover no-repeat !important;" % avatar_uri
        avatar_after = ""
    else:
        avatar_bg = "background:var(--dv-accent) !important;"
        avatar_after = ".st-key-avatar button::after{content:'%s';font-size:15px;font-weight:700;color:var(--dv-on);letter-spacing:.5px}" % initials(name)

    return """<style>
%(font_import)s
:root{--dv-on:%(on)s;--dv-accent:%(accent)s;--dv-accent2:%(accent2)s;--dv-soft:%(soft)s;--dv-bg:%(bg)s;--dv-surface:%(surface)s;
--dv-text:%(text)s;--dv-muted:%(muted)s;--dv-border:%(border)s;--dv-shadow:%(shadow)s}
@keyframes dv-fade-up{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes dv-pop{0%%{opacity:0;transform:scale(.96) translateY(6px)}100%%{opacity:1;transform:none}}
@keyframes dv-spin{from{transform:rotate(-240deg) scale(.7);opacity:0}to{transform:rotate(0) scale(1);opacity:1}}
@keyframes dv-float{0%%,100%%{transform:translateY(0)}50%%{transform:translateY(-5px)}}
@keyframes dv-shimmer{0%%{background-position:0%% 50%%}100%%{background-position:200%% 50%%}}

html{font-size:18px !important}
.stApp{background:var(--dv-bg) !important;color:var(--dv-text) !important}
html,body,.stApp,.stApp p,.stApp li,.stApp label,.stApp a,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp button,.stApp input,.stApp textarea,
.stApp [data-baseweb="select"] div,.stApp [data-baseweb="tab"],.stApp [data-testid="stMarkdownContainer"],.stApp [data-testid="stCaptionContainer"],
[data-baseweb="popover"] li,[data-testid="stPopoverBody"] *:not([data-testid="stIconMaterial"]){font-family:%(font)s !important}
.stApp p,.stApp li,.stApp label,.stApp input,.stApp textarea{font-size:1.06rem}
.stApp [data-testid="stCaptionContainer"] *{font-size:.95rem !important}
.dv-ico,.stButton button p,[data-testid="stPopoverBody"] p{filter:grayscale(1)}
header[data-testid="stHeader"],#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none !important}
.block-container{max-width:1120px !important;padding:0 1.2rem 3rem !important}
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp p,.stApp li,.stApp label,.stApp span,.stApp div[data-testid="stMarkdownContainer"],
.stApp [data-testid="stWidgetLabel"] p,.stApp [data-testid="stCaptionContainer"]{color:var(--dv-text)}
.stApp .dv-muted,.stApp [data-testid="stCaptionContainer"] *{color:var(--dv-muted) !important}

/* ---------- logo and brand ---------- */
.dv-logo{display:flex;align-items:center;gap:10px;color:var(--dv-accent);cursor:default}
.dv-wheel{transform-box:view-box;transform-origin:50%% 50%%;animation:dv-spin 1.1s cubic-bezier(.2,.9,.25,1) both;transition:transform .7s cubic-bezier(.2,.9,.25,1)}
.dv-logo:hover .dv-wheel{animation:dv-dial 1.5s cubic-bezier(.45,.05,.25,1) both}
.dv-logo:hover .dv-word{letter-spacing:.9px;transition:letter-spacing .4s ease}
@keyframes dv-dial{0%%{transform:rotate(0)}30%%{transform:rotate(160deg)}48%%{transform:rotate(-80deg)}66%%{transform:rotate(45deg)}82%%{transform:rotate(-12deg)}100%%{transform:rotate(0)}}
.dv-word{font-weight:800;letter-spacing:.2px;color:var(--dv-text) !important}
.dv-brand{text-align:center;margin:2.2rem 0 1.2rem;animation:dv-fade-up .6s ease both}
.dv-logo-big{justify-content:center;animation:dv-float 4.5s ease-in-out infinite}
.dv-word-big{font-size:2.5rem;line-height:1.1;margin-top:.3rem}
.dv-tag{color:var(--dv-muted);margin-top:.35rem;font-size:1rem}

/* ---------- top bar ---------- */
.st-key-topbar{position:sticky;top:0;z-index:50;background:var(--dv-surface);border:1px solid var(--dv-border);border-radius:0 0 18px 18px;
padding:.45rem 1rem;margin-bottom:1.4rem;box-shadow:var(--dv-shadow);animation:dv-fade-up .45s ease both}
.st-key-topbar [data-testid="stHorizontalBlock"]{align-items:center !important}
.st-key-topbar [data-testid="stMarkdownContainer"]{margin:0 !important}
.st-key-topbar [data-testid="stElementContainer"],.st-key-topbar [data-testid="stVerticalBlock"]{margin:0 !important;gap:0 !important}
.st-key-topbar .dv-logo{margin:0 !important;min-height:44px;align-items:center}
[class*="st-key-navoff_"] button,[class*="st-key-navon_"] button{background:transparent !important;border:none !important;box-shadow:none !important;
position:relative;padding:.65rem .5rem !important;border-radius:10px !important;transition:color .2s,background .2s !important;min-height:0 !important;\nwhite-space:nowrap !important;display:flex !important;align-items:center !important;justify-content:center !important;line-height:1.2 !important}
[class*="st-key-navoff_"] button p,[class*="st-key-navon_"] button p{font-weight:650;font-size:1rem;white-space:nowrap !important;word-break:keep-all !important;overflow-wrap:normal !important;margin:0 !important;line-height:1.2 !important}\n[class*="st-key-navoff_"],[class*="st-key-navon_"]{min-width:max-content}
[class*="st-key-navoff_"] button p{color:var(--dv-muted) !important}
[class*="st-key-navon_"] button p{color:var(--dv-accent) !important}
[class*="st-key-navoff_"] button:hover{background:var(--dv-soft) !important}
[class*="st-key-navoff_"] button:hover p{color:var(--dv-accent) !important}
[class*="st-key-navoff_"] button::after,[class*="st-key-navon_"] button::after{content:'';position:absolute;left:50%%;bottom:-.5rem;height:3px;width:0;
background:var(--dv-accent);border-radius:3px;transform:translateX(-50%%);transition:width .3s ease}
[class*="st-key-navon_"] button::after{width:76%%}
[class*="st-key-navoff_"] button:hover::after{width:38%%}

/* avatar button */
.st-key-avatar{display:flex;justify-content:flex-end}
.st-key-avatar button{width:44px !important;height:44px !important;min-height:44px !important;padding:0 !important;border-radius:50%% !important;
border:2px solid var(--dv-accent) !important;%(avatar_bg)s overflow:hidden;font-size:0 !important;color:transparent !important;
transition:transform .25s,box-shadow .25s !important;position:relative}
.st-key-avatar button p,.st-key-avatar button svg,.st-key-avatar button span{font-size:0 !important;color:transparent !important;display:none !important}
.st-key-avatar button:hover{transform:scale(1.08);box-shadow:0 0 0 4px var(--dv-soft)}
%(avatar_after)s
[data-testid="stPopoverBody"] p,[data-testid="stPopoverBody"] strong,[data-testid="stPopoverBody"] span,[data-testid="stPopoverBody"] a,[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] *{color:var(--dv-text) !important;opacity:1 !important;text-decoration:none !important}
[data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],[data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] *,[data-testid="stPopoverBody"] small{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;opacity:1 !important}
[data-testid="InputInstructions"],.stApp [data-testid="InputInstructions"],[data-testid="stTextInputRootElement"] [data-testid*="nstruction"],[data-testid="stTextInput"] [class*="nstructions"],[data-testid="stTextInput"] [class*="InputInstructions"],[data-testid="stForm"] [data-testid*="nstruction"]{display:none !important;visibility:hidden !important}
[data-testid="stPopoverBody"]{min-width:230px;background:var(--dv-surface) !important;border:1px solid var(--dv-border) !important;
border-radius:14px !important;animation:dv-pop .22s ease both}

/* ---------- pages, cards ---------- */
[class*="st-key-page_"]{animation:dv-fade-up .5s ease both}
.dv-h{font-weight:800;font-size:1.9rem;margin:.2rem 0 .1rem}
[class*="st-key-card"]{background:var(--dv-surface);border:1px solid var(--dv-border);border-radius:16px;padding:1rem 1.2rem;margin-bottom:.8rem;
box-shadow:var(--dv-shadow);transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease;animation:dv-pop .4s ease both}
[class*="st-key-card"]:hover{transform:translateY(-3px);border-color:var(--dv-accent);box-shadow:0 10px 26px %(hover)s}
.st-key-card_auth{max-width:440px;margin:0 auto;padding:1.5rem 1.6rem}
.dv-file{display:flex;align-items:center;gap:14px}
.dv-ico{font-size:1.7rem;width:46px;height:46px;border-radius:12px;background:var(--dv-soft);display:flex;align-items:center;justify-content:center}
.stApp .dv-badge{display:inline-block;padding:.12rem .6rem;border-radius:999px;font-size:.78rem;font-weight:700;background:var(--dv-soft);
color:var(--dv-accent) !important;margin-left:.4rem}
.stApp .dv-badge-now{background:var(--dv-accent);color:var(--dv-on) !important}
.dv-or{text-align:center;color:var(--dv-muted);margin:.5rem 0;font-size:.9rem}
.dv-avatar-lg{width:112px;height:112px;border-radius:50%%;display:flex;align-items:center;justify-content:center;color:var(--dv-on) !important;
font-size:2.4rem;font-weight:800;background:var(--dv-accent);box-shadow:0 8px 22px %(hover)s;animation:dv-pop .5s ease both}
.st-key-avatar_big img{border-radius:50%% !important;box-shadow:0 8px 22px %(hover)s}

/* ---------- buttons, inputs ---------- */
.stButton button,.stDownloadButton button,.stLinkButton a,[data-testid="stFormSubmitButton"] button{border-radius:11px !important;
transition:transform .18s,box-shadow .18s,background .2s,border-color .2s !important;font-weight:600}
.stButton button:hover,.stDownloadButton button:hover,.stLinkButton a:hover{transform:translateY(-2px);box-shadow:0 6px 16px %(hover)s}
.stButton button:active{transform:translateY(0) scale(.98)}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{background:var(--dv-accent) !important;
border:none !important;color:var(--dv-on) !important}
[data-testid="stBaseButton-primary"] p,[data-testid="stBaseButton-primaryFormSubmit"] p,[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] p,.stApp [data-testid="stBaseButton-primaryFormSubmit"] p,.stApp [data-testid="stBaseButton-primaryFormSubmit"] *{color:var(--dv-on) !important;-webkit-text-fill-color:var(--dv-on) !important;opacity:1 !important;visibility:visible !important}
[data-testid="stBaseButton-secondaryFormSubmit"] p{color:var(--dv-text) !important}
[data-testid="stBaseButton-secondary"]{background:var(--dv-surface) !important;border:1px solid var(--dv-border) !important}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--dv-accent) !important}
[data-testid="stBaseButton-secondary"] p{color:var(--dv-text) !important}
[class*="st-key-linkrow"] button{background:transparent !important;border:none !important;box-shadow:none !important;padding:0 !important;min-height:0 !important}
[class*="st-key-linkrow"] button p{color:var(--dv-accent) !important;font-size:.92rem;font-weight:600}
[class*="st-key-linkrow"] button:hover{transform:none;box-shadow:none}
[class*="st-key-linkrow"] button:hover p{text-decoration:underline}
.st-key-linkrow_forgot{display:flex;justify-content:flex-end;margin:-.3rem 0 .4rem}
.stTextInput input,.stTextArea textarea,.stNumberInput input{background:var(--dv-surface) !important;color:var(--dv-text) !important;
border:1px solid var(--dv-border) !important;border-radius:11px !important;transition:border-color .2s,box-shadow .2s}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:var(--dv-accent) !important;box-shadow:0 0 0 3px var(--dv-soft) !important}
[data-baseweb="select"]>div,[data-baseweb="input"]{background:var(--dv-surface) !important;border-color:var(--dv-border) !important;border-radius:11px !important}
[data-baseweb="select"] *{color:var(--dv-text) !important}
[data-baseweb="popover"] [role="listbox"],[data-baseweb="menu"]{background:var(--dv-surface) !important}
[data-baseweb="popover"] li{color:var(--dv-text) !important}
/* read-only fields (email, username) stay readable */
.stApp input:disabled,.stApp textarea:disabled,.stApp [data-baseweb="input"] input[disabled],.stApp [data-baseweb="base-input"] input[disabled]{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;opacity:1 !important;cursor:not-allowed}
.stApp [data-baseweb="input"][aria-disabled="true"],.stApp [data-baseweb="base-input"][aria-disabled="true"],.stApp [data-baseweb="input"]:has(input:disabled){background:var(--dv-surface) !important;opacity:1 !important}
/* tab underline follows the theme */
.stApp [data-baseweb="tab-highlight"]{background:var(--dv-accent) !important;background-color:var(--dv-accent) !important}
.stApp [data-baseweb="tab-border"]{background:var(--dv-border) !important;background-color:var(--dv-border) !important}
.stApp [data-baseweb="tab"] p,.stApp [data-baseweb="tab"] span{color:var(--dv-muted) !important}
.stApp [data-baseweb="tab"][aria-selected="true"] p,.stApp [data-baseweb="tab"][aria-selected="true"] span{color:var(--dv-accent) !important}
.stApp [data-baseweb="tab"]:hover p{color:var(--dv-accent) !important}
/* uploaded file chip: readable name and size in every theme */
[data-testid="stFileUploaderFile"],[data-testid="stFileChip"],[data-testid="stFileUploaderFile"]>div{background:var(--dv-soft) !important;border:1px solid var(--dv-border) !important;border-radius:12px !important}
[data-testid="stFileUploaderFile"] *:not(svg):not(path),[data-testid="stFileChip"] *:not(svg):not(path),[data-testid="stFileUploaderFileName"],[data-testid="stFileChipName"]{color:var(--dv-text) !important;opacity:1 !important;-webkit-text-fill-color:var(--dv-text) !important}
[data-testid="stFileUploaderFile"] small,[data-testid="stFileChip"] small,[data-testid="stFileUploaderFile"] [data-testid="stCaptionContainer"] *{color:var(--dv-muted) !important;-webkit-text-fill-color:var(--dv-muted) !important}
[data-testid="stFileUploaderFile"] svg,[data-testid="stFileChip"] svg,[data-testid="stFileUploaderDeleteBtn"] svg{fill:var(--dv-text) !important;color:var(--dv-text) !important}
/* input borders follow the theme (no red), also when invalid or focused */
.stApp [data-baseweb="textarea"],.stApp [data-baseweb="input"],.stApp [data-baseweb="base-input"],.stApp .stTextArea textarea,.stApp .stTextInput input{border-color:var(--dv-border) !important;outline:none !important;box-shadow:none !important}
.stApp [data-baseweb="textarea"]:focus-within,.stApp [data-baseweb="input"]:focus-within,.stApp [data-baseweb="base-input"]:focus-within,.stApp .stTextArea textarea:focus,.stApp .stTextInput input:focus{border-color:var(--dv-accent) !important;box-shadow:0 0 0 3px var(--dv-soft) !important}
.stApp [aria-invalid="true"],.stApp [data-baseweb][aria-invalid="true"]{border-color:var(--dv-border) !important;box-shadow:none !important}
.stApp .stTextArea textarea::placeholder,.stApp .stTextInput input::placeholder{color:var(--dv-muted) !important;opacity:.85 !important}
[data-testid="stFileUploaderDropzone"]{background:var(--dv-surface) !important;border:2px dashed var(--dv-border) !important;border-radius:16px !important;
transition:border-color .25s,background .25s,transform .25s}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--dv-accent) !important;background:var(--dv-soft) !important;transform:scale(1.005)}
[data-testid="stFileUploaderDropzone"] *{color:var(--dv-text) !important}
[data-testid="stExpander"]{background:var(--dv-surface);border:1px solid var(--dv-border) !important;border-radius:14px !important}
[data-testid="stExpander"] summary:hover{color:var(--dv-accent)}
button[data-baseweb="tab"]{transition:color .2s,background .2s}
button[data-baseweb="tab"][aria-selected="true"] p{color:var(--dv-accent) !important}
[data-baseweb="tab-highlight"]{background:var(--dv-accent) !important;height:3px !important;border-radius:3px}
[data-testid="stForm"]{border:none !important;padding:0 !important}
/* message boxes (info, success, warning, error): Streamlit paints an inner layer, so colour every layer */
[data-testid="stAlert"],[data-testid="stAlertContainer"],[data-testid="stAlert"] [data-baseweb="notification"],[data-testid="stAlert"]>div,
[data-testid="stNotification"],[data-testid="stNotificationContent"]{background:var(--dv-surface) !important;background-color:var(--dv-surface) !important;
border-radius:12px !important;box-shadow:none !important}
[data-testid="stAlert"]{animation:dv-pop .3s ease both;border:1px solid var(--dv-border) !important}
[data-testid="stAlert"] *,[data-testid="stAlertContainer"] *,[data-testid="stNotification"] *{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important}
[data-testid="stAlert"] svg,[data-testid="stAlertContainer"] svg{fill:var(--dv-accent) !important;color:var(--dv-accent) !important}
/* code blocks (for example the team invite link) and inline code */
[data-testid="stCode"],[data-testid="stCodeBlock"],.stCodeBlock{background:var(--dv-surface) !important;background-color:var(--dv-surface) !important;
border:1px solid var(--dv-border) !important;border-radius:10px !important}
[data-testid="stCode"] pre,[data-testid="stCode"] code,[data-testid="stCodeBlock"] pre,[data-testid="stCodeBlock"] code,.stCodeBlock pre{
background:transparent !important;background-color:transparent !important;border-radius:10px !important}
[data-testid="stCode"] *,[data-testid="stCodeBlock"] *,.stCodeBlock *{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;
background-color:transparent !important}
[data-testid="stCode"] button,[data-testid="stCodeBlock"] button,[data-testid="stCodeCopyButton"]{background:var(--dv-surface) !important;border:1px solid var(--dv-border) !important;opacity:1 !important}
[data-testid="stCode"] button svg,[data-testid="stCodeBlock"] button svg,[data-testid="stCodeCopyButton"] svg{fill:var(--dv-text) !important;color:var(--dv-text) !important}
.stApp :not(pre)>code{background:var(--dv-soft) !important;color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;padding:.1rem .4rem;border-radius:6px}
/* pop-up notices */
[data-testid="stToast"],[data-testid="stToastContainer"]>div,[data-testid="stToastContainer"] [data-baseweb="toast"]{background:var(--dv-surface) !important;
border:1px solid var(--dv-border) !important;border-radius:12px !important}
[data-testid="stToast"] *,[data-testid="stToastContainer"] *{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important}
/* number boxes, sliders, checkboxes, radio buttons */
[data-testid="stNumberInput"] button{background:var(--dv-surface) !important;border:1px solid var(--dv-border) !important}
[data-testid="stNumberInput"] button svg,[data-testid="stNumberInput"] button *{fill:var(--dv-text) !important;color:var(--dv-text) !important}
[data-testid="stNumberInput"] [data-baseweb="input"],[data-testid="stNumberInput"] [data-baseweb="base-input"]{background:var(--dv-surface) !important}
[data-testid="stSlider"] [role="slider"]{background:var(--dv-accent) !important;border-color:var(--dv-accent) !important;box-shadow:none !important}
[data-testid="stSlider"] [data-testid="stSliderThumbValue"]{color:var(--dv-accent) !important;background:transparent !important}
[data-testid="stSlider"] [data-testid="stTickBarMin"],[data-testid="stSlider"] [data-testid="stTickBarMax"]{color:var(--dv-muted) !important}
[data-baseweb="checkbox"] span,[data-baseweb="radio"] span,[data-baseweb="radio"] div,[data-testid="stCheckbox"] label,[data-testid="stRadio"] label{color:var(--dv-text) !important}
[data-baseweb="checkbox"] input:checked+div,[data-baseweb="radio"] input:checked+div{background:var(--dv-accent) !important;border-color:var(--dv-accent) !important}
[data-baseweb="radio"]>div:first-child,[data-baseweb="checkbox"]>div:first-child{border-color:var(--dv-border)}
/* drop-down lists (newer Streamlit builds them from react-aria parts instead of baseweb) */
[data-testid="stSelectbox"] [class*="react-aria-ComboBox"]>div,[data-testid="stMultiSelect"] [class*="react-aria-ComboBox"]>div,
[data-testid="stSelectbox"] [class*="react-aria"][class*="Group"]{background:var(--dv-surface) !important;background-color:var(--dv-surface) !important;
border:1px solid var(--dv-border) !important;border-radius:11px !important}
[data-testid="stSelectbox"] input,[data-testid="stMultiSelect"] input{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;background:transparent !important}
[data-testid="stSelectbox"] button svg,[data-testid="stMultiSelect"] button svg{fill:var(--dv-text) !important;color:var(--dv-text) !important}
[class*="react-aria-Popover"],[class*="react-aria-ListBox"],[class*="react-aria-Popover"]>div{background:var(--dv-surface) !important;background-color:var(--dv-surface) !important;
border:1px solid var(--dv-border) !important;border-radius:12px !important;color:var(--dv-text) !important}
[class*="react-aria-ListBoxItem"],[class*="react-aria-ListBoxItem"] *,[role="option"],[role="option"] *{color:var(--dv-text) !important;-webkit-text-fill-color:var(--dv-text) !important;background-color:transparent}
[class*="react-aria-ListBoxItem"][data-focused="true"],[class*="react-aria-ListBoxItem"][data-hovered="true"],[class*="react-aria-ListBoxItem"][data-selected="true"],
[role="option"]:hover,[role="option"][aria-selected="true"]{background-color:var(--dv-soft) !important}
/* tabs in newer Streamlit are plain role="tab" elements */
.stApp [role="tablist"]{border-color:var(--dv-border) !important}
.stApp [role="tab"]{color:var(--dv-muted) !important;border-bottom-color:transparent !important;background:transparent !important}
.stApp [role="tab"] *{color:inherit !important}
.stApp [role="tab"][aria-selected="true"]{color:var(--dv-accent) !important;border-bottom-color:var(--dv-accent) !important}
.stApp [role="tab"]:hover{color:var(--dv-accent) !important}
.stApp [class*="react-aria-SelectionIndicator"]{background:var(--dv-accent) !important;background-color:var(--dv-accent) !important}
/* colour picker and small widgets */
[data-testid="stColorPicker"] *{color:var(--dv-text) !important}
[data-testid="stColorPicker"] [data-baseweb="input"]{background:var(--dv-surface) !important}
/* tables made with st.dataframe / data_editor take Streamlit's own theme, so give their frame a visible edge */
[data-testid="stDataFrame"],[data-testid="stDataFrameResizable"]{border:1px solid var(--dv-border) !important;border-radius:10px !important;overflow:hidden}

</style>""" % dict(
        accent=t["accent"], accent2=t["accent2"], soft=_rgba(t["accent"], 0.13 if not dark else 0.2), bg=t["bg"], surface=t["surface"],
        text=t["text"], muted=t["muted"], border=t["border"], hover=_rgba(t["accent"], 0.22 if not dark else 0.28),
        shadow=("0 2px 10px rgba(255,255,255,.06)" if dark else "0 2px 12px rgba(0,0,0,.08)"),
        avatar_bg=avatar_bg, avatar_after=avatar_after, on=t["on"], font=FONT_STACK, font_import=FONT_IMPORT)
