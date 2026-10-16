"""
Flows through containers, with the default settings: a write into a
subscript or attribute, or a call to a mutating method (`append`, `extend`,
`add`, `update`...), taints the whole value (weak update, the earlier taint is
kept), and reads of any element are tainted. A method that is not on the list,
or a receiver that is a call result, does not taint it. field_sensitive.py
runs the subscript and attribute shapes with `field_sensitive`.
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
    # ruleid: python-command-injection
    os.system(commands[0])


def extended():
    words = ["ls"]
    words.extend(input().split())
    # ruleid: python-command-injection
    os.system(" ".join(words))


def updated():
    env = {"HOME": "/tmp"}
    env.update(PATH=input())
    # ruleid: python-command-injection
    os.system(env["PATH"])


def added_to_an_attribute(self):
    self.hosts.add(input())
    # ruleid: python-command-injection
    os.system(" ".join(self.hosts))


def kept_across_a_clean_append():
    commands = [input()]
    commands.append("true")
    # ruleid: python-command-injection
    os.system(commands[0])


def other_methods():
    commands = []
    commands.count(input())
    # ok: python-command-injection
    os.system(" ".join(commands))


def receiver_is_a_call(table):
    table.get("commands").append(input())
    # todoruleid: python-command-injection -- only a receiver read by name is updated, not one a call returns (table.get(...))
    os.system(" ".join(table["commands"]))


registry = []


def register():
    registry.append(input())


def run_registered():
    # ruleid: python-command-injection
    os.system(registry[0])


def iterated():
    for command in {"a": input()}.values():
        # ruleid: python-command-injection
        os.system(command)
