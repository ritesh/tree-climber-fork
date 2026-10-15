"""
Flows through containers, with the default settings: a write into a
subscript or attribute taints the whole value (weak update, the earlier
taint is kept), reads of any element are tainted, and values put in by a
method call are lost. field_sensitive.py runs the same shapes with
`field_sensitive`.
"""

import os


def subscript_write():
    options = {}
    options["user"] = input()
    # ruleid: python-command-injection
    os.system(options["user"])
    # todook: python-command-injection -- a write into one key taints the whole dict unless field_sensitive
    os.system(options["mode"])


def literal():
    pair = [input(), "ls"]
    # ruleid: python-command-injection
    os.system(pair[0])
    # todook: python-command-injection -- a list is one value: its constant element is tainted too
    os.system(pair[1])


def weak_update_keeps_taint():
    options = {"user": input()}
    options["user"] = "nobody"
    # todook: python-command-injection -- a subscript write is a weak update, so the earlier taint stays
    os.system(options["user"])


def attribute_write(config):
    config.command = input()
    # ruleid: python-command-injection
    os.system(config.command)


def appended():
    commands = []
    commands.append(input())
    # todoruleid: python-command-injection -- a method call does not define its receiver, so what append puts in is lost (#75)
    os.system(commands[0])


def iterated():
    for command in {"a": input()}.values():
        # ruleid: python-command-injection
        os.system(command)
