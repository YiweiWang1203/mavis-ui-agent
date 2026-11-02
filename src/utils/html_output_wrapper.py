"""Conservative output wrapper parsing. Never repairs document contents."""
import hashlib
import re
from html.parser import HTMLParser


class HtmlOutputError(ValueError):
    pass


def _require(value, code):
    if not value: raise HtmlOutputError(code)


def _validate_document(code):
    _require(re.match(r'(?is)\s*(?:<!doctype\s+html[^>]*>\s*)?<html(?:\s|>)', code) is not None,
             'HTML_DOCUMENT_START_REQUIRED')
    class Document(HTMLParser):
        def __init__(self): super().__init__(convert_charrefs=False); self.tags=[]
        def handle_starttag(self,tag,attrs):
            if tag in {'html','body'}: self.tags.append(('start',tag))
        def handle_endtag(self,tag):
            if tag in {'html','body'}: self.tags.append(('end',tag))
    parser=Document()
    try: parser.feed(code); parser.close()
    except Exception as exc: raise HtmlOutputError('HTML_DOCUMENT_PARSE_FAILED') from exc
    _require(parser.tags==[('start','html'),('start','body'),('end','body'),('end','html')],
             'HTML_DOCUMENT_INCOMPLETE_OR_MULTIPLE')
    _require(code.rstrip().lower().endswith('</html>'), 'HTML_DOCUMENT_TRAILING_CONTENT')


def parse_html_output(raw, *, finish_reason='stop'):
    """Return one original contiguous substring and auditable wrapper metadata.

    This is a document/wrapper gate, not full HTML validity, security or behavior QA.
    Character offsets use Python Unicode positions; byte offsets refer to UTF-8.
    """
    _require(finish_reason=='stop', 'HTML_OUTPUT_NON_STOP')
    _require(isinstance(raw,str) and bool(raw.strip()), 'HTML_OUTPUT_EMPTY')
    left=len(raw)-len(raw.lstrip()); right=len(raw.rstrip()); trimmed=raw[left:right]
    if re.match(r'(?is)(?:<!doctype\s+html[^>]*>\s*)?<html(?:\s|>)',trimmed):
        start,end=left,right; wrapper='plain_html'
    else:
        fences=[];offset=0
        for line in raw.splitlines(keepends=True):
            text=line.rstrip('\r\n')
            match=re.fullmatch(r' {0,3}(`{3,}|~{3,})([^\r\n]*)',text)
            if match: fences.append((offset,offset+len(line),match.group(1),match.group(2).strip()))
            offset+=len(line)
        _require(len(fences)==2, 'HTML_OUTPUT_AMBIGUOUS_OR_UNCLOSED_FENCES')
        opening,closing=fences
        _require(opening[3].lower()=='html', 'HTML_OUTPUT_EXPLICIT_HTML_FENCE_REQUIRED')
        _require(closing[2][0]==opening[2][0] and len(closing[2])>=len(opening[2]) and not closing[3],
                 'HTML_OUTPUT_INVALID_CLOSING_FENCE')
        outside=raw[:opening[0]]+raw[closing[1]:]
        _require(re.search(r'</?[A-Za-z][^>]*>',outside) is None and '```' not in outside and '~~~' not in outside,
                 'HTML_OUTPUT_OUTSIDE_CODE_OR_DOCUMENT')
        start,end=opening[1],closing[0];wrapper='single_html_fence'
    code=raw[start:end]
    _require(bool(code.strip()), 'HTML_OUTPUT_EMPTY')
    _validate_document(code)
    digest=lambda text:hashlib.sha256(text.encode('utf-8')).hexdigest()
    record={'version':'html-wrapper-v1','wrapper':wrapper,'character_range':[start,end],
        'utf8_byte_range':[len(raw[:start].encode('utf-8')),len(raw[:end].encode('utf-8'))],
        'raw_content_sha256':digest(raw),'selected_code_sha256':digest(code),
        'outside_character_ranges':[[0,start],[end,len(raw)]],
        'outside_sha256':[digest(raw[:start]),digest(raw[end:])],
        'content_mutations':'NONE; exact original contiguous substring',
        'unverified':'full HTML validity, safety, semantic intent, layout and browser behavior'}
    return {'code':code,'record':record}
