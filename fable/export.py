"""Export threads/sessions as Markdown or standalone HTML.

Shared transcripts are the organic distribution loop — every export
carries a "made with fable" footer.
"""
import html as html_mod
import json

from fable import db as fdb
from fable.db import connect
from fable.jsonl import read_span
from fable.threads import reconstruct

FOOTER_MD = "\n---\n*exported with [fable](https://github.com/grooverLab/fable) — full-fidelity memory for Claude Code*\n"
TOOL_RESULT_CAP = 4000


def _turn_md(turn, obj):
    out = [f"### {obj.get('type') or turn.type} · `{turn.uuid[:8]}` · {turn.ts or ''}\n"]
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        out.append(content + "\n")
        return out
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            out.append(block.get("text", "") + "\n")
        elif kind == "thinking" and block.get("thinking"):
            out.append("> *(thinking)* " +
                       block["thinking"].replace("\n", "\n> ") + "\n")
        elif kind == "tool_use":
            inp = block.get("input") if isinstance(block.get("input"), dict) else {}
            args = "\n".join(f"{k}: {v}" for k, v in inp.items()
                             if isinstance(v, str))
            out.append(f"**tool: {block.get('name', '?')}**\n```\n{args}\n```\n")
        elif kind == "tool_result":
            inner = block.get("content")
            texts = []
            if isinstance(inner, str):
                texts.append(inner)
            elif isinstance(inner, list):
                texts = [b.get("text", "") for b in inner
                         if isinstance(b, dict) and b.get("type") == "text"]
            body = "\n".join(texts)
            if len(body) > TOOL_RESULT_CAP:
                body = body[:TOOL_RESULT_CAP] + "\n… (truncated)"
            out.append(f"```\n{body}\n```\n")
        elif kind == "image":
            out.append("*[image]*\n")
    return out


def export_thread_md(db_path: str, prompt_id: str) -> str:
    conn = fdb.connect(db_path)
    try:
        view = reconstruct(conn, prompt_id)
        card = conn.execute(
            "SELECT title, type, outcome, summary FROM cards "
            "WHERE prompt_id = ?", (prompt_id,)).fetchone()
    finally:
        conn.close()
    if not view.main and not view.orphans:
        raise KeyError(f"thread not in index: {prompt_id}")
    lines = []
    if card:
        lines += [f"# {card[0]}", "",
                  f"*{card[1]} · {card[2] or ''}*", "",
                  card[3] or "", ""]
    else:
        lines += [f"# thread {prompt_id}", ""]
    for turn in view.main:
        obj = json.loads(read_span(turn.path, turn.offset, turn.length)
                         .decode("utf-8", "surrogateescape"))
        lines += _turn_md(turn, obj)
    return "\n".join(lines) + FOOTER_MD


HTML_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{title}</title><style>
body{{max-width:860px;margin:40px auto;padding:0 20px;background:#0b0d10;
color:#cdd6e4;font:15px/1.6 -apple-system,sans-serif}}
h1{{color:#ffb454}} h3{{color:#ffb454;border-top:1px solid #232a35;
padding-top:14px;font-size:13px;font-weight:600}}
pre{{background:#171b22;border:1px solid #232a35;border-radius:6px;
padding:12px;overflow:auto;font-size:12.5px;white-space:pre-wrap}}
blockquote{{color:#6b7689;border-left:3px solid #232a35;margin-left:0;
padding-left:14px}} code{{color:#6cc7d9}}
footer{{margin-top:40px;border-top:1px solid #232a35;padding-top:12px;
color:#6b7689;font-size:12px}} a{{color:#ffb454}}
</style></head><body>{body}
<footer>exported with <a href="https://github.com/grooverLab/fable">fable</a>
— full-fidelity memory for Claude Code</footer></body></html>"""


def export_thread_html(db_path: str, prompt_id: str) -> str:
    md = export_thread_md(db_path, prompt_id)
    md = md.split("\n---\n*exported with")[0]
    body, in_code = [], False
    title = "fable export"
    for line in md.splitlines():
        if line.startswith("```"):
            body.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html_mod.escape(line))
            continue
        esc = html_mod.escape(line)
        if line.startswith("# "):
            title = line[2:]
            body.append(f"<h1>{esc[2:]}</h1>")
        elif line.startswith("### "):
            body.append(f"<h3>{esc[4:]}</h3>")
        elif line.startswith("> "):
            body.append(f"<blockquote>{esc[5:]}</blockquote>")
        elif line.startswith("**tool:"):
            body.append(f"<p><code>{esc.replace('**', '')}</code></p>")
        else:
            body.append(f"<p>{esc}</p>" if line.strip() else "")
    return HTML_SHELL.format(title=html_mod.escape(title),
                             body="\n".join(body))


# There are many threads per session, we are making functions for full sessions, based on similar logic in export_thread_md
def get_threads_by_session(db_path: str, session_id: str): # session_id came from human input on CLI
    conn = fdb.connect(db_path)
    try:
        session = conn.execute(
            "SELECT session_id "
            "FROM sessions "
            "WHERE session_id = ?", (session_id,)).fetchone()

        if session is None:
            raise KeyError(f"Session {session_id} doesn't exist")

        # if we made it this far, that means the session_ID was verified in sessions table, but we dont know if there's any threads in threads table tied to this session_ID
        threads_data_rows = conn.execute(
            "SELECT prompt_id FROM threads "
            "WHERE session_id = ? "
            "ORDER BY first_ts", (session_id,)).fetchall()

    finally:
        conn.close() # need to close out the connection regardless of what is found in the above try

    relevant_threads = []

    for threads_data_row in threads_data_rows:
        relevant_threads.append(threads_data_row[0]) # only 1 value in the tuple

    '''
    SAMPLE OUTPUT, which might be an empty list:
    ['6bf46c69-7d2c-4f82-aeea-cbe226e87555', 'ae658f33-fe3b-490b-93f4-48b3a5aa3c81', '1df9fd78-9c65-4938-ab05-37e65affb229']
    
    can test on CLI with:
    python -c "from fable.export import get_threads_by_session; result = get_threads_by_session('demo/demo.db', '5790f82e-c1d3-4cff-aa3a-f4d46b0a18e8'); print(result)"
    '''

    return relevant_threads

# New function from: https://github.com/grooverLab/fable/issues/3
def export_session_html(db_path: str, session_id: str) -> str:
    # leverage helper function to retrieve a LIST of child threads related to session parent, knowing the list might be empty
    list_of_threads = get_threads_by_session(db_path, session_id)

    # HTML_SHELL is already premade with "title" and "body" tokens

    if len(list_of_threads) == 0:
        # We assume that the session_is is valid, but there are no threads tied to this valid session_id
        # Per explicit instructions, produce an html file explaining no sessions were found. Do NOT error out.
        empty_session_HTML = HTML_SHELL.format(
            title = f"fable export for session: {session_id}", # not consistent with original feature for single-threads only where title was "fable export"
            body = f"No threads in this session."
            )

        return empty_session_HTML

    table_of_contents_html = "<h2>Table of Contents</h2> \n"
    table_of_contents_html += "<ol> \n"

    all_threads_html = "<ol> \n"

    # insert a FOR LOOP that will jam in info for each thread
    for thread_id in list_of_threads:

        TOC_thread_entry_HTML = (f'<li><a href="#{thread_id}">{thread_id}</a></li> \n')
        table_of_contents_html += TOC_thread_entry_HTML

        body_thread_entry_HTML = ( f'<div id="{thread_id}">\n')

        #use pre-existing function to go from database pull -> MD markdown ->
        single_thread_md = export_thread_md(db_path, thread_id)
        single_thread_md = single_thread_md.split("\n---\n*exported with")[0] #doublecheck this one as it was produced by PyCharm's autocomplete

        in_code_block = False
        for md_line in single_thread_md.split("\n"):

            # CASE 1: opener or closer for codeblocks
            if md_line.startswith("```"): #we need to toggle mode because we can't know when the codeblocks end until we look at next line in the MD file
                if in_code_block: # ending a codeblock
                    body_thread_entry_HTML += "</pre>\n"
                    in_code_block = False
                    continue
                else: #starting a codeblock
                    body_thread_entry_HTML += "<pre>\n"
                    in_code_block = True
                    continue

            # we use escapes to have browser-safe renderings
            esc = html_mod.escape(md_line)

            # CASE 2: In the middle of code blocks
            if in_code_block:
                body_thread_entry_HTML += html_mod.escape(md_line)
                continue

            # CASE 3: Single-hashtag indicates thread title
            if md_line.startswith("# "):
                character_count = len("# ")
                body_thread_entry_HTML += f"<h1>{esc[character_count:]}</h1>\n"

            # CASE 4: Triple-hashtag indicates speaker (human user vs. Claude assistant)
            elif md_line.startswith("### "):
                character_count = len("### ")
                body_thread_entry_HTML += f"<h3>{esc[character_count:]}</h3>\n"

            # CASE 5: Double asterisk indicates use of a specific tool
            elif md_line.startswith("**tool:"):
                # <code> came from test.html
                body_thread_entry_HTML += f"<p><code>{esc.replace('**', '')}</code></p>\n" # do not assume ** only shows up once

            # CASE 6: > for thinking, which did NOT show up in demos but I was advised on
            elif md_line.startswith("> "):
                character_count = len("> ")
                body_thread_entry_HTML += f"<blockquote>{esc[character_count:]}</blockquote>\n"

            # CASE 7: Triple hyphens, we ignore everything past this because this is the footer giving Claude credit...no longer necessary as this was handled upstream

            # CASE 8: catchall for regular paragraph text (and empty lines)
            else:
                if len(md_line.strip()) == 0: # CASE 8A: blank lines
                    body_thread_entry_HTML += "\n"  # check this
                else: #CASE 8B: add everything else
                    body_thread_entry_HTML += f"<p>{esc}</p> \n" # check this

        # close out with </div>
        body_thread_entry_HTML += (f'</div>\n')

        all_threads_html += body_thread_entry_HTML

    #close out the ordered lists
    table_of_contents_html += "</ol> \n"
    all_threads_html += "</ol> \n"

    body_html = table_of_contents_html + all_threads_html

    full_session_HTML = HTML_SHELL.format(
        title = f"fable export for session: {session_id}",
        body = body_html
    )

    return full_session_HTML


def cmd_export(args) -> int:
    '''
    Test issue #3 in CLI with fable --db demo/demo.db export --session 5790f82e-c1d3-4cff-aa3a-f4d46b0a18e8 --format html -o session_test.html

    '''
    if getattr(args, "session", None):
        content = export_session_html(args.db, args.session)
        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            print(f"exported -> {args.output}")
        else:
            print(content)
        return 0
    '''
    ABOVE THIS is the additive code for the issue #3 on HTML exporting for full sessions
    '''

    fmt = args.format
    content = (export_thread_html(args.db, args.prompt_id) if fmt == "html"
               else export_thread_md(args.db, args.prompt_id))

    if getattr(args, "gist", False):
        import subprocess
        import tempfile
        suffix = ".html" if fmt == "html" else ".md"
        with tempfile.NamedTemporaryFile(
                "w", suffix=suffix, delete=False,
                prefix=f"fable-{args.prompt_id[:8]}-") as f:
            f.write(content)
            path = f.name
        proc = subprocess.run(["gh", "gist", "create", path],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"gh gist create failed: {proc.stderr[:200]}")
        print(proc.stdout.strip())  # the gist URL (secret by default)
        return 0
    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
        print(f"exported -> {args.output}")
    else:
        print(content)
    return 0


