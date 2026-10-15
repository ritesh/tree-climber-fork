# Taint corpus

Programs annotated with what the built-in rules (`builtin_rules(language)`) must and must not find; `test/taint/test_taint_corpus.py` checks them. Each file says what it covers in its header.

A comment on the line before a sink call:

- `ruleid: <rule>`: a finding of that rule is expected on the next line;
- `ok: <rule>`: no finding of that rule there;
- `todoruleid: <rule> -- <reason>`: a real flow the analysis misses (a strict xfail);
- `todook: <rule> -- <reason>`: a finding that is wrong (a strict xfail).

Every finding in a file must be annotated. `taint-options: field_sensitive implicit_flows` in a file's header turns those options on for it. When a fix makes a `todo` case pass, its xfail fails: change it to `ruleid` or `ok`.
