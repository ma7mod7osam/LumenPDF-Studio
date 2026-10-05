"""Amounts in words, worked out when the page is printed.

ERPNext writes In Words once, when the document is saved, in the language of whoever saved it,
and stores the sentence. A receipt saved from an English desk therefore says "SAR Fifty Five
Thousand only." on every print, whatever the format around it is written in. A Field block can
ask for the words in a chosen language instead, and they are rebuilt here from the amount itself.

Arabic is written by this module rather than by num2words: num2words separates the "wa" from
the next word ("خمسة و خمسون"), uses the construct form of two hundred where the free form
belongs ("مئتا"), and knows nothing of how the counted noun changes after a number, so every
amount from three to ten riyals came out as "ثلاثة ريال". Nothing here carries a diacritic.
"""
import frappe

# ---------------------------------------------------------------------------------- numbers
_ONES_M = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة"]
_ONES_F = ["", "واحدة", "اثنتان", "ثلاث", "أربع", "خمس", "ست", "سبع", "ثماني", "تسع", "عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة",
             "ثمانمائة", "تسعمائة"]
# (size, one, two, three to ten)
_SCALES = [(10 ** 12, "تريليون", "تريليونان", "تريليونات"),
           (10 ** 9, "مليار", "ملياران", "مليارات"),
           (10 ** 6, "مليون", "مليونان", "ملايين"),
           (10 ** 3, "ألف", "ألفان", "آلاف")]


def _below_100(n, fem):
    ones = _ONES_F if fem else _ONES_M
    if n <= 10:
        return ones[n]
    if n == 11:
        return "إحدى عشرة" if fem else "أحد عشر"
    if n == 12:
        return "اثنتا عشرة" if fem else "اثنا عشر"
    if n < 20:
        return ones[n - 10] + (" عشرة" if fem else " عشر")
    tens, unit = divmod(n, 10)
    return (ones[unit] + " و" + _TENS[tens]) if unit else _TENS[tens]


def _below_1000(n, fem=False, construct=False):
    """0 to 999. `construct` is the form before a noun it counts: two hundred thousand is
    "مائتا ألف", not "مائتان ألف"."""
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append("مائتا" if (hundreds == 2 and not rest and construct) else _HUNDREDS[hundreds])
    if rest:
        parts.append(_below_100(rest, fem))
    return " و".join(parts)


def number_ar(n, fem=False):
    """A whole number in Arabic words. `fem` agrees the last group with a feminine noun
    (هللة, بيسة): three halalas are "ثلاث هللات"."""
    n = int(n)
    if n == 0:
        return "صفر"
    parts = []
    for size, one, two, few in _SCALES:
        count, n = divmod(n, size)
        if not count:
            continue
        if count == 1:
            parts.append(one)
        elif count == 2:
            parts.append(two)
        elif 3 <= count <= 10:
            parts.append(_below_1000(count) + " " + few)
        else:
            parts.append(_below_1000(count, construct=True) + " " + (few if 3 <= count % 100 <= 10 else one))
    if n:
        parts.append(_below_1000(n, fem=fem))
    return " و".join(parts)


# ---------------------------------------------------------------------------------- currencies
# code: (one, two, three to ten, eleven to ninety-nine, feminine)
_UNITS = {
    "SAR": ("ريال سعودي", "ريالان سعوديان", "ريالات سعودية", "ريالا سعوديا", False),
    "AED": ("درهم إماراتي", "درهمان إماراتيان", "دراهم إماراتية", "درهما إماراتيا", False),
    "KWD": ("دينار كويتي", "ديناران كويتيان", "دنانير كويتية", "دينارا كويتيا", False),
    "BHD": ("دينار بحريني", "ديناران بحرينيان", "دنانير بحرينية", "دينارا بحرينيا", False),
    "OMR": ("ريال عماني", "ريالان عمانيان", "ريالات عمانية", "ريالا عمانيا", False),
    "QAR": ("ريال قطري", "ريالان قطريان", "ريالات قطرية", "ريالا قطريا", False),
    "JOD": ("دينار أردني", "ديناران أردنيان", "دنانير أردنية", "دينارا أردنيا", False),
    "EGP": ("جنيه مصري", "جنيهان مصريان", "جنيهات مصرية", "جنيها مصريا", False),
    "USD": ("دولار أمريكي", "دولاران أمريكيان", "دولارات أمريكية", "دولارا أمريكيا", False),
    "EUR": ("يورو", "يورو", "يورو", "يورو", False),
    "GBP": ("جنيه إسترليني", "جنيهان إسترلينيان", "جنيهات إسترلينية", "جنيها إسترلينيا", False),
}
_FRACTIONS = {
    "SAR": ("هللة", "هللتان", "هللات", "هللة", True),
    "AED": ("فلس", "فلسان", "فلوس", "فلسا", False),
    "KWD": ("فلس", "فلسان", "فلوس", "فلسا", False),
    "BHD": ("فلس", "فلسان", "فلوس", "فلسا", False),
    "OMR": ("بيسة", "بيستان", "بيسات", "بيسة", True),
    "QAR": ("درهم", "درهمان", "دراهم", "درهما", False),
    "JOD": ("فلس", "فلسان", "فلوس", "فلسا", False),
    "EGP": ("قرش", "قرشان", "قروش", "قرشا", False),
    "USD": ("سنت", "سنتان", "سنتات", "سنتا", False),
    "EUR": ("سنت", "سنتان", "سنتات", "سنتا", False),
    "GBP": ("بنس", "بنسان", "بنسات", "بنسا", False),
}


def _counted(n, forms):
    """The number and the noun it counts, in the order and form Arabic puts them."""
    one, two, few, many, fem = forms
    if n == 1:
        return one + (" واحدة" if fem else " واحد")
    if n == 2:
        return two
    r = n % 100
    noun = few if 3 <= r <= 10 else (many if 11 <= r <= 99 else one)
    return number_ar(n, fem=fem) + " " + noun


def _fraction_units(currency):
    try:
        units = frappe.db.get_value("Currency", currency, "fraction_units", cache=True)
    except Exception:
        units = None
    try:
        units = int(units or 0)
    except (TypeError, ValueError):
        units = 0
    if units > 0:
        return units
    return 1000 if currency in ("KWD", "BHD", "OMR", "JOD") else 100


def money_ar(amount, currency):
    """"فقط خمسة وخمسون ألف ريال سعودي لا غير"."""
    try:
        amount = abs(float(amount or 0))
    except (TypeError, ValueError):
        return ""
    currency = (currency or "").upper()
    units = _fraction_units(currency)
    whole, frac = divmod(int(round(amount * units)), units)
    main = _UNITS.get(currency) or (currency, currency, currency, currency, False)
    parts = []
    if whole or not frac:
        parts.append(_counted(whole, main) if whole else "صفر " + main[0])
    if frac:
        sub = _FRACTIONS.get(currency)
        parts.append(_counted(frac, sub) if sub else f"{frac}/{units}")
    return "فقط " + " و".join(parts) + " لا غير"


def money_en(amount, currency):
    """Frappe's own English wording, whatever language the desk is in right now."""
    from frappe.utils import money_in_words
    prev = getattr(frappe.local, "lang", None)
    try:
        frappe.local.lang = "en"
        return money_in_words(abs(float(amount or 0)), currency) or ""
    except Exception:
        return ""
    finally:
        frappe.local.lang = prev


def money(amount, currency, lang):
    return money_ar(amount, currency) if lang == "ar" else money_en(amount, currency)


# ---------------------------------------------------------------------------------- documents
def _company_currency(doc):
    cur = doc.get("company_currency")
    if not cur and doc.get("company"):
        try:
            cur = frappe.get_cached_value("Company", doc.company, "default_currency")
        except Exception:
            cur = None
    return cur


def _source(doc, field):
    """(amount field, currency) that a stored in-words field was written from, the way ERPNext
    writes it, or None when the field is not one of those."""
    base = field.startswith("base_")
    if field in ("in_words", "base_in_words"):
        if doc.doctype == "Payment Entry":
            pay = doc.get("payment_type") in ("Pay", "Internal Transfer")
            if base:
                return ("base_paid_amount" if pay else "base_received_amount"), _company_currency(doc)
            return (("paid_amount" if pay else "received_amount"),
                    doc.get("paid_from_account_currency" if pay else "paid_to_account_currency"))
        rounded = not doc.get("disable_rounded_total") and doc.get("base_rounded_total" if base else "rounded_total")
        return (("base_" if base else "") + ("rounded_total" if rounded else "grand_total"),
                _company_currency(doc) if base else doc.get("currency"))
    if field == "total_amount_in_words":  # Journal Entry
        return "total_amount", doc.get("total_amount_currency") or _company_currency(doc)
    return None


def doc_currency(doc):
    """The currency the document's money is in, chosen the way ERPNext chooses it for In Words:
    a Payment Entry by its payment type, a Journal Entry by its total, anything else by its
    own currency, and the company's when the document has none."""
    if doc.doctype == "Payment Entry":
        pay = doc.get("payment_type") in ("Pay", "Internal Transfer")
        cur = doc.get("paid_from_account_currency" if pay else "paid_to_account_currency")
    elif doc.doctype == "Journal Entry":
        cur = doc.get("total_amount_currency")
    else:
        cur = doc.get("currency")
    return cur or _company_currency(doc) or ""


# the short form an Arabic document writes after an amount
_AR_SHORT = {"SAR": "ر.س", "AED": "د.إ", "KWD": "د.ك", "BHD": "د.ب", "OMR": "ر.ع", "QAR": "ر.ق",
             "JOD": "د.أ", "EGP": "ج.م", "USD": "دولار", "EUR": "يورو", "GBP": "جنيه إسترليني"}


def currency_label(code, style="ar"):
    """A currency as a label: "ar" ر.س, "name" ريال سعودي, "code" SAR, "symbol" the symbol set on
    the Currency record. A currency without an Arabic form falls back to its symbol, then code."""
    code = (code or "").upper()
    if not code:
        return ""
    if style == "code":
        return code
    if style == "name" and code in _UNITS:
        return _UNITS[code][0]
    if style == "ar" and code in _AR_SHORT:
        return _AR_SHORT[code]
    try:
        sym = frappe.db.get_value("Currency", code, "symbol", cache=True)
    except Exception:
        sym = None
    return sym or code


# The Saudi riyal sign approved in February 2025, drawn from the Saudi Central Bank's own SVG
# (sama.gov.sa, Saudi_Riyal_Symbol-2.svg), paths unchanged. Few fonts carry U+20C1 yet, so it is
# printed as a vector. SAMA's rules: left of the number in Arabic and English alike, a space
# between, the height of the text, proportions kept, enough contrast. The size below keeps the
# official 1124.14 x 1256.39 proportion, and currentColor gives it the colour of its text.
SAR_SIGN_PATHS = (
    "M699.62,1113.02h0c-20.06,44.48-33.32,92.75-38.4,143.37l424.51-90.24c20.06-44.47,33.31-92.75,38.4-143.37l-424.51,90.24Z",
    "M1085.73,895.8c20.06-44.47,33.32-92.75,38.4-143.37l-330.68,70.33v-135.2l292.27-62.11c20.06-44.47,33.32-92.75,38.4-143.37l-330.68,70.27V66.13c-50.67,28.45-95.67,66.32-132.25,110.99v403.35l-132.25,28.11V0c-50.67,28.44-95.67,66.32-132.25,110.99v525.69l-295.91,62.88c-20.06,44.47-33.33,92.75-38.42,143.37l334.33-71.05v170.26l-358.3,76.14c-20.06,44.47-33.32,92.75-38.4,143.37l375.04-79.7c30.53-6.35,56.77-24.4,73.83-49.24l68.78-101.97v-.02c7.14-10.55,11.3-23.27,11.3-36.97v-149.98l132.25-28.11v270.4l424.53-90.28Z",
)


def sar_sign_svg():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1124.14 1256.39" role="img" '
            'aria-label="SAR" style="height:.75em;width:.671em;vertical-align:baseline;fill:currentColor">'
            + "".join(f'<path d="{d}"/>' for d in SAR_SIGN_PATHS) + "</svg>")


def sign_html(code):
    """The currency's sign as HTML: the official riyal sign for SAR, the Currency record's
    symbol for anything else."""
    code = (code or "").upper()
    if code == "SAR":
        return sar_sign_svg()
    return frappe.utils.escape_html(currency_label(code, "symbol"))


def field_currency(doc, field):
    try:
        df = frappe.get_meta(doc.doctype).get_field(field)
        from frappe.model.meta import get_field_currency
        return get_field_currency(df, doc) if df else None
    except Exception:
        return None


def _readable(doc, field):
    try:
        df = frappe.get_meta(doc.doctype).get_field(field)
    except Exception:
        return True
    return df is None or not (df.permlevel or 0)


def field_words(doc, field, lang):
    """The words for a Field block bound to `field` with words set to `lang` ("ar" or "en").
    Bound to an in-words field, the words are rebuilt from the amount it was written from.
    Bound to an amount, the words are that amount in its own currency. Anything else, or a
    field the reader may not see, gives None and the block prints what it would anyway."""
    if lang not in ("ar", "en") or not field or "." in field:
        return None
    src = _source(doc, field)
    if src:
        amount_field, currency = src
    else:
        try:
            df = frappe.get_meta(doc.doctype).get_field(field)
        except Exception:
            df = None
        if not df or df.fieldtype not in ("Currency", "Float", "Int"):
            return None
        amount_field, currency = field, None
        try:
            from frappe.model.meta import get_field_currency
            currency = get_field_currency(df, doc)
        except Exception:
            pass
        currency = currency or doc.get("currency") or _company_currency(doc)
    # the words give the amount away, so they follow the same rule as printing the amount
    if not (_readable(doc, field) and _readable(doc, amount_field)):
        return ""
    amount = doc.get(amount_field)
    if amount is None or not currency:
        return None
    return money(amount, currency, lang)


def currency_sample(doc):
    """The document's currency in every label style, for the builder's canvas."""
    code = doc_currency(doc)
    return {"code": code, "labels": {st: currency_label(code, st) for st in ("ar", "name", "code", "symbol")}}


def sign_sample(doc):
    """{field: currency code} for every Currency field, so the canvas draws the right sign."""
    out = {}
    try:
        fields = frappe.get_meta(doc.doctype).fields
    except Exception:
        return out
    for df in fields:
        if df.fieldtype == "Currency" and df.fieldname and not (df.permlevel or 0):
            out[df.fieldname] = field_currency(doc, df.fieldname) or ""
    return out


def amount_plain(doc, field):
    """A Currency field as the bare figure, in the number format of its currency, for a layout
    that prints the currency beside it. None when the field is not a currency amount."""
    try:
        df = frappe.get_meta(doc.doctype).get_field(field)
    except Exception:
        df = None
    if not df or df.fieldtype != "Currency" or (df.permlevel or 0):
        return None
    v = doc.get(field)
    if v is None:
        return None
    from frappe.utils import fmt_money
    cur, prec = None, None
    try:
        from frappe.model.meta import get_field_currency, get_field_precision
        cur = get_field_currency(df, doc)
        prec = get_field_precision(df, doc)
    except Exception:
        pass
    fmt = None
    if cur:
        try:
            fmt = frappe.db.get_value("Currency", cur, "number_format", cache=True)
        except Exception:
            fmt = None
    return fmt_money(v, precision=prec, format=fmt)


def sample(doc):
    """{field: {"ar": ..., "en": ...}} for the builder's canvas, so a Field block set to words
    shows the real sentence for the chosen sample document."""
    out = {}
    try:
        fields = frappe.get_meta(doc.doctype).fields
    except Exception:
        return out
    for df in fields:
        if not df.fieldname or (df.permlevel or 0):
            continue
        if df.fieldtype == "Currency" or _source(doc, df.fieldname):
            w = {lang: field_words(doc, df.fieldname, lang) for lang in ("ar", "en")}
            if any(w.values()):
                out[df.fieldname] = w
    return out
