"""New Quiz items to a QTI 1.2 package in the Classic Quizzes layout."""
from __future__ import annotations

from pathlib import Path
import re
import zipfile

from painter.storage.atomic import atomic_write


# --------------------------------------------------------------------------
# Exporting a quiz's questions and answers
# --------------------------------------------------------------------------
# New Quizzes has no QTI export in the API (only the Build page's Exports
# tab), so the questions are read from the New Quiz Items API, saved as JSON
# exactly as returned, and converted here into a QTI 1.2 package in the
# Classic Quizzes layout that Canvas's "QTI .zip file" import accepts.
# Optionally a Common Cartridge course export of the quiz's assignment is
# also requested and kept only if it actually contains the quiz.
QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"


CC_NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"


CANVAS_META_NS = "http://canvas.instructure.com/xsd/cccv1p0"


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


QTI_REPORT_COLUMNS = ["Position", "Item ID", "Entry Type", "Question Type",
                      "Title", "Points", "In QTI", "Notes"]


class Unsupported(Exception):
    """An item that cannot be represented as a Classic Quizzes question."""


def strip_html(text) -> str:
    import html as _html
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return " ".join(_html.unescape(text).split())


def _num(value) -> str:
    """Numbers as QTI wants them: 10 -> '10.0', 0.25 -> '0.25'."""
    v = float(value)
    return f"{v:.1f}" if v == int(v) and abs(v) < 1e15 else format(v, ".15g")


def _el(parent, tag: str, text=None, **attrs):
    import xml.etree.ElementTree as ET
    attrs = {k.rstrip("_"): str(v) for k, v in attrs.items() if v is not None}
    node = ET.SubElement(parent, tag, attrs) if parent is not None else ET.Element(tag, attrs)
    if text is not None:
        node.text = str(text)
    return node


def _mattext(parent, content, html: bool = True):
    mat = _el(parent, "material")
    return _el(mat, "mattext", content or "",
               texttype="text/html" if html else "text/plain")


def _xml_bytes(root) -> bytes:
    import io
    import xml.etree.ElementTree as ET
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


class QtiItemWriter:
    """Builds one Classic-Quizzes-style QTI <item> for a New Quiz question."""

    def __init__(self, builder: "QtiBuilder", ident: str, title: str,
                 qtype: str, points):
        self.b = builder
        self.notes: list[str] = []
        self.item = _el(None, "item", ident=ident, title=title or "Question")
        meta = _el(_el(self.item, "itemmetadata"), "qtimetadata")
        self._meta = meta
        self._field("question_type", qtype)
        self._field("points_possible", _num(points or 0))
        self.answer_ids_field = self._field("original_answer_ids", "")
        self._field("assessment_question_identifierref", ident + "_aq")
        self.presentation = _el(self.item, "presentation")
        self.rp = None
        self.feedback: dict[str, str] = {}

    def _field(self, label: str, value: str):
        f = _el(self._meta, "qtimetadatafield")
        _el(f, "fieldlabel", label)
        return _el(f, "fieldentry", value)

    def set_answer_ids(self, ids) -> None:
        self.answer_ids_field.text = ",".join(str(i) for i in ids)

    def body(self, html: str) -> None:
        _mattext(self.presentation, html)
        if "<img" in (html or "").lower():
            self.notes.append("embedded image stays a link to Canvas; "
                              "not packaged in the zip")

    def resprocessing(self, general_fb: str | None = None):
        self.rp = _el(self.item, "resprocessing")
        _el(_el(self.rp, "outcomes"), "decvar", maxvalue="100", minvalue="0",
            varname="SCORE", vartype="Decimal")
        if general_fb:
            self._feedback_cond("general_fb", general_fb, other=True)
        return self.rp

    def _feedback_cond(self, ident: str, html: str, other: bool = False,
                       varequal: tuple[str, str] | None = None) -> None:
        cond = _el(self.rp, "respcondition", continue_="Yes")
        cv = _el(cond, "conditionvar")
        if other:
            _el(cv, "other")
        else:
            _el(cv, "varequal", varequal[1], respident=varequal[0])
        _el(cond, "displayfeedback", feedbacktype="Response", linkrefid=ident)
        self.feedback[ident] = html

    def score_cond(self, value, action: str = "Set", continue_: str | None = "No"):
        cond = _el(self.rp, "respcondition", continue_=continue_)
        cv = _el(cond, "conditionvar")
        _el(cond, "setvar", value if isinstance(value, str) else _num(value),
            action=action, varname="SCORE")
        return cond, cv

    def correct_feedback(self, cond, fb: dict) -> None:
        if fb.get("correct"):
            _el(cond, "displayfeedback", feedbacktype="Response", linkrefid="correct_fb")
            self.feedback["correct_fb"] = fb["correct"]

    def incorrect_feedback(self, fb: dict) -> None:
        if fb.get("incorrect"):
            self._feedback_cond("general_incorrect_fb", fb["incorrect"], other=True)

    def finish(self):
        for ident, html in self.feedback.items():
            fbe = _el(self.item, "itemfeedback", ident=ident)
            _mattext(_el(fbe, "flow_mat"), html)
        return self.item


class QtiBuilder:
    """Turns New Quiz items into a QTI 1.2 package (Classic Quizzes flavour)."""

    def __init__(self, quiz: dict, ident: str):
        self.quiz = quiz
        self.ident = ident
        self.items = []                  # <item> elements, in quiz order
        self.report: list[dict] = []
        self._next = 1000

    def new_id(self) -> int:
        self._next += 1
        return self._next

    # ---- ordering ----------------------------------------------------------
    @staticmethod
    def ordered(items: list[dict]) -> list[dict]:
        """Quiz order, with each stimulus's questions right after it."""
        def pos(i):
            try:
                return float(i.get("position") or 0)
            except (TypeError, ValueError):
                return 0.0
        by_stim: dict[str, list[dict]] = {}
        top = []
        ids = {str(i.get("id")) for i in items}
        for it in items:
            sid = it.get("stimulus_quiz_entry_id")
            if sid and str(sid) in ids:
                by_stim.setdefault(str(sid), []).append(it)
            else:
                top.append(it)
        out = []
        for it in sorted(top, key=pos):
            out.append(it)
            out += sorted(by_stim.get(str(it.get("id")), []), key=pos)
        return out

    # ---- items -----------------------------------------------------------------
    def add(self, quiz_item: dict) -> None:
        etype = quiz_item.get("entry_type") or ""
        entry = quiz_item.get("entry") or {}
        points = quiz_item.get("points_possible") or 0
        row = {"Position": quiz_item.get("position", ""),
               "Item ID": quiz_item.get("id", ""), "Entry Type": etype,
               "Question Type": "", "Title": "", "Points": points,
               "In QTI": "no", "Notes": ""}
        notes: list[str] = []
        try:
            if etype == "Bank":
                n = (quiz_item.get("properties") or {}).get("sample_num")
                row["Title"] = entry.get("title", "")
                raise Unsupported(
                    f"draws {n or 'all'} question(s) at random from item bank "
                    f"'{entry.get('title', '')}' ({entry.get('item_entry_count', '?')} "
                    "items); bank contents are not available through the API")
            if etype == "BankEntry":
                notes.append(f"single question from item bank {entry.get('bank_id', '?')}")
                etype = entry.get("entry_type") or "Item"
                entry = entry.get("entry") or {}
            row["Title"] = entry.get("title", "")
            if etype == "Stimulus":
                row["Question Type"] = "stimulus"
                w = self._stimulus(quiz_item, entry)
            elif etype == "Item":
                slug_ = entry.get("interaction_type_slug") or ""
                row["Question Type"] = slug_
                w = self._question(quiz_item, entry, slug_, points)
            else:
                raise Unsupported(f"unknown entry type {etype!r}")
            notes += w.notes
            self.items.append(w.finish())
            row["In QTI"] = "yes"
        except Unsupported as exc:
            notes.append(str(exc))
        row["Notes"] = "; ".join(notes)
        self.report.append(row)

    def _writer(self, quiz_item: dict, entry: dict, qtype: str, points) -> QtiItemWriter:
        ident = f"i{quiz_item.get('id', self.new_id())}"
        return QtiItemWriter(self, ident, entry.get("title") or "Question", qtype, points)

    def _stimulus(self, quiz_item: dict, entry: dict) -> QtiItemWriter:
        w = self._writer(quiz_item, entry, "text_only_question", 0)
        parts = []
        if entry.get("title"):
            parts.append(f"<h3>{_escape(entry['title'])}</h3>")
        parts.append(entry.get("body") or "")
        if entry.get("instructions"):
            parts.append(f"<p>{entry['instructions']}</p>")
        w.body("\n".join(parts))
        w.resprocessing()
        w.notes.append("stimulus exported as a text-only question; Classic "
                       "Quizzes cannot pin it beside its questions")
        return w

    def _question(self, quiz_item, entry, slug_, points) -> QtiItemWriter:
        handler = {
            "choice": self._choice, "true-false": self._true_false,
            "multi-answer": self._multi_answer, "essay": self._essay,
            "file-upload": self._file_upload, "numeric": self._numeric,
            "matching": self._matching, "rich-fill-blank": self._rich_fill_blank,
            "fill-blank": self._fill_blank,
        }.get(slug_)
        if handler is None:
            raise Unsupported(f"'{slug_}' questions have no Classic Quizzes "
                              "equivalent; kept in the JSON only")
        return handler(quiz_item, entry, points)

    # Each handler gets the QuizItem, its QuestionItem entry, and points.
    @staticmethod
    def _choice_body(c: dict) -> str:
        return c.get("item_body") or c.get("itemBody") or ""

    def _choice(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        choices = sorted(data.get("choices") or [], key=lambda c: c.get("position") or 0)
        correct = sd.get("value")
        ids = {c["id"]: self.new_id() for c in choices}
        if correct not in ids:
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "multiple_choice_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Single")
        rc = _el(lid, "render_choice")
        for c in choices:
            _mattext(_el(rc, "response_label", ident=ids[c["id"]]), self._choice_body(c))
        w.set_answer_ids(ids.values())
        w.resprocessing(fb.get("neutral"))
        for cid, html in (e.get("answer_feedback") or {}).items():
            if cid in ids and html:
                w._feedback_cond(f"{ids[cid]}_fb", html,
                                 varequal=("response1", str(ids[cid])))
        cond, cv = w.score_cond(100)
        _el(cv, "varequal", ids[correct], respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        if (e.get("properties") or {}).get("vary_points_by_answer") or sd.get("values"):
            w.notes.append("per-answer points dropped; only the correct answer scores")
        return w

    def _true_false(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        value = sd.get("value")
        if isinstance(value, str):
            value = value.strip().lower() == "true"
        t, f = self.new_id(), self.new_id()
        w = self._writer(qi, e, "true_false_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Single")
        rc = _el(lid, "render_choice")
        _mattext(_el(rc, "response_label", ident=t), data.get("true_choice") or "True", html=False)
        _mattext(_el(rc, "response_label", ident=f), data.get("false_choice") or "False", html=False)
        w.set_answer_ids([t, f])
        w.resprocessing(fb.get("neutral"))
        cond, cv = w.score_cond(100)
        _el(cv, "varequal", t if value else f, respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        return w

    def _multi_answer(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        choices = sorted(data.get("choices") or [], key=lambda c: c.get("position") or 0)
        ids = {c["id"]: self.new_id() for c in choices}
        correct = set(sd.get("value") or [])
        if not correct & set(ids):
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "multiple_answers_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Multiple")
        rc = _el(lid, "render_choice")
        for c in choices:
            _mattext(_el(rc, "response_label", ident=ids[c["id"]]), self._choice_body(c))
        w.set_answer_ids(ids.values())
        w.resprocessing(fb.get("neutral"))
        cond, cv = w.score_cond(100)
        both = _el(cv, "and")
        for cid, aid in ids.items():
            if cid in correct:
                _el(both, "varequal", aid, respident="response1")
            else:
                _el(_el(both, "not"), "varequal", aid, respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        if e.get("scoring_algorithm") == "AllOrNothing":
            w.notes.append("was all-or-nothing; Classic Quizzes gives partial credit")
        return w

    def _essay(self, qi, e, points):
        fb = e.get("feedback") or {}
        w = self._writer(qi, e, "essay_question", points)
        w.body(e.get("item_body"))
        rs = _el(w.presentation, "response_str", ident="response1", rcardinality="Single")
        _el(_el(rs, "render_fib"), "response_label", ident="answer1", rshuffle="No")
        w.resprocessing(fb.get("neutral"))
        notes = (e.get("scoring_data") or {}).get("value")
        if notes:
            w.notes.append("grading notes kept in the JSON only (Classic has no "
                           "private grading-notes field)")
        return w

    def _file_upload(self, qi, e, points):
        fb = e.get("feedback") or {}
        w = self._writer(qi, e, "file_upload_question", points)
        w.body(e.get("item_body"))
        w.resprocessing(fb.get("neutral"))
        props = e.get("properties") or {}
        if props.get("restrict_types") or (e.get("interaction_data") or {}).get("restrict_count"):
            w.notes.append("file type/count restrictions dropped")
        return w

    def _numeric(self, qi, e, points):
        import math
        fb = e.get("feedback") or {}
        answers = (e.get("scoring_data") or {}).get("value") or []
        if not answers:
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "numerical_question", points)
        w.body(e.get("item_body"))
        rs = _el(w.presentation, "response_str", ident="response1", rcardinality="Single")
        _el(_el(rs, "render_fib", fibtype="Decimal"), "response_label", ident="answer1")
        w.resprocessing(fb.get("neutral"))

        def exact(cv, value, lo, hi):
            either = _el(cv, "or")
            _el(either, "varequal", _num(value), respident="response1")
            both = _el(either, "and")
            _el(both, "vargte", _num(lo), respident="response1")
            _el(both, "varlte", _num(hi), respident="response1")

        written = 0
        for a in answers:
            kind = a.get("type")
            try:
                if kind == "exactResponse":
                    v = float(a["value"])
                    lo = hi = v
                elif kind == "marginOfError":
                    v, m = float(a["value"]), float(a.get("margin") or 0)
                    if a.get("margin_type") == "percent":
                        m = abs(v) * m / 100
                        w.notes.append("percent margin converted to an absolute margin")
                    lo, hi = v - m, v + m
                elif kind == "withinARange":
                    lo, hi = float(a["start"]), float(a["end"])
                    v = None
                elif kind == "preciseResponse":
                    v, p = float(a["value"]), int(a.get("precision") or 0)
                    if a.get("precision_type") == "significantDigits" and v:
                        step = 10 ** (math.floor(math.log10(abs(v))) - p + 1)
                    else:
                        step = 10 ** (-p)
                    lo, hi = v - step / 2, v + step / 2
                    w.notes.append("precision answer converted to a range")
                else:
                    w.notes.append(f"answer type {kind!r} skipped")
                    continue
            except (KeyError, TypeError, ValueError):
                w.notes.append(f"unreadable {kind} answer skipped")
                continue
            cond, cv = w.score_cond(100)
            if v is None:
                _el(cv, "vargte", _num(lo), respident="response1")
                _el(cv, "varlte", _num(hi), respident="response1")
            else:
                exact(cv, v, lo, hi)
            w.correct_feedback(cond, fb)
            written += 1
        if not written:
            raise Unsupported("no answer could be converted")
        w.incorrect_feedback(fb)
        return w

    def _matching(self, qi, e, points):
        fb = e.get("feedback") or {}
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        questions = data.get("questions") or []
        pairs = sd.get("value") or {}
        answers = list(dict.fromkeys(
            list(data.get("answers") or [])
            + list(((sd.get("edit_data") or {}).get("distractors")) or [])
            + [str(v) for v in pairs.values()]))
        if not questions or not pairs:
            raise Unsupported("no matches recorded")
        aid = {a: self.new_id() for a in answers}
        w = self._writer(qi, e, "matching_question", points)
        w.body(e.get("item_body"))
        qids = {}
        for q in questions:
            qids[q["id"]] = self.new_id()
            lid = _el(w.presentation, "response_lid", ident=f"response_{qids[q['id']]}")
            _mattext(lid, strip_html(q.get("item_body")), html=False)
            rc = _el(lid, "render_choice")
            for a in answers:
                _mattext(_el(rc, "response_label", ident=aid[a]), a, html=False)
        w.set_answer_ids(qids.values())
        w.resprocessing(fb.get("neutral"))
        share = 100 / len(questions)
        for q in questions:
            correct = pairs.get(q["id"])
            if correct is None:
                continue
            cond, cv = w.score_cond(share, action="Add", continue_=None)
            _el(cv, "varequal", aid[str(correct)], respident=f"response_{qids[q['id']]}")
        if e.get("scoring_algorithm") == "DeepEquals":
            w.notes.append("was all-or-nothing; Classic Quizzes gives partial credit")
        return w

    def _blanks(self, qi, e, points, body: str, blank_ids: list[str],
                blanks: dict, scoring: dict, bank_choices: list[dict]):
        """Shared by both fill-in-the-blank flavours. body already holds
        [blank1], [blank2]... in place of each blank."""
        types = {(blanks.get(b) or {}).get("answer_type", "openEntry") for b in blank_ids}
        dropdowns = types <= {"dropdown", "wordbank"}
        w = self._writer(qi, e, "multiple_dropdowns_question" if dropdowns
                         else "fill_in_multiple_blanks_question", points)
        if not dropdowns and types & {"dropdown", "wordbank"}:
            w.notes.append("mixes typed and drop-down blanks; drop-downs became "
                           "typed answers")
        w.body(body)
        w.resprocessing((e.get("feedback") or {}).get("neutral"))
        share = 100 / len(blank_ids)
        all_ids = []
        for n, bid in enumerate(blank_ids, start=1):
            b = blanks.get(bid) or {}
            s = scoring.get(bid) or {}
            sdata = s.get("scoring_data") or {}
            algo = s.get("scoring_algorithm") or ""
            kind = b.get("answer_type", "openEntry")
            options: list[str]
            correct: list[str]
            if kind == "dropdown":
                opts = sorted(b.get("choices") or [], key=lambda c: c.get("position") or 0)
                options = [c.get("item_body", "") for c in opts]
                hit = [c.get("item_body", "") for c in opts if c.get("id") == sdata.get("value")]
                correct = hit or [sdata.get("blank_text") or ""]
            elif kind == "wordbank":
                options = [c.get("item_body", "") for c in bank_choices]
                hit = [c.get("item_body", "") for c in bank_choices
                       if c.get("id") == sdata.get("choice_id")]
                correct = hit or [str(sdata.get("value") or sdata.get("blank_text") or "")]
            else:
                value = sdata.get("value")
                correct = [str(v) for v in value] if isinstance(value, list) else [str(value or "")]
                if algo == "TextRegex":
                    correct = [sdata.get("blank_text") or ""]
                    w.notes.append(f"blank {n}: regex answer replaced by its example answer")
                elif algo in ("TextCloseEnough", "TextContainsAnswer"):
                    w.notes.append(f"blank {n}: {algo} matching became exact match")
                options = correct
            if not dropdowns:
                options = correct           # typed blanks list only right answers
            correct = [c for c in correct if c]
            if not correct:
                raise Unsupported(f"blank {n} has no correct answer recorded")
            label_ids = {opt: self.new_id() for opt in dict.fromkeys(options + correct)}
            all_ids += label_ids.values()
            lid = _el(w.presentation, "response_lid", ident=f"response_blank{n}")
            _mattext(lid, f"blank{n}", html=False)
            rc = _el(lid, "render_choice")
            for opt, i in label_ids.items():
                _mattext(_el(rc, "response_label", ident=i), opt, html=False)
            for c in correct:
                cond, cv = w.score_cond(share, action="Add", continue_=None)
                _el(cv, "varequal", label_ids[c], respident=f"response_blank{n}")
        w.set_answer_ids(all_ids)
        return w

    def _rich_fill_blank(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        blanks = {b["id"]: b for b in data.get("blanks") or []}
        order = [b["id"] for b in data.get("blanks") or []]
        scoring = {s["id"]: s for s in sd.get("value") or [] if "id" in s}
        working = sd.get("working_item_body") or ""
        spans = re.findall(r"`([^`]*)`", working)
        if not order or len(spans) != len(order):
            raise Unsupported("could not locate the blanks in the question text")
        counter = iter(range(1, len(order) + 1))
        body = re.sub(r"`[^`]*`", lambda _m: f"[blank{next(counter)}]", working)
        w = self._blanks(qi, e, points, body, order, blanks, scoring,
                         data.get("word_bank_choices") or [])
        for n, (span, bid) in enumerate(zip(spans, order), start=1):
            text = ((scoring.get(bid) or {}).get("scoring_data") or {}).get("blank_text")
            if text is not None and strip_html(text) != strip_html(span):
                w.notes.append(f"blank {n}: text order did not match answer order; check it")
        return w

    def _fill_blank(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        blanks = {b["id"]: b for b in data.get("blanks") or []}
        scoring = {s["id"]: s for s in sd.get("value") or [] if "id" in s}
        parts, order = [], []
        for s in sorted(data.get("stem_items") or [], key=lambda s: s.get("position") or 0):
            if s.get("type") == "blank":
                order.append(s.get("blank_id"))
                parts.append(f"[blank{len(order)}]")
            else:
                parts.append(_escape(s.get("value") or ""))
        if not order:
            raise Unsupported("no blanks found")
        body = (data.get("prompt") or "") + f"<p>{''.join(parts)}</p>"
        return self._blanks(qi, e, points, body, order, blanks, scoring, [])

    # ---- package -----------------------------------------------------------
    def assessment_xml(self) -> bytes:
        root = _el(None, "questestinterop", xmlns=QTI_NS)
        root.set("xmlns:xsi", XSI_NS)
        root.set("xsi:schemaLocation",
                 f"{QTI_NS} http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.xsd")
        assessment = _el(root, "assessment", ident=self.ident,
                         title=self.quiz.get("title") or "Quiz")
        meta = _el(assessment, "qtimetadata")
        f = _el(meta, "qtimetadatafield")
        _el(f, "fieldlabel", "cc_maxattempts")
        _el(f, "fieldentry", self._allowed_attempts())
        section = _el(assessment, "section", ident="root_section")
        section.extend(self.items)
        return _xml_bytes(root)

    def _allowed_attempts(self) -> str:
        ma = (self.quiz.get("quiz_settings") or {}).get("multiple_attempts") or {}
        if not ma.get("multiple_attempts_enabled"):
            return "1"
        return str(ma.get("max_attempts") or 1) if ma.get("attempt_limit") else "-1"

    def meta_xml(self) -> bytes:
        q, s = self.quiz, self.quiz.get("quiz_settings") or {}
        ma = s.get("multiple_attempts") or {}
        root = _el(None, "quiz", identifier=self.ident, xmlns=CANVAS_META_NS)
        _el(root, "title", q.get("title") or "Quiz")
        _el(root, "description", q.get("instructions") or "")
        _el(root, "shuffle_answers", str(bool(s.get("shuffle_answers"))).lower())
        _el(root, "scoring_policy", {"latest": "keep_latest", "average": "keep_average"}
            .get(ma.get("score_to_keep"), "keep_highest"))
        _el(root, "quiz_type", "assignment")
        if q.get("points_possible") is not None:
            _el(root, "points_possible", _num(q["points_possible"]))
        _el(root, "allowed_attempts", self._allowed_attempts())
        if s.get("has_time_limit") and s.get("session_time_limit_in_seconds"):
            _el(root, "time_limit", max(1, int(s["session_time_limit_in_seconds"]) // 60))
        _el(root, "one_question_at_a_time",
            str(s.get("one_at_a_time_type") == "question").lower())
        _el(root, "cant_go_back", str(s.get("one_at_a_time_type") == "question"
                                      and not s.get("allow_backtracking")).lower())
        return _xml_bytes(root)

    def manifest_xml(self) -> bytes:
        root = _el(None, "manifest", identifier=f"{self.ident}_manifest", xmlns=CC_NS)
        md = _el(root, "metadata")
        _el(md, "schema", "IMS Content")
        _el(md, "schemaversion", "1.1.3")
        _el(root, "organizations")
        res = _el(root, "resources")
        main = _el(res, "resource", identifier=self.ident, type="imsqti_xmlv1p2")
        _el(main, "file", href=f"{self.ident}/{self.ident}.xml")
        _el(main, "dependency", identifierref=f"{self.ident}_meta")
        meta = _el(res, "resource", identifier=f"{self.ident}_meta",
                   type="associatedcontent/imscc_xmlv1p1/learning-application-resource",
                   href=f"{self.ident}/assessment_meta.xml")
        _el(meta, "file", href=f"{self.ident}/assessment_meta.xml")
        return _xml_bytes(root)

    def write_zip(self, path: Path) -> None:
        with atomic_write(path, "wb") as fh, \
                zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("imsmanifest.xml", self.manifest_xml())
            zf.writestr(f"{self.ident}/{self.ident}.xml", self.assessment_xml())
            zf.writestr(f"{self.ident}/assessment_meta.xml", self.meta_xml())


def _escape(text: str) -> str:
    import html as _html
    return _html.escape(text or "", quote=False)
