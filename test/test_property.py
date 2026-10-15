"""
Property tests: the analyses do not crash on generated Python programs
(Hypothesmith), nor on their prefixes, since the editor sends half-written code.

Pull requests run a few derandomized examples; the scheduled stress workflow
sets HYPOTHESIS_PROFILE=stress for many more.
"""

import os

import hypothesmith
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tree_climber.stress import STAGES, Work

settings.register_profile(
    "ci",
    max_examples=20,
    derandomize=True,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
settings.register_profile(
    "stress", max_examples=1000, deadline=None, suppress_health_check=list(HealthCheck)
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


def analyze_everything(source: str) -> None:
    work = Work("python", source)
    for stage in STAGES.values():
        stage(work)


@given(hypothesmith.from_grammar())
def test_programs_from_the_grammar(source):
    analyze_everything(source)


@given(hypothesmith.from_node())
def test_programs_from_syntax_trees(source):
    analyze_everything(source)


@given(hypothesmith.from_node(), st.data())
def test_prefixes_of_programs(source, data):
    cut = data.draw(st.integers(0, len(source)))
    analyze_everything(source[:cut])
