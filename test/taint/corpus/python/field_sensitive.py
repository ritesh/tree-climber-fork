"""
The containers.py shapes with `field_sensitive`: a write into a constant key
or an attribute taints only that field, other fields stay clean, and earlier
fields are kept across writes to others; a read of the whole value is
tainted when any field is.

taint-options: field_sensitive
"""

import os


def subscript_write():
    options = {}
    options["user"] = input()
    # ruleid: python-command-injection
    os.system(options["user"])
    # ok: python-command-injection
    os.system(options["mode"])


def overwritten_field():
    options = {}
    options["user"] = input()
    options["user"] = "nobody"
    # todook: python-command-injection -- a field write is still a weak update, so the field keeps its earlier taint
    os.system(options["user"])


def whole_value():
    options = {}
    options["user"] = input()
    # ruleid: python-command-injection
    os.system(str(options))


def attributes(config):
    config.command = input()
    config.mode = "fast"
    # ruleid: python-command-injection
    os.system(config.command)
    # ok: python-command-injection
    os.system(config.mode)


def passed_to_a_method():
    request = Request()
    request.path = input()
    request.run()


class Request:
    def run(self):
        # ruleid: python-command-injection
        os.system(self.path)
        # ok: python-command-injection
        os.system(self.method)


def variable_key(key):
    options = {}
    options[key] = input()
    # ruleid: python-command-injection
    os.system(options["mode"])


def nested(config):
    config.items[0] = input()
    # todook: python-command-injection -- only the first level is tracked: a write to config.items[0] taints all of config.items
    os.system(config.items[1])
