"""
Implicit flows with `implicit_flows`: what is defined or returned under a
condition, loop or `match` that reads a tainted value is tainted, through
nested branches. A sink call under such a condition is not tainted by it, and
exceptions are not implicit flows.

taint-options: implicit_flows
"""

import os


def branch():
    if input() == "debug":
        flags = "-v"
    else:
        flags = "-q"
    # ruleid: python-command-injection
    os.system("make " + flags)


def nested(level):
    choice = input()
    if level > 1:
        if choice == "a":
            target = "all"
        else:
            target = "clean"
        # ruleid: python-command-injection
        os.system("make " + target)


def loop():
    count = 0
    while input() != "stop":
        count = count + 1
    # ruleid: python-command-injection
    os.system("echo " + str(count))


def returned():
    return "yes" if input() else "no"


def caller():
    # ruleid: python-command-injection
    os.system(returned())


def sink_under_the_branch():
    if input() == "go":
        # ok: python-command-injection
        os.system("make")


def defined_before_the_branch():
    flags = "-q"
    if input():
        pass
    # ok: python-command-injection
    os.system("make " + flags)
