"""
Documented approximations, as known false negatives (todoruleid) and false
positives (todook): aliasing, dynamic attribute access, branching on a
tainted value without `implicit_flows`, a function analysed once for all its
callers, and a sanitizer whose result is not used.
"""

import os
import shlex


def alias():
    first = []
    second = first
    second.append(input())
    # todoruleid: python-command-injection -- two names for one object are not tracked (no aliasing)
    os.system(first[0])


def dynamic():
    handler = getattr(os, "system")
    # todoruleid: python-command-injection -- calls through getattr are not resolved to their sink
    handler(input())


def branch_without_implicit_flows():
    if input() == "yes":
        command = "rm -rf /tmp/cache"
    else:
        command = "true"
    # todoruleid: python-command-injection -- branching on a tainted value is only followed with implicit_flows
    os.system(command)


def identity(value):
    return value


def tainted_caller():
    return identity(input())


def clean_caller():
    # todook: python-command-injection -- a function is analysed once for all callers: identity returns tainted data for one, so for every caller
    os.system(identity("true"))


def sanitizer_result_dropped():
    name = input()
    shlex.quote(name)
    # ruleid: python-command-injection
    os.system("ls " + name)
